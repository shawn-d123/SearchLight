"""Aggregation, evidence filtering, and the headline area number.

Person C owns this file. The orchestrator calls it directly -- see CONTRACT.md
section 10 for the frozen boundary:

    build_field(trajectory_batches, bounds, resolution, accumulator=None)
        -> (grid, accumulator)
    apply_evidence(trajectory_batches, evidence)
        -> (filtered, field_dict)
    field_area_pct(grid, cell_area_m2, ring_radius_m)
        -> float

Grid conventions (CONTRACT.md section 3):
  - row-major, grid[0] is the NORTH edge, grid[r][0] the WEST edge
  - display grid 256 x 256, scoring grid 5001 x 5001 at 5 m
  - same function, different resolution argument

THE BANDWIDTH IS IN METRES, NOT CELLS. This matters more than it looks. The
same function produces both grids, so a sigma expressed in cells would smooth
the 256 grid and the 5001 grid by physically different amounts, and
field_area_pct -- the number in the pitch -- would silently depend on which
resolution you happened to call. Kept in metres, the two agree.
"""
from __future__ import annotations

import base64
import json
import math
from pathlib import Path

import numpy as np
from scipy.ndimage import gaussian_filter, maximum_filter

FAMILIES = ("route_travelling", "direction_sampling", "backtracking",
            "view_enhancing", "staying_put")

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

M_PER_DEG_LAT = 110_574.0

# Kernel bandwidth. Each endpoint is one sample from a hypothesis, and the
# honest uncertainty around it is a few hundred metres -- finer than that
# pretends to a precision the model does not have, coarser and the field stops
# following the drainages, which is the whole visual argument.
DEFAULT_SIGMA_M = 350.0

# Displayed field is normalised against a running ceiling that only ever rises,
# and rises smoothly. Renormalising to the instantaneous max on every update
# makes the field pulse and flicker as the max shifts. See CONTRACT.md.
CEILING_DECAY = 0.85


def m_per_deg_lon(lat):
    return 111_320.0 * math.cos(math.radians(lat))


def _load_json(name):
    p = DATA / name
    return json.load(open(p)) if p.exists() else None


def default_bounds():
    b = _load_json("bbox.json")
    return {k: b[k] for k in ("north", "south", "east", "west")} if b else None


def default_ring_radius_m():
    p = _load_json("priors.json")
    return p["ring_radius_km"] * 1000.0 if p else None


def cell_area_m2(bounds, resolution):
    """Ground area of one cell, in square metres."""
    mid = (bounds["north"] + bounds["south"]) / 2
    h = (bounds["north"] - bounds["south"]) / resolution * M_PER_DEG_LAT
    w = (bounds["east"] - bounds["west"]) / resolution * m_per_deg_lon(mid)
    return w * h


def rowcol(bounds, resolution, lat, lon):
    """Fractional row/col. Row 0 is the NORTH edge."""
    r = (bounds["north"] - lat) / (bounds["north"] - bounds["south"]) * resolution
    c = (lon - bounds["west"]) / (bounds["east"] - bounds["west"]) * resolution
    return r, c


def cell_latlon(bounds, resolution, row, col):
    lat = bounds["north"] - (row + 0.5) / resolution * (bounds["north"] - bounds["south"])
    lon = bounds["west"] + (col + 0.5) / resolution * (bounds["east"] - bounds["west"])
    return lat, lon


# ---------------------------------------------------------------------------
# aggregation
# ---------------------------------------------------------------------------

def new_accumulator(bounds, resolution):
    """Running state for incremental aggregation.

    `raw` holds unsmoothed weighted endpoint counts. Smoothing happens when a
    grid is emitted, not on the way in -- smoothing incrementally would blur
    already-blurred data and the field would creep outward on every update.
    """
    return {
        "raw": np.zeros((resolution, resolution), dtype=np.float64),
        "bounds": dict(bounds),
        "resolution": int(resolution),
        "n_total": 0,        # every run seen, ok or failed
        "n_ok": 0,           # runs that produced an endpoint
        "n_failed": 0,
        "n_batches": 0,
        "off_grid": 0,       # endpoints outside the bounds, counted not clamped
        "ceiling": 0.0,      # smoothed running max, for stable display scaling
        "families": {f: 0 for f in FAMILIES},
    }


