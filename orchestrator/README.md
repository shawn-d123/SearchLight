# orchestrator/ — Person B

Fleet control, aggregation calls, and the WebSocket server. Runs on the laptop,
not in a sandbox, so it may use whatever libraries it likes.

## Responsibilities

1. **Fleet** — claim sandboxes from a warm pool, dispatch one hypothesis each,
   collect batches, retry or fall back on failure.
2. **Model calls** — one call per sandbox, **not per simulation**. 200 sandboxes
   each get one generated script, then each runs it 60 times with different
   seeds. 12,000 simulations from 200 model calls.
3. **WebSocket** — `ws://localhost:8000/ws`, envelope
   `{ "type": ..., "seq": n, "payload": {} }`. Message types in `../CONTRACT.md`.
4. **Aggregation** — call into `model/` (Person C). Do not reimplement it.

## Things that will bite

- **Batch the trajectories.** `trajectory_batch`, max 200 per message. Twelve
  thousand individual messages will kill the browser.
- **The scoring grid never touches the WebSocket.** 5001 × 5001 is 25 million
  floats. Display grid is 256 × 256. Same function, different resolution.
- **Stream `field_update` while the fleet is still working**, roughly once a
  second with a `progress` value. The field must accumulate on screen, not
  appear finished. That beat fills the dead air between paths and field.
- **Normalise against a fixed ceiling or a heavily smoothed running maximum.**
  Renormalising to 0..1 on every update makes the field pulse and flicker.

## Timings

`prep/daytona_probe.py` measures 50 cold vs 50 warm sandboxes and writes
`prep/TIMINGS.md`. **Run it before deciding the worker count.** It has never
been executed against a live API — expect to fix a call signature.
