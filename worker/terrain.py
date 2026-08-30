"""Terrain access inside the sandbox. NUMPY ONLY.

No geopandas, no rasterio, no scipy -- they are heavy and they multiply across
200 sandboxes. Everything here works on the four float32 arrays baked into the
snapshot at /data/.

Arrays are 1395 x 1510 at 30 m, row-major, **row 0 is NORTH**. Get that
backwards and every trajectory is mirrored, which looks completely plausible
on screen and only shows up when validation scores badly.

All lookups are vectorised: one call samples every walker at once, because the
runner simulates all 60 seeds simultaneously rather than looping.
"""
from __future__ import annotations

import json
import os

import numpy as np

M_PER_DEG_LAT = 110_574.0

DEFAULT_DATA_DIR = os.environ.get("SEARCHLIGHT_DATA", "/data")

# Beyond this the ground is effectively a cliff to a walking subject. Used to
# make slope prohibitive rather than merely expensive.
IMPASSABLE_SLOPE_DEG = 45.0


def m_per_deg_lon(lat):
    return 111_320.0 * np.cos(np.radians(lat))


class Terrain:
    """Elevation, slope, trail distance and water distance on a common grid."""

    def __init__(self, data_dir=None):
        d = data_dir or DEFAULT_DATA_DIR
        with open(os.path.join(d, "meta.json")) as fh:
            self.meta = json.load(fh)
        b = self.meta["bounds"]
        self.north, self.south = b["north"], b["south"]
        self.east, self.west = b["east"], b["west"]
        self.rows, self.cols = self.meta["shape"]
        self.cell_m = float(self.meta["cell_m"])

        self.elevation = np.load(os.path.join(d, "elevation.npy"))
        self.slope = np.load(os.path.join(d, "slope.npy"))
        self.trail_dist = np.load(os.path.join(d, "trail_dist.npy"))
        self.water_dist = np.load(os.path.join(d, "water_dist.npy"))

        for name in ("elevation", "slope", "trail_dist", "water_dist"):
            a = getattr(self, name)
            if a.shape != (self.rows, self.cols):
                raise ValueError(
                    "{}.npy is {} but meta.json says {} -- the arrays and the "
                    "grid disagree, regenerate with prep/fetch_terrain.py"
                    .format(name, a.shape, (self.rows, self.cols)))

        self.mid_lat = (self.north + self.south) / 2.0
        self.m_lon = float(m_per_deg_lon(self.mid_lat))
        self.m_lat = M_PER_DEG_LAT

    # -- indexing -----------------------------------------------------------

    def rowcol(self, lat, lon):
        """Fractional row/col. Row 0 is NORTH, so row increases southward."""
        r = (self.north - np.asarray(lat)) / (self.north - self.south) * self.rows
        c = (np.asarray(lon) - self.west) / (self.east - self.west) * self.cols
        return r, c

    def inside(self, lat, lon):
        lat, lon = np.asarray(lat), np.asarray(lon)
        return ((lat >= self.south) & (lat <= self.north)
                & (lon >= self.west) & (lon <= self.east))

    def _sample(self, arr, lat, lon):
        """Nearest-neighbour sample, clamped. Out-of-bounds is handled by the
        caller via `inside` -- clamping here only keeps the index legal."""
        r, c = self.rowcol(lat, lon)
        ri = np.clip(r.astype(np.int32), 0, self.rows - 1)
        ci = np.clip(c.astype(np.int32), 0, self.cols - 1)
        return arr[ri, ci]

    def elev(self, lat, lon):
        return self._sample(self.elevation, lat, lon)

    def slope_deg(self, lat, lon):
        return self._sample(self.slope, lat, lon)

    def to_trail(self, lat, lon):
        return self._sample(self.trail_dist, lat, lon)

    def to_water(self, lat, lon):
        return self._sample(self.water_dist, lat, lon)

    # -- movement helpers ---------------------------------------------------

    def offset(self, lat, lon, bearing_rad, dist_m):
        """Move dist_m along a bearing measured clockwise from north."""
        dlat = dist_m * np.cos(bearing_rad) / self.m_lat
        dlon = dist_m * np.sin(bearing_rad) / self.m_lon
        return lat + dlat, lon + dlon

    def clamp(self, lat, lon, margin_deg=1e-4):
        return (np.clip(lat, self.south + margin_deg, self.north - margin_deg),
                np.clip(lon, self.west + margin_deg, self.east - margin_deg))

    def tobler_speed_ms(self, d_elev_m, d_horiz_m):
        """Tobler's hiking function. Walking speed as a function of gradient.

            W = 6 * exp(-3.5 * |S + 0.05|)  km/h,  S = dh/dx

        The +0.05 is not a fudge: it puts peak speed on a gentle DOWNHILL,
        about -2.9 degrees, which is what people actually do. Uphill and steep
        descent both cost. Published and citable, which matters because every
        number in this project is supposed to have a source.

        Tobler, W. (1993), Three Presentations on Geographical Analysis and
        Modeling, NCGIA Technical Report 93-1.
        """
        d_horiz_m = np.maximum(d_horiz_m, 1.0)
        s = d_elev_m / d_horiz_m
        kmh = 6.0 * np.exp(-3.5 * np.abs(s + 0.05))
        return kmh / 3.6

    def summary(self, lat, lon, radius_m=2000.0):
        """Plain-English terrain description around a point.

        Feeds the hypothesis-generation prompt (CONTRACT.md section 4) so the
        model proposes site-specific behaviour rather than textbook categories.
        """
        r, c = self.rowcol(lat, lon)
        ri, ci = int(r), int(c)
        k = max(1, int(radius_m / self.cell_m))
        r0, r1 = max(0, ri - k), min(self.rows, ri + k + 1)
        c0, c1 = max(0, ci - k), min(self.cols, ci + k + 1)
        win_e = self.elevation[r0:r1, c0:c1]
        win_s = self.slope[r0:r1, c0:c1]
        here = float(self.elevation[np.clip(ri, 0, self.rows - 1),
                                    np.clip(ci, 0, self.cols - 1)])
        rel = here - float(win_e.mean())
        return {
            "elevation_m": round(here),
            "relief_m": round(float(win_e.max() - win_e.min())),
            "landform": ("ridge" if rel > 40 else
                         "drainage" if rel < -40 else "slope"),
            "mean_slope_deg": round(float(win_s.mean()), 1),
            "steep_fraction": round(float((win_s > 30).mean()), 3),
            "trail_dist_m": round(float(self.to_trail(lat, lon))),
            "water_dist_m": round(float(self.to_water(lat, lon))),
            "descends_to": _descent_bearing(self, lat, lon, radius_m),
        }


def _descent_bearing(t, lat, lon, radius_m):
    """Compass direction of steepest descent -- where a tiring subject drifts."""
    bearings = np.radians(np.arange(0, 360, 45.0))
    la, lo = t.offset(np.full(8, lat), np.full(8, lon), bearings, radius_m)
    la, lo = t.clamp(la, lo)
    drop = t.elev(np.full(8, lat), np.full(8, lon)) - t.elev(la, lo)
    names = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")
    return names[int(np.argmax(drop))]