def build_field(trajectory_batches, bounds, resolution, accumulator=None):
    """Kernel density over run endpoints, weighted by family prior.

    Incremental by design: pass the previous accumulator back in and the new
    batches are added to it, so the field can be streamed to the frontend while
    the fleet is still working.

    Parameters
    ----------
    trajectory_batches : list[dict]
        Worker batches in the CONTRACT.md section 6 shape. Runs whose `status`
        is not "ok" are counted but contribute no density.
    bounds : dict
        {north, south, east, west} in degrees.
    resolution : int
        Cells per side. 256 display, 5001 scoring.
    accumulator : dict | None
        Previous return value, or None to start fresh.

    Returns
    -------
    (np.ndarray, dict)
        The smoothed density grid (float32, UNNORMALISED -- callers normalise
        for display, the scorer wants raw), and the updated accumulator.
    """
    if accumulator is None:
        accumulator = new_accumulator(bounds, resolution)
    elif accumulator["resolution"] != resolution:
        raise ValueError(
            "accumulator is {}x{} but resolution={} was requested; build the "
            "display and scoring grids with separate accumulators".format(
                accumulator["resolution"], accumulator["resolution"], resolution))

    raw = accumulator["raw"]
    n = resolution

    for batch in trajectory_batches or []:
        accumulator["n_batches"] += 1
        family = batch.get("family")
        # Weight comes from the family prior, never from the model. A batch
        # without one contributes uniformly rather than vanishing.
        w = float(batch.get("weight") or 0.0) or 1.0
        if family in accumulator["families"]:
            accumulator["families"][family] += 1

        for run in batch.get("runs", []):
            accumulator["n_total"] += 1
            if run.get("status") != "ok":
                accumulator["n_failed"] += 1
                continue
            end = run.get("endpoint")
            if not end:
                accumulator["n_failed"] += 1
                continue
            r, c = rowcol(bounds, n, end[0], end[1])
            ri, ci = int(r), int(c)
            if 0 <= ri < n and 0 <= ci < n:
                raw[ri, ci] += w
                accumulator["n_ok"] += 1
            else:
                # Off-grid endpoints are counted, not clamped to the edge.
                # Clamping would pile spurious mass on the border and the field
                # would grow a bright frame that means nothing.
                accumulator["off_grid"] += 1

    grid = smooth(raw, bounds, resolution)

    # Ceiling only rises, and rises smoothly, so the display does not pulse.
    peak = float(grid.max())
    accumulator["ceiling"] = max(
        accumulator["ceiling"],
        CEILING_DECAY * accumulator["ceiling"] + (1 - CEILING_DECAY) * peak,
        peak * 0.999,
    )
    return grid.astype(np.float32), accumulator


def smooth(raw, bounds, resolution, sigma_m=DEFAULT_SIGMA_M):
    """Gaussian splat, bandwidth specified in METRES.

    Converted to cells here and only here. See the module docstring for why
    that distinction is load-bearing.
    """
    mid = (bounds["north"] + bounds["south"]) / 2
    h_m = (bounds["north"] - bounds["south"]) * M_PER_DEG_LAT / resolution
    w_m = (bounds["east"] - bounds["west"]) * m_per_deg_lon(mid) / resolution
    # Cells are not square in degrees, so sigma differs per axis. (row, col).
    sigma_cells = (sigma_m / h_m, sigma_m / w_m)
    if max(sigma_cells) < 0.5:
        # Bandwidth finer than the grid: smoothing would be a no-op and the
        # field would be salt-and-pepper. Say so rather than emit noise.
        raise ValueError(
            "sigma {:.0f} m is below one cell at resolution {} ({:.0f} m/cell). "
            "Raise sigma_m or lower the resolution.".format(
                sigma_m, resolution, max(h_m, w_m)))
    return gaussian_filter(raw, sigma=sigma_cells, mode="constant")


