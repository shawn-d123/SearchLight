"""The baseline: what search teams actually draw today.

Concentric rings at the p25/p50/p75/p95 distance quantiles, uniform probability
DENSITY inside each band, the remaining 5% spread beyond the outer ring. This is
the model Searchlight is arguing against, so it is built honestly and scored on
the same cases with the same metric.

Rebuilding this ourselves is also the sanity check that matters most. If the
harness is correct, a ring built from published quantiles lands near the
published 0.78. If it does not, suspect grid orientation, degrees-to-metres
conversion, or the find location falling outside the window -- in that order.

The grid is radially symmetric about the IPP and the IPP is always at the exact
centre of the scoring window, so the ring grid is IDENTICAL for every case.
Build it once, score it many times.
"""
from __future__ import annotations

import numpy as np

from .score import SCORING_CELL_M, SCORING_RESOLUTION

# Mass in each band. 25/25/25/20/5 -- the last 5% is everything beyond p95.
BAND_MASS = (0.25, 0.25, 0.25, 0.20, 0.05)


def build_ring_grid(quantiles_km, resolution=SCORING_RESOLUTION,
                    cell_m=SCORING_CELL_M, dtype=np.float32):
    """Probability grid for the ISRID distance-ring model.

    Parameters
    ----------
    quantiles_km : dict
        ``{"p25": .., "p50": .., "p75": .., "p95": ..}`` in kilometres.
    resolution, cell_m : int, float
        Grid geometry. Defaults are the scoring grid.

    Returns
    -------
    np.ndarray
        Sums to 1.0. Density is uniform within each band and strictly
        decreasing outward, which is what makes the tie term in Rossmo's R
        carry the score.
    """
    r_km = [quantiles_km["p25"], quantiles_km["p50"],
            quantiles_km["p75"], quantiles_km["p95"]]
    if not all(r_km[i] < r_km[i + 1] for i in range(len(r_km) - 1)):
        raise ValueError("quantiles must increase: {}".format(r_km))

    centre = (resolution - 1) // 2
    idx = (np.arange(resolution) - centre) * cell_m
    dist_m = np.hypot(idx[:, None], idx[None, :])          # metres from IPP

    edges_m = [r * 1000.0 for r in r_km]
    grid = np.zeros((resolution, resolution), dtype=np.float64)

    lo = 0.0
    for i, hi in enumerate(edges_m):
        band = (dist_m >= lo) & (dist_m < hi)
        n = int(band.sum())
        if n == 0:
            raise ValueError(
                "band {} ({:.0f}-{:.0f} m) contains no cells at {} m "
                "resolution".format(i, lo, hi, cell_m))
        grid[band] = BAND_MASS[i] / n
        lo = hi

    outer = dist_m >= edges_m[-1]
    n_outer = int(outer.sum())
    if n_outer == 0:
        # p95 covers the whole window: there is nowhere to put the last 5%.
        # Renormalise the bands rather than silently dropping mass.
        grid /= grid.sum()
    else:
        grid[outer] = BAND_MASS[-1] / n_outer

    total = grid.sum()
    if not np.isclose(total, 1.0, atol=1e-9):
        grid /= total
    return grid.astype(dtype)


def ring_area_km2(radius_km):
    return np.pi * radius_km ** 2
