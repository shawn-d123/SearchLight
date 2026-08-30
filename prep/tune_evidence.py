"""Pick the witness-report parameters against REAL trajectories, not the mocks.

    python prep/tune_evidence.py                 # one live run, then sweep
    python prep/tune_evidence.py --batches x.json  # sweep a saved run

Why this exists
---------------
`radius_m` in the witness report was tuned so that ~1/3 of the MOCK runs
survived, and the mocks came from a crude corridor-biased random walk. Against
real terrain-aware simulations the same radius is far more selective: the field
collapsed from 6.5% of the ring to 0.5%, which is numerically spectacular and
visually almost nothing — a few pixels where there should be a small, bright,
obviously-searchable area.

So this runs the pipeline once, keeps the batches, and sweeps the three knobs
offline. One paid fleet run instead of one per guess.

What the knobs mean, so the choice can be defended rather than fitted
--------------------------------------------------------------------
radius_m     how precisely the witness placed the subject. A wider radius is a
             vaguer sighting, which is the normal case for a member of the
             public pointing at a hillside.
tolerance_s  how precisely they placed it in TIME.
reliability  1.0 discards inconsistent runs outright. Below 1.0 they are kept
             at reduced weight, so the field dims where the witness might be
             wrong instead of going black. This is the honest knob for "witness
             reports are often wrong", which is on the project's own list of
             stated weaknesses.

None of these is a measurement. They are the stated uncertainty of a fictional
witness report, and the demo should say so.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "orchestrator"))

from model.field import apply_evidence  # noqa: E402

# The sighting's location and time are FIXED — they are the demo's narrative
# ("red jacket, eastern drainage, at 90 minutes"). Only the uncertainty around
# them is being chosen here.
LAT, LON, T_S = 32.364754, -110.736908, 5400


def load_batches(path=None):
    if path:
        return json.loads(pathlib.Path(path).read_text())

    from pipeline import Pipeline  # noqa: E402
    from settings import MAX_SANDBOXES, load_case  # noqa: E402

    events = []
    pipe = Pipeline(emit=lambda t, p: events.append(t), n_sandboxes=MAX_SANDBOXES)
    print("acquiring fleet...")
    pipe.acquire_fleet()
    try:
        case = load_case()
        print("running...")
        result = pipe.run(case, total_runs=12000, n_hypotheses=20)
        batches = result["batches"]
    finally:
        print("releasing fleet...")
        pipe.release_fleet()

    out = ROOT / "prep" / "_batches.json"
    out.write_text(json.dumps(batches))
    print("saved {} batches -> {}".format(len(batches), out))
    return batches


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--batches")
    args = ap.parse_args()

    batches = load_batches(args.batches)
    total = sum(len(b.get("runs", [])) for b in batches)

    from settings import load_case
    case = load_case()
    bounds = case["bounds"]
    ring = case.get("ring_radius_m")

    print("\n{} runs across {} batches\n".format(total, len(batches)))

    print("{:>9} {:>7} {:>6}  {:>9}  {:>7}".format(
        "radius_m", "tol_s", "rel", "consistent", "area_%"))
    rows = []
    for radius in (3250, 4000, 5000):
        for tol in (1800,):
            for rel in (1.0, 0.97, 0.94, 0.9, 0.85):
                ev = {"lat": LAT, "lon": LON, "t": T_S,
                      "radius_m": radius, "tolerance_s": tol,
                      "reliability": rel}
                filtered, field = apply_evidence(
                    batches, ev, bounds=bounds, resolution=256,
                    ring_radius_m=ring)
                n_ok = field.get("n_consistent")
                area = field.get("field_area_pct")
                rows.append((radius, tol, rel, n_ok, area))
                print("{:>9} {:>7} {:>6}  {:>9}  {:>7}".format(
                    radius, tol, rel, n_ok, round(area, 2)))

    print("\nAim: an area a judge can SEE shrink, not one that vanishes.")
    print("Roughly 2-3% of the ring reads as a small bright searchable area;")
    print("below ~1% it is a dot and the collapse stops being legible.")


if __name__ == "__main__":
    main()
