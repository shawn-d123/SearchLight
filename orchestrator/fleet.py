"""Daytona fleet control. Claims sandboxes, dispatches one hypothesis each,
collects trajectory batches.

The architecture only earns its sandboxes because a MODEL WRITES THE MOVEMENT
CODE for each hypothesis -- so this executes generated code hundreds of times in
parallel and isolation is the actual requirement, not decoration. A fixed random
walk with different seeds would run twelve thousand times in one process in
under a second. Protect that above any feature.

One model call per SANDBOX, not per simulation. 200 sandboxes each get one
generated script, then each runs it many times with different seeds.

    python orchestrator/fleet.py --smoke          # 1 sandbox, template script
    python orchestrator/fleet.py --n 10           # 10 workers end to end
"""
from __future__ import annotations

import argparse, json, os, sys, threading, time
from concurrent.futures import ThreadPoolExecutor, as_completed

from settings import (SNAPSHOT, SNAPSHOT_CPU, SNAPSHOT_MEM_GIB, MAX_SANDBOXES,
                      SB_DIR, SB_SIM, SB_JOB, SB_OUT, SB_DATA,
                      WORKER_TIMEOUT_S, WORKER_BUDGET_S, WORKER, DATA, key,
                      load_case)

sys.path.insert(0, str(WORKER))
from templates import template_for  # noqa: E402

SENTINEL = "---SEARCHLIGHT-BATCH---"

RUN_CMD = ("python {sim} --job {job} --out {out} --data-dir {data} "
           "--budget-s {budget}").format(
    sim=SB_SIM, job=SB_JOB, out=SB_OUT, data=SB_DATA, budget=WORKER_BUDGET_S)


def failed_batch(hyp, reason, generated):
    """Every failure path produces a well-formed batch. The frontend counts
    failures; it must never receive a shape it cannot read."""
    n = int(hyp.get("n_runs", 60))
    return {"hypothesis_id": hyp.get("hypothesis_id", "unknown"),
            "family": hyp.get("family", "unknown"),
            "weight": hyp.get("weight", 0.0),
            "generated": generated,
            "runs": [{"run_index": i, "status": "failed", "error": reason[:160]}
                     for i in range(n)],
            "error": reason[:400]}


def parse_output(text):
    """Generated code may print. Take only what follows the sentinel."""
    i = text.rfind(SENTINEL)
    if i < 0:
        raise ValueError("no batch sentinel in worker output: "
                         + text.strip()[-300:])
    return json.loads(text[i + len(SENTINEL):].strip())


