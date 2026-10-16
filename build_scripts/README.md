# build_video.py (Drive "Build Scripts" copy)

This is the single-file San Juan Skyway template from `Road Trip Assets/Build Scripts/` in Google Drive. It now has
the vertical social export from `Shorts & Social Export Spec.md`.

```
python3 build_video.py "../Videos/San Juan Skyway/san-juan-skyway.mp4"     # 16:9 video, then the social export
python3 build_video.py out.mp4 --social-only                                # social export only
python3 build_video.py out.mp4 --no-social                                  # 16:9 video only
```

Next to the 16:9 render it writes:

| File | What |
|---|---|
| `<trip>_short1_numbers.mp4` | By the Numbers, about 20 s |
| `<trip>_short2_route.mp4` | Route fly-through, 45–58 s |
| `<trip>_short3_<stop>.mp4` | Best stop, 30–45 s |
| `<trip>_pin.png` | Pinterest pin, 1000x1500 |
| `<trip>_chapters.txt` | YouTube chapters for the 16:9 video |

All clips are 1080x1920 at 30 fps, H.264 (CRF 20) with AAC audio at -14 LUFS. The last 2 s of each is the end slate.

Inputs, looked up in Road Trip Assets (the folder above `Build Scripts/`, or `RTA_ROOT`):

- `Photos/<Trip>/<Stop>/`: photos for Short 3 and the pin, used in file-name order (`PHOTOS_DIR` overrides
  `Photos/`). With no photos the illustrated placeholder is used.
- `Music/`: the first file with "bed" in its name, otherwise the first audio file (`MUSIC` overrides). With no
  music the clips get a silent track.
- `Voiceover/<Trip>/<trip>_short1.mp3` (or `short2`, `short3`): optional narration, mixed over the music at 0:00.3.

New TRIP keys: `state`, `best_stop` (defaults to the stop with the most rows), `short_hooks` (per-stop one-liners
for Short 2; falls back to the first SEE/EAT row) and `pin_hook` (falls back to the tagline).

YouTube chapters must start at 0:00, and each must be at least 10 s long. So a chapter that would start too soon
moves later within its own section, or is folded into the chapter before it. That is why the San Juan Skyway gets
"0:00 Intro & By the Numbers" and "0:10 Durango".

The test outputs are in `examples/san-juan-skyway-social/`. The Ouray photos in Short 3 and the pin are Pixabay
images (Pixabay Content License, no attribution required): 670527, 669467 and 669432 by psaudio, and 1679707 by 12019.
