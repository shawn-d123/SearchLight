# Searchlight

**Don't search everywhere. Search where they could be.**

A person goes missing. Rescue teams today draw a distance ring around the last
known point, because published statistics say a hiker is usually found within a
certain distance. A ring is a circle, and people do not walk in circles — they
follow paths, avoid steep ground, head downhill when tired, and stop at water.

Searchlight takes the same published statistics and runs thousands of simulated
people across the real terrain. Where lots of them end up, the map goes bright.
Then a witness report lands, every simulation inconsistent with it is discarded,
and the search area shrinks.

*A ring cannot respond to evidence.*

## What is actually being claimed

Not "we predict where missing people are". The field is not empty: Koester's
ISRID holds 145,000+ searches and teams already build ring models from it.

> Ring models apply published statistics as circles. We apply the same
> statistics as terrain-aware simulations, and update them against evidence.

## Where it runs

**Santa Catalina Mountains, Arizona** — 45.3 × 42.1 km centred (32.387, −110.829).
Mount Lemmon at 2,791 m over a ~700 m valley floor. Six real historical cases
from the MapScore ISRID subset sit inside the box.

> The spec originally assumed Yosemite. The free MapScore set contains no
> Yosemite cases — only Arizona. See `prep/STATUS.md`.

## Benchmark

| Model | R |
|---|---|
| Published ISRID distance ring (n=376) | 0.78 (95% CI 0.74–0.82) |
| Published best combined | 0.805 |
| **Our ring, all 109 usable cases** | **0.711 (95% CI 0.643–0.779)** |
| **Our ring, the 6 validation cases** | **0.761** |

Our ring reproducing the published baseline is the check that the harness is
correct. The field is scored against the 0.761, not the 0.78 — same model, same
cases, same metric.

## Layout

```
frontend/       Person A   Next.js, deck.gl, MapLibre
worker/         Person B   runs inside a Daytona sandbox
orchestrator/   Person B   fleet control, WebSocket server
model/          Person C   aggregation, evidence, scoring
mocks/          Person C   committed, validated against CONTRACT.md
data/           terrain arrays, trails, cases, priors
prep/           throwaway scripts used the night before
CONTRACT.md     the frozen interface — read this first
```

**Everyone works on `main`.** No feature branches. `git pull --rebase`, push
every 20–30 minutes. Nobody edits another person's directory.

## Setup

```bash
python -m venv .venv && .venv/Scripts/activate      # Windows
pip install -r prep/requirements.txt
cp .env.example .env                                 # then fill in the keys
```

Rebuild everything from scratch:

```bash
git clone https://github.com/ctwardy/mapscore prep/mapscore
python prep/extract_cases.py       # -> data/cases.csv, data/bbox.json
python prep/make_priors.py         # -> data/priors.json
python prep/fetch_terrain.py all   # -> trails, water, arrays  (elevation needs a key)
python prep/make_mocks.py          # -> mocks/ and frontend/public/mocks/
python prep/validate_mocks.py      # checks all six against CONTRACT.md
python prep/verify_baseline.py     # reproduces the ring baseline
```

Terrain tiles for offline use (189 tiles, ~21 MB, already committed):

```bash
python prep/cache_tiles.py
```

Frontend:

```bash
cd frontend && npm install && npm run dev
```

Frame-rate stress fixture (12,000 runs, gitignored, ~10 s):

```bash
python prep/make_mocks.py --stress
```

`DATA_SOURCE` in `frontend/lib/config.ts` switches `'mock'` → `'live'`.

## Known weaknesses — state these first

- Six validation cases, not 376. The interval is wide. Say so.
- Family weights in `data/priors.json` are `PLACEHOLDER` and flagged as such.
- Terrain cost functions are hand-tuned, not fitted.
- One subject category, one search area, one weather condition.
- The evidence filter treats witness reports as reliable. Real ones often are not.
- **This is decision support that surfaces hypotheses, not a probability
  oracle.** It informs a human decision. It never replaces one.

## Source

Sava, Twardy, Koester & Sonwalkar, *Evaluating Lost Person Behavior Models*,
Transactions in GIS.
Cases: https://github.com/ctwardy/mapscore (Arizona subset, free to distribute).
