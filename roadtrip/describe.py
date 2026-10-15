"""Side outputs: YouTube description (chapters, itinerary, credits), captions and the
voiceover script."""

from .photos import pick_photos
from .style import fmt_clock, fmt_int, fmt_minutes
from .terrain import ATTRIBUTION as TERRAIN_ATTRIBUTION
from .timeline import VO_LEAD, text_hash


def chapters(route, segs, offset):
    """YouTube chapters: first at 0:00, each at least 10 s long."""
    marks = [(0.0, "Intro")]
    for seg in segs:
        if seg.kind == "stop" and seg.stop == 0:
            marks.append((offset + seg.start, route.stops[0].name))
        elif seg.kind == "drive":
            marks.append((offset + seg.start, route.stops[seg.stop].name))
        elif seg.kind == "planner":
            marks.append((offset + seg.start, "Trip planner"))
    out = []
    for t, name in marks:
        if out and t - out[-1][0] < 10:
            if len(out) > 1:
                out[-1] = (out[-1][0], f"{out[-1][1]} / {name}")
            continue
        out.append((t, name))
    return out


YOUTUBE_LIMIT = 5000  # characters; YouTube also rejects "<" and ">"


def description(route, segs, offset, brand):
    """YouTube description, kept under YouTube's 5,000-character limit."""
    # Trim what the video already shows: first the per-stop see/eat/stay rows, then the
    # notes on "worth a stop" sights (their names stay).
    for details, notes in ((True, True), (False, True), (False, False)):
        text = _description(route, segs, offset, brand, details=details, notes=notes)
        if len(text) <= YOUTUBE_LIMIT:
            break
    else:
        raise ValueError(f"description is {len(text)} characters; YouTube allows {YOUTUBE_LIMIT}")
    return text.replace("<", "(").replace(">", ")")


def short_attribution(entry):
    """Compact credit: title, author, license and a short source link."""
    if not entry or "author" not in entry:
        return ""
    author = " ".join(entry["author"].split())
    if entry.get("source") == "pixabay":
        return f"{author} / Pixabay, {entry['page_url']}"
    if entry.get("source") == "own":
        return f"Photo: {author}"
    title = entry.get("title", "").rsplit(".", 1)[0] if entry.get("source") == "wikimedia" else entry.get("title", "")
    if entry.get("source") == "wikimedia" and entry.get("id"):
        link = f"https://commons.wikimedia.org/?curid={entry['id']}"
    else:
        link = entry.get("page_url", "")
    return f'"{title}" by {author}, {entry.get("license", "")}, {link}'

def _description(route, segs, offset, brand, details=True, notes=True):
    lines = [f"{route.title} | {route.series}" if route.series else route.title, ""]
    bits = [f"{fmt_int(route.total_miles)} miles", f"{len(route.stops)} stops",
            f"about {fmt_minutes(route.total_drive_minutes)} of driving"]
    if route.days:
        bits.append(f"{route.days} day{'' if route.days.strip() == "1" else 's'} recommended")
    lines += [" · ".join(bits), ""]
    lines += ["CHAPTERS"] + [f"{fmt_clock(t)} {name}" for t, name in chapters(route, segs, offset)] + [""]
    lines.append("THE ROUTE")
    for st in route.stops:
        where = "start" if st.index == 0 else (f"mile {int(round(st.mile))} · {st.miles} mi / "
                                               f"{fmt_minutes(st.drive_minutes)} from {route.stops[st.index - 1].name}"
                                               + (f" via {st.road}" if st.road else ""))
        lines.append(f"{st.index + 1}. {st.name} ({fmt_int(st.elevation_ft)} ft) · {where}")
        for sight in st.sights:
            lines.append(f"   On the way, worth a stop: {sight.name}." + (f" {sight.note}" if notes else ""))
        for label, value in (st.info.items() if details else ()):
            lines.append(f"   {label.title()}: {value}")
    lines.append("")
    if route.best_season:
        lines += [f"Best season: {route.best_season}", ""]
    if route.tips:
        lines += ["GOOD TO KNOW"] + [f"- {tip}" for tip in route.tips] + [""]
    lines.append("Mileage and drive times are approximate and don't include stops. "
                 "Check road conditions before you go.")
    lines.append("")
    credits = []
    for st in route.stops:
        for item in [st, *st.sights]:
            for _, entry in pick_photos(item, limit=1 if item is not st else 4):
                line = short_attribution(entry)
                if line and line not in credits:
                    credits.append(line)
    if credits:
        lines += ["PHOTO CREDITS"] + [f"- {c}" for c in credits] + [""]
    lines.append("CREDITS")
    lines.append(f"- Intro sting and outro music: {brand.get('music_credit', brand.get('channel', ''))}")
    if any(s.vo_path for s in segs):
        voice = brand.get("voice", {})
        lines.append(f"- Voiceover: {voice.get('credit', 'recorded narration')}")
    lines.append(f"- {TERRAIN_ATTRIBUTION}")
    return "\n".join(lines).rstrip() + "\n"


def srt(route, segs, offset):
    """Captions file: the narration when there is one, else the on-screen captions."""
    def ts(t):
        ms = int(round(t * 1000))
        return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"
    cues = []
    for seg in segs:
        text = seg.narration
        if not text:
            continue
        start = offset + seg.start + VO_LEAD
        end = start + seg.vo_dur if seg.vo_path else offset + seg.end - 0.2
        # Split long lines into sentence-sized cues spread across the segment.
        sentences = [s.strip() for s in text.replace("! ", "!|").replace("? ", "?|").replace(". ", ".|").split("|") if s.strip()]
        total_chars = sum(len(s) for s in sentences) or 1
        t = start
        for s in sentences:
            d = (end - start) * len(s) / total_chars
            cues.append((t, t + d, s))
            t += d
    return "\n".join(f"{i}\n{ts(a)} --> {ts(b)}\n{text}\n" for i, (a, b, text) in enumerate(cues, 1))


def voiceover_script(route, segs, offset):
    lines = [f"# Voiceover script: {route.title}", "",
             f"Record one clip per segment and save it as `voiceover/{route.slug}/<segment>.mp3` "
             "(or .wav/.m4a), or run `python3 scripts/make_voiceover.py "
             f"routes/{route.slug}.toml` to generate them with ElevenLabs. Segments stretch to fit "
             "their clips, so read at a natural pace.", "",
             "| Segment | Starts | Room | Line |", "|---|---|---|---|"]
    for seg in segs:
        lines.append(f"| `{seg.id}` | {fmt_clock(offset + seg.start)} | {seg.min_dur - VO_LEAD - 0.6:.1f} s "
                     f"| {seg.narration} |")
    lines += ["", f"Text hashes (used to spot stale recordings): " +
              ", ".join(f"{s.id}={text_hash(s.narration)}" for s in segs)]
    return "\n".join(lines) + "\n"
