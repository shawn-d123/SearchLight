"""Deterministic movement templates, one per ISRID strategy family.

**Build this day one. The demo must be able to run with zero successful
generations.** When a model-written script fails -- syntax error, infinite
loop, walking off the grid, returning nothing -- the runner falls back to the
template for that family and marks the batch `generated: false`. That feeds
the failure count on screen, which is credibility rather than weakness.

NUMPY ONLY. All 60 seeds are simulated simultaneously as arrays rather than
looped, so a batch costs ~200 vectorised steps instead of 12,000 scalar ones.

The five families come from Koester's published lost-person strategies. Their
prior weights live in data/priors.json and are applied by the orchestrator --
this module decides how each family MOVES, not how likely it is.
"""
from __future__ import annotations

import numpy as np

from .terrain import IMPASSABLE_SLOPE_DEG

FAMILIES = ("route_travelling", "direction_sampling", "backtracking",
            "view_enhancing", "staying_put")

POINTS_OUT = 60      # CONTRACT.md caps points at <=60 per run
SIM_STEPS = 180      # simulated finer than emitted, then downsampled
N_CANDIDATES = 12    # candidate bearings evaluated per step

# Per-family movement parameters. These are HAND-TUNED, not fitted -- stated
# as a known weakness rather than dressed up. Each is a plain claim about
# behaviour that a search planner would recognise.
PARAMS = {
    # Follows paths. Strong trail affinity, committed heading, travels far.
    "route_travelling": dict(
        w_trail=2.6, w_slope=1.1, w_down=0.5, w_water=0.1,
        persist=0.90, speed=1.00, spread_deg=22),
    # Picks a direction and holds it, terrain permitting. Ignores trails.
    "direction_sampling": dict(
        w_trail=0.25, w_slope=1.4, w_down=0.7, w_water=0.2,
        persist=0.86, speed=0.85, spread_deg=30),
    # Heads out, realises, turns back toward the IPP. Reversal at ~55%.
    "backtracking": dict(
        w_trail=1.5, w_slope=1.2, w_down=0.5, w_water=0.15,
        persist=0.80, speed=0.75, spread_deg=34),
    # Climbs for a view or a phone signal. Uphill bias, slow, short range.
    "view_enhancing": dict(
        w_trail=0.8, w_slope=0.7, w_down=-1.3, w_water=0.05,
        persist=0.72, speed=0.55, spread_deg=42),
    # Shelters in place. Drifts only far enough to find cover or water.
    "staying_put": dict(
        w_trail=0.5, w_slope=1.6, w_down=0.3, w_water=0.9,
        persist=0.55, speed=0.10, spread_deg=70),
}

# Fatigue: by the end of a long walk, downhill preference roughly doubles and
# speed drops. This is what bends late trajectories into the drainages.
FATIGUE_DOWN_GAIN = 1.4
FATIGUE_SPEED_LOSS = 0.45


