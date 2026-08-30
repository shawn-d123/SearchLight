"""Pre-download the Terrarium terrain tiles for the bounding box.

Person A's brief: "Cache the tiles locally. Venue wifi at 16:50 is not
something to rely on, and a demo that cannot load terrain is not a demo."

Tiles land in frontend/public/tiles/terrarium/{z}/{x}/{y}.png, which Next
serves statically. Flip TERRAIN_TILES in frontend/lib/config.ts to the local
path and the demo no longer touches the network for terrain.

    python prep/cache_tiles.py            # z8-z13, the useful range
    python prep/cache_tiles.py --max-zoom 14
    python prep/cache_tiles.py --dry-run  # count and size estimate only

Idempotent: existing tiles are skipped, so re-running after a dropped
connection resumes rather than restarts.
"""
from __future__ import annotations

import argparse, json, math, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = ROOT / "frontend" / "public" / "tiles" / "terrarium"

URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
MIN_ZOOM, MAX_ZOOM = 8, 13
WORKERS = 12


def deg2tile(lat, lon, z):
    n = 2 ** z
    x = int((lon + 180.0) / 360.0 * n)
    r = math.radians(lat)
    y = int((1.0 - math.asinh(math.tan(r)) / math.pi) / 2.0 * n)
    return max(0, min(n - 1, x)), max(0, min(n - 1, y))


def tiles_for(bbox, z):
    x0, y0 = deg2tile(bbox["north"], bbox["west"], z)   # NW corner
    x1, y1 = deg2tile(bbox["south"], bbox["east"], z)   # SE corner
    for x in range(min(x0, x1), max(x0, x1) + 1):
        for y in range(min(y0, y1), max(y0, y1) + 1):
            yield z, x, y


def fetch(session, z, x, y):
    path = OUT / str(z) / str(x) / "{}.png".format(y)
    if path.exists() and path.stat().st_size > 0:
        return "skip", path.stat().st_size
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        r = session.get(URL.format(z=z, x=x, y=y), timeout=30)
    except Exception as e:
        return "error:{}".format(type(e).__name__), 0
    if r.status_code == 404:
        # Ocean and some edges legitimately have no tile.
        return "missing", 0
    if r.status_code != 200:
        return "error:{}".format(r.status_code), 0
    path.write_bytes(r.content)
    return "ok", len(r.content)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-zoom", type=int, default=MIN_ZOOM)
    ap.add_argument("--max-zoom", type=int, default=MAX_ZOOM)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    bbox = json.load(open(DATA / "bbox.json"))
    print("caching terrain for {}".format(bbox["region"]))
    print("  {:.1f} x {:.1f} km".format(bbox["width_km"], bbox["height_km"]))

    wanted = []
    for z in range(args.min_zoom, args.max_zoom + 1):
        t = list(tiles_for(bbox, z))
        wanted += t
        print("  z{:<3} {:>5} tiles".format(z, len(t)))
    print("  total {} tiles, roughly {:.0f} MB".format(
        len(wanted), len(wanted) * 0.06))

    if args.dry_run:
        return

    OUT.mkdir(parents=True, exist_ok=True)
    counts, total_bytes = {}, 0
    t0 = time.time()
    with requests.Session() as session, ThreadPoolExecutor(WORKERS) as pool:
        futs = [pool.submit(fetch, session, *t) for t in wanted]
        for i, f in enumerate(as_completed(futs), 1):
            status, n = f.result()
            key = status.split(":")[0]
            counts[key] = counts.get(key, 0) + 1
            total_bytes += n
            if i % 100 == 0 or i == len(futs):
                print("    {}/{} ...".format(i, len(futs)), end="\r", flush=True)

    print()
    print("  done in {:.0f}s | {} | {:.1f} MB on disk".format(
        time.time() - t0,
        ", ".join("{} {}".format(v, k) for k, v in sorted(counts.items())),
        sum(p.stat().st_size for p in OUT.rglob("*.png")) / 1e6))

    errors = sum(v for k, v in counts.items() if k == "error")
    if errors:
        print("  {} tiles failed -- re-run to retry just those".format(errors))
        return 1

    print()
    print("  To use them, in frontend/lib/config.ts set:")
    print('    export const TERRAIN_TILES = "/tiles/terrarium/{z}/{x}/{y}.png";')
    print("  and TERRAIN_MAXZOOM = {}".format(args.max_zoom))
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
