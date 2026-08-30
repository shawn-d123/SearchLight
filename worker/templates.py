"""Hand-written fallback movement scripts, one per family.

These are the reason the demo survives a bad API response. They are SOURCE
STRINGS, not functions, because they must travel the identical path through
`sim.compile_script` that model-written code does: same namespace, same five
API functions, same budget. Swapping a generated script for a template is a
one-line change with no other consequence.

A batch produced from one of these is marked `generated: false`, which feeds the
honest failure count on screen (CONTRACT.md section 6).

The namespace each script sees:

    elevation_at(lat, lon)      -> metres
    slope_at(lat, lon)          -> degrees
    dist_to_trail(lat, lon)     -> metres
    dist_to_water(lat, lon)     -> metres
    step(lat, lon, bearing, m)  -> (lat, lon)      bearing 0 = N, 90 = E
    math, DT_S                  and `rng`, a seeded numpy Generator, as an arg

Every script defines exactly:

    def simulate(start_lat, start_lon, duration_s, rng) -> [(lat, lon, t), ...]
"""
from __future__ import annotations

# Shared preamble, textually inlined into each template rather than imported: a
# template must stand alone, because the model's version of the same script has
# to as well.
#
# Two things here are load-bearing and were both wrong on the first pass.
#
# 1. `slope.npy` is the slope of the GROUND. A trail crossing a 29 deg hillside
#    is graded and does not climb at 29 deg, so on a trail the terrain slope
#    says almost nothing about pace. Feeding it to Tobler put the demo IPP at
#    0.15 m/s -- 0.7 km of travel in 72 minutes against a 2.9 km ISRID median.
#
# 2. Tobler takes the grade ALONG THE DIRECTION OF TRAVEL, not the terrain
#    gradient. Using the gradient penalises contouring a hillside and
#    descending a drainage exactly as hard as climbing straight up it, which
#    erases the one behaviour the pitch turns on: people go downhill when
#    they are tired. `_pace` probes 50 m ahead on the actual bearing.
_PRELUDE = """
    def _pace(la, lo, b):
        pla, plo = step(la, lo, b, 50.0)
        if dist_to_trail(la, lo) < 40.0 and dist_to_trail(pla, plo) < 40.0:
            return 1.15
        g = (elevation_at(pla, plo) - elevation_at(la, lo)) / 50.0
        v = 6.0 * math.exp(-3.5 * abs(g + 0.05)) / 3.6
        return max(0.20, min(1.40, v * 0.75))

    def _turn(a, b):
        return ((a - b + 180.0) % 360.0) - 180.0
"""


ROUTE_TRAVELLING = """
def simulate(start_lat, start_lon, duration_s, rng):
    # Stays on the path network: samples headings within a realistic turn and
    # takes the one that keeps closest to a trail on ground it can move over.
""" + _PRELUDE + """
    lat, lon = start_lat, start_lon
    pts = [(lat, lon, 0)]
    bearing = float(rng.uniform(0.0, 360.0))
    t = 0
    while t < duration_s:
        best = None
        # +/- 45 deg only. Someone travelling a route does not reverse down it
        # every minute, and an unrestricted min-cost pick does exactly that --
        # it diffuses along the trail instead of going anywhere.
        for _ in range(9):
            b = bearing + float(rng.normal(0.0, 22.0))
            if abs(_turn(b, bearing)) > 45.0:
                continue
            pace = _pace(lat, lon, b)
            nlat, nlon = step(lat, lon, b, pace * DT_S)
            cost = (dist_to_trail(nlat, nlon) * 0.03
                    + max(0.0, slope_at(nlat, nlon) - 25.0) * 0.5
                    - pace * 20.0)
            if best is None or cost < best[0]:
                best = (cost, b, nlat, nlon)
        if best is None:
            pace = _pace(lat, lon, bearing)
            nlat, nlon = step(lat, lon, bearing, pace * DT_S)
            best = (0.0, bearing, nlat, nlon)
        bearing = bearing + 0.7 * _turn(best[1], bearing)
        lat, lon = best[2], best[3]
        t += DT_S
        pts.append((lat, lon, t))
    return pts
"""


DIRECTION_SAMPLING = """
def simulate(start_lat, start_lon, duration_s, rng):
    # Commits to one heading and holds it, deflecting off ground too steep to
    # cross. The classic "picked a direction and kept going".
""" + _PRELUDE + """
    lat, lon = start_lat, start_lon
    pts = [(lat, lon, 0)]
    bearing = float(rng.uniform(0.0, 360.0))
    t = 0
    while t < duration_s:
        b = bearing + float(rng.normal(0.0, 12.0))
        # Steep ground deflects rather than stops: try either side and take the
        # gentler, which is how people actually contour a slope.
        if slope_at(*step(lat, lon, b, 50.0)) > 30.0:
            alts = []
            for off in (-55.0, -25.0, 25.0, 55.0):
                alat, alon = step(lat, lon, b + off, 50.0)
                alts.append((slope_at(alat, alon), b + off))
            alts.sort()
            b = alts[0][1]
        pace = _pace(lat, lon, b)
        lat, lon = step(lat, lon, b, pace * DT_S)
        bearing = bearing + 0.15 * _turn(b, bearing)
        t += DT_S
        pts.append((lat, lon, t))
    return pts
"""


