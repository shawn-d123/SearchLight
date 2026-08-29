"""The benchmark metric. Person C owns this file.

Published scores on 376 real historical cases: the ISRID distance ring that
teams use today scores 0.78 (95% CI 0.74-0.82); the best published combined
model scores 0.805. Random maps score 0, perfect maps score 1.

  Sava, Twardy, Koester & Sonwalkar, "Evaluating Lost Person Behavior Models",
  Transactions in GIS.
  https://sarbayes.org/wp-content/uploads/2015/02/Evaluating-Lost-Person-Behavior-Models-revised-submission.pdf

Entering an existing benchmark with a number is the spine of the project. This
file is what produces that number, so it stays small and readable enough to be
checked by eye on stage.

Grid convention (CONTRACT.md): 5001 x 5001, 5 m cells, IPP at the EXACT centre,
giving a 25.005 x 25.005 km window. Row 0 is north.
"""
from __future__ import annotations

import math

import numpy as np

SCORING_RESOLUTION = 5001
SCORING_CELL_M = 5.0

M_PER_DEG_LAT = 110_574.0


def m_per_deg_lon(lat):
    return 111_320.0 * math.cos(math.radians(lat))


def find_cell(ipp, find, resolution=SCORING_RESOLUTION, cell_m=SCORING_CELL_M):
    """Row/col of the find location on a grid centred on the IPP.

    Returns (row, col, inside). `inside` is False when the find falls outside
    the window, which means the case cannot be scored -- do not clamp it to the
    edge and pretend otherwise, that silently invents a good score.
    """
    centre = (resolution - 1) // 2
    north_m = (find[0] - ipp[0]) * M_PER_DEG_LAT
    east_m = (find[1] - ipp[1]) * m_per_deg_lon(ipp[0])
    row = int(round(centre - north_m / cell_m))   # row increases southward
    col = int(round(centre + east_m / cell_m))
    inside = 0 <= row < resolution and 0 <= col < resolution
    return row, col, inside


def rossmo_r(grid, find_row, find_col):
    """Fraction-of-area score. Worst -1, random 0, best +1.

        p = density at the find cell
        n = cells strictly more probable
        m = cells equally probable  (ties matter: a ring model is mostly ties)
        r = (n + m/2) / N           -> fraction of the map you would search first
        R = (0.5 - r) / 0.5

    The m/2 term is not decoration. A ring model assigns one identical density
    to every cell in a band, so without it a case scores by tie-breaking
    accident rather than by the model.
    """
    g = np.asarray(grid)
    if not (0 <= find_row < g.shape[0] and 0 <= find_col < g.shape[1]):
        raise IndexError("find cell {} is outside the {} grid"
                         .format((find_row, find_col), g.shape))
    p = g[find_row, find_col]
    n = int((g > p).sum())
    m = int((g == p).sum())
    r = (n + m / 2.0) / g.size
    return (0.5 - r) / 0.5


def mean_with_ci(values, confidence=0.95):
    """Mean and a t-based CI. n is small (5-8 cases), so t, not normal.

    The published 0.78 has a 95% CI of 0.74-0.82 across 376 cases. On six cases
    the interval is much wider, and saying so is the honest framing.
    """
    v = np.asarray(values, dtype=float)
    n = v.size
    mean = float(v.mean())
    if n < 2:
        return mean, float("nan"), float("nan"), float("nan")
    sem = float(v.std(ddof=1) / math.sqrt(n))
    try:
        from scipy import stats
        t = float(stats.t.ppf(0.5 + confidence / 2, n - 1))
    except Exception:
        t = 2.571 if n == 6 else 2.0
    # R is bounded on [-1, +1] by construction, so clamp. On six cases the
    # t-interval readily runs past +1, and quoting "CI up to 1.03" on stage
    # invites exactly the question you do not want.
    lo = max(-1.0, mean - t * sem)
    hi = min(1.0, mean + t * sem)
    return mean, lo, hi, sem


def area_pct_at_mass(grid, mass=0.5):
    """Fraction of grid cells holding `mass` of the probability.

    The area-based companion to R, and the same idea as
    model.field.field_area_pct but expressed against the grid rather than
    against a ring, so ring and field can be compared on identical terms.
    """
    g = np.asarray(grid, dtype=np.float64).ravel()
    total = g.sum()
    if total <= 0:
        raise ValueError("grid sums to zero")
    order = np.sort(g)[::-1]
    cum = np.cumsum(order) / total
    return float((np.searchsorted(cum, mass) + 1) / g.size * 100.0)
