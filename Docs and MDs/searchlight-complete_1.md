# SEARCHLIGHT

**Don't search everywhere. Search where they could be.**

Daytona HackSprint, Entrepreneurs First HQ, London. Sunday 30 August 2026.
Doors close 12:00. Kick-off 10:30. Submissions 17:00. Team of three.

---

# PART ONE — THE PROJECT

## 1. What it is

A person goes missing. You know where they were last seen and roughly what kind of person they are.

Rescue teams today draw distance rings around that point, because published statistics say a hiker is usually found within a certain distance. A ring is a circle on a map, and people do not walk in circles. They follow paths, avoid steep ground, head downhill when tired, and stop at water.

Searchlight takes the same published statistics and runs thousands of simulated people across the real terrain. Each one is a different guess: this one kept going, this one turned back, this one twisted an ankle after twenty minutes. Where lots of them end up, the map goes bright.

Then a witness reports a red jacket by the eastern stream at 18:40. Every simulation that was nowhere near that stream at that time is discarded. Most of the map goes dark and the search area shrinks.

**Closing line:** *A ring cannot respond to evidence.*

## 2. What is actually being claimed

The field is not empty and pretending otherwise is fatal.

Koester's International Search and Rescue Incident Database holds over 145,000 searches across 30-plus lost-person categories, each with published distance-from-IPP quantiles. Teams already build ring models from it. Agent-based lost-person modelling exists in the literature too.

So the claim is **not** "we predict where missing people are". It is:

> Ring models apply published statistics as circles. We apply the same statistics as terrain-aware simulations, and update them against incoming evidence.

Incremental, defensible, and it survives a judge who knows search and rescue. **State it unprompted.** Being caught unaware of the prior art would be fatal; citing it first makes you the person who did the reading.

## 3. The benchmark

Published scores on 376 real historical cases. Random maps score 0, perfect maps score 1.

| Model | Score |
|---|---|
| ISRID distance ring — what teams use today | 0.78 (95% CI 0.74–0.82) |
| Watershed | 0.61 |
| Combined distance + watershed — best published | 0.805 (95% CI 0.77–0.84) |

Source: Sava, Twardy, Koester & Sonwalkar, *Evaluating Lost Person Behavior Models*, Transactions in GIS.
https://sarbayes.org/wp-content/uploads/2015/02/Evaluating-Lost-Person-Behavior-Models-revised-submission.pdf

**This is the spine of the project.** You are not showing a nicer heatmap. You are entering an existing benchmark with a number. Nobody else in the room will have a sentence like that.

## 4. The three moments that carry the demo

Everything else is support. If time collapses, these survive.

**One — the ring against the field.** The traditional ring, kilometres across, with your field inside it taking a fifth of the area and hugging the valleys. One image, no explanation needed.

**Two — the simulation explosion.** Thousands of paths spreading from the last known point across real terrain, accumulating into a density field as they arrive.

**Three — the evidence collapse.** A witness report lands, inconsistent simulations vanish, most of the field goes dark. The ring stays exactly the same size.

## 5. Location: Yosemite

The free validation cases are Arizona, New York and Yosemite. Yosemite has 199, it is genuinely mountainous so terrain matters, and one pipeline then serves both the demo and the validation.

Running the demo on UK terrain while validating on US cases would mean two pipelines and a validation disconnected from what is on screen.

---

# PART TWO — HOW IT WORKS

## 6. Pipeline

```
LAST KNOWN POINT
      │
      ├──▶ hypothesis 1 ──▶ sandbox ──▶ trajectory
      ├──▶ hypothesis 2 ──▶ sandbox ──▶ trajectory
      ├──▶     ...      ──▶   ...   ──▶     ...
      └──▶ hypothesis N ──▶ sandbox ──▶ trajectory
                                          │
                                          ▼
                          incremental kernel density
                                          │
                                          ▼
                              PROBABILITY FIELD
                                          │
                            new evidence  │
                                     ─────┤
                                          ▼
                              discard inconsistent
                                 renormalise
                                          │
                                          ▼
                               COLLAPSED FIELD
```

