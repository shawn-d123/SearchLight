"""TASK 8 - measure the fleet before the day, not on it.

Person B owns this. It answers the two questions that decide worker count and
how long the simulation beat lasts on stage:

    1. how long do 50 sandboxes take COLD, in parallel?
    2. how long do 50 take from a WARM pool?

An independent benchmark measured Daytona creating a sandbox in ~742 ms and
resuming in ~1254 ms, where "ready" means a command actually executed. That is
SEQUENTIAL. The number that matters is 50-200 in parallel, which depends on
your account concurrency limit. That is what this measures.

    python prep/daytona_probe.py --n 5      # smoke test first, cheap
    python prep/daytona_probe.py --n 50     # the real measurement
    python prep/daytona_probe.py --snapshot-only

Costs, at 1 vCPU / 2 GiB ~= $0.083 per sandbox-hour: 50 sandboxes alive three
minutes is about $0.21. You have $200 free on signup plus $100 event credit.
You will not run out. Test freely.

!! UNVERIFIED AGAINST A LIVE API !!
Written against the daytona Python SDK's introspected surface (debian_slim,
pip_install, CreateSnapshotParams, CreateSandboxFromSnapshotParams), but never
executed -- there was no API key on the machine the night before. Expect to fix
one or two call signatures on first run. The prep doc's `Image.debianSlim(...)
.pipInstall(...)` is the TYPESCRIPT spelling; Python is snake_case, as below.

Writes: prep/TIMINGS.md
"""
from __future__ import annotations

import argparse, json, os, statistics, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

SNAPSHOT = "searchlight-worker"
READY_CMD = (
    "python -c \"import numpy, os; "
    "a = numpy.load('/data/trail_dist.npy', mmap_mode='r'); "
    "print('READY', a.shape, len(os.listdir('/data')))\""
)


def load_key():
    key = os.environ.get("DAYTONA_API_KEY", "").strip()
    if not key and (ROOT / ".env").exists():
        for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
            if line.startswith("DAYTONA_API_KEY="):
                key = line.split("=", 1)[1].strip()
    if not key:
        sys.exit("No DAYTONA_API_KEY in environment or .env.\n"
                 "Get one at https://www.daytona.io -> dashboard -> API keys,\n"
                 "and note the concurrent sandbox limit shown there.")
    return key


def build_snapshot(daytona, force=False):
    from daytona import CreateSnapshotParams, Image, Resources

    arrays = sorted(DATA.glob("*.npy")) + [DATA / "meta.json"]
    missing = [p.name for p in arrays if not p.exists()]
    if missing:
        print("WARNING: missing from data/: {}".format(", ".join(missing)))
        print("  run  python prep/fetch_terrain.py all  first")
    present = [p for p in arrays if p.exists()]
    total_mb = sum(p.stat().st_size for p in present) / 1e6
    print("baking {} file(s), {:.1f} MB, into the snapshot".format(
        len(present), total_mb))
    if total_mb > 50:
        print("  NOTE: over the ~50 MB budget; this multiplies across 200 "
              "sandboxes. Downsample in fetch_terrain.py if pulls are slow.")

    # NEVER pip install at sandbox start. Bake it in. Workers get numpy only --
    # no geopandas, no OSMnx, no rasterio; they are heavy and they multiply.
    image = Image.debian_slim("3.12").pip_install("numpy")
    for p in present:
        image = image.add_local_file(str(p), "/data/{}".format(p.name))

    existing = []
    try:
        existing = [s.name for s in daytona.snapshot.list()]
    except Exception as e:
        print("  could not list snapshots: {}".format(e))
    if SNAPSHOT in existing and not force:
        print("  snapshot '{}' already exists, reusing "
              "(--rebuild to replace)".format(SNAPSHOT))
        return

    t0 = time.time()
    daytona.snapshot.create(
        CreateSnapshotParams(name=SNAPSHOT, image=image,
                             resources=Resources(cpu=1, memory=2)),
        on_logs=lambda m: print("    " + str(m).rstrip()),
    )
    print("  snapshot built in {:.1f}s".format(time.time() - t0))


def time_cold(daytona, n):
    """Create n sandboxes in parallel; clock each to its first successful exec."""
    from daytona import CreateSandboxFromSnapshotParams

    results, errors, sandboxes = [], [], []

    def one(i):
        t0 = time.perf_counter()
        sb = daytona.create(CreateSandboxFromSnapshotParams(
            snapshot=SNAPSHOT, ephemeral=True,
            labels={"searchlight": "probe"}))
        sandboxes.append(sb)
        r = sb.process.exec(READY_CMD, timeout=120)
        dt = time.perf_counter() - t0
        out = getattr(r, "result", "") or ""
        if "READY" not in str(out):
            raise RuntimeError("exec did not report READY: {}".format(
                str(out)[:200]))
        return dt

    print("creating {} sandboxes COLD, in parallel...".format(n))
    wall = time.perf_counter()
    with ThreadPoolExecutor(max_workers=n) as pool:
        futs = {pool.submit(one, i): i for i in range(n)}
        for f in as_completed(futs):
            try:
                results.append(f.result())
            except Exception as e:
                errors.append(str(e))
    wall = time.perf_counter() - wall
    return results, errors, wall, sandboxes


