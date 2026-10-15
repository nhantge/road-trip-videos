#!/usr/bin/env python3
"""Search Wikimedia Commons, Flickr and Pixabay for photos of a place and download them.

Images land in images/<place-slug>/ alongside a credits.json that records the
source, license and author of every file, plus a ready-to-paste attribution line.

Usage:
    python3 scripts/fetch_photos.py "Grand Canyon"
    python3 scripts/fetch_photos.py "Route 66" "Monument Valley" --count 8 --source wikimedia

    python3 scripts/fetch_photos.py "Molas Pass" --source flickr --lat 37.7406 --lon -107.6969

Pixabay needs PIXABAY_API_KEY and Flickr needs FLICKR_API_KEY in the environment; sources
without a key are skipped. Flickr searches near --lat/--lon when given, which finds photos
taken at the place itself, and only returns licenses that allow reuse with edits.
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
FLICKR_API = "https://api.flickr.com/services/rest/"
# Flickr license ids that allow commercial reuse with edits (we crop and pan).
FLICKR_LICENSES = {
    "4": ("CC BY 2.0", "https://creativecommons.org/licenses/by/2.0/", True),
    "5": ("CC BY-SA 2.0", "https://creativecommons.org/licenses/by-sa/2.0/", True),
    "7": ("No known copyright restrictions", "https://www.flickr.com/commons/usage/", False),
    "8": ("United States Government Work", "http://www.usa.gov/copyright.shtml", False),
    "9": ("CC0 1.0", "https://creativecommons.org/publicdomain/zero/1.0/", False),
    "10": ("Public Domain Mark 1.0", "https://creativecommons.org/publicdomain/mark/1.0/", False),
    "11": ("CC BY 4.0", "https://creativecommons.org/licenses/by/4.0/", True),
    "12": ("CC BY-SA 4.0", "https://creativecommons.org/licenses/by-sa/4.0/", True),
}
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


def search_flickr(place, count, api_key, lat=None, lon=None, radius_km=1.0):
    """Flickr photos of a place: near lat/lon when given (best), else by keyword."""
    def search(**extra):
        data = json.loads(http_get(FLICKR_API, {
            "method": "flickr.photos.search", "api_key": api_key, "format": "json", "nojsoncallback": 1,
            "license": ",".join(FLICKR_LICENSES), "media": "photos", "content_type": 1, "safe_search": 1,
            "sort": "interestingness-desc", "per_page": max(count * 3, 10),
            "extras": "license,owner_name,url_k,url_l,o_dims", **extra,
        }))
        if data.get("stat") != "ok":
            raise urllib.error.URLError(f"Flickr: {data.get('message', data)}")
        return data["photos"]["photo"]
    if lat is not None and lon is not None:
        geo = {"lat": lat, "lon": lon, "radius": radius_km, "radius_units": "km"}
        hits = search(text=place, **geo)
        if len(hits) < count:  # fill with anything shot right there, still sorted by interest
            seen = {h["id"] for h in hits}
            hits += [h for h in search(**geo) if h["id"] not in seen]
    else:
        hits = search(text=place)
    results = []
    for hit in hits:
        url = hit.get("url_k") or hit.get("url_l")
        if not url or hit["license"] not in FLICKR_LICENSES:
            continue
        name, license_url, required = FLICKR_LICENSES[hit["license"]]
        results.append({
            "source": "flickr",
            "id": hit["id"],
            "title": hit.get("title") or place,
            "download_url": url,
            "page_url": f"https://www.flickr.com/photos/{hit['owner']}/{hit['id']}/",
            "author": hit.get("ownername") or "Unknown",
            "license": name,
            "license_url": license_url,
            "attribution_required": required,
        })
        if len(results) == count:
            break
    return results


def extension_for(url):
    ext = Path(urllib.parse.urlparse(url).path).suffix.lower()
    return ".jpg" if ext in ("", ".jpeg") else ext


def fetch_place(place, sources, count, width, pixabay_key, dest=None, flickr_key="", lat=None, lon=None, radius_km=1.0):
    folder = Path(dest or REPO_ROOT / "images") / slugify(place)
    folder.mkdir(parents=True, exist_ok=True)
    credits_path = folder / "credits.json"
    credits = json.loads(credits_path.read_text()) if credits_path.exists() else []
    known = {entry["file"] for entry in credits}

    candidates = []
    if "wikimedia" in sources:
        candidates += search_wikimedia(place, count, width)
    if "flickr" in sources:
        candidates += search_flickr(place, count, flickr_key, lat, lon, radius_km)
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
        credits_path.write_text(json.dumps(credits, indent=2, ensure_ascii=False) + "\n")  # keep progress if stopped
        added += 1
        print(f"  {filename}  [{item['license']}] {item['author']}")
        if item["source"] == "wikimedia":
            time.sleep(3)  # stay well under Wikimedia's rate limits (shared IPs get throttled)

    credits_path.write_text(json.dumps(credits, indent=2, ensure_ascii=False) + "\n")
    print(f"{place}: {added} new image(s) in {folder}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("places", nargs="+", help="place names to search for")
    parser.add_argument("--count", type=int, default=5, help="images per source per place (default 5)")
    parser.add_argument("--source", choices=["all", "both", "wikimedia", "flickr", "pixabay"], default="all",
                        help="where to search (default all; both = wikimedia and pixabay)")
    parser.add_argument("--lat", type=float, help="search Flickr near this latitude (with --lon)")
    parser.add_argument("--lon", type=float, help="search Flickr near this longitude (with --lat)")
    parser.add_argument("--radius", type=float, default=1.0, help="Flickr search radius in km (default 1)")
    parser.add_argument("--width", type=int, default=1920, help="Wikimedia thumbnail width (default 1920)")
    parser.add_argument("--dest", help="folder to download into instead of images/ (e.g. to vet photos first)")
    args = parser.parse_args()

    sources = {"all": {"wikimedia", "flickr", "pixabay"}, "both": {"wikimedia", "pixabay"}}.get(args.source, {args.source})
    keys = {"pixabay": os.environ.get("PIXABAY_API_KEY", ""), "flickr": os.environ.get("FLICKR_API_KEY", "")}
    for source, key in keys.items():
        if source in sources and not key:
            if args.source == source:
                parser.error(f"{source.upper()}_API_KEY is not set")
            print(f"{source.upper()}_API_KEY not set; skipping {source.title()}", file=sys.stderr)
            sources.discard(source)

    for place in args.places:
        fetch_place(place, sources, args.count, args.width, keys["pixabay"], args.dest,
                    keys["flickr"], args.lat, args.lon, args.radius)


if __name__ == "__main__":
    main()
