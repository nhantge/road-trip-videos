"""Route files: loading, geometry, mileage and elevation.

A route is a list of stops. The leg *into* each stop can carry shaping points
(`via`), a road name, the real road mileage and drive time. The drawn line is a
smooth spline through stops and via points; the mile counter is scaled so each
leg adds up to its real road miles.
"""

import math
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .terrain import lonlat_to_world

FT_PER_M = 3.28084
EARTH_MILES = 3958.8
DEFAULT_MPH = 45  # used only when a leg has no drive_time
WIGGLE = 1.12     # spline miles -> road miles when a leg has no `miles`


def slugify(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "route"


def parse_minutes(text):
    """'1 hr 15 min' / '50 min' / '2h' -> minutes."""
    if text is None:
        return None
    h = re.search(r"(\d+(?:\.\d+)?)\s*h", text)
    m = re.search(r"(\d+)\s*m", text)
    if not h and not m:
        raise ValueError(f"can't read drive_time {text!r} (try '1 hr 15 min')")
    return (float(h.group(1)) * 60 if h else 0) + (int(m.group(1)) if m else 0)


@dataclass
class Place:
    """A labeled point on the map that isn't a stop (a town or pass you drive through)."""
    name: str
    lat: float
    lon: float
    kind: str = "town"
    elevation_ft: float | None = None
    mile: float = 0.0


@dataclass
class Stop:
    name: str
    lat: float
    lon: float
    kind: str = "town"
    tag: str = ""
    elevation_ft: float | None = None
    caption: str = ""
    fact: str = ""
    narration: str = ""
    info: dict = field(default_factory=dict)
    photo_query: str = ""
    photos: list = field(default_factory=list)
    # The leg that arrives here (unused for the first stop).
    road: str = ""
    miles: float | None = None
    drive_minutes: float | None = None
    via: list = field(default_factory=list)
    drive_caption: str = ""
    drive_fact: str = ""
    drive_narration: str = ""
    # Filled in by Route.
    mile: float = 0.0
    index: int = 0


@dataclass
class Route:
    title: str
    stops: list
    path: Path
    series: str = ""
    region: str = ""
    days: str = ""
    best_season: str = ""
    hook: list = field(default_factory=list)
    tips: list = field(default_factory=list)
    narration: dict = field(default_factory=dict)
    inset: dict = field(default_factory=dict)
    up_next: dict = field(default_factory=dict)
    places: list = field(default_factory=list)

    @property
    def slug(self):
        return self.path.stem

    # -- geometry ------------------------------------------------------------

    def build(self, terrain=None):
        """Compute the dense route line, per-point road miles and elevation."""
        ctrl, owner = [], []  # control points, and which stop (if any) each one is
        for i, stop in enumerate(self.stops):
            stop.index = i
            points = [(v.lat, v.lon) if isinstance(v, Place) else tuple(v) for v in stop.via] if i else []
            for p, who in [(p, None) for p in points] + [((stop.lat, stop.lon), i)]:
                if ctrl and abs(ctrl[-1][0] - p[0]) + abs(ctrl[-1][1] - p[1]) < 1e-6:
                    owner[-1] = who if who is not None else owner[-1]  # drop duplicate points
                    continue
                ctrl.append(p)
                owner.append(who)
        stop_ctrl = [owner.index(i) for i in range(len(self.stops))]
        lat = np.array([c[0] for c in ctrl])
        lon = np.array([c[1] for c in ctrl])
        wx, wy = lonlat_to_world(lon, lat)
        dense_x, dense_y, ctrl_idx = catmull_rom(np.stack([wx, wy], 1), samples=48)
        self.wx, self.wy = dense_x, dense_y
        stop_idx = [ctrl_idx[c] for c in stop_ctrl]

        # Great-circle length of each dense segment, then scale each leg to road miles.
        from .terrain import world_to_lonlat
        dlon, dlat = world_to_lonlat(dense_x, dense_y)
        seg = haversine(dlat[:-1], dlon[:-1], dlat[1:], dlon[1:])
        miles = np.zeros(len(dense_x))
        for i in range(1, len(self.stops)):
            a, b = stop_idx[i - 1], stop_idx[i]
            leg = seg[a:b]
            stop = self.stops[i]
            target = stop.miles if stop.miles else leg.sum() * WIGGLE
            stop.miles = round(float(target))
            miles[a + 1:b + 1] = miles[a] + np.cumsum(leg) * (target / max(leg.sum(), 1e-9))
            if stop.drive_minutes is None:
                stop.drive_minutes = round(target / DEFAULT_MPH * 60 / 5) * 5
        self.mi = miles
        self.total_miles = float(miles[-1])
        self.stop_idx = stop_idx
        for stop, idx in zip(self.stops, stop_idx):
            stop.mile = float(miles[idx])

        # Labeled places along the way get the mile of their nearest line point.
        self.places = []
        for stop in self.stops[1:]:
            for v in stop.via:
                if isinstance(v, Place):
                    k = int(np.argmin((dlat - v.lat) ** 2 + (dlon - v.lon) ** 2))
                    v.mile = float(miles[k])
                    self.places.append(v)
        self._build_elevation(terrain, dlat, dlon)
        return self

    def _build_elevation(self, terrain, dlat, dlon):
        """Elevation profile (ft) sampled every ~0.25 mi, pinned to known elevations."""
        n = max(200, int(self.total_miles * 4))
        # Sample every ~0.25 mi plus exactly at each stop and named place, so readouts match.
        named = [s.mile for s in self.stops] + [p.mile for p in self.places]
        self.prof_mi = np.unique(np.concatenate([np.linspace(0, self.total_miles, n), named]))
        px = np.interp(self.prof_mi, self.mi, self.wx)
        py = np.interp(self.prof_mi, self.mi, self.wy)
        anchors = [(s.mile, s.elevation_ft) for s in self.stops if s.elevation_ft]
        anchors += [(p.mile, p.elevation_ft) for p in self.places if p.elevation_ft]
        anchors.sort()
        sampled = terrain.sample(px, py) if terrain else None
        self.elevation_from_terrain = sampled is not None
        if sampled is None:
            if not anchors:
                raise ValueError("no terrain data and no elevation_ft on any stop")
            prof = np.interp(self.prof_mi, [a[0] for a in anchors], [a[1] for a in anchors])
        else:
            prof = moving_average(sampled * FT_PER_M, 7)
            if anchors:
                # The drawn line only approximates the road, so nudge the terrain
                # profile to pass exactly through the known stop/pass elevations.
                offsets = [e - np.interp(m, self.prof_mi, prof) for m, e in anchors]
                prof = prof + np.interp(self.prof_mi, [a[0] for a in anchors], offsets)
            # A pass is the high point of the road over it; trim terrain bumps next to it.
            for p in self.stops + self.places:
                if p.kind == "pass" and p.elevation_ft:
                    near = np.abs(self.prof_mi - p.mile) < 5
                    prof[near] = np.minimum(prof[near], p.elevation_ft)
        self.prof_ft = prof
        for s in self.stops:
            if not s.elevation_ft:
                s.elevation_ft = round(float(np.interp(s.mile, self.prof_mi, prof)))

    # -- lookups -------------------------------------------------------------

    def point_at(self, mile):
        mile = min(max(mile, 0.0), self.total_miles)
        return float(np.interp(mile, self.mi, self.wx)), float(np.interp(mile, self.mi, self.wy))

    def index_at(self, mile):
        """Fractional dense-point index at a mile."""
        return float(np.interp(mile, self.mi, np.arange(len(self.mi))))

    def elevation_at(self, mile):
        return float(np.interp(mile, self.prof_mi, self.prof_ft))

    @property
    def total_drive_minutes(self):
        return sum(s.drive_minutes or 0 for s in self.stops[1:])

    @property
    def passes(self):
        named = [s for s in self.stops if s.kind == "pass"] + [p for p in self.places if p.kind == "pass"]
        return sorted(named, key=lambda p: p.mile)

    @property
    def climb_ft(self):
        d = np.diff(self.prof_ft)
        return float(d[d > 0].sum())

    def high_point(self):
        """(elevation ft, name of the nearest named point) for the highest point."""
        k = int(np.argmax(self.prof_ft))
        named = list(self.stops) + list(self.places)
        near = min(named, key=lambda p: abs(p.mile - self.prof_mi[k]))
        return float(self.prof_ft[k]), near.name

    def low_point(self):
        k = int(np.argmin(self.prof_ft))
        named = list(self.stops) + list(self.places)
        near = min(named, key=lambda p: abs(p.mile - self.prof_mi[k]))
        return float(self.prof_ft[k]), near.name


# -- loading -----------------------------------------------------------------

STOP_KEYS = {"name", "lat", "lon", "kind", "tag", "elevation_ft", "caption", "fact", "narration",
             "info", "photo_query", "photos", "road", "miles", "drive_time", "via",
             "drive_caption", "drive_fact", "drive_narration"}
ROUTE_KEYS = {"title", "series", "region", "days", "best_season", "hook", "tips", "narration",
              "inset", "up_next", "stops"}


def load_route(path):
    path = Path(path)
    data = tomllib.loads(path.read_text())
    unknown = set(data) - ROUTE_KEYS
    if unknown:
        raise ValueError(f"{path}: unknown keys {sorted(unknown)}")
    if len(data.get("stops", [])) < 2:
        raise ValueError(f"{path}: a route needs at least two [[stops]]")
    stops = []
    for raw in data["stops"]:
        unknown = set(raw) - STOP_KEYS
        if unknown:
            raise ValueError(f"{path}: stop {raw.get('name')!r} has unknown keys {sorted(unknown)}")
        for key in ("name", "lat", "lon"):
            if key not in raw:
                raise ValueError(f"{path}: every stop needs {key}")
        via = []
        for v in raw.get("via", []):
            if isinstance(v, dict):
                via.append(Place(name=v["name"], lat=v["lat"], lon=v["lon"], kind=v.get("kind", "town"),
                                 elevation_ft=v.get("elevation_ft")))
            else:
                via.append((float(v[0]), float(v[1])))
        stops.append(Stop(
            name=raw["name"], lat=raw["lat"], lon=raw["lon"], kind=raw.get("kind", "town"),
            tag=raw.get("tag", ""), elevation_ft=raw.get("elevation_ft"), caption=raw.get("caption", ""),
            fact=raw.get("fact", ""), narration=raw.get("narration", ""), info=raw.get("info", {}),
            photo_query=raw.get("photo_query", raw["name"]), photos=raw.get("photos", []),
            road=raw.get("road", ""), miles=raw.get("miles"),
            drive_minutes=parse_minutes(raw.get("drive_time")), via=via,
            drive_caption=raw.get("drive_caption", ""), drive_fact=raw.get("drive_fact", ""),
            drive_narration=raw.get("drive_narration", ""),
        ))
    return Route(
        title=data.get("title") or f"{stops[0].name} to {stops[-1].name}", stops=stops, path=path,
        series=data.get("series", ""), region=data.get("region", ""), days=data.get("days", ""),
        best_season=data.get("best_season", ""), hook=data.get("hook", []), tips=data.get("tips", []),
        narration=data.get("narration", {}), inset=data.get("inset", {}), up_next=data.get("up_next", {}),
    )


# -- math --------------------------------------------------------------------

def haversine(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 2 * EARTH_MILES * np.arcsin(np.sqrt(a))


def catmull_rom(pts, samples=48, alpha=0.5):
    """Centripetal Catmull-Rom through pts (N,2). Returns xs, ys and the dense
    index of each control point."""
    if len(pts) == 2:
        t = np.linspace(0, 1, samples + 1)
        line = pts[0] + (pts[1] - pts[0]) * t[:, None]
        return line[:, 0], line[:, 1], [0, samples]
    ext = np.vstack([2 * pts[0] - pts[1], pts, 2 * pts[-1] - pts[-2]])
    out, idx = [pts[0]], [0]
    for i in range(1, len(ext) - 2):
        p0, p1, p2, p3 = ext[i - 1], ext[i], ext[i + 1], ext[i + 2]
        t0 = 0.0
        t1 = t0 + max(np.linalg.norm(p1 - p0), 1e-12) ** alpha
        t2 = t1 + max(np.linalg.norm(p2 - p1), 1e-12) ** alpha
        t3 = t2 + max(np.linalg.norm(p3 - p2), 1e-12) ** alpha
        for t in np.linspace(t1, t2, samples + 1)[1:]:
            a1 = (t1 - t) / (t1 - t0) * p0 + (t - t0) / (t1 - t0) * p1
            a2 = (t2 - t) / (t2 - t1) * p1 + (t - t1) / (t2 - t1) * p2
            a3 = (t3 - t) / (t3 - t2) * p2 + (t - t2) / (t3 - t2) * p3
            b1 = (t2 - t) / (t2 - t0) * a1 + (t - t0) / (t2 - t0) * a2
            b2 = (t3 - t) / (t3 - t1) * a2 + (t - t1) / (t3 - t1) * a3
            out.append((t2 - t) / (t2 - t1) * b1 + (t - t1) / (t2 - t1) * b2)
        idx.append(len(out) - 1)
    out = np.array(out)
    return out[:, 0], out[:, 1], idx


def moving_average(a, k):
    if k <= 1:
        return a
    pad = np.pad(a, (k // 2, k - 1 - k // 2), mode="edge")
    return np.convolve(pad, np.ones(k) / k, mode="valid")
