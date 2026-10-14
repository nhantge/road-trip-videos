"""YouTube thumbnail (1280x720): a stop photo, a short punchy headline and a mini map
of the route, in the episode's colors."""

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageOps

from . import style as S
from .photos import pick_photos
from .scenes import placeholder_art

W, H = 1280, 720


def default_lines(route):
    return [f"{S.fmt_int(route.total_miles)} MILES", route.title.upper()]


def render(route, out_path):
    cfg = route.thumbnail
    lines = cfg.get("text") or default_lines(route)
    names = {s.name.lower(): s for s in route.stops}
    stop = names.get(str(cfg.get("stop", "")).lower()) or max(route.stops, key=lambda s: s.elevation_ft or 0)
    photos = pick_photos(stop, limit=0) if stop.photos else pick_photos(stop)
    img = _background(photos, cfg, stop.index)
    _shade(img)
    d = ImageDraw.Draw(img)

    # Headline: first line white, the rest orange, as big as fits.
    x, y = 60, 120 if len(lines) > 1 else 200
    for k, text in enumerate(lines):
        size = 150 if k == 0 else 92
        fnt = S.font("display", size)
        while fnt.getlength(text) > 760 and size > 40:
            size -= 4
            fnt = S.font("display", size)
        color = S.TEXT if k == 0 else S.ORANGE
        shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ImageDraw.Draw(shadow).text((x + 4, y + 6), text, font=fnt, fill=(0, 0, 0, 200), anchor="lt")
        img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(8)))
        d.text((x, y), text, font=fnt, fill=color, anchor="lt", stroke_width=2, stroke_fill=(0, 0, 0))
        y += int(size * 1.08)

    if route.series:
        f = S.font("bold", 26)
        tw = int(f.getlength(route.series.upper()) + 36)
        img.alpha_composite(S.rounded_box(tw, 48, 24, S.BG_TITLE + (230,)), (60, H - 96))
        d.text((60 + tw / 2, H - 72), route.series.upper(), font=f, fill=S.TEXT, anchor="mm")
    _map_card(img, route)
    img.convert("RGB").save(out_path, quality=92)
    return out_path


def _background(photos, cfg, index):
    if photos:
        path, _ = photos[min(int(cfg.get("photo", 0)), len(photos) - 1)]
        with Image.open(path) as im:
            im = ImageOps.exif_transpose(im).convert("RGB")
        zoom = float(cfg.get("zoom", 1.0))
        fx = float(cfg.get("focus", 0.5))
        w = int(W * zoom)
        h = int(H * zoom)
        im = ImageOps.fit(im, (w, h), Image.LANCZOS, centering=(fx, 0.5))
        left = int((w - W) * fx)
        im = im.crop((left, (h - H) // 2, left + W, (h - H) // 2 + H))
    else:
        im = placeholder_art((W, H), index)
    return im.convert("RGBA")


def _shade(img):
    """Darken the left side so the headline pops; lift contrast a touch."""
    x = np.linspace(0, 1, W)[None, :]
    y = np.linspace(0, 1, H)[:, None]
    alpha = np.clip(0.82 - 0.95 * x, 0, 0.82) + np.clip((y - 0.75) * 1.4, 0, 0.35)
    arr = np.zeros((H, W, 4), np.uint8)
    arr[..., :3] = S.BG_TITLE
    arr[..., 3] = (np.clip(alpha, 0, 0.9) * 255).astype(np.uint8)
    img.alpha_composite(Image.fromarray(arr, "RGBA"))


def _map_card(img, route):
    cw, ch = 330, 250
    x0, y0 = W - cw - 40, H - ch - 40
    card = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    card.alpha_composite(S.rounded_box(cw, ch, 18, S.BG_TITLE + (225,), S.CARD_BORDER + (255,), 2))
    d = ImageDraw.Draw(card)
    first, last = route.stops[0].name, route.stops[-1].name
    d.text((cw / 2, 30), f"{first.upper()} → {last.upper()}", font=S.font("bold", 20), fill=S.TEXT, anchor="mm")
    wx, wy = route.wx, route.wy
    pad, top = 34, 58
    k = min((cw - 2 * pad) / (wx.max() - wx.min()), (ch - top - pad) / (wy.max() - wy.min()))
    ox = (cw - (wx.max() - wx.min()) * k) / 2
    oy = top + (ch - top - pad - (wy.max() - wy.min()) * k) / 2
    ss = 3
    layer = Image.new("RGBA", (cw * ss, ch * ss), (0, 0, 0, 0))
    pts = [((ox + (x - wx.min()) * k) * ss, (oy + (y - wy.min()) * k) * ss) for x, y in zip(wx, wy)]
    dl = ImageDraw.Draw(layer)
    dl.line(pts, fill=S.ORANGE + (90,), width=14 * ss, joint="curve")
    dl.line(pts, fill=S.ORANGE + (255,), width=5 * ss, joint="curve")
    card.alpha_composite(layer.resize((cw, ch), Image.LANCZOS))
    for st in route.stops:
        i = route.stop_idx[st.index]
        S.paste_center(card, S.circle(14, S.ORANGE + (255,), (255, 255, 255, 255), 2), pts[i][0] / ss, pts[i][1] / ss)
    img.alpha_composite(card, (x0, y0))
