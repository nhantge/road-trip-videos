#!/usr/bin/env python3
"""Render a road trip episode from a route file.

    python3 scripts/make_video.py routes/denver-to-ouray.toml

Writes out/<route>/<route>.mp4 (1080p30) plus thumbnail.jpg, description.txt
(chapters, itinerary, photo credits), captions.srt, voiceover_script.md and timeline.json.
"""

import argparse
import json
import multiprocessing as mp
import os
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from roadtrip import audio, describe, photos, style, thumbnail  # noqa: E402
from roadtrip.route import load_route  # noqa: E402
from roadtrip.scenes import Renderer  # noqa: E402
from roadtrip.terrain import Terrain  # noqa: E402
from roadtrip.timeline import layout  # noqa: E402

_renderer = None  # set before the worker pool forks, so workers share it


def _render(t):
    return _renderer.frame(t).tobytes()


def main():
    global _renderer
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("route", help="route file, e.g. routes/denver-to-ouray.toml")
    ap.add_argument("--out", help="output folder (default out/<route>)")
    ap.add_argument("--workers", type=int, default=os.cpu_count() or 2, help="render processes")
    ap.add_argument("--no-fetch", action="store_true", help="don't download missing stop photos")
    ap.add_argument("--no-voiceover", action="store_true", help="ignore recorded voiceover clips")
    ap.add_argument("--offline", action="store_true", help="use only cached terrain tiles")
    ap.add_argument("--stills", action="store_true", help="write a PNG per segment instead of the video")
    ap.add_argument("--photo-sheets", action="store_true",
                    help="write a contact sheet of each stop's photos (for choosing `photos = [...]`) and exit")
    ap.add_argument("--crf", type=int, default=19, help="x264 quality (lower is better, default 19)")
    ap.add_argument("--audio-only", action="store_true", help="write just the soundtrack (soundtrack.wav), to check the mix")
    args = ap.parse_args()

    route = load_route(args.route)
    out = Path(args.out) if args.out else REPO_ROOT / "out" / route.slug
    out.mkdir(parents=True, exist_ok=True)
    photos.ensure_photos(route, fetch=not args.no_fetch)
    if args.photo_sheets:
        for st in route.stops:
            for item in (st, *st.sights):
                folder = photos.folder_for(item.photo_query)
                path = photos.contact_sheet(item, out / "photos" / f"{st.index + 1}-{folder.name}.jpg")
                print(path or f"{item.name}: no photos in {folder}")
        return

    terrain = Terrain(REPO_ROOT / ".cache" / "terrain", offline=args.offline)
    route.build(terrain)
    brand = audio.load_brand()
    brand["voice"] = {**brand.get("voice", {}), **route.voice}
    segs, total, notes = layout(route, use_voiceover=not args.no_voiceover, voice=brand["voice"])
    for note in notes:
        print(f"warning: {note}", file=sys.stderr)
    sting = audio.BRAND_DIR / brand["intro_sting"] if brand.get("intro_sting") else None
    if sting and not sting.exists():
        print(f"warning: intro sting {sting} not found; skipping it", file=sys.stderr)
        sting = None
    outro = audio.BRAND_DIR / brand["outro_music"] if brand.get("outro_music") else None
    if outro and not outro.exists():
        print(f"warning: outro music {outro} not found; skipping it", file=sys.stderr)
        outro = None
    bed = audio.BRAND_DIR / brand["music_bed"] if brand.get("music_bed") else None
    if bed and not bed.exists():
        print(f"warning: music bed {bed} not found; skipping it", file=sys.stderr)
        bed = None
    sting_dur = audio.media_duration(sting) if sting else 0.0
    full = sting_dur + total

    voiced = sum(1 for s in segs if s.vo_path)
    print(f"{route.title}: {route.total_miles:.0f} miles, {len(route.stops)} stops, "
          f"{full:.1f} s ({voiced}/{len(segs)} segments voiced)")
    for st in route.stops:
        picked = photos.pick_photos(st)
        if not picked:
            print(f"  {st.name}: no usable photos, using illustrated placeholder", file=sys.stderr)

    (out / "description.txt").write_text(describe.description(route, segs, sting_dur, brand))
    (out / "captions.srt").write_text(describe.srt(route, segs, sting_dur))
    (out / "voiceover_script.md").write_text(describe.voiceover_script(route, segs, sting_dur))
    (out / "timeline.json").write_text(json.dumps({
        "sting_seconds": round(sting_dur, 3), "total_seconds": round(full, 3),
        "segments": [{"id": s.id, "start": round(sting_dur + s.start, 3), "duration": round(s.dur, 3),
                      "narration": s.narration, "voiceover": s.vo_path.name if s.vo_path else None}
                     for s in segs]}, indent=2) + "\n")

    thumbnail.render(route, out / "thumbnail.jpg")

    soundtrack = out / "soundtrack.wav"
    mix_args = (full, sting, sting_dur, outro, float(brand.get("outro_seconds", 10)), segs,
                bed, float(brand.get("music_bed_volume", 0.16)))
    if args.audio_only:
        audio.mix(soundtrack, *mix_args)
        print(f"wrote {soundtrack.relative_to(REPO_ROOT)}")
        return

    t0 = time.time()
    _renderer = Renderer(route, segs, terrain)
    print(f"map built in {time.time() - t0:.0f} s")

    if args.stills:
        for seg in segs:
            t = seg.start + min(seg.dur * 0.7, seg.dur - 0.1)
            _renderer.frame(t).save(out / f"still-{seg.id}.png")
            if seg.id == "intro":  # the title card comes first, before the stats
                _renderer.frame(seg.start + 1.5).save(out / "still-title.png")
        print(f"stills in {out}")
        return

    audio.mix(soundtrack, *mix_args)

    video = out / f"{route.slug}.mp4"
    n = int(round(total * style.FPS))
    inputs, filters = [], []
    if sting:
        inputs += ["-i", str(sting)]
        filters.append(f"[0:v]scale={style.W}:{style.H}:force_original_aspect_ratio=decrease,"
                       f"pad={style.W}:{style.H}:(ow-iw)/2:(oh-ih)/2,fps={style.FPS},format=yuv420p,setsar=1[v0]")
    k = len(inputs) // 2
    inputs += ["-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{style.W}x{style.H}", "-r", str(style.FPS), "-i", "pipe:0"]
    filters.append(f"[{k}:v]format=yuv420p,setsar=1[v1]")
    filters.append("[v0][v1]concat=n=2:v=1:a=0[v]" if sting else "[v1]null[v]")
    inputs += ["-i", str(soundtrack)]
    cmd = ["ffmpeg", "-y", "-v", "error", "-stats", *inputs, "-filter_complex", ";".join(filters),
           "-map", "[v]", "-map", f"{k + 1}:a", "-c:v", "libx264", "-preset", "medium", "-crf", str(args.crf),
           "-pix_fmt", "yuv420p", "-profile:v", "high", "-c:a", "aac", "-b:a", "192k",
           "-movflags", "+faststart", "-shortest", str(video)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    times = [i / style.FPS for i in range(n)]
    t0 = time.time()
    ctx = mp.get_context("fork")
    with ctx.Pool(max(1, args.workers)) as pool:
        for i, frame in enumerate(pool.imap(_render, times, chunksize=8)):
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
