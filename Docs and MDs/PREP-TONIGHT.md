# SEARCHLIGHT — tonight's prep

**For Claude Code.** Saturday evening, 29 August 2026. Hackathon is tomorrow, kick-off 10:30.

Read `searchlight-complete.md` for full project context. This file is the executable task list.

**Constraint: one evening, not two days.** Tasks are ordered so that if you run out of time, what is missing is the least damaging thing. Do not reorder. Do not skip ahead to the interesting parts.

---

## What Shawn must do manually (do these first, they block Claude Code)

Claude Code cannot create accounts or accept terms. Five minutes:

1. **Daytona account** at https://www.daytona.io — get an API key, put it in `.env` as `DAYTONA_API_KEY`. Note the concurrent sandbox limit shown on the dashboard.
2. **OpenTopography account** at https://opentopography.org — free, needed for the API key to pull USGS 3DEP elevation. Put it in `.env` as `OPENTOPO_API_KEY`.
3. **OpenAI API key** in `.env` as `OPENAI_API_KEY`.
4. **A GitHub repo**, empty, and give Claude Code the remote URL.

Everything below is Claude Code's job.

---

## TASK 0 — Repo scaffold

Create this structure and commit:

```
searchlight/
  frontend/          Person A
  worker/            Person B  (runs inside a sandbox)
  orchestrator/      Person B  (fleet control, WS server)
  model/             Person C  (aggregation, evidence, scoring)
  mocks/             Person C  (committed tonight)
  data/              terrain arrays, trail graph, cases
  prep/              throwaway scripts used tonight
  CONTRACT.md        copy of §18 from searchlight-complete.md
  .env.example
  .gitignore         (.env, data/*.npy, node_modules, __pycache__)
```

Branches: `main`, `fe`, `sim`, `model`. Push all four.

Python 3.12, a venv, and `prep/requirements.txt` with: `numpy scipy osmnx geopandas rasterio shapely pandas requests pillow`.

---

## TASK 1 — Cases and bounding box

**This decides everything downstream. Do it before touching terrain.**

```bash
git clone https://github.com/ctwardy/mapscore prep/mapscore
```

Explore `case_in/` and `database/`. The repo holds roughly 400 ISRID cases; Arizona, New York and Yosemite are free to distribute. Structure may not match expectations, so inspect before parsing.

Extract to `data/cases.csv` with columns:

```
case_id, ipp_lat, ipp_lon, find_lat, find_lon, category, region
```

Then:

1. Filter to Yosemite.
2. Filter to hiker-like categories if the field exists. If it does not, keep everything and note it.
3. **Find the tightest bounding box containing at least 5 cases**, with 15 km padding around every IPP so the 25 × 25 km scoring window fits. Cluster the IPPs and take the densest cluster rather than the extent of all cases, or the box will cover the whole park.
4. Write `data/bbox.json`: `{north, south, east, west, n_cases, case_ids: [...]}`.
5. Print how many cases made the cut.

**If fewer than 5 cases fit any reasonable box, stop and say so.** The fallback is a larger box with coarser terrain, and that is a decision for Shawn, not for you.

---

## TASK 2 — Priors from the cases

Do **not** chase Koester's book tonight. Derive empirically instead — faster and defensible, since these are the same cases being scored against.

From `data/cases.csv`, compute great-circle IPP-to-find distances and write `data/priors.json`:

```json
{
  "source": "derived from MapScore ISRID subset, n=<count>",
  "distance_km": {"p25": 0.0, "p50": 0.0, "p75": 0.0, "p95": 0.0},
  "ring_radius_km": 0.0,
  "families": {
    "route_travelling": 0.41,
    "direction_sampling": 0.29,
    "backtracking": 0.17,
    "view_enhancing": 0.08,
    "staying_put": 0.05
  },
  "families_source": "PLACEHOLDER — ISRID strategy frequencies, not yet sourced"
}
```

`ring_radius_km` is the p95 distance. That is what the on-screen ring represents and it must be labelled as such.

**Flag the family weights clearly as placeholder.** They are invented until someone sources them, and the document says every number carries a citation.

---

## TASK 3 — Terrain and trails

Using `data/bbox.json`:

**Elevation.** USGS 3DEP via the OpenTopography API, roughly 10 m. Save the raw GeoTIFF to `data/dem.tif`.

**Trails.** OSMnx, `network_type='all'`, clipped to the bbox. Save the graph to `data/trails.graphml` and the edge geometry to `data/trails.geojson` for the frontend.

**Water.** OSM `waterway` features to `data/water.geojson`.

**Pre-process to flat numpy arrays** on a common grid, and be explicit about the grid in `data/meta.json` (bounds, shape, cell size in metres, row 0 = north):

```
data/elevation.npy      float32
data/slope.npy          float32, degrees
data/trail_dist.npy     float32, metres to nearest trail
data/water_dist.npy     float32, metres to nearest watercourse
data/meta.json
```

Keep the total under about 50 MB so it bakes into a sandbox snapshot cheaply. Downsample if needed and record the resolution in `meta.json`.

**Note for later:** if TASK 1's box is large, these arrays are what every case is scored against. Do not silently crop them per case.

---

## TASK 4 — The mocks (highest priority after data)

**Person A cannot start without these.** If the evening collapses, this and TASK 1/3 are what must survive.

Write `prep/make_mocks.py` generating files that match `CONTRACT.md` exactly. A crude random walk is fine — realism does not matter, shape does.