def simulate(terrain, family, start, duration_s, n_runs, seed,
             params=None, points_out=POINTS_OUT, steps=SIM_STEPS):
    """Simulate `n_runs` walkers of one family from one start point.

    Returns
    -------
    (points, ok)
        points : float array (n_runs, points_out, 3) of [lat, lon, t_seconds]
        ok     : bool array (n_runs,) -- False where the walker left the grid

    All runs advance together; index 0 of every run is the start point, so the
    trajectories genuinely begin at the IPP rather than near it.
    """
    if family not in PARAMS:
        raise ValueError("unknown family {!r}; expected one of {}".format(
            family, ", ".join(FAMILIES)))
    p = dict(PARAMS[family])
    if params:
        p.update(params)

    rng = np.random.default_rng(seed)
    R = int(n_runs)
    lat = np.full(R, float(start[0]))
    lon = np.full(R, float(start[1]))
    start_lat, start_lon = lat.copy(), lon.copy()

    heading = rng.uniform(0, 2 * np.pi, R)
    alive = np.ones(R, dtype=bool)

    dt = float(duration_s) / steps
    keep = np.linspace(0, steps, points_out).astype(int)
    out = np.zeros((R, points_out, 3), dtype=np.float64)
    out[:, 0, 0], out[:, 0, 1], out[:, 0, 2] = lat, lon, 0.0
    written = 1

    spread = np.radians(p["spread_deg"])
    offsets = np.linspace(-spread, spread, N_CANDIDATES)

    for step in range(1, steps + 1):
        frac = step / steps
        fatigue = frac ** 1.5

        if family == "backtracking" and frac > 0.55:
            # Turn around and head back toward where they started.
            dy = (start_lat - lat) * terrain.m_lat
            dx = (start_lon - lon) * terrain.m_lon
            home = np.arctan2(dx, dy)
            heading = heading + 0.30 * _angdiff(home, heading)

        # --- propose candidate bearings and score them ---------------------
        cand = heading[:, None] + offsets[None, :]
        cand = cand + rng.normal(0, 0.10, cand.shape)

        w_down = p["w_down"] * (1.0 + FATIGUE_DOWN_GAIN * fatigue)
        speed_scale = p["speed"] * (1.0 - FATIGUE_SPEED_LOSS * fatigue)

        # Probe at the distance actually about to be travelled. Probing one
        # cell ahead while moving 110 m per step means the walker chooses on
        # terrain it never enters -- which made route_travelling, the family
        # with the STRONGEST trail affinity, finish furthest from any trail.
        nominal_v = 1.25 * speed_scale                  # m/s on gentle ground
        probe_m = float(max(terrain.cell_m, nominal_v * dt))
        clat, clon = terrain.offset(lat[:, None], lon[:, None], cand, probe_m)
        in_box = terrain.inside(clat, clon)
        clat_s, clon_s = terrain.clamp(clat, clon)

        here_e = terrain.elev(lat, lon)[:, None]
        here_trail = terrain.to_trail(lat, lon)[:, None]
        here_water = terrain.to_water(lat, lon)[:, None]
        cand_e = terrain.elev(clat_s, clon_s)
        cand_slope = terrain.slope_deg(clat_s, clon_s)
        cand_trail = terrain.to_trail(clat_s, clon_s)
        cand_water = terrain.to_water(clat_s, clon_s)

        # EVERY steering term is a gradient -- metres gained per metre walked --
        # so the weights are directly comparable. Mixing an absolute distance
        # (trail_dist / 600) with a gradient scaled by 10 let the descent term
        # outweigh trail affinity about sevenfold, which quietly turned
        # route_travelling into a downhill family wearing a trail label.
        descent = (here_e - cand_e) / probe_m            # + is downhill
        trail_g = (here_trail - cand_trail) / probe_m    # + is toward a trail
        water_g = (here_water - cand_water) / probe_m    # + is toward water

        # Slope stays an ABSOLUTE penalty, not a gradient: it is about whether
        # the ground can be walked at all, which does not depend on approach.
        slope_pen = cand_slope / IMPASSABLE_SLOPE_DEG
        slope_pen = np.where(cand_slope >= IMPASSABLE_SLOPE_DEG,
                             slope_pen + 6.0, slope_pen)

        STEER = 3.0
        cost = (p["w_slope"] * slope_pen
                - STEER * (w_down * descent
                           + p["w_trail"] * trail_g
                           + p["w_water"] * water_g))
        cost = np.where(in_box, cost, cost + 50.0)      # leaving is expensive

        # Softmax choice. Not argmin: identical walkers would then follow
        # identical paths and 60 seeds would render as one line.
        z = -(cost - cost.min(axis=1, keepdims=True))
        w = np.exp(np.clip(z, -50, 50))
        cw = np.cumsum(w, axis=1)
        pick = (rng.random(R) * cw[:, -1])
        idx = (cw < pick[:, None]).sum(axis=1).clip(0, N_CANDIDATES - 1)
        rows = np.arange(R)
        chosen = cand[rows, idx]

        heading = p["persist"] * heading + (1 - p["persist"]) * chosen
        heading = heading + _angdiff(chosen, heading) * (1 - p["persist"])

        # --- advance at Tobler speed --------------------------------------
        d_elev = cand_e[rows, idx] - here_e[:, 0]
        v = terrain.tobler_speed_ms(d_elev, probe_m) * speed_scale
        dist = np.maximum(v * dt, 0.0)

        nlat, nlon = terrain.offset(lat, lon, heading, dist)
        left = ~terrain.inside(nlat, nlon)
        alive &= ~left
        nlat, nlon = terrain.clamp(nlat, nlon)
        lat = np.where(alive, nlat, lat)
        lon = np.where(alive, nlon, lon)

        if written < points_out and step >= keep[written]:
            out[:, written, 0] = lat
            out[:, written, 1] = lon
            out[:, written, 2] = step * dt
            written += 1

    # Fill any unwritten tail with the final position rather than zeros --
    # a zero would render as a path to null island.
    for j in range(written, points_out):
        out[:, j, 0], out[:, j, 1], out[:, j, 2] = lat, lon, duration_s

    return out, alive


def _angdiff(a, b):
    """Signed smallest angle from b to a, in radians."""
    return (a - b + np.pi) % (2 * np.pi) - np.pi


def to_batch(points, ok, hypothesis_id, family, weight, duration_s,
             generated=False):
    """Pack into the CONTRACT.md section 6 trajectory batch shape."""
    runs = []
    for i in range(points.shape[0]):
        if not bool(ok[i]):
            # Walked off the grid. Counted, not plotted.
            runs.append({"run_index": i, "points": [], "endpoint": None,
                         "duration_s": 0, "status": "failed"})
            continue
        pts = [[round(float(la), 6), round(float(lo), 6), int(round(t))]
               for la, lo, t in points[i]]
        runs.append({
            "run_index": i,
            "points": pts,
            "endpoint": [pts[-1][0], pts[-1][1]],
            "duration_s": int(duration_s),
            "status": "ok",
        })
    return {
        "hypothesis_id": hypothesis_id,
        "family": family,
        "weight": round(float(weight), 4),
        "generated": bool(generated),
        "runs": runs,
    }
