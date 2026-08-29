# Prep status — night of Sat 29 / Sun 30 Aug 2026

Read this first in the morning. Person C (Shawn).

---

## Do these before kick-off — 10 minutes, they unblock the rest

Claude Code cannot create accounts. Nothing below was done.

1. **OpenTopography** — https://opentopography.org → sign up (free) → *My Account*
   → *Request API key*. It arrives immediately.
   Then: `cp .env.example .env`, paste it as `OPENTOPO_API_KEY`, and run

   ```
   python prep/fetch_terrain.py elevation
   python prep/fetch_terrain.py arrays
   ```

   That fills in the last two of four worker arrays. **~3 minutes. Do it first
   — Person B cannot bake the snapshot without them.**

2. **Daytona** — https://www.daytona.io → API key into `.env` as
   `DAYTONA_API_KEY`. **Write down the concurrent sandbox limit on the
   dashboard** — it caps the fleet. Then Person B runs:

   ```
   python prep/daytona_probe.py --n 5     # smoke test
   python prep/daytona_probe.py --n 50    # the real numbers
   ```

3. **OpenAI** — key into `.env` as `OPENAI_API_KEY`. Person B only.

4. **Push access** — the repo is committed locally but **not pushed**; see
   *Not done* below.

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
| 3 — trails + water | done. **elevation + slope blocked on the key** |
| 4 — mocks | done, and validated against the contract |
| 5 — scoring harness + ring baseline | done, **and it reproduces** |
| 6 — `model/field.py` shapes | done |
| 7 — frontend scaffold | done, builds and serves |
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

---

## What is NOT done, and what it costs

1. **`data/elevation.npy` and `data/slope.npy`** — need `OPENTOPO_API_KEY`.
   Two of the four worker arrays exist (`trail_dist`, `water_dist`, 16.9 MB).
   **Cost if skipped: workers have no terrain, which is the entire thesis.**
   3 minutes once you have the key.

2. **The Daytona probe was never run.** No key. The script is written but
   **unverified against a live API** — expect to fix a call signature or two
   on first run. Note the prep doc's `Image.debianSlim().pipInstall()` is the
   *TypeScript* spelling; the Python SDK is snake_case and the script uses the
   correct form, verified by introspecting the installed package.
   **Cost if skipped: demo choreography is guesswork.**

3. **Nothing is pushed.** Three commits sit on local `main`. The remote is
   `https://github.com/shawn-d123/SearchLight.git`. I did not push because
   that needs your credentials. Run `git push origin main`.

4. **Branches `fe` / `sim` / `model` were not created.** The prep doc asks for
   four branches, but `searchlight-complete_1.md` §18 is emphatic that everyone
   works on `main` with no feature branches. I followed the spec.
   **If you want them: `git branch fe && git branch sim && git branch model`.**

5. **`model/build_field` and `apply_evidence` are signatures only** — as the
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

1. `git push origin main` — everyone else is blocked until it lands.
2. OpenTopography key → `fetch_terrain.py elevation` → `arrays`. 3 minutes.
3. Contract lock, all three, 15 minutes. `CONTRACT.md` is written; read it
   aloud and freeze it by 10:45.
4. Point Person A at `frontend/` — `npm run dev`, mocks already served from
   `/public/mocks`, `DATA_SOURCE` in `lib/config.ts`.
5. Person B: `daytona_probe.py --n 5`, then `--n 50`.

Regenerate anything: `python prep/make_mocks.py && python prep/validate_mocks.py`
