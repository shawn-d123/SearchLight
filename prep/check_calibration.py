"""Does the simulation reproduce the published distance quantiles?

The pitch claims "the same published statistics, applied through terrain
instead of a circle". This is the check that the claim is true rather than
rhetorical: run a full local fleet and compare the simulated endpoint-distance
distribution against data/priors.json.

It also contrasts the terrain-aware field against a plain random walk, which
is the visual argument expressed as a number.

    python prep/check_calibration.py
    python prep/check_calibration.py --n 400 --runs 60

Run it after any change to the movement templates. If the distribution drifts
away from the priors, the claim weakens and you want to know before a judge
asks, not after.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("SEARCHLIGHT_DATA", str(ROOT / "data"))

from model.field import (build_field, cell_area_m2, default_bounds,   # noqa: E402
                         default_ring_radius_m, field_area_pct, find_zones,
                         load_terrain)
from orchestrator.hypotheses import calibrate, load_priors, plan  # noqa: E402
from worker.runner import run_hypothesis                          # noqa: E402
from worker.terrain import Terrain                                # noqa: E402

IPP = [32.4102, -110.7314]   # CONTRACT.md s8, Marshall Gulch


def distances_km(batches, terrain, ipp):
    ends = np.asarray([r["endpoint"] for b in batches for r in b["runs"]
                       if r["endpoint"]])
    if not len(ends):
        return np.array([])
    return np.hypot((ends[:, 0] - ipp[0]) * terrain.m_lat,
                    (ends[:, 1] - ipp[1]) * terrain.m_lon) / 1000.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=200, help="hypotheses")
    ap.add_argument("--runs", type=int, default=60, help="seeds per hypothesis")
    ap.add_argument("--ipp", type=float, nargs=2, default=IPP)
    ap.add_argument("--no-calibrate", action="store_true")
    args = ap.parse_args()

    terrain = Terrain(str(ROOT / "data"))
    priors = load_priors()
    bounds, ring = default_bounds(), default_ring_radius_m()
    ipp = list(args.ipp)

    base = None
    if not args.no_calibrate:
        print("calibrating base duration against the published p50...")
        t0 = time.time()
        base, report = calibrate(ipp, terrain, priors,
                                 rng=np.random.default_rng(3))
        for r in report:
            print("   base {:>6} s -> median {:.2f} km   (target {:.2f})".format(
                r["base_s"], r["median_km"], priors["distance_km"]["p50"]))
        print("   converged base = {:.0f} s ({:.1f} h) in {:.0f}s".format(
            base, base / 3600, time.time() - t0))

    print()
    print("running {} hypotheses x {} seeds...".format(args.n, args.runs))
    t0 = time.time()
    hs = plan(ipp, n=args.n, n_runs=args.runs, priors=priors,
              rng=np.random.default_rng(7), base_s=base, terrain=terrain)
    batches = [run_hypothesis(h, terrain)[0] for h in hs]
    grid, acc = build_field(batches, bounds, 256)
    dt = time.time() - t0
    print("   {} runs in {:.1f}s ({:.0f}/s) | ok {} failed {} off-grid {}".format(
        acc["n_total"], dt, acc["n_total"] / max(dt, 1e-9),
        acc["n_ok"], acc["n_failed"], acc["off_grid"]))

    d = distances_km(batches, terrain, ipp)
    q = priors["distance_km"]
    sim = {p: float(np.percentile(d, p)) for p in (25, 50, 75, 95)}

    print()
    print("ENDPOINT DISTANCE vs PUBLISHED PRIORS (km)")
    print("   {:<14}{:>8}{:>8}{:>8}{:>8}".format("", "p25", "p50", "p75", "p95"))
    print("   {:<14}{:>8.2f}{:>8.2f}{:>8.2f}{:>8.2f}".format(
        "simulated", sim[25], sim[50], sim[75], sim[95]))
    print("   {:<14}{:>8.2f}{:>8.2f}{:>8.2f}{:>8.2f}".format(
        "ISRID prior", q["p25"], q["p50"], q["p75"], q["p95"]))
    print("   {:<14}{:>7.0f}%{:>7.0f}%{:>7.0f}%{:>7.0f}%".format(
        "error", *[100 * (sim[p] - q["p{}".format(p)]) / q["p{}".format(p)]
                   for p in (25, 50, 75, 95)]))

    worst = max(abs(100 * (sim[p] - q["p{}".format(p)]) / q["p{}".format(p)])
                for p in (25, 50, 75, 95))
    print()
    if worst < 35:
        print("   CONSISTENT -- worst quantile off by {:.0f}%. The simulation "
              "reproduces".format(worst))
        print("   the published distribution, so 'the same statistics' is a "
              "statement of fact.")
    else:
        print("   DRIFTED -- worst quantile off by {:.0f}%. Re-run calibrate(), "
              "or say".format(worst))
        print("   plainly that the movement model is not distance-calibrated.")

    fa = field_area_pct(grid, cell_area_m2(bounds, 256), ring)
    print()
    print("FIELD vs RING")
    print("   terrain-aware field holds 50% of its mass in {:.1f}% of the "
          "ring area".format(fa))
    print("   ring radius {:.2f} km (derived p95)".format(ring / 1000))
    for z in find_zones(grid, bounds, k=3, terrain=load_terrain()):
        print("   zone {:<24}{:>5.1f}%  {}".format(z["name"], z["pct"],
                                                   z["centroid"]))

    json.dump({"base_duration_s": base, "n_hypotheses": args.n,
               "n_runs": acc["n_total"], "simulated_km": sim,
               "prior_km": q, "worst_quantile_error_pct": round(worst, 1),
               "field_area_pct": round(fa, 2)},
              open(ROOT / "data" / "calibration.json", "w"), indent=2)
    print()
    print("wrote data/calibration.json")


if __name__ == "__main__":
    main()
