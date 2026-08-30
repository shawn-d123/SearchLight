# Prep status — night of Sat 29 / Sun 30 Aug 2026

Read this first in the morning. Person C (Shawn).

---

## Do these before kick-off — 10 minutes, they unblock the rest

Claude Code cannot create accounts. The OpenTopography key has since been
supplied and used; the other two are still needed.

1. ~~OpenTopography~~ — **DONE.** Key supplied, `.env` written (gitignored),
   USGS 3DEP pulled, all four worker arrays built. **33.7 MB, under the 50 MB
   snapshot budget.** Person B can bake the snapshot immediately.

2. **Daytona** — https://www.daytona.io → API key into `.env` as
   `DAYTONA_API_KEY`. **Write down the concurrent sandbox limit on the
   dashboard** — it caps the fleet. Then Person B runs:

   ```
   python prep/daytona_probe.py --n 5     # smoke test
   python prep/daytona_probe.py --n 50    # the real numbers
   ```

3. **OpenAI** — key into `.env` as `OPENAI_API_KEY`. Person B only.

4. ~~Push access~~ — done, four commits are on `origin/main`.

---

## Ready for the build — what each person can start on immediately

### Person A — frontend
`cd frontend && npm run dev`. Everything on your prep checklist is done except
the two judgement calls that are yours:

- deck.gl over MapLibre, sharing a camera, panning in lockstep — **done**
- terrain, `terrarium` encoding, **189 tiles cached locally into
  `public/tiles`** (z8–z13, 21 MB, committed). `TERRAIN_SOURCE` in
  `lib/config.ts` is already `'local'`, so the demo does not touch the network
  for terrain. **`TERRAIN_MAXZOOM` is 13 — do not raise it without re-caching,
  or MapLibre 404s and the terrain silently goes flat.**
- rotation disabled, `PITCH = 0`, `EXAGGERATION = 3.0` as named constants
- TripsLayer animating from mocks — **done**
- **Frame-rate check:** `python prep/make_mocks.py --stress` writes
  `trajectories_12k.json` (12,000 runs, 60 points each, ~10 s to generate). It
  is gitignored, so generate it locally. `MOCKS.trajectories12k` already points
  at it.
- **Draping decision made for you:** the field is a MapLibre **canvas** source,
  not a deck layer, so MapLibre drapes it natively. Paths deliberately float —
  do not drape them.
- Styling untouched. The visual direction is yours.

**Still your call:** the steep-slope draping sanity check, and everything in
section 7 of your brief.

> **One risk I did not solve:** `BASEMAP_STYLE` still loads from CARTO's CDN.
> Terrain is offline but the basemap is not, so on a dead network you get a
> black map under working terrain. Flagged in `config.ts`.

### Person B — simulation and Daytona
`worker/README.md` and `orchestrator/README.md` describe what you own, the
contract shapes, and the traps. **All four terrain arrays exist and are
committed** — 33.7 MB, ready to bake:

`elevation.npy` `slope.npy` `trail_dist.npy` `water_dist.npy`, all
1395 × 1510 at 30 m, row 0 north, geometry verified against Mount Lemmon.

First move: key into `.env`, then `python prep/daytona_probe.py --n 5`.

### Person C — you
`model/score.py` and `model/ring_model.py` are done and the baseline
reproduces. Sunday is `build_field` (10:45) and `apply_evidence` (13:30),
whose signatures are already frozen in `model/field.py`.

---

## The one decision already taken, and why

**The spec assumed Yosemite. There are no Yosemite cases.**

The free MapScore subset contains **131 Arizona cases only**. `database/
website_data.db` is an empty Django scaffold (`framework_case` = 0 rows); full
git history and all branches were checked. The README's claim that AZ/NY/
Yosemite are included is aspirational — only Arizona was ever committed. The
sole "Yosemite" mention in that repo is a heading in `arc-models/
diffusionwriteup.tex` marked *"not done"*.

You approved moving to the **Santa Catalina Mountains, Arizona** — the densest
mountainous cluster in the Arizona cases. Mount Lemmon at 2,791 m over a ~700 m
valley floor is ~2,100 m of relief, so terrain genuinely drives the field, and
OSM trail coverage there is dense.

**In the pitch, say "the Santa Catalina Mountains" instead of "Yosemite".
Nothing else changes.** Every argument still holds.

---

## What is done

| Task | State |
|---|---|
| 0 — repo scaffold, `.gitignore`, `.env.example`, `CONTRACT.md` | done |
| 1 — cases extracted, bounding box chosen | done |
| 2 — priors derived | done |
| 3 — terrain, trails, water, all four arrays | done, orientation verified |
| 4 — mocks | done, and validated against the contract |
| 5 — scoring harness + ring baseline | done, **and it reproduces** |
| 6 — `model/field.py` shapes | done |
| 7 — frontend scaffold | done, builds and serves, terrain tiles cached |
| 8 — Daytona probe | **script written, never run — no key** |

### Numbers worth knowing before you speak

- **109 of 131** cases have usable coordinates. Dropped: 6 where the find
  location *is* the IPP (degenerate — any model peaked at the IPP scores ~1.0,
  so they inflate everything), and 16 whose find lies beyond the 25 km scoring
  window and therefore cannot be scored at all.
