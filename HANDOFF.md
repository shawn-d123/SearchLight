# SEARCHLIGHT — HANDOFF

**Read this before touching anything.** It exists so a fresh start costs
minutes instead of hours, and so nobody re-derives a decision that was already
made for a reason.

Written after the prep session, night of Sat 29 → Sun 30 Aug 2026.
Hackathon: Daytona HackSprint, Entrepreneurs First HQ, London.
Kick-off 10:30, submissions 17:00, team of three.

Full context: `Docs and MDs/searchlight-complete_1.md` (the spec),
`Docs and MDs/PREP-TONIGHT.md` (Person C's prep list),
`Docs and MDs/PREP-PERSON-A.md` (Person A's prep list),
`CONTRACT.md` (the frozen interface — **this wins over the spec**),
`prep/STATUS.md` (morning checklist).

---

## 1. What this is, in one paragraph

A person goes missing. Rescue teams today draw a distance ring around the last
known point from published ISRID statistics. A ring is a circle, and people do
not walk in circles — they follow trails, avoid steep ground, go downhill when
tired, and stop at water. Searchlight takes the *same* published statistics and
runs thousands of simulated walkers across real terrain, accumulating a
probability field. A witness report then discards every inconsistent simulation
and the field collapses, while the ring stays exactly the same size.

**The claim is not "we predict where missing people are."** It is: *ring models
apply published statistics as circles; we apply the same statistics as
terrain-aware simulations, and update them against evidence.* State the prior
art unprompted — Koester's ISRID, 145,000+ searches — being caught unaware of
it would be fatal.

---

## 2. State at a glance

8 commits, all dated 2026-08-30, on
`https://github.com/shawn-d123/SearchLight.git`.

| Task | State |
|---|---|
| 0 repo scaffold, `CONTRACT.md` | done |
| 1 cases + bounding box | done |
| 2 priors | done |
| 3 terrain, trails, water, 4 arrays | done, geometry verified |
| 4 mocks | done, validated against contract |
| 5 scoring harness + ring baseline | done, **and it reproduces** |
| 6 `model/field.py` shapes | done |
| 7 frontend scaffold | done, builds + serves, terrain cached offline |
| 8 Daytona probe | **written, NEVER RUN — no key** |

**Not built, on purpose** (prep rules forbid it — this is the core project,
built at the event): the worker, the orchestrator, the aggregation internals
(`build_field`, `apply_evidence` raise `NotImplementedError`), and all UI
styling.

---

## 3. Decisions already made — do not re-litigate these

### 3.1 It is Arizona, not Yosemite

The spec assumed Yosemite. **The free MapScore set contains no Yosemite cases.**
131 Arizona cases only; `database/website_data.db` is an empty Django scaffold
(`framework_case` = 0 rows). Full git history and all branches were checked. The
only "Yosemite" mention in that repo is a heading marked *"not done"*.

Moved to the **Santa Catalina Mountains, Arizona** — the densest mountainous
cluster. Mount Lemmon 2,791 m over a ~700 m valley floor.

> **In the pitch say "the Santa Catalina Mountains."** Nothing else changes;
> every argument still holds.

### 3.2 The case filters

131 → **109 usable**, via two filters the brief did not specify:

- **−6 degenerate**: find location *is* the IPP. Any model peaked at the IPP
  scores ~1.0 on these, inflating everything. Excluded from validation, and
  **say so** — an inflated score a judge spots is far worse than an exclusion
  you announced.
- **−16 unscoreable**: find lies beyond the 25 km scoring window. Cannot be
  scored at all; this is geometry, not preference.

### 3.3 Priors have a holdout variant

Deriving quantiles from the same 6 cases you score on is circular.
`data/priors.json` therefore carries `distance_km` (n=75) **and**
`distance_km_holdout` (n=69, excluding the validation cases).
`verify_baseline.py` uses the holdout. Keep it that way.

### 3.4 The field drapes via a MapLibre canvas source

deck.gl layers over MapLibre terrain **do not follow the ground** — they render
in their own pass and float flat. MapLibre drapes its own raster/canvas layers
natively. So the field is a canvas source, not a deck layer. `TerrainExtension`
would also work but is one more thing to debug under time pressure.

**Paths are deliberately NOT draped** — floating above ground looks better and
avoids z-fighting on hillsides.

### 3.5 Everyone works on `main`

No feature branches. The prep doc asks for `fe`/`sim`/`model`; spec §18 is
emphatic about `main` only. Spec won. `git pull --rebase`, push every 20–30 min.
Nobody edits another person's directory.

---

## 4. The numbers, and which are trustworthy

### Verified — two independent geometry checks, both passed

| Check | Ours | Reference | Result |
|---|---|---|---|
| Ring baseline, 109 cases | **0.711** (95% CI 0.643–0.779) | published **0.78** (CI 0.74–0.82, n=376) | intervals overlap |
| DEM highest cell | **2793 m** @ (32.4422, −110.7887) | Mt Lemmon **2791 m** @ (32.4429, −110.7885) | 80 m offset |
| Derived priors | p25 1.63 / p50 2.86 / p75 6.26 km | Koester (2008) 1.60 / 3.10 / 6.10 | near-exact |

The first proves grid orientation, degrees-to-metres and the 25 km window are
right. The second proves the terrain array is north-up. The third independently
corroborates the whole extraction chain. **Because these passed, later numbers
can be trusted.** If you change the grid geometry, re-run both.

### The number for the pitch

**Ring on the 6 validation cases = 0.761.** *This* is what the field must beat.
Quote it, **not 0.78** — same model, same cases, same metric, which is the only
honest comparison available on six cases.

Koester's own quantiles score 0.615 on these cases because his p95 (19.3 km) is
far wider than this Arizona subset warrants (ours is 9.55 km). An oversized ring
spends area on empty ground and R penalises exactly that. Expected, not a bug.

### Not trustworthy yet — do not rehearse these

`field_area_pct` in the mocks (**partial 38.8% / full 26.4% / collapsed 9.9%**)
comes from a crude corridor-biased random walk, **not from terrain**. These
*will* change once real simulations run. The spec's "a fifth of the area" is
illustrative.

---

## 5. Traps already found — each would have cost hours

1. **The `Distance` column is in statute MILES.** Coordinates are decimal
   degrees. At face value 102 of 131 rows contradict their own coordinates.
   Converting at 1.609344 drops median disagreement from ~4.8 km to 0.44 km
   (94/131 within 1 km). Missing this makes the priors ~1.6× too small.

2. **`network_type='all'` returns 105,236 walkable ways here, 86,363 of them
   northern Tucson's pavements** — 35 MB of GeoJSON that crushes the frontend.
   Display trails keep `path`/`track`/`bridleway`/`steps` only: 14,750 ways,
   3.4 MB. `trail_dist` is still rasterised from the **full 444k-edge network**,
   because a subject walks a dirt road as readily as a marked trail.

3. **`rasterio` and `fiona` cannot load on the prep machine.** Smart App Control
   is ENFORCED and blocks their GDAL native DLLs; they pip-install fine then
   fail at import. Use `tifffile` for GeoTIFF and `gdf.to_json()` for GeoJSON.
   **Do not disable Smart App Control — it cannot be re-enabled without a full
   Windows reset.** On a machine without this restriction, rasterio would work
   and nothing would need changing.

4. **`.gitignore` has no trailing comments.** `data/trails.graphml  # 205 MB`
   ignores a file whose name literally ends in `# 205 MB`.

5. **Terrain `maxzoom` must match the tile cache.** It was hardcoded to 14 while
   the cache stops at 13; MapLibre would 404 past the cache and the terrain goes
   flat **silently**, with no error to chase. Now `TERRAIN_MAXZOOM`.

---

## 6. Environment

- Python **3.12** venv at `.venv/`. `pip install -r prep/requirements.txt`.
- Node **24**, npm 11. Frontend: Next 16, React 19, deck.gl 9.3, MapLibre 6,
  react-map-gl 8.
- Repo lives inside OneDrive. Fine, but `node_modules`/`.venv` sync churn is
  slow; both are gitignored.
- `.env` is gitignored. `OPENTOPO_API_KEY` is set. **`DAYTONA_API_KEY` and
  `OPENAI_API_KEY` are still empty.**
- `gh` CLI is **not installed** — GitHub repo operations must be done in a browser.

### Regenerating everything from a clean clone

```bash
python -m venv .venv && .venv/Scripts/activate     # Windows
pip install -r prep/requirements.txt
cp .env.example .env                                # fill in keys

git clone https://github.com/ctwardy/mapscore prep/mapscore
python prep/extract_cases.py      # -> data/cases.csv, data/bbox.json
python prep/make_priors.py        # -> data/priors.json
python prep/fetch_terrain.py all  # -> trails, water, DEM, 4 arrays
python prep/cache_tiles.py        # -> 189 terrain tiles (already committed)
python prep/make_mocks.py         # -> mocks/ and frontend/public/mocks/
```

### Verify nothing is broken (run these after any change to geometry)

```bash
python prep/validate_mocks.py     # all six mocks vs CONTRACT.md
python prep/verify_baseline.py    # must still print CONSISTENT
cd frontend && npx next build     # must compile + typecheck clean
```

---

## 7. Concrete values — these are the real ones

| Thing | Value |
|---|---|
| Region | Santa Catalina Mountains, Arizona, USA |
| Bounds | N 32.576089, S 32.197678, E −110.587766, W −111.069734 |
| Box | 45.26 × 42.08 km, centre (32.386883, −110.828750) |
| Terrain grid | 1395 × 1510 @ **30 m**, row 0 = NORTH |
| Elevation | 639–2793 m, relief 2154 m; slope mean 12.2°, max 75.7° |
| Arrays | `elevation` `slope` `trail_dist` `water_dist`, **33.7 MB total** |
| Ring radius (p95) | **9.55 km** — label it `ISRID RING · 95TH PCTL · 9.5 km` |
| Validation cases | 6: Arizona53, 58, 80, 85, 89, 90 |
| Demo case | **Arizona80** — IPP (32.41977, −110.74733), 2439 m, 29° slope, 42 m from trail, 450 m from water |
| Scoring grid | 5001 × 5001 @ 5 m, IPP at exact centre = 25.005 km window |
| Display grid | 256 × 256, base64 float32, normalised 0..1 |

**The two grids are not interchangeable.** The scoring grid is 25 million
floats and **never touches the WebSocket**. Same function, different resolution
argument.

---

## 7b. The fleet ceiling — measured, and it is 10

**The Daytona account caps at 10 concurrent sandboxes, not 200.** Both limits
bind at 10: 10 GiB of memory and 10 vCPU. There is no configuration on this
tier that reaches 200.

| snapshot | memory | concurrent | 200 hypotheses | rate |
|---|---|---|---|---|
| `searchlight-worker` | 2 GiB | 5 | 13.7 s | 877 sims/s |
| **`sl-worker-1g`** (default) | **1 GiB** | **10** | **9.3 s** | **1,289 sims/s** |

Both produce an identical field, so the 1 GiB image is strictly better and is
now the default in `orchestrator/fleet.py`.

**Do not say "200 sandboxes" while 10 are running.** The fleet counter is the
only on-screen proof that real machines are working. "Ten isolated sandboxes,
12,000 simulations in nine seconds" is true and good. Full numbers, pitch
implications and two Windows snapshot traps are in `prep/TIMINGS.md`.

Credit discipline: every sandbox is labelled, torn down in a `finally`, swept
at exit, and capped by `MAX_SANDBOXES`. **Run `python prep/daytona_ctl.py
status` after any interrupted run** — idle sandboxes bill by the second and
nothing on screen tells you they are up.

---

## 8. What is blocked, and what it costs

1. **Daytona probe never run** — no `DAYTONA_API_KEY`. `prep/daytona_probe.py`
   is written against the SDK surface *verified by introspecting the installed
   package*, but never executed. **Expect to fix a call signature or two.**
   Note the prep doc's `Image.debianSlim().pipInstall()` is the **TypeScript**
   spelling; Python is snake_case (`debian_slim`, `pip_install`).
   *Cost if skipped: fleet size and demo choreography are guesswork.*

2. **`OPENAI_API_KEY` missing — THIS IS THE BIGGEST GAP.** Every batch
   currently returns `generated: false`, i.e. the deterministic template ran.
   The plumbing is built and tested: `worker/runner.py` accepts a model-written
   script, validates its output shape, times it out at 10 s, and falls back
   cleanly. Nothing feeds it.

   B's brief is blunt about why that matters: *"If you fall back to a fixed
   script with parameters, the Daytona story collapses and the project becomes
   an animation. Protect this above any feature."* What exists today is the
   fallback, which must exist. What is missing is the thing that justifies
   sandboxes at all. **Protect this part**: if you fall back to a fixed
   script with parameters, the whole Daytona story collapses. One model call per
   *sandbox*, not per simulation — 200 sandboxes × 60 seeds = 12,000 sims from
   200 calls.

3. **CARTO basemap is a live network dependency.** Terrain is cached offline
   (189 tiles, z8–z13, 21 MB, committed) but `BASEMAP_STYLE` still loads from
   CARTO's CDN. On dead wifi: black basemap under working terrain. Flagged in
   `frontend/lib/config.ts`. Fix would be a local style JSON — Person A's call.

---

## 9. Where to start, per role

### Person A — frontend
`cd frontend && npm run dev`. Camera integration, terrain, rotation lock,
TripsLayer and the draping decision are all done. `DATA_SOURCE` in
`lib/config.ts` flips `'mock'` → `'live'` at 14:30.
Frame-rate check: `python prep/make_mocks.py --stress` (12,000 runs, gitignored,
~10 s). **The static frame by 11:30 is the milestone that matters** — terrain,
trails, marker, ring, flat, no animation. Chase the 3D camera first and you can
be four hours in with nothing to show.

### Person B — simulation + Daytona
Read `worker/README.md` and `orchestrator/README.md`. All four arrays are
committed and ready to bake. **Ten workers end to end by 12:30** — if not, tell
the team; that is the point where the plan changes, not where you work harder.
Build the per-family fallback template **day one**: the demo must be able to run
with zero successful generations.

### Person C — aggregation, evidence, validation
`model/score.py` and `model/ring_model.py` are done and verified. Sunday is
`build_field` (10:45) and `apply_evidence` (13:30) — signatures already frozen
in `model/field.py`. `field_area_pct` is implemented; **it is the headline
number and must be computed identically for ring and field**, so use the same
function for both.

---

## 10. Rules that are not negotiable

1. **Contract frozen at 10:45.** `CONTRACT.md` is written; read it aloud and
   lock it. Two people editing it at 10:45 is the one conflict that hurts.
2. **Mocks first, live second.**
3. **14:30 is a hard integration point.** Everything connects end to end,
   however ugly. First integration at 16:00 means no demo.
4. **Nobody edits another person's directory.**
5. **At 16:00, once the demo works, tag `demo-safe` and leave it alone.**
6. **Cut in this order if behind:** camera choreography → team deployment →
   3D terrain (fall back to 2D) → zone detail panels. **Never cut validation.**
7. **Never present cached output as live.** Cache model outputs if you like and
   say so in four words — nobody blinks at that.

---

## 11. Honest caveats — state these before a judge finds them

- Six validation cases, not 376. The interval is wide (±0.24 on the ring).
- **The family weights in `data/priors.json` are invented** and flagged
  `PLACEHOLDER` in the file itself. Either source them to Koester's published
  strategy frequencies or call them an assumption. Do not present them as derived.
- Terrain cost functions will be hand-tuned, not fitted.
- One subject category, one ecoregion, one weather condition.
- The evidence filter treats witness reports as reliable. Real ones often are not.
- The mock evidence radius was **tuned** so ~⅓ of runs survive, to match the demo
  beat. Labelled as such in `field_collapsed.json`. Not a measured quantity.
- **This is decision support that surfaces hypotheses, not a probability oracle.**
  It informs a human decision. It never replaces one.

---

## 12. File map

```
CONTRACT.md          the frozen interface. Beats the spec where they disagree
HANDOFF.md           this file
README.md            project overview + setup
prep/STATUS.md       morning checklist, what is done/blocked

model/     C    score.py (Rossmo R) · ring_model.py (baseline) · field.py
                (field_area_pct done; build_field/apply_evidence are stubs)
worker/    B    README only — runs in a sandbox, numpy only
orchestrator/ B README only — fleet, WS server, aggregation calls
frontend/  A    Next.js scaffold; lib/config.ts holds every switch
mocks/     C    six payloads, validated against CONTRACT.md
data/           cases.csv, bbox.json, priors.json, meta.json, baseline.json,
                4 terrain arrays, trails/water geojson
prep/           extract_cases · make_priors · fetch_terrain · cache_tiles ·
                make_mocks · validate_mocks · verify_baseline · daytona_probe
```

Not committed (regenerable): `data/trails.graphml` (205 MB), `data/dem.tif`
(67 MB), `data/_*.npy` masks, `mocks/trajectories_12k.json`, `prep/mapscore/`.

---

## 13. The pitch, in one screen

**0:00** ring drawn. *"This ring is how search areas are drawn today. Published
statistics, applied as a circle."*
**0:12** *"The statistics are good. The circle is the problem."* Run.
**0:18** paths explode, field accumulates, fleet counter climbs.
**0:35** *"Same statistics. A fraction of the area."*
**0:50** witness report. Field collapses. Ring unchanged.
**1:05** *"The ring didn't move, because a ring can't respond to evidence."*
**1:12** validation. *"Real historical cases. The ring model scores 0.761 on
these same cases. We scored X."*
**1:25** *"Don't search everywhere. Search where they could be."*

**Report the validation number honestly whichever way it falls.** A model that
scores 0.6 and says so is worth more than one that shows a tick. Beat the ring
and you have a headline; miss it and you have a finding — plus a far better
answer to the inevitable question than silence.
