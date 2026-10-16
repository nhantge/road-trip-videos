"""Road trip video template v3: following map, mile counter, captions, elevation profile, end card.
Every render also exports the vertical social clips, a Pinterest pin and YouTube chapters (Shorts & Social Export Spec)."""
import math, os, random, re, subprocess, sys
from PIL import Image, ImageDraw, ImageFont, ImageChops

W, H = 1920, 1080
FPS = int(os.environ.get("FPS", 30))
MAPW = 1160; PW = W - MAPW
Z = 2.2; WW, WH = int(MAPW * Z), int(H * Z)     # world canvas (max zoom)
STRIP = 170                                     # elevation strip height
FD = "/usr/share/fonts/opentype/inter/"
def F(name, size): return ImageFont.truetype(FD + name + ".otf", int(round(size)))
BG = (16, 24, 32); PANEL = (11, 17, 23); INK = (240, 236, 226); MUTE = (140, 152, 160)
ACC = (244, 162, 60); LINE = (52, 68, 80); TEAL = (94, 196, 182); DARK = (9, 14, 19)
ease = lambda x: x * x * (3 - 2 * x)
clamp = lambda v, a, b: max(a, min(b, v))

# ================= TRIP DATA (the only part that changes per video) =================
TRIP = dict(channel="COLORADO ROAD TRIPS", name="San Juan Skyway", region="Southwest Colorado",
            tagline="236 miles  ·  4 mountain passes  ·  2 to 3 days", miles=236,
            low_ft=6191, low_at="Cortez", high_ft=11018, high_at="Red Mountain Pass",
            towns=10, towns_note="Durango, Silverton, Ouray, Telluride and six more",
            drive_hours="6–7", days="2–3", days_note="Enough time for the towns and the hot springs",
            signature=(4, "PASSES ABOVE 10,000 FT", "Coal Bank, Molas, Red Mountain, Lizard Head"),
            next_name="Trail Ridge Road", next_note="Rocky Mountain National Park  ·  48 miles",
            # social export (vertical clips + pin): state label, the stop for Short 3, one-liners for Short 2
            state="COLORADO", best_stop="Ouray",
            short_hooks={"Durango": "steam trains to Silverton since 1882", "Molas Pass": "10,910 ft with the San Juans all around",
                         "Silverton": "an Old West mining town at 9,318 ft", "Million Dollar Highway": "no guardrails over Red Mountain Pass",
                         "Ouray": "hot springs in the Switzerland of America", "Telluride": "a free gondola over a box canyon",
                         "Lizard Head Pass": "meadows, lakes and one strange spire", "Mesa Verde": "cliff dwellings more than 700 years old"},
            pin_hook="Four mountain passes, hot springs and cliff dwellings in one loop")
WAY = [(37.275,-107.880),(37.414,-107.835),(37.540,-107.810),(37.630,-107.814),(37.699,-107.777),
       (37.738,-107.698),(37.812,-107.664),(37.862,-107.722),(37.899,-107.713),(37.935,-107.672),
       (38.023,-107.671),(38.090,-107.700),(38.153,-107.756),(38.120,-107.830),(38.096,-107.899),
       (38.050,-107.990),(38.016,-108.053),(37.994,-108.001),(37.960,-107.930),(37.947,-107.873),
       (37.9375,-107.812),(37.947,-107.873),(37.900,-107.880),(37.861,-107.868),(37.811,-107.907),
       (37.750,-107.975),(37.693,-108.031),(37.640,-108.170),(37.589,-108.319),(37.530,-108.420),
       (37.474,-108.504),(37.410,-108.550),(37.349,-108.586),(37.337,-108.412),(37.345,-108.289),
       (37.300,-108.160),(37.289,-108.039),(37.270,-107.950),(37.275,-107.880)]
SPUR = 20
STOPS = [
 dict(name="Durango", sub="START  ·  6,512 ft", at=(37.275,-107.880), mile=0, hue=(196,110,60), rows=[
   ("SEE & DO", "Durango & Silverton Narrow Gauge Railroad. Stroll historic Main Avenue."),
   ("EAT", "Steamworks Brewing Co."), ("STAY", "Strater Hotel, open since 1887")],
   cap="We start in Durango, an old railroad town where the steam train still runs to Silverton."),
 dict(name="Molas Pass", sub="10,910 ft  ·  mile 41", at=(37.738,-107.698), mile=41, leg="1 hr", hue=(90,150,120), rows=[
   ("SEE", "Coal Bank Pass, then the Molas overlook with a full sweep of the San Juans."),
   ("DO", "Stretch your legs on the Colorado Trail at Molas Lake."),
   ("TIP", "Aspens peak in late September.")],
   cap="US 550 climbs fast. At Molas Pass you're nearly 11,000 feet up, with the San Juans all around."),
 dict(name="Silverton", sub="9,318 ft  ·  mile 48", at=(37.812,-107.664), mile=48, leg="15 min", hue=(170,90,90), rows=[
   ("SEE & DO", "Old Hundred Gold Mine tour. Walk notorious Blair Street."),
   ("EAT", "Handlebars Food & Saloon"), ("STAY", "Grand Imperial Hotel, built 1883")],
   cap="Silverton sits in a high valley ringed by peaks, a mining town that kept its Old West look."),
 dict(name="Million Dollar Highway", sub="Red Mountain Pass  ·  11,018 ft", at=(37.899,-107.713), mile=58, leg="25 min", hue=(200,80,60), rows=[
   ("SEE", "Rust-red peaks, old mine ruins, and Bear Creek Falls before Ouray."),
   ("TIP", "Tight curves and no guardrails through the gorge. Drive it in daylight.")],
   cap="Now the famous stretch: the Million Dollar Highway over Red Mountain Pass. Take it slow."),
 dict(name="Ouray", sub="7,792 ft  ·  mile 71", at=(38.023,-107.671), mile=71, leg="35 min", hue=(80,140,170), rows=[
   ("SEE & DO", "Soak at Ouray Hot Springs Pool. Walk into Box Cañon Falls."),
   ("EAT", "Ouray Brewery"), ("STAY", "Beaumont Hotel")],
   cap="Drop into Ouray, the Switzerland of America, and soak in the hot springs."),
 dict(name="Telluride", sub="8,750 ft  ·  mile 119", at=(37.9375,-107.812), mile=119, leg="1 hr 5 min", hue=(110,120,190), rows=[
   ("SEE & DO", "Ride the free gondola to Mountain Village. Hike to Bridal Veil Falls."),
   ("EAT", "Brown Dog Pizza"), ("STAY", "The Hotel Telluride")],
   cap="Over Dallas Divide to Telluride, tucked at the end of a box canyon. The gondola is free."),
 dict(name="Lizard Head Pass", sub="10,222 ft  ·  mile 134", at=(37.811,-107.907), mile=134, leg="25 min", hue=(120,160,90), rows=[
   ("SEE", "Trout Lake and the spire of Lizard Head, then the Dolores River valley."),
   ("TIP", "Quietest stretch of the loop. Fuel up in Telluride or Rico.")],
   cap="Lizard Head Pass is the quiet side of the loop: meadows, lakes and one strange spire."),
 dict(name="Mesa Verde", sub="National Park  ·  mile 201", at=(37.337,-108.412), mile=201, leg="1 hr 30 min", hue=(190,140,80), rows=[
   ("SEE & DO", "Cliff Palace overlook and the Mesa Top Loop drive."),
   ("EAT", "Metate Room"), ("STAY", "Far View Lodge, inside the park"),
   ("TIP", "Allow at least half a day.")],
   cap="Last stop: Mesa Verde, where cliff dwellings have stood for more than 700 years."),
]
FINAL_LEG = "45 min"
# approximate elevation profile: (mile, feet)
PROF = [(0,6512),(10,6650),(20,7600),(27,8800),(35,10640),(38,9950),(41,10910),(48,9318),(53,10100),(58,11018),
        (62,9800),(66,8800),(71,7792),(81,6985),(92,8970),(104,7320),(112,8200),(119,8750),(123,8900),(134,10222),
        (146,8825),(166,7480),(183,6936),(193,6191),(201,6950),(208,7030),(214,7700),(224,8110),(236,6512)]
PEAKS = [(41, "Molas", "rb", 6), (58, "Red Mtn 11,018 ft", "lb", -10), (92, "Dallas Divide", "mb", 0), (134, "Lizard Head 10,222 ft", "mb", 0)]
TICKS = [(0, "Durango", "lt"), (48, "Silverton", "mt"), (71, "Ouray", "mt"), (119, "Telluride", "mt"), (193, "Cortez 6,191 ft", "mt"), (236, "Durango", "rt")]
TOWNS = [("Durango",37.275,-107.880,"lm",(12,8)),("Silverton",37.812,-107.664,"lm",(12,0)),("Ouray",38.023,-107.671,"lm",(12,0)),
         ("Ridgway",38.153,-107.756,"mb",(0,-9)),("Telluride",37.9375,-107.812,"lm",(11,-1)),("Rico",37.693,-108.031,"rm",(-10,-3)),
         ("Dolores",37.474,-108.504,"lt",(9,5)),("Cortez",37.349,-108.586,"rm",(-10,3)),("Mancos",37.345,-108.289,"mb",(0,-9))]
