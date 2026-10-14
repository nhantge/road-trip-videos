#!/usr/bin/env python3
"""Add your own photos to a place's folder so videos can use them.

    python3 scripts/add_photos.py "Molas Pass" ~/Pictures/molas1.jpg ~/Pictures/molas2.jpg --author "Nick"

Photos are resized to at most 1920 px wide, saved as images/<place-slug>/own-<name>.jpg
and recorded in credits.json (credited as "Photo: <author>"). Unpinned stops pick your
own photos before Wikimedia or Pixabay ones; pin them like any other with photos = [...].
"""

import argparse
import importlib.util
import json
import sys
from pathlib import Path

from PIL import Image, ImageOps

REPO_ROOT = Path(__file__).resolve().parent.parent


def slugify(text):
    spec = importlib.util.spec_from_file_location("fetch_photos", REPO_ROOT / "scripts" / "fetch_photos.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.slugify(text)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("place", help='place name, matching the stop\'s photo_query (e.g. "Molas Pass")')
    ap.add_argument("files", nargs="+", type=Path)
    ap.add_argument("--author", required=True, help="who took the photos, for the on-screen credit")
    ap.add_argument("--max-width", type=int, default=1920)
    args = ap.parse_args()

    folder = REPO_ROOT / "images" / slugify(args.place)
    folder.mkdir(parents=True, exist_ok=True)
    credits_path = folder / "credits.json"
    credits = json.loads(credits_path.read_text()) if credits_path.exists() else []
    for src in args.files:
        try:
            with Image.open(src) as im:
                im = ImageOps.exif_transpose(im).convert("RGB")
        except OSError as err:
            print(f"skipped {src}: {err}", file=sys.stderr)
            continue
        if im.width > args.max_width:
            im = im.resize((args.max_width, round(im.height * args.max_width / im.width)), Image.LANCZOS)
        name = f"own-{slugify(src.stem)}.jpg"
        im.save(folder / name, quality=90)
        credits = [c for c in credits if c["file"] != name]
        credits.append({"file": name, "place": args.place, "source": "own", "title": src.stem,
                        "author": args.author, "license": "All rights reserved",
                        "attribution_required": False, "attribution": f"Photo: {args.author}"})
        print(f"  {name}  {im.width}x{im.height}")
    credits_path.write_text(json.dumps(credits, indent=2, ensure_ascii=False) + "\n")
    print(f"{args.place}: {len(args.files)} photo(s) in {folder.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
