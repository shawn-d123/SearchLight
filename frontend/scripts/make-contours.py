"""
Generate contour lines from the committed DEM.

    python3 scripts/make-contours.py [--interval 100] [--epsilon-cells 1.5]

Writes frontend/public/data/contours.geojson.

The visual direction asks for "contour lines rather than heavy hillshade, every
fifth line brighter" — standard cartographic practice, and the single strongest
signal that the map is a survey sheet rather than a dark-mode basemap. Hillshade
alone reads as grey mush on a projector and competes with the probability field
for attention; contours sit underneath it and stay legible.

We have no contour vector data, but we do have data/elevation.npy at 30 m, which
is what contours are derived from in the first place. matplotlib does the
marching squares; everything else here is turning cell indices back into WGS84
and throwing away vertices nobody can see.

Output properties:
  elev   metres
  index  true on every fifth line (500 m at the default interval) — the brighter
         one, and the only one that would carry a label on a real sheet
"""

import argparse
import json
import pathlib

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent
FRONTEND = HERE.parent
DATA = FRONTEND.parent / "data"
OUT = FRONTEND / "public" / "data" / "contours.geojson"

ap = argparse.ArgumentParser()
ap.add_argument("--interval", type=float, default=100.0, help="metres between lines")
ap.add_argument("--index-every", type=int, default=5, help="every Nth line is an index contour")
ap.add_argument("--epsilon-cells", type=float, default=1.5, help="simplification tolerance, in DEM cells")
ap.add_argument("--min-vertices", type=int, default=6, help="drop shorter fragments")
args = ap.parse_args()

meta = json.loads((DATA / "meta.json").read_text())
B = meta["bounds"]
ROWS, COLS = meta["shape"]
elevation = np.load(DATA / "elevation.npy")

lo = float(np.floor(elevation.min() / args.interval) * args.interval)
hi = float(np.ceil(elevation.max() / args.interval) * args.interval)
levels = np.arange(lo, hi + args.interval, args.interval)


def rdp(points: np.ndarray, epsilon: float) -> np.ndarray:
    """Ramer-Douglas-Peucker, iterative so a long ring cannot blow the stack.
    Contours off a smooth DEM are mostly redundant vertices; this removes ~90%
    of them with no visible change at demo zooms."""
    n = len(points)
    if n < 3:
        return points
    keep = np.zeros(n, dtype=bool)
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        i0, i1 = stack.pop()
        if i1 <= i0 + 1:
            continue
        seg = points[i1] - points[i0]
        norm = float(np.hypot(*seg))
        chunk = points[i0 + 1 : i1] - points[i0]
        if norm == 0.0:
            d = np.hypot(chunk[:, 0], chunk[:, 1])
        else:
            d = np.abs(chunk[:, 0] * seg[1] - chunk[:, 1] * seg[0]) / norm
        k = int(np.argmax(d))
        if d[k] > epsilon:
            idx = i0 + 1 + k
            keep[idx] = True
            stack.append((i0, idx))
            stack.append((idx, i1))
    return points[keep]


# Contour in cell space, then map cell -> degrees. Row 0 is NORTH, col 0 is WEST.
fig = plt.figure()
ax = fig.add_subplot(111)
cs = ax.contour(elevation, levels=levels)

lat_span = B["north"] - B["south"]
lon_span = B["east"] - B["west"]

features = []
kept_v = dropped_v = 0

for level, seg_list in zip(cs.levels, cs.allsegs):
    elev = float(level)
    is_index = int(round(elev / args.interval)) % args.index_every == 0
    for seg in seg_list:
        if len(seg) < args.min_vertices:
            continue
        simplified = rdp(np.asarray(seg, dtype=float), args.epsilon_cells)
        if len(simplified) < 2:
            continue
        dropped_v += len(seg) - len(simplified)
        kept_v += len(simplified)
        # seg columns are (x=col, y=row) in cell units.
        lons = B["west"] + (simplified[:, 0] / (COLS - 1)) * lon_span
        lats = B["north"] - (simplified[:, 1] / (ROWS - 1)) * lat_span
        features.append({
            "type": "Feature",
            "properties": {"elev": elev, "index": is_index},
            "geometry": {
                "type": "LineString",
                "coordinates": [
                    [round(float(x), 5), round(float(y), 5)]
                    for x, y in zip(lons, lats)
                ],
            },
        })

plt.close(fig)

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps({"type": "FeatureCollection", "features": features}))

print(
    f"{len(features):,} lines over {len(levels)} levels "
    f"({lo:.0f}-{hi:.0f} m at {args.interval:.0f} m, every {args.index_every}th indexed)"
)
print(
    f"vertices kept {kept_v:,}, dropped {dropped_v:,} "
    f"({dropped_v / max(1, kept_v + dropped_v):.0%} simplified away)"
)
print(f"wrote {OUT} — {OUT.stat().st_size / 1e6:.1f} MB")