PASSES = [("Coal Bank Pass",37.699,-107.777,"lt",(10,5)),("Molas Pass",37.738,-107.698,"lm",(17,0)),
          ("Red Mountain Pass",37.899,-107.713,"lm",(17,0)),("Dallas Divide",38.096,-107.899,"mb",(0,-9)),
          ("Lizard Head Pass",37.811,-107.907,"rm",(-17,0)),("Mesa Verde NP",37.300,-108.412,"mt",(0,9))]
PILLS = [("US 550",37.50,-107.755),("CO 62",38.055,-107.94),("CO 145",37.60,-108.19),("US 160",37.262,-108.13)]
# ======================================================================================

# ---------- geography: fit the route into a design rectangle (1x "design" pixels) ----------
lats = [w[0] for w in WAY]; lons = [w[1] for w in WAY]
KX = math.cos(math.radians(sum(lats) / len(lats)))
BX0, BX1, BY0, BY1 = 190, 980, 150, 850
SC = min((BX1 - BX0) / ((max(lons) - min(lons)) * KX), (BY1 - BY0) / (max(lats) - min(lats)))
CXG, CYG = (BX0 + BX1) / 2, (BY0 + BY1) / 2
LONC, LATC = (max(lons) + min(lons)) / 2, (max(lats) + min(lats)) / 2
def P(lat, lon): return (CXG + (lon - LONC) * KX * SC, CYG - (lat - LATC) * SC)

def chaikin(pts, n=3):
    for _ in range(n):
        out = [pts[0]]
        for a, b in zip(pts, pts[1:]):
            out.append((a[0]*.75 + b[0]*.25, a[1]*.75 + b[1]*.25)); out.append((a[0]*.25 + b[0]*.75, a[1]*.25 + b[1]*.75))
        out.append(pts[-1]); pts = out
    return pts
def resample(pts, step):
    out = [pts[0]]; carry = 0.0
    for a, b in zip(pts, pts[1:]):
        d = math.dist(a, b)
        if d == 0: continue
        t = step - carry
        while t <= d:
            out.append((a[0] + (b[0]-a[0])*t/d, a[1] + (b[1]-a[1])*t/d)); t += step
        carry = (carry + d) % step
    out.append(pts[-1]); return out
raw = [P(*w) for w in WAY]
route = resample(chaikin(raw[:SPUR + 1]) + chaikin(raw[SPUR:])[1:], 1.4)
N = len(route)
def nearest(lat, lon, lo=0, hi=None):
    p = P(lat, lon); return min(range(lo, hi or N), key=lambda i: math.dist(route[i], p))
lo = 0
for s in STOPS:
    hi = nearest(37.861, -107.868, lo) if s["name"] == "Telluride" else None
    s["idx"] = nearest(*s["at"], lo, hi); lo = s["idx"] + 1
STOPS[0]["idx"] = 0
ANCH = [(s["idx"], s["mile"]) for s in STOPS] + [(N - 1, TRIP["miles"])]
def mile_at(pos):
    for (i0, m0), (i1, m1) in zip(ANCH, ANCH[1:]):
        if pos <= i1: return m0 + (m1 - m0) * (pos - i0) / max(1, i1 - i0)
    return TRIP["miles"]
def elev(m):
    for (m0, e0), (m1, e1) in zip(PROF, PROF[1:]):
        if m <= m1:
            u = (m - m0) / (m1 - m0); u = (1 - math.cos(math.pi * u)) / 2; return e0 + (e1 - e0) * u
    return PROF[-1][1]

# ---------- world layers ----------
def wlayer(fn, K=4):
    im = Image.new("RGBA", (MAPW * K, H * K), (0, 0, 0, 0)); fn(ImageDraw.Draw(im), K)
    return im.resize((WW, WH), Image.LANCZOS)
def sprite(size, fn, k=4):
    im = Image.new("RGBA", (size[0]*k, size[1]*k), (0, 0, 0, 0)); fn(ImageDraw.Draw(im), k); return im.resize(size, Image.LANCZOS)
ws = lambda v: v * Z   # design -> world

wbase = Image.new("RGB", (WW, WH), BG); wd = ImageDraw.Draw(wbase)
for g in range(0, MAPW, 60): wd.line([(ws(g), 0), (ws(g), WH)], fill=(20, 30, 39), width=2)
for g in range(0, H, 60): wd.line([(0, ws(g)), (WW, ws(g))], fill=(20, 30, 39), width=2)
random.seed(7)
def glyphs(dr, k):
    placed = 0
    while placed < 260:
        x, y = random.uniform(20, MAPW - 20), random.uniform(20, H - 20)
        if min(math.dist((x, y), route[i]) for i in range(0, N, 14)) < 20: continue
        s = random.uniform(5, 11); a = random.randint(26, 54)
        dr.line([((x-s)*k, (y+s*.6)*k), (x*k, (y-s*.6)*k), ((x+s)*k, (y+s*.6)*k)], fill=(150,170,180,a), width=max(1, int(1.1*k)), joint="curve")
        placed += 1
def ghost(dr, k): dr.line([(x*k, y*k) for x, y in route], fill=(70, 90, 104, 255), width=int(2.6*k), joint="curve")
for fn in (glyphs, ghost):
    g = wlayer(fn); wbase.paste(g, (0, 0), g)
wd = ImageDraw.Draw(wbase); fpill = F("Inter-Bold", 9.5 * Z)
for n, la, lo_ in PILLS:
    x, y = P(la, lo_); x, y = ws(x), ws(y); tw = wd.textlength(n, font=fpill)
    wd.rounded_rectangle([x - tw/2 - 10, y - 15, x + tw/2 + 10, y + 15], 7, fill=(26, 38, 48), outline=LINE, width=2)
    wd.text((x, y), n, font=fpill, fill=(170, 182, 190), anchor="mm")
def bright(dr, k):
    pts = [(x*k, y*k) for x, y in route]
    dr.line(pts, fill=ACC + (70,), width=int(8.5*k), joint="curve"); dr.line(pts, fill=ACC + (255,), width=int(3.4*k), joint="curve")
route_a = wlayer(bright).getchannel("A")
wmask = Image.new("L", (WW, WH), 0); mdraw = ImageDraw.Draw(wmask)
wover = Image.new("RGBA", (WW, WH), (0, 0, 0, 0)); od = ImageDraw.Draw(wover)
ftown, fpass = F("Inter-SemiBold", 14 * Z), F("Inter-Medium", 10.5 * Z)
dot = sprite((26, 26), lambda dr, k: dr.ellipse([4*k, 4*k, 22*k, 22*k], fill=BG + (255,), outline=INK + (255,), width=4*k))
tri = sprite((24, 22), lambda dr, k: dr.polygon([(12*k, 2*k), (22*k, 20*k), (2*k, 20*k)], fill=MUTE + (255,)))
for n, la, lo_, anc, off in TOWNS:
    x, y = P(la, lo_); x, y = ws(x), ws(y)
    wover.alpha_composite(dot, (int(x - 13), int(y - 13)))
    od.text((x + ws(off[0]), y + ws(off[1])), n, font=ftown, fill=INK, anchor=anc, stroke_width=5, stroke_fill=BG)
for n, la, lo_, anc, off in PASSES:
    x, y = P(la, lo_); x, y = ws(x), ws(y)
    wover.alpha_composite(tri, (int(x - 12), int(y - 11)))
    od.text((x + ws(off[0]), y + ws(off[1])), n, font=fpass, fill=(176, 186, 192), anchor=anc, stroke_width=4, stroke_fill=BG)
def badge(n):
    def fn(dr, k):
        dr.ellipse([2*k, 2*k, 54*k, 54*k], fill=ACC + (255,), outline=BG + (255,), width=4*k)
        dr.text((28*k, 28*k), str(n), font=F("Inter-Bold", 27*k), fill=(20, 24, 28, 255), anchor="mm")
    return sprite((56, 56), fn)
marker = sprite((52, 52), lambda dr, k: (dr.ellipse([2*k, 2*k, 50*k, 50*k], fill=ACC + (80,)),
                                         dr.ellipse([13*k, 13*k, 39*k, 39*k], fill=(255, 255, 255, 255), outline=ACC + (255,), width=5*k)))

