# CONTRACT

**Everyone reads this. Frozen by 10:45. Nothing changes after that without all three agreeing out loud.**

This exists so three people can build alone and connect at 14:30 without a rewrite.

---

## 1. Ground truth from last night

| | Value |
|---|---|
| Region | Santa Catalina Mountains, Arizona |
| Box | 45.3 × 42.1 km |
| Validation cases | 6 |
| Usable cases (harness verification) | 109 of 131 |
| Ring radius (derived p95) | **9.55 km** |
| Ring baseline on the 6 validation cases | **R = 0.761** |
| Ring baseline on all 109 | R = 0.711 (CI 0.643–0.779) |
| Terrain arrays | 33.7 MB, four .npy in `data/` |
| Display trails | 14,750 ways, 3.4 MB |

**Quote 0.761, never 0.78.** Same model, same six cases, same metric. The published 0.78 came from 376 different cases and is not comparable.

Exact bounds, from `data/bbox.json`:
`N 32.576089, S 32.197678, E −110.587766, W −111.069734`

---

## 2. Repo and workflow

```
searchlight/
  frontend/        A owns
  worker/          B owns   (runs inside a sandbox)
  orchestrator/    B owns   (fleet control, WS server)
  model/           C owns   (aggregation, evidence, scoring)
  mocks/           C owns   (committed, validated)
  data/            terrain arrays, trails, cases - committed
  prep/            last night's scripts, all re-runnable
```

**Everyone on `main`. No feature branches.** The directories are disjoint so conflicts are near-impossible, and continuous integration matters more than isolation over six hours.

- `git pull --rebase` then push, every 20–30 minutes
- No PRs, no reviews, no branch protection
- **Break main? Fix forward.** Nobody reverts, nobody blocks
- **Nobody edits another person's directory**
- Shared files (root `README`, `.gitignore`, `CONTRACT.md`, `data/`) are owned by C. Need a change? Ask
- At 16:00, once it works, tag it. A known-good state one command away

---

## 3. Conventions

- All payloads: WGS84, `[lat, lon]`, decimal degrees
- Bounds: `{north, south, east, west}` in degrees
- Grids row-major. `grid[0]` is the **north** edge, `grid[r][0]` the **west** edge
- Times: **seconds elapsed since the last known point**, integers. Not wall clock, not ISO
- Distances in metres unless the field name says otherwise

---

## 4. Hypothesis — orchestrator to worker

Hypotheses are **generated for this incident**, not read from a fixed list. A single model call receives the subject description, the conditions, and a terrain summary of the neighbourhood around the IPP, and proposes site-specific behaviours. Family weights still come from `data/priors.json`, so the model varies within published categories rather than inventing the statistical structure.

```json
{
  "hypothesis_id": "h_00184",
  "family": "direction_sampling",
  "description": "Followed the drainage south-east from the junction, path of least resistance on tiring legs",
  "rationale": "Drainage descends 340 m over 2 km from the IPP; the alternative north-west route gains elevation immediately",
  "source": {
    "kind": "local",
    "label": "Pima County SAR incident report, 2019",
    "url": "https://..."
  },
  "weight": 0.22,
  "start": [32.4102, -110.7314],
  "duration_s": 4320,
  "n_runs": 60,
  "seed_base": 184000
}
```

`description` and `rationale` are plain English and **surface on screen** during the simulation state — see §7. `weight` comes from the family prior, not from the model.

`source` is optional. `kind` is `terrain` (derived from the arrays), `statistical` (from ISRID priors), or `local` (from the Parallel research pass, §5). When `kind` is `local`, `label` and `url` come from Parallel's citations and are shown as a one-line attribution under the description.

### The three grounding layers

| Layer | Source | Answers |
|---|---|---|
| Statistical | ISRID priors, `data/priors.json` | How far do people travel |
| Physical | Terrain arrays | What ground is walkable |
| **Local** | **Parallel research pass** | **Where do people go wrong *here*** |

