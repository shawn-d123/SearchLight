"""Fleet control. Dispatch hypotheses to sandboxes, collect trajectory batches.

Two backends behind one interface:

  LocalFleet    -- runs in this process. No credits, no network. Use it for
                   everything except measuring real sandbox timings.
  DaytonaFleet  -- the real thing. One sandbox per hypothesis, one generated
                   script per sandbox, N seeds inside.

**Credit discipline is built in, not left to the caller.**

  - every sandbox is created with a label and torn down in a `finally`,
    and again by an atexit hook if the process dies mid-flight
  - `estimate_cost` prints before anything spins up
  - MAX_SANDBOXES is a hard ceiling; exceeding it raises rather than bills
  - `reap()` finds and deletes orphans from an earlier crashed run

An idle sandbox costs about $0.083/hour at 1 vCPU / 2 GiB. That is cheap, but
a fleet of 200 left running overnight is not, and the failure mode is silent.
"""
from __future__ import annotations

import atexit
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SNAPSHOT = "searchlight-worker"
LABEL = {"searchlight": "fleet"}
WORKER_FILES = ("__init__.py", "terrain.py", "templates.py", "runner.py")

# Hard ceiling. The spec plans 200; anything far above that is a mistake, and
# a mistake that bills by the second should fail loudly instead of running.
MAX_SANDBOXES = 260

# $/hour at 1 vCPU + 2 GiB, from Daytona's published rates.
COST_PER_SANDBOX_HOUR = 0.0504 * 1 + 0.0162 * 2

# Keyed by sandbox id, NOT a set: Sandbox objects are unhashable, and adding
# one raised AFTER the sandbox had already been created -- so provisioning
# aborted with five live sandboxes billing and no handle on them. The label
# plus prep/daytona_ctl.py is what made them findable.
_live = {}
_live_lock = threading.Lock()


def _remember(sb):
    with _live_lock:
        _live[str(getattr(sb, "id", id(sb)))] = sb


def _forget(sb):
    with _live_lock:
        _live.pop(str(getattr(sb, "id", id(sb))), None)


@atexit.register
def _sweep():
    """Last-ditch cleanup if the process exits with sandboxes still up."""
    with _live_lock:
        left = list(_live.values())
    if not left:
        return
    print("atexit: deleting {} sandbox(es) still running".format(len(left)))
    for sb in left:
        try:
            sb.delete()
        except Exception:
            pass


def load_env():
    env = ROOT / ".env"
    if env.exists():
        for ln in env.read_text(encoding="utf-8").splitlines():
            if "=" in ln and not ln.strip().startswith("#"):
                k, v = ln.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def estimate_cost(n, minutes):
    """Print what a run will cost before it runs."""
    usd = n * COST_PER_SANDBOX_HOUR * (minutes / 60.0)
    print("  cost estimate: {} sandboxes x {:.0f} min = ${:.3f} "
          "(${:.4f}/sandbox-hour)".format(n, minutes, usd, COST_PER_SANDBOX_HOUR))
    return usd


# ---------------------------------------------------------------------------
# local
# ---------------------------------------------------------------------------

class LocalFleet:
    """In-process execution. Same interface, no credits, no network."""

    def __init__(self, data_dir=None, **_):
        from worker.terrain import Terrain
        self.terrain = Terrain(str(data_dir or ROOT / "data"))
        self.backend = "local"

    def run(self, hypotheses, scripts=None, on_batch=None, **_):
        from worker.runner import run_hypothesis
        out = []
        for i, h in enumerate(hypotheses):
            script = (scripts or {}).get(h["hypothesis_id"])
            batch, _note = run_hypothesis(h, self.terrain, script)
            out.append(batch)
            if on_batch:
                on_batch(batch, i + 1, len(hypotheses))
        return out

    def close(self):
        pass


# ---------------------------------------------------------------------------
# daytona
# ---------------------------------------------------------------------------