- **Ring baseline reproduces.** Our ring over all 109 usable cases scores
  **R = 0.711 (95% CI 0.643–0.779)** against the published **0.78 (CI
  0.74–0.82, n=376)**. The intervals overlap. That means grid orientation,
  degrees-to-metres, and the 25 km window are all correct — every later number
  is trustworthy. This was the check that mattered most and it passed.
- **Ring on the 6 validation cases: R = 0.761.** *This* is the number the field
  must beat. Quote it, not 0.78 — it is the same model, same cases, same
  metric, which is the only honest comparison available on six cases.
- **Derived priors cross-check against Koester (2008)**: p25 1.63 vs 1.60,
  p50 2.86 vs 3.10, p75 6.26 vs 6.10 km. Independent corroboration that the
  extraction is right. Our p95 is 9.55 vs his 19.3 because this Arizona subset
  has a shorter tail than the full international database.
- **Ring radius is 9.55 km** (the p95), not the spec's illustrative 5.8 km.
  The on-screen label already says `ISRID RING · 95TH PCTL · 9.5 km`.
- **Terrain is real and verified.** Elevation 639–2793 m over the box, 2,154 m
  of relief. The DEM's highest cell sits 80 m from Mount Lemmon's published
  summit and reads 2793 m against a published 2791 m — so the array is north-up
  and correctly georeferenced, which is the terrain equivalent of the ring
  reproduction check. Mean slope 12.2°, max 75.7°.
- **The demo IPP is a good one.** Arizona80 sits at 2,439 m on a 29° slope,
  42 m from a trail and 450 m from water — a hiker high on a steep trailed
  mountainside. Terrain will genuinely shape that field rather than decorate it.

---

## What is NOT done, and what it costs

1. **The Daytona probe was never run.** No key. The script is written but
   **unverified against a live API** — expect to fix a call signature or two
   on first run. Note the prep doc's `Image.debianSlim().pipInstall()` is the
   *TypeScript* spelling; the Python SDK is snake_case and the script uses the
   correct form, verified by introspecting the installed package.
   **Cost if skipped: demo choreography is guesswork.**

2. ~~Nothing is pushed.~~ **Pushed.** Four commits are on
   `origin/main` at `https://github.com/shawn-d123/SearchLight.git`.
   The team can clone immediately.

3. **Branches `fe` / `sim` / `model` were not created.** The prep doc asks for
   four branches, but `searchlight-complete_1.md` §18 is emphatic that everyone
   works on `main` with no feature branches. I followed the spec.
   **If you want them: `git branch fe && git branch sim && git branch model`.**

4. **`model/build_field` and `apply_evidence` are signatures only** — as the
   prep rules require. Their internals are Sunday's 10:45 and 13:30 slots.

---

## Traps found tonight that would have cost you hours

- **The `Distance` column is in statute MILES**, not km, while the coordinates
  are decimal degrees. At face value 102 of 131 rows "disagree" with their own
  coordinates. Converting at 1.609344 drops median disagreement to 0.44 km.
  Had this been missed, the distance priors would have been ~1.6× too small and
  the ring would have been wrong all day.

- **`network_type='all'` over this box returns 105,236 walkable ways, 86,363 of
  which are northern Tucson's pavements** — 35 MB of GeoJSON that would have
  crushed the frontend. Display trails now keep `path`/`track`/`bridleway`/
  `steps` only: 14,750 ways, 3.4 MB. `trail_dist` is still rasterised from the
  full 444k-edge network, because a subject walks a dirt road as readily as a
  marked trail.

- **`rasterio` and `fiona` cannot load on this machine.** Smart App Control is
  ENFORCED and blocks their GDAL native DLLs. They pip-install fine and then
  fail at import. We use `tifffile` for the GeoTIFF and `gdf.to_json()` for
  GeoJSON — no functional difference. **Do not disable Smart App Control to
  "fix" this: it cannot be re-enabled without a full Windows reset.**

- **`.gitignore` has no trailing comments.** `data/trails.graphml  # 205 MB`
  ignores a file whose name ends in `# 205 MB`. Cost ten minutes; noted in the
  file so it does not recur.

---

## Honest caveats to state before a judge finds them

- Six validation cases, not the 376 of the published benchmark. The confidence
  interval is correspondingly wide (±0.24 on the ring). Say so.
- The family weights in `data/priors.json` are **invented** and flagged
  `PLACEHOLDER` in the file itself. Either source them to Koester's published
  strategy frequencies or describe them as an assumption. Do not present them
  as derived.
- Distance priors are derived from Arizona cases and the demo runs on Arizona
  terrain — consistent, but a single ecoregion and one subject category.
- The `field_area_pct` mock values (26.4% full, 9.9% collapsed) come from a
  crude corridor-biased random walk, not from terrain. **They will change once
  real simulations run.** Do not rehearse a specific number until Sunday.
- The evidence radius in the mock was tuned so ~⅓ of runs survive, to match the
  demo beat. It is labelled as such in `field_collapsed.json`. It is not a
  measured quantity.

---

## First moves at 10:30

1. Contract lock, all three, 15 minutes. `CONTRACT.md` is written; read it
   aloud and freeze it by 10:45.
2. Point Person A at `frontend/` — `npm run dev`, mocks already served from
   `/public/mocks`, `DATA_SOURCE` in `lib/config.ts`.
3. Person B: `daytona_probe.py --n 5`, then `--n 50`.

Regenerate anything: `python prep/make_mocks.py && python prep/validate_mocks.py`
