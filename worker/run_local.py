"""Run the worker on this laptop, no sandbox, no API keys.

The point of this file: every failure it catches is a failure you are not
debugging over a network at 12:30. Run it after any change to sim.py or
templates.py.

    python worker/run_local.py                 # all five family templates
    python worker/run_local.py --family staying_put --runs 5
    python worker/run_local.py --script my.py  # a saved generated script
"""
from __future__ import annotations

import argparse, json, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "worker"))

import sim  # noqa: E402
from templates import TEMPLATES, template_for  # noqa: E402


def make_job(family, script, start, n_runs, duration_s, weight):
    return {
        "hypothesis": {
            "hypothesis_id": "h_local_{}".format(family),
            "family": family,
            "weight": weight,
            "description": "local check",
            "start": start,
            "duration_s": duration_s,
            "n_runs": n_runs,
            "seed_base": 1000,
        },
        "script": script,
        "generated": False,
    }


def report(batch):
    runs = batch["runs"]
    ok = [r for r in runs if r["status"] == "ok"]
    failed = [r for r in runs if r["status"] != "ok"]
    n_pts = [len(r["points"]) for r in ok]
    line = "  {:<20} {:>2}/{:<2} ok".format(
        batch["family"], len(ok), len(runs))
    if ok:
        # straight-line displacement of the endpoint from the start
        line += "  pts {}-{}".format(min(n_pts), max(n_pts))
    print(line + "  {:.2f}s".format(batch.get("elapsed_s", 0.0)))
    if failed:
        seen = set()
        for r in failed:
            e = r.get("error", "?")
            if e not in seen:
                seen.add(e)
                print("      FAIL: {}".format(e))
    if batch.get("error"):
        print("      BATCH ERROR: {}".format(batch["error"]))
    return len(ok), len(runs)


def displacement_km(start, endpoint):
    dy = (endpoint[0] - start[0]) * 110.574
    dx = (endpoint[1] - start[1]) * 94.004237
    return (dy * dy + dx * dx) ** 0.5


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--family", help="one family instead of all five")
    ap.add_argument("--script", help="path to a script to run instead of a template")
    ap.add_argument("--runs", type=int, default=8)
    ap.add_argument("--duration-s", type=int, default=4320)
    ap.add_argument("--data-dir", default=str(ROOT / "data"))
    ap.add_argument("--dump", help="write the batch JSON here")
    args = ap.parse_args()

    case = json.loads((ROOT / "mocks" / "case.json").read_text())
    start = case["ipp"]
    print("IPP {}  duration {}s  {} runs/family".format(
        start, args.duration_s, args.runs))
    print()

    if args.script:
        families = [args.family or "route_travelling"]
        scripts = {families[0]: Path(args.script).read_text()}
    elif args.family:
        families = [args.family]
        scripts = {args.family: template_for(args.family)}
    else:
        families = list(TEMPLATES)
        scripts = dict(TEMPLATES)

    total_ok = total = 0
    t0 = time.monotonic()
    last = None
    for fam in families:
        job = make_job(fam, scripts[fam], start, args.runs, args.duration_s, 0.2)
        batch = sim.run_batch(job, args.data_dir, budget_s=30.0)
        batch["elapsed_s"] = batch.get("elapsed_s", 0.0)
        ok, n = report(batch)
        total_ok += ok
        total += n
        last = batch
        good = [r for r in batch["runs"] if r["status"] == "ok"]
        if good:
            d = sorted(displacement_km(start, r["endpoint"]) for r in good)
            print("      displacement km: min {:.2f}  median {:.2f}  max {:.2f}"
                  .format(d[0], d[len(d) // 2], d[-1]))

    print()
    print("{}/{} runs ok in {:.2f}s".format(total_ok, total, time.monotonic() - t0))

    if args.dump and last:
        Path(args.dump).write_text(json.dumps(last, indent=2))
        print("wrote {}".format(args.dump))

    # A template failing is a build-stopper: the fallback path is the one thing
    # that must never be broken.
    return 0 if total_ok == total else 1


if __name__ == "__main__":
    sys.exit(main())