BACKTRACKING = """
def simulate(start_lat, start_lon, duration_s, rng):
    # Travels out, realises the mistake, and turns for the last known point --
    # navigating from memory, so it rarely retraces its own line.
""" + _PRELUDE + """
    lat, lon = start_lat, start_lon
    pts = [(lat, lon, 0)]
    bearing = float(rng.uniform(0.0, 360.0))
    turn_t = duration_s * float(rng.uniform(0.35, 0.6))
    # A fixed per-run navigation error, and the return bearing is fixed ONCE at
    # the turn. Recomputing it toward the IPP every step is a pursuit curve: a
    # constant angular error still spirals in and lands on the IPP, which is the
    # one outcome that needs no search. Somebody heading back from memory holds
    # a remembered bearing, and misses by however wrong it was.
    bias = float(rng.normal(0.0, 28.0))
    home_b = None
    t = 0
    while t < duration_s:
        if t < turn_t:
            b = bearing + float(rng.normal(0.0, 20.0))
        else:
            if home_b is None:
                dy = start_lat - lat
                dx = (start_lon - lon) * 0.85
                home_b = math.degrees(math.atan2(dx, dy)) + bias
            b = home_b + float(rng.normal(0.0, 15.0))
        if slope_at(*step(lat, lon, b, 50.0)) > 35.0:
            b = b + float(rng.choice([-45.0, 45.0]))
        pace = _pace(lat, lon, b)
        lat, lon = step(lat, lon, b, pace * DT_S)
        bearing = b
        t += DT_S
        pts.append((lat, lon, t))
    return pts
"""


VIEW_ENHANCING = """
def simulate(start_lat, start_lon, duration_s, rng):
    # Climbs for a view or a phone signal, then holds position on the high
    # ground. Slow by construction: going up is what Tobler punishes.
""" + _PRELUDE + """
    lat, lon = start_lat, start_lon
    pts = [(lat, lon, 0)]
    t = 0
    stalled = 0
    while t < duration_s:
        here = elevation_at(lat, lon)
        best = None
        for k in range(12):
            b = k * 30.0 + float(rng.normal(0.0, 10.0))
            pace = _pace(lat, lon, b)
            nlat, nlon = step(lat, lon, b, pace * DT_S)
            gain = elevation_at(nlat, nlon) - here
            # Gain is wanted, but not up a cliff. The noise term matters: a
            # pure argmax hill-climb is deterministic, so every seed draws the
            # same line and the whole family contributes one point of mass.
            score = (gain - max(0.0, slope_at(nlat, nlon) - 30.0) * 3.0
                     + float(rng.normal(0.0, 12.0)))
            if best is None or score > best[0]:
                best = (score, nlat, nlon, gain)
        if best[3] < 1.0:
            stalled += 1
        else:
            stalled = 0
        if stalled >= 3:
            # on a local summit: mill about rather than walk off it
            lat, lon = step(lat, lon, float(rng.uniform(0.0, 360.0)),
                            float(rng.uniform(0.0, 25.0)))
        else:
            lat, lon = best[1], best[2]
        t += DT_S
        pts.append((lat, lon, t))
    return pts
"""


STAYING_PUT = """
def simulate(start_lat, start_lon, duration_s, rng):
    # Stops and waits, drifting only as far as shade, water or a sitting spot.
""" + _PRELUDE + """
    lat, lon = start_lat, start_lon
    pts = [(lat, lon, 0)]
    anchor_lat, anchor_lon = lat, lon
    leash = float(rng.uniform(60.0, 220.0))
    t = 0
    while t < duration_s:
        b = float(rng.uniform(0.0, 360.0))
        nlat, nlon = step(lat, lon, b, float(rng.uniform(0.0, 30.0)))
        # metres from the anchor, using the same lat/lon scaling as the raster
        dy = (nlat - anchor_lat) * 110574.0
        dx = (nlon - anchor_lon) * 94004.237
        if math.sqrt(dy * dy + dx * dx) < leash:
            lat, lon = nlat, nlon
        t += DT_S
        pts.append((lat, lon, t))
    return pts
"""


TEMPLATES = {
    "route_travelling": ROUTE_TRAVELLING,
    "direction_sampling": DIRECTION_SAMPLING,
    "backtracking": BACKTRACKING,
    "view_enhancing": VIEW_ENHANCING,
    "staying_put": STAYING_PUT,
}

FAMILIES = tuple(TEMPLATES)


def template_for(family):
    """Never raises. An unknown family falls back to the commonest behaviour
    rather than killing the batch."""
    return TEMPLATES.get(family, ROUTE_TRAVELLING)
