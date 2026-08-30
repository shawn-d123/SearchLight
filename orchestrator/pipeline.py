"""The run itself: hypotheses -> generated scripts -> fleet -> batches -> field.

Headless and synchronous on purpose. `server.py` wraps it for the WebSocket;
this module can be driven from a terminal with no browser, which is how you
debug it at 14:30 when the frontend is also moving.

    python orchestrator/pipeline.py --hypotheses 12 --total-runs 2400
    python orchestrator/pipeline.py --no-model        # templates only
"""
from __future__ import annotations

import argparse, json, sys, threading, time

from settings import MAX_SANDBOXES, ROOT, load_case
import hypotheses as hypmod
from fleet import Fleet

sys.path.insert(0, str(ROOT))

# CONTRACT.md section 9: max 200 runs per trajectory_batch message. Twelve
# thousand individual messages will kill the browser.
MAX_RUNS_PER_MESSAGE = 200
FIELD_UPDATE_EVERY_S = 1.0
FLEET_STATUS_EVERY_S = 0.5
DISPLAY_RESOLUTION = 256


class Pipeline:
    def __init__(self, emit=None, n_sandboxes=MAX_SANDBOXES, use_model=True):
        self.emit = emit or (lambda t, p: None)
        self.n_sandboxes = n_sandboxes
        self.use_model = use_model
        self.fleet = Fleet()
        self.sandboxes = []
        self.case = None
        self.batches = []
        self._folded = 0        # batches already folded into the accumulator
        self._prepared = None
        self._warned = set()    # per instance, not per class -- see _warn_once
        self._lock = threading.Lock()
        # _emit_field is called from on_batch, which fleet.run_all invokes from
        # PARALLEL worker threads. Two concurrent calls both read self._folded
        # before either advances it, so the same batches get folded twice --
        # measured n_total 800 for a 600-run job, with those endpoints also
        # double-weighted in the field. One folder at a time.
        self._field_lock = threading.Lock()
        self._stats = {"active": 0, "complete": 0, "failed": 0, "families": {}}

    # -- setup -------------------------------------------------------------

    def acquire_fleet(self):
        """Call this at startup, not when the operator presses run. Cold start
        is only ~2 s for the whole fleet, but 2 s of still map is 2 s of still
        map. There is no warm-pool API on this tier -- see prep/TIMINGS.md."""
        self.fleet.ensure_snapshot()
        self.sandboxes, errors = self.fleet.acquire(self.n_sandboxes)
        return self.sandboxes, errors

    def release_fleet(self):
        # Release EVERYTHING the fleet created, not just the list this pipeline
        # happens to hold. A sandbox that failed during setup is tracked by the
        # fleet but never reached self.sandboxes, and releasing only the local
        # list left it alive and billing.
        self.fleet.release()
        self.sandboxes = []

    # -- the run -----------------------------------------------------------

    def prepare(self, case, total_runs=12000, n_hypotheses=12):
        """Everything the model has to do, done BEFORE the operator presses run.

        Measured: hypothesis generation is ~13 s and codegen ~4 s, against a
        fan-out of ~3.5 s. Doing them on the keypress means seventeen seconds of
        still map before anything moves, with the beat that has to land arriving
        last. Run this while the briefing is on screen and `run()` puts paths up
        in half a second.
        """
        self.case = case
        hyps, err = self._hypotheses(case, n_hypotheses)
        hyps = hypmod.expand(hyps, case, total_runs=total_runs)
        scripts = self._scripts(hyps)
        self._prepared = (hyps, scripts)
        self.emit("hypotheses_ready", {
            "n_hypotheses": len(hyps),
            "n_generated": len(scripts),
            "hypotheses": [
                {"hypothesis_id": h["hypothesis_id"], "family": h["family"],
                 "description": h["description"], "rationale": h.get("rationale"),
                 "source": h.get("source")}
                for h in sorted(hyps, key=lambda x: -x["weight"])[:6]],
        })
        return hyps, scripts, err

    def run(self, case, total_runs=12000, n_hypotheses=12, evidence=None):
        self.case = case
        self.batches = []
        self._folded = 0
        self.emit("case_loaded", case)

        prepared = getattr(self, "_prepared", None)
        if prepared:
            hyps, scripts, err = prepared[0], prepared[1], None
            self._prepared = None
            # Honour the caller's run size. prepare() runs at STARTUP with the
            # server defaults, so without this a run command asking for 600
            # sims silently delivered 12,000 -- the frontend could not size a
            # run at all. Re-expanding is arithmetic on the existing
            # hypotheses: no model call, and hypothesis_id is assigned by
            # index so the prepared scripts still map.
            if total_runs and sum(h["n_runs"] for h in hyps) != total_runs:
                hyps = hypmod.expand(hyps, case, total_runs=total_runs)
        else:
            hyps, err = self._hypotheses(case, n_hypotheses)
            hyps = hypmod.expand(hyps, case, total_runs=total_runs)
            scripts = None  # generated after sim_started, below

        self.emit("sim_started", {
            "n_planned": sum(h["n_runs"] for h in hyps),
            "n_hypotheses": len(hyps),
            "n_sandboxes": len(self.sandboxes),
            # CONTRACT.md section 7: at most 6, highest-weighted first.
            "hypotheses": [
                {"hypothesis_id": h["hypothesis_id"], "family": h["family"],
                 "description": h["description"], "source": h.get("source")}
                for h in sorted(hyps, key=lambda x: -x["weight"])[:6]],
        })

        if scripts is None:
            scripts = self._scripts(hyps)

        self._stats = {"active": len(self.sandboxes), "complete": 0,
                       "failed": 0, "families": {}}
        stop = threading.Event()
        ticker = threading.Thread(target=self._fleet_status_loop, args=(stop,),
                                  daemon=True)
        ticker.start()

        pending, last_field = [], [0.0]
        accumulator_ref = [None]

        def on_batch(batch, done, total):
            with self._lock:
                self.batches.append(batch)
                ok = sum(1 for r in batch["runs"] if r["status"] == "ok")
                self._stats["complete"] += ok
                self._stats["failed"] += len(batch["runs"]) - ok
                fam = batch["family"]
                self._stats["families"][fam] = \
                    self._stats["families"].get(fam, 0) + ok
                pending.append(batch)
                n_pending = sum(len(b["runs"]) for b in pending)
                flush = n_pending >= MAX_RUNS_PER_MESSAGE or done == total
                due = (time.monotonic() - last_field[0]) > FIELD_UPDATE_EVERY_S
                batch_slice = list(pending) if flush else None
                if flush:
                    pending.clear()
            if batch_slice:
                self._emit_trajectories(batch_slice)
            if due or done == total:
                last_field[0] = time.monotonic()
                accumulator_ref[0] = self._emit_field(
                    accumulator_ref[0], done / max(1, total),
                    blocking=(done == total))

        work = [(h, scripts.get(h["hypothesis_id"])) for h in hyps]
        t0 = time.perf_counter()
        self.fleet.run_all(self.sandboxes, work, on_batch=on_batch)
        wall = time.perf_counter() - t0

        stop.set()
        self._emit_fleet_status(final=True)

        if evidence:
            self._emit_evidence(evidence)

        return {"batches": self.batches, "wall_s": wall,
                "hypothesis_error": err,
                "n_generated": sum(1 for b in self.batches if b.get("generated"))}

    # -- steps -------------------------------------------------------------

    def _hypotheses(self, case, n):
        if not self.use_model:
            return hypmod.fallback_hypotheses(case, n), None
        t0 = time.perf_counter()
        hyps, err = hypmod.generate(case, n=n)
        self.emit("log", {"step": "hypotheses", "n": len(hyps),
                          "s": round(time.perf_counter() - t0, 2),
                          "error": err})
        return hyps, err

    def _scripts(self, hyps):
        """One model call per hypothesis -> one generated script per sandbox.

        A missing script is not an error path, it is the floor: the fleet falls
        back to that family's hand-written template and marks the batch
        `generated: false`.
        """
        if not self.use_model:
            return {}
        import codegen
        from terrain_summary import summarise
        facts, _ = summarise(*self.case["ipp"])
        t0 = time.perf_counter()
        scripts, errors = codegen.generate_many(
            codegen.client(), hyps, facts,
            max_workers=min(len(hyps), 32))
        self.emit("log", {"step": "codegen", "ok": len(scripts),
                          "failed": len(errors),
                          "s": round(time.perf_counter() - t0, 2)})
        return scripts

    # -- emitters ----------------------------------------------------------

    def _emit_trajectories(self, batches):
        """Never more than MAX_RUNS_PER_MESSAGE runs per message."""
        out, n = [], 0
        for b in batches:
            for i in range(0, len(b["runs"]), MAX_RUNS_PER_MESSAGE):
                chunk = b["runs"][i:i + MAX_RUNS_PER_MESSAGE]
                piece = {k: b[k] for k in
                         ("hypothesis_id", "family", "weight", "generated")}
                piece["runs"] = [r for r in chunk if r["status"] == "ok"]
                if not piece["runs"]:
                    continue
                if n + len(piece["runs"]) > MAX_RUNS_PER_MESSAGE and out:
                    self.emit("trajectory_batch", {"batches": out})
                    out, n = [], 0
                out.append(piece)
                n += len(piece["runs"])
        if out:
            self.emit("trajectory_batch", {"batches": out})

    def _emit_field(self, accumulator, progress, blocking=False):
        """Person C owns build_field. Until it exists this is a no-op that says
        so once, rather than a crash that takes the run with it.

        Serialised: a concurrent caller skips rather than queues, because the
        next tick folds whatever it missed. The FINAL emit passes blocking=True
        so the last batches are never dropped.
        """
        if not self._field_lock.acquire(blocking=blocking):
            return accumulator
        try:
            return self._emit_field_locked(accumulator, progress)
        finally:
            self._field_lock.release()

    def _emit_field_locked(self, accumulator, progress):
        try:
            from model.field import build_field, field_payload
        except Exception as e:
            self._warn_once("field_import", "model.field unavailable: {}".format(e))
            return accumulator

        # Fold ONLY the batches not already in the accumulator. build_field is
        # incremental -- passing the full list back alongside the accumulator
        # re-adds every earlier trajectory on every update, so by the end the
        # first batch is counted sixty times and the field is weighted towards
        # whichever hypotheses happened to finish first.
        #
        # Snapshotting under the lock also matters: other lanes append to
        # self.batches while this runs.
        with self._lock:
            new = self.batches[self._folded:]
            folded_to = len(self.batches)
        if not new and accumulator is not None:
            return accumulator

        # CONTRACT.md section 10: build_field returns (grid, accumulator). The
        # accumulator is opaque state owned by model/field.py -- keep handing
        # back exactly what it gave us, never the grid.
        try:
            grid, accumulator = build_field(new, self.case["bounds"],
                                            DISPLAY_RESOLUTION,
                                            accumulator=accumulator)
        except NotImplementedError:
            self._warn_once("field_stub",
                            "model.build_field is still a stub (Person C)"
                            " - no field_update will be sent")
            return accumulator
        except Exception as e:
            self._warn_once("field_error", "build_field raised: {}".format(e))
            return accumulator

        # Only now is it safe to say these batches are in the accumulator. On
        # any failure above we return early WITHOUT advancing, so the batches
        # are folded in on the next attempt rather than silently dropped.
        self._folded = folded_to

        try:
            payload = field_payload(
                grid, accumulator, self.case["bounds"], DISPLAY_RESOLUTION,
                self.case.get("ring_radius_m") or 9545.9,
                progress=progress, terrain=self._zone_terrain())
        except Exception as e:
            self._warn_once("payload_error", "field_payload raised: {}".format(e))
            return accumulator
        self.emit("field_update", payload)
        return accumulator

    def _zone_terrain(self):
        """Elevation array for naming zones. Loaded once; absent is fine."""
        if not hasattr(self, "_zt"):
            try:
                from model.field import load_terrain
                self._zt = load_terrain()
            except Exception:
                self._zt = None
        return self._zt

    def _emit_evidence(self, evidence):
        with self._lock:
            batches = list(self.batches)
        # Returns (filtered_batches, field payload) -- the payload is already in
        # the CONTRACT section 7 shape, so it goes on the wire as-is with the
        # evidence attached alongside it (section 9, `evidence_applied`).
        try:
            from model.field import apply_evidence
            _filtered, field = apply_evidence(
                batches, evidence, bounds=self.case["bounds"],
                resolution=DISPLAY_RESOLUTION,
                ring_radius_m=self.case.get("ring_radius_m"))
        except NotImplementedError:
            self._warn_once("evidence_stub",
                            "model.apply_evidence is still a stub (Person C)")
            return
        except Exception as e:
            self._warn_once("evidence_error", "apply_evidence raised: {}".format(e))
            return
        payload = dict(field)
        payload["evidence"] = evidence
        self.emit("evidence_applied", payload)

    def _fleet_status_loop(self, stop):
        while not stop.wait(FLEET_STATUS_EVERY_S):
            self._emit_fleet_status()

    def _emit_fleet_status(self, final=False):
        with self._lock:
            s = dict(self._stats)
            s["families"] = dict(s["families"])
        if final:
            s["active"] = 0
        self.emit("fleet_status", s)

    def _warn_once(self, tag, msg):
        if tag in self._warned:
            return
        self._warned.add(tag)
        print("  [pipeline] {}".format(msg))
        self.emit("log", {"warning": msg})


