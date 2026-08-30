"""FastAPI + WebSocket server. `ws://localhost:8000/ws`, per CONTRACT.md section 9.

Every message is `{"type": ..., "seq": n, "payload": {...}}`.

The pipeline is synchronous and runs in a worker thread; messages cross into the
event loop through a queue. Person A drives it with `state_change` and `run`.

    python orchestrator/server.py
    python orchestrator/server.py --no-fleet    # mocks, no Daytona, no keys
"""
from __future__ import annotations

import collections
import argparse, asyncio, json, threading, time
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from settings import DATA, MOCKS, MAX_SANDBOXES, load_case as settings_load_case
from pipeline import Pipeline

STATES = ("landing", "intake", "briefing", "simulating", "field_ready",
          "evidence", "validation")

@asynccontextmanager
async def lifespan(app):
    hub.loop = asyncio.get_running_loop()
    if CONFIG["use_fleet"]:
        # Acquire at startup, not on the keypress. See prep/TIMINGS.md: there is
        # no warm-pool API on this tier, so holding the fleet IS the warm pool.
        threading.Thread(target=_boot_fleet, daemon=True).start()
    try:
        yield
    finally:
        if pipeline:
            print("releasing fleet...")
            pipeline.release_fleet()


app = FastAPI(title="Searchlight orchestrator", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                   allow_headers=["*"])


class Hub:
    """Fan-out to every connected client, with a monotonic seq per CONTRACT.md."""

    def __init__(self):
        self.clients = set()
        self.seq = 0
        self.loop = None
        self.lock = threading.Lock()
        self.history = []          # replayed to a client that joins mid-run
        self.state = "landing"
        self.pending = collections.deque()
        self.draining = False

    def envelope(self, mtype, payload):
        with self.lock:
            self.seq += 1
            return {"type": mtype, "seq": self.seq, "payload": payload}

    async def _send(self, msg):
        dead = []
        for ws in list(self.clients):
            try:
                await ws.send_text(json.dumps(msg))
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)

    def emit_threadsafe(self, mtype, payload):
        """Called from the pipeline's worker thread.

        Queued, not sent directly. seq was previously stamped here and the send
        scheduled separately with run_coroutine_threadsafe, so concurrent
        producer threads had their sends completed out of order -- measured
        breaks like trajectory_batch seq=112 followed by fleet_status seq=106.
        The lock protected the counter but not the wire, and a frontend cannot
        order or de-duplicate on a seq that goes backwards.

        seq is now stamped by the single drain task, immediately before the
        send, so wire order and seq order are the same by construction.
        """
        with self.lock:
            self.pending.append((mtype, payload))
        if self.loop is None:
            return
        asyncio.run_coroutine_threadsafe(self._drain(), self.loop)

    async def _drain(self):
        if self.draining:
            return                      # single-flight; the running task will see it
        self.draining = True
        try:
            while True:
                with self.lock:
                    if not self.pending:
                        return
                    mtype, payload = self.pending.popleft()
                    self.seq += 1
                    msg = {"type": mtype, "seq": self.seq, "payload": payload}
                    if mtype == "case_loaded":
                        self.history = []
                    if mtype in ("case_loaded", "sim_started", "hypotheses_ready",
                                 "fleet_ready", "state_change"):
                        self.history.append(msg)
                        del self.history[:-32]
                await self._send(msg)
        finally:
            self.draining = False

    def _legacy_emit(self, mtype, payload):
        msg = self.envelope(mtype, payload)
        # Trajectories and fields are large and stale the moment they land; only
        # keep the small state-setting messages for a late joiner.
        with self.lock:
            if mtype == "case_loaded":
                # A new run invalidates the old one. Without this, history grows
                # across rehearsals and a client connecting before the third run
                # is replayed the first two runs' sim_started messages.
                self.history = []
            if mtype in ("case_loaded", "sim_started", "hypotheses_ready",
                         "fleet_ready", "state_change"):
                self.history.append(msg)
                del self.history[:-32]
        if self.loop is None:
            return
        asyncio.run_coroutine_threadsafe(self._send(msg), self.loop)


# Seconds between report-card fields. Fast enough not to stall the pitch,
# slow enough that the stagger reads as extraction rather than a stutter.
FIELD_STAGGER_S = 0.35

hub = Hub()
pipeline = None
CONFIG = {"total_runs": 12000, "n_hypotheses": 20, "use_fleet": True}


def load_case():
    return settings_load_case()


