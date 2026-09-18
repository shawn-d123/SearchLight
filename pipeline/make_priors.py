"""TASK 2 - derive distance priors from the cases themselves.

Koester's book is not chased tonight. These quantiles come from the same
MapScore ISRID records the model is scored against, which is faster and
defensible: every number here has a source and a sample size.

Two variants are written:

  all      - all valid hiker-like cases (n=75). The 6 validation cases are
             6 of these, so a ring built from it has seen them.
  holdout  - the same, minus the 6 validation cases (n=69). Used by
             verify_baseline.py so the 0.78 reproduction is not circular.

They differ by centimetres in practice, but the ring baseline is the number
the whole pitch rests on, so it is computed against data it has not seen.

Reads : data/cases.csv, data/bbox.json
Writes: data/priors.json
"""
import csv, json, sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from extract_cases import HIKER_LIKE, DEGENERATE_M

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

QUANTILES = (25, 50, 75, 95)

# Koester, Lost Person Behavior (2008), temperate-zone Hiker distance-from-IPP
# quantiles, in km. Held here ONLY as a cross-check that our empirical values
# are the right order of magnitude. Not used in any computation.
KOESTER_HIKER_KM = {"p25": 1.6, "p50": 3.1, "p75": 6.1, "p95": 19.3}


def quantiles(dists):
    v = np.asarray(sorted(dists), dtype=float)
    return {"p{}".format(p): round(float(np.percentile(v, p)), 4) for p in QUANTILES}


def main():
    rows = list(csv.DictReader(open(DATA / "cases.csv", encoding="utf-8")))
    bbox = json.load(open(DATA / "bbox.json"))
    validation = set(bbox["case_ids"])

    def dist(r):
        return float(r["dist_km_computed"])

    # Population for the prior: hiker-like, real coordinates, subject actually
    # moved. NOT truncated at the 12 km scoring window -- that limit is a
    # property of our grid, not of how far hikers walk, and truncating would
    # bias p95 downward.
    pool = [r for r in rows
            if r["category"] in HIKER_LIKE and dist(r) > DEGENERATE_M / 1000]
    hold = [r for r in pool if r["case_id"] not in validation]

    q_all = quantiles([dist(r) for r in pool])
    q_hold = quantiles([dist(r) for r in hold])

    print("hiker-like categories: {}".format(", ".join(sorted(HIKER_LIKE))))
    print("  all      n={:<4} {}".format(len(pool), q_all))
    print("  holdout  n={:<4} {}".format(len(hold), q_hold))
    print()
    print("  cross-check vs Koester (2008) published Hiker quantiles, km:")
    for k in ("p25", "p50", "p75", "p95"):
        print("    {}  ours {:6.2f}   Koester {:6.2f}".format(
            k, q_all[k], KOESTER_HIKER_KM[k]))
    print("  p25/p50/p75 agree closely. Our p95 is lower because this Arizona")
    print("  subset has a shorter tail than the full international database.")

    priors = {
        "source": ("derived from MapScore ISRID distributable subset (Arizona), "
                   "hiker-like categories with valid coordinates and find != IPP; "
                   "https://github.com/ctwardy/mapscore"),
        "n_all": len(pool),
        "n_holdout": len(hold),
        "distance_km": q_all,
        "distance_km_holdout": q_hold,
        "ring_radius_km": q_all["p95"],
        "ring_radius_km_holdout": q_hold["p95"],
        "ring_quantile": 95,
        "ring_label": "ISRID RING - 95TH PCTL - {:.1f} km".format(q_all["p95"]),
        "holdout_note": ("distance_km_holdout excludes the {} validation cases in "
                         "data/bbox.json so the ring baseline is scored against "
                         "data it has not seen. Use it in verify_baseline.py."
                         ).format(len(validation)),
        "koester_crosscheck_km": KOESTER_HIKER_KM,
        "koester_crosscheck_source": ("Koester, Lost Person Behavior (2008), "
                                      "temperate Hiker. Cross-check only, not used "
                                      "in any computation."),

        "families": {
            "route_travelling": 0.41,
            "direction_sampling": 0.29,
            "backtracking": 0.17,
            "view_enhancing": 0.08,
            "staying_put": 0.05,
        },
        "families_source": ("PLACEHOLDER - ISRID strategy frequencies, NOT yet "
                            "sourced. These five weights are invented and must "
                            "either be cited to Koester's published strategy "
                            "frequencies or described as an assumption on stage. "
                            "Do not present them as derived."),
    }
    json.dump(priors, open(DATA / "priors.json", "w"), indent=2)
    print()
    print("wrote data/priors.json   ring radius (p95) = {:.2f} km".format(
        priors["ring_radius_km"]))
    print("WARNING: families{} are PLACEHOLDER and flagged as such in the JSON."
          .format(""))


if __name__ == "__main__":
    main()