# --------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hypotheses", type=int, default=12)
    ap.add_argument("--total-runs", type=int, default=2400)
    ap.add_argument("--sandboxes", type=int, default=MAX_SANDBOXES)
    ap.add_argument("--no-model", action="store_true",
                    help="templates only -- proves the zero-generation floor")
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--dump")
    args = ap.parse_args()

    counts = {}

    def emit(t, p):
        counts[t] = counts.get(t, 0) + 1
        if t in ("log",):
            print("  log: {}".format(p))
        elif t == "field_update":
            print("  field {:>3.0f}%  area {:>5.1f}% of ring  n={}  zones: {}"
                  .format(p["progress"] * 100, p.get("field_area_pct", -1),
                          p.get("n_total"),
                          ", ".join("{} {:.0f}%".format(z["name"], z["pct"])
                                    for z in p.get("zones", []))))
        elif t == "sim_started":
            print("sim_started: {} runs over {} hypotheses, {} sandboxes"
                  .format(p["n_planned"], p["n_hypotheses"], p["n_sandboxes"]))
            for h in p["hypotheses"]:
                print("   [{}] {}".format(h["family"], h["description"][:88]))

    case = load_case()
    pipe = Pipeline(emit=emit, n_sandboxes=args.sandboxes,
                    use_model=not args.no_model)

    print("acquiring fleet...")
    sbs, errors = pipe.acquire_fleet()
    print("  {} sandboxes ready, {} failed ({:.2f}s)".format(
        len(sbs), len(errors), pipe.fleet.wall_acquire_s))
    for e in errors[:2]:
        print("  ERROR " + e)
    if not sbs:
        return 1

    try:
        t_prep = time.perf_counter()
        pipe.prepare(case, total_runs=args.total_runs,
                     n_hypotheses=args.hypotheses)
        t_prep = time.perf_counter() - t_prep
        print("prepare (model work, off the critical path): {:.2f}s".format(t_prep))
        res = pipe.run(case, total_runs=args.total_runs,
                       n_hypotheses=args.hypotheses)
    finally:
        if not args.keep:
            pipe.release_fleet()
            print("released fleet")

    n_ok = sum(1 for b in res["batches"] for r in b["runs"] if r["status"] == "ok")
    n_all = sum(len(b["runs"]) for b in res["batches"])
    print()
    print("{}/{} sims ok  |  {}/{} batches from GENERATED code  |  {:.2f}s"
          .format(n_ok, n_all, res["n_generated"], len(res["batches"]),
                  res["wall_s"]))
    print("messages: {}".format(counts))

    reasons = {}
    for b in res["batches"]:
        for r in b["runs"]:
            if r["status"] != "ok":
                reasons[r.get("error", "?")] = reasons.get(r.get("error", "?"), 0) + 1
    for why, k in sorted(reasons.items(), key=lambda x: -x[1]):
        print("  {:>5}x  {}".format(k, why[:110]))

    if args.dump:
        from pathlib import Path
        Path(args.dump).write_text(json.dumps({"batches": res["batches"]}))
        print("wrote {}".format(args.dump))
    return 0 if n_ok else 1


if __name__ == "__main__":
    sys.exit(main())
