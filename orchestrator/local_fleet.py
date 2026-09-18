"""The fleet, without Daytona: the same worker, run in this process.

`fleet.Fleet` uploads a job to a remote sandbox and execs `sim.py` there.
`LocalFleet` calls the identical `sim.run_batch` over a thread pool instead.
Both present the same four methods to `pipeline.Pipeline`, so nothing upstream
knows which one it is holding.

What this preserves is most of the product. Hypotheses are expanded against the
real ISRID weights, the movement code is the same, the terrain arrays are the
same mmapped files the sandbox bakes into its snapshot, and the field, the zone
naming and the evidence filter are byte-for-byte the live path. What it gives
up is the isolation boundary and the model call that writes each script -- so
every batch runs the hand-written family template and is reported
`generated: false`, which is exactly what the live path does when a generation
fails.

    python orchestrator/pipeline.py --offline --total-runs 2400

Isolation is the thing Daytona is there for, and running generated code in
this process would throw it away. LocalFleet therefore refuses a generated
script and takes the template, rather than exec'ing model output on the
developer's laptop.
"""
from __future__ import annotations

import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from settings import DATA, WORKER, WORKER_BUDGET_S

# WORKER_BUDGET_S is 8 s because a sandbox has a 10 s hard exec timeout in
# front of it. Nothing here is behind a network timeout, and the lanes are
# threads sharing one machine rather than ten vCPUs, so a batch takes
# roughly ten times longer per run. Budget by run count: a fixed 8 s
# silently truncated 331 of 2,400 runs with 'batch deadline', which is a
# quiet wrong answer rather than a loud failure.
LOCAL_BUDGET_PER_RUN_S = 0.1

sys.path.insert(0, str(WORKER))
import sim as simmod                       # noqa: E402
from templates import template_for         # noqa: E402


class Lane:
    """Stands where a sandbox stands. Carries only its index, because the
    parallelism here is threads and the terrain is shared."""

    def __init__(self, index):
        self.index = index
        self.id = "local-{:02d}".format(index)

    def __repr__(self):
        return "<Lane {}>".format(self.id)


class LocalFleet:
    def __init__(self, on_event=None):
        self.on_event = on_event or (lambda *a: None)
        self.lanes = []
        self.wall_acquire_s = 0.0
        self._lock = threading.Lock()

    # -- lifecycle ---------------------------------------------------------

    def ensure_snapshot(self, rebuild=False):
        """Nothing to bake. Reading the terrain once here turns a missing or
        truncated array into an error at startup rather than into sixty failed
        runs with a compile message that does not mention the real cause."""
        simmod.Terrain(DATA)

    def acquire(self, n, max_workers=None):
        t0 = time.perf_counter()
        self.lanes = [Lane(i) for i in range(n)]
        self.wall_acquire_s = time.perf_counter() - t0
        return self.lanes, []

    def release(self, sandboxes=None):
        self.lanes = []

    # -- dispatch ----------------------------------------------------------

    def run_hypothesis(self, lane, hyp, script=None):
        """One hypothesis, one batch. Never raises.

        `script` is accepted and ignored. Generated code belongs in a sandbox;
        the whole argument for the fleet is that it is not executed here.
        """
        if script is not None:
            self.on_event("script_declined", hyp.get("hypothesis_id"))
        job = {"hypothesis": hyp,
               "script": template_for(hyp.get("family")),
               "generated": False}
        budget = max(WORKER_BUDGET_S,
                     int(hyp.get("n_runs", 60)) * LOCAL_BUDGET_PER_RUN_S)
        try:
            batch = simmod.run_batch(job, str(DATA), budget_s=budget)
        except Exception as e:
            n = int(hyp.get("n_runs", 60))
            return {"hypothesis_id": hyp["hypothesis_id"],
                    "family": hyp.get("family", "route_travelling"),
                    "weight": hyp.get("weight", 0.0),
                    "generated": False,
                    "error": "{}: {}".format(type(e).__name__, e)[:300],
                    "runs": [{"run_index": i, "status": "failed",
                              "error": "local run raised"} for i in range(n)]}
        batch["generated"] = False
        return batch

    def run_all(self, sandboxes, work, on_batch=None):
        """Same lane split as the Daytona fleet, so batch arrival order and the
        shape of the progress callbacks match what the live path produces."""
        n = len(sandboxes)
        if not n:
            return []

        lanes = [[] for _ in range(n)]
        for i, item in enumerate(work):
            lanes[i % n].append(item)

        out = []

        def drain(lane, items):
            for hyp, script in items:
                batch = self.run_hypothesis(lane, hyp, script)
                with self._lock:
                    out.append(batch)
                    done = len(out)
                if on_batch:
                    # A raising callback must not take this lane's remaining
                    # hypotheses with it.
                    try:
                        on_batch(batch, done, len(work))
                    except Exception as e:
                        self.on_event("callback_error", str(e))
                        print("  [local-fleet] on_batch raised: {}: {}".format(
                            type(e).__name__, e))
                self.on_event("batch_done", done)

        with ThreadPoolExecutor(max_workers=n) as pool:
            futs = [pool.submit(drain, sandboxes[i], lanes[i]) for i in range(n)]
            for f in as_completed(futs):
                f.result()
        return out