def time_warm(daytona, sandboxes):
    """Stop the pool, then time start -> first exec. This is the warm-pool
    path: a pre-created sandbox claimed rather than provisioned."""
    if not sandboxes:
        return [], [], 0.0
    print("stopping {} sandboxes to build the warm pool...".format(len(sandboxes)))
    with ThreadPoolExecutor(max_workers=len(sandboxes)) as pool:
        list(pool.map(lambda sb: _safe(daytona.stop, sb), sandboxes))

    results, errors = [], []

    def one(sb):
        t0 = time.perf_counter()
        daytona.start(sb)
        r = sb.process.exec(READY_CMD, timeout=120)
        dt = time.perf_counter() - t0
        if "READY" not in str(getattr(r, "result", "")):
            raise RuntimeError("warm exec did not report READY")
        return dt

    print("claiming {} from the WARM pool, in parallel...".format(len(sandboxes)))
    wall = time.perf_counter()
    with ThreadPoolExecutor(max_workers=len(sandboxes)) as pool:
        for f in as_completed([pool.submit(one, sb) for sb in sandboxes]):
            try:
                results.append(f.result())
            except Exception as e:
                errors.append(str(e))
    return results, errors, time.perf_counter() - wall


def _safe(fn, *a):
    try:
        return fn(*a)
    except Exception:
        return None


def summarise(name, times, errors, wall):
    if not times:
        print("  {}: ALL {} FAILED".format(name, len(errors)))
        return {"n_ok": 0, "n_failed": len(errors),
                "errors": errors[:5], "wall_s": round(wall, 2)}
    s = sorted(times)
    d = {"n_ok": len(times), "n_failed": len(errors),
         "wall_s": round(wall, 2),
         "median_s": round(statistics.median(s), 3),
         "p95_s": round(s[int(len(s) * 0.95) - 1], 3),
         "min_s": round(s[0], 3), "max_s": round(s[-1], 3),
         "errors": errors[:5]}
    print("  {}: {} ok, {} failed | median {:.2f}s  p95 {:.2f}s  max {:.2f}s | "
          "wall {:.1f}s".format(name, d["n_ok"], d["n_failed"], d["median_s"],
                                d["p95_s"], d["max_s"], wall))
    return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=5,
                    help="sandboxes to launch (start at 5, then 50)")
    ap.add_argument("--rebuild", action="store_true", help="rebuild the snapshot")
    ap.add_argument("--snapshot-only", action="store_true")
    ap.add_argument("--keep", action="store_true", help="do not delete afterwards")
    args = ap.parse_args()

    from daytona import Daytona, DaytonaConfig

    daytona = Daytona(DaytonaConfig(api_key=load_key()))
    build_snapshot(daytona, force=args.rebuild)
    if args.snapshot_only:
        return

    cold, cold_err, cold_wall, sandboxes = time_cold(daytona, args.n)
    print()
    c = summarise("COLD", cold, cold_err, cold_wall)
    warm, warm_err, warm_wall = time_warm(daytona, sandboxes)
    w = summarise("WARM", warm, warm_err, warm_wall)

    limit = [e for e in cold_err + warm_err
             if any(k in e.lower() for k in ("limit", "quota", "concurren"))]
    if limit:
        print()
        print("CONCURRENCY LIMIT LIKELY HIT -- {} of {} failed with:".format(
            len(limit), args.n))
        print("  " + limit[0][:300])
        print("  Cap the fleet below this and say the real number on stage.")

    if not args.keep:
        print("cleaning up {} sandboxes...".format(len(sandboxes)))
        with ThreadPoolExecutor(max_workers=max(1, len(sandboxes))) as pool:
            list(pool.map(lambda sb: _safe(daytona.delete, sb), sandboxes))

    out = {"n_requested": args.n, "snapshot": SNAPSHOT,
           "cold": c, "warm": w,
           "concurrency_limit_hit": bool(limit),
           "measured_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    (ROOT / "prep" / "TIMINGS.json").write_text(json.dumps(out, indent=2))

    md = ["# Daytona fleet timings", "",
          "Measured {} with `prep/daytona_probe.py --n {}`.".format(
              out["measured_at"], args.n), "",
          "| | n ok | n failed | median | p95 | max | wall |",
          "|---|---|---|---|---|---|---|"]
    for label, d in (("cold", c), ("warm pool", w)):
        if d.get("n_ok"):
            md.append("| {} | {} | {} | {:.2f}s | {:.2f}s | {:.2f}s | {:.1f}s |"
                      .format(label, d["n_ok"], d["n_failed"], d["median_s"],
                              d["p95_s"], d["max_s"], d["wall_s"]))
        else:
            md.append("| {} | 0 | {} | - | - | - | - |".format(
                label, d.get("n_failed", 0)))
    md += ["",
           "**Concurrency limit hit:** {}".format("YES" if limit else "no"), "",
           "These two numbers decide the worker count and how long the",
           "simulation beat lasts on stage. Wall time is what the audience",
           "sees; median is what a single sandbox costs you.", ""]
    (ROOT / "prep" / "TIMINGS.md").write_text("\n".join(md), encoding="utf-8")
    print()
    print("wrote prep/TIMINGS.md and prep/TIMINGS.json")


if __name__ == "__main__":
    main()
