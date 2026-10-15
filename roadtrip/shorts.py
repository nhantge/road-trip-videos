"""Vertical short (1080x1920) cut from an episode, for YouTube Shorts, Reels and TikTok.

Three beats, all voiced with the episode's own clips so a short costs no new narration:

1. hook: the episode's "coming up" line over full-screen photos of each highlight
2. route: the whole route draws itself on the map while the stops stack up below it,
   with mile, elevation and the leg miles (voiced by the episode's finale line)
3. end: "full trip on the channel" card with subscribe (voiced by the end line)
"""

import dataclasses

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageOps

from . import style as S
from .scenes import Renderer, days_text, drive_progress, plural
from .timeline import layout

SW, SH = 1080, 1920
XFADE = 0.35
X0 = 72              # left margin; Shorts puts its buttons on the right, so text stays in x < ~900
TEXT_W = 830
ROUTE_MIN = 9.0      # seconds for the route to draw itself
END_HOLD = 1.2       # seconds the end card holds after the last word, so the outro chord rings


def short_layout(route, use_voiceover=True, voice=None):
    """The short's segments (copies of the episode's hook, finale and end) and its length."""
    segs, _, notes = layout(route, use_voiceover=use_voiceover, voice=voice)
    by_id = {s.id: s for s in segs}
    picked = []
    for sid, kind, extra in (("hook", "hook", 0.0), ("finale", "route", 0.0), ("end", "end", END_HOLD)):
        if sid not in by_id:
            continue
        seg = dataclasses.replace(by_id[sid], kind=kind)
        seg.dur = seg.dur + extra
        if kind == "route":
            seg.dur = max(seg.dur, ROUTE_MIN)
        picked.append(seg)
    t = 0.0
    for seg in picked:
        seg.start = t
        t += seg.dur
    return picked, t, notes


