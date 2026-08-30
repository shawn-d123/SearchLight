# PERSON B — simulation and Daytona

**Read `CONTRACT.md` first.** You own the thing that makes this a Daytona project rather than a nice animation.

Two pieces: the **worker** that runs inside a sandbox, and the **orchestrator** that manages the fleet and serves the WebSocket. This is the most technically uncertain part of the build. Treat every estimate here as optimistic.

---

## The core idea, and the thing you must protect

Each hypothesis runs in its own sandbox.

**A fixed random walk with different seeds runs twelve thousand times in one Python process in under a second, and a judge will ask why you needed sandboxes at all.** The answer has to be that **a model writes the movement code for each hypothesis**, so you are executing generated code hundreds of times in parallel and isolation is the actual requirement.

If you fall back to a fixed script with parameters, the Daytona story collapses and the project becomes an animation. Protect this above any feature.

**One model call per sandbox, not per simulation.** 200 sandboxes each get one generated script, then each runs it many times with different seeds. Twelve thousand simulations from 200 model calls.

**Plus one call before the fan-out — see "Hypothesis generation" below.** That call is what makes the model's contribution substantial rather than a code generator for short numpy loops.

**Honest caveat if pressed:** the architecture needs ephemeral isolated compute at scale, not this specific vendor. Say so rather than overclaiming.

---

## FIRST TASK — the probe, before anything else

`prep/daytona_probe.py` exists but **has never run against a live API.** Expect a call-signature fix. Do this before writing any worker code, because its output changes your plan.

1. Build the snapshot: `Image.debianSlim('3.12').pipInstall('numpy')`, with `data/*.npy` and `data/meta.json` uploaded to `/data/`. The arrays are 33.7 MB, inside budget.
2. Create 50 sandboxes cold, in parallel. Time to first successful command.
3. Configure a warm pool, claim 50. Time again.
4. Record the concurrency limit if you hit one.

Write both numbers to `prep/TIMINGS.md` and **tell the team**.

**These two numbers decide fleet size and how long the simulation beat lasts on stage.** If cold start is slow and warm pools help, the demo is warm-pool based and you warm during the team before you. If both are slow, drop to 50 sandboxes running 240 simulations each instead of 200 running 60. The visual is identical and nobody can count sandboxes.

Docs: https://www.daytona.io/docs/en/python-sdk/ and https://www.daytona.io/docs/en/snapshots/

**Never `pip install` at sandbox start.** Bake into the snapshot.

---

## Hypothesis generation — the upgrade that makes OpenAI meaningful

**Do this if you are on schedule by 13:00. Skip it if you are behind.** The fixed-family fallback works and the demo survives without it.

### The problem it solves

A judge can reasonably say you are using a frontier model to write short numpy loops a template could produce, and that the interesting work is the statistics. That is a fair hit and it is worth removing.

### The change

Right now the hypothesis list would come straight from the family weights in `data/priors.json` — route travelling, backtracking, staying put. Those are generic categories that apply to any lost hiker anywhere.

Instead, **one call before the fan-out** receives:

- the subject description and conditions from `mocks/case.json` / the live case
- a **terrain summary of the neighbourhood around the IPP**: ridge to the north, drainage descending south-east, trail junction 400 m west, elevation change over the first 2 km in each direction
- **the cached local knowledge from `data/local_knowledge.json`** — see the Parallel section below

It returns hypotheses **specific to this place and this person**, each tagged with a family from the priors. Then each goes to a sandbox as before, where a second call writes its movement code.

### Why this is worth 40 minutes

The model is now doing something a template genuinely cannot: reading a situation and proposing plausible behaviours grounded in the actual landscape. *"Followed the drainage south-east because it's the path of least resistance from the junction"* is a hypothesis that exists only because a model looked at this terrain.

It is also a better demo beat. Three or four generated hypotheses surface on screen in plain English during the simulation state, and they are site-specific rather than textbook. The reasoning becomes legible instead of hidden inside a code generator.

### The constraint that keeps it defensible

**Family weights still come from `data/priors.json`.** The model proposes variations *within* published categories; it does not invent the statistical structure. That is what keeps the ISRID grounding intact, which is the whole basis of the project. If the model returns a hypothesis you cannot map to a family, drop it.

### What you need to write

`orchestrator/terrain_summary.py` — describe the neighbourhood around a lat/lon from the arrays in `data/`. Bearing, elevation change and trail proximity in eight directions over the first 2 km is enough. Plain English out.

Then one prompt: subject, conditions, terrain summary, the five family names with their weights, and "return N hypotheses as JSON, each with family, description, rationale."

Send at most 6 to the frontend in `sim_started`, highest-weighted first, each with its `source` object.

---

## Local knowledge — the Parallel pass

**Optional. The third thing to cut, after hypothesis generation.** Only Daytona is required for prize eligibility.

### What it adds

