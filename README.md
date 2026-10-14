# road-trip-videos

Images and a video generator for road trip episodes. Give it a route (start, stops,
end) and it renders a 1080p MP4: an animated map that follows the drive, a running
mile counter, an elevation profile, captions and photo cards for each stop, voiceover,
a branded intro sting, a music bed and outro music, and an end card. It also writes
the thumbnail, the YouTube description (chapters, itinerary, photo credits) and a
captions file.

Demo: [`examples/denver-to-ouray/`](examples/denver-to-ouray/) (US 285 and US 50 over
the Continental Divide, narrated by the ElevenLabs voice "Sadie").

## Quick start

```sh
pip install -r requirements.txt          # Pillow and numpy; ffmpeg must be on PATH
export PIXABAY_API_KEY=...               # optional, for extra photos
python3 scripts/make_video.py routes/denver-to-ouray.toml
```

Output lands in `out/<route>/`:

| File | What it is |
|---|---|
| `<route>.mp4` | the episode, 1920x1080, 30 fps, H.264 + AAC, audio at -14 LUFS (YouTube's level) |
| `thumbnail.jpg` | 1280x720 YouTube thumbnail: stop photo, headline, mini route map |
| `description.txt` | YouTube description: chapters, the route with mileage and drive times, tips, photo credits |
| `captions.srt` | captions timed to the narration, for upload to YouTube |
| `voiceover_script.md` | every narration line with its segment id and start time |
| `timeline.json` | segment start times and durations |

Useful flags: `--stills` (one PNG per segment instead of the video, for a quick look),
`--audio-only` (just the soundtrack, to check the mix), `--crf N` (video quality),
`--photo-sheets` (contact sheets of each stop's photos, for picking `photos = [...]`),
`--no-voiceover`, `--no-fetch`, `--offline` (cached terrain only), `--workers N`.

## Making a new episode

1. **Write a route file** in `routes/`. Copy `routes/denver-to-ouray.toml` and edit it.
2. **Get photos.** The first render runs `scripts/fetch_photos.py` for any stop without
   a photo folder. Then run with `--photo-sheets`, look at `out/<route>/photos/`, and
   pin the shots you want with `photos = ["wikimedia-123.jpg", ...]`. Check what you
   pin: keyword searches return the wrong place surprisingly often (searching "Monarch
   Pass" on Pixabay returns butterflies). Unpinned stops use Wikimedia photos first.
3. **Record the voiceover** (see below), or skip it and render with room left for one.
4. **Render**, check the stills or the MP4, and paste `description.txt` into YouTube.

### Route file

```toml
title = "Denver to Ouray"           # shown on the title card, HUD and end card
series = "Colorado Road Trips"      # kicker above the title
region = "Central Colorado"         # under the title in the HUD
days = "2 to 3"
best_season = "Late June to early October"
hook = ["Over the Continental Divide at 11,312 ft : Monarch Pass", ...]  # "line : stop"
tips = ["Fill up in Buena Vista...", ...]                               # planner card

[inset]                             # the locator map, top right
name = "Colorado"
bounds = [-109.05, 37.0, -102.04, 41.0]          # west, south, east, north
city = { name = "Denver", lat = 39.7392, lon = -104.9903 }

[thumbnail]                         # thumbnail.jpg
text = ["305 MILES", "OVER THE DIVIDE"]   # line 1 white, line 2 orange; 2-5 words
stop = "Blue Mesa Reservoir"        # whose photo (default: the highest stop)
photo = 1                           # which of its photos; also zoom = 1.3, focus = 0.8

[up_next]                           # end card
title = "The Million Dollar Highway"
subtitle = "Ouray to Silverton"
miles = 24

[[stops]]
name = "Monarch Pass"
lat = 38.4967
lon = -106.3253
elevation_ft = 11312                # optional; otherwise read from terrain data
kind = "pass"                       # "town" (default) or "pass"
tag = "CONTINENTAL DIVIDE"          # chip on the photo
photo_query = "Monarch Pass"        # images/<slug>/ folder; defaults to the name
photos = ["wikimedia-5767514.jpg"]  # optional pinned photos, in order
caption = "Monarch Pass: 11,312 ft. ..."   # on the map at the stop
fact = "Water on the east side ..."        # "Did you know?" card
[stops.info]                        # rows on the stop card, in order
"SEE" = "..."
"DO" = "..."
"TIP" = "..."
```

The leg that arrives at a stop is described on that stop:

| Key | Meaning |
|---|---|
| `road` | highway label on the map and in the next-stop panel, e.g. `"US 50"` |
| `miles` | real road miles for the leg (the counter is scaled to match) |
| `drive_time` | e.g. `"1 hr 15 min"`; estimated at 45 mph if left out |
| `via` | points the line passes through: `[lat, lon]` to shape it, or `{ name = "Fairplay", lat = ..., lon = ..., kind = "town" }` to also label a town or pass (`elevation_ft` optional) |
| `drive_caption` | caption on the map during the drive |
| `drive_fact` | "On this stretch" card during the drive |

There is no routing service in the loop, so the map line is a smooth curve through the
stops and `via` points: add a point at each town and wherever the road bends. Mileage
comes from `miles`, so the counter matches the real road even where the curve cuts a
corner. Elevations come from free terrain tiles and are pinned to any `elevation_ft`
you give, so the HUD, stop cards and profile always agree.

Narration is built from the captions and facts. To word a line differently, set
`narration` (stop), `drive_narration` (leg), or `[narration]` keys `hook`, `intro`,
`overview`, `finale`, `planner` and `end`.

## Voiceover

Each segment of the video has one narration line (see `out/<route>/voiceover_script.md`).
Clips go in `voiceover/<route>/<segment>.mp3` (or `.wav`/`.m4a`). When a clip exists its
segment stretches to fit it, so narration is never cut off; without clips the video
renders at default timings with the narration space left empty.

The channel voice is ElevenLabs **Sadie** (`bD9maNcCuQQS75DGuteM`), set in
`assets/brand/brand.json`. To generate a route's narration with it:

```sh
export ELEVENLABS_API_KEY=...
python3 scripts/make_voiceover.py routes/my-route.toml --dry-run   # lines and character count
python3 scripts/make_voiceover.py routes/my-route.toml             # records missing or changed lines
python3 scripts/make_voiceover.py routes/my-route.toml --only stop-3 --force
```

`voiceover/<route>/manifest.json` remembers the text each clip was recorded from; the
renderer warns when a line has changed since. You can also drop in your own recordings
with the same file names.

At render time, clips are tidied: pauses longer than `voice.max_pause` (0.45 s) are
shortened and the pace is lifted by `voice.tempo` (1.08, pitch unchanged). Sadie's
natural delivery is slow, and dead air loses viewers. Set `max_pause` to 0 and `tempo`
to 1.0 to use clips as recorded.

## Brand assets

`assets/brand/` holds what every episode shares:

- `intro_sting.mp4`: a 2.6 s logo sting with sound, played first
- `music_bed.m4a`: a quiet loop under the whole episode at `music_bed_volume`; it
  ducks about 10 dB whenever the narrator talks and hands over to the outro
- `outro_music.m4a`: music for the end; its last `outro_seconds` (10) play under the
  planner and end card, so the final chord lands on the last frame
- `brand.json`: channel name, tagline, the file names above, and the voice settings

Both media files are original and were synthesized by `scripts/make_brand_assets.py`
(no samples or licensed audio). Re-run it after changing the channel name or tagline
(`python3 scripts/make_brand_assets.py sting` rebuilds just the sting; `outro` and `bed`
work the same way), or replace any file with your own and every episode will use it.
The final mix is loudness-normalized to -14 LUFS, so swapped-in music needs no leveling.

## Publishing on YouTube

The generator doesn't upload; do this in YouTube Studio:

1. Upload `<route>.mp4`, set the title, and paste `description.txt` (YouTube builds
   chapters from its timestamps).
2. Upload `thumbnail.jpg` as the custom thumbnail.
3. Subtitles: upload `captions.srt` (English, "with timing").
4. End screen: add a Subscribe element and a video element over the last ~7 s; the
   end card leaves room for both on the left and right.

`examples/denver-to-ouray/UPLOAD.md` has the full checklist used for the demo.

## How an episode is laid out

1. Intro sting
2. "Coming up" hook: three photo cards teasing the best moments (from `hook`)
3. Title card, then "By the numbers": miles, elevation change, stops, driving hours,
   days, passes over 10,000 ft (all computed from the route)
4. Route overview: the whole map and the list of stops, then the camera flies to the start
5. For each stop: the drive (camera follows the car; next-stop panel with miles to go,
   drive time, an elevation chart of the leg and an "On this stretch" fact), then the
   stop (photo card, see/do/eat/stay rows, "Did you know?" fact)
6. Finale: zoom out to the whole route with trip totals
7. Trip planner: the itinerary with miles, elevations and leg drive times, plus tips
8. End card: subscribe and "Up next"

The look (dark map, HUD, inset, elevation strip, panel, stats and end cards) follows the
earlier San Juan Skyway demo.

## Fetching photos

`scripts/fetch_photos.py` searches Wikimedia Commons and Pixabay by place name and
downloads the results into `images/<place-slug>/`. Each folder gets a `credits.json`
listing every file's source page, author, license and a ready-to-paste attribution line.
`make_video.py` calls it for you and puts the credits for the photos it uses in
`description.txt`; it also prints a small credit on each photo.

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

## Layout of the repo

```
routes/            one .toml per episode
images/            downloaded photos + credits.json per place
voiceover/         narration clips per route
assets/brand/      intro sting, outro music, brand.json
assets/fonts/      Inter (SIL Open Font License)
roadtrip/          the generator (route, terrain, map, scenes, timeline, audio, description)
scripts/           make_video.py, make_voiceover.py, make_brand_assets.py, fetch_photos.py
examples/          rendered demo with its description and captions
tests/             python3 -m unittest discover tests
```

Terrain shading and elevations come from the AWS Terrain Tiles open dataset, cached in
`.cache/terrain/`. Rendering takes a few minutes for a 3-4 minute episode on 4 cores.