**Priors.** ISRID distance quantiles for the subject category, and hypothesis families weighted by published frequency: route travelling, direction sampling, backtracking, view enhancing, staying put.

**Per hypothesis.** A model writes a bespoke movement script for that hypothesis against the terrain and trail graph. The sandbox executes the generated code and returns a trajectory.

**Aggregation.** Kernel density over trajectory endpoints, weighted by family prior. **Incremental** — see §8.

**Evidence.** A witness report is a spatial and temporal constraint. Discard trajectories not near that location at that time, renormalise, redraw.

## 7. Why each hypothesis needs a sandbox

This is where the Daytona story lives or dies.

A fixed random walk with different seeds runs twelve thousand times in one Python process in under a second, and a judge will ask why you needed sandboxes at all. The answer has to be that **a model writes the movement code**, so you are executing generated code hundreds of times in parallel and isolation is the actual requirement.

If you fall back to a fixed script with parameters, the Daytona story collapses. Protect this.

**One model call per sandbox, not per simulation.** 200 sandboxes each get one generated script, then each runs it 60 times with different seeds. 12,000 simulations from 200 model calls.

**Honest caveat if pressed:** the architecture needs ephemeral isolated compute at scale, not this specific vendor. Say so rather than overclaiming.

## 8. The field accumulates, it does not appear

Do not render the finished field and fade it in. The field should build itself out of the simulations as they arrive.

Person B streams trajectories in batches while the fleet is still working, so the field starts forming at simulation 200 and sharpens until 12,000. It is not an effect, it is just rendering data as it arrives.

- C keeps a running accumulator grid and adds each batch's Gaussian splats
- C emits `field_update` roughly every second with the running state, plus a `progress` value
- A interpolates between the previous grid and the new one over ~800ms rather than swapping

**Why it matters:** the field starts as a vague smear covering most of the ring and sharpens into distinct zones. That is literally what is happening statistically, and it is visible. It also fills the dead air between "paths flying" and "here is the field".

**Normalise against a fixed ceiling or a heavily smoothed running maximum.** Renormalising to 0..1 on every update makes the field pulse and flicker.

## 9. Costs and timing

Daytona bills $0.0504/vCPU-hour and $0.0162/GiB-hour, per second. $200 free compute on signup, plus $100 event credit and $50 Codex credit.

At 1 vCPU / 2 GiB, about $0.083 per sandbox-hour:

| Scenario | Cost |
|---|---|
| 200 sandboxes alive 3 minutes | ~$0.83 |
| 200 sandboxes alive 10 minutes | ~$2.80 |
| 200 warm in a pool for 30 min pre-demo | ~$8.30 |
| 40 development runs at 3 min | ~$33 |

You will not run out of credit. Test freely.

**Tokens:** ~1,000 in and ~600 out per hypothesis, 200 hypotheses ≈ 320k tokens per full run. A couple of dollars. Generate the scripts beforehand and cache them for the demo.

**Speed:** an independent benchmark measured Daytona creating a sandbox in ~742ms and resuming in ~1254ms, where "ready" means a command actually executed. That is sequential. The number that matters is 200 in parallel, which depends on your account concurrency limit. **Measure it Saturday.**

---

# PART THREE — WHAT IT LOOKS LIKE

## 10. One screen with states

Not seven screens. Roughly 70% map, 30% side rail. The layout never changes.

| State | On screen |
|---|---|
| BRIEFING | Terrain, trails, last known point, ring already drawn |
| SIMULATING | Paths spreading, field accumulating, fleet counter |
| FIELD READY | Field settled, two zones labelled |
| EVIDENCE | Witness marker, field collapses, counts drop |
| VALIDATION | Real case result against the 0.78 benchmark |

Progression is scripted and advances on a single key. The pitch never depends on finding a button.

## 11. Visual direction