# ---------- HUD (screen space) ----------
hud = Image.new("RGBA", (MAPW, H), (0, 0, 0, 0)); hd = ImageDraw.Draw(hud)
hd.rounded_rectangle([24, 24, 452, 204], 18, fill=PANEL + (232,), outline=LINE + (255,), width=2)
hd.text((48, 42), TRIP["name"].upper(), font=F("InterDisplay-Bold", 25), fill=INK)
hd.text((48, 76), TRIP["region"], font=F("Inter-Medium", 16), fill=MUTE)
hd.line([(48, 106), (428, 106)], fill=LINE, width=2)
hd.text((48, 118), "MILE", font=F("Inter-Bold", 13), fill=MUTE); hd.text((262, 118), "ELEVATION", font=F("Inter-Bold", 13), fill=MUTE)
IX, IY, IW, IH = MAPW - 190, 62, 142, 100
hd.rounded_rectangle([IX - 18, 24, MAPW - 24, IY + IH + 18], 18, fill=PANEL + (232,), outline=LINE + (255,), width=2)
hd.text((IX, 38), "COLORADO", font=F("Inter-Bold", 13), fill=MUTE)
hd.rectangle([IX, IY, IX + IW, IY + IH], outline=(90, 106, 118), width=2)
cx_ = IX + IW * ((LONC + 109.05) / 7.0); cy_ = IY + IH * ((41.0 - LATC) / 4.0)
hd.ellipse([cx_ - 7, cy_ - 7, cx_ + 7, cy_ + 7], fill=ACC)
dx_ = IX + IW * ((-104.99 + 109.05) / 7.0); dy_ = IY + IH * ((41.0 - 39.74) / 4.0)
hd.ellipse([dx_ - 3, dy_ - 3, dx_ + 3, dy_ + 3], fill=MUTE); hd.text((dx_ + 7, dy_ - 9), "Denver", font=F("Inter-Medium", 13), fill=MUTE)
f_mile, f_of, f_el = F("InterDisplay-Bold", 52), F("Inter-Medium", 20), F("InterDisplay-Bold", 34)

EX0, EX1, EYT, EYB = 64, 1112, 60, 128
ex = lambda m: EX0 + (EX1 - EX0) * m / TRIP["miles"]
ey = lambda e: EYB - (EYB - EYT) * (e - 5800) / (11200 - 5800)
def make_strip(lit):
    k = 2; im = Image.new("RGB", (MAPW * k, STRIP * k), PANEL); dr = ImageDraw.Draw(im)
    pts = [(ex(m / 2) * k, ey(elev(m / 2)) * k) for m in range(0, TRIP["miles"] * 2 + 1)]
    dr.polygon([(EX0 * k, EYB * k)] + pts + [(EX1 * k, EYB * k)], fill=(112, 76, 34) if lit else (30, 42, 52))
    dr.line(pts, fill=ACC if lit else (92, 110, 122), width=(3 if lit else 2) * k, joint="curve")
    dr.line([(EX0 * k, EYB * k), (EX1 * k, EYB * k)], fill=LINE, width=k)
    dr.line([(0, k), (MAPW * k, k)], fill=LINE, width=2 * k)
    dr.text((48 * k, 16 * k), "ELEVATION", font=F("Inter-Bold", 13 * k), fill=MUTE)
    dr.text((132 * k, 16 * k), "approximate", font=F("Inter-Regular", 13 * k), fill=(92, 106, 116))
    fs_ = F("Inter-Medium", 12 * k)
    for m, lab, anc, dx in PEAKS:
        dr.text(((ex(m) + dx) * k, (ey(elev(m)) - 5) * k), lab, font=fs_, fill=(190, 198, 204), anchor=anc)
    for m, lab, anc in TICKS:
        dr.line([(ex(m) * k, EYB * k), (ex(m) * k, (EYB + 5) * k)], fill=MUTE, width=k)
        dr.text((ex(m) * k, (EYB + 9) * k), lab, font=fs_, fill=MUTE, anchor=anc)
    return im.resize((MAPW, STRIP), Image.LANCZOS)
strip_dim, strip_lit = make_strip(False), make_strip(True)
pdot = sprite((20, 20), lambda dr, k: dr.ellipse([2*k, 2*k, 18*k, 18*k], fill=(255, 255, 255, 255), outline=ACC + (255,), width=4*k))

def wrap(dr, text, font, width):
    lines, cur = [], ""
    for w_ in text.split():
        t = (cur + " " + w_).strip()
        if dr.textlength(t, font=font) <= width: cur = t
        else: lines.append(cur); cur = w_
    lines.append(cur); return lines
fcap = F("Inter-SemiBold", 29)
def make_caption(text):
    tmp = ImageDraw.Draw(Image.new("RGB", (4, 4))); lines = wrap(tmp, text, fcap, 860)
    tw = max(tmp.textlength(l, font=fcap) for l in lines); bw, bh = int(tw + 56), 40 * len(lines) + 30
    im = Image.new("RGBA", (bw, bh), (0, 0, 0, 0)); dr = ImageDraw.Draw(im)
    dr.rounded_rectangle([0, 0, bw - 1, bh - 1], 16, fill=(6, 10, 14, 236))
    for i, l in enumerate(lines): dr.text((bw / 2, 15 + 40 * i), l, font=fcap, fill=(250, 248, 242), anchor="mt")
    return im
caps = [make_caption(s["cap"]) for s in STOPS]

# ---------- right-panel cards ----------
CX, CW = 44, PW - 88
def photo_slot(hue, seed):
    k = 2; w, h = CW * k, 330 * k; im = Image.new("RGB", (w, h)); dr = ImageDraw.Draw(im)
    for y in range(h):
        t = y / h; dr.line([(0, y), (w, y)], fill=tuple(int(hue[i] * (0.95 - .55 * t) + 30 * t) for i in range(3)))
    rnd = random.Random(seed)
    dr.ellipse([w * .70, h * .14, w * .70 + 70 * k, h * .14 + 70 * k], fill=tuple(min(255, c + 70) for c in hue))
    for layer in range(3):
        yb = h * (.45 + .17 * layer); pts = [(0, h)]; x = 0; y = yb + rnd.uniform(-20, 20) * k
        while x < w:
            pts.append((x, y)); x += rnd.uniform(40, 110) * k; y = yb + rnd.uniform(-70, 50) * k * (1 - .25 * layer)
        pts += [(w, y), (w, h)]; sh = .55 - .17 * layer
        dr.polygon(pts, fill=tuple(int(c * sh * .6 + 8) for c in hue))
    im = im.resize((CW, 330), Image.LANCZOS)
    m = Image.new("L", (CW * 2, 660), 0); ImageDraw.Draw(m).rounded_rectangle([0, 0, CW * 2 - 1, 659], 36, fill=255)
    return im, m.resize((CW, 330), Image.LANCZOS)
def make_card(i, s):
    im = Image.new("RGB", (PW, H), PANEL); dr = ImageDraw.Draw(im)
    dr.text((CX, 46), f"STOP {i+1} OF {len(STOPS)}", font=F("Inter-Bold", 18), fill=ACC)
    for j in range(len(STOPS)):
        x0 = PW - 44 - (len(STOPS) - j) * 26; dr.rounded_rectangle([x0, 52, x0 + 18, 60], 4, fill=ACC if j <= i else LINE)
    ph, m = photo_slot(s["hue"], i * 13 + 5); im.paste(ph, (CX, 92), m)
    tag = "PHOTO SLOT"; ftg = F("Inter-Bold", 13); tw = dr.textlength(tag, font=ftg)
    dr.rounded_rectangle([CX + 16, 108, CX + 16 + tw + 20, 134], 6, fill=(0, 0, 0)); dr.text((CX + 26, 113), tag, font=ftg, fill=(230, 230, 230))
    y = 452; big = len(s["name"]) < 16
    dr.text((CX, y), s["name"], font=F("InterDisplay-Bold", 56 if big else 46), fill=INK); y += 74 if big else 64
    dr.text((CX, y), s["sub"], font=F("Inter-Medium", 22), fill=TEAL); y += 50
    dr.line([(CX, y), (CX + CW, y)], fill=LINE, width=2); y += 26
    fl, fb = F("Inter-Bold", 15), F("Inter-Regular", 25)
    for lab, txt in s["rows"]:
        dr.text((CX, y + 6), lab, font=fl, fill=MUTE)
        for ln in wrap(dr, txt, fb, CW - 130): dr.text((CX + 130, y), ln, font=fb, fill=INK); y += 35
        y += 20
    return im
cards = [make_card(i, s) for i, s in enumerate(STOPS)]
def make_idle(kick, name, miles, leg):
    im = Image.new("RGB", (PW, H), PANEL); pd = ImageDraw.Draw(im)
    pd.text((CX, 396), kick, font=F("Inter-Bold", 18), fill=ACC)
    pd.text((CX, 430), name, font=F("InterDisplay-Bold", 50 if len(name) < 16 else 42), fill=INK)
    pd.line([(CX, 514), (CX + CW, 514)], fill=LINE, width=2)
    pd.text((CX, 540), "DISTANCE", font=F("Inter-Bold", 15), fill=MUTE); pd.text((CX + 300, 540), "DRIVE TIME", font=F("Inter-Bold", 15), fill=MUTE)
    pd.text((CX, 566), f"{miles} miles", font=F("InterDisplay-Bold", 40), fill=INK)
    pd.text((CX + 300, 566), leg, font=F("InterDisplay-Bold", 40), fill=INK)
    pd.text((CX, 632), "Approximate, without stops", font=F("Inter-Regular", 18), fill=(92, 106, 116))
    return im
