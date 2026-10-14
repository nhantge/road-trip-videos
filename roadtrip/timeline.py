"""Narration script and the episode timeline.

Every segment has a narration line. When a recorded clip exists for a segment
(voiceover/<route>/<segment>.mp3, .wav or .m4a) the segment stretches to fit it,
so the voiceover never gets cut off. Without clips the default durations apply and
the video is laid out with room for a voiceover to be added later.
"""

import hashlib
import json
import re
import subprocess
from dataclasses import dataclass

from .style import REPO_ROOT, fmt_int

VO_DIR = REPO_ROOT / "voiceover"
VO_LEAD = 0.35   # seconds of air before a line starts
VO_TAIL = 0.6    # and after it ends
AUDIO_EXTS = (".mp3", ".wav", ".m4a")


@dataclass
class Segment:
    id: str
    kind: str            # hook, intro, overview, stop, drive, finale, planner, end
    min_dur: float
    narration: str
    stop: int | None = None
    start: float = 0.0
    dur: float = 0.0
    vo_path: object = None
    vo_dur: float = 0.0

    @property
    def end(self):
        return self.start + self.dur


def spoken(text):
    """Tidy on-screen text into something a TTS voice reads naturally."""
    text = re.sub(r"(\d)\s*ft\b", r"\1 feet", text)
    text = text.replace("&", "and").replace(" · ", ", ").replace("·", ",")
    return re.sub(r"\s+", " ", text).strip()


def hook_items(route):
    """[(line, stop_index or None)] from `hook = ["Line : Stop name", ...]`."""
    names = {s.name.lower(): s.index for s in route.stops}
    items = []
    for raw in route.hook:
        line, _, where = raw.partition(" : ")
        items.append((line.strip(), names.get(where.strip().lower())))
    return items


def build_segments(route):
    n = len(route.stops)
    nar = route.narration
    passes = [p for p in route.passes if (p.elevation_ft or 0) >= 10000]
    hook = [line for line, _ in hook_items(route)]
    segs = []
    if hook:
        last = hook[-1]
        if last.split(" ", 1)[0] in ("A", "An", "The"):
            last = last[0].lower() + last[1:]
        lines = hook[:-1] + [f"And {last}"] if len(hook) > 1 else hook
        segs.append(Segment("hook", "hook", max(4.8, 1.7 * len(hook)), nar.get("hook") or
                            "Coming up. " + ". ".join(lines) + "."))
    size = (f"{fmt_int(route.total_miles)} miles, {n} stops, and {len(passes)} mountain passes over 10,000 ft"
            if len(passes) > 1 else f"{fmt_int(route.total_miles)} miles and {n} stops")
    segs.append(Segment("intro", "intro", 8.0, nar.get("intro") or
                        f"{route.title}: {size}. Stick around to the end for the full trip planner."))
    middle = [s.name for s in route.stops[1:-1]]
    plan = (f"Here's the plan. We leave {route.stops[0].name}, stop at {_join(middle)}, "
            f"and finish in {route.stops[-1].name}." if middle else
            f"Here's the plan: {route.stops[0].name} to {route.stops[-1].name}.")
    segs.append(Segment("overview", "overview", 5.0, nar.get("overview") or plan))
    for s in route.stops:
        if s.index:
            says = [x.say or f"Worth a stop: {x.name}. {x.note}" for x in s.sights]
            text = s.drive_narration or " ".join(x for x in (s.drive_caption, *says, s.drive_fact) if x)
            dur = min(6.0, max(3.6, 3.0 + s.miles / 40)) + 3.0 * len(s.sights)
            segs.append(Segment(f"drive-{s.index}", "drive", dur, text, stop=s.index))
        text = s.narration or " ".join(x for x in (s.caption, s.fact) if x)
        segs.append(Segment(f"stop-{s.index}", "stop", 5.5 if s.index == 0 else 6.5, text, stop=s.index))
    high, high_name = route.high_point()
    segs.append(Segment("finale", "finale", 4.0, nar.get("finale") or
                        f"That's {fmt_int(route.total_miles)} miles from {route.stops[0].name} to "
                        f"{route.stops[-1].name}, topping out at {fmt_int(high)} ft near {high_name}."))
    segs.append(Segment("planner", "planner", 8.5, nar.get("planner") or
                        "Here's everything you need to plan it yourself. Pause and screenshot this one."))
    up = route.up_next.get("title")
    segs.append(Segment("end", "end", 6.5, nar.get("end") or
                        "Thanks for riding along. Subscribe for more road trips" +
                        (f", and I'll see you on {up}." if up else ".")))
    for seg in segs:
        seg.narration = spoken(seg.narration)
    return segs


def _join(names):
    if len(names) <= 2:
        return " and ".join(names)
    return ", ".join(names[:-1]) + ", and " + names[-1]


def text_hash(text):
    return hashlib.sha1(text.encode()).hexdigest()[:10]


def find_clip(route, seg):
    folder = VO_DIR / route.slug
    for ext in AUDIO_EXTS:
        path = folder / f"{seg.id}{ext}"
        if path.exists():
            return path
    return None


def audio_duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=nw=1:nk=1", str(path)], capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


def layout(route, use_voiceover=True, voice=None):
    """Build segments and assign start times. Returns (segments, total_seconds, notes).

    voice: brand.json "voice" settings; max_pause and tempo tidy up recorded clips.
    """
    from .voice import tighten
    voice = voice or {}
    segs = build_segments(route)
    notes = []
    manifest_path = VO_DIR / route.slug / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    t = 0.0
    for seg in segs:
        seg.dur = seg.min_dur
        clip = find_clip(route, seg) if use_voiceover else None
        if clip:
            recorded = manifest.get(seg.id)
            if recorded and recorded != text_hash(seg.narration):
                notes.append(f"voiceover/{route.slug}/{clip.name} was recorded for different text; re-record it")
            seg.vo_path = tighten(clip, voice.get("max_pause", 0.45), voice.get("tempo", 1.0))
            seg.vo_dur = audio_duration(seg.vo_path)
            seg.dur = max(seg.min_dur, VO_LEAD + seg.vo_dur + VO_TAIL)
        seg.start = t
        t += seg.dur
    return segs, t, notes