**Reference world: a topographic survey sheet.** USGS quad sheets, OS Explorer maps, avalanche bulletins, incident command boards. Not a sci-fi command centre. The default instinct is dark navy plus electric cyan and it reads as generated.

**Dark, and warm dark rather than blue dark.** Charcoal with an olive cast, linework in bone rather than pure white. Reads as chart paper in low light instead of a hacker terminal.

Dark is also practical: you present on a projector in a dimmed room, and the probability field is a luminous overlay that needs a dark ground. On white it becomes a muddy stain.

**The probability field is the only saturated thing on screen.** Terrain muted, trails bone, ring a thin dashed bone line, panels greyscale. When the field appears it is the only colour in the room.

**Field ramp: a single hue with an opacity ramp**, transparent through amber to hot coral. Not a rainbow, not viridis. Multi-hue ramps fight the hillshade underneath and turn to mud on 3D terrain, and a single hue reads as "more of one thing", which is what probability is.

Amber for evidence. One bright colour for teams. Nothing else coloured, ever.

**Type.** IBM Plex Mono for all data and labels. Archivo or Archivo Narrow for headings. Avoid Inter — it is the default and reads as such. Eyebrow labels in small caps at ~0.2em letter spacing.

**Signature element: chart furniture.** Corner registration ticks on panels instead of full borders. Scale bar, north arrow. The ring annotated like a survey feature, thin dashed line with a leader and a small label reading `ISRID RING · 95th PCTL · 5.8 km`. **State which quantile the ring is.** An unlabelled circle invites "where did that number come from?"

**Terrain.** Contour lines rather than heavy hillshade, every fifth line brighter — standard cartographic practice, reads as intentional, and keeps trails legible. Trails drawn with a dark casing under a bright line so they hold up over busy ground.

**Vertical exaggeration around 3x.** Past roughly 4x, terrain stops reading as landscape and starts reading as a video game. Say "vertical exaggeration 3x" once in the pitch. Nobody objects to a stated exaggeration; they object to an unstated one.

**Motion.** The paths are the only fast-moving thing. Panels do not animate in. Numbers do not count up. State transitions 200–400ms, camera moves 1200ms. That is the entire motion vocabulary. Restraint is what makes the simulation explosion land.

## 12. Keep the screen quiet

The instinct is to fill the rail with telemetry. Resist it. Seven numbers total:

- Subject name and last contact
- Sandboxes active — the fleet counter, and the only thing on screen proving real machines are working
- Simulation count
- Consistent count
- Top zone percentage
- **Field area as a percentage of the ring** — this is the whole argument in one number and should be the largest text in the rail by some margin

**Cut:** hypothesis family bars (interesting to you, meaningless in 90 seconds), the conditions block (never affects anything visible), zone list beyond two rows, the coordinate readout if the screen feels busy.

Everything else moves into the pitch, where you say it once and it lands better than a permanent label nobody reads.

## 13. Camera and navigation

**2.5D, not free 3D.** Fixed pitch 55–60°.

- Pan and zoom **enabled**
- Rotation **disabled** — `dragRotate.disable()` and `touchZoomRotate.disableRotation()`. A wrong bearing hides the bright zone behind a ridge
- One key resets the camera to the scripted position for the current state
- One key drops pitch to ~15° so hidden ground becomes visible, and returns on a second press

**During the 90 seconds you never touch the mouse.** Panning exists for one situation: a judge asks to see somewhere specific. Then the fact it responds live is itself evidence the map is not a video. Reset before continuing.

**Rehearsal check:** confirm the bright zone is visible from the default camera in every state. If it is not, move the camera rather than flattening the terrain.

## 14. What would make it look generated

Cut on sight: glassmorphism, frosted panels, neon glow, gradient text, border radius above ~4px with drop shadows, purple-to-blue gradients, centred hero layouts, Inter.

**No emoji as icons.** The original concept document was full of 🚨 👤 🌡 📍. They are the fastest way to make a serious tool look like a template. Thin line icons or text labels only.

