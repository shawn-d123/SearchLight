"""TASK 8 -- measure the fleet. RUN AND SUPERSEDED; results in prep/TIMINGS.md.

This was written before there was an API key and never executed. It has since
been run, and the answers it was built to find are already recorded:

    * the fleet ceiling is 10 SANDBOXES, not 200 -- the account tier caps
      total CPU at 10 and total memory at 10 GiB across all live sandboxes
    * there is NO WARM POOL on this tier: /api/warm-pools returns 404, so the
      cold/warm comparison this script was written to make cannot be made
    * cold-starting the whole 10-sandbox fleet takes ~2.2 s, which is why the
      demo acquires at startup and holds rather than pooling

**Read `prep/TIMINGS.md`. It is the deliverable; this is just the tool.**

The original implementation had three faults that are fixed by delegating to
`orchestrator/fleet.py` instead of duplicating it:

  1. `Image.add_local_file` with a Windows absolute path produces a broken
     Dockerfile -- see TIMINGS.md trap 3.
  2. `daytona.snapshot.list()` returns PaginatedSnapshots, not a list, so the
     "already exists" check always threw and fell through to a create.
  3. The warm measurement stopped and started `ephemeral=True` sandboxes, which
     is not what a warm pool is, and warm pools do not exist here anyway.

    python prep/daytona_probe.py --n 10
"""
from __future__ import annotations

import argparse, json, statistics, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "orchestrator"))

from fleet import Fleet          # noqa: E402
from settings import MAX_SANDBOXES, SNAPSHOT  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=MAX_SANDBOXES)
    ap.add_argument("--runs", type=int, default=60)
    ap.add_argument("--rebuild", action="store_true")
    ap.add_argument("--snapshot-only", action="store_true")
    args = ap.parse_args()

    fleet = Fleet()
    built = fleet.ensure_snapshot(rebuild=args.rebuild)
    print("snapshot '{}' {}".format(SNAPSHOT, "built" if built else "ready"))
    if args.snapshot_only:
        return 0

    if args.n > MAX_SANDBOXES:
        print("NOTE: asking for {} but the tier ceiling is {}; expect the "
              "excess to fail.".format(args.n, MAX_SANDBOXES))

    print("\ncreating {} sandboxes in parallel...".format(args.n))
    sbs, errors = fleet.acquire(args.n)
    print("  {} ready, {} failed, wall {:.2f}s".format(
        len(sbs), len(errors), fleet.wall_acquire_s))
    for e in errors[:3]:
        print("  ERROR " + e[:200])
    if not sbs:
        return 1

    # Time one dispatch per sandbox: upload a job, run it, parse the batch.
    from fleet import _demo_hypotheses
    hyps = _demo_hypotheses(len(sbs), args.runs, None)
    print("\ndispatching one batch of {} runs to each...".format(args.runs))

    times = []
    t0 = time.perf_counter()

    def timed(sb, hyp):
        t = time.perf_counter()
        b = fleet.run_hypothesis(sb, hyp)
        times.append(time.perf_counter() - t)
        return b

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=len(sbs)) as pool:
        batches = list(pool.map(timed, sbs, hyps))
    wall = time.perf_counter() - t0

    n_ok = sum(1 for b in batches for r in b["runs"] if r["status"] == "ok")
    n_all = sum(len(b["runs"]) for b in batches)
    s = sorted(times)
    print("  {}/{} runs ok  |  median batch {:.2f}s  max {:.2f}s  |  wall {:.2f}s"
          .format(n_ok, n_all, statistics.median(s), s[-1], wall))
    print("  {:.0f} sims/s across {} sandboxes".format(n_ok / max(wall, 1e-6),
                                                       len(sbs)))

    fleet.release(sbs)
    print("released {} sandboxes".format(len(sbs)))

    out = {"measured_at": time.strftime("%Y-%m-%d %H:%M:%S"),
           "n_requested": args.n, "n_ready": len(sbs),
           "tier_ceiling": MAX_SANDBOXES,
           "warm_pool_available": False,
           "acquire_wall_s": round(fleet.wall_acquire_s, 3),
           "dispatch_wall_s": round(wall, 3),
           "runs_ok": n_ok, "runs_total": n_all,
           "sims_per_s": round(n_ok / max(wall, 1e-6), 1)}
    (ROOT / "prep" / "TIMINGS.json").write_text(json.dumps(out, indent=2))
    print("\nwrote prep/TIMINGS.json  (the narrative lives in prep/TIMINGS.md)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
