# worker/ — Person B

Runs **inside a Daytona sandbox**. Nothing here imports anything outside numpy.

## Contract

Read `../CONTRACT.md` first. One sandbox holds **one generated movement script**
and runs it many times with different seeds, so a worker returns a **batch**:

```json
{ "hypothesis_id": "h_00184", "family": "route_travelling", "weight": 0.22,
  "generated": true,
  "runs": [ {"run_index": 0, "points": [[lat, lon, t]], "endpoint": [lat, lon],
             "duration_s": 4320, "status": "ok"} ] }
```

`points` ≤ 60 per run. `status` is `ok` or `failed`.

## What is baked into the snapshot

`/data/` holds four float32 arrays plus `meta.json`, **33.7 MB total**:

| file | meaning |
|---|---|
| `elevation.npy` | metres, 639–2793 over the box |
| `slope.npy` | degrees, mean 12.2, max 75.7 |
| `trail_dist.npy` | metres to the nearest walkable way |
| `water_dist.npy` | metres to the nearest watercourse |

All are `1395 × 1510` at **30 m/cell**, row-major, **row 0 is NORTH**.
`meta.json` carries bounds, shape and cell size. Index them with the helper in
`meta.json["note"]` — get the orientation backwards and every trajectory is
mirrored, which is invisible until validation fails.

**Never `pip install` at sandbox start.** Bake numpy into the snapshot. No
geopandas, no OSMnx, no rasterio — heavy, and they multiply across 200 sandboxes.

## The fallback — build it day one

Generated code will fail: syntax errors, infinite loops, walking off the grid,
returning nothing. Required from the start:

- **hard timeout per worker, 10 seconds**
- failures return `{"status": "failed"}`, **counted not plotted**
- **a hand-written template script per family** as a deterministic fallback,
  with `generated: false` so the failure count on screen stays honest

**The demo must be able to run with zero successful generations.**
A failure count on screen is credibility, not weakness.