The third is what a Pima County search planner knows and a generic model does not: which drainage people mistakenly descend, which junctions are confusing, which routes look shorter than they are.

---

## 5. Local knowledge — the Parallel pass

**Optional. Third thing to cut.** Only Daytona is required for prize eligibility, so this is pure upside.

One Parallel research call retrieves documented incidents, ranger advisories and trip reports for the Santa Catalinas, with citations. Findings feed the hypothesis prompt alongside the terrain summary.

### Caching is mandatory, not an optimisation

**Run this before the event and commit the result to `data/local_knowledge.json`.** Never call Parallel live during the demo.

Three reasons, and the first two are the important ones:

1. **It is a failure point on stage.** A live web call in the middle of the pitch can hang, rate-limit or return nothing, at the exact moment nothing can go wrong.
2. **It is latency in the worst place.** The research pass sits *before* the fan-out, so a slow call means the map sits still while you talk. The simulation explosion is the beat that has to land instantly when you press run.
3. It is the same query every run, so calling it repeatedly wastes budget and changes nothing.

```json
{
  "generated_at": "2026-08-30T09:14:00Z",
  "region": "Santa Catalina Mountains, AZ",
  "findings": [
    {
      "claim": "Subjects descending from Marshall Gulch frequently follow the wrong drainage south-east",
      "label": "Pima County SAR incident report, 2019",
      "url": "https://...",
      "confidence": 0.8
    }
  ]
}
```

**Say "local knowledge is cached" in four words** if it comes up. Nobody blinks at a cached research pass. They blink at a suspiciously fast live web call, or at a demo that stalls waiting for one.

If the file is missing or empty, hypothesis generation proceeds on terrain and statistics alone. **Nothing breaks.**

---

## 6. Trajectory batch — worker to orchestrator

One sandbox holds one generated script and runs it many times with different seeds, so a worker returns a **batch**.

```json
{
  "hypothesis_id": "h_00184",
  "family": "route_travelling",
  "weight": 0.22,
  "generated": true,
  "runs": [
    {
      "run_index": 0,
      "points": [[32.4102, -110.7314, 0], [32.4118, -110.7290, 300]],
      "endpoint": [32.4201, -110.7002],
      "duration_s": 4320,
      "status": "ok"
    }
  ]
}
```

- `family` ∈ `route_travelling | direction_sampling | backtracking | view_enhancing | staying_put`
- `points` downsampled to **≤60 per run**
- `status` is `ok` or `failed`. Failures are counted, not plotted
- `generated` is `false` when the deterministic fallback template ran instead of model-written code. This feeds the failure count on screen

---

## 7. Field update — orchestrator to frontend

```json
{
  "bounds": {"north": 32.576089, "south": 32.197678,
             "east": -110.587766, "west": -111.069734},
  "resolution": 256,
  "grid": "<base64 float32, 256*256, row-major, normalised 0..1>",
  "progress": 0.62,
  "zones": [{"name": "Ridge north", "pct": 31.2, "centroid": [32.4501, -110.7602]}],
  "n_total": 12000,
  "n_consistent": 12000,
  "ring_radius_m": 9550,
  "field_area_pct": 26.4
}
```

**Sent repeatedly as the field accumulates.** `progress` tells A whether this is partial or final.

### `field_area_pct` — the headline number, defined precisely

> The area of the smallest region containing 50% of the probability mass, as a percentage of the ring's area.

Sort cells descending, accumulate to 0.5, count cells, multiply by cell area, divide by ring area. **Not** "cells above a threshold", which is arbitrary and shifts with normalisation.

The same definition is applied to the ring, so the comparison is like-for-like rather than rhetorical. Implemented in `model/field.py`.

**Do not rehearse a number for this.** The mocks show 26.4% from a random walk. The real figure comes from terrain-aware simulation and will differ.

### Hypothesis surfacing