You have statistical priors (ISRID: how far) and physical priors (terrain: what's walkable). You have no **local** priors — the things a Pima County search planner knows and a generic model does not. Which drainage people mistakenly descend from Marshall Gulch. Which junctions are genuinely confusing. Which routes look shorter on a map than they are.

That knowledge lives in trip reports, ranger advisories and incident write-ups. Parallel is a research API built for agents that returns evidence-backed results **with citations**, which is exactly the shape you need for a project whose identity is evidence over intuition.

One call retrieves it. Findings feed the hypothesis prompt. Hypotheses carry a `source` object and the frontend shows the attribution.

### CACHE IT. This is not an optimisation.

**Run the Parallel call before kick-off — or at the latest early in the build — and commit the result to `data/local_knowledge.json`. Never call it live during the demo.**

1. **It is a failure point on stage.** A live web call mid-pitch can hang, rate-limit or return nothing, at the exact moment nothing can go wrong.
2. **It is latency in the worst possible place.** The research pass sits *before* the fan-out. A slow call means the map sits still while you talk, and the simulation explosion is the beat that must land the instant you press run.
3. It is the same query every run. Calling it repeatedly wastes budget and changes nothing.

Schema is in `CONTRACT.md` §5. **If the file is missing or empty, hypothesis generation proceeds on terrain and statistics alone and nothing breaks.** Build that path first, then add the file.

Say "local knowledge is cached" in four words if it comes up. Nobody blinks at a cached research pass. They blink at a stalled demo.

### The test for whether it earns its place

You should be able to say in one sentence why the project is better with it: *the hypotheses become locally grounded rather than generically plausible.* If that sentence ever feels strained, drop it. Partner badges nobody can justify read worse than no partner at all.

---

## The worker

Lives in `worker/`. Runs inside the sandbox. **Dependencies: numpy only.**

Terrain is baked in, not downloaded:

```
/data/elevation.npy      float32
/data/slope.npy          float32, degrees
/data/trail_dist.npy     float32, metres to nearest trail
/data/water_dist.npy     float32, metres to nearest watercourse
/data/meta.json          bounds, shape, cell size, row 0 = north
```

No geopandas, no OSMnx, no shapely, no rasterio. They are heavy and they multiply across 200 sandboxes.

Note the trail distance raster derives from the **full 444k-edge network**, not the thinned 14,750-way display set A renders. The workers see more trails than the screen shows, which is correct.

### Input

The hypothesis object from `CONTRACT.md` §4 — including `description` and `rationale`, which go straight into the script-generation prompt. A site-specific description produces better movement code than a generic category name.

### Output

The trajectory batch from `CONTRACT.md` §4. `runs[]`, each with `run_index`, points downsampled to ≤60, `endpoint`, `status`. Plus `generated` on the batch.

### The API you expose to generated code

Give the model a narrow surface and say these are the only functions available:

```python
elevation_at(lat, lon)      -> float
slope_at(lat, lon)          -> float, degrees
dist_to_trail(lat, lon)     -> float, metres
dist_to_water(lat, lon)     -> float, metres
step(lat, lon, bearing, m)  -> (lat, lon)
```

The script's job is to return a list of positions over time. Keep the prompt boring and specific: state the hypothesis, list the API, state the output format, tell it to return only code.

---

## The fallback that saves your demo — build it first, not as a patch

**Generated code will fail sometimes.** Syntax errors, infinite loops, walking off the grid, returning nothing.

- Hard timeout per worker: 10 seconds
- Failures return `{"status": "failed"}` and are counted, not plotted
- **A hand-written template script per family** as a deterministic fallback. When it runs, the batch is marked `"generated": false`

**The demo must be able to run with zero successful generations.** If it cannot, one bad API response kills the pitch.

Say plainly in the demo that some scripts fail. A failure count on screen is credibility, not weakness.

---

## Orchestrator

Lives in `orchestrator/`. FastAPI + WebSocket per `CONTRACT.md` §6.

1. Load the case, emit `case_loaded`
2. Build the hypothesis list from `data/priors.json` — note the priors use a **holdout set** excluding the 6 validation cases, which avoids circularity. Do not swap them for the full-set version
3. Dispatch to the fleet, collect batches
4. Emit `fleet_status` every 500ms, `trajectory_batch` in batches of **max 200 runs per message**
5. Call C's `build_field()` incrementally as batches arrive, emit `field_update` roughly every second with a `progress` value
6. On evidence, call C's `apply_evidence()`, emit `evidence_applied`

**Batch the trajectories.** Twelve thousand individual messages will kill the browser.

**The field accumulates.** Do not wait for all batches and send one update at the end. Streaming partial fields is the visual, and it fills the dead air between "paths flying" and "here is the field".

---

## Validation support — 15:00

C runs the scoring, but it needs the fleet: **6 validation cases at ~50 sandboxes each**. Scoped deliberately so it fits after integration.

All six sit inside the terrain bounding box. Do not let the fleet size for validation balloon; it is a background job while A polishes.

---

## Timeline

| Time | Target |
|---|---|
| 10:30 | Contract lock, 15 min |
| 10:45 | **Probe first.** Fix signatures, get both timings, tell the team |
| 11:15 | Worker skeleton, one hypothesis, running locally without a sandbox |
| 11:45 | Model writes a script, sandbox executes it, batch returns |
| **12:30** | **Ten workers end to end** |
| 13:00 | Scale to target fleet, warm pool configured |
| 13:30 | **Hypothesis generation, if on schedule.** Terrain summary + one call before the fan-out |
| 14:00 | **Parallel pass, if still on schedule.** One call, cached to `data/local_knowledge.json`, committed |
| 14:30 | **Integration — A flips to live** |
| 15:00 | Support C's validation run |
| 16:00 | Tune counts, support |
| 16:20 | **Record the first clean rehearsal as the fallback video** |

**If you are not at ten workers end to end by 12:30, say so.** That is the point where the plan changes, not the point where you work harder. The fallback path is fewer sandboxes with more runs each.

The fallback recording is a capture of the first clean run. It cannot happen before the demo works.

---

## What shows on screen from your work

Only the fleet counter: sandboxes active, simulations complete, failures. That is the visible proof real machines are doing work rather than the browser faking it.

Also worth having ready: **the ability to inspect a live sandbox's filesystem.** If a judge asks whether this is real, showing the generated script and the trajectory file sitting on a machine you can then kill is a better answer than any diagram.