- `mocks/case.json` — a `case_loaded` payload: subject name, last contact, IPP, ring radius from priors
- `mocks/trajectories.json` — 200 worker batches in the §18 shape, with `runs[]`, `run_index`, `generated`, and about 5% marked `"status": "failed"`
- `mocks/field.json` — a `field_update` payload with a **real** base64 float32 256×256 grid, `progress: 1.0`, two zones, `field_area_pct`
- `mocks/field_partial.json` — same, `progress: 0.35`, blurrier field
- `mocks/field_collapsed.json` — post-evidence, tighter field, `n_consistent` about a third of `n_total`
- `mocks/fleet_status.json` — an array of about 20 frames, sandbox and completion counts climbing

Trajectories must start at the real IPP and stay inside the bbox, so A's map shows them in the right place.

Commit and push to `main` so both branches can pull.

---

## TASK 5 — Scoring harness

Write `model/score.py`.

```python
def rossmo_r(grid, find_row, find_col):
    p = grid[find_row][find_col]
    n = (grid > p).sum()
    m = (grid == p).sum()
    r = (n + m / 2) / grid.size
    return (0.5 - r) / 0.5      # worst -1, best +1, random 0
```

Grid convention: 5001 × 5001, 5 m cells, IPP at the exact centre, so a 25 × 25 km window. Row 0 is north.

Also write `model/ring_model.py`: concentric rings at the p25/p50/p75/p95 distances from `priors.json`, uniform probability density within each band, remaining 5% spread beyond the outer ring.

Then `prep/verify_baseline.py`: score the ring model over every case in `cases.csv` and print the mean R with a 95% confidence interval.

**Expected: near 0.78.** The published figure is 0.78 with a 95% CI of 0.74 to 0.82 across 376 cases; on 5 to 8 cases the interval will be much wider, so treat anything from roughly 0.6 to 0.9 as consistent and anything outside that as a bug.

If it comes out far off, the likely culprits in order: row/column orientation flipped, degrees not converted to metres properly at this latitude, or the find location falling outside the 25 km window. Report what you find rather than tuning until it looks right.

---

## TASK 6 — `model/field.py` skeleton

Signatures only, matching what the orchestrator will call. Working implementations are tomorrow's job, but the shapes must be fixed tonight:

```python
def build_field(trajectory_batches, bounds, resolution, accumulator=None): ...
def apply_evidence(trajectory_batches, evidence): ...
def field_area_pct(grid, cell_area_m2, ring_radius_m): ...
```

`field_area_pct` is defined as: the area of the smallest region containing 50% of the probability mass, as a percentage of the ring's area. Sort cells descending, accumulate to 0.5, count cells, multiply by cell area, divide by ring area. Implement this one properly tonight — it is the headline number and it must be computed the same way for the ring and the field.

---

## TASK 7 — Frontend scaffold for Person A

Next.js with Tailwind, plus `deck.gl @deck.gl/geo-layers @deck.gl/extensions maplibre-gl react-map-gl`.

One page that:

- Renders MapLibre with a dark basemap over `data/bbox.json`
- Adds terrain from AWS Terrarium terrain-RGB tiles: `https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png` (encoding `terrarium`)
- Sets pitch to **0** initially, with `exaggeration` and `pitch` as named constants so raising the camera is one change
- Calls `map.dragRotate.disable()` and `map.touchZoomRotate.disableRotation()`
- Loads `mocks/trajectories.json` and animates them with a TripsLayer
- Loads `mocks/field.json`, decodes the base64 grid to a canvas, and adds it as a **MapLibre image source** so it drapes on terrain

A `DATA_SOURCE` flag switching between `'mock'` and `'live'`, defaulting to mock.

Do not style it beyond a dark background. The visual direction is Person A's call tomorrow.

---

## TASK 8 — Daytona probe for Person B

`prep/daytona_probe.py`:

1. Build a snapshot: `Image.debianSlim('3.12').pipInstall('numpy')`, with `data/*.npy` and `data/meta.json` uploaded to `/data/`
2. Create 50 sandboxes cold, in parallel, and time to first successful command
3. Configure a warm pool, claim 50 from it, time again
4. Print both numbers, the concurrency limit hit if any, and the snapshot size

Write the results to `prep/TIMINGS.md`. **These two numbers decide the worker count and how long the simulation beat lasts on stage.** Docs: https://www.daytona.io/docs/en/python-sdk/ and https://www.daytona.io/docs/en/snapshots/

---

## Order and triage

| Priority | Task | Breaks if missing |
|---|---|---|
| 1 | 0, 1, 3 | Nothing can be built tomorrow |
| 2 | 4 | Person A idle until 14:30 |
| 3 | 2, 6 | Priors invented on the day, headline number undefined |
| 4 | 7 | Person A loses an hour to setup |
| 5 | 8 | Demo choreography is guesswork |
| 6 | 5 | Can be done during Sunday's 13:30 lull |

**If it gets late, stop after priority 3 and push.** A repo with real data and correct mocks beats a half-finished scoring harness nobody can run.

---

## Rules for this session

- Commit after every task with a clear message. Push to `main`.
- If real data does not match what this file assumes, **say so and stop**. Do not invent a schema and carry on.
- Every number written to a JSON file gets a `source` field. Placeholder values are labelled `PLACEHOLDER`.
- Do not build the worker, the orchestrator, the aggregation internals, or any UI styling. Those are the core project and get built at the event.
- Leave a `prep/STATUS.md` listing what completed, what did not, and anything that needs a decision from Shawn in the morning.