**The test:** screenshot it and ask whether it looks like it came from a rescue coordination centre or from a landing page. If a panel has a border radius, a shadow and a gradient at once, it came from a landing page.

---

# PART FOUR — BUILDING IT

## 15. Stack

```
FRONTEND                 ORCHESTRATOR              DAYTONA FLEET

Next.js + Tailwind  ◀─WS─▶  FastAPI      ──SDK──▶  200+ sandboxes
deck.gl                     fleet control            numpy only
MapLibre GL                 aggregation              terrain arrays baked in
                            evidence filter          runs generated script
                            scoring harness          returns trajectory
```

**Map layers, back to front**

| Layer | What | Notes |
|---|---|---|
| Basemap | MapLibre dark style | CARTO dark is the fast option |
| Terrain | Terrain-RGB heightfield | Cache tiles locally. Do not trust venue wifi at 16:50 |
| Contours | Dim bone lines | Every fifth brighter |
| Trails | deck.gl `PathLayer` | Dark casing under bright line. Same OSM data the workers' trail-distance raster is derived from |
| Ring | Circle, thin dashed bone | Naive by design, annotated with a leader label |
| Field | **MapLibre image source**, not a deck layer | See below |
| Paths | `TripsLayer` | Float 20–50m above ground |
| Markers | `ScatterplotLayer` | IPP, witness, teams |

**Draping — get this right.** deck.gl layers over MapLibre terrain do **not** automatically follow the ground; they render in their own pass and float flat. Two options:

1. **Reliable:** make the field a MapLibre image source. MapLibre drapes its own raster and fill layers onto terrain natively. C sends a grid, A paints it to a canvas, the canvas becomes the image source.
2. `TerrainExtension` from `@deck.gl/extensions` drapes deck layers onto the terrain mesh. Works, but another thing to debug on the day.

Do **not** drape the animated paths. Let them float above the ground — looks better and avoids z-fighting where lines flicker in and out of hillsides.

## 16. Data

| Need | Source |
|---|---|
| Validation cases | https://github.com/ctwardy/mapscore — ~400 ISRID cases, AZ/NY/Yosemite free to distribute |
| Elevation | USGS 3DEP via https://opentopography.org (~10m). Terrain-RGB tiles for render: https://registry.opendata.aws/terrain-tiles/ |
| Trails | OSMnx, `network_type='all'`, clipped to bbox |
| Hydrology | OSM waterway tags — people stop at water and follow drainages |
| Priors | Koester, *Lost Person Behavior* (2008), or derived from the case coordinates |
| Basemap | MapLibre https://maplibre.org, CARTO dark style |

**Google Maps was considered and rejected.** Its 3D tiles are photorealistic buildings in cities; in wilderness its terrain is no better than USGS 3DEP. You cannot easily drape a custom surface on it, styling is constrained so the survey-sheet look becomes hard, it needs a billing-enabled key, and its footpath coverage in US wilderness is worse than OSM's.

Pre-process into flat numpy arrays: elevation, slope, trail distance, water distance. **These get baked into the sandbox snapshot.** No geospatial libraries inside the workers.

**The trap: validation needs terrain for every case, not just the demo area.** The 199 Yosemite cases are scattered across the park, each with a different IPP. You cannot score a case against a terrain window centred somewhere else.

Pick one of these tonight, because it decides what you clip:

1. **Filter the case list to incidents inside a single bounding box.** Fewer cases, one terrain array, everything stays simple. Accept you may end up with 5–8 rather than 20.
2. **Make terrain a runtime parameter** — one array per case, loaded by path. More flexible, more moving parts, and the snapshot gets larger.

Option 1 unless the filtered case count drops below about five.

## 17. Dependencies

**Inside each sandbox:** `numpy` only, plus the baked terrain arrays. No geopandas, no OSMnx, no shapely, no rasterio — heavy, and they multiply across 200 sandboxes.

**Orchestrator:** fastapi, uvicorn, websockets, daytona, osmnx, geopandas, rasterio, scipy, openai.

