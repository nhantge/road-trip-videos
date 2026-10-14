"""Frame compositor: turns (timeline, time) into a 1920x1080 frame.

Full-screen cards (hook, title + stats, planner, end card) and the map scenes
(overview, drives, stops, finale) share the San Juan Skyway demo's look.
"""

import math

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from . import style as S
from .mapview import ZFOLLOW, MapView
from .photos import load_cover, pick_photos, short_credit
from .timeline import hook_items

XFADE = 0.4         # crossfade between full-screen scenes
PANEL_XFADE = 0.35  # crossfade of the right-hand panel between map segments
PHOTO_BOX = (1206, 92, 672, 330)
SKY = [(180, 105, 60), (75, 125, 100), (165, 80, 80), (70, 120, 150), (190, 80, 55),
       (110, 105, 165), (95, 135, 70), (160, 120, 60)]


class Renderer:
    def __init__(self, route, segments, terrain):
        self.route = route
        self.segs = segments
        self.map = MapView(route, terrain)
        self.n = len(route.stops)
        self.photos = {s.index: pick_photos(s) for s in route.stops}
        self._covers = {}
        self.hook = hook_items(route)
        self._stats = self._stat_cards()

    # -- helpers ---------------------------------------------------------------

    def cover(self, path, size):
        key = (str(path), size)
        if key not in self._covers:
            self._covers[key] = load_cover(path, size)
        return self._covers[key]

    def placeholder(self, index, size):
        key = ("placeholder", index, size)
        if key not in self._covers:
            self._covers[key] = placeholder_art(size, index)
        return self._covers[key]

    def photo_frame(self, stop_index, size, t, which=0):
        """Ken Burns crop of a stop photo (or illustrated placeholder) at time t."""
        photos = self.photos.get(stop_index) or []
        if photos:
            path, entry = photos[which % len(photos)]
            src = self.cover(path, size)
        else:
            entry = None
            src = self.placeholder(stop_index, size)
        p = S.clamp(t / 9.0)
        zoom = 1.0 + 0.10 * p
        cw, ch = src.width / 1.12 / zoom * 1.12, src.height / 1.12 / zoom * 1.12
        cw, ch = min(cw, src.width), min(ch, src.height)
        drift = (stop_index % 2 * 2 - 1) * 0.5
        cx = src.width / 2 + drift * (src.width - cw) * (p - 0.5)
        cy = src.height / 2
        box = (cx - cw / 2, cy - ch / 2, cx + cw / 2, cy + ch / 2)
        return src.resize(size, Image.BILINEAR, box=box), entry

    def segment_at(self, t):
        for seg in self.segs:
            if t < seg.end:
                return seg
        return self.segs[-1]

    # -- top level -------------------------------------------------------------

    def frame(self, t):
        seg = self.segment_at(t)
        i = self.segs.index(seg)
        local = t - seg.start
        img = self.render(seg, local)
        prev = self.segs[i - 1] if i else None
        if prev and local < XFADE and (not self.is_map(seg) or not self.is_map(prev)):
            before = self.render(prev, prev.dur)
            img = Image.blend(before, img, S.smooth(local / XFADE))
        return img

    @staticmethod
    def is_map(seg):
        return seg.kind in ("overview", "drive", "stop", "finale")

    def render(self, seg, t):
        if seg.kind == "hook":
            return self.hook_scene(seg, t)
        if seg.kind == "intro":
            return self.intro_scene(seg, t)
        if seg.kind == "planner":
            return self.planner_scene(seg, t)
        if seg.kind == "end":
            return self.end_scene(seg, t)
        return self.map_scene(seg, t)

    # -- map scenes --------------------------------------------------------------

    def map_state(self, seg, t):
        """Camera center, zoom, car mile, stops visited, stop parked at."""
        route, mv = self.route, self.map
        zf = ZFOLLOW
        if seg.kind == "overview":
            p = S.ease_in_out((t - seg.dur * 0.5) / (seg.dur * 0.5))
            c0, c1 = mv.overview, mv.follow_center(0)
            zoom = math.exp(math.log(1.0) + (math.log(zf) - math.log(1.0)) * p)
            # Move the center in step with the zoom so the fly-in feels like one motion.
            q = (zoom - 1) / (zf - 1) if zf > 1 else p
            center = (c0[0] + (c1[0] - c0[0]) * q, c0[1] + (c1[1] - c0[1]) * q)
            return center, zoom, 0.0, 0, None
        if seg.kind == "stop":
            st = route.stops[seg.stop]
            zoom = zf * (1 + 0.06 * S.ease_out(t / seg.dur))
            return mv.follow_center(st.mile), zoom, st.mile, seg.stop, seg.stop
        if seg.kind == "drive":
            a, b = route.stops[seg.stop - 1], route.stops[seg.stop]
            p = drive_progress(t / seg.dur)
            mile = a.mile + (b.mile - a.mile) * p
            dip = S.clamp((b.mile - a.mile) / 260, 0.08, 0.28)
            zoom = (zf * 1.06 + (zf - zf * 1.06) * p) * (1 - dip * math.sin(math.pi * p))
            return mv.follow_center(mile), zoom, mile, seg.stop, None
        # finale
        p = S.ease_in_out(t / min(2.4, seg.dur))
        end = route.total_miles
        c0, c1 = mv.follow_center(end), mv.overview
        z0 = zf * 1.06
        zoom = math.exp(math.log(z0) + (math.log(1.0) - math.log(z0)) * p)
        q = (z0 - zoom) / (z0 - 1)
        center = (c0[0] + (c1[0] - c0[0]) * q, c0[1] + (c1[1] - c0[1]) * q)
        return center, zoom, end, self.n, None

    def map_scene(self, seg, t):
        center, zoom, mile, visited, current = self.map_state(seg, t)
        img = Image.new("RGBA", (S.W, S.H), S.BG_PANEL + (255,))
        img.alpha_composite(self.map.render(center, zoom, mile, seg.start + t, visited, current), (0, 0))
        self.map.draw_hud(img, mile, self.route.elevation_at(mile))
        self.map.draw_inset(img, mile)
        caption = self.caption_for(seg)
        if caption:
            a = min(S.fade(t, 0.35, 0.3), 1 - S.fade(t, seg.dur - 0.35, 0.3))
            self.map.draw_caption(img, caption, a)
        self.map.draw_profile(img, mile)
        # Right-hand panel, crossfading from the previous map segment's panel.
        panel = self.panel(seg, t)
        i = self.segs.index(seg)
        prev = self.segs[i - 1] if i else None
        if prev is not None and self.is_map(prev) and t < PANEL_XFADE:
            panel = Image.blend(self.panel(prev, prev.dur), panel, S.smooth(t / PANEL_XFADE))
        img.alpha_composite(panel, (S.PANEL_X, 0))
        ImageDraw.Draw(img).line((S.MAP_W, 0, S.MAP_W, S.H), fill=(36, 48, 60), width=2)
        return img.convert("RGB")

    def caption_for(self, seg):
        if seg.kind == "stop":
            return self.route.stops[seg.stop].caption
        if seg.kind == "drive":
            return self.route.stops[seg.stop].drive_caption
        return ""

    # -- right-hand panels ---------------------------------------------------------

    def panel(self, seg, t):
        img = Image.new("RGBA", (S.W - S.PANEL_X, S.H), S.BG_PANEL + (255,))
        if seg.kind == "stop":
            self.stop_panel(img, seg, t)
        elif seg.kind == "drive":
            self.drive_panel(img, seg, t)
        elif seg.kind == "overview":
            self.overview_panel(img, seg, t)
        else:
            self.finale_panel(img, seg, t)
        return img

    def _dots(self, d, filled, active=None):
        x1 = S.W - S.PANEL_X - 42
        for k in range(self.n):
            x = x1 - (self.n - 1 - k) * 26
            color = S.ORANGE if k < filled else (55, 68, 80)
            if k == active:
                color = S.ORANGE
            d.rounded_rectangle((x - 9, 52, x + 9, 61), 4, fill=color)

    def _photo(self, img, stop_index, t, chip="", h=330, switch_at=None):
        X, Y, Wd, Ht = PHOTO_BOX
        X -= S.PANEL_X
        Ht = h
        a = S.ease_out(t / 0.5)
        if switch_at is not None and len(self.photos.get(stop_index) or []) > 1 and t > switch_at:
            first, _ = self.photo_frame(stop_index, (Wd, Ht), t, 0)
            second, entry = self.photo_frame(stop_index, (Wd, Ht), t - switch_at, 1)
            photo = Image.blend(first, second, S.smooth((t - switch_at) / 0.6))
        else:
            photo, entry = self.photo_frame(stop_index, (Wd, Ht), t, 0)
        mask = S.rounded_box(Wd, Ht, 14, (255, 255, 255, 255)).getchannel("A")
        if a < 1:
            mask = mask.point(lambda v: int(v * a))
        img.paste(photo, (X, Y + int((1 - a) * 16)), mask)
        d = ImageDraw.Draw(img)
        if chip:
            f = S.font("bold", 14)
            w = int(f.getlength(chip) + 22)
            img.alpha_composite(S.with_alpha(S.rounded_box(w, 28, 6, (6, 10, 14, 225)), a), (X + 16, Y + 16))
            d.text((X + 16 + w / 2, Y + 30), chip, font=f, fill=S.TEXT, anchor="mm")
        credit = short_credit(entry)
        if credit:
            f = S.font("medium", 12)
            w = int(f.getlength(credit) + 16)
            img.alpha_composite(S.with_alpha(S.rounded_box(w, 22, 5, (6, 10, 14, 190)), a), (X + Wd - w - 10, Y + Ht - 32))
            d.text((X + Wd - 10 - w / 2, Y + Ht - 21), credit, font=f, fill=(205, 210, 214), anchor="mm")
        return Y + Ht

    def _fact_card(self, img, kicker, text, t, start):
        if not text:
            return
        a = S.ease_out((t - start) / 0.45)
        if a <= 0:
            return
        X = 1206 - S.PANEL_X
        f = S.font("regular", 23)
        lines = S.wrap(text, f, 600)
        h = 62 + len(lines) * 33
        y = 1040 - h + int((1 - a) * 22)
        card = Image.new("RGBA", (672, h), (0, 0, 0, 0))
        card.alpha_composite(S.rounded_box(672, h, 14, S.CARD + (255,), S.CARD_BORDER + (255,), 2))
        d = ImageDraw.Draw(card)
        d.rounded_rectangle((0, 14, 4, h - 14), 2, fill=S.ORANGE)
        d.text((30, 30), kicker, font=S.font("bold", 15), fill=S.ORANGE, anchor="lm")
        S.draw_lines(d, (30, 50), lines, f, S.TEXT, 33)
        img.alpha_composite(S.with_alpha(card, a), (X, y))

    def stop_panel(self, img, seg, t):
        st = self.route.stops[seg.stop]
        d = ImageDraw.Draw(img)
        X = 1206 - S.PANEL_X
        d.text((X, 57), f"STOP {st.index + 1} OF {self.n}", font=S.font("semibold", 19), fill=S.ORANGE, anchor="lm")
        self._dots(d, st.index + 1)
        switch = seg.dur * 0.5 if seg.dur > 5 else None
        bottom = self._photo(img, st.index, t, chip=st.tag, switch_at=switch)
        a = S.ease_out((t - 0.12) / 0.45)
        title = S.font("display", 60)
        if title.getlength(st.name) > 672:
            title = S.font("display", int(60 * 672 / title.getlength(st.name)))
        layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
        dl = ImageDraw.Draw(layer)
        y = bottom + 66
        dl.text((X, y), st.name, font=title, fill=S.TEXT, anchor="ls")
        parts = []
        if st.index == 0:
            parts.append("START")
        elif st.index == self.n - 1:
            parts.append("FINISH")
        parts.append(f"{S.fmt_int(st.elevation_ft)} ft")
        if st.index:
            parts.append(f"mile {int(round(st.mile))}")
        dl.text((X, y + 42), "  ·  ".join(parts), font=S.font("medium", 24), fill=S.TEAL, anchor="ls")
        dl.line((X, y + 68, X + 672, y + 68), fill=(40, 52, 62), width=2)
        img.alpha_composite(S.with_alpha(layer, a), (0, int((1 - a) * 14)))
        # Info rows, staggered in.
        y += 100
        f = S.font("regular", 25)
        for k, (label, value) in enumerate(st.info.items()):
            ra = S.ease_out((t - 0.3 - 0.1 * k) / 0.4)
            lines = S.wrap(value, f, 535)
            row = Image.new("RGBA", (img.width, 34 * len(lines) + 10), (0, 0, 0, 0))
            dr = ImageDraw.Draw(row)
            dr.text((X, 14), label.upper(), font=S.font("semibold", 15), fill=S.TEXT_DIM, anchor="lm")
            S.draw_lines(dr, (X + 134, 0), lines, f, S.TEXT, 34)
            img.alpha_composite(S.with_alpha(row, ra), (int((1 - ra) * 18), y))
            y += 34 * len(lines) + 18
        self._fact_card(img, "DID YOU KNOW?", st.fact, t, 1.1)

    def drive_panel(self, img, seg, t):
        route = self.route
        st, prev = route.stops[seg.stop], route.stops[seg.stop - 1]
        d = ImageDraw.Draw(img)
        X = 1206 - S.PANEL_X
        d.text((X, 57), f"NEXT STOP  ·  {st.index + 1} OF {self.n}", font=S.font("semibold", 19), fill=S.ORANGE, anchor="lm")
        self._dots(d, st.index, active=st.index)
        bottom = self._photo(img, st.index, t, chip="COMING UP", h=300)
        a = S.ease_out((t - 0.1) / 0.45)
        layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
        dl = ImageDraw.Draw(layer)
        y = bottom + 62
        title = S.font("display", 54)
        if title.getlength(st.name) > 672:
            title = S.font("display", int(54 * 672 / title.getlength(st.name)))
        dl.text((X, y), st.name, font=title, fill=S.TEXT, anchor="ls")
        if st.road:
            dl.text((X, y + 38), f"via {st.road}", font=S.font("medium", 23), fill=S.TEAL, anchor="ls")
        dl.line((X, y + 62, X + 672, y + 62), fill=(40, 52, 62), width=2)
        # Live countdown of miles to go.
        p = drive_progress(t / seg.dur)
        to_go = (st.mile - prev.mile) * (1 - p)
        cols = [("MILES TO GO", f"{int(math.ceil(to_go - 1e-6))}"), ("DRIVE TIME", S.fmt_minutes(st.drive_minutes)),
                ("ELEVATION", f"{S.fmt_int(st.elevation_ft)} ft")]
        for k, (label, value) in enumerate(cols):
            cx = X + k * 232
            dl.text((cx, y + 98), label, font=S.font("semibold", 15), fill=S.TEXT_DIM, anchor="lm")
            dl.text((cx, y + 146), value, font=S.font("display-semibold", 36), fill=S.TEXT, anchor="ls")
        dl.text((X, y + 184), "Road miles and drive time are approximate, without stops.",
                font=S.font("regular", 16), fill=S.TEXT_FAINT, anchor="lm")
        img.alpha_composite(S.with_alpha(layer, a), (0, int((1 - a) * 14)))
        self._leg_chart(img, prev, st, p, y + 220, S.ease_out((t - 0.4) / 0.45))
        self._fact_card(img, "ON THIS STRETCH", st.drive_fact, t, 0.8)

    def _leg_chart(self, img, a_stop, b_stop, p, top, alpha):
        """Small elevation chart of just this leg, filling in as the car drives it."""
        if alpha <= 0:
            return
        route = self.route
        X, w, h = 1206 - S.PANEL_X, 672, 150
        miles = np.linspace(a_stop.mile, b_stop.mile, 160)
        elev = np.array([route.elevation_at(m) for m in miles])
        lo, hi = elev.min(), elev.max()
        span = max(hi - lo, 600)
        ss = 3
        chart = Image.new("RGBA", (w * ss, (h + 40) * ss), (0, 0, 0, 0))
        dc = ImageDraw.Draw(chart)
        y0, y1 = 44 * ss, (h + 4) * ss
        xs = np.linspace(0, (w - 2) * ss, len(miles))
        ys = y1 - (elev - lo) / span * (y1 - y0)
        pts = list(zip(xs, ys))
        dc.polygon(pts + [(xs[-1], y1), (0, y1)], fill=(29, 40, 51, 255))
        dc.line(pts, fill=S.ROUTE_GREY + (255,), width=2 * ss)
        k = max(2, int(len(pts) * p))
        if p > 0:
            dc.polygon(pts[:k] + [(xs[k - 1], y1), (0, y1)], fill=S.ORANGE_DARK + (255,))
            dc.line(pts[:k], fill=S.ORANGE + (255,), width=2 * ss)
        chart = chart.resize((w, h + 40), Image.LANCZOS)
        d = ImageDraw.Draw(chart)
        d.text((0, 12), "ELEVATION ON THIS LEG", font=S.font("semibold", 15), fill=S.TEXT_DIM, anchor="lm")
        top_k = int(np.argmax(elev))
        d.text((w, 12), f"high point {S.fmt_int(hi)} ft", font=S.font("medium", 15), fill=S.TEXT, anchor="rm")
        d.text((0, h + 24), f"{a_stop.name}  {S.fmt_int(a_stop.elevation_ft)} ft", font=S.font("regular", 15),
               fill=S.TEXT_FAINT, anchor="lm")
        d.text((w, h + 24), f"{S.fmt_int(b_stop.elevation_ft)} ft  {b_stop.name}", font=S.font("regular", 15),
               fill=S.TEXT_FAINT, anchor="rm")
        x_top = xs[top_k] / ss
        S.paste_center(chart, S.circle(9, S.LABEL + (255,)), x_top, ys[top_k] / ss)
        img.alpha_composite(S.with_alpha(chart, alpha), (X, top))

    def overview_panel(self, img, seg, t):
        route = self.route
        d = ImageDraw.Draw(img)
        X = 1206 - S.PANEL_X
        d.text((X, 57), "THE ROUTE", font=S.font("semibold", 19), fill=S.ORANGE, anchor="lm")
        d.text((X, 128), f"{self.n} stops, {S.fmt_int(route.total_miles)} miles", font=S.font("display", 50),
               fill=S.TEXT, anchor="ls")
        d.text((X, 168), f"About {S.fmt_minutes(route.total_drive_minutes)} of driving",
               font=S.font("medium", 23), fill=S.TEAL, anchor="ls")
        rows = route.stops
        avail = 1040 - 205 - 70
        rh = min(92, avail // len(rows))
        for k, st in enumerate(rows):
            ra = S.ease_out((t - 0.25 - 0.12 * k) / 0.4)
            row = Image.new("RGBA", (img.width, rh), (0, 0, 0, 0))
            dr = ImageDraw.Draw(row)
            S.paste_center(row, S.circle(34, S.ORANGE + (255,)), X + 17, rh / 2)
            dr.text((X + 17, rh / 2 + 0.5), str(k + 1), font=S.font("bold", 17), fill=S.BG_TITLE, anchor="mm")
            dr.text((X + 54, rh / 2), st.name, font=S.font("semibold", 27), fill=S.TEXT, anchor="lm")
            right = "start" if k == 0 else f"mile {int(round(st.mile))}"
            dr.text((X + 672, rh / 2 - 11), right, font=S.font("medium", 20), fill=S.TEXT_DIM, anchor="rm")
            dr.text((X + 672, rh / 2 + 14), f"{S.fmt_int(st.elevation_ft)} ft", font=S.font("regular", 17),
                    fill=S.TEXT_FAINT, anchor="rm")
            if k < len(rows) - 1:
                dr.line((X + 17, rh / 2 + 20, X + 17, rh), fill=(55, 68, 80), width=2)
            if k:
                dr.line((X + 17, 0, X + 17, rh / 2 - 20), fill=(55, 68, 80), width=2)
            img.alpha_composite(S.with_alpha(row, ra), (int((1 - ra) * 18), 205 + k * rh))
        a = S.ease_out((t - 1.2) / 0.4)
        self._pill(img, "FULL TRIP PLANNER AT THE END", X, 1000, a)

    def finale_panel(self, img, seg, t):
        route = self.route
        d = ImageDraw.Draw(img)
        X = 1206 - S.PANEL_X
        d.text((X, 57), "YOU MADE IT", font=S.font("semibold", 19), fill=S.ORANGE, anchor="lm")
        self._dots(d, self.n)
        d.text((X, 140), route.stops[-1].name, font=S.font("display", 64), fill=S.TEXT, anchor="ls")
        high, high_name = route.high_point()
        low, low_name = route.low_point()
        rows = [
            (S.fmt_int(route.total_miles), "miles driven"),
            (S.fmt_minutes(route.total_drive_minutes), "behind the wheel"),
            (f"{S.fmt_int(high)} ft", f"high point, near {high_name}"),
            (f"{S.fmt_int(low)} ft", f"low point, near {low_name}"),
        ]
        passes = [p for p in route.passes if (p.elevation_ft or 0) >= 10000]
        if passes:
            rows.append((str(len(passes)), "passes over 10,000 ft"))
        for k, (big, small) in enumerate(rows):
            ra = S.ease_out((t - 0.3 - 0.15 * k) / 0.4)
            row = Image.new("RGBA", (img.width, 110), (0, 0, 0, 0))
            dr = ImageDraw.Draw(row)
            dr.text((X, 62), big, font=S.font("display", 52), fill=S.TEXT, anchor="ls")
            dr.text((X, 94), small.upper(), font=S.font("semibold", 17), fill=S.TEAL, anchor="ls")
            img.alpha_composite(S.with_alpha(row, ra), (int((1 - ra) * 18), 190 + k * 130))
        self._pill(img, "TRIP PLANNER NEXT", X, 1000, S.ease_out((t - 1.0) / 0.4))

    def _pill(self, img, text, x, y, a):
        if a <= 0:
            return
        f = S.font("bold", 16)
        w = int(f.getlength(text) + 36)
        pill = Image.new("RGBA", (w, 38), (0, 0, 0, 0))
        pill.alpha_composite(S.rounded_box(w, 38, 19, (0, 0, 0, 0), S.ORANGE + (255,), 2))
        ImageDraw.Draw(pill).text((w / 2, 19), text, font=f, fill=S.ORANGE, anchor="mm")
        img.alpha_composite(S.with_alpha(pill, a), (x, y - 19))

    # -- full-screen scenes ----------------------------------------------------------

    def hook_scene(self, seg, t):
        items = self.hook
        per = seg.dur / len(items)
        k = min(int(t / per), len(items) - 1)
        lt = t - k * per
        line, stop_index = items[k]
        img = self._hook_card(line, stop_index, lt, per, k)
        if k and lt < 0.25:
            prev_line, prev_stop = items[k - 1]
            img = Image.blend(self._hook_card(prev_line, prev_stop, per, per, k - 1), img, S.smooth(lt / 0.25))
        return img

    def _hook_card(self, line, stop_index, t, per, k):
        idx = stop_index if stop_index is not None else k
        bg, _ = self.photo_frame(idx, (S.W, S.H), 2 + t * 2.2, which=1 if k % 2 else 0)
        img = bg.convert("RGBA")
        img.alpha_composite(_gradient_overlay())
        d = ImageDraw.Draw(img)
        a = S.ease_out(t / 0.35)
        n = len(self.hook)
        for j in range(n):
            x = 120 + j * 74
            d.rounded_rectangle((x, 96, x + 60, 102), 3, fill=S.ORANGE if j <= k else (255, 255, 255, 70))
        d.text((120, 150), (self.route.series or "").upper(), font=S.font("semibold", 22), fill=(220, 225, 228), anchor="lm")
        layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
        dl = ImageDraw.Draw(layer)
        dl.text((120, 690), "COMING UP", font=S.font("bold", 26), fill=S.ORANGE, anchor="ls")
        f = S.font("display", 76)
        lines = S.wrap(line, f, 1350)
        S.draw_lines(dl, (118, 712), lines, f, S.TEXT, 88)
        if stop_index is not None:
            st = self.route.stops[stop_index]
            where = st.name if st.index == 0 else f"{st.name}  ·  mile {int(round(st.mile))}"
            dl.text((120, 712 + len(lines) * 88 + 36), where, font=S.font("semibold", 28), fill=S.TEAL, anchor="ls")
        img.alpha_composite(S.with_alpha(layer, a), (int((1 - a) * -30), 0))
        return img.convert("RGB")

    def intro_scene(self, seg, t):
        split = min(2.8, seg.dur * 0.35)
        if t < split:
            img = self._title_card(t)
            return img
        if t < split + XFADE:
            return Image.blend(self._title_card(split), self._stats_card(t - split), S.smooth((t - split) / XFADE))
        return self._stats_card(t - split)

    def _title_card(self, t):
        route = self.route
        img = Image.new("RGBA", (S.W, S.H), S.BG_TITLE + (255,))
        layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        d.text((S.W / 2, 412), (route.series or "Road trips").upper(), font=S.font("bold", 26), fill=S.ORANGE, anchor="mm")
        f = S.font("display", 120)
        if f.getlength(route.title) > 1700:
            f = S.font("display", int(120 * 1700 / f.getlength(route.title)))
        d.text((S.W / 2, 515), route.title, font=f, fill=S.TEXT, anchor="mm")
        bits = [f"{S.fmt_int(route.total_miles)} miles", f"{self.n} stops"]
        passes = [p for p in route.passes if (p.elevation_ft or 0) >= 10000]
        if passes:
            bits.append(f"{len(passes)} passes over 10,000 ft")
        if route.days:
            bits.append(f"{route.days} days")
        d.text((S.W / 2, 640), "  ·  ".join(bits), font=S.font("regular", 32), fill=S.TEXT_DIM, anchor="mm")
        a = S.ease_out(t / 0.5)
        img.alpha_composite(S.with_alpha(layer, a), (0, int((1 - a) * 20)))
        pa = S.ease_out((t - 0.7) / 0.4)
        f2 = S.font("bold", 17)
        text = "FULL TRIP PLANNER AT THE END"
        self._pill(img, text, int(S.W / 2 - (f2.getlength(text) + 36) / 2), 760, pa)
        return img.convert("RGB")

    def _stat_cards(self):
        route = self.route
        high, high_name = route.high_point()
        low, low_name = route.low_point()
        names = [s.name for s in route.stops]
        stops_note = ", ".join(names[:3]) + (f" and {len(names) - 3} more" if len(names) > 3 else "")
        passes = [p for p in route.passes if (p.elevation_ft or 0) >= 10000]
        hours = route.total_drive_minutes / 60
        cards = [
            (route.total_miles, "", "TOTAL MILES", "Full route, start to finish"),
            (high - low, "", "FT ELEVATION CHANGE",
             f"{S.fmt_int(low)} ft near {low_name} to {S.fmt_int(high)} ft near {high_name}"),
            (len(names), "", "STOPS ON THE ROUTE", stops_note),
            (hours, "h", "HOURS OF DRIVING", "Behind the wheel, without stops"),
            (None, route.days.replace(" to ", "–") if route.days else "–", "DAYS RECOMMENDED",
             f"Best season: {route.best_season}" if route.best_season else "Time for the stops, not just the drive"),
        ]
        if passes:
            cards.append((len(passes), "", "PASSES OVER 10,000 FT", ", ".join(p.name for p in passes)))
        else:
            cards.append((route.climb_ft, "", "FT OF CLIMBING", "Total uphill along the way"))
        return cards

    def _stats_card(self, t):
        img = Image.new("RGBA", (S.W, S.H), S.BG_TITLE + (255,))
        d = ImageDraw.Draw(img)
        d.text((140, 100), "BY THE NUMBERS", font=S.font("bold", 24), fill=S.ORANGE, anchor="lm")
        d.text((138, 185), self.route.title, font=S.font("display", 60), fill=S.TEXT, anchor="ls")
        for k, (value, text, label, note) in enumerate(self._stats):
            col, row = k % 3, k // 3
            x, y = 140 + col * 560, 250 + row * 370
            a = S.ease_out((t - 0.1 * k) / 0.45)
            card = Image.new("RGBA", (520, 330), (0, 0, 0, 0))
            card.alpha_composite(S.rounded_box(520, 330, 22, S.CARD + (255,), S.CARD_BORDER + (255,), 2))
            dc = ImageDraw.Draw(card)
            dc.rectangle((36, 40, 92, 45), fill=S.ORANGE)
            count = S.ease_out((t - 0.1 * k) / 1.1)
            if value is None:
                shown = text
            elif text == "h":
                shown = f"{value * count:.1f}".rstrip("0").rstrip(".")
            else:
                shown = S.fmt_int(value * count) if value >= 1000 else str(int(round(value * count)))
            dc.text((32, 178), shown, font=S.font("display", 120), fill=S.TEXT, anchor="ls")
            dc.text((36, 218), label, font=S.font("bold", 22), fill=S.TEAL, anchor="lm")
            f = S.font("regular", 22)
            S.draw_lines(dc, (36, 243), S.wrap(note, f, 450)[:2], f, S.TEXT_DIM, 28)
            img.alpha_composite(S.with_alpha(card, a), (x, y + int((1 - a) * 24)))
        return img.convert("RGB")

    def planner_scene(self, seg, t):
        route = self.route
        img = Image.new("RGBA", (S.W, S.H), S.BG_TITLE + (255,))
        d = ImageDraw.Draw(img)
        d.text((120, 92), "PLAN YOUR TRIP", font=S.font("bold", 24), fill=S.ORANGE, anchor="lm")
        d.text((118, 170), route.title, font=S.font("display", 58), fill=S.TEXT, anchor="ls")
        # Itinerary
        top, bottom = 215, 1010
        rh = min(118, (bottom - top) // len(route.stops))
        d.text((120, top + 8), "STOP", font=S.font("semibold", 15), fill=S.TEXT_DIM, anchor="lm")
        for label, x in (("MILE", 720), ("ELEV", 850), ("FROM LAST STOP", 1080)):
            d.text((x, top + 8), label, font=S.font("semibold", 15), fill=S.TEXT_DIM, anchor="rm")
        for k, st in enumerate(route.stops):
            ra = S.ease_out((t - 0.2 - 0.09 * k) / 0.4)
            row = Image.new("RGBA", (1000, rh), (0, 0, 0, 0))
            dr = ImageDraw.Draw(row)
            cy = rh / 2 + 6
            dr.line((0, 1, 960, 1), fill=(32, 44, 54), width=2)
            S.paste_center(row, S.circle(34, S.ORANGE + (255,)), 17, cy)
            dr.text((17, cy + 0.5), str(k + 1), font=S.font("bold", 17), fill=S.BG_TITLE, anchor="mm")
            dr.text((56, cy - 12), st.name, font=S.font("semibold", 27), fill=S.TEXT, anchor="lm")
            first = next(iter(st.info.values()), "") if st.info else ""
            sub = S.wrap(first, S.font("regular", 18), 470)
            if sub:
                dr.text((56, cy + 18), sub[0] + ("…" if len(sub) > 1 else ""), font=S.font("regular", 18),
                        fill=S.TEXT_DIM, anchor="lm")
            dr.text((600, cy), "0" if k == 0 else str(int(round(st.mile))), font=S.font("medium", 24),
                    fill=S.TEXT, anchor="rm")
            dr.text((730, cy), f"{S.fmt_int(st.elevation_ft)} ft", font=S.font("regular", 22), fill=S.TEXT, anchor="rm")
            leg = "start" if k == 0 else f"{st.miles} mi · {S.fmt_minutes(st.drive_minutes)}"
            dr.text((960, cy), leg, font=S.font("regular", 22), fill=S.TEAL if k else S.TEXT_DIM, anchor="rm")
            img.alpha_composite(S.with_alpha(row, ra), (120 + int((1 - ra) * 20), top + 24 + k * rh))
        # Side cards
        x0, w = 1200, 600
        y = 215
        facts = [("TOTAL", f"{S.fmt_int(route.total_miles)} miles · {S.fmt_minutes(route.total_drive_minutes)}")]
        if route.days:
            facts.append(("TAKE", f"{route.days} days"))
        if route.best_season:
            facts.append(("BEST SEASON", route.best_season))
        for k, (label, value) in enumerate(facts):
            a = S.ease_out((t - 0.5 - 0.12 * k) / 0.4)
            card = Image.new("RGBA", (w, 96), (0, 0, 0, 0))
            card.alpha_composite(S.rounded_box(w, 96, 16, S.CARD + (255,), S.CARD_BORDER + (255,), 2))
            dc = ImageDraw.Draw(card)
            dc.text((26, 30), label, font=S.font("bold", 15), fill=S.TEAL, anchor="lm")
            dc.text((26, 66), value, font=S.font("semibold", 26), fill=S.TEXT, anchor="lm")
            img.alpha_composite(S.with_alpha(card, a), (x0, y))
            y += 112
        if route.tips:
            a = S.ease_out((t - 0.9) / 0.4)
            f = S.font("regular", 21)
            blocks = [S.wrap(tip, f, w - 70) for tip in route.tips]
            h = 64 + sum(len(b) * 29 + 14 for b in blocks)
            card = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            card.alpha_composite(S.rounded_box(w, h, 16, S.CARD + (255,), S.CARD_BORDER + (255,), 2))
            dc = ImageDraw.Draw(card)
            dc.text((26, 32), "GOOD TO KNOW", font=S.font("bold", 15), fill=S.ORANGE, anchor="lm")
            yy = 58
            for b in blocks:
                S.paste_center(card, S.circle(8, S.ORANGE + (255,)), 32, yy + 14)
                S.draw_lines(dc, (48, yy), b, f, S.TEXT, 29)
                yy += len(b) * 29 + 14
            img.alpha_composite(S.with_alpha(card, a), (x0, y))
        d.text((120, 1040), "Details in the description.", font=S.font("regular", 18), fill=S.TEXT_FAINT, anchor="lm")
        return img.convert("RGB")

    def end_scene(self, seg, t):
        route = self.route
        img = Image.new("RGBA", (S.W, S.H), S.BG_TITLE + (255,))
        a = S.ease_out(t / 0.5)
        layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        d.text((140, 265), "THANKS FOR RIDING ALONG", font=S.font("bold", 22), fill=S.ORANGE, anchor="lm")
        d.text((136, 375), route.title, font=S.font("display", 90), fill=S.TEXT, anchor="ls")
        bits = [f"{S.fmt_int(route.total_miles)} miles", f"{self.n} stops"]
        if route.days:
            bits.append(f"{route.days} days")
        d.text((140, 440), "  ·  ".join(bits), font=S.font("regular", 30), fill=S.TEXT_DIM, anchor="lm")
        layer.alpha_composite(S.rounded_box(258, 76, 38, S.ORANGE + (255,)), (140, 538))
        d.text((269, 576), "SUBSCRIBE", font=S.font("bold", 25), fill=S.BG_TITLE, anchor="mm")
        d.text((428, 576), "for more road trips", font=S.font("medium", 27), fill=S.TEXT, anchor="lm")
        img.alpha_composite(S.with_alpha(layer, a), (0, int((1 - a) * 16)))
        up = route.up_next
        if up.get("title"):
            ca = S.ease_out((t - 0.35) / 0.5)
            cw, ch = 650, 470
            card = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
            card.alpha_composite(S.rounded_box(cw, ch, 22, (17, 27, 35, 255), S.CARD_BORDER + (255,), 2))
            art = placeholder_art((cw - 28, 250), 3)
            mask = S.rounded_box(cw - 28, 250, 14, (255, 255, 255, 255)).getchannel("A")
            card.paste(art, (14, 14), mask)
            dc = ImageDraw.Draw(card)
            dc.text((30, 312), "UP NEXT", font=S.font("bold", 18), fill=S.ORANGE, anchor="lm")
            dc.text((28, 372), up["title"], font=S.font("display", 46), fill=S.TEXT, anchor="ls")
            sub = up.get("subtitle", "")
            if up.get("miles"):
                sub = f"{sub}  ·  {up['miles']} miles" if sub else f"{up['miles']} miles"
            dc.text((30, 414), sub, font=S.font("regular", 22), fill=S.TEXT_DIM, anchor="lm")
            img.alpha_composite(S.with_alpha(card, ca), (1135, 238 + int((1 - ca) * 20)))
        return img.convert("RGB")


def drive_progress(p):
    """Leg progress with a gentle pull-away and roll-in, linear in the middle."""
    p = S.clamp(p)
    e = 0.18
    if p < e:
        return p * p / (2 * e * (1 - e))
    if p > 1 - e:
        q = 1 - p
        return 1 - q * q / (2 * e * (1 - e))
    return (p - e / 2) / (1 - e)


_GRADIENT = None


def _gradient_overlay():
    global _GRADIENT
    if _GRADIENT is None:
        y = np.linspace(0, 1, S.H)[:, None]
        x = np.linspace(0, 1, S.W)[None, :]
        alpha = np.clip(0.15 + 0.85 * np.clip((y - 0.35) / 0.65, 0, 1) ** 1.2 + 0.35 * (1 - x) ** 2, 0, 0.93)
        top = np.clip(1 - y / 0.22, 0, 1) * 0.55
        alpha = np.maximum(alpha, top)
        arr = np.zeros((S.H, S.W, 4), np.uint8)
        arr[..., :3] = S.BG_TITLE
        arr[..., 3] = (alpha * 255).astype(np.uint8)
        _GRADIENT = Image.fromarray(arr, "RGBA")
    return _GRADIENT


def placeholder_art(size, index):
    """Illustrated mountains-and-sun card (the reference's photo slot), used when a stop has no photo."""
    w, h = size
    sky = np.array(SKY[index % len(SKY)], np.float32)
    ss = 2
    img = Image.new("RGB", (w * ss, h * ss))
    grad = np.linspace(1.0, 0.55, h * ss)[:, None, None] * sky
    img = Image.fromarray(np.broadcast_to(grad, (h * ss, w * ss, 3)).astype(np.uint8))
    d = ImageDraw.Draw(img)
    sun = tuple(int(min(255, c * 1.25 + 60)) for c in sky)
    r = int(h * 0.11 * ss)
    d.ellipse((int(w * 0.75 * ss) - r, int(h * 0.25 * ss) - r, int(w * 0.75 * ss) + r, int(h * 0.25 * ss) + r), fill=sun)
    rng = np.random.default_rng(index + 1)
    for layer, shade in enumerate((0.55, 0.38, 0.24)):
        base = h * (0.55 + layer * 0.14)
        pts = [(0, h * ss)]
        for x in np.linspace(0, w, 8):
            pts.append((x * ss, (base - rng.uniform(0.05, 0.3) * h) * ss))
        pts.append((w * ss, h * ss))
        d.polygon(pts, fill=tuple(int(c * shade) for c in sky))
    return img.resize(size, Image.LANCZOS).filter(ImageFilter.SMOOTH)
