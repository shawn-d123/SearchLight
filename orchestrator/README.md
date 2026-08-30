# orchestrator/ — Person B

Fleet control, model calls, aggregation calls, and the WebSocket server. Runs on
the laptop, so it may use whatever libraries it likes.

**Read `../prep/TIMINGS.md` first.** It has the measured numbers and the three
traps that cost real time.

## Files

| file | what it does |
|---|---|
| `settings.py` | paths, snapshot name, `.env` loading, the fleet ceiling |
| `fleet.py` | Daytona: snapshot, acquire, dispatch, fallback, reap |
| `codegen.py` | one model call per sandbox writes that hypothesis's movement code |
| `terrain_summary.py` | plain-English description of the ground around a point |
| `hypotheses.py` | one call before the fan-out proposes site-specific hypotheses |
| `local_knowledge.py` | the cached Parallel research pass — **run once, commit** |
| `pipeline.py` | the whole run, headless — no browser needed |
| `server.py` | FastAPI + WebSocket, `ws://localhost:8000/ws` |

## Run it

```bash
python orchestrator/server.py                 # the real thing
python orchestrator/pipeline.py --hypotheses 20 --total-runs 12000
python orchestrator/pipeline.py --no-model    # the zero-generation floor
python worker/run_local.py                    # no sandbox, no keys
python orchestrator/fleet.py --reap           # delete orphaned sandboxes
```

`--reap` matters. The account quota is **shared and small**; a Ctrl-C skips the
shutdown hook and leaves ten sandboxes holding the whole team's budget.

## Measured, end to end

| | |
|---|---|
| Fleet ceiling | **10 sandboxes** (account caps total CPU at 10, memory at 10 GiB) |
| Acquire 10 sandboxes | 2.0–2.2 s |
| Hypothesis generation (1 call) | ~9–13 s |
| Codegen (20 calls, parallel) | ~4 s |
| 12,000 sims over 10 sandboxes | **3.5 s**, 12,000/12,000 ok, 20/20 from generated code |
| First trajectories after keypress | **~1.2 s** |

## The two things not to break

**1. The model writes the movement code.** A fixed random walk with different
seeds would run twelve thousand times in one process in under a second, and the
sandboxes would be decoration. `codegen.py` is what makes isolation the actual
requirement. One call per *sandbox*, never per simulation.

**2. `prepare()` runs before the operator presses run.** Hypothesis generation
and codegen are ~17 s against a 3.5 s fan-out. On the keypress that is seventeen
seconds of still map with the beat that has to land arriving last.
`server.py` calls `prepare()` at startup; `run()` then puts paths up in ~1.2 s.

## Things that will bite

- **Concurrent execs on ONE sandbox collide** — bare `Failed to execute command`,
  no detail. Each sandbox owns a lane and works it sequentially
  (`fleet.run_all`). Parallelism comes from the number of sandboxes.
- **Deleting a sandbox does not free quota immediately.** `acquire()` retries
  through the lag; without that, two rehearsals back to back fail.
- **Batch the trajectories.** `trajectory_batch`, max 200 runs per message.
- **The scoring grid never touches the WebSocket.** 5001 × 5001 is 25 million
  floats. Display is 256 × 256, same function, different resolution argument.
- **Normalise against a stable ceiling.** Renormalising every update makes the
  field pulse. `model.normalise_for_display` takes a `ceiling`.

## Waiting on Person C

`model.build_field` and `model.apply_evidence` still raise `NotImplementedError`.
The pipeline catches that, says so once, and carries on — trajectories and fleet
status stream fine, `field_update` and `evidence_applied` simply do not fire yet.
When those land, nothing here needs changing.