def _boot_fleet():
    global pipeline
    pipeline = Pipeline(emit=hub.emit_threadsafe, n_sandboxes=MAX_SANDBOXES)
    t0 = time.perf_counter()
    try:
        sbs, errors = pipeline.acquire_fleet()
    except Exception as e:
        print("fleet acquire failed: {}".format(e))
        hub.emit_threadsafe("log", {"error": "fleet unavailable: {}".format(e)})
        return
    print("fleet: {} sandboxes ready in {:.2f}s ({} failed)".format(
        len(sbs), time.perf_counter() - t0, len(errors)))
    hub.emit_threadsafe("fleet_ready", {"n_sandboxes": len(sbs),
                                        "n_failed": len(errors)})
    # The model work is ~17 s and must not sit on the critical path.
    try:
        pipeline.prepare(load_case(), total_runs=CONFIG["total_runs"],
                         n_hypotheses=CONFIG["n_hypotheses"])
    except Exception as e:
        print("prepare failed, run() will fall back inline: {}".format(e))


@app.get("/health")
def health():
    return {"ok": True, "state": hub.state, "clients": len(hub.clients),
            "sandboxes": len(pipeline.sandboxes) if pipeline else 0,
            "prepared": bool(pipeline and pipeline._prepared)}


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    hub.clients.add(ws)

    # CONTRACT.md section 8: the frontend builds the ISRID ring, the IPP marker
    # and every camera framing out of `case_loaded`. Emitting it only when a run
    # starts meant that between connecting and pressing run the map had no case
    # at all -- no ring, no marker, no framing -- and the static frame is the
    # milestone the whole build rests on. The case is known at startup, so send
    # it on connect. Skipped if a run has already put one in the history, which
    # is replayed just below.
    if not any(m.get("type") == "case_loaded" for m in hub.history):
        try:
            await ws.send_text(json.dumps(hub.envelope("case_loaded", load_case())))
        except Exception as e:
            print("case_loaded on connect failed: {}".format(e))

    for msg in hub.history:
        await ws.send_text(json.dumps(msg))
    await ws.send_text(json.dumps(hub.envelope("state_change",
                                               {"state": hub.state})))
    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except Exception:
                continue
            await handle(msg)
    except WebSocketDisconnect:
        pass
    finally:
        hub.clients.discard(ws)


# --- intake and validation ---------------------------------------------------
# The pipeline produces five of the seven states. It has nothing to say about
# `intake` (a phone call) or `validation` (six historical cases scored offline),
# so without these the demo could not be driven end to end from the socket: the
# frontend sat on an empty transcript with BEGIN SEARCH disabled, and the
# validation card had no numbers.
#
# INTAKE is the recorded transcript replayed at speaking pace. That is not a
# shortcut around the live Web Speech path -- CONTRACT.md section 8 requires
# exactly this as the mandatory fallback ("a key that types a pre-written
# transcript at speaking pace"), because a hackathon venue at 5pm is loud. When
# the live extraction exists it emits the same two message types and nothing
# downstream changes.
#
# Word groups rather than one word at a time: real recognition arrives in
# bursts, and the whole pitch is 90 seconds, so the call has to be over in
# about six of them. Mirrors TRANSCRIPT_* in frontend/lib/config.ts.
TRANSCRIPT_WORDS_PER_TICK = 2
TRANSCRIPT_TICK_S = 0.15

_scripted_task = None


