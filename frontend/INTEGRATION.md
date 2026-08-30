# Integration — frontend ↔ orchestrator

For Person B (orchestrator, WebSocket) and Person C (model, payloads).
**The short version: run `npm run ws` and point your server at what it does.**

```bash
cd frontend
npm run ws          # reference orchestrator on ws://localhost:8000/ws
npm run dev:live    # frontend in live mode, in another terminal
```

That is the whole demo running over a real socket. `scripts/mock-ws-server.mjs`
is a working server that emits exactly the frames this frontend expects, so it
is an executable spec: if your orchestrator drives the frontend the way that one
does, integration is done. Run yours on another port and compare:

```bash
NEXT_PUBLIC_WS_URL=ws://localhost:8001/ws npm run dev:live
```

---

## 1. What the frontend does

- Connects to `NEXT_PUBLIC_WS_URL` (default `ws://localhost:8000/ws`).
- Reconnects on its own with backoff. Killing and restarting the orchestrator
  mid-demo is survivable and does not need a page reload — which matters,
  because a reload loses the demo's current state.
- Logs a warning on a `seq` gap. Gaps in `trajectory_batch` mean paths that will
  never be drawn, so they are worth seeing.

**The frontend drives the script; the orchestrator follows.** On every state
change it sends **up** the socket:

```json
{ "type": "state_change", "payload": { "state": "simulating" } }
```

States, in order: `landing · intake · briefing · simulating · field_ready ·
evidence · validation`.

> **B — this is the one thing to agree out loud.** Both ends currently assume
> the frontend is the driver, because the demo advances on a keypress and the
> presenter owns the pacing. If you want the orchestrator to drive instead, say
> so and I will make `state_change` inbound-authoritative. Do not let this be
> discovered at 14:30.

It also sends `{"type":"replay_transcript"}` when the presenter presses `T`.
Ignore it if you have nothing to replay.

## 2. What the frontend expects

Every frame is the CONTRACT §9 envelope. Nothing else is read.

```json
{ "type": "field_update", "seq": 42, "payload": { } }
```

| type | when | notes |
|---|---|---|
| `case_loaded` | on connect | §8 extraction payload. Send it **unprompted, immediately** — the ring and IPP marker come from it |
| `transcript_partial` | during intake | `{text, is_final}`. `text` is cumulative, not a delta |
| `extraction_update` | during intake | partial §8 payload, merged one level deep |
| `sim_started` | on entering simulating | `{n_planned, hypotheses[]}` — at most 6, highest-weighted |
| `fleet_status` | every 500 ms while running | |
| `trajectory_batch` | while running | `{batches:[...]}`, **max 200 runs per message** |
| `field_update` | repeatedly | send partials; the surface grows rather than appearing |
| `evidence_applied` | after the filter | a field payload plus `evidence` |
| `validation_result` | on entering validation | |

Unknown `type` values are ignored without throwing, so adding a message will not
break the screen — it just will not do anything until I handle it.

## 3. Things that will bite

**`grid` must be exactly `resolution² × 4` bytes of base64 float32**, row-major,
row 0 = NORTH, normalised 0..1. The decoder throws with the byte count if not,
so check the console before assuming the field is broken.

**Send partial fields, not just the final one.** The whole point of §8 is that
the surface accumulates. One `field_update` at the end works but throws away the
best twelve seconds of the demo.

**Do not renormalise to 0..1 on every update.** The field will pulse. Normalise
against a fixed ceiling or a heavily smoothed running maximum.

**Batch the trajectories.** 12,000 individual messages will kill the browser.

**`n_total` / `n_consistent` are read straight onto the screen.** They are the
"12,000 → 808" beat, so they need to be the real counts, including failures.

## 4. Two payload spellings, both accepted

`lib/adapt.ts` reads the CONTRACT spelling first and the mock spelling second,
so **neither of you has to change anything you have already built**:

| | CONTRACT §9 | committed mocks | both work |
|---|---|---|---|
| fleet | `{active, complete, failed, families}` | `{sandboxes_active, hypotheses_completed, runs_completed, runs_failed}` | ✅ |
| evidence | `{lat, lon, t, radius_m, reliability}` | `{location, t_s, radius_m, tolerance_s, description}` | ✅ |

If you emit the contract spelling it wins outright. `families` is optional — the
frontend does not currently render it.

## 5. What I still need

**From B**
- A socket answering on `/ws`, even one that only sends `case_loaded`. That is
  enough to prove the transport before the fleet exists.
- The direction decision in §1.
- Your real `sim_started`, with `description` and `rationale` per hypothesis.
  Until it exists I generate one locally from the terrain arrays — see
  `scripts/make-frontend-mocks.py`. **Nothing in mine is invented, but nothing
  in mine came from your model either.**

**From C**
- `our_score` in `validation_result`. It renders as "pending" until then, on
  purpose — I will not display a number we do not have.
- `sim_started` hypothesis prose, if it is yours rather than B's.
- Optional: `data/local_knowledge.json`. Where a hypothesis carries
  `source.kind: "local"`, the rail already renders `source.label` as an
  attribution line beneath it. That code path is built and currently dark.
- A word on the mock field spilling outside the ring — a bright lobe sits south
  of it, which undercuts "9.8% of the ring's area" visually. Expected to change
  with real terrain-aware sims, but worth confirming before rehearsal.

## 6. Fallback

If the orchestrator is not up, the frontend runs standalone with no flag at all
(`npm run dev`) against the committed mocks. If it dies mid-demo, the reference
server is a drop-in on the same port. **Neither is presented as live** — the
header shows `mock` or `live` and the connection state throughout.