**Frontend:** next, react, tailwindcss, deck.gl, @deck.gl/geo-layers, @deck.gl/extensions, maplibre-gl, react-map-gl.

**Never `pip install` at sandbox start.** Bake into a snapshot:

```python
image = Image.debianSlim('3.12').pipInstall('numpy')
daytona.snapshot.create(CreateSnapshotParams(name='searchlight-worker', image=image))
```

Then use **warm pools** — pre-created running sandboxes claimed instantly rather than provisioned. This is the answer to demo cold start. https://www.daytona.io/docs/en/snapshots/

## 18. The contract — frozen at 10:45

### Conventions

- All interface payloads: WGS84, `[lat, lon]`, decimal degrees
- Bounds: `{north, south, east, west}` in degrees
- Grids row-major. `grid[0]` is the **north** edge, `grid[r][0]` the **west** edge
- Times: seconds elapsed since last known point, integers. Not wall clock, not ISO

### Trajectory — worker to orchestrator

One sandbox holds one generated script and runs it many times with different seeds, so a worker returns a **batch**, not a single trajectory:

```json
{
  "hypothesis_id": "h_00184",
  "family": "route_travelling",
  "weight": 0.22,
  "generated": true,
  "runs": [
    {
      "run_index": 0,
      "points": [[37.7345, -119.5821, 0], [37.7351, -119.5810, 300]],
      "endpoint": [37.7412, -119.5688],
      "duration_s": 4320,
      "status": "ok"
    }
  ]
}
```

`family` ∈ `route_travelling | direction_sampling | backtracking | view_enhancing | staying_put`.
`points` downsampled to ≤60 per run. `status` is `ok` or `failed`; failures are counted, not plotted.
`generated` is false when the deterministic fallback template ran instead of model-written code — this is what feeds the failure count on screen.

### Field — orchestrator to frontend

```json
{
  "bounds": {"north": 37.80, "south": 37.68, "east": -119.48, "west": -119.68},
  "resolution": 256,
  "grid": "<base64 float32, 256*256, row-major, normalised 0..1>",
  "progress": 0.62,
  "zones": [{"name": "Ridge north", "pct": 31.2, "centroid": [37.7501, -119.5602]}],
  "n_total": 12482,
  "n_consistent": 12482,
  "ring_radius_m": 5800,
  "field_area_pct": 21
}
```

Sent repeatedly as the field accumulates. `progress` tells A whether this is partial or final.

**Define `field_area_pct` precisely, because it is the headline number.** It is:

> the area of the smallest region containing 50% of the probability mass, as a percentage of the ring's area.

Not "cells above a threshold", which is arbitrary and changes with normalisation. Sort cells by probability descending, accumulate until you reach 0.5, count the cells, multiply by cell area, divide by ring area. Same definition applies to the ring itself, which gives you an honest like-for-like comparison rather than a rhetorical one.

### Two grids — do not confuse them

| | Display grid | Scoring grid |
|---|---|---|
| Size | 256 × 256 | 5001 × 5001 |
| Goes to | Frontend over WebSocket | Nowhere, written to disk |
| Purpose | The visual | The benchmark number |

The scoring grid is 25 million floats. It never touches the WebSocket. Same function, different resolution argument.

### WebSocket envelope

`ws://localhost:8000/ws`, every message `{ "type": ..., "seq": n, "payload": {} }`.

| type | when |
|---|---|
| `case_loaded` | on connect |
| `sim_started` | run pressed |
| `fleet_status` | every 500ms while running |
| `trajectory_batch` | batched, max 200 per message |
| `field_update` | repeatedly, as the field accumulates |
| `evidence_applied` | after filter |
| `validation_result` | validation state |
| `state_change` | on keypress |

**Batch the trajectories.** Twelve thousand individual messages will kill the browser.

### Repo

```
searchlight/
  frontend/        A owns
  worker/          B owns   (runs inside a sandbox)
  orchestrator/    B owns   (fleet control, WS server)
  model/           C owns   (aggregation, evidence, scoring)
  mocks/           C owns   (committed before Sunday)
  data/            terrain arrays, trail graph, cases
```

