# road-trip-videos
images for road trip videos

## Fetching photos

`scripts/fetch_photos.py` searches Wikimedia Commons and Pixabay by place name and
downloads the results into `images/<place-slug>/`. Each folder gets a `credits.json`
listing every file's source page, author, license and a ready-to-paste attribution line.

```sh
export PIXABAY_API_KEY=...        # optional; without it only Wikimedia is searched
python3 scripts/fetch_photos.py "Grand Canyon" "Monument Valley" --count 5
```

Options: `--source wikimedia|pixabay|both` (default both), `--count N` per source
per place (default 5), `--width PX` for Wikimedia thumbnails (default 1920).
Re-running skips images already listed in `credits.json`.

Licenses differ: many Wikimedia images are CC BY / CC BY-SA and **require attribution**
(check `attribution_required`); Pixabay images don't, but crediting them is good practice.
Put the `attribution` lines in your video descriptions.