def _read_json(path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


async def _play_intake(source="fallback"):
    """Stream the recorded call, then the REAL fields it yields.

    `source` is carried into case_loaded so the UI can distinguish a recorded
    replay from a live microphone. Recorded audio with a live extraction is
    entirely honest; presenting it as a live call is not.
    """
    try:
        transcript = (MOCKS / "transcript.txt").read_text(encoding="utf-8").strip()
    except Exception:
        print("intake: mocks/transcript.txt missing; nothing to replay")
        return
    words = transcript.split()
    ticks = (len(words) + TRANSCRIPT_WORDS_PER_TICK - 1) // TRANSCRIPT_WORDS_PER_TICK

    # THE EXTRACTION IS REAL. This previously read mocks/extraction.json and
    # streamed it on a timer, which is a canned card pretending to be a live
    # extraction -- the one thing in this demo a judge can catch by asking to
    # speak into the microphone themselves.
    #
    # The model call runs CONCURRENTLY with the transcript replay. It takes
    # about two seconds against a call that takes six to speak, so it lands
    # well before the fields are due and Person A's choreography is unchanged:
    # word groups at TRANSCRIPT_TICK_S, fields starting partway through.
    #
    # On any failure extract() returns the committed mock tagged
    # source="fallback", so the demo continues and nothing claims to be live
    # that is not.
    import extract as extractor
    # Started, NOT awaited. Awaiting here delayed the first transcript frame by
    # the length of the model call and pushed the fields to the very END of the
    # call -- measured +6.10s, against a design where they resolve partway
    # through. The transcript takes about six seconds to speak and the call
    # about two to extract, so kicking it off here and collecting it when the
    # first field is due hides it completely.
    extract_task = asyncio.create_task(
        asyncio.to_thread(extractor.extract, transcript))
    # Fields resolve one at a time, and resolution STARTS PARTWAY THROUGH the
    # call rather than after it. A real streaming extraction does not wait for
    # the caller to stop talking, and a report that sits empty for the whole
    # call gives the presenter nothing to point at.
    spoken = ticks * TRANSCRIPT_TICK_S
    extraction = None
    steps = []
    every = 0.25          # replaced once the real step count is known

    async def collect():
        """Await the extraction once, the first time a field is due."""
        nonlocal extraction, steps, every
        if extraction is not None:
            return
        extraction, err = await extract_task
        if err:
            hub.emit_threadsafe("log", {"step": "extraction", "error": err})
        if source != "live":
            extraction["source"] = source
        built = [
            {"subject": {"name": (extraction.get("subject") or {}).get("name")}},
            {"subject": extraction.get("subject")},
            {"last_known": extraction.get("last_known")},
            {"assessment": extraction.get("assessment"),
             "confidence": extraction.get("confidence")},
        ]
        steps = [b for b in built if any(v for v in b.values())]
        # Pacing depends on how many fields actually resolved, which is only
        # known now. Computing it before collect() used len([]) and every step
        # would have fired in the same tick.
        every = (spoken * 0.5 + 0.7) / max(1, len(steps))

    first_step = spoken * 0.5

    elapsed = 0.0
    next_step = 0
    for i in range(ticks):
        upto = min(len(words), (i + 1) * TRANSCRIPT_WORDS_PER_TICK)
        hub.emit_threadsafe("transcript_partial", {
            "text": " ".join(words[:upto]),
            "is_final": upto >= len(words)})
        await asyncio.sleep(TRANSCRIPT_TICK_S)
        elapsed += TRANSCRIPT_TICK_S
        if elapsed >= first_step:
            await collect()
        while (next_step < len(steps)
               and elapsed >= first_step + next_step * every):
            hub.emit_threadsafe("extraction_update", steps[next_step])
            next_step += 1

    # Anything the loop did not reach (a very short transcript).
    await collect()
    for step in steps[next_step:]:
        hub.emit_threadsafe("extraction_update", step)
        await asyncio.sleep(every)

    # The pipeline needs ipp, ring_radius_m and elapsed at the top level.
    case = dict(extraction)
    last = extraction.get("last_known") or {}
    if last.get("ipp"):
        case["ipp"] = last["ipp"]
        case["ring_radius_m"] = (extraction.get("assessment") or {}).get(
            "ring_radius_m")
        case["last_contact_s_ago"] = int(last.get("elapsed_min") or 72) * 60
        base = settings_load_case() or {}
        case.setdefault("bounds", base.get("bounds"))
        hub.emit_threadsafe("case_loaded", case)


def _emit_validation():
    """The ring baseline is real and measured; our score is not, yet.

    data/baseline.json holds the ring model scored over the six validation
    cases. `our_score` stays None until someone runs the field through the same
    harness -- the frontend renders that as "pending" rather than inventing a
    number, which is the whole point of reporting honestly whichever way it
    falls.
    """
    base = _read_json(DATA / "baseline.json", {}) or {}
    try:
        val = base["runs"]["derived (holdout)"]["validation"]
    except Exception:
        print("validation: data/baseline.json missing the holdout run")
        return
    hub.emit_threadsafe("validation_result", {
        "n_cases": val.get("n", 6),
        "our_score": None,
        "ring_baseline": round(val.get("mean_R", 0.761), 3),
        "ci95": val.get("ci95"),
        "per_case": val.get("per_case"),
    })


def _start_scripted(state):
    """Kick off whatever a state needs, cancelling the previous one.

    Cancelling matters: advancing early must not leave an intake replay firing
    transcript frames into a state that has moved on.
    """
    global _scripted_task
    if _scripted_task and not _scripted_task.done():
        _scripted_task.cancel()
        _scripted_task = None
    if state == "intake":
        _scripted_task = asyncio.create_task(_play_intake())
    elif state == "validation":
        _emit_validation()


async def handle(msg):
    t = msg.get("type")
    payload = msg.get("payload") or {}

    if t == "state_change":
        state = payload.get("state")
        if state in STATES:
            hub.state = state
            hub.emit_threadsafe("state_change", {"state": state})
            _start_scripted(state)

    elif t == "replay_transcript":
        _start_scripted("intake")

    elif t == "run":
        if pipeline is None:
            hub.emit_threadsafe("log", {"error": "fleet not ready"})
            return
        threading.Thread(target=_run_pipeline, args=(payload,),
                         daemon=True).start()

    elif t == "evidence":
        if pipeline:
            threading.Thread(target=pipeline._emit_evidence, args=(payload,),
                             daemon=True).start()

    elif t == "replay_transcript":
        # The T key, and the mandatory fallback. Person A's wsSource sends this
        # and the server ignored it, so in live mode the intake screen produced
        # nothing at all. Replays the committed transcript at speaking pace and
        # runs a REAL extraction on it -- recorded audio, live extraction, and
        # the payload says source="fallback" so nothing can present it as a
        # live call.
        _start_scripted("intake")

    elif t == "transcript_partial":
        # Interim words are relayed so every client sees the same call as it is
        # spoken. Only the FINAL transcript is worth an extraction call.
        hub.emit_threadsafe("transcript_partial",
                            {"text": payload.get("text", ""),
                             "is_final": bool(payload.get("is_final"))})
        if payload.get("is_final"):
            threading.Thread(target=_run_extraction,
                             args=(payload.get("text", ""),),
                             daemon=True).start()

    elif t == "ping":
        hub.emit_threadsafe("pong", {"t": time.time()})




def _run_extraction(transcript, source="live"):
    """The LIVE MICROPHONE path.

    _play_intake handles the recorded replay with its own choreography; this is
    what a real spoken call goes through. Same extraction, no scripted timing,
    because the words arrive when the caller says them.
    """
    """Transcript -> report card, one field at a time.

    The stagger is deliberate and is the visual payoff of the transcription:
    fields landing one after another read as a call being taken, where a card
    appearing whole reads as a canned screen. FIELD_STAGGER_S is the only knob.
    """
    import extract as extractor

    hub.state = "intake"
    payload, err = extractor.extract(transcript)
    # A recorded replay is never dressed up as a live call.
    if source != "live" and not err:
        payload["source"] = source
    if err:
        # Never fatal: extract() returns the committed mock, tagged
        # source="fallback" so nothing can mistake it for a live extraction.
        hub.emit_threadsafe("log", {"step": "extraction", "error": err})

    for field in extractor.field_sequence(payload):
        hub.emit_threadsafe("extraction_update", field)
        time.sleep(FIELD_STAGGER_S)

    # case_loaded is the full section 8 payload and is what BEGIN SEARCH acts
    # on. The pipeline needs ipp and ring_radius_m at the top level.
    case = dict(payload)
    case["ipp"] = payload["last_known"]["ipp"]
    case["ring_radius_m"] = payload["assessment"]["ring_radius_m"]
    case["last_contact_s_ago"] = int(
        payload["last_known"].get("elapsed_min") or 72) * 60
    case["bounds"] = settings_load_case().get("bounds")
    hub.emit_threadsafe("extraction_complete", {"source": payload.get("source")})
    hub.emit_threadsafe("case_loaded", case)


def _run_pipeline(payload):
    hub.state = "simulating"
    hub.emit_threadsafe("state_change", {"state": "simulating"})
    try:
        pipeline.run(load_case(),
                     total_runs=payload.get("total_runs", CONFIG["total_runs"]),
                     n_hypotheses=payload.get("n_hypotheses",
                                              CONFIG["n_hypotheses"]))
    except Exception as e:
        hub.emit_threadsafe("log", {"error": "run failed: {}".format(e)})
        return
    hub.state = "field_ready"
    hub.emit_threadsafe("state_change", {"state": "field_ready"})

    # run() consumes the prepared hypotheses and scripts. Re-prepare now, or the
    # SECOND rehearsal pays the full ~17 s of model work on the keypress -- and
    # rehearsals are exactly when that is least affordable.
    threading.Thread(target=_prepare_next, daemon=True).start()


def _prepare_next():
    try:
        pipeline.prepare(load_case(), total_runs=CONFIG["total_runs"],
                         n_hypotheses=CONFIG["n_hypotheses"])
    except Exception as e:
        print("re-prepare failed; next run falls back inline: {}".format(e))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--no-fleet", action="store_true",
                    help="serve the socket without touching Daytona")
    ap.add_argument("--total-runs", type=int, default=12000)
    ap.add_argument("--hypotheses", type=int, default=20)
    args = ap.parse_args()

    CONFIG["use_fleet"] = not args.no_fleet
    CONFIG["total_runs"] = args.total_runs
    CONFIG["n_hypotheses"] = args.hypotheses

    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=args.port, log_level="info")


if __name__ == "__main__":
    main()