class Fleet:
    def __init__(self, api_key=None, snapshot=SNAPSHOT, on_event=None):
        from daytona import Daytona, DaytonaConfig
        self.daytona = Daytona(DaytonaConfig(
            api_key=api_key or key("DAYTONA_API_KEY")))
        self.snapshot = snapshot
        self.sim_src = (WORKER / "sim.py").read_bytes()
        self.sandboxes = []
        self._lock = threading.Lock()
        self.on_event = on_event or (lambda *a, **k: None)

    # -- lifecycle ---------------------------------------------------------

    QUOTA_HINTS = ("limit exceeded", "quota", "concurren")

    def _create_one(self, i, attempts=8, backoff=2.0):
        from daytona import CreateSandboxFromSnapshotParams

        last = None
        for attempt in range(attempts):
            try:
                # auto_stop_interval=0 disables auto-stop. The real warm pool
                # API is a 404 on this tier, so "warm" means acquiring the fleet
                # before the pitch and holding it. On the default idle timeout
                # the fleet would quietly stop between setup and the demo, and
                # the first dispatch would be resuming ten machines while the
                # room watches a still map.
                sb = self.daytona.create(CreateSandboxFromSnapshotParams(
                    snapshot=self.snapshot, labels={"searchlight": "worker"},
                    auto_stop_interval=0))
                break
            except Exception as e:
                last = e
                # Releasing a fleet does NOT free its quota immediately, so the
                # create that starts the next run fails while `list()` shows
                # zero sandboxes. Between two rehearsals that reads as "Daytona
                # is down". It is not; it is lag. Wait it out.
                if not any(h in str(e).lower() for h in self.QUOTA_HINTS):
                    raise
                if attempt == attempts - 1:
                    raise
                time.sleep(backoff)
        else:  # pragma: no cover - loop always breaks or raises
            raise last

        # Prime once per sandbox: the runtime is the same for every hypothesis,
        # only job.json changes. Doing this at dispatch would pay the upload
        # again on every retry.
        sb.fs.upload_file(self.sim_src, SB_SIM)
        with self._lock:
            self.sandboxes.append(sb)
        return sb

    def acquire(self, n, max_workers=None):
        """Create n sandboxes in parallel. Returns (sandboxes, errors).

        Partial success is normal and survivable -- a concurrency limit costs
        you workers, not the demo. The caller spreads hypotheses over whatever
        came back.
        """
        ready, errors = [], []
        t0 = time.perf_counter()
        with ThreadPoolExecutor(max_workers=max_workers or min(n, 64)) as pool:
            futs = [pool.submit(self._create_one, i) for i in range(n)]
            for f in as_completed(futs):
                try:
                    ready.append(f.result())
                    self.on_event("sandbox_ready", len(ready))
                except Exception as e:
                    errors.append("{}: {}".format(type(e).__name__, e))
        self.wall_acquire_s = time.perf_counter() - t0
        return ready, errors

    def release(self, sandboxes=None):
        sbs = sandboxes if sandboxes is not None else list(self.sandboxes)
        if not sbs:
            return
        with ThreadPoolExecutor(max_workers=min(len(sbs), 64)) as pool:
            list(pool.map(self._delete_one, sbs))

    def _delete_one(self, sb):
        try:
            self.daytona.delete(sb)
        except Exception:
            pass

    def reap(self, label="worker"):
        """Delete every sandbox this project left behind.

        The account tier allows 10 sandboxes total and the quota is SHARED, so
        one orphaned fleet blocks the whole team. Ctrl-C or a killed server
        skips the shutdown hook, which orphans ten of them, so this needs to be
        one command rather than a dashboard visit.
        """
        try:
            sbs = list(self.daytona.list())
        except Exception as e:
            print("could not list sandboxes: {}".format(e))
            return 0, 0  # caller unpacks two values; a bare 0 would raise here
        mine = [s for s in sbs
                if (getattr(s, "labels", None) or {}).get("searchlight")]
        for s in mine:
            self._delete_one(s)
        return len(mine), len(sbs)

    # -- dispatch ----------------------------------------------------------

    def dispatch(self, sb, hyp, script, generated):
        """Run one hypothesis on one sandbox. Never raises."""
        job = {"hypothesis": hyp, "script": script, "generated": generated}
        try:
            sb.fs.upload_file(json.dumps(job).encode("utf-8"), SB_JOB)
        except Exception as e:
            return failed_batch(hyp, "job upload failed: {}".format(e), generated)
        try:
            r = sb.process.exec(RUN_CMD, timeout=WORKER_TIMEOUT_S)
        except Exception as e:
            return failed_batch(hyp, "exec failed: {}".format(e), generated)
        try:
            batch = parse_output(getattr(r, "result", "") or "")
        except Exception as e:
            return failed_batch(hyp, "unparseable output: {}".format(e), generated)
        batch["generated"] = generated
        return batch

    def run_hypothesis(self, sb, hyp, script=None):
        """Dispatch, and fall back to the family template if generated code
        produced nothing usable.

        This is the line the demo rests on: the fallback is not a patch, it is
        the same code path with a different source string.
        """
        generated = script is not None
        if generated:
            batch = self.dispatch(sb, hyp, script, True)
            if any(r["status"] == "ok" for r in batch["runs"]):
                return batch
            self.on_event("generation_failed", hyp.get("hypothesis_id"))
        return self.dispatch(sb, hyp, template_for(hyp.get("family")), False)

    def run_all(self, sandboxes, work, on_batch=None):
        """Spread `work` -- a list of (hypothesis, script_or_None) -- over the
        sandboxes and collect every batch.

        Each sandbox owns a lane and works it SEQUENTIALLY. Firing concurrent
        execs at one sandbox looks like more parallelism and is not: it returns
        bare "Failed to execute command" with no detail, and it cost 300 of 720
        runs the first time. Parallelism comes from the number of sandboxes,
        which the account tier caps at MAX_SANDBOXES.
        """
        n = len(sandboxes)
        if not n:
            return [failed_batch(h, "no sandboxes available", s is not None)
                    for h, s in work]

        lanes = [[] for _ in range(n)]
        for i, item in enumerate(work):
            lanes[i % n].append(item)

        out, lock = [], threading.Lock()

        def drain(sb, lane):
            for hyp, script in lane:
                batch = self.run_hypothesis(sb, hyp, script)
                with lock:
                    out.append(batch)
                    done = len(out)
                if on_batch:
                    # A raising callback must not take this sandbox's remaining
                    # hypotheses with it. The callback does aggregation and
                    # WebSocket work; a dead client should cost one message,
                    # not a tenth of the simulation.
                    try:
                        on_batch(batch, done, len(work))
                    except Exception as e:
                        self.on_event("callback_error", str(e))
                        print("  [fleet] on_batch raised: {}: {}".format(
                            type(e).__name__, e))
                self.on_event("batch_done", done)

        with ThreadPoolExecutor(max_workers=n) as pool:
            futs = [pool.submit(drain, sandboxes[i], lanes[i]) for i in range(n)]
            for f in as_completed(futs):
                f.result()
        return out

    # -- snapshot ----------------------------------------------------------

    def ensure_snapshot(self, rebuild=False):
        """Bake the four terrain arrays into the image. NEVER pip install at
        sandbox start -- it multiplies across the whole fleet."""
        from daytona import CreateSnapshotParams, Image, Resources

        # A build that fails still leaves a snapshot record behind, and it is
        # not usable. Only ACTIVE counts as "already exists"; anything else gets
        # deleted so the rebuild can take the name.
        existing = None
        try:
            page = 1
            while existing is None:
                res = self.daytona.snapshot.list(page=page, limit=100)
                for s in res.items:
                    if s.name == self.snapshot:
                        existing = s
                        break
                if page >= (res.total_pages or 1):
                    break
                page += 1
        except Exception as e:
            print("  could not list snapshots: {}".format(e))

        if existing is not None:
            active = str(getattr(existing, "state", "")).endswith("ACTIVE")
            if active and not rebuild:
                return False
            print("  deleting existing snapshot (state={}, rebuild={})".format(
                getattr(existing, "state", "?"), rebuild))
            try:
                self.daytona.snapshot.delete(existing)
            except Exception as e:
                print("  delete failed: {}".format(e))
            # Deletion is asynchronous. Creating straight after returns 409
            # "already exists" -- poll until the name is actually free.
            for _ in range(60):
                time.sleep(1.0)
                try:
                    self.daytona.snapshot.get(self.snapshot)
                except Exception:
                    break
            else:
                print("  WARNING: snapshot name still taken after 60s")

        files = sorted(DATA.glob("*.npy")) + [DATA / "meta.json"]
        files = [p for p in files if p.exists()]
        mb = sum(p.stat().st_size for p in files) / 1e6
        print("baking {} file(s), {:.1f} MB, cpu={} mem={}GiB".format(
            len(files), mb, SNAPSHOT_CPU, SNAPSHOT_MEM_GIB))

        # Build from inside data/ and add files by BARE NAME.
        #
        # daytona 0.207.0 has a Windows bug: Image.add_local_file runs the local
        # path through ObjectStorage.compute_archive_base_path, which strips the
        # drive but keeps backslashes, and the resulting `COPY Users\masca\...`
        # reaches a Linux builder that reads every backslash as an escape. It
        # fails with `"/UsersmascaOneDrive...meta.json": not found`. A bare
        # filename has no separators to mangle. cwd must stay here through
        # create(), because the context is uploaded from the relative path.
        cwd = os.getcwd()
        try:
            os.chdir(DATA)
            image = Image.debian_slim("3.12").pip_install("numpy")
            for p in files:
                image = image.add_local_file(p.name, "/data/{}".format(p.name))

            t0 = time.time()
            self.daytona.snapshot.create(
                CreateSnapshotParams(
                    name=self.snapshot, image=image,
                    resources=Resources(cpu=SNAPSHOT_CPU,
                                        memory=SNAPSHOT_MEM_GIB)),
                on_logs=lambda m: print("    " + str(m).rstrip()))
        finally:
            os.chdir(cwd)
        print("  built in {:.1f}s".format(time.time() - t0))
        return True


