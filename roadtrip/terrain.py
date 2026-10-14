"""Elevation from the free AWS Terrain Tiles (Mapzen "terrarium" encoding).

Tiles are cached under .cache/terrain/ so re-renders work offline. If tiles can't be
fetched, callers get None and fall back to elevations interpolated between stops.
"""

import io
import math
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from PIL import Image

TILE_URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
USER_AGENT = "road-trip-videos/1.0 (https://github.com/nhantge/road-trip-videos)"
ATTRIBUTION = ("Elevation: AWS Terrain Tiles (USGS 3DEP, SRTM, GMTED2010, ETOPO1 and others, "
               "https://registry.opendata.aws/terrain-tiles/)")


def lonlat_to_world(lon, lat):
    """Web Mercator, normalized so the whole world spans 0..1 in x and y."""
    lat = np.clip(lat, -85.0511, 85.0511)
    x = (np.asarray(lon) + 180.0) / 360.0
    s = np.sin(np.radians(lat))
    y = 0.5 - np.log((1 + s) / (1 - s)) / (4 * math.pi)
    return x, y


def world_to_lonlat(x, y):
    lon = np.asarray(x) * 360.0 - 180.0
    lat = np.degrees(np.arctan(np.sinh(math.pi * (1 - 2 * np.asarray(y)))))
    return lon, lat


class Terrain:
    def __init__(self, cache_dir, offline=False):
        self.cache_dir = Path(cache_dir)
        self.offline = offline
        self.failed = False
        self._tiles = {}

    def tile(self, z, x, y):
        key = (z, x, y)
        if key in self._tiles:
            return self._tiles[key]
        path = self.cache_dir / str(z) / str(x) / f"{y}.png"
        data = None
        if path.exists():
            data = path.read_bytes()
        elif not self.offline and not self.failed:
            try:
                req = urllib.request.Request(TILE_URL.format(z=z, x=x, y=y), headers={"User-Agent": USER_AGENT})
                with urllib.request.urlopen(req, timeout=30) as resp:
                    data = resp.read()
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            except OSError as err:
                print(f"  terrain tiles unavailable ({err}); using stop elevations only", file=sys.stderr)
                self.failed = True
        elev = None
        if data:
            rgb = np.asarray(Image.open(io.BytesIO(data)).convert("RGB"), dtype=np.float32)
            elev = rgb[..., 0] * 256 + rgb[..., 1] + rgb[..., 2] / 256 - 32768
        self._tiles[key] = elev
        return elev

    def prefetch(self, keys):
        todo = [k for k in keys if k not in self._tiles]
        with ThreadPoolExecutor(8) as pool:
            list(pool.map(lambda k: self.tile(*k), todo))

    def mosaic(self, x0, y0, x1, y1, z):
        """Elevation grid (meters) covering world rect [x0,x1]x[y0,y1] at zoom z.

        Returns (array, origin_x, origin_y, scale) where pixel (i, j) sits at world
        (origin_x + j / scale, origin_y + i / scale), or None if tiles are missing.
        """
        n = 2 ** z
        tx0, tx1 = int(x0 * n), int(x1 * n)
        ty0, ty1 = int(y0 * n), int(y1 * n)
        keys = [(z, tx, ty) for ty in range(ty0, ty1 + 1) for tx in range(tx0, tx1 + 1)]
        self.prefetch(keys)
        rows = []
        for ty in range(ty0, ty1 + 1):
            row = []
            for tx in range(tx0, tx1 + 1):
                t = self.tile(z, tx, ty)
                if t is None:
                    return None
                row.append(t)
            rows.append(np.hstack(row))
        return np.vstack(rows), tx0 / n, ty0 / n, n * 256

    def sample(self, wx, wy, z=11):
        """Bilinear elevation (meters) at world coordinates, or None if unavailable."""
        n = 2 ** z
        px = np.asarray(wx) * n * 256 - 0.5
        py = np.asarray(wy) * n * 256 - 0.5
        keys = {(z, int(x) // 256, int(y) // 256) for x, y in zip(px, py)}
        keys |= {(z, int(x + 1) // 256, int(y + 1) // 256) for x, y in zip(px, py)}
        self.prefetch(keys)
        out = np.empty(len(px), dtype=np.float64)

        def at(ix, iy):
            t = self.tile(z, ix // 256, iy // 256)
            if t is None:
                raise LookupError
            return t[iy % 256, ix % 256]

        try:
            for k, (x, y) in enumerate(zip(px, py)):
                ix, iy = int(math.floor(x)), int(math.floor(y))
                fx, fy = x - ix, y - iy
                out[k] = ((at(ix, iy) * (1 - fx) + at(ix + 1, iy) * fx) * (1 - fy)
                          + (at(ix, iy + 1) * (1 - fx) + at(ix + 1, iy + 1) * fx) * fy)
        except LookupError:
            return None
        return out


def hillshade(elev, meters_per_px, altitude=40, exaggeration=2.0):
    """Hillshade in 0..1, lit from the northwest (rows run south, columns east)."""
    gy, gx = np.gradient(elev * exaggeration, meters_per_px)
    c, s = math.cos(math.radians(altitude)) * math.sqrt(0.5), math.sin(math.radians(altitude))
    shade = (c * (gx + gy) + s) / np.sqrt(gx * gx + gy * gy + 1)
    return np.clip(shade, 0, 1)
