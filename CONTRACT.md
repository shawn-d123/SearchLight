# SEARCHLIGHT — THE CONTRACT

**Frozen at 10:45. Owned by Person C. Nobody edits this file without asking.**

Two people editing this at 10:45 is the one conflict that would genuinely hurt.

This is §18 of `searchlight-complete_1.md`, with tonight's concrete values filled
in. Where this file and the spec disagree, **this file wins** — it has the real
numbers in it.

---

## Concrete values for this build

Derived tonight. Sources in `data/bbox.json` and `data/priors.json`.

| Thing | Value |
|---|---|
| Region | Santa Catalina Mountains, Arizona, USA |
| Bounds | N 32.576089, S 32.197678, E −110.587766, W −111.069734 |
| Box size | 45.26 × 42.08 km |
| Centre | 32.386883, −110.828750 |
| Terrain cell size | 30 m |
| Ring radius (p95) | **9.55 km** |
| Validation cases | 6 — Arizona53, 58, 80, 85, 89, 90 |

> **Not Yosemite.** The free MapScore subset contains no Yosemite cases — only
> 131 Arizona ones. See `prep/STATUS.md`. Everything downstream is unaffected;
> only the pitch wording changes.

---

## Conventions

- All interface payloads: WGS84, `[lat, lon]`, decimal degrees
- Bounds: `{north, south, east, west}` in degrees
- Grids row-major. `grid[0]` is the **north** edge, `grid[r][0]` the **west** edge
- Times: seconds elapsed since last known point, integers. Not wall clock, not ISO

---

## Trajectory — worker to orchestrator

One sandbox holds one generated script and runs it many times with different
seeds, so a worker returns a **batch**, not a single trajectory.

```json
{
  "hypothesis_id": "h_00184",
  "family": "route_travelling",
  "weight": 0.22,
  "generated": true,
  "runs": [
    {
      "run_index": 0,
      "points": [[32.4404, -110.7911, 0], [32.4451, -110.7860, 300]],
      "endpoint": [32.4512, -110.7688],
      "duration_s": 4320,
      "status": "ok"
    }
  ]
}
```

- `family` ∈ `route_travelling | direction_sampling | backtracking | view_enhancing | staying_put`
- `points` downsampled to **≤60 per run**, each `[lat, lon, t_seconds]`
- `status` is `ok` or `failed`. Failures are **counted, not plotted**
- `generated` is `false` when the deterministic fallback template ran instead of
  model-written code. This is what feeds the failure count on screen

---

## Field — orchestrator to frontend

```json
{
  "bounds": {"north": 32.576089, "south": 32.197678,
             "east": -110.587766, "west": -111.069734},
  "resolution": 256,
  "grid": "<base64 float32, 256*256, row-major, normalised 0..1>",
  "progress": 0.62,
  "zones": [{"name": "Ridge north", "pct": 31.2, "centroid": [32.4501, -110.7602]}],
  "n_total": 12482,
  "n_consistent": 12482,
  "ring_radius_m": 9546,
  "field_area_pct": 21
}
```

Sent repeatedly as the field accumulates. `progress` tells Person A whether this
is partial or final.

### `field_area_pct` — the headline number

Define it precisely, because it is the largest text in the rail:

> the area of the smallest region containing **50%** of the probability mass, as
> a percentage of the **ring's** area.

Sort cells by probability descending, accumulate until you reach 0.5, count the
cells, multiply by cell area, divide by ring area.

**Not** "cells above a threshold" — that is arbitrary and changes with
normalisation. The same definition is applied to the ring itself, which gives an
honest like-for-like comparison rather than a rhetorical one.

Implemented in `model/field.py::field_area_pct`.

### Two grids — do not confuse them

| | Display grid | Scoring grid |
|---|---|---|
| Size | 256 × 256 | 5001 × 5001 |
| Goes to | Frontend over WebSocket | Nowhere, written to disk |
| Purpose | The visual | The benchmark number |

The scoring grid is 25 million floats. **It never touches the WebSocket.** Same
function, different resolution argument.

Scoring grid geometry: 5 m cells, IPP at the exact centre → a 25.005 × 25.005 km
window. Row 0 is north.

---

## WebSocket envelope

`ws://localhost:8000/ws`, every message `{ "type": ..., "seq": n, "payload": {} }`.

| type | when |
|---|---|
| `case_loaded` | on connect |
| `sim_started` | run pressed |
| `fleet_status` | every 500 ms while running |
| `trajectory_batch` | batched, **max 200 per message** |
| `field_update` | repeatedly, as the field accumulates |
| `evidence_applied` | after filter |
| `validation_result` | validation state |
| `state_change` | on keypress |

**Batch the trajectories.** Twelve thousand individual messages will kill the
browser.

---

## Repo

```
searchlight/
  frontend/        A owns
  worker/          B owns   (runs inside a sandbox)
  orchestrator/    B owns   (fleet control, WS server)
  model/           C owns   (aggregation, evidence, scoring)
  mocks/           C owns   (committed before Sunday)
  data/            terrain arrays, trail graph, cases
  prep/            throwaway scripts used tonight
```

**Everyone works on `main`. No feature branches.**

- `git pull --rebase` then push, every 20–30 minutes
- No pull requests, no reviews, no branch protection
- **Break `main`? Fix forward.** Nobody reverts, nobody blocks
- **Nobody edits another person's directory**
- Shared files — root `README`, `.gitignore`, `CONTRACT.md`, anything in
  `data/` — are owned by **C**. Anyone needing a change asks
- `data/` is committed, `.npy` arrays included — except that on this machine the
  arrays exceed comfortable git sizes, so see `prep/STATUS.md` for how they are
  regenerated

**At 16:00, once the demo works, tag it or cut `demo-safe` and leave it alone.**

---

## Mock files (committed tonight, `mocks/`)

Person A builds against these until the 14:30 integration point, then flips
`DATA_SOURCE` from `'mock'` to `'live'`.

| File | Matches |
|---|---|
| `mocks/case.json` | a `case_loaded` payload |
| `mocks/trajectories.json` | 200 worker batches, the shape above |
| `mocks/field.json` | a `field_update`, `progress: 1.0` |
| `mocks/field_partial.json` | a `field_update`, `progress: 0.35`, blurrier |
| `mocks/field_collapsed.json` | post-evidence, `n_consistent` ≈ ⅓ of `n_total` |
| `mocks/fleet_status.json` | ~20 `fleet_status` frames, counts climbing |

Every mock is generated by `prep/make_mocks.py` and validated against this
contract by `prep/validate_mocks.py`. **If you change this file, re-run both.**