class ShortRenderer(Renderer):
    """Reuses the episode renderer's photos, hook items and map; draws vertical frames."""

    def __init__(self, route, segments, terrain):
        super().__init__(route, segments, terrain)
        self._tall = {}
        self._end_bg = None

    # -- helpers ---------------------------------------------------------------

    def tall_photo(self, key, t, which=0, dur=5.0):
        """Full-screen vertical crop of a photo that pans across it, so a landscape shot
        shows more than its middle third."""
        photos = self.photos.get(key) or []
        if photos:
            path, entry = photos[which % len(photos)]
            if path not in self._tall:
                with Image.open(path) as im:
                    im = ImageOps.exif_transpose(im).convert("RGB")
                    h = int(SH * 1.06)
                    w = max(int(im.width * h / im.height), int(SW * 1.06))
                    self._tall[path] = ImageOps.fit(im, (w, h), Image.LANCZOS)
            src = self._tall[path]
        else:
            entry, src = None, self.placeholder(key if isinstance(key, int) else 0, (int(SW * 1.06), int(SH * 1.06)))
        p = S.clamp(t / dur)
        zoom = 1.0 + 0.05 * p
        ch = src.height / 1.06 / zoom
        cw = ch * SW / SH
        span = src.width - cw
        # Pan over the middle 60% of the photo, alternating direction.
        lo, hi = 0.2, 0.8
        if (which + (key if isinstance(key, int) else 0)) % 2:
            lo, hi = hi, lo
        cx = cw / 2 + span * (lo + (hi - lo) * S.ease_in_out(p))
        cy = src.height / 2
        box = (cx - cw / 2, cy - ch / 2, cx + cw / 2, cy + ch / 2)
        return src.resize((SW, SH), Image.BILINEAR, box=box), entry

    def frame(self, t):
        seg = self.segment_at(t)
        i = self.segs.index(seg)
        local = t - seg.start
        img = self.render(seg, local)
        if i and local < XFADE:
            prev = self.segs[i - 1]
            img = Image.blend(self.render(prev, prev.dur), img, S.smooth(local / XFADE))
        return img

    def render(self, seg, t):
        if seg.kind == "hook":
            return self.short_hook(seg, t)
        if seg.kind == "route":
            return self.short_route(seg, t)
        return self.short_end(seg, t)

    def _title_block(self, d, y, a=255):
        route = self.route
        d.text((X0, y), (route.series or "").upper(), font=S.font("semibold", 28),
               fill=(220, 225, 228, a), anchor="ls", stroke_width=2, stroke_fill=S.BG_TITLE + (a // 2,))
        f = S.font("display", 84)
        if f.getlength(route.title) > TEXT_W:
            f = S.font("display", int(84 * TEXT_W / f.getlength(route.title)))
        d.text((X0 - 3, y + 92), route.title, font=f, fill=S.TEXT + (a,), anchor="ls",
               stroke_width=3, stroke_fill=S.BG_TITLE + (a // 2,))
        bits = [f"{S.fmt_int(route.total_miles)} miles", f"{self.n} stops"]
        if route.days:
            bits.append(days_text(route.days))
        d.text((X0, y + 148), "  ·  ".join(bits), font=S.font("semibold", 34), fill=S.TEAL + (a,), anchor="ls",
               stroke_width=3, stroke_fill=S.BG_TITLE + (a * 2 // 3,))

    # -- 1. hook ---------------------------------------------------------------

    def short_hook(self, seg, t):
        items = self.hook or [(self.route.title, len(self.route.stops) - 1)]
        per = seg.dur / len(items)
        k = min(int(t / per), len(items) - 1)
        lt = t - k * per
        img = self._hook_frame(items, k, lt, per)
        if k and lt < 0.25:
            img = Image.blend(self._hook_frame(items, k - 1, per, per), img, S.smooth(lt / 0.25))
        return img

    def _hook_frame(self, items, k, t, per):
        line, stop_index = items[k]
        idx = stop_index if stop_index is not None else k
        bg, entry = self.tall_photo(idx, t, which=0, dur=per)
        img = bg.convert("RGBA")
        img.alpha_composite(_shade())
        d = ImageDraw.Draw(img)
        for j in range(len(items)):
            x = X0 + j * 96
            d.rounded_rectangle((x, 150, x + 82, 158), 4, fill=S.ORANGE if j <= k else (255, 255, 255, 80))
        self._title_block(d, 236)
        a = S.ease_out(t / 0.35)
        layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
        dl = ImageDraw.Draw(layer)
        f = S.font("display", 92)
        lines = S.wrap(line, f, TEXT_W)
        if len(lines) > 3:
            f = S.font("display", 76)
            lines = S.wrap(line, f, TEXT_W)
        lh = int(f.size * 1.12)
        top = 1330 - len(lines) * lh
        kick = f"HIGHLIGHT {k + 1} OF {len(items)}"
        kf = S.font("bold", 30)
        kw = int(kf.getlength(kick) + 40)
        layer.alpha_composite(S.rounded_box(kw, 50, 25, S.ORANGE + (255,)), (X0, top - 92))
        dl.text((X0 + kw / 2, top - 67), kick, font=kf, fill=S.BG_TITLE, anchor="mm")
        for i, ln in enumerate(lines):
            dl.text((X0 - 3, top + i * lh), ln, font=f, fill=S.TEXT, stroke_width=3, stroke_fill=S.BG_TITLE + (110,))
        if stop_index is not None:
            st = self.route.stops[stop_index]
            where = [st.name, f"{S.fmt_int(st.elevation_ft)} ft"]
            if st.index:
                where.append(f"mile {int(round(st.mile))}")
            dl.text((X0, top + len(lines) * lh + 52), "  ·  ".join(where), font=S.font("semibold", 38),
                    fill=S.TEAL, anchor="ls", stroke_width=3, stroke_fill=S.BG_TITLE + (170,))
        img.alpha_composite(S.with_alpha(layer, a), (int((1 - a) * -30), 0))
        from .photos import short_credit
        credit = short_credit(entry)
        if credit:
            d.text((X0, 1505), credit, font=S.font("regular", 20), fill=(205, 210, 214), anchor="ls")
        return img.convert("RGB")

    # -- 2. route ----------------------------------------------------------------

    def short_route(self, seg, t):
        route, mv = self.route, self.map
        img = Image.new("RGBA", (SW, SH), S.BG_TITLE + (255,))
        d = ImageDraw.Draw(img)
        d.text((X0, 236), "THE WHOLE ROUTE", font=S.font("bold", 32), fill=S.ORANGE, anchor="ls")
        f = S.font("display", 72)
        if f.getlength(route.title) > TEXT_W:
            f = S.font("display", int(72 * TEXT_W / f.getlength(route.title)))
        d.text((X0 - 3, 318), route.title, font=f, fill=S.TEXT, anchor="ls")

        p = drive_progress((t - 0.5) / max(1.0, seg.dur - 2.2))
        mile = route.total_miles * p
        visited = sum(1 for s in route.stops if s.mile <= mile + 0.05)
        current = route.stops[-1].index if p >= 1 else None
        center, zoom = self.route_camera()
        m = mv.render(center, zoom, mile, seg.start + t, visited, current, pulse=p < 1)
        mv.draw_hud(m, mile, route.elevation_at(mile))
        mv.draw_inset(m, mile)
        mh = int(S.MAP_H * SW / S.MAP_W)
        m = m.convert("RGB").resize((SW, mh), Image.LANCZOS)
        img.paste(m, (0, 360))

        # The stops stack up under the map as the line reaches them.
        n = len(route.stops)
        top, bottom = 360 + mh + 34, 1590
        rh = min(78, (bottom - top) // n)
        name_f, sub_f = S.font("semibold", min(38, int(rh * 0.5))), S.font("medium", min(28, int(rh * 0.37)))
        for st in route.stops:
            reached = max(0.0, (seg.start + t) - self._reach_time(seg, st.mile))
            a = S.ease_out(reached / 0.35) if st.mile <= mile + 0.05 else 0.0
            if a <= 0:
                continue
            y = top + st.index * rh + rh // 2
            row = Image.new("RGBA", (SW, rh), (0, 0, 0, 0))
            dr = ImageDraw.Draw(row)
            r = int(rh * 0.62)
            S.paste_center(row, S.circle(r, S.ORANGE + (255,)), X0 + r / 2, rh / 2)
            dr.text((X0 + r / 2, rh / 2 + 1), str(st.index + 1), font=S.font("bold", int(r * 0.55)),
                    fill=S.BG_TITLE, anchor="mm")
            dr.text((X0 + r + 22, rh / 2), st.name, font=name_f, fill=S.TEXT, anchor="lm")
            facts = f"{S.fmt_int(st.elevation_ft)} ft"
            if st.index:
                facts += f"  ·  +{st.miles:g} mi"
            dr.text((SW - 190, rh / 2), facts, font=sub_f, fill=S.TEAL, anchor="rm")
            img.alpha_composite(S.with_alpha(row, a), (int((1 - a) * 24), y - rh // 2))
        return img.convert("RGB")

    def route_camera(self):
        """Zoom in past the episode's overview so the route fills the map below the HUD."""
        route, mv = self.route, self.map
        rw = (route.wx.max() - route.wx.min()) / mv.u0
        rh = (route.wy.max() - route.wy.min()) / mv.u0
        hud = 230  # px at the top of the map taken by the HUD and inset
        zoom = S.clamp(min(0.8 * S.MAP_W / max(rw, 1), (S.MAP_H - hud - 70) / max(rh, 1)), 1.0, 2.4)
        target_y = hud + (S.MAP_H - hud) / 2  # where the route's middle should sit on screen
        cx = (route.wx.max() + route.wx.min()) / 2
        cy = (route.wy.max() + route.wy.min()) / 2 - (target_y - S.MAP_H / 2) * mv.u0 / zoom
        return (float(cx), float(cy)), zoom

    def _reach_time(self, seg, mile):
        """Absolute time at which the route line reaches `mile` (inverse of drive_progress)."""
        route = self.route
        target = mile / route.total_miles if route.total_miles else 0
        lo, hi = 0.0, 1.0
        for _ in range(30):
            mid = (lo + hi) / 2
            if drive_progress(mid) < target - 1e-6:
                lo = mid
            else:
                hi = mid
        return seg.start + 0.5 + hi * max(1.0, seg.dur - 2.2)

    # -- 3. end card ---------------------------------------------------------------

    def used_photos(self):
        """Credit entries for the photos the short shows."""
        keys = [(stop if stop is not None else k, 0) for k, (_, stop) in enumerate(self.hook)]
        keys.append((self._end_index(), int(self.route.thumbnail.get("photo", 0))))
        out = []
        for key, which in keys:
            photos = self.photos.get(key) or []
            if photos:
                entry = photos[which % len(photos)][1]
                if entry not in out:
                    out.append(entry)
        return out

    def _end_index(self):
        key = self.route.thumbnail.get("stop")
        return next((s.index for s in self.route.stops if s.name == key), len(self.route.stops) - 1)

    def end_background(self):
        if self._end_bg is None:
            bg, _ = self.tall_photo(self._end_index(), 0.0, which=int(self.route.thumbnail.get("photo", 0)))
            bg = bg.filter(ImageFilter.GaussianBlur(18)).convert("RGBA")
            bg.alpha_composite(Image.new("RGBA", bg.size, S.BG_TITLE + (178,)))
            self._end_bg = bg
        return self._end_bg

    def short_end(self, seg, t):
        route = self.route
        img = self.end_background().copy()
        a = S.ease_out(t / 0.5)
        layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        y = 560
        d.text((X0, y), "WANT THE FULL TRIP?", font=S.font("bold", 36), fill=S.ORANGE, anchor="ls")
        f = S.font("display", 104)
        lines = S.wrap(route.title, f, TEXT_W)
        S.draw_lines(d, (X0 - 4, y + 34), lines, f, S.TEXT, 112)
        y += 34 + len(lines) * 112 + 40
        passes = [p for p in route.passes if (p.elevation_ft or 0) >= 10000]
        high, _ = route.high_point()
        facts = [f"{S.fmt_int(route.total_miles)} miles  ·  {self.n} stops",
                 f"Top elevation {S.fmt_int(high)} ft" +
                 (f"  ·  {len(passes)} {plural(len(passes), 'pass', 'passes')} over 10,000 ft" if passes else "")]
        for line in facts:
            d.text((X0, y), line, font=S.font("medium", 36), fill=S.TEXT_DIM, anchor="lm")
            y += 54
        y += 40
        perks = ["Every stop, drive times and elevations", "Where to eat, see and stay",
                 "A trip planner you can screenshot"]
        for line in perks:
            S.paste_center(layer, S.circle(16, S.TEAL + (255,)), X0 + 8, y)
            d.text((X0 + 36, y), line, font=S.font("semibold", 36), fill=S.TEXT, anchor="lm")
            y += 62
        y += 50
        label = "FULL EPISODE ON THE CHANNEL"
        bf = S.font("bold", 34)
        bw = int(bf.getlength(label) + 76)
        layer.alpha_composite(S.rounded_box(bw, 92, 46, S.ORANGE + (255,)), (X0, y))
        d.text((X0 + bw / 2, y + 46), label, font=bf, fill=S.BG_TITLE, anchor="mm")
        y += 150
        up = route.up_next.get("title")
        if up:
            d.text((X0, y), "UP NEXT", font=S.font("bold", 28), fill=S.ORANGE, anchor="lm")
            d.text((X0 + 150, y), up, font=S.font("semibold", 36), fill=S.TEXT, anchor="lm")
        img.alpha_composite(S.with_alpha(layer, a), (0, int((1 - a) * 24)))
        return img.convert("RGB")


_SHADE = None


def _shade():
    """Dark top and bottom so white text reads over any photo."""
    global _SHADE
    if _SHADE is None:
        y = np.linspace(0, 1, SH)[:, None]
        top = np.clip(1 - y / 0.3, 0, 1) ** 1.1 * 0.85
        bottom = np.clip((y - 0.3) / 0.32, 0, 1) ** 1.1 * 0.9
        alpha = np.broadcast_to(np.maximum(top, bottom), (SH, SW))
        arr = np.zeros((SH, SW, 4), np.uint8)
        arr[..., :3] = S.BG_TITLE
        arr[..., 3] = (alpha * 255).astype(np.uint8)
        _SHADE = Image.fromarray(arr, "RGBA")
    return _SHADE


def caption_text(route, brand, total, credits=()):
    """Title and description to paste when posting the short."""
    high, _ = route.high_point()
    hook = route.hook[0].partition(" : ")[0] if route.hook else ""
    title = f"{route.title}: {S.fmt_int(route.total_miles)} miles in {round(total)} seconds #shorts"
    tags = ["#shorts", "#roadtrip", "#colorado", "#" + "".join(w.capitalize() for w in route.title.split()
                                                                  if w.isalpha() and w.lower() != "to")]
    lines = [
        "TITLE (under 100 characters)",
        title,
        "",
        "DESCRIPTION / CAPTION",
        f"{hook}. {route.title}: {S.fmt_int(route.total_miles)} miles, {len(route.stops)} stops, "
        f"topping out at {S.fmt_int(high)} ft.",
        "",
        "Full episode with every stop, drive times and a trip planner is on the channel. "
        f"Subscribe to {brand.get('channel', 'the channel')} for more road trips!",
        "",
        " ".join(tags + ["#travel", "#scenicdrive", "#roadtripideas"]),
        "",
        *(["PHOTO CREDITS"] + [f"- {c}" for c in credits] + [""] if credits else []),
        "When posting: on YouTube, link the full episode as the short's \"Related video\". "
        "On Instagram and TikTok, use the same caption.",
    ]
    return "\n".join(lines) + "\n"
