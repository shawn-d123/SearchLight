"""Aggregation, evidence filtering, and the headline area number.

Person C owns this file.

Only `field_area_pct` is implemented tonight -- it is the number the whole
argument rests on, and it must be computed identically for the ring and for
the field or the comparison is rhetoric rather than measurement.

`build_field` and `apply_evidence` are signatures only. Their internals are
Sunday's job (build order, 10:45 and 13:30). The shapes are frozen tonight so
the orchestrator can be written against them.

Grid conventions, from CONTRACT.md:
  - row-major, grid[0] is the NORTH edge, grid[r][0] the WEST edge
  - display grid 256 x 256, scoring grid 5001 x 5001 at 5 m
  - same function, different resolution argument
"""
from __future__ import annotations

import numpy as np

FAMILIES = ("route_travelling", "direction_sampling", "backtracking",
            "view_enhancing", "staying_put")


def build_field(trajectory_batches, bounds, resolution, accumulator=None):
    """Kernel density over trajectory endpoints, weighted by family prior.

    Incremental by design: pass the previous return value back in as
    `accumulator` and the new batches are added to it, so the field can be
    streamed to the frontend while the fleet is still working (spec section 8).

    Parameters
    ----------
    trajectory_batches : list[dict]
        Worker batches in the CONTRACT.md trajectory shape. Runs whose
        ``status`` is not ``"ok"`` are counted but contribute no density.
    bounds : dict
        ``{north, south, east, west}`` in degrees.
    resolution : int
        Cells per side. 256 for the display grid, 5001 for the scoring grid.
    accumulator : np.ndarray | None
        Previous unnormalised accumulator, or None to start fresh.

    Returns
    -------
    np.ndarray
        float32, shape (resolution, resolution), UNNORMALISED. Callers
        normalise for display; the scorer wants raw density.

    Notes
    -----
    Normalise against a fixed ceiling or a heavily smoothed running maximum
    when displaying. Renormalising to 0..1 on every update makes the field
    pulse and flicker.
    """
    raise NotImplementedError("Sunday 10:45 - Person C")


def apply_evidence(trajectory_batches, evidence):
    """Discard trajectories inconsistent with a witness report.

    A witness report is a spatial AND temporal constraint: the subject was
    near a location at a time. A trajectory survives if it passed within
    ``evidence['radius_m']`` of ``evidence['location']`` within
    ``evidence['tolerance_s']`` of ``evidence['t_s']``.

    Parameters
    ----------
    trajectory_batches : list[dict]
        As above.
    evidence : dict
        ``{"location": [lat, lon], "t_s": int, "radius_m": float,
        "tolerance_s": int}``

    Returns
    -------
    (list[dict], int, int)
        Filtered batches, n_total, n_consistent.

    Notes
    -----
    The demo claim is only that inconsistent simulations are discarded and the
    field renormalised. The filter treats witness reports as reliable, which
    real ones often are not -- stated as a known weakness (spec section 30).
    """
    raise NotImplementedError("Sunday 13:30 - Person C")


def field_area_pct(grid, cell_area_m2, ring_radius_m, mass=0.5):
    """Smallest area holding `mass` of the probability, as a % of ring area.

    This is the headline number in the side rail and the largest text on
    screen. Defined precisely because "cells above a threshold" is arbitrary
    and changes with normalisation:

        sort cells by probability descending, accumulate until the cumulative
        mass reaches `mass`, count the cells, multiply by cell area, divide by
        the ring's area.

    Apply the SAME function to the ring model's own grid to get an honest
    like-for-like comparison. A ring of uniform density needs `mass` of its
    area to hold `mass` of its mass, so it scores ~50% and the field's number
    is meaningful against it.

    Parameters
    ----------
    grid : array_like
        Non-negative density. Need not be normalised; it is normalised here.
    cell_area_m2 : float
        Ground area of one cell.
    ring_radius_m : float
        Radius of the ISRID ring the field is being compared against.
    mass : float
        Probability mass to enclose. 0.5 per CONTRACT.md.

    Returns
    -------
    float
        Percentage. Can exceed 100 if the field is more diffuse than the ring.

    Raises
    ------
    ValueError
        If the grid is empty, negative, or sums to zero -- all of which mean
        an upstream bug, and none of which should be silently papered over
        with a plausible-looking number.
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
    # searchsorted finds the first index where cum >= mass; +1 converts the
    # index to a count of cells.
    n_cells = int(np.searchsorted(cum, mass) + 1)

    area_m2 = n_cells * cell_area_m2
    ring_area_m2 = np.pi * ring_radius_m ** 2
    return 100.0 * area_m2 / ring_area_m2


def normalise_for_display(grid, ceiling=None):
    """Scale to 0..1 for the wire. Pass a stable `ceiling` across updates.

    Renormalising to the running max on every update makes the field pulse.
    Hold the ceiling fixed, or smooth it heavily, once the field has formed.
    """
    g = np.asarray(grid, dtype=np.float32)
    top = float(g.max()) if ceiling is None else float(ceiling)
    if top <= 0:
        return np.zeros_like(g, dtype=np.float32)
    return np.clip(g / top, 0.0, 1.0).astype(np.float32)