idles = [None] + [make_idle("NEXT STOP", s["name"], s["mile"] - STOPS[i]["mile"], s["leg"]) for i, s in enumerate(STOPS[1:])]
idle_end = make_idle("CLOSING THE LOOP", "Back to " + STOPS[0]["name"], TRIP["miles"] - STOPS[-1]["mile"], FINAL_LEG)
idle_start = Image.new("RGB", (PW, H), PANEL)

# ---------- full-frame slides ----------
def fullcard(lines):
    im = Image.new("RGB", (W, H), DARK); dr = ImageDraw.Draw(im)
    y = (H - sum(h for _, _, h, _ in lines)) / 2
    for txt, font, h, col in lines: dr.text((W / 2, y), txt, font=font, fill=col, anchor="mt"); y += h
    return im
title = fullcard([(TRIP["channel"], F("Inter-Bold", 24), 64, ACC), (TRIP["name"], F("InterDisplay-Bold", 120), 160, INK),
                  (TRIP["tagline"], F("Inter-Medium", 32), 50, MUTE)])
STATS = [(TRIP["miles"], "{:,}", "TOTAL MILES", "Full route, start to finish"),
         (TRIP["high_ft"] - TRIP["low_ft"], "{:,}", "FT ELEVATION CHANGE", f'{TRIP["low_ft"]:,} ft in {TRIP["low_at"]} to {TRIP["high_ft"]:,} ft on {TRIP["high_at"]}'),
         (TRIP["towns"], "{}", "TOWNS ON THE ROUTE", TRIP["towns_note"]),
         (None, TRIP["drive_hours"], "HOURS OF DRIVING", "Behind the wheel, without stops"),
         (None, TRIP["days"], "DAYS RECOMMENDED", TRIP["days_note"]),
         (TRIP["signature"][0], "{}", TRIP["signature"][1], TRIP["signature"][2])]
_sf = dict(num=F("InterDisplay-Bold", 112), unit=F("Inter-Bold", 21), sub=F("Inter-Regular", 21), kick=F("Inter-Bold", 24), head=F("InterDisplay-Bold", 60))
def stats_frame(tt):
    tt = max(0.0, tt); im = Image.new("RGB", (W, H), DARK); dr = ImageDraw.Draw(im)
    dr.text((140, 84), "BY THE NUMBERS", font=_sf["kick"], fill=ACC); dr.text((138, 122), TRIP["name"], font=_sf["head"], fill=INK)
    TW, TH, GAP, X0, Y0 = 520, 330, 40, 140, 250
    for i, (val, fmt, unit, sub) in enumerate(STATS):
        a = clamp((tt - .15 - .12 * i) / .45, 0, 1)
        if a <= 0: continue
        e = ease(a); x = X0 + (i % 3) * (TW + GAP); y = Y0 + (i // 3) * (TH + GAP) + int((1 - e) * 24)
        mix = lambda c: tuple(int(DARK[j] + (c[j] - DARK[j]) * e) for j in range(3))
        dr.rounded_rectangle([x, y, x + TW, y + TH], 22, fill=mix((18, 27, 36)), outline=mix(LINE), width=2)
        dr.rectangle([x + 36, y + 40, x + 92, y + 45], fill=mix(ACC))
        txt = fmt if val is None else fmt.format(int(round(val * ease(clamp((tt - .3 - .12 * i) / 1.3, 0, 1)))))
        dr.text((x + 32, y + 62), txt, font=_sf["num"], fill=mix(INK)); dr.text((x + 36, y + 206), unit, font=_sf["unit"], fill=mix(TEAL))
        for j, ln in enumerate(wrap(dr, sub, _sf["sub"], TW - 72)): dr.text((x + 36, y + 242 + j * 28), ln, font=_sf["sub"], fill=mix(MUTE))
    return im
def make_end():
    im = Image.new("RGB", (W, H), DARK); dr = ImageDraw.Draw(im)
    dr.text((140, 250), "THANKS FOR RIDING ALONG", font=F("Inter-Bold", 24), fill=ACC)
    dr.text((136, 296), TRIP["name"], font=F("InterDisplay-Bold", 92), fill=INK)
    dr.text((140, 420), f'{TRIP["miles"]} miles  ·  {len(STOPS)} stops  ·  {TRIP["days"]} days', font=F("Inter-Medium", 32), fill=MUTE)
    lab = "SUBSCRIBE"; fsb = F("Inter-Bold", 30); tw = dr.textlength(lab, font=fsb)
    dr.rounded_rectangle([140, 540, 140 + tw + 88, 616], 38, fill=ACC); dr.text((184, 578), lab, font=fsb, fill=(24, 20, 14), anchor="lm")
    dr.text((140 + tw + 116, 578), "for more road trips", font=F("Inter-Medium", 30), fill=INK, anchor="lm")
    x0, y0, x1, y1 = 1130, 236, 1780, 700
    dr.rounded_rectangle([x0, y0, x1, y1], 26, fill=(18, 27, 36), outline=LINE, width=2)
    ph, m = photo_slot((70, 120, 160), 99); ph = ph.resize((x1 - x0 - 48, 240)); m = m.resize((x1 - x0 - 48, 240)); im.paste(ph, (x0 + 24, y0 + 24), m)
    dr.text((x0 + 36, y0 + 296), "UP NEXT", font=F("Inter-Bold", 20), fill=ACC)
    dr.text((x0 + 34, y0 + 328), TRIP["next_name"], font=F("InterDisplay-Bold", 52), fill=INK)
    dr.text((x0 + 36, y0 + 400), TRIP["next_note"], font=F("Inter-Medium", 22), fill=MUTE)
    return im
endcard = make_end()

# ---------- timeline ----------
T_TITLE, T_STATS, T_TRAVEL, T_HOLD, T_OUT = 3.5, 5.0, 3.2, 7.5, 7.5
T0 = T_TITLE + T_STATS
events = []; t = T0; prev = 0
for i, s in enumerate(STOPS):
    if i > 0: events.append((t, t + T_TRAVEL, "travel", (prev, s["idx"], i))); t += T_TRAVEL
    events.append((t, t + T_HOLD, "hold", i)); t += T_HOLD; prev = s["idx"]
t_final = t; events.append((t, t + T_TRAVEL + 1.0, "travel", (prev, N - 1, None))); t += T_TRAVEL + 1.0
t_out = t + .8; TOTAL = t_out + T_OUT
print("duration", round(TOTAL, 2), file=sys.stderr)

# ==================== SOCIAL EXPORT: vertical clips, Pinterest pin, chapters ====================
# One export for YouTube Shorts, Instagram Reels, TikTok and Facebook Reels (see "Shorts & Social Export Spec").
VW, VH = 1080, 1920
SX0, SX1, SY0, SY1 = 60, 940, 180, 1500            # text safe zone: platform UI covers the bottom and right
SCX = (SX0 + SX1) // 2
SLATE = 2.0                                        # end slate on the last 2 s of every clip
T_TRAVEL_S, T_HOLD_S = 1.2, 2.5                    # Short 2 pacing; holds stretch or shrink to land 45-58 s
CHANNEL_LABEL = "ROAD TRIP ATLAS"
ROOT = os.environ.get("RTA_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # Road Trip Assets
WOVER0, WMASK0 = wover.copy(), wmask.copy()        # pristine world layers (the main render draws into them)
STATE = TRIP.get("state", "").upper()
SLUG = re.sub(r"[^a-z0-9]+", "-", TRIP["name"].lower()).strip("-")

def words_of(text, col=INK): return [(w_, col) for w_ in text.split()]
def wrap_words(words, font, width):
    lines, cur, cw = [], [], 0.0; sp = font.getlength(" ")
    for w_, c in words:
        wl = font.getlength(w_)
        if cur and cw + sp + wl > width: lines.append(cur); cur, cw = [], 0.0
        cw += (sp if cur else 0) + wl; cur.append((w_, c))
    if cur: lines.append(cur)
    return lines
def line_len(line, font): return sum(font.getlength(w_) for w_, _ in line) + font.getlength(" ") * (len(line) - 1)
def fit_words(words, width, sizes=(60, 56, 52), max_lines=2, face="Inter-SemiBold"):
    """Captions: 52-60 px, max 2 lines; trims with an ellipsis if even 52 px won't fit."""
    for sz in sizes:
        f = F(face, sz); lines = wrap_words(words, f, width)
        if len(lines) <= max_lines: return f, lines
    lines = lines[:max_lines]
    while len(lines[-1]) > 1 and line_len(lines[-1] + [("…", INK)], f) > width: lines[-1] = lines[-1][:-1]
    w_, c = lines[-1][-1]; lines[-1][-1] = (w_.rstrip(",.;:—-") + "…", c)
    return f, lines
def draw_words(dr, x, y, line, font):
    sp = font.getlength(" ")
    for w_, c in line: dr.text((x, y), w_, font=font, fill=c); x += font.getlength(w_) + sp
def caption_img(words, width=SX1 - SX0 - 56, sizes=(60, 56, 52)):
    f, lines = fit_words(words, width, sizes); lh = int(f.size * 1.24)
    bw = int(max(line_len(l, f) for l in lines) + 56); bh = lh * len(lines) + 34
    im = Image.new("RGBA", (bw, bh), (0, 0, 0, 0)); dr = ImageDraw.Draw(im)
    dr.rounded_rectangle([0, 0, bw - 1, bh - 1], 22, fill=(6, 10, 14, 226))
    for i, l in enumerate(lines): draw_words(dr, (bw - line_len(l, f)) / 2, 14 + lh * i, l, f)
    return im
def paste_alpha(base, im, xy, a):
    if a <= 0: return
    if a < 1: im = im.copy(); im.putalpha(im.getchannel("A").point(lambda v: int(v * a)))
    base.paste(im, (int(xy[0]), int(xy[1])), im)
def atlas_icon(d):
    return sprite((d, d), lambda dr, k: (dr.ellipse([0, 0, d * k - 1, d * k - 1], fill=TEAL + (80,)),
                                          dr.ellipse([d * k * .24, d * k * .24, d * k * .76, d * k * .76], fill=TEAL + (255,))))
def draw_logo(img, x, y, size, anchor="l"):
    """Icon + ROAD TRIP ATLAS (ATLAS in amber), like the thumbnail logo. y is the text middle."""
    dr = ImageDraw.Draw(img); f = F("Inter-Bold", size); a, b = "ROAD TRIP ", "ATLAS"; ic = int(size * 1.05)
    tw = ic + size * .5 + f.getlength(a) + f.getlength(b)
    x = x - tw / 2 if anchor == "m" else x - tw if anchor == "r" else x
    img.paste(i := atlas_icon(ic), (int(x), int(y - ic / 2)), i); x += ic + size * .5
    dr.text((x, y), a, font=f, fill=INK, anchor="lm"); dr.text((x + f.getlength(a), y), b, font=f, fill=ACC, anchor="lm")
def make_slate():
    im = Image.new("RGB", (VW, VH), DARK); dr = ImageDraw.Draw(im)
    dr.text((SCX, 640), TRIP["name"].upper(), font=F("Inter-Bold", 30), fill=TEAL, anchor="mm")
    f = F("InterDisplay-Bold", 84); lines = wrap(dr, "Full road trip guide on YouTube", f, SX1 - SX0)
    for i, l in enumerate(lines): dr.text((SCX, 700 + i * 96), l, font=f, fill=INK, anchor="mt")
    y = 700 + len(lines) * 96 + 56
    dr.line([(SCX - 110, y), (SCX + 110, y)], fill=LINE, width=3)
    draw_logo(im, SCX, y + 74, 46, "m")
    return im
def with_slate(frame_fn, dur):
    slate = make_slate(); t_s = dur - SLATE
    def fn(t):
        if t < t_s: return frame_fn(t)
        a = clamp((t - t_s) / .25, 0, 1)
        return slate if a >= 1 else Image.blend(frame_fn(t), slate, ease(a))
    return fn
def cover(im, size):
    im = im.convert("RGB"); s = max(size[0] / im.width, size[1] / im.height)
    im = im.resize((max(size[0], round(im.width * s)), max(size[1], round(im.height * s))), Image.LANCZOS)
    x, y = (im.width - size[0]) // 2, (im.height - size[1]) // 2
    return im.crop((x, y, x + size[0], y + size[1]))
def stop_photos(s):
    """Photos/<Trip>/<Stop>/ under Road Trip Assets, in file-name order."""
    d = os.path.join(os.environ.get("PHOTOS_DIR") or os.path.join(ROOT, "Photos"), TRIP["name"], s["name"])
    if not os.path.isdir(d): return []
    return [os.path.join(d, f) for f in sorted(os.listdir(d)) if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))]