**Everyone works on `main`. No feature branches.**

The directories are disjoint, so two people almost never touch the same file, which is the only thing that causes conflicts. Long-lived branches would buy isolation you don't need and cost you the continuous integration you do.

- `git pull --rebase` then push, every 20–30 minutes
- No pull requests, no reviews, no branch protection. That is ceremony for a six-hour build
- **Break `main`? Fix forward.** Nobody reverts, nobody blocks. A's broken component does not stop B's Python from running
- **Nobody edits another person's directory**
- Shared files — root `README`, `.gitignore`, `CONTRACT.md`, anything in `data/` — are owned by C. Anyone needing a change asks. Two people editing `CONTRACT.md` at 10:45 is the one conflict that would genuinely hurt
- `data/` is committed, .npy arrays included. B needs them for the snapshot, A needs the bbox and trails

**At 16:00, once the demo works, tag it or cut `demo-safe` and leave it alone.** If a late change breaks something during rehearsal, a known-good state is one command away. That is the only branch worth having.

This also changes what 14:30 means. Since everyone is already on `main`, integration is flipping A's `DATA_SOURCE` flag from `'mock'` to `'live'` and finding out what breaks. Minutes, not an hour of conflict resolution.

## 19. Validation

The scripted ending — PERSON LOCATED, tick, applause — proves nothing. You chose where they were and you chose where the model pointed. A sharp judge sees it immediately.

**The metric**, ~20 lines:

```python
# grid: 5001 x 5001, 5m pixels, IPP at centre → 25 x 25 km
p = grid[find_row][find_col]
n = (grid > p).sum()
m = (grid == p).sum()
N = grid.size
r = (n + m / 2) / N
R = (0.5 - r) / 0.5          # worst −1, best +1, random 0
```

**The sanity check that matters most.** Rebuild the ring model yourself — concentric circles at the 25/50/75/95% distances, probability divided by area, remaining 5% beyond the outer ring — and score it on the same cases. **You should land near 0.78.** If you do, the harness is correct and every later number is trustworthy. If not, suspect grid orientation, projection, or the metric.

**Scope it realistically.** Twenty cases at 200 sandboxes each is 4,000 sandbox runs plus twenty 5001×5001 density passes, starting half an hour after integration. That does not fit.

**Run five cases at 50 sandboxes each.** Say "five real historical cases" in the pitch. It is honest, it is enough to make the claim, and it finishes inside the window. If it runs faster than expected, add cases.

All five cases must sit inside your terrain bounding box — see §16.

**Report honestly whichever way it falls.** A model that scores 0.6 and says so is worth more than one that scores nothing and shows a tick. Beat 0.78 and you have a headline. Miss it and you have a finding, plus a much better answer to the inevitable question than silence.

---

# PART FIVE — THE TEAM

## 20. Roles

### Person A — Frontend
Everything on screen. Terrain, trails, ring, animated paths, field rendering, state machine, camera, side rail.

**Full time from 10:30. Touches nothing else all day.** The largest single piece and it is the demo. The classic failure is borrowing this person for backend work at 14:00 when the backend looks scarier. Don't.

### Person B — Simulation and Daytona
The worker that runs in the sandbox: hypothesis in, model writes movement script, sandbox executes, trajectory out. Then fleet orchestration, warm pools, scaling 10 → 200. Plus the orchestrator and WebSocket server.

Most technically uncertain and most likely to eat time. **Ten workers end to end by 12:30.** If not, tell the team — that is the point where the plan changes rather than where you work harder.

Their only on-screen output is the fleet counter, which is the visible proof that real machines are doing work.

### Person C — Aggregation, evidence, validation (Shawn)
Trajectories into a probability grid. Incremental KDE, zones, the evidence filter, the scoring run. Produces the number in the pitch. Owns the mocks. Owns the pitch.

**Why you take this one.** You did the design thinking, so you know the whole system and will be interrupted constantly. This is where knowing the design matters most and interruption costs least.

