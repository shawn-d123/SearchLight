"""Describe the ground around a point, in plain English, from the arrays.

This is what lets the hypothesis model propose behaviours that exist only
because something looked at THIS terrain -- "followed the drainage south-east,
path of least resistance from the junction" rather than "route travelling".
Without it the model is picking from five textbook categories and a template
could do the same job.

    python orchestrator/terrain_summary.py
"""
from __future__ import annotations

import sys

from settings import DATA, WORKER

sys.path.insert(0, str(WORKER))
import sim as simmod  # noqa: E402

COMPASS = [("north", 0), ("north-east", 45), ("east", 90), ("south-east", 135),
           ("south", 180), ("south-west", 225), ("west", 270),
           ("north-west", 315)]


def _probe(terrain, lat, lon, bearing, out_m=2000.0, samples=8):
    """Walk out along a bearing, sampling the arrays."""
    here_r, here_c = terrain.rc(lat, lon)
    here_elev = float(terrain.elevation[here_r, here_c])
    pts = []
    for i in range(1, samples + 1):
        d = out_m * i / samples
        b = bearing * 3.141592653589793 / 180.0
        la = lat + d * _cos(b) / terrain.m_per_deg_lat
        lo = lon + d * _sin(b) / terrain.m_per_deg_lon
        if not terrain.in_bounds(la, lo):
            break
        r, c = terrain.rc(la, lo)
        pts.append((float(terrain.elevation[r, c]),
                    float(terrain.slope[r, c]),
                    float(terrain.trail_dist[r, c])))
    if not pts:
        return None
    elevs = [p[0] for p in pts]
    return {
        "bearing": bearing,
        "d_elev_m": elevs[-1] - here_elev,
        "min_elev_m": min(elevs),
        "max_elev_m": max(elevs),
        "mean_slope_deg": sum(p[1] for p in pts) / len(pts),
        "min_trail_dist_m": min(p[2] for p in pts),
        "mean_trail_dist_m": sum(p[2] for p in pts) / len(pts),
    }


def _cos(x):
    import math
    return math.cos(x)


def _sin(x):
    import math
    return math.sin(x)


def summarise(lat, lon, data_dir=None, out_m=2000.0):
    """Returns (facts, text). `facts` is for the codegen prompt, `text` for the
    hypothesis prompt."""
    terrain = simmod.Terrain(data_dir or DATA)
    r, c = terrain.rc(lat, lon)
    facts = {
        "elevation": float(terrain.elevation[r, c]),
        "slope": float(terrain.slope[r, c]),
        "trail_dist": float(terrain.trail_dist[r, c]),
        "water_dist": float(terrain.water_dist[r, c]),
    }

    lines = [
        "Start point ({:.5f}, {:.5f}): {:.0f} m elevation, on a {:.0f} degree "
        "slope, {:.0f} m from the nearest trail and {:.0f} m from water."
        .format(lat, lon, facts["elevation"], facts["slope"],
                facts["trail_dist"], facts["water_dist"]),
        "",
        "Over the first {:.1f} km in each direction:".format(out_m / 1000.0),
    ]

    sectors = []
    for name, bearing in COMPASS:
        p = _probe(terrain, lat, lon, bearing, out_m)
        if p is None:
            lines.append("  {:<11} leaves the mapped area".format(name))
            continue
        sectors.append((name, p))
        rise = p["d_elev_m"]
        verb = ("descends {:.0f} m".format(-rise) if rise < -20 else
                "climbs {:.0f} m".format(rise) if rise > 20 else
                "stays level")
        trail = ("trail within {:.0f} m".format(p["min_trail_dist_m"])
                 if p["min_trail_dist_m"] < 100 else
                 "no trail closer than {:.0f} m".format(p["min_trail_dist_m"]))
        lines.append("  {:<11} {}, mean slope {:.0f} deg, {}".format(
            name, verb, p["mean_slope_deg"], trail))

    if sectors:
        lo = min(sectors, key=lambda s: s[1]["d_elev_m"])
        hi = max(sectors, key=lambda s: s[1]["d_elev_m"])
        easiest = min(sectors, key=lambda s: s[1]["mean_slope_deg"])
        trailed = min(sectors, key=lambda s: s[1]["mean_trail_dist_m"])
        lines += [
            "",
            "Steepest descent is {} ({:.0f} m down). Highest ground is {} "
            "({:.0f} m up).".format(lo[0], -lo[1]["d_elev_m"], hi[0],
                                    hi[1]["d_elev_m"]),
            "Gentlest going is {}. Best trail cover is {}.".format(
                easiest[0], trailed[0]),
        ]

    return facts, "\n".join(lines)


if __name__ == "__main__":
    import json
    from settings import MOCKS
    case = json.loads((MOCKS / "case.json").read_text())
    facts, text = summarise(*case["ipp"])
    print(text)
