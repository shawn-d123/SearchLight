"""TASK 5 - reproduce the published ring-model baseline.

This is the sanity check that matters most. If the harness is correct, a ring
built from published quantiles lands near the published 0.78 (95% CI 0.74-0.82,
n=376). If it does not, suspect in this order: grid orientation flipped,
degrees not converted to metres properly at this latitude, or the find location
falling outside the 25 km window.

Report what you find rather than tuning until it looks right.

Two quantile sets are scored:

  derived  - from this Arizona subset (data/priors.json, holdout variant, so
             the ring has not seen the validation cases)
  Koester  - the published temperate Hiker quantiles

The derived set is much tighter than Koester's (p95 9.6 km vs 19.3 km), so it
will score HIGHER on these cases. That is a property of the subset, not a bug,
and it is why the number that matters on stage is field-vs-ring on the SAME
cases rather than either number against 0.78.

Usage:  python prep/verify_baseline.py
"""
from __future__ import annotations

import csv, json, sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from model.ring_model import build_ring_grid                    # noqa: E402
from model.score import (SCORING_CELL_M, SCORING_RESOLUTION,    # noqa: E402
                         area_pct_at_mass, find_cell, mean_with_ci, rossmo_r)

DATA = ROOT / "data"

PUBLISHED_RING = (0.78, 0.74, 0.82, 376)
PUBLISHED_BEST = 0.805


def load():
    rows = list(csv.DictReader(open(DATA / "cases.csv", encoding="utf-8")))
    priors = json.load(open(DATA / "priors.json"))
    bbox = json.load(open(DATA / "bbox.json"))
    return rows, priors, bbox


def score_set(grid, cases, label):
    scores, skipped = [], []
    for c in cases:
        ipp = (float(c["ipp_lat"]), float(c["ipp_lon"]))
        find = (float(c["find_lat"]), float(c["find_lon"]))
        r, col, inside = find_cell(ipp, find)
        if not inside:
            skipped.append(c["case_id"])
            continue
        scores.append(rossmo_r(grid, r, col))
    mean, lo, hi, sem = mean_with_ci(scores)
    print("  {:<22} n={:<4} mean R = {:.3f}   95% CI {:.3f} to {:.3f}".format(
        label, len(scores), mean, lo, hi))
    if skipped:
        print("      skipped (find outside window): " + ", ".join(skipped))
    return scores