**You are also the blocker for everyone else.** A cannot start without your mocks.

### The worker's fallback — build it day one

Generated code will sometimes fail: syntax errors, infinite loops, walking off the grid, returning nothing.

- Hard timeout per worker, 10 seconds
- Failures return `{"status": "failed"}`, counted not plotted
- **A hand-written template script per family** as a deterministic fallback

The demo must be able to run with zero successful generations. A failure count on screen is credibility, not weakness.

## 21. Rules

1. **Contract lock starts at kick-off, frozen by 10:45.** All three, fifteen minutes, written down. Get it wrong and you spend 15:00–16:00 gluing instead of polishing.
2. **Mocks first, live second.** Every component works against mock data before real data. A should have paths animating from `mocks/trajectories.json` within the first hour.
3. **14:30 is a hard integration point.** Everything connects end to end, however ugly. First integration at 16:00 means no demo.
4. Nobody edits another person's directory.
5. Commit and push hourly.

## 22. Build order

| Time | A — Frontend | B — Simulation | C — Aggregation |
|---|---|---|---|
| 10:30 | **Contract lock, all three, 15 min** | | |
| 10:45 | Terrain + trails render, flat | Worker skeleton, local | Mocks loaded, KDE working |
| 11:30 | **Ring, IPP marker — static frame done** | Model writes script, sandbox runs it | Grid renders, encoding correct |
| 12:30 | TripsLayer animating mocks | **Ten workers end to end** | Zones, field area % |
| 13:30 | Field layer, incremental updates | Scale to 200, warm pool | Evidence filter |
| **14:30** | **HARD INTEGRATION — flip `DATA_SOURCE` to live, end to end however ugly** | | |
| 15:00 | State machine, camera keys | Support integration | **Validation run** |
| 16:00 | Polish, contrast, projector test | Support, tune counts | Number into the pitch |
| 16:20 | **First clean rehearsal — B records it immediately as the fallback** | | |
| 16:30 | **Rehearse ×2 more on the presenting laptop. Submit.** | | |

The fallback recording cannot happen before the demo works. It is a capture of the first clean run, not a separate task.

**The static frame by 11:30 matters.** Terrain, trails, marker, ring, flat, no animation. If that is on screen you have a skeleton and everything after is additive. Chase the 3D camera first and you can be four hours in with nothing to show.

**Cut in this order if behind:** camera choreography → team deployment → 3D terrain (fall back to 2D) → zone detail panels. **Never cut validation.**

**2D is not a failure state.** A flat dark map with trails, a ring, and a field that follows the valleys makes every argument the demo needs. Terrain makes it more beautiful, not more convincing. Build flat with pitch 0 and raise the camera once everything works — that should be changing one number, not a rewrite.

---

# PART SIX — BEFORE SUNDAY

## 23. Person C — one evening, not two days

There is no Friday and no Saturday daytime. Everything below happens tonight, so it is ordered by what breaks if it is missing.

**Must exist before 10:30 tomorrow**

1. **The mocks.** Person A sits idle without them. A crude random walk is fine — they only need the right *shape*: `mocks/case.json`, `mocks/trajectories.json` (200, batch shape per §18), `mocks/field.json`, `mocks/field_collapsed.json`, `mocks/fleet_status.json`.
2. **The data.** Cases extracted, bounding box chosen, terrain and trails clipped and pre-processed to numpy arrays. Nothing can be built tomorrow without this and it cannot be done on venue wifi.
3. **The repo**, scaffolded, with the contract committed.

**Should exist, can slip to Sunday's quiet stretch**

4. `model/score.py` and the 0.78 ring reproduction. Ideally tonight, because it validates the harness. If it slips, do it while the fleet is scaling around 13:30.
5. `model/priors.json`. **Derive the quantiles from the case coordinates rather than chasing Koester's book tonight** — it is faster, it is defensible, and they are the same cases you score against.

**Cut entirely if the night runs out:** anything not on this list.

## 24. Person A