Three or four `description` strings from §4 are shown during the simulation state, cycling. They are site-specific rather than textbook categories, which is what makes the model's contribution legible instead of hidden inside a code generator.

Sent as part of `sim_started`: `{n_planned, hypotheses: [{hypothesis_id, family, description, source}]}` — at most 6, the highest-weighted.

Where `source.kind` is `local`, show `source.label` as a small muted line under the description. That attribution is the visible payoff of the research pass and it fits a project whose identity is evidence over intuition.

### Two grids — do not confuse them

| | Display grid | Scoring grid |
|---|---|---|
| Size | 256 × 256 | 5001 × 5001 |
| Goes to | Frontend over WebSocket | Nowhere. Written to disk |
| Purpose | The visual | The benchmark number |
| Owner | C produces, A renders | C only |

The scoring grid is 25 million floats. It never touches the WebSocket. Same function, different resolution argument.

---

## 8. Intake — landing, call, report

The demo opens before the map. Three states, all in the same Next.js app sharing the same canvas, panels and palette. **Not a separate application.**

### `landing`

**Purely decorative. No map, no terrain, no live data.** Dark screen, a searchlight silhouette on the left casting a beam to the right, and a panel that intercepts it with a subtle illuminated edge where the light lands.

**A searchlight, not a lighthouse.** Same animation, same collision effect — but a lighthouse warns ships away from hazards and this product finds people in them. Costs nothing to get right and someone will notice the mismatch.

Constraints so it does not read as a different application:

- **One moving element.** The beam. Nothing else animates
- **Warm light, not white** — same amber family as the probability field shown later
- **CSS or SVG, not canvas.** Costs nothing to render
- **Test the collision glow on a projector.** Soft glows that look right on a laptop often vanish entirely when projected

The panel holds the title, one line of subtitle, and one button: **REPORT A MISSING PERSON**.

### `intake` — the call

Live transcription via the **browser Web Speech API**, not Whisper. It transcribes word by word with no upload and no round trip, which is the whole effect. Whisper requires record, upload, wait, which kills it.

**The transcript is texture. The structured extraction is the hero.** A hackathon venue at 5pm is loud and recognition will mangle words. Build so that does not matter: an imperfect transcript still yields a correct report because a model pulls the fields out of it. If it garbles a word and the card still populates correctly, say so — that reads as robustness.

**Mandatory fallback:** a key that types a pre-written transcript at speaking pace. If the mic fails, say "the room's too loud, here's the recorded version" and move on.

### `intake` — the report

Header shows `INCIDENT SL-2084` and keeps it for the rest of the demo. Three panels, same corner registration ticks as the rail so it does not look like a different application:

| Panel | Fields |
|---|---|
| SUBJECT | name, age, category, experience, clothing |
| LAST KNOWN | trailhead, time, elapsed, coordinates |
| ASSESSMENT | ring radius from priors, hypothesis families pending, conditions |

**Fields populate one at a time as extraction returns**, not all at once. That staggering is the visual payoff of the transcription.

One button: **BEGIN SEARCH** → `briefing`.

### Extraction payload

```json
{
  "transcript": "...",
  "subject": {"name": "Alex Morgan", "age": 24, "category": "hiker",
              "experience": "experienced", "clothing": "red jacket", "injuries": "none reported"},
  "last_known": {"place": "Marshall Gulch trailhead", "time": "06:10",
                 "elapsed_min": 72, "ipp": [32.4102, -110.7314]},
  "assessment": {"ring_radius_m": 9550, "conditions": "clear, 18°C"},
  "confidence": {"ipp": 0.9, "time": 0.95, "category": 1.0}
}
```

This becomes the `case_loaded` payload. `ring_radius_m` comes from `data/priors.json` keyed on `category` — **derived, not extracted.** The model reads the call; the statistics come from ISRID.

### The demo script — every detail feeds something visible

