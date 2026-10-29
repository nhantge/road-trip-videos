"""The animated map: a terrain-shaded basemap rendered once at high resolution,
then cropped per frame by a camera, with the driven part of the route in orange.

Also draws the map-side furniture from the reference layout: the HUD (mile counter
and elevation), the region inset, captions and the elevation strip.
"""

import math

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from . import style as S
from .terrain import hillshade, lonlat_to_world

ZMAX = 3.4      # basemap resolution, in multiples of the overview zoom
ZFOLLOW = 2.9   # zoom while following the car
MARGIN = 0.2    # basemap extends this far past the overview view on each side
PAD = dict(left=0.09, right=0.09, top=0.25, bottom=0.2)  # keep the overview clear of HUD/inset


class MapView:
    def __init__(self, route, terrain):
        self.route = route
        self.terrain = terrain
        wx, wy = route.wx, route.wy
        avail_w = S.MAP_W * (1 - PAD["left"] - PAD["right"])
        avail_h = S.MAP_H * (1 - PAD["top"] - PAD["bottom"])
        self.u0 = max((wx.max() - wx.min()) / avail_w, (wy.max() - wy.min()) / avail_h)
        cx = (wx.min() + wx.max()) / 2 - (PAD["left"] - PAD["right"]) / 2 * S.MAP_W * self.u0
        cy = (wy.min() + wy.max()) / 2 - (PAD["top"] - PAD["bottom"]) / 2 * S.MAP_H * self.u0
        self.overview = (cx, cy)
        self.scale = ZMAX / self.u0  # basemap px per world unit
        self.bw = int(S.MAP_W * (1 + 2 * MARGIN) * ZMAX)
        self.bh = int(S.MAP_H * (1 + 2 * MARGIN) * ZMAX)
        self.ox = cx - self.bw / 2 / self.scale  # world coords of basemap pixel (0, 0)
        self.oy = cy - self.bh / 2 / self.scale
        self._build()
        self._build_profile()

    # -- coordinates ---------------------------------------------------------

    def to_base(self, x, y):
        return (np.asarray(x) - self.ox) * self.scale, (np.asarray(y) - self.oy) * self.scale

    def view_box(self, center, zoom):
        bx, by = self.to_base(*center)
        hw = S.MAP_W / 2 * ZMAX / zoom
        hh = S.MAP_H / 2 * ZMAX / zoom
        bx = min(max(bx, hw), self.bw - hw)
        by = min(max(by, hh), self.bh - hh)
        return (bx - hw, by - hh, bx + hw, by + hh)

    def follow_center(self, mile):
        """Camera target: a short average around the car so turns don't jerk the view."""
        pts = [self.route.point_at(mile + d) for d in (-4, -2, 0, 2, 4, 6)]
        return float(np.mean([p[0] for p in pts])), float(np.mean([p[1] for p in pts]))

    # -- basemap -------------------------------------------------------------

    def _build(self):
        bw, bh, sc = self.bw, self.bh, self.scale
        rgb = np.empty((bh, bw, 3), np.float32)
        rgb[:] = S.BG_MAP
        elev = self._terrain_grid()
        if elev is not None:
            meters_per_px = 40075016 * math.cos(math.radians(self.route.stops[0].lat)) / (sc * 1.0)
            shade = hillshade(elev, meters_per_px)
            lo, hi = np.percentile(elev, [5, 98])
            height = np.clip((elev - lo) / max(hi - lo, 1), 0, 1)
            light = (shade - 0.62) * 34 + height * 7
            rgb += light[..., None] * np.array([0.85, 0.95, 1.1], np.float32)
        # Grid
        g = int(115 * ZMAX)
        lw = max(1, int(ZMAX * 0.9))
        for x in range(g // 2, bw, g):
            rgb[:, x:x + lw] = rgb[:, x:x + lw] * 0.5 + np.array(S.GRID) * 0.5 + 2
        for y in range(g // 2, bh, g):
            rgb[y:y + lw, :] = rgb[y:y + lw, :] * 0.5 + np.array(S.GRID) * 0.5 + 2

        ss = 2  # supersample vector layers for antialiasing
        bx, by = self.to_base(self.route.wx, self.route.wy)
        line = [(float(x) * ss, float(y) * ss) for x, y in zip(bx, by)]

        if elev is not None:
            glyphs = Image.new("L", (bw * ss, bh * ss), 0)
            d = ImageDraw.Draw(glyphs)
            rng = np.random.default_rng(7)
            step = int(62 * ZMAX)
            thresh = np.percentile(elev, 62)
            size = 17 * ZMAX * ss
            for gy in range(step // 2, bh, step):
                for gx in range(step // 2, bw, step):
                    jx, jy = rng.uniform(-0.4, 0.4, 2) * step
                    px, py = int(gx + jx), int(gy + jy)
                    if 0 <= px < bw and 0 <= py < bh and elev[py, px] > thresh:
                        s = size * rng.uniform(0.75, 1.15)
                        cx, cy = px * ss, py * ss
                        d.line([(cx - s / 2, cy + s * 0.32), (cx, cy - s * 0.32), (cx + s / 2, cy + s * 0.32)],
                               fill=255, width=int(1.5 * ZMAX * ss), joint="curve")
            self._blend(rgb, glyphs.reduce(ss), S.GLYPH, 0.75)

        grey = Image.new("L", (bw * ss, bh * ss), 0)
        ImageDraw.Draw(grey).line(line, fill=255, width=int(2.4 * ZMAX * ss), joint="curve")
        self._blend(rgb, grey.reduce(ss), S.ROUTE_GREY, 1.0)
        self.base = Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8), "RGB")

        core = Image.new("L", (bw * ss, bh * ss), 0)
        ImageDraw.Draw(core).line(line, fill=255, width=int(4.0 * ZMAX * ss), joint="curve")
        self.core = core.reduce(ss)
        glow = Image.new("L", (bw, bh), 0)
        ImageDraw.Draw(glow).line([(x / ss, y / ss) for x, y in line], fill=255, width=int(11 * ZMAX), joint="curve")
        self.glow = glow.filter(ImageFilter.GaussianBlur(3 * ZMAX))
        # Which route segment covers each pixel, so the orange line can be revealed by distance.
        idx = Image.new("I", (bw, bh), 0)
        di = ImageDraw.Draw(idx)
        w = int(16 * ZMAX)
        for k in range(len(bx) - 1):
            di.line([(bx[k], by[k]), (bx[k + 1], by[k + 1])], fill=k + 1, width=w)
            di.ellipse((bx[k + 1] - w / 2, by[k + 1] - w / 2, bx[k + 1] + w / 2, by[k + 1] + w / 2), fill=k + 1)
        self.idx = idx

    @staticmethod
    def _blend(rgb, mask_img, color, strength):
        a = np.asarray(mask_img, np.float32)[..., None] / 255 * strength
        rgb *= 1 - a
        rgb += a * np.array(color, np.float32)

    def _terrain_grid(self):
        """Elevation (m) resampled onto the basemap grid, or None."""
        if self.terrain is None or self.route.flat:  # flat routes: shaded sea floor only adds noise
            return None
        x0, y0 = self.ox, self.oy
        x1, y1 = self.ox + self.bw / self.scale, self.oy + self.bh / self.scale
        z = int(math.ceil(math.log2(self.scale / 2 / 256)))
        while z > 4 and ((x1 - x0) * 2 ** z + 1) * ((y1 - y0) * 2 ** z + 1) > 260:
            z -= 1
        z = min(z, 12)
        res = self.terrain.mosaic(max(x0, 0), max(y0, 0), min(x1, 1), min(y1, 1), z)
        if res is None:
            return None
        arr, mx, my, msc = res
        img = Image.fromarray(arr.astype(np.float32), "F")
        box = ((x0 - mx) * msc, (y0 - my) * msc, (x1 - mx) * msc, (y1 - my) * msc)
        out = img.resize((self.bw, self.bh), Image.BILINEAR, box=box)
        return np.asarray(out, np.float32)

    # -- per frame -----------------------------------------------------------

    def render(self, center, zoom, mile, t, visited, current=None, pulse=True):
        """Map viewport image for one frame.

        visited: number of stops reached (their markers turn orange and numbered).
        current: index of the stop the car is parked at, if any.
        """
        box = self.view_box(center, zoom)
        size = (S.MAP_W, S.MAP_H)
        rgb = np.asarray(self.base.resize(size, Image.BILINEAR, box=box), np.float32)
        if mile > 0:
            cut = self.route.index_at(mile)
            seg = np.asarray(self.idx.resize(size, Image.NEAREST, box=box))
            on = ((seg > 0) & (seg - 1 <= cut)).astype(np.float32)[..., None]
            glow = np.asarray(self.glow.resize(size, Image.BILINEAR, box=box), np.float32)[..., None] / 255 * on
            core = np.asarray(self.core.resize(size, Image.BILINEAR, box=box), np.float32)[..., None] / 255 * on
            orange = np.array(S.ORANGE, np.float32)
            rgb = rgb * (1 - glow * 0.42) + orange * 0.85 * glow * 0.42
            rgb = rgb * (1 - core) + orange * core
        img = Image.fromarray(rgb.clip(0, 255).astype(np.uint8), "RGB").convert("RGBA")

        k = S.MAP_W / (box[2] - box[0])  # screen px per basemap px
        def screen(x, y):
            bx, by = self.to_base(x, y)
            return (bx - box[0]) * k, (by - box[1]) * k

        s = 1 + 0.5 * S.clamp((zoom - 1) / (ZFOLLOW - 1))  # labels grow a bit when zoomed in
        draw = ImageDraw.Draw(img)
        route = self.route
        shields = self._draw_shields(img, draw, screen, s)
        taken = [(0, 0, 460, 215), (945, 0, S.MAP_W, 190)] + shields  # HUD, inset, road shields
        car = screen(*route.point_at(mile))
        taken.append((car[0] - 18, car[1] - 18, car[0] + 18, car[1] + 18))
        labels = []  # (priority, x, y, marker, text, font, color, gap)
        for st in route.stops:
            x, y = screen(*lonlat_to_world(st.lon, st.lat))
            if st.index == current:
                marker, gap = None, 22 * s
            elif st.index < visited:
                marker, gap = "visited", 17 * s
            else:
                marker, gap = "upcoming", 13 * s
            labels.append((0, x, y, marker, st, S.font("semibold", 17 * s), S.LABEL, gap))
        for p in route.places:
            x, y = screen(*lonlat_to_world(p.lon, p.lat))
            if p.kind in ("pass", "summit"):
                labels.append((1, x, y, "pass", p, S.font("medium", 13 * s), S.LABEL_DIM, 12 * s))
            else:
                labels.append((1, x, y, "town", p, S.font("semibold", 14 * s), S.LABEL_DIM, 10 * s))
        for st in route.stops:
            for sight in st.sights:
                if sight.lat is not None and sight.lon is not None:
                    x, y = screen(*lonlat_to_world(sight.lon, sight.lat))
                    labels.append((1, x, y, "sight", sight, S.font("semibold", 14 * s), S.ORANGE, 11 * s))
        for prio, x, y, marker, obj, fnt, color, gap in labels:
            if not (-150 < x < S.MAP_W + 150 and -50 < y < S.MAP_H + 50):
                continue
            if marker == "visited":
                S.paste_center(img, S.circle(int(24 * s), S.ORANGE + (255,)), x, y)
                draw.text((x, y + 0.5), str(obj.index + 1), font=S.font("bold", 13 * s), fill=S.BG_TITLE, anchor="mm")
            elif marker == "upcoming":
                S.paste_center(img, S.circle(int(13 * s), S.BG_MAP + (255,), S.LABEL + (255,), 3), x, y)
            elif marker == "pass":
                S.paste_center(img, S.triangle(int(12 * s), (150, 160, 170, 255)), x, y)
            elif marker == "sight":
                S.paste_center(img, S.diamond(int(15 * s), S.ORANGE + (255,), S.BG_MAP + (255,)), x, y)
            elif marker == "town":
                S.paste_center(img, S.circle(int(9 * s), None, S.LABEL_DIM + (255,), 2), x, y)
            tw, th = fnt.getlength(obj.name), fnt.size
            for anchor, lx, ly in (("lm", x + gap, y), ("rm", x - gap, y), ("ms", x, y - gap * 0.7), ("mt", x, y + gap * 0.7)):
                left = lx if anchor == "lm" else lx - tw if anchor == "rm" else lx - tw / 2
                top = ly - th / 2 if anchor in ("lm", "rm") else ly - th if anchor == "ms" else ly
                rect = (left - 3, top - 2, left + tw + 3, top + th + 2)
                off = rect[0] < 4 or rect[2] > S.MAP_W - 4  # would run off the map
                if not off and not any(rect[0] < r[2] and rect[2] > r[0] and rect[1] < r[3] and rect[3] > r[1] for r in taken):
                    break
            else:
                if prio:
                    continue  # minor labels give way
                anchor, lx, ly = "lm", x + gap, y
                rect = (lx, y - th / 2, lx + tw, y + th / 2)
            taken.append(rect)
            draw.text((lx, ly), obj.name, font=fnt, fill=color, anchor=anchor, stroke_width=3, stroke_fill=S.BG_MAP)
        # The car.
        cx, cy = car
        phase = (t * 1.1) % 1 if pulse else 0.35
        S.paste_center(img, S.circle(int(30 + 34 * phase), S.ORANGE + (int(110 * (1 - phase)),)), cx, cy)
        S.paste_center(img, S.circle(30, S.ORANGE + (255,)), cx, cy)
        S.paste_center(img, S.circle(13, (255, 255, 255, 255)), cx, cy)
        return img

    def _draw_shields(self, img, draw, screen, s):
        route = self.route
        rects = []
        for st in route.stops[1:]:
            if not st.road:
                continue
            prev = route.stops[st.index - 1]
            m = (prev.mile + st.mile) / 2
            x0, y0 = screen(*route.point_at(m - 1))
            x1, y1 = screen(*route.point_at(m + 1))
            nx, ny = -(y1 - y0), x1 - x0
            n = math.hypot(nx, ny) or 1
            x, y = (x0 + x1) / 2 + nx / n * 30 * s, (y0 + y1) / 2 + ny / n * 30 * s
            if not (0 < x < S.MAP_W and 0 < y < S.MAP_H):
                continue
            fnt = S.font("bold", 11.5 * s)
            tw = fnt.getlength(st.road)
            box = S.rounded_box(int(tw + 14 * s), int(20 * s), int(4 * s), (22, 32, 42, 235), (74, 89, 103, 255), 1)
            S.paste_center(img, box, x, y)
            draw.text((x, y + 0.5), st.road, font=fnt, fill=(164, 176, 184), anchor="mm")
            rects.append((x - box.width / 2, y - box.height / 2, x + box.width / 2, y + box.height / 2))
        return rects

    # -- HUD, inset, caption -------------------------------------------------

    def draw_hud(self, img, mile, elevation_ft):
        route = self.route
        img.alpha_composite(S.rounded_box(428, 180, 14, S.HUD_BG + (238,), (40, 52, 62, 255), 2), (25, 25))
        d = ImageDraw.Draw(img)
        d.text((48, 57), route.title.upper(), font=S.font("bold", 25), fill=S.TEXT, anchor="lm")
        if route.region:
            d.text((48, 86), route.region, font=S.font("regular", 17), fill=S.TEXT_DIM, anchor="lm")
        d.line((48, 106, 429, 106), fill=(49, 64, 78), width=2)
        d.text((48, 126), "MILE", font=S.font("semibold", 14), fill=S.TEXT_DIM, anchor="lm")
        d.text((262, 126), "TO GO" if route.flat else "ELEVATION", font=S.font("semibold", 14), fill=S.TEXT_DIM,
               anchor="lm")
        big = S.font("display", 52)
        val = str(int(mile + 0.5))
        d.text((46, 187), val, font=big, fill=S.TEXT, anchor="ls")
        d.text((56 + big.getlength(val), 184), f"of {int(round(route.total_miles))}",
               font=S.font("regular", 21), fill=S.TEXT_DIM, anchor="ls")
        right = f"{S.fmt_int(max(0, route.total_miles - mile))} mi" if route.flat else f"{S.fmt_int(elevation_ft)} ft"
        d.text((261, 180), right, font=S.font("display", 34), fill=S.TEXT, anchor="ls")

    def draw_inset(self, img, mile):
        inset = self.route.inset
        if not inset.get("bounds"):
            return
        x0, y0, w, h = 953, 25, 182, 155
        img.alpha_composite(S.rounded_box(w, h, 14, S.HUD_BG + (238,), (40, 52, 62, 255), 2), (x0, y0))
        d = ImageDraw.Draw(img)
        d.text((x0 + 17, y0 + 21), inset.get("name", "").upper(), font=S.font("semibold", 13), fill=S.TEXT_DIM, anchor="lm")
        west, south, east, north = inset["bounds"]
        bx0, by0 = lonlat_to_world(west, north)
        bx1, by1 = lonlat_to_world(east, south)
        iw, ih = w - 34, h - 56
        k = min(iw / (bx1 - bx0), ih / (by1 - by0))
        rw, rh = (bx1 - bx0) * k, (by1 - by0) * k
        rx, ry = x0 + 17 + (iw - rw) / 2, y0 + 40 + (ih - rh) / 2
        to = lambda x, y: (rx + (x - bx0) * k, ry + (y - by0) * k)
        if inset.get("outline"):  # state shape as [[lon, lat], ...]; default is the bounds box
            d.polygon([to(*lonlat_to_world(lon, lat)) for lon, lat in inset["outline"]], outline=(150, 159, 167), width=2)
        else:
            d.rectangle((rx, ry, rx + rw, ry + rh), outline=(150, 159, 167), width=2)
        pts = [to(x, y) for x, y in zip(self.route.wx[::4], self.route.wy[::4])]
        d.line(pts, fill=S.ROUTE_GREY, width=2)
        cut = int(self.route.index_at(mile) / 4) + 1
        if cut > 1:
            d.line(pts[:cut], fill=S.ORANGE, width=2)
        city = inset.get("city")
        if city:
            cxy = to(*lonlat_to_world(city["lon"], city["lat"]))
            S.paste_center(img, S.circle(6, S.LABEL + (255,)), *cxy)
            fnt = S.font("medium", 13)
            right_side = cxy[0] + 8 + fnt.getlength(city["name"]) < x0 + w - 8  # else label left of the dot
            d.text((cxy[0] + (8 if right_side else -8), cxy[1]), city["name"], font=fnt,
                   fill=S.LABEL_DIM, anchor="lm" if right_side else "rm")
        S.paste_center(img, S.circle(13, S.ORANGE + (255,)), *to(*self.route.point_at(mile)))

    @staticmethod
    def draw_caption(img, text, alpha):
        if not text or alpha <= 0:
            return
        fnt = S.font("semibold", 30)
        lines = S.wrap(text, fnt, 860)
        if len(lines) > 2:
            fnt = S.font("semibold", 26)
            lines = S.wrap(text, fnt, 900)
        lh = int(fnt.size * 1.33)
        bw = int(max(fnt.getlength(l) for l in lines) + 56)
        bh = lh * len(lines) + 26
        layer = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
        layer.alpha_composite(S.rounded_box(bw, bh, 12, S.CAPTION_BG + (232,)))
        d = ImageDraw.Draw(layer)
        for i, line in enumerate(lines):
            d.text((bw / 2, 13 + lh * i + lh / 2), line, font=fnt, fill=S.TEXT, anchor="mm")
        y = 885 - bh + int((1 - S.ease_out(alpha)) * 14)
        img.alpha_composite(S.with_alpha(layer, alpha), (int(S.MAP_W / 2 - bw / 2), y))

    # -- elevation strip -----------------------------------------------------

    PX0, PX1, PY0, PY1 = 64, 1112, 968, 1036

    def _build_profile(self):
        route = self.route
        lo, hi = route.prof_ft.min(), route.prof_ft.max()
        self._prof_lo, self._prof_hi = lo, hi
        xs = self.PX0 + route.prof_mi / route.total_miles * (self.PX1 - self.PX0)
        ys = self.PY1 - (route.prof_ft - lo) / max(hi - lo, 1) * (self.PY1 - self.PY0)
        if route.flat:  # no elevation story at sea level: the strip becomes a progress bar
            ys = np.full_like(route.prof_ft, self.PY1 - 12.0)
        self._prof_xy = (xs, ys)
        w, h = S.MAP_W, S.H - S.ELEV_Y
        ss = 3

        def layer(fill, line):
            im = Image.new("RGBA", (w * ss, h * ss), (0, 0, 0, 0))
            d = ImageDraw.Draw(im)
            pts = [(x * ss, (y - S.ELEV_Y) * ss) for x, y in zip(xs, ys)]
            d.polygon(pts + [(self.PX1 * ss, (self.PY1 - S.ELEV_Y) * ss), (self.PX0 * ss, (self.PY1 - S.ELEV_Y) * ss)], fill=fill)
            d.line(pts, fill=line, width=2 * ss, joint="curve")
            return im.resize((w, h), Image.LANCZOS)

        self.prof_grey = layer((29, 40, 51, 255), (74, 89, 103, 255))
        self.prof_orange = layer(S.ORANGE_DARK + (255,), S.ORANGE + (255,))

        static = Image.new("RGBA", (w, h), S.BG_PANEL + (255,))
        d = ImageDraw.Draw(static)
        d.line((0, 0, w, 0), fill=S.DIVIDER, width=2)
        head = "ROUTE" if route.flat else "ELEVATION"
        d.text((48, 22), head, font=S.font("semibold", 14), fill=S.TEXT_DIM, anchor="lm")
        note = "stop by stop" if route.flat else "feet above sea level" if route.elevation_from_terrain else "approximate"
        d.text((48 + S.font("semibold", 14).getlength(head) + 12, 22), note,
               font=S.font("regular", 14), fill=S.TEXT_FAINT, anchor="lm")
        d.line((self.PX0, self.PY1 - S.ELEV_Y, self.PX1, self.PY1 - S.ELEV_Y), fill=(40, 52, 62), width=1)
        fnt = S.font("medium", 13)
        last = -1e9
        for st in route.stops:
            x = self.PX0 + st.mile / route.total_miles * (self.PX1 - self.PX0)
            d.line((x, self.PY1 - S.ELEV_Y, x, self.PY1 - S.ELEV_Y + 5), fill=S.TEXT_FAINT, width=1)
            anchor = "lm" if st.index == 0 else "rm" if st.index == len(route.stops) - 1 else "mm"
            tw = fnt.getlength(st.name)
            left = x if anchor == "lm" else x - tw if anchor == "rm" else x - tw / 2
            if left > last + 8:
                d.text((x, self.PY1 - S.ELEV_Y + 15), st.name, font=fnt, fill=S.TEXT_DIM, anchor=anchor)
                last = left + tw
        self.prof_static = static
        # Peak labels (passes) are drawn over the profile.
        self.prof_peaks = []
        for p in route.passes:
            elev = p.elevation_ft or route.elevation_at(p.mile)
            x = self.PX0 + p.mile / route.total_miles * (self.PX1 - self.PX0)
            y = self.PY1 - (elev - lo) / max(hi - lo, 1) * (self.PY1 - self.PY0)
            self.prof_peaks.append((x, y, f"{p.name.replace(' Pass', '')} {S.fmt_int(elev)} ft"))

    def draw_profile(self, img, mile):
        strip = self.prof_static.copy()
        strip.alpha_composite(self.prof_grey)
        xs, ys = self._prof_xy
        xcut = self.PX0 + mile / self.route.total_miles * (self.PX1 - self.PX0)
        if xcut > self.PX0 + 1:
            strip.alpha_composite(self.prof_orange.crop((0, 0, int(xcut), self.prof_orange.height)), (0, 0))
        d = ImageDraw.Draw(strip)
        fnt = S.font("medium", 13)
        last = -1e9
        for x, y, text in self.prof_peaks:
            tw = fnt.getlength(text)
            if x - tw / 2 > last + 6:
                d.text((x, y - S.ELEV_Y - 10), text, font=fnt, fill=S.LABEL, anchor="ms",
                       stroke_width=2, stroke_fill=S.BG_PANEL)
                last = x + tw / 2
        y = float(np.interp(xcut, xs, ys)) - S.ELEV_Y
        S.paste_center(strip, S.circle(16, S.ORANGE + (255,), (255, 255, 255, 255), 2), xcut, y)
        img.alpha_composite(strip, (0, S.ELEV_Y))
