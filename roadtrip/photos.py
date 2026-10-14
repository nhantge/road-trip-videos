"""Stop photos: fetched with scripts/fetch_photos.py into images/<slug>/, picked per
stop, and credited in the YouTube description and on screen."""

import importlib.util
import json
import os
import sys

from PIL import Image, ImageOps

from .style import REPO_ROOT

IMAGES = REPO_ROOT / "images"
PER_STOP = 2


def _fetcher():
    spec = importlib.util.spec_from_file_location("fetch_photos", REPO_ROOT / "scripts" / "fetch_photos.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def folder_for(query):
    return IMAGES / _fetcher().slugify(query)


def ensure_photos(route, fetch=True, count=5):
    """Run fetch_photos for any stop whose folder has no credits.json yet."""
    missing = [s.photo_query for s in route.stops if not (folder_for(s.photo_query) / "credits.json").exists()]
    if not missing or not fetch:
        return
    mod = _fetcher()
    key = os.environ.get("PIXABAY_API_KEY", "")
    sources = {"wikimedia", "pixabay"} if key else {"wikimedia"}
    for query in dict.fromkeys(missing):
        print(f"fetching photos for {query!r}")
        try:
            mod.fetch_place(query, sources, count, 1280, key)
        except OSError as err:
            print(f"  could not fetch photos for {query!r}: {err}", file=sys.stderr)


def pick_photos(stop, limit=PER_STOP):
    """[(path, credit_entry)] for a stop: pinned `photos` first, else the best landscape shots."""
    folder = folder_for(stop.photo_query)
    credits_path = folder / "credits.json"
    entries = json.loads(credits_path.read_text()) if credits_path.exists() else []
    by_file = {e["file"]: e for e in entries}
    chosen = []
    if stop.photos:
        for name in stop.photos:
            path = folder / name if "/" not in name else REPO_ROOT / name
            if path.exists():
                chosen.append((path, by_file.get(path.name, {"file": path.name})))
            else:
                print(f"  {stop.name}: pinned photo {name} not found", file=sys.stderr)
        return chosen[:limit] if limit else chosen
    # Wikimedia results are tagged to the place; Pixabay keyword hits often aren't
    # (search "Monarch Pass" and you get butterflies), so they only fill gaps.
    ranked = sorted(entries, key=lambda e: e.get("source") == "pixabay")
    for entry in ranked:
        path = folder / entry["file"]
        if not path.exists():
            continue
        try:
            with Image.open(path) as im:
                w, h = im.size
        except OSError:
            continue
        if w >= 900 and w / h >= 1.3:
            chosen.append((path, entry))
        if len(chosen) == limit:
            break
    return chosen


def load_cover(path, size):
    """Photo cropped to fill size, a little oversized so it can drift (Ken Burns)."""
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        w, h = int(size[0] * 1.12), int(size[1] * 1.12)
        return ImageOps.fit(im, (w, h), Image.LANCZOS, centering=(0.5, 0.45))


def short_credit(entry):
    """One-line on-screen credit, e.g. 'Photo: Jane Doe / CC BY-SA 4.0'."""
    if not entry or "author" not in entry:
        return ""
    author = entry["author"].split("\n")[0][:40]
    if entry.get("source") == "pixabay":
        return f"Photo: {author} / Pixabay"
    return f"Photo: {author} / {entry.get('license', '')}".strip(" /")


def contact_sheet(stop, out_path):
    """Grid of every downloaded photo for a stop with file names, for choosing `photos = [...]`."""
    from PIL import ImageDraw
    from .style import font
    folder = folder_for(stop.photo_query)
    files = sorted(p for p in folder.glob("*") if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"))
    if not files:
        return None
    cols, tw, th = 4, 480, 320
    sheet = Image.new("RGB", (cols * tw, -(-len(files) // cols) * th), (12, 16, 22))
    d = ImageDraw.Draw(sheet)
    for i, path in enumerate(files):
        with Image.open(path) as im:
            im = ImageOps.exif_transpose(im).convert("RGB")
            size = im.size
            im.thumbnail((tw - 8, th - 40))
            x, y = (i % cols) * tw + 4, (i // cols) * th + 4
            sheet.paste(im, (x, y))
        d.text((x + 4, y + th - 30), f"{path.name}  {size[0]}x{size[1]}", font=font("semibold", 16), fill=(240, 240, 240))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path, quality=85)
    return out_path