> *"I need to report a missing person. My friend Alex Morgan went hiking on the Marshall Gulch trail in the Catalinas this morning. He's twenty-four, experienced hiker, been out there before. He was going to call me when he reached the top but I haven't heard from him since about ten past six. His phone's going straight to voicemail so I think the battery's dead. He was wearing a red jacket and he had no injuries when he set off."*

| Said | Drives |
|---|---|
| Marshall Gulch trail | the IPP |
| ten past six | elapsed time → simulation duration |
| experienced hiker | ISRID category → priors and ring radius |
| no injuries | lowers the staying-put family weight |
| phone battery dead | explains the absence of GPS before anyone asks |
| **red jacket** | **sets up the witness sighting at 0:50 so the payoff lands** |

Nothing in that script is decoration. If a detail does not drive something visible, cut it.

### Ownership and cut order

**Person C builds this, 13:30–14:30**, after the evidence filter. It needs no deck.gl and no terrain, so it does not compete for Person A's time. The extraction is a model call, which is C's territory, and C owns the pitch so the narrative framing is theirs.

**First thing cut if the validation run is at risk.** Validation is worth more than the opening.

---

## 9. WebSocket

`ws://localhost:8000/ws`. Every message:

```json
{ "type": "field_update", "seq": 42, "payload": { } }
```

| type | payload | when |
|---|---|---|
| `transcript_partial` | `{text, is_final}` | during the call, from the browser |
| `extraction_update` | partial extraction payload | as fields resolve, one at a time |
| `case_loaded` | full extraction payload, §8 | BEGIN SEARCH pressed |
| `sim_started` | `{n_planned, hypotheses: [...]}` | run pressed |
| `fleet_status` | `{active, complete, failed, families: {name: count}}` | every 500ms while running |
| `trajectory_batch` | `{batches: [...]}` | **batched, max 200 runs per message** |
| `field_update` | field object | repeatedly, as the field accumulates |
| `evidence_applied` | field object + `{evidence: {lat, lon, t, radius_m, reliability}}` | after filter |
| `validation_result` | `{n_cases: 6, our_score, ring_baseline: 0.761}` | validation state |
| `state_change` | `{state}` | on keypress |

**Batch the trajectories.** Twelve thousand individual messages will kill the browser.

States, in order: `landing`, `intake`, `briefing`, `simulating`, `field_ready`, `evidence`, `validation`.

---

## 10. Python function boundary

The orchestrator calls C's code directly:

```python
build_field(trajectory_batches, bounds, resolution, accumulator=None) -> (grid, accumulator)
apply_evidence(trajectory_batches, evidence)                          -> (filtered, field_dict)
field_area_pct(grid, cell_area_m2, ring_radius_m)                     -> float
```

---

## 11. Mocks

In `mocks/`, validated against this file:

`case.json`, `trajectories.json`, `field.json`, `field_partial.json`, `field_collapsed.json`, `fleet_status.json`

Add `mocks/transcript.txt` (the demo script above) and `mocks/extraction.json` (the §8 payload) so intake can be built and rehearsed without a microphone.

**They ship at 12 runs per batch (2,400 runs), not 60.** A 12,000-run JSON is ~12 MB. For frame-rate testing regenerate at full scale:

```bash
python prep/make_mocks.py --stress
```

**Person A must stress-test against the 60-run file, not the committed one.**

Every component works against mocks before it works against live data. A `DATA_SOURCE` flag switches `'mock'` / `'live'`. If that flag exists, 14:30 is a config change instead of a debugging session.

---

## 12. The five rules

1. **Contract frozen by 10:45.** All three, fifteen minutes, out loud.
2. **Mocks first, live second.** Nobody ever waits on anyone.
3. **14:30 is hard.** Flip `DATA_SOURCE` to live and find out what breaks. However ugly. First integration at 16:00 means no demo.
4. **Nobody edits another person's directory.**
5. **Commit and push hourly.**
