#!/usr/bin/env python3
"""Generate the voiceover for a route with ElevenLabs, one clip per video segment.

    export ELEVENLABS_API_KEY=...
    python3 scripts/make_voiceover.py routes/denver-to-ouray.toml            # missing/stale lines only
    python3 scripts/make_voiceover.py routes/denver-to-ouray.toml --dry-run  # show lines and cost
    python3 scripts/make_voiceover.py routes/denver-to-ouray.toml --only stop-3 --force

The voice and model come from assets/brand/brand.json ("voice"), so every episode
sounds the same. Clips land in voiceover/<route>/<segment>.mp3 with a manifest of the
text each was recorded from; make_video.py fits each segment to its clip and warns
when a line's text changed since it was recorded.
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from roadtrip.audio import load_brand  # noqa: E402
from roadtrip.route import load_route  # noqa: E402
from roadtrip.terrain import Terrain  # noqa: E402
from roadtrip.timeline import VO_DIR, build_segments, text_hash  # noqa: E402

API = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}?output_format=mp3_44100_128"


def synthesize(text, voice, key):
    body = json.dumps({"text": text, "model_id": voice.get("model_id", "eleven_v3")}).encode()
    req = urllib.request.Request(API.format(voice_id=voice["voice_id"]), data=body, method="POST",
                                 headers={"xi-api-key": key, "Content-Type": "application/json",
                                          "Accept": "audio/mpeg"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("route")
    ap.add_argument("--only", nargs="+", metavar="SEGMENT", help="segment ids to (re)record, e.g. hook stop-3")
    ap.add_argument("--force", action="store_true", help="re-record even if the clip is up to date")
    ap.add_argument("--dry-run", action="store_true", help="print the lines that would be recorded")
    args = ap.parse_args()

    route = load_route(args.route)
    voice = {**load_brand().get("voice", {}), **route.voice}
    # Narration quotes miles and elevations, so build the route (terrain is cached after the first run).
    route.build(Terrain(REPO_ROOT / ".cache" / "terrain"))
    segs = build_segments(route)
    folder = VO_DIR / route.slug
    manifest_path = folder / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}

    todo = []
    for seg in segs:
        if args.only and seg.id not in args.only:
            continue
        current = (folder / f"{seg.id}.mp3").exists() and manifest.get(seg.id) == text_hash(seg.narration)
        if current and not args.force:
            continue
        todo.append(seg)
    chars = sum(len(s.narration) for s in todo)
    print(f"{len(todo)} of {len(segs)} lines to record ({chars} characters) with "
          f"{voice.get('name', voice.get('voice_id'))} / {voice.get('model_id')}")
    for seg in todo:
        print(f"  [{seg.id}] {seg.narration}")
    if args.dry_run or not todo:
        return
    key = os.environ.get("ELEVENLABS_API_KEY")
    if not key:
        sys.exit("ELEVENLABS_API_KEY is not set")
    folder.mkdir(parents=True, exist_ok=True)
    manifest.setdefault("voice", f"{voice.get('name')} (ElevenLabs {voice.get('voice_id')})")
    manifest["model"] = voice.get("model_id")
    for seg in todo:
        try:
            audio = synthesize(seg.narration, voice, key)
        except urllib.error.HTTPError as err:
            sys.exit(f"{seg.id}: ElevenLabs returned {err.code}: {err.read()[:300]!r}")
        (folder / f"{seg.id}.mp3").write_bytes(audio)
        manifest[seg.id] = text_hash(seg.narration)
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
        print(f"  wrote {seg.id}.mp3")


if __name__ == "__main__":
    main()