- Next.js + Tailwind + deck.gl + MapLibre scaffold running
- Terrain rendering for the Yosemite bounds, **tiles cached locally**
- **The deck.gl / MapLibre camera integration working** — https://deck.gl/docs/get-started/using-with-map. Expect to lose an hour if new to it. Saturday, not Sunday
- A dummy TripsLayer animating fake paths. **Verify 12,000 paths at your actual point counts.** If it stutters, render a visible subset of 2,000 — the visual is identical and nobody can count them
- Test one trail line on a steep slope. If it clings to the ground, draping works
- Pitch locked, drag-rotate disabled

## 25. Person B

- Daytona account, API key, SDK installed
- A snapshot built with numpy and dummy data arrays
- **Time 50 sandboxes cold, then 50 from a warm pool. Write both numbers down.** They decide worker count and how long the simulation beat lasts on stage. Check the account concurrency cap while you are there
- Know how to kill a sandbox and inspect its filesystem — inspecting a live worker is a good answer to "is this real"

All of this is learning the platform and building scaffolding, which the rules explicitly allow. The core project gets built on the day.

---

# PART SEVEN — THE PITCH

## 26. Ninety seconds

**0:00** Terrain, last known point, ring already drawn.
*"A hiker went missing 72 minutes ago. This ring is how search areas are drawn today. Published statistics, applied as a circle."*

**0:12** *"The statistics are good. The circle is the problem. People follow trails, go downhill, stop at water."* Run.

**0:18** Paths explode, field begins accumulating, fleet counter climbing.
*"Every sandbox takes one hypothesis from the published strategy categories, writes its own movement model, and runs it against the real landscape."*

**0:35** Field settles, hugging the valleys.
*"Same statistics. A fifth of the area."*

**0:50** Witness report. Apply. Field collapses.
*"Twelve thousand simulations. Three thousand eight hundred are consistent with that sighting."* Ring unchanged.

**1:05** *"The ring didn't move, because a ring can't respond to evidence."*

**1:12** Validation.
*"This is a real historical case. Known last seen point, known find location. The published benchmark for the ring model is 0.78. We scored X on the same cases."*

**1:25** Hold on ring and field side by side.
*"Don't search everywhere. Search where they could be."*

## 27. The prior-art answer, rehearsed until automatic

> Search and rescue already uses probability models. Koester's ISRID holds over 145,000 cases and teams draw distance rings from it. The published benchmark for that ring model is 0.78, and the best published model is 0.805. We're not replacing it. We're running the same statistics through terrain instead of a circle.

## 28. Demo integrity

- Warm the fleet before presenting, during the team before you
- Cache model outputs and **say so in four words**. Nobody blinks at that. They blink at a suspiciously fast live call
- Put slow stages under your talking. Nothing happens in silence
- Record a fallback and label it as a fallback if you use it
- **Never present cached output as live**
- Plug the laptop in — on battery the GPU throttles and the frame rate halves
- Test on an external display at venue resolution. Projectors crush dark greys and wash out thin strokes; push contrast well past what looks right on the laptop

## 29. Cut from the original concept

**The invented 39% vs 82% figure.** Either compute it honestly from your own field — straightforward once the grid exists, it is just probability mass inside searched cells — or drop it. An invented benchmark is exactly what a judge asks about.

**Worker cards** unless they stream from real sandboxes. Decorative telemetry reads as fake, and a judge who suspects one number suspects all of them.

**Screens 4 and 6 as separate screens.** Deployment is a state. Mission summary is a closing overlay.

**Free camera rotation.**

## 30. Known weaknesses — state these first

- The behaviour model is not validated at the scale ISRID is. §19 is the mitigation, and its result gets reported whichever way it falls
- Terrain cost functions are hand-tuned, not fitted
- One subject category, one search area, one weather condition
- The evidence filter treats witness reports as reliable. Real ones often are not
- **This is decision support that surfaces hypotheses, not a probability oracle.** A system directing rescuers informs a human decision. It never replaces one