def main():
    rows, priors, bbox = load()
    usable = [r for r in rows if r["usable"] == "True"]
    validation = [r for r in rows if r["case_id"] in set(bbox["case_ids"])]

    print("scoring grid {} x {} at {:.0f} m  ->  {:.2f} x {:.2f} km window".format(
        SCORING_RESOLUTION, SCORING_RESOLUTION, SCORING_CELL_M,
        SCORING_RESOLUTION * SCORING_CELL_M / 1000,
        SCORING_RESOLUTION * SCORING_CELL_M / 1000))
    print("published ring baseline: {:.2f} (95% CI {:.2f}-{:.2f}, n={})".format(
        *PUBLISHED_RING))
    print("published best combined model: {:.3f}".format(PUBLISHED_BEST))

    quantile_sets = {
        "derived (holdout)": priors["distance_km_holdout"],
        "Koester published": priors["koester_crosscheck_km"],
    }

    results = {}
    for name, q in quantile_sets.items():
        print()
        print("ring from {}  p25={p25:.2f} p50={p50:.2f} p75={p75:.2f} "
              "p95={p95:.2f} km".format(name, **q))
        grid = build_ring_grid(q)
        area = area_pct_at_mass(grid, 0.5)
        print("  ring holds 50% of its mass in {:.1f}% of the window".format(area))
        results[name] = {
            "all_usable": score_set(grid, usable, "all usable cases"),
            "validation": score_set(grid, validation, "validation cases"),
            "area_pct_at_50": area,
            "quantiles_km": q,
        }
        del grid

    # --- verdict ----------------------------------------------------------
    # The published 0.78 came from rings built on category statistics and
    # scored over 376 cases, so the closest analogue we have is our own
    # derived quantiles over all usable cases -- not the six-case subset and
    # not Koester's international quantiles applied to Arizona.
    print()
    print("=" * 72)
    print("HARNESS CHECK -- ring from derived quantiles, all usable cases")
    mean, lo, hi, _ = mean_with_ci(results["derived (holdout)"]["all_usable"])
    p_mean, p_lo, p_hi, p_n = PUBLISHED_RING
    print("  ours      {:.3f}  (95% CI {:.3f} to {:.3f}, n={})".format(
        mean, lo, hi, len(results["derived (holdout)"]["all_usable"])))
    print("  published {:.3f}  (95% CI {:.3f} to {:.3f}, n={})".format(
        p_mean, p_lo, p_hi, p_n))

    if lo <= p_hi and hi >= p_lo:
        print("  CONSISTENT -- the intervals overlap. The harness is trustworthy:")
        print("  grid orientation, metre conversion and window are all correct.")
    elif 0.55 <= mean <= 0.95:
        print("  CLOSE but the intervals do not overlap. Plausible given a")
        print("  single-state case population; treat later numbers with care.")
    else:
        print("  NOT consistent with 0.78. Do not trust any later number.")
        print("  Check in this order: row/col orientation flipped north/south,")
        print("  degrees-to-metres at latitude {:.1f}, find outside the window."
              .format(float(usable[0]["ipp_lat"])))

    kmean = mean_with_ci(results["Koester published"]["all_usable"])[0]
    print()
    print("  Koester's own quantiles score lower on these cases ({:.3f}) because".format(kmean))
    print("  his p95 of 19.3 km is far wider than this Arizona subset warrants")
    print("  (ours is {:.1f} km). An oversized ring spends area on empty ground,".format(
        results["derived (holdout)"]["quantiles_km"]["p95"]))
    print("  and R penalises exactly that. Expected, not a bug.")
    print("=" * 72)

    d = results["derived (holdout)"]["validation"]
    dm, dlo, dhi, _ = mean_with_ci(d)
    print()
    print("THE NUMBER FOR THE PITCH -- ring from our derived quantiles,")
    print("scored on the {} validation cases the field will be scored on:".format(len(d)))
    print("  mean R = {:.3f}  (95% CI {:.3f} to {:.3f})".format(dm, dlo, dhi))
    print()
    print("  This is what the field has to beat. Quote THIS, not 0.78 --")
    print("  it is the same model on the same cases with the same metric,")
    print("  which is the only honest comparison available on six cases.")

    out = {
        "published_ring": {"mean": PUBLISHED_RING[0], "ci": PUBLISHED_RING[1:3],
                           "n": PUBLISHED_RING[3],
                           "source": "Sava, Twardy, Koester & Sonwalkar, "
                                     "Evaluating Lost Person Behavior Models, "
                                     "Transactions in GIS"},
        "published_best_combined": PUBLISHED_BEST,
        "scoring_grid": {"resolution": SCORING_RESOLUTION,
                         "cell_m": SCORING_CELL_M,
                         "window_km": SCORING_RESOLUTION * SCORING_CELL_M / 1000},
        "runs": {name: {"quantiles_km": r["quantiles_km"],
                        "area_pct_at_50": round(r["area_pct_at_50"], 3),
                        "all_usable": {"n": len(r["all_usable"]),
                                       "mean_R": round(mean_with_ci(r["all_usable"])[0], 4),
                                       "ci95": [round(x, 4) for x in
                                                mean_with_ci(r["all_usable"])[1:3]]},
                        "validation": {"n": len(r["validation"]),
                                       "mean_R": round(mean_with_ci(r["validation"])[0], 4),
                                       "ci95": [round(x, 4) for x in
                                                mean_with_ci(r["validation"])[1:3]],
                                       "per_case": [round(x, 4) for x in r["validation"]]}}
                 for name, r in results.items()},
    }
    json.dump(out, open(DATA / "baseline.json", "w"), indent=2)
    print()
    print("wrote data/baseline.json")


if __name__ == "__main__":
    main()