# --------------------------------------------------------------------------
# CLI: the 12:30 milestone, runnable on its own
# --------------------------------------------------------------------------

def _demo_hypotheses(n, runs_per_batch, families):
    case = load_case()
    priors = json.loads((DATA / "priors.json").read_text())
    fams = families or list(priors["families"])
    out = []
    for i in range(n):
        fam = fams[i % len(fams)]
        out.append({
            "hypothesis_id": "h_{:05d}".format(i),
            "family": fam,
            "description": "fleet check, {}".format(fam),
            "weight": priors["families"][fam],
            "start": case["ipp"],
            "duration_s": case["last_contact_s_ago"],
            "n_runs": runs_per_batch,
            "seed_base": 1000 * (i + 1),
        })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=MAX_SANDBOXES, help="sandboxes")
    ap.add_argument("--hypotheses", type=int, help="default: one per sandbox")
    ap.add_argument("--runs", type=int, default=60, help="runs per hypothesis")
    ap.add_argument("--smoke", action="store_true", help="1 sandbox, 4 runs")
    ap.add_argument("--keep", action="store_true", help="leave sandboxes alive")
    ap.add_argument("--build-snapshot", action="store_true")
    ap.add_argument("--rebuild", action="store_true")
    ap.add_argument("--dump", help="write the collected batches here")
    ap.add_argument("--reap", action="store_true",
                    help="delete every searchlight sandbox and exit")
    args = ap.parse_args()

    fleet = Fleet()
    if args.reap:
        mine, total = fleet.reap()
        print("deleted {} searchlight sandbox(es) of {} alive".format(mine, total))
        return 0
    if args.build_snapshot or args.rebuild:
        built = fleet.ensure_snapshot(rebuild=args.rebuild)
        print("snapshot '{}' {}".format(SNAPSHOT,
                                        "built" if built else "already exists"))
        if args.build_snapshot:
            return 0

    n, runs = (1, 4) if args.smoke else (args.n, args.runs)
    n_hyp = 1 if args.smoke else (args.hypotheses or n)
    hyps = _demo_hypotheses(n_hyp, runs, None)

    print("acquiring {} sandbox(es)...".format(n))
    sbs, errors = fleet.acquire(n)
    print("  {} ready, {} failed, wall {:.2f}s".format(
        len(sbs), len(errors), fleet.wall_acquire_s))
    for e in errors[:3]:
        print("  ERROR " + e)
    if not sbs:
        return 1

    print("dispatching {} hypotheses over {} sandbox(es), {} runs each...".format(
        len(hyps), len(sbs), runs))
    t0 = time.perf_counter()
    first = {}

    def progress(batch, done, total):
        first.setdefault("t", time.perf_counter() - t0)
        if done % max(1, total // 8) == 0 or done == total:
            print("  {}/{} batches  {:.2f}s".format(
                done, total, time.perf_counter() - t0))

    batches = fleet.run_all(sbs, [(h, None) for h in hyps], on_batch=progress)
    wall = time.perf_counter() - t0

    n_ok = sum(1 for b in batches for r in b["runs"] if r["status"] == "ok")
    n_run = sum(len(b["runs"]) for b in batches)
    n_gen = sum(1 for b in batches if b.get("generated"))
    print()
    print("{}/{} runs ok across {} batches ({} generated) in {:.2f}s".format(
        n_ok, n_run, len(batches), n_gen, wall))
    print("first batch back at {:.2f}s  |  {:.0f} sims/s".format(
        first.get("t", 0.0), n_ok / max(wall, 1e-6)))
    for b in batches:
        if b.get("error"):
            print("  {} {}: {}".format(b["hypothesis_id"], b["family"],
                                       b["error"][:160]))

    if args.dump:
        from pathlib import Path
        Path(args.dump).write_text(json.dumps({"batches": batches}, indent=2))
        print("wrote {}".format(args.dump))

    if args.keep:
        print("\nsandboxes left alive (--keep). Inspect one:")
        print("  {} -> {}/hypothesis.py, {}/batch.json".format(
            sbs[0].id, SB_DIR, SB_DIR))
    else:
        fleet.release(sbs)
        print("released {} sandbox(es)".format(len(sbs)))
    return 0 if n_ok else 1


if __name__ == "__main__":
    sys.exit(main())
