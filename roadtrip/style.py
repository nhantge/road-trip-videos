"""Palette, fonts and small drawing helpers shared by every scene.

Colors were sampled from the San Juan Skyway demo so new episodes keep its look.
"""

from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

REPO_ROOT = Path(__file__).resolve().parent.parent
FONT_DIR = REPO_ROOT / "assets" / "fonts"

W, H = 1920, 1080
FPS = 30

# Layout (from the reference): map on the left, info panel on the right,
# elevation strip under the map.
MAP_W, MAP_H = 1160, 910
PANEL_X = 1161
ELEV_Y = 912

BG_TITLE = (7, 12, 18)
BG_PANEL = (11, 16, 22)
BG_MAP = (15, 23, 30)
GRID = (19, 29, 37)
GLYPH = (40, 48, 55)
DIVIDER = (49, 64, 78)
CARD = (17, 27, 35)
CARD_BORDER = (51, 67, 78)
HUD_BG = (9, 17, 24)
ROUTE_GREY = (74, 89, 103)
ORANGE = (242, 163, 64)
ORANGE_DARK = (111, 74, 32)
TEAL = (110, 196, 182)
TEXT = (245, 242, 238)
TEXT_DIM = (150, 159, 167)
TEXT_FAINT = (98, 108, 118)
LABEL = (227, 233, 234)
LABEL_DIM = (160, 168, 175)
CAPTION_BG = (6, 10, 14)

WEIGHTS = {
    "regular": "Inter-Regular.otf",
    "medium": "Inter-Medium.otf",
    "semibold": "Inter-SemiBold.otf",
    "bold": "Inter-Bold.otf",
    "display": "InterDisplay-Bold.otf",
    "display-semibold": "InterDisplay-SemiBold.otf",
}


@lru_cache(maxsize=None)
def font(weight, size):
    return ImageFont.truetype(str(FONT_DIR / WEIGHTS[weight]), int(round(size)))


def text_width(text, fnt):
    return fnt.getlength(text)


def wrap(text, fnt, max_width):
    """Greedy word wrap; returns a list of lines."""
    lines, line = [], ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if line and fnt.getlength(trial) > max_width:
            lines.append(line)
            line = word
        else:
            line = trial
    if line:
        lines.append(line)
    return lines


def draw_lines(draw, xy, lines, fnt, fill, line_height, anchor="la"):
    x, y = xy
    for i, line in enumerate(lines):
        draw.text((x, y + i * line_height), line, font=fnt, fill=fill, anchor=anchor)
    return y + len(lines) * line_height


def rgba(color, alpha=255):
    return (*color[:3], int(alpha))


SS = 3  # supersampling factor for antialiased shapes


@lru_cache(maxsize=256)
def rounded_box(w, h, radius, fill, outline=None, width=1):
    """An antialiased rounded rectangle as an RGBA image (cached)."""
    w, h = int(w), int(h)
    big = Image.new("RGBA", (w * SS, h * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(big)
    d.rounded_rectangle((0, 0, w * SS - 1, h * SS - 1), radius * SS, fill=fill,
                        outline=outline, width=width * SS if outline else 0)
    return big.resize((w, h), Image.LANCZOS)


@lru_cache(maxsize=256)
def circle(diameter, fill, outline=None, width=0):
    d = int(diameter)
    big = Image.new("RGBA", (d * SS, d * SS), (0, 0, 0, 0))
    ImageDraw.Draw(big).ellipse((width * SS // 2, width * SS // 2, d * SS - 1 - width * SS // 2,
                                 d * SS - 1 - width * SS // 2), fill=fill, outline=outline,
                                width=width * SS)
    return big.resize((d, d), Image.LANCZOS)


@lru_cache(maxsize=64)
def triangle(size, fill):
    s = int(size)
    big = Image.new("RGBA", (s * SS, s * SS), (0, 0, 0, 0))
    ImageDraw.Draw(big).polygon([(s * SS / 2, 0), (s * SS, s * SS * 0.87), (0, s * SS * 0.87)], fill=fill)
    return big.resize((s, s), Image.LANCZOS)


def paste_center(canvas, sprite, x, y, alpha=1.0):
    if alpha < 1:
        sprite = with_alpha(sprite, alpha)
    canvas.alpha_composite(sprite, (int(round(x - sprite.width / 2)), int(round(y - sprite.height / 2))))


def with_alpha(img, alpha):
    if alpha >= 1:
        return img
    img = img.copy()
    a = img.getchannel("A").point(lambda v: int(v * max(0.0, alpha)))
    img.putalpha(a)
    return img


def soft_shadow(size, radius, blur=18, opacity=120):
    w, h = size
    pad = blur * 2
    img = Image.new("RGBA", (w + pad * 2, h + pad * 2), (0, 0, 0, 0))
    ImageDraw.Draw(img).rounded_rectangle((pad, pad, pad + w, pad + h), radius, fill=(0, 0, 0, opacity))
    return img.filter(ImageFilter.GaussianBlur(blur)), pad


# --- easing -----------------------------------------------------------------

def clamp(v, lo=0.0, hi=1.0):
    return lo if v < lo else hi if v > hi else v


def smooth(t):
    t = clamp(t)
    return t * t * (3 - 2 * t)


def ease_out(t):
    t = clamp(t)
    return 1 - (1 - t) ** 3


def ease_in_out(t):
    t = clamp(t)
    return 4 * t ** 3 if t < 0.5 else 1 - (-2 * t + 2) ** 3 / 2


def fade(t, start, dur):
    return clamp((t - start) / dur) if dur > 0 else float(t >= start)


def fmt_int(v):
    return f"{int(round(v)):,}"


def fmt_minutes(minutes):
    h, m = divmod(int(round(minutes)), 60)
    if h and m:
        return f"{h} hr {m} min"
    return f"{h} hr" if h else f"{m} min"


def fmt_clock(seconds):
    s = int(seconds)
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"