class DaytonaFleet:
    """Real sandboxes. Create in parallel, dispatch, collect, always tear down."""

    def __init__(self, snapshot=SNAPSHOT, max_workers=32, timeout_s=180,
                 keep=False):
        load_env()
        key = os.environ.get("DAYTONA_API_KEY", "").strip()
        if not key:
            raise RuntimeError("no DAYTONA_API_KEY in environment or .env")
        from daytona import Daytona, DaytonaConfig
        self._d = Daytona(DaytonaConfig(api_key=key))
        self.snapshot = snapshot
        self.max_workers = max_workers
        self.timeout_s = timeout_s
        self.keep = keep
        self.sandboxes = []
        self.backend = "daytona"
        self.timings = {}

    # -- lifecycle ----------------------------------------------------------

    def provision(self, n):
        """Create n sandboxes in parallel and upload the worker into each."""
        if n > MAX_SANDBOXES:
            raise ValueError(
                "refusing to create {} sandboxes; MAX_SANDBOXES is {}. Raise it "
                "deliberately if you really mean to.".format(n, MAX_SANDBOXES))
        from daytona import CreateSandboxFromSnapshotParams

        files = [(str(ROOT / "worker" / f), "/worker/" + f) for f in WORKER_FILES]

        def one(_i):
            sb = self._d.create(CreateSandboxFromSnapshotParams(
                snapshot=self.snapshot, labels=dict(LABEL)))
            _remember(sb)
            for src, dst in files:
                sb.fs.upload_file(src, dst)
            return sb

        t0 = time.perf_counter()
        errs = []
        with ThreadPoolExecutor(max_workers=min(self.max_workers, n)) as pool:
            for f in as_completed([pool.submit(one, i) for i in range(n)]):
                try:
                    self.sandboxes.append(f.result())
                except Exception as e:
                    errs.append("{}: {}".format(type(e).__name__, str(e)[:160]))
        self.timings["provision_s"] = time.perf_counter() - t0
        self.timings["provision_errors"] = errs
        if errs and not self.sandboxes:
            self.close()
            raise RuntimeError("no sandboxes came up. First error: " + errs[0])
        return self.sandboxes

    def close(self):
        """Delete every sandbox. Safe to call twice."""
        if self.keep or not self.sandboxes:
            if self.keep and self.sandboxes:
                print("  --keep set: {} sandboxes LEFT RUNNING and billing. "
                      "Delete with: python prep/daytona_ctl.py clean"
                      .format(len(self.sandboxes)))
            return
        t0 = time.perf_counter()
        with ThreadPoolExecutor(max_workers=min(self.max_workers,
                                                len(self.sandboxes))) as pool:
            list(pool.map(self._delete_one, list(self.sandboxes)))
        self.timings["teardown_s"] = time.perf_counter() - t0
        self.sandboxes = []

    def _delete_one(self, sb):
        try:
            self._d.delete(sb)
        except Exception:
            pass
        finally:
            _forget(sb)

    # -- work ---------------------------------------------------------------

    def run(self, hypotheses, scripts=None, on_batch=None, provision=True):
        """Dispatch one hypothesis per sandbox. Returns batches, in any order.

        A sandbox that fails to answer still yields a batch -- the deterministic
        template is run locally instead -- because the field must not develop a
        hole just because one machine died.
        """
        hypotheses = list(hypotheses)
        if provision and len(self.sandboxes) < len(hypotheses):
            self.provision(len(hypotheses) - len(self.sandboxes))
        if not self.sandboxes:
            raise RuntimeError("no sandboxes available")

        scripts = scripts or {}
        done = [0]
        lock = threading.Lock()
        out = []

        def one(sb, h):
            hid = h["hypothesis_id"]
            payload = {"hypothesis": h}
            if scripts.get(hid):
                payload["script"] = scripts[hid]
            try:
                sb.fs.upload_file(json.dumps(payload).encode(),
                                  "/h_{}.json".format(hid))
                r = sb.process.exec(
                    "cd / && python -m worker.runner /h_{}.json".format(hid),
                    timeout=self.timeout_s)
                return json.loads((getattr(r, "result", "") or "").strip())
            except Exception as e:
                return {"__failed__": "{}: {}".format(
                    type(e).__name__, str(e)[:160]), "hypothesis": h}

        t0 = time.perf_counter()
        pairs = [(self.sandboxes[i % len(self.sandboxes)], h)
                 for i, h in enumerate(hypotheses)]
        with ThreadPoolExecutor(max_workers=min(self.max_workers,
                                                len(pairs))) as pool:
            for f in as_completed([pool.submit(one, sb, h) for sb, h in pairs]):
                b = f.result()
                if "__failed__" in b:
                    b = self._local_fallback(b["hypothesis"], b["__failed__"])
                out.append(b)
                with lock:
                    done[0] += 1
                    n = done[0]
                if on_batch:
                    on_batch(b, n, len(pairs))
        self.timings["dispatch_s"] = time.perf_counter() - t0
        return out

    def _local_fallback(self, h, note):
        """A dead sandbox must not leave a hole in the field."""
        from worker.runner import run_hypothesis
        from worker.terrain import Terrain
        if not hasattr(self, "_terrain"):
            self._terrain = Terrain(str(ROOT / "data"))
        batch, _ = run_hypothesis(h, self._terrain)
        batch["note"] = "sandbox failed, ran locally: " + note
        batch["generated"] = False
        return batch

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def reap(dry_run=False):
    """Delete every sandbox this project left behind. Run it if a run crashed."""
    load_env()
    from daytona import Daytona, DaytonaConfig
    d = Daytona(DaytonaConfig(api_key=os.environ["DAYTONA_API_KEY"]))
    found = list(d.list())
    mine = [s for s in found
            if (getattr(s, "labels", None) or {}).get("searchlight")]
    print("{} sandbox(es) exist, {} tagged searchlight".format(
        len(found), len(mine)))
    for s in found:
        tag = (getattr(s, "labels", None) or {}).get("searchlight", "-")
        print("   {} state={} searchlight={}".format(
            getattr(s, "id", "?"), getattr(s, "state", "?"), tag))
    if dry_run or not mine:
        return mine
    for s in mine:
        try:
            d.delete(s)
            print("   deleted {}".format(s.id))
        except Exception as e:
            print("   FAILED to delete {}: {}".format(s.id, e))
    return mine