def find_audio(*names):
    for n in names:
        if n and os.path.isfile(n): return n
    return None
def music_bed():
    if os.environ.get("MUSIC"): return os.environ["MUSIC"]
    d = os.path.join(ROOT, "Music")
    files = sorted(f for f in os.listdir(d) if f.lower().endswith((".m4a", ".mp3", ".wav", ".aac"))) if os.path.isdir(d) else []
    beds = [f for f in files if "bed" in f.lower()] or files
    return os.path.join(d, beds[0]) if beds else None
def narration(tag):
    d = os.path.join(ROOT, "Voiceover", TRIP["name"])
    return find_audio(*[os.path.join(d, f"{SLUG}_{tag}.{e}") for e in ("mp3", "wav", "m4a")])

def encode(frame_fn, dur, out, vo=None):
    """H.264 1080x1920 30 fps CRF 20 + AAC: music bed (or silence), plus narration if there is one."""
    tmp = out + ".video.mp4"; n = int(round(dur * FPS))
    ff_ = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{VW}x{VH}", "-r", str(FPS),
                            "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", tmp], stdin=subprocess.PIPE)
    for i in range(n): ff_.stdin.write(frame_fn(i / FPS).tobytes())
    ff_.stdin.close(); ff_.wait()
    music = music_bed(); cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", tmp]
    cmd += ["-stream_loop", "-1", "-i", music] if music else ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
    fade = f"afade=t=out:st={max(0, dur - 1.6):.2f}:d=1.6"
    if vo:
        cmd += ["-i", vo]
        fc = (f"[1:a]atrim=0:{dur:.3f},asetpts=PTS-STARTPTS,volume=0.35[m];[2:a]adelay=300|300[v];"
              f"[m][v]amix=inputs=2:duration=first:normalize=0,{fade},loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000[a]")
    else:
        fc = f"[1:a]atrim=0:{dur:.3f},asetpts=PTS-STARTPTS,{fade},loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000[a]"
    cmd += ["-filter_complex", fc, "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            "-t", f"{dur:.3f}", "-movflags", "+faststart", out]
    subprocess.run(cmd, check=True); os.remove(tmp)
    print(f"wrote {out} ({dur:.1f} s)", file=sys.stderr)

def head_block(img, y=186):
    """State (teal) + trip name at the top, ROAD TRIP ATLAS on the right."""
    dr = ImageDraw.Draw(img)
    dr.text((SX0, y), STATE, font=F("Inter-Bold", 30), fill=TEAL, anchor="lm")
    draw_logo(img, SX1, y, 24, "r")
    f = F("InterDisplay-Bold", 72)
    if f.getlength(TRIP["name"]) > SX1 - SX0: f = F("InterDisplay-Bold", 72 * (SX1 - SX0) / f.getlength(TRIP["name"]))
    dr.text((SX0 - 3, y + 30), TRIP["name"], font=f, fill=INK)

# ---------- Short 1: By the Numbers ----------
def short1():
    STEP, HOLD, LEAD = 2.8, 3.0, .45               # tile 0 is up on frame 1 and nearly counted (the hook)
    n = len(STATS); t_done = (n - 1) * STEP - LEAD + .3 + 1.3; dur = t_done + HOLD + SLATE
    TW, TH, GAP = 420, 290, 30; X0, Y0 = SCX - TW - GAP // 2, 325
    head = Image.new("RGB", (VW, VH), DARK); head_block(head)
    fnum, funit = F("InterDisplay-Bold", 112), F("Inter-Bold", 26)
    caps = [caption_img(words_of(sub)) for _, _, _, sub in STATS] + [caption_img(words_of(TRIP["tagline"].replace("  ·  ", " · ")))]
    def frame(t):
        im = head.copy(); dr = ImageDraw.Draw(im)
        for i, (val, fmt, unit, sub) in enumerate(STATS):
            loc = t + LEAD - i * STEP; a = clamp(loc / .45, 0, 1)
            if a <= 0: continue
            e = ease(a); x = X0 + (i % 2) * (TW + GAP); y = Y0 + (i // 2) * (TH + GAP) + int((1 - e) * 24)
            mix = lambda c: tuple(int(DARK[j] + (c[j] - DARK[j]) * e) for j in range(3))
            dr.rounded_rectangle([x, y, x + TW, y + TH], 22, fill=mix((18, 27, 36)), outline=mix(LINE), width=2)
            dr.rectangle([x + 36, y + 38, x + 92, y + 43], fill=mix(ACC))
            head_start = .95 if i == 0 else 0
            txt = fmt if val is None else fmt.format(int(round(val * ease(clamp((loc + head_start - .3) / 1.3, 0, 1)))))
            dr.text((x + 32, y + 56), txt, font=fnum, fill=mix(INK))
            for j, ln in enumerate(wrap(dr, unit, funit, TW - 64)): dr.text((x + 36, y + 200 + j * 32), ln, font=funit, fill=mix(TEAL))
        k = n if t > t_done + .3 else min(n - 1, int((t + LEAD) // STEP))
        start = t_done + .3 if k == n else k * STEP - LEAD
        c = caps[k]; paste_alpha(im, c, (SCX - c.width / 2, SY1 - 10 - c.height), clamp((t - start) / .25, 0, 1) if k else 1)
        return im
    return with_slate(frame, dur), dur

# ---------- Short 2: route fly-through ----------
MVH = 1150                                         # map viewport 1080x1150 (top 60%)
VW_OV = min(WW, WH * VW / MVH)                     # widest view: the whole route
E_LO = min(e for _, e in PROF) - 500; E_HI = max(e for _, e in PROF) + 300
def make_vstrip(lit, x0=SX0, x1=SX1 - 10, top=26, base=128):
    k = 2; im = Image.new("RGB", (VW * k, 170 * k), PANEL); dr = ImageDraw.Draw(im)
    vx = lambda m: x0 + (x1 - x0) * m / TRIP["miles"]; vy = lambda e: base - (base - top) * (e - E_LO) / (E_HI - E_LO)
    pts = [(vx(m / 2) * k, vy(elev(m / 2)) * k) for m in range(0, TRIP["miles"] * 2 + 1)]
    dr.polygon([(x0 * k, base * k)] + pts + [(x1 * k, base * k)], fill=(112, 76, 34) if lit else (30, 42, 52))
    dr.line(pts, fill=ACC if lit else (92, 110, 122), width=(4 if lit else 3) * k, joint="curve")
    dr.line([(x0 * k, base * k), (x1 * k, base * k)], fill=LINE, width=k)
    fs_ = F("Inter-Medium", 22 * k); taken = []
    def free(cx, w_):
        if cx - w_ / 2 < x0 or cx + w_ / 2 > x1 + 10 or any(abs(cx - c) < (w_ + o) / 2 + 12 for c, o in taken): return False
        taken.append((cx, w_)); return True
    for m, lab, anc in TICKS:
        w_ = fs_.getlength(lab) / k; cx = vx(m) + (w_ / 2 if anc[0] == "l" else -w_ / 2 if anc[0] == "r" else 0)
        dr.line([(vx(m) * k, base * k), (vx(m) * k, (base + 5) * k)], fill=MUTE, width=k)
        if free(cx, w_): dr.text((vx(m) * k, (base + 9) * k), lab, font=fs_, fill=MUTE, anchor=anc)
    taken.clear()
    for m, lab, anc, dx in PEAKS:
        w_ = fs_.getlength(lab) / k; cx = vx(m) + dx + (-w_ / 2 if anc[0] == "r" else w_ / 2 if anc[0] == "l" else 0)
        if free(cx, w_) and vy(elev(m)) - 30 > 0: dr.text(((vx(m) + dx) * k, (vy(elev(m)) - 6) * k), lab, font=fs_, fill=(190, 198, 204), anchor=anc)
    return im.resize((VW, 170), Image.LANCZOS), vx, vy
def short2():
    loop = STOPS[-1]["idx"] < N - 3                # does the route return to its start?
    n = len(STOPS); T_HOOK, T_END = 1.6, 1.4; fin = T_TRAVEL_S + .6 if loop else 0
    fixed = T_HOOK + (n - 1) * T_TRAVEL_S + fin + T_END + SLATE
    hold = clamp((48 - fixed) / n, 1.4, 4.5)        # spec: T_HOLD ~2.5 s, total 45-58 s
    if fixed + n * hold > 58: hold = max(1.0, (58 - fixed) / n)
    ev = []; t = T_HOOK; prev = 0
    for i, s in enumerate(STOPS):
        if i: ev.append((t, t + T_TRAVEL_S, "travel", (prev, s["idx"]))); t += T_TRAVEL_S
        ev.append((t, t + hold, "hold", i)); t += hold; prev = s["idx"]
    if loop: ev.append((t, t + fin, "travel", (prev, N - 1))); t += fin
    t_end = t; dur = t + T_END + SLATE
    hooks = TRIP.get("short_hooks", {})
    def hook_of(s):
        if s["name"] in hooks: return hooks[s["name"]]
        row = next((r for r in s["rows"] if "SEE" in r[0] or "EAT" in r[0]), s["rows"][0])
        return row[1].split(". ")[0].rstrip(".")
    labels = [caption_img([(w_, ACC) for w_ in s["name"].split()] + [("—", INK)] + words_of(hook_of(s))) for s in STOPS]
    hook_cap = caption_img(words_of(f"{TRIP['miles']} miles in {round(dur)} seconds"), sizes=(60,))
    end_cap = caption_img(words_of(f"{TRIP['miles']} miles · {n} stops · {TRIP['days']} days"))
    strip_dim, vx, vy = make_vstrip(False); strip_lit, _, _ = make_vstrip(True)
    panel = Image.new("RGB", (VW, VH - MVH), PANEL); pd = ImageDraw.Draw(panel)
    pd.line([(0, 0), (VW, 0)], fill=LINE, width=3)
    pd.text((SX0, 44), "MILE", font=F("Inter-Bold", 26), fill=MUTE); pd.text((520, 44), "ELEVATION", font=F("Inter-Bold", 26), fill=MUTE)
    top = Image.new("RGBA", (VW, 380), (0, 0, 0, 0)); td = ImageDraw.Draw(top)
    for y in range(380): td.line([(0, y), (VW, y)], fill=DARK + (int(245 * (1 - y / 380) ** 1.1),))
    head_block(top)
    f_mile, f_of, f_el = F("InterDisplay-Bold", 104), F("Inter-Medium", 34), F("InterDisplay-Bold", 76)
    wm, wo = WMASK0.copy(), WOVER0.copy(); md = ImageDraw.Draw(wm); R_ = int(8 * Z)
    st = dict(drawn=0, cam=[CXG, CYG, 1.0], badged=set())
    def view(cx, cy, z):
        w_ = min(VW_OV, VW * Z / z); h_ = w_ * MVH / VW
        x0 = int(clamp(ws(cx) - w_ / 2, 0, WW - w_)); y0 = int(clamp(ws(cy) - h_ / 2, 0, WH - h_))
        return (x0, y0, x0 + int(w_), y0 + int(h_))
    def frame(t):
        pos, lab, la = 0.0, None, 0.0
        for t0, t1, kind, data in ev:
            if kind == "hold" and t >= t0:
                pos = STOPS[data]["idx"]
                if data not in st["badged"]:
                    x, y = route[int(pos)]; wo.alpha_composite(badge(data + 1), (int(ws(x) - 28), int(ws(y) - 28))); st["badged"].add(data)
                if t < t1: lab = data; la = clamp((t - t0 - .15) / .25, 0, 1) * clamp((t1 - t) / .2, 0, 1)
            if kind == "travel" and t >= t0: a, b_ = data; pos = a + (b_ - a) * ease(min(1, (t - t0) / (t1 - t0)))
        if t >= t_end: pos = N - 1 if loop else STOPS[-1]["idx"]
        ip = int(pos)
        if t >= T_HOOK and ip > st["drawn"]:
            for px, py in route[max(0, st["drawn"] - 1):ip + 1]: md.ellipse([ws(px) - R_, ws(py) - R_, ws(px) + R_, ws(py) + R_], fill=255)
            st["drawn"] = ip
        cx, cy = route[ip]; cam = st["cam"]
        over = t < T_HOOK + .3 or t >= t_end
        tx, ty, tz = (CXG, CYG, 1.0) if over else (cx, cy, Z)
        kc, kz = 1 - math.exp(-1 / FPS / .30), 1 - math.exp(-1 / FPS / .50)
        cam[0] += (tx - cam[0]) * kc; cam[1] += (ty - cam[1]) * kc; cam[2] += (tz - cam[2]) * kz
        box = view(*cam); w_, h_ = box[2] - box[0], box[3] - box[1]
        v = wbase.crop(box)
        mask = route_a.crop(box) if t < T_HOOK or t >= t_end else ImageChops.multiply(route_a.crop(box), wm.crop(box))
        v.paste(ACC, (0, 0, w_, h_), mask); o = wo.crop(box); v.paste(o, (0, 0), o)
        v = v.resize((VW, MVH), Image.BILINEAR)
        if T_HOOK <= t < t_end:
            mx, my = (ws(cx) - box[0]) * VW / w_, (ws(cy) - box[1]) * MVH / h_; v.paste(marker, (int(mx - 26), int(my - 26)), marker)
        im = Image.new("RGB", (VW, VH), PANEL); im.paste(v, (0, 0)); im.paste(top, (0, 0), top); im.paste(panel, (0, MVH))
        dr = ImageDraw.Draw(im)
        mile = TRIP["miles"] if t >= t_end and loop else mile_at(pos) if t >= T_HOOK else 0
        mt = str(int(round(mile))); dr.text((SX0, MVH + 80), mt, font=f_mile, fill=INK)
        dr.text((SX0 + dr.textlength(mt, font=f_mile) + 14, MVH + 140), f"of {TRIP['miles']}", font=f_of, fill=MUTE)
        dr.text((520, MVH + 100), f"{int(round(elev(mile))):,} ft", font=f_el, fill=INK)
        sy = 1330; im.paste(strip_dim, (0, sy)); px = int(vx(mile)); im.paste(strip_lit.crop((0, 0, px, 170)), (0, sy))
        im.paste(pdot, (px - 10, int(sy + vy(elev(mile)) - 10)), pdot)
        c = hook_cap if t < T_HOOK else end_cap if t >= t_end else labels[lab] if lab is not None else None
        ca = 1 if t < T_HOOK else clamp((t - t_end) / .25, 0, 1) if t >= t_end else la
        if c is not None: paste_alpha(im, c, (SCX - c.width / 2, MVH - 30 - c.height), ca)
        return im
    return with_slate(frame, dur), dur

# ---------- Short 3: best stop ----------
def best_stop():
    want = TRIP.get("best_stop")
    return next((s for s in STOPS if s["name"] == want), None) or max(STOPS, key=lambda s: len(s["rows"]))
def mini_map(size, hi):
    """Whole route in a small card, every stop dotted, `hi` (a stop) highlighted."""
    k = 2; W_, H_ = size; im = Image.new("RGBA", (W_ * k, H_ * k), (0, 0, 0, 0)); dr = ImageDraw.Draw(im)
    xs, ys = [p[0] for p in route], [p[1] for p in route]; pad = min(70, int(min(W_, H_) * .1))
    sc = min((W_ - 2 * pad) / (max(xs) - min(xs)), (H_ - 2 * pad) / (max(ys) - min(ys)))
    ox, oy = (W_ - (max(xs) - min(xs)) * sc) / 2, (H_ - (max(ys) - min(ys)) * sc) / 2
    M = lambda p: ((ox + (p[0] - min(xs)) * sc) * k, (oy + (p[1] - min(ys)) * sc) * k)
    pts = [M(p) for p in route]
    dr.line(pts, fill=ACC + (70,), width=14 * k, joint="curve"); dr.line(pts, fill=ACC + (255,), width=5 * k, joint="curve")
    for s in STOPS:
        x, y = M(route[s["idx"]]); r = 7 * k
        dr.ellipse([x - r, y - r, x + r, y + r], fill=BG + (255,), outline=INK + (255,), width=3 * k)
    x, y = M(route[hi["idx"]])
    im = im.resize(size, Image.LANCZOS)
    return im, (x / k, y / k)
def short3():
    s = best_stop(); n = len(s["rows"]); T_NAME, T_MAP = 5.0, 7.0
    row_t = max(4.5, (31 - T_NAME - T_MAP - SLATE) / n); dur = T_NAME + n * row_t + T_MAP + SLATE
    phases = [0.0] + [T_NAME + i * row_t for i in range(n)] + [T_NAME + n * row_t]
    paths = stop_photos(s)
    if paths: photos = [cover(Image.open(p), (int(VW * 1.12), int(VH * 1.12))) for p in paths]
    else:
        ph, _ = photo_slot(s["hue"], 3); photos = [cover(ph, (int(VW * 1.12), int(VH * 1.12)))]
    shade = Image.new("RGBA", (VW, VH), (0, 0, 0, 0)); sd = ImageDraw.Draw(shade)
    for y in range(VH):
        a = max(240 * (1 - y / 720) ** 1.1 if y < 720 else 0, 235 * clamp((y - 640) / 900, 0, 1) ** .9)
        sd.line([(0, y), (VW, y)], fill=DARK + (int(a),))
    title = Image.new("RGBA", (VW, 700), (0, 0, 0, 0)); td = ImageDraw.Draw(title)
    fk = F("Inter-Bold", 28); td.text((SX0, 190), CHANNEL_LABEL, font=fk, fill=ACC, anchor="lm")
    td.text((SX0 + fk.getlength(CHANNEL_LABEL), 190), f"  ·  {STATE}", font=fk, fill=TEAL, anchor="lm")
    fn_ = F("InterDisplay-Bold", 124); nl = wrap(td, s["name"], fn_, SX1 - SX0)
    if len(nl) > 2: fn_ = F("InterDisplay-Bold", 96); nl = wrap(td, s["name"], fn_, SX1 - SX0)
    for i, l in enumerate(nl): td.text((SX0 - 4, 222 + i * 128), l, font=fn_, fill=INK)
    td.text((SX0, 222 + len(nl) * 128 + 30), f"{s['sub']}  ·  {TRIP['name']}", font=F("Inter-SemiBold", 36), fill=TEAL)
    rows = []
    for lab, txt in s["rows"]:
        f, lines = fit_words(words_of(txt), SX1 - SX0 - 64, (56, 54, 52)); lh = int(f.size * 1.22)
        bh = 66 + lh * len(lines) + 22; im = Image.new("RGBA", (SX1 - SX0, bh), (0, 0, 0, 0)); dr = ImageDraw.Draw(im)
        dr.rounded_rectangle([0, 0, SX1 - SX0 - 1, bh - 1], 22, fill=(6, 10, 14, 214))
        dr.text((32, 24), lab, font=F("Inter-Bold", 28), fill=ACC)
        for i, l in enumerate(lines): draw_words(dr, 32, 64 + i * lh, l, f)
        rows.append(im)
    ys = []; y = SY1 - 10
    for r in reversed(rows): y -= r.height; ys.insert(0, y); y -= 18
    card_w, card_h = SX1 - SX0, 760
    mm, (hx, hy) = mini_map((card_w, card_h - 90), s)
    card = Image.new("RGBA", (card_w, card_h), (0, 0, 0, 0)); cd = ImageDraw.Draw(card)
    cd.rounded_rectangle([0, 0, card_w - 1, card_h - 1], 26, fill=PANEL + (236,), outline=LINE + (255,), width=2)
    cd.text((32, 46), "WHERE IT SITS ON THE ROUTE", font=F("Inter-Bold", 26), fill=ACC, anchor="lm")
    card.paste(mm, (0, 90), mm); hy += 90
    card_y = 520; map_cap = caption_img(words_of(f"Mile {s['mile']} of {TRIP['miles']} on the {TRIP['name']}"))
    def photo_at(i, loc, span):
        p = photos[i % len(photos)]; z = 1.0 + .10 * clamp(loc / span, 0, 1)
        cw_, ch_ = p.width / z, p.height / z; x0 = (p.width - cw_) / 2 + (8 if i % 2 else -8) * loc; y0 = (p.height - ch_) / 2
        x0 = clamp(x0, 0, p.width - cw_)
        return p.resize((VW, VH), Image.BILINEAR, box=(x0, y0, x0 + cw_, y0 + ch_))
    def frame(t):
        k = max(i for i, p0 in enumerate(phases) if t >= p0); span = (phases[k + 1] if k + 1 < len(phases) else dur) - phases[k]
        im = photo_at(k, t - phases[k], span + 1)
        if k and t - phases[k] < .6: im = Image.blend(photo_at(k - 1, t - phases[k - 1], span + 1), im, ease((t - phases[k]) / .6))
        im = im.convert("RGBA"); im.alpha_composite(shade); im.alpha_composite(title)
        t_map = phases[-1]; out_a = 1 - clamp((t - t_map) / .4, 0, 1)
        for i, r in enumerate(rows):
            a = clamp((t - phases[i + 1]) / .35, 0, 1) * out_a
            if a > 0: paste_alpha(im, r, (SX0, ys[i] + int((1 - ease(min(1, a))) * 20)), a)
        if t >= t_map:
            a = clamp((t - t_map - .2) / .4, 0, 1); c = card.copy(); cdr = ImageDraw.Draw(c)
            pr = 22 + 6 * math.sin((t - t_map) * 5)
            cdr.ellipse([hx - pr, hy - pr, hx + pr, hy + pr], fill=ACC + (90,)); cdr.ellipse([hx - 12, hy - 12, hx + 12, hy + 12], fill=(255, 255, 255, 255), outline=ACC + (255,), width=5)
            fl = F("Inter-Bold", 34); lw = fl.getlength(s["name"]); lx = clamp(hx - lw / 2, 24, card_w - 24 - lw)
            ly = hy - 58 if hy > 160 else hy + 30
            cdr.text((lx, ly), s["name"], font=fl, fill=INK, stroke_width=5, stroke_fill=PANEL)
            paste_alpha(im, c, (SX0, card_y + int((1 - ease(a)) * 24)), a)
            paste_alpha(im, map_cap, (SCX - map_cap.width / 2, SY1 - 10 - map_cap.height), clamp((t - t_map - .5) / .3, 0, 1))
        return im.convert("RGB")
    return with_slate(frame, dur), dur, s

# ---------- Pinterest pin ----------
def make_pin(out):
    PW_, PH_ = 1000, 1500; top_h = int(PH_ * .55); s = best_stop(); paths = stop_photos(s)
    im = Image.new("RGB", (PW_, PH_), BG)
    ph = cover(Image.open(paths[0]), (PW_, top_h)) if paths else cover(photo_slot(s["hue"], 3)[0], (PW_, top_h))
    im.paste(ph, (0, 0)); g = Image.new("RGBA", (PW_, 220), (0, 0, 0, 0)); gd = ImageDraw.Draw(g)
    for y in range(220): gd.line([(0, y), (PW_, y)], fill=BG + (int(255 * (y / 220) ** 1.6),))
    im.paste(g, (0, top_h - 220), g); dr = ImageDraw.Draw(im); x = 64; y = top_h + 34
    dr.text((x, y), f"{STATE} ROAD TRIP", font=F("Inter-Bold", 32), fill=TEAL); y += 52
    fn_ = F("InterDisplay-Bold", 92); nl = wrap(dr, TRIP["name"], fn_, PW_ - 2 * x)
    for l in nl: dr.text((x - 3, y), l, font=fn_, fill=INK); y += 100
    y += 16; fm = F("InterDisplay-Bold", 150); mt = f"{TRIP['miles']:,}"
    dr.text((x - 4, y), mt, font=fm, fill=ACC); mw = dr.textlength(mt, font=fm)
    dr.text((x + mw + 14, y + 94), "MILES", font=F("Inter-Bold", 40), fill=INK)
    rl, _ = mini_map((300, 230), s); im.paste(rl, (PW_ - 300 - 30, y - 30), rl); y += 196
    for l in wrap(dr, TRIP.get("pin_hook") or TRIP["tagline"].replace("  ·  ", " · "), F("Inter-SemiBold", 36), PW_ - 2 * x)[:2]:
        dr.text((x, y), l, font=F("Inter-SemiBold", 36), fill=MUTE); y += 48
    dr.line([(x, PH_ - 110), (PW_ - x, PH_ - 110)], fill=LINE, width=2)
    draw_logo(im, x, PH_ - 58, 34)
    im.save(out); print(f"wrote {out}", file=sys.stderr)

# ---------- YouTube chapters for the full video ----------
def chapter_list():
    """Intro, By the Numbers, each stop's hold, Up next. YouTube needs 0:00 first and every chapter >= 10 s,
    so a chapter that would start too soon moves later inside its own section, or folds into the one before."""
    raw = [(0.0, "Intro"), (T_TITLE, "By the Numbers")]
    holds = [(t0, t1, STOPS[d]["name"]) for t0, t1, k, d in events if k == "hold"]
    raw += [(t0, nm) for t0, _, nm in holds] + [(t_out, "Up next")]
    ends = [T0] + [t1 for _, t1, _ in holds] + [TOTAL]
    out = [list(raw[0])]
    for (t0, nm), end in zip(raw[1:], ends):
        start = max(t0, out[-1][0] + 10)
        if start < end - 1: out.append([start, nm])
        else: out[-1][1] += " & " + nm
    if TOTAL - out[-1][0] < 10:
        if len(out) > 1 and TOTAL - 10 >= out[-2][0] + 10: out[-1][0] = TOTAL - 10
        else: last = out.pop(); out[-1][1] += " & " + last[1]
    return [(int(t), nm) for t, nm in out]
def write_chapters(out):
    with open(out, "w") as fh:
        for t, nm in chapter_list(): fh.write(f"{int(t) // 60}:{int(t) % 60:02d} {nm}\n")
    print(f"wrote {out}", file=sys.stderr)

def export_social(out_dir):
    os.makedirs(out_dir, exist_ok=True); p = lambda name: os.path.join(out_dir, f"{SLUG}_{name}")
    write_chapters(p("chapters.txt")); make_pin(p("pin.png"))
    fn, dur = short1(); encode(fn, dur, p("short1_numbers.mp4"), narration("short1"))
    fn, dur = short2(); encode(fn, dur, p("short2_route.mp4"), narration("short2"))
    fn, dur, s = short3(); encode(fn, dur, p(f"short3_{re.sub(r'[^a-z0-9]+', '-', s['name'].lower()).strip('-')}.mp4"), narration("short3"))

# ---------- main 16:9 render ----------
def render_main(out_path):
    ff = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
                           "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p", "-movflags", "+faststart", out_path],
                          stdin=subprocess.PIPE)
    frame_bg = Image.new("RGB", (W, H), PANEL)
    drawn = 0; badged = set(); R = int(8 * Z)
    cam = [CXG, CYG, 1.0]; dt = 1 / FPS; YC = 465
    for f in range(int(TOTAL * FPS)):
        ts = f / FPS
        pos, card, ca, idle, cap, capa = 0.0, None, 0.0, idle_start, None, 0.0
        for t0, t1, kind, data in events:
            if kind == "hold" and ts >= t0:
                pos = STOPS[data]["idx"]
                if data not in badged:
                    x, y = route[int(pos)]; wover.alpha_composite(badge(data + 1), (int(ws(x) - 28), int(ws(y) - 28))); badged.add(data)
                if ts < t1 + .4: card = data; ca = min(1, (ts - t0) / .5) * clamp((t1 + .4 - ts) / .4, 0, 1)
                if ts < t1: cap = data; capa = clamp((ts - t0 - .5) / .4, 0, 1) * clamp((t1 - ts) / .4, 0, 1)
            if kind == "travel" and t0 <= ts:
                a, b_, nx = data; idle = idle_end if nx is None else idles[nx]; pos = a + (b_ - a) * ease(min(1, (ts - t0) / (t1 - t0)))
        ip = int(pos)
        if ip > drawn:
            for px, py in route[max(0, drawn - 1):ip + 1]: mdraw.ellipse([ws(px) - R, ws(py) - R, ws(px) + R, ws(py) + R], fill=255)
            drawn = ip
        carx, cary = route[ip]
        # camera
        overview = ts < T0 + 1.6 or ts > t_final + 1.3
        tx, ty, tz = (CXG, CYG, 1.0) if overview else (carx, cary, Z)
        kc, kz = 1 - math.exp(-dt / .30), 1 - math.exp(-dt / .50)
        cam[0] += (tx - cam[0]) * kc; cam[1] += (ty - cam[1]) * kc; cam[2] += (tz - cam[2]) * kz
        z = cam[2]; w = min(WW, int(round(MAPW * Z / z))); h = min(WH, int(round(w * H / MAPW)))
        x0 = int(clamp(ws(cam[0]) - w / 2, 0, WW - w)); y0 = int(clamp(ws(cam[1]) - YC * h / H, 0, WH - h)); box = (x0, y0, x0 + w, y0 + h)
        view = wbase.crop(box)
        view.paste(ACC, (0, 0, w, h), ImageChops.multiply(route_a.crop(box), wmask.crop(box)))
        ov = wover.crop(box); view.paste(ov, (0, 0), ov)
        if (w, h) != (MAPW, H): view = view.resize((MAPW, H), Image.BILINEAR)
        fr = frame_bg.copy(); fr.paste(view, (0, 0))
        mx, my = (ws(carx) - x0) * MAPW / w, (ws(cary) - y0) * H / h
        fr.paste(marker, (int(mx - 26), int(my - 26)), marker)
        # HUD
        fr.paste(hud, (0, 0), hud); dr = ImageDraw.Draw(fr)
        mile = mile_at(pos); mtxt = str(int(round(mile)))
        dr.text((48, 136), mtxt, font=f_mile, fill=INK)
        dr.text((48 + dr.textlength(mtxt, font=f_mile) + 10, 164), f'of {TRIP["miles"]}', font=f_of, fill=MUTE)
        dr.text((262, 146), f"{int(round(elev(mile))):,} ft", font=f_el, fill=INK)
        fr.paste(strip_dim, (0, H - STRIP)); px = int(ex(mile))
        fr.paste(strip_lit.crop((0, 0, px, STRIP)), (0, H - STRIP))
        fr.paste(pdot, (px - 10, int(H - STRIP + ey(elev(mile)) - 10)), pdot)
        capa *= clamp((z - 1.7) / .4, 0, 1)
        if cap is not None and capa > 0:
            c = caps[cap]; bx = (MAPW - c.width) // 2; by = H - STRIP - 26 - c.height; reg = (bx, by, bx + c.width, by + c.height)
            base_reg = fr.crop(reg); comp = base_reg.copy(); comp.paste(c, (0, 0), c); fr.paste(Image.blend(base_reg, comp, capa), reg)
        dr.line([(MAPW, 0), (MAPW, H)], fill=LINE, width=2)
        fr.paste(idle if card is None else (Image.blend(idle, cards[card], ca) if ca < 1 else cards[card]), (MAPW + 2, 0))
        if ts < T0 + .6:
            if ts < T_TITLE - .25: ovl = title
            else:
                ovl = stats_frame(ts - T_TITLE)
                if ts < T_TITLE + .25: ovl = Image.blend(title, ovl, (ts - T_TITLE + .25) / .5)
            a = 1 - max(0, (ts - T0) / .6); fr = Image.blend(fr, ovl, a) if a < 1 else ovl
        if ts > t_out: fr = Image.blend(fr, endcard, min(1, (ts - t_out) / .7))
        ff.stdin.write(fr.tobytes())
    ff.stdin.close(); ff.wait()

if __name__ == "__main__":
    # python3 build_video.py out.mp4 [--social-only | --no-social]
    # The 16:9 video, then the vertical clips, pin and chapters next to it.
    out = next(a for a in sys.argv[1:] if not a.startswith("--"))
    if "--social-only" not in sys.argv: render_main(out)
    if "--no-social" not in sys.argv: export_social(os.path.dirname(os.path.abspath(out)))