def normalise_for_display(grid, ceiling=None):
    """Scale to 0..1 for the wire. Pass the accumulator's stable ceiling."""
    g = np.asarray(grid, dtype=np.float32)
    top = float(g.max()) if ceiling is None else float(ceiling)
    if top <= 0:
        return np.zeros_like(g, dtype=np.float32)
    return np.clip(g / top, 0.0, 1.0).astype(np.float32)


# ---------------------------------------------------------------------------
# zones
# ---------------------------------------------------------------------------

def find_zones(grid, bounds, k=2, min_separation_cells=None, terrain=None):
    """Top-k local maxima with the probability mass around each.

    `pct` is the share of total mass inside the suppression window around the
    peak, which is what "31.2% in Ridge north" means on screen.
    """
    g = np.asarray(grid, dtype=np.float64)
    n = g.shape[0]
    sep = min_separation_cells or max(4, n // 10)
    total = g.sum()
    if total <= 0:
        return []

    # Prefer true local maxima, but do NOT stop when they run out. A field
    # concentrated into a single blob has exactly one local maximum, so the
    # earlier version returned ONE zone -- and the contract and the side rail
    # both expect two. Fall back to the brightest remaining cell outside the
    # suppressed window so k zones always come back while mass remains.
    peaks = (g == maximum_filter(g, size=max(3, sep // 2))) & (g > 0)
    avail = g.copy()
    peak_only = np.where(peaks, g, 0.0)
    # Mass is claimed from `remaining`, not from `g`. Suppression windows
    # overlap when two peaks sit closer than 2*sep -- measured 100% + 44.6% for
    # two zones 26 cells apart at sep=25 -- and the rail would then show
    # percentages summing past 100.
    remaining = g.copy()

    zones = []
    for _ in range(k):
        src = peak_only if peak_only.max() > 0 else avail
        if src.max() <= 0:
            break                      # genuinely no mass left
        r, c = np.unravel_index(int(np.argmax(src)), g.shape)
        r0, r1 = max(0, r - sep), min(n, r + sep + 1)
        c0, c1 = max(0, c - sep), min(n, c + sep + 1)
        pct = float(remaining[r0:r1, c0:c1].sum() / total * 100.0)
        remaining[r0:r1, c0:c1] = 0.0
        lat, lon = cell_latlon(bounds, n, r, c)
        zones.append({
            "name": _zone_name(bounds, n, r, c, terrain),
            "pct": round(pct, 1),
            "centroid": [round(lat, 6), round(lon, 6)],
        })
        peak_only[r0:r1, c0:c1] = 0.0
        avail[r0:r1, c0:c1] = 0.0
    return zones


def _zone_name(bounds, resolution, row, col, terrain=None):
    """Compass position, plus a landform word when terrain is available.

    Without terrain this is purely geometric -- not wrong, just not a landmark
    name. With the elevation array loaded it can say Ridge or Drainage, which
    is what a search planner would actually call it.
    """
    lat, lon = cell_latlon(bounds, resolution, row, col)
    mid_lat = (bounds["north"] + bounds["south"]) / 2
    mid_lon = (bounds["east"] + bounds["west"]) / 2
    ns = "North" if lat >= mid_lat else "South"
    ew = "east" if lon >= mid_lon else "west"

    landform = ""
    if terrain is not None:
        try:
            tr = int(row / resolution * terrain.shape[0])
            tc = int(col / resolution * terrain.shape[1])
            win = terrain[max(0, tr - 25):tr + 26, max(0, tc - 25):tc + 26]
            if win.size:
                rel = float(terrain[tr, tc]) - float(win.mean())
                landform = ("Ridge " if rel > 40 else
                            "Drainage " if rel < -40 else "Slope ")
        except (IndexError, ValueError):
            landform = ""
    return "{}{} {}".format(landform, ns, ew)


def load_terrain():
    """Elevation array for zone naming. Optional -- returns None if absent."""
    p = DATA / "elevation.npy"
    try:
        return np.load(p) if p.exists() else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# evidence
# ---------------------------------------------------------------------------

def run_is_consistent(run, ev_lat, ev_lon, t, radius_m, tolerance_s):
    """Did this run pass within radius_m of the sighting, near time t?

    Checks the interpolated track between stored points, not just the stored
    points themselves. Points are downsampled to <=60 per run, so at a 4-hour
    duration they sit ~4 minutes apart -- a run can cross the sighting circle
    entirely between two samples. Testing only the samples would discard runs
    that genuinely passed through it.
    """
    pts = run.get("points") or []
    if len(pts) < 2:
        return False
    mlat = M_PER_DEG_LAT
    mlon = m_per_deg_lon(ev_lat)
    r2 = radius_m * radius_m

    for (la1, lo1, t1), (la2, lo2, t2) in zip(pts, pts[1:]):
        # Skip segments entirely outside the time window.
        if max(t1, t2) < t - tolerance_s or min(t1, t2) > t + tolerance_s:
            continue
        x1, y1 = (lo1 - ev_lon) * mlon, (la1 - ev_lat) * mlat
        x2, y2 = (lo2 - ev_lon) * mlon, (la2 - ev_lat) * mlat
        dx, dy = x2 - x1, y2 - y1
        seg2 = dx * dx + dy * dy
        if seg2 <= 0:
            if x1 * x1 + y1 * y1 <= r2:
                return True
            continue
        # Closest approach of the segment to the sighting.
        u = max(0.0, min(1.0, -(x1 * dx + y1 * dy) / seg2))
        px, py = x1 + u * dx, y1 + u * dy
        if px * px + py * py <= r2:
            return True
    return False


def apply_evidence(trajectory_batches, evidence, bounds=None, resolution=256,
                   ring_radius_m=None, accumulator=None):
    """Discard trajectories inconsistent with a witness report.

    A witness report is a spatial AND temporal constraint: the subject was near
    a location at a time. A run survives if it passed within `radius_m` of
    `[lat, lon]` inside a window around `t`.

    Parameters
    ----------
    trajectory_batches : list[dict]
    evidence : dict
        {lat, lon, t, radius_m, reliability}. `tolerance_s` optional, default
        900 s. `reliability` in 0..1, default 1.0.
    bounds, resolution, ring_radius_m, accumulator : optional
        Not in the frozen signature -- they default from data/bbox.json and
        data/priors.json so the orchestrator can call the two-argument form.

    Returns
    -------
    (list[dict], dict)
        Filtered batches, and a ready-to-send field payload (CONTRACT.md s7).

    Notes
    -----
    `reliability` softens the filter rather than switching it off. At 1.0 an
    inconsistent run is discarded outright. Below 1.0 it is retained with
    weight scaled by (1 - reliability), so the field dims where the witness
    might be wrong instead of going absolutely black. Real witness reports
    often are not reliable, and this is the honest knob for that -- stated as
    a known weakness rather than hidden.
    """
    if bounds is None:
        bounds = default_bounds()
        if bounds is None:
            raise ValueError("no bounds given and data/bbox.json not found")
    if ring_radius_m is None:
        ring_radius_m = default_ring_radius_m()

    ev_lat = evidence.get("lat", (evidence.get("location") or [None, None])[0])
    ev_lon = evidence.get("lon", (evidence.get("location") or [None, None])[1])
    if ev_lat is None or ev_lon is None:
        raise ValueError("evidence needs lat and lon")
    t = int(evidence.get("t", evidence.get("t_s", 0)))
    radius_m = float(evidence.get("radius_m", 500.0))
    tolerance_s = int(evidence.get("tolerance_s", 900))
    reliability = float(evidence.get("reliability", 1.0))
    if not 0.0 <= reliability <= 1.0:
        raise ValueError("reliability must be in 0..1")
    residual = 1.0 - reliability

    filtered = []
    n_total = n_consistent = 0
    for batch in trajectory_batches or []:
        keep, dim = [], []
        for run in batch.get("runs", []):
            n_total += 1
            if run.get("status") != "ok":
                continue
            if run_is_consistent(run, ev_lat, ev_lon, t, radius_m, tolerance_s):
                n_consistent += 1
                keep.append(run)
            elif residual > 0:
                dim.append(run)
        w = float(batch.get("weight") or 0.0) or 1.0
        if keep:
            filtered.append(dict(batch, runs=keep, weight=w))
        if dim:
            # Same hypothesis, reduced weight. Marked so nothing downstream
            # mistakes a dimmed batch for a consistent one.
            filtered.append(dict(batch, runs=dim, weight=w * residual,
                                 evidence_consistent=False))

    grid, acc = build_field(filtered, bounds, resolution)
    payload = field_payload(grid, acc, bounds, resolution, ring_radius_m,
                            progress=1.0, n_total=n_total,
                            n_consistent=n_consistent)
    payload["evidence"] = {
        "lat": ev_lat, "lon": ev_lon, "t": t,
        "radius_m": radius_m, "tolerance_s": tolerance_s,
        "reliability": reliability,
    }
    return filtered, payload


# ---------------------------------------------------------------------------
# the headline number
# ---------------------------------------------------------------------------

def field_area_pct(grid, cell_area_m2, ring_radius_m, mass=0.5):
    """Smallest area holding `mass` of the probability, as a % of ring area.

    This is the largest text in the side rail and the whole argument in one
    number. Defined precisely because "cells above a threshold" is arbitrary
    and shifts with normalisation:

        sort cells by probability descending, accumulate until the cumulative
        mass reaches `mass`, count the cells, multiply by cell area, divide by
        the ring's area.

    Apply the SAME function to the ring model's own grid for an honest
    like-for-like comparison. A ring of uniform density needs `mass` of its
    area to hold `mass` of its mass, so it scores ~50% and the field's number
    is meaningful against it.

    Raises
    ------
    ValueError
        On an empty, negative, non-finite or zero-sum grid. All of these mean
        an upstream bug, and none should be papered over with a plausible
        looking number.
    """
    g = np.asarray(grid, dtype=np.float64).ravel()
    if g.size == 0:
        raise ValueError("empty grid")
    if not np.all(np.isfinite(g)):
        raise ValueError("grid contains NaN or inf")
    if (g < 0).any():
        raise ValueError("grid has negative density")
    total = g.sum()
    if total <= 0:
        raise ValueError("grid sums to zero - no probability mass to enclose")
    if not 0 < mass <= 1:
        raise ValueError("mass must be in (0, 1]")
    if ring_radius_m <= 0 or cell_area_m2 <= 0:
        raise ValueError("ring radius and cell area must be positive")

    order = np.sort(g)[::-1]
    cum = np.cumsum(order) / total
    n_cells = int(np.searchsorted(cum, mass) + 1)
    area_m2 = n_cells * cell_area_m2
    return 100.0 * area_m2 / (math.pi * ring_radius_m ** 2)


# ---------------------------------------------------------------------------
# wire format
# ---------------------------------------------------------------------------

def encode_grid(grid):
    """base64 float32, row-major, row 0 north. CONTRACT.md section 7."""
    return base64.b64encode(
        np.ascontiguousarray(grid, dtype=np.float32).tobytes()).decode("ascii")


def field_payload(grid, accumulator, bounds, resolution, ring_radius_m,
                  progress=1.0, n_total=None, n_consistent=None, terrain=None):
    """Build the section 7 `field_update` object the frontend consumes."""
    disp = normalise_for_display(grid, accumulator.get("ceiling"))
    total = accumulator["n_total"] if n_total is None else n_total
    cons = (accumulator["n_ok"] if n_consistent is None else n_consistent)
    return {
        "bounds": {k: bounds[k] for k in ("north", "south", "east", "west")},
        "resolution": int(resolution),
        "grid": encode_grid(disp),
        "progress": round(float(progress), 3),
        "zones": find_zones(grid, bounds, k=2, terrain=terrain),
        "n_total": int(total),
        "n_consistent": int(cons),
        "ring_radius_m": round(float(ring_radius_m), 1),
        "field_area_pct": round(
            field_area_pct(grid, cell_area_m2(bounds, resolution),
                           ring_radius_m), 1),
    }
