#!/usr/bin/env python3
"""Render a vertical short (1080x1920, under a minute) from an episode's route file.

    python3 scripts/make_short.py routes/silverton-to-durango.toml

Uses the episode's own voiceover clips (hook, finale, end), photos and map, so it needs
no new narration. Writes out/<route>/short/<route>-short.mp4 and short.txt (title,
caption, hashtags and photo credits to paste when posting).
"""

import argparse
import multiprocessing as mp
import os
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from roadtrip import audio, describe, shorts, style  # noqa: E402
from roadtrip.route import load_route  # noqa: E402
from roadtrip.terrain import Terrain  # noqa: E402

_renderer = None  # set before the worker pool forks, so workers share it


def _render(t):
    return _renderer.frame(t).tobytes()


def main():
    global _renderer
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("route", help="route file, e.g. routes/denver-to-ouray.toml")
    ap.add_argument("--out", help="output folder (default out/<route>/short)")
    ap.add_argument("--workers", type=int, default=os.cpu_count() or 2, help="render processes")
    ap.add_argument("--no-voiceover", action="store_true", help="ignore recorded voiceover clips")
    ap.add_argument("--offline", action="store_true", help="use only cached terrain tiles")
    ap.add_argument("--stills", action="store_true", help="write a few PNGs instead of the video")
    ap.add_argument("--crf", type=int, default=21, help="x264 quality (lower is better, default 21)")
    args = ap.parse_args()

    route = load_route(args.route)
    out = Path(args.out) if args.out else REPO_ROOT / "out" / route.slug / "short"
    out.mkdir(parents=True, exist_ok=True)
    terrain = Terrain(REPO_ROOT / ".cache" / "terrain", offline=args.offline)
    route.build(terrain)
    brand = audio.load_brand()
    brand["voice"] = {**brand.get("voice", {}), **route.voice}
    segs, total, notes = shorts.short_layout(route, use_voiceover=not args.no_voiceover, voice=brand["voice"])
    for note in notes:
        print(f"warning: {note}", file=sys.stderr)
    print(f"{route.title} short: {total:.1f} s ({', '.join(f'{s.id} {s.dur:.1f}s' for s in segs)})")

    _renderer = shorts.ShortRenderer(route, segs, terrain)
    credits = [c for c in (describe.short_attribution(e) for e in _renderer.used_photos()) if c]
    (out / "short.txt").write_text(shorts.caption_text(route, brand, total, credits))

    if args.stills:
        for seg in segs:
            for frac in (0.15, 0.5, 0.9):
                t = seg.start + seg.dur * frac
                _renderer.frame(t).save(out / f"still-{seg.id}-{int(frac * 100):02d}.png")
        print(f"stills in {out}")
        return

    def brand_file(key):
        path = audio.BRAND_DIR / brand[key] if brand.get(key) else None
        return path if path and path.exists() else None

    soundtrack = out / "soundtrack.wav"
    audio.mix(soundtrack, total, None, 0.0, brand_file("outro_music"), float(brand.get("outro_seconds", 10)),
              segs, brand_file("music_bed"), float(brand.get("music_bed_volume", 0.16)))

    video = out / f"{route.slug}-short.mp4"
    n = int(round(total * style.FPS))
    cmd = ["ffmpeg", "-y", "-v", "error", "-stats",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{shorts.SW}x{shorts.SH}", "-r", str(style.FPS), "-i", "pipe:0",
           "-i", str(soundtrack), "-map", "0:v", "-map", "1:a",
           "-c:v", "libx264", "-preset", "medium", "-crf", str(args.crf), "-pix_fmt", "yuv420p",
           "-profile:v", "high", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-shortest", str(video)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    t0 = time.time()
    with mp.get_context("fork").Pool(max(1, args.workers)) as pool:
        for i, frame in enumerate(pool.imap(_render, [i / style.FPS for i in range(n)], chunksize=8)):
            proc.stdin.write(frame)
            if i % 300 == 0:
                print(f"  frame {i}/{n} ({time.time() - t0:.0f} s)", file=sys.stderr)
    proc.stdin.close()
    if proc.wait():
        sys.exit("ffmpeg failed")
    soundtrack.unlink()
    print(f"wrote {video.relative_to(REPO_ROOT)} in {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()
