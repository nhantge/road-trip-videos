#!/usr/bin/env python3
"""Search Wikimedia Commons and Pixabay for photos of a place and download them.

Images land in images/<place-slug>/ alongside a credits.json that records the
source, license and author of every file, plus a ready-to-paste attribution line.

Usage:
    python3 scripts/fetch_photos.py "Grand Canyon"
    python3 scripts/fetch_photos.py "Route 66" "Monument Valley" --count 8 --source wikimedia

Pixabay needs PIXABAY_API_KEY in the environment; without it only Wikimedia is used.
"""

import argparse
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO_URL = "https://github.com/nhantge/road-trip-videos"
USER_AGENT = f"road-trip-videos/1.0 ({REPO_URL})"
REPO_ROOT = Path(__file__).resolve().parent.parent
WIKIMEDIA_API = "https://commons.wikimedia.org/w/api.php"
PIXABAY_API = "https://pixabay.com/api/"
MAX_RETRIES = 8
MAX_WAIT = 90  # seconds; Wikimedia may ask for 600 but often answers much sooner


def slugify(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "place"


def strip_html(text):
    return html.unescape(re.sub(r"<[^>]+>", "", text or "")).strip()


def http_get(url, params=None):
    """GET with a polite User-Agent, backing off on 429/5xx (Wikimedia rate-limits shared IPs)."""
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(MAX_RETRIES):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return response.read()
        except urllib.error.HTTPError as err:
            if (err.code != 429 and err.code < 500) or attempt == MAX_RETRIES - 1:
                raise
            retry_after = err.headers.get("Retry-After", "")
            delay = int(retry_after) if retry_after.isdigit() else 5 * 2**attempt
            delay = min(delay, MAX_WAIT)  # throttling is bursty; retrying sooner usually works
            print(f"  HTTP {err.code}, retrying in {delay}s", file=sys.stderr)
            time.sleep(delay)


def search_wikimedia(place, count, width):
    data = json.loads(http_get(WIKIMEDIA_API, {
        "action": "query",
        "format": "json",
        "generator": "search",
        "gsrsearch": f"{place} filetype:bitmap",
        "gsrnamespace": 6,
        "gsrlimit": count,
        "prop": "imageinfo",
        "iiprop": "url|extmetadata|mime",
        "iiurlwidth": width,
    }))
    pages = sorted(data.get("query", {}).get("pages", {}).values(), key=lambda p: p.get("index", 0))
    results = []
    for page in pages:
        info = page["imageinfo"][0]
        meta = info.get("extmetadata", {})
        field = lambda key: strip_html(meta.get(key, {}).get("value", ""))
        results.append({
            "source": "wikimedia",
            "id": str(page["pageid"]),
            "title": page["title"].removeprefix("File:"),
            "download_url": info.get("thumburl") or info["url"],
            "page_url": info["descriptionurl"],
            "author": field("Artist") or "Unknown",
            "license": field("LicenseShortName") or "See source page",
            "license_url": field("LicenseUrl"),
            "attribution_required": field("AttributionRequired") == "true",
        })
    return results


def search_pixabay(place, count, api_key):
    data = json.loads(http_get(PIXABAY_API, {
        "key": api_key,
        "q": place[:100],
        "image_type": "photo",
        "safesearch": "true",
        "per_page": max(3, min(count, 200)),  # Pixabay rejects per_page < 3
    }))
    return [{
        "source": "pixabay",
        "id": str(hit["id"]),
        "title": ", ".join(dict.fromkeys(t.strip() for t in hit.get("tags", "").split(","))),
        "download_url": hit["largeImageURL"],
        "page_url": hit["pageURL"],
        "author": hit["user"],
        "author_url": f"https://pixabay.com/users/{hit['user']}-{hit['user_id']}/",
        "license": "Pixabay Content License",
        "license_url": "https://pixabay.com/service/license-summary/",
        "attribution_required": False,
    } for hit in data.get("hits", [])[:count]]


def extension_for(url):
    ext = Path(urllib.parse.urlparse(url).path).suffix.lower()
    return ".jpg" if ext in ("", ".jpeg") else ext


def fetch_place(place, sources, count, width, pixabay_key):
    folder = REPO_ROOT / "images" / slugify(place)
    folder.mkdir(parents=True, exist_ok=True)
    credits_path = folder / "credits.json"
    credits = json.loads(credits_path.read_text()) if credits_path.exists() else []
    known = {entry["file"] for entry in credits}

    candidates = []
    if "wikimedia" in sources:
        candidates += search_wikimedia(place, count, width)
    if "pixabay" in sources:
        candidates += search_pixabay(place, count, pixabay_key)

    added = 0
    for item in candidates:
        filename = f"{item['source']}-{item['id']}{extension_for(item['download_url'])}"
        if filename in known:
            continue
        try:
            (folder / filename).write_bytes(http_get(item["download_url"]))
        except urllib.error.URLError as err:
            print(f"  skipped {item['page_url']}: {err}", file=sys.stderr)
            continue
        item.pop("download_url")
        if item["source"] == "pixabay":
            item["attribution"] = f"Image by {item['author']} from Pixabay ({item['page_url']})"
        else:
            license_part = f"{item['license']} ({item['license_url']})" if item["license_url"] else item["license"]
            item["attribution"] = f"\"{item['title']}\" by {item['author']}, {license_part}, via {item['page_url']}"
        credits.append({"file": filename, "place": place, **item})
        known.add(filename)
        added += 1
        print(f"  {filename}  [{item['license']}] {item['author']}")
        if item["source"] == "wikimedia":
            time.sleep(3)  # stay well under Wikimedia's rate limits (shared IPs get throttled)

    credits_path.write_text(json.dumps(credits, indent=2, ensure_ascii=False) + "\n")
    print(f"{place}: {added} new image(s) in {folder.relative_to(REPO_ROOT)}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("places", nargs="+", help="place names to search for")
    parser.add_argument("--count", type=int, default=5, help="images per source per place (default 5)")
    parser.add_argument("--source", choices=["both", "wikimedia", "pixabay"], default="both")
    parser.add_argument("--width", type=int, default=1920, help="Wikimedia thumbnail width (default 1920)")
    args = parser.parse_args()

    sources = {"wikimedia", "pixabay"} if args.source == "both" else {args.source}
    pixabay_key = os.environ.get("PIXABAY_API_KEY", "")
    if "pixabay" in sources and not pixabay_key:
        if args.source == "pixabay":
            parser.error("PIXABAY_API_KEY is not set")
        print("PIXABAY_API_KEY not set; using Wikimedia only", file=sys.stderr)
        sources.discard("pixabay")

    for place in args.places:
        fetch_place(place, sources, args.count, args.width, pixabay_key)


if __name__ == "__main__":
    main()
