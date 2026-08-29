"""TASK 3 - terrain, trails, water, and the flat numpy arrays workers use.

Runs in stages so the keyless parts complete tonight and the elevation stage
can be run the moment the OpenTopography key arrives:

    python prep/fetch_terrain.py osm          # trails + water, no key needed
    python prep/fetch_terrain.py elevation    # needs OPENTOPO_API_KEY
    python prep/fetch_terrain.py arrays       # builds whatever inputs exist
    python prep/fetch_terrain.py all

The arrays are baked into the Daytona snapshot, so workers need numpy only --
no geopandas, no OSMnx, no rasterio inside a sandbox.

NOTE on rasterio: this machine has Smart App Control ENFORCED, which blocks the
GDAL native DLLs that rasterio and fiona load. Both pip-install fine and then
fail at import. We read the GeoTIFF with tifffile (pure Python) and write
GeoJSON with gdf.to_json() instead. No functional difference here.

Writes: data/trails.graphml, data/trails.geojson, data/water.geojson,
        data/dem.tif, data/elevation.npy, data/slope.npy,
        data/trail_dist.npy, data/water_dist.npy, data/meta.json
"""
from __future__ import annotations

import json, math, os, sys, time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

CELL_M = 30           # keeps four arrays near 34 MB for this box
OPENTOPO_URL = "https://portal.opentopography.org/API/usgsdem"
OPENTOPO_DATASET = "USGS10m"     # USGS 3DEP 1/3 arc-second, ~10 m

# Display trails. The full 'all' network includes northern Tucson's street grid
# -- 86,363 of the 105,236 walkable ways in this box are urban `footway`, i.e.
# pavements. Correct for movement, ruinous to draw. The frontend gets only the
# ways a lost subject in the mountains would actually be on.
FOOT_TAGS = {"path", "track", "bridleway", "steps"}

# ~5 m in degrees at this latitude. Trails are drawn at 30 m cells and rendered
# on a map, so vertices finer than this are invisible weight.
SIMPLIFY_DEG = 5e-5


def load_bbox():
    return json.load(open(DATA / "bbox.json"))


def grid_spec(bbox, cell_m=CELL_M):
    """Row 0 is NORTH. Bounds are the outer edges of the corner cells."""
    mid = (bbox["north"] + bbox["south"]) / 2
    m_lat = 110_574.0
    m_lon = 111_320.0 * math.cos(math.radians(mid))
    rows = int(round((bbox["north"] - bbox["south"]) * m_lat / cell_m))
    cols = int(round((bbox["east"] - bbox["west"]) * m_lon / cell_m))
    return {
        "bounds": {k: bbox[k] for k in ("north", "south", "east", "west")},
        "shape": [rows, cols],
        "cell_m": cell_m,
        "row0": "north",
        "col0": "west",
        "crs": "EPSG:4326",
        "m_per_deg_lat": round(m_lat, 3),
        "m_per_deg_lon": round(m_lon, 3),
        "note": ("Row-major. grid[0] is the north edge, grid[r][0] the west "
                 "edge. Cells are square in metres by construction, so the "
                 "grid is slightly anisotropic in degrees."),
    }


def rowcol(spec, lat, lon):
    b, (rows, cols) = spec["bounds"], spec["shape"]
    r = (b["north"] - lat) / (b["north"] - b["south"]) * rows
    c = (lon - b["west"]) / (b["east"] - b["west"]) * cols
    return r, c


# --------------------------------------------------------------------------
# stage: osm
# --------------------------------------------------------------------------
def stage_osm(bbox):
    import osmnx as ox
    import geopandas as gpd

    ox.settings.log_console = False
    ox.settings.requests_timeout = 300
    ox.settings.use_cache = True
    ox.settings.cache_folder = str(ROOT / "prep" / ".osm_cache")

    # OSMnx 2.x takes bbox as (left, bottom, right, top) = (W, S, E, N).
    bb = (bbox["west"], bbox["south"], bbox["east"], bbox["north"])

    print("downloading movement network (network_type='all')...")
    t0 = time.time()
    G = ox.graph_from_bbox(bb, network_type="all", simplify=True,
                           retain_all=True, truncate_by_edge=True)
    print("  {} nodes, {} edges in {:.0f}s".format(
        G.number_of_nodes(), G.number_of_edges(), time.time() - t0))

    ox.save_graphml(G, DATA / "trails.graphml")
    print("  wrote data/trails.graphml  {:.1f} MB".format(
        (DATA / "trails.graphml").stat().st_size / 1e6))

    edges = ox.graph_to_gdfs(G, nodes=False, edges=True)
    spec = grid_spec(bbox)

    # trail_dist is rasterised from the FULL network -- a subject walks a dirt
    # road as readily as a marked trail. Written straight to a mask rather than
    # via a 110 MB intermediate GeoJSON nobody reads.
    mask, n = rasterise_geoms(edges.geometry, spec)
    np.save(DATA / "_trail_mask.npy", mask)
    print("  rasterised {} ways -> _trail_mask.npy ({:.1f}% of cells)".format(
        n, 100 * mask.mean()))

    def is_foot(hw):
        vals = hw if isinstance(hw, list) else [hw]
        return any(str(v) in FOOT_TAGS for v in vals)

    foot = edges[edges["highway"].apply(is_foot)].copy()
    keep = [c for c in ("highway", "name", "surface") if c in foot.columns]
    foot = foot[keep + ["geometry"]]
    foot["geometry"] = foot.geometry.simplify(SIMPLIFY_DEG, preserve_topology=False)
    foot = foot[~foot.geometry.is_empty & foot.geometry.notna()]
    for c in keep:                       # lists are not JSON-serialisable
        foot[c] = foot[c].apply(lambda v: ", ".join(map(str, v))
                                if isinstance(v, list) else v)
    write_geojson(DATA / "trails.geojson", foot)
    print("  wrote data/trails.geojson  {} wilderness ways ({}), {:.1f} MB".format(
        len(foot), "/".join(sorted(FOOT_TAGS)),
        (DATA / "trails.geojson").stat().st_size / 1e6))

    print("downloading watercourses...")
    water = ox.features_from_bbox(bb, tags={"waterway": True})
    water = water[water.geometry.type.isin(["LineString", "MultiLineString"])].copy()
    keep = [c for c in ("waterway", "name", "intermittent") if c in water.columns]
    water = water[keep + ["geometry"]]
    for c in keep:
        water[c] = water[c].apply(lambda v: ", ".join(map(str, v))
                                  if isinstance(v, list) else v)
    wmask, wn = rasterise_geoms(water.geometry, spec)
    np.save(DATA / "_water_mask.npy", wmask)
    print("  rasterised {} watercourses -> _water_mask.npy ({:.1f}% of cells)"
          .format(wn, 100 * wmask.mean()))

    water["geometry"] = water.geometry.simplify(SIMPLIFY_DEG, preserve_topology=False)
    water = water[~water.geometry.is_empty & water.geometry.notna()]
    write_geojson(DATA / "water.geojson", water)
    print("  wrote data/water.geojson   {} watercourses, {:.1f} MB".format(
        len(water), (DATA / "water.geojson").stat().st_size / 1e6))


def write_geojson(path, gdf, ndigits=5):
    """Round coordinates before writing. 5 dp is ~1.1 m here; full float
    precision roughly doubles the file for no visible gain."""
    gj = json.loads(gdf.to_json())

    def rnd(o):
        if isinstance(o, float):
            return round(o, ndigits)
        if isinstance(o, list):
            return [rnd(x) for x in o]
        return o

    for f in gj.get("features", []):
        f.pop("id", None)
        if f.get("geometry"):
            f["geometry"]["coordinates"] = rnd(f["geometry"]["coordinates"])
        f["properties"] = {k: v for k, v in (f.get("properties") or {}).items()
                           if v is not None}
    path.write_text(json.dumps(gj, separators=(",", ":")), encoding="utf-8")


def rasterise_geoms(geoms, spec):
    """Mark every grid cell a shapely line passes through."""
    rows, cols = spec["shape"]
    mask = np.zeros((rows, cols), dtype=bool)
    b = spec["bounds"]
    step_lat = (b["north"] - b["south"]) / rows
    step_lon = (b["east"] - b["west"]) / cols
    n = 0
    for geom in geoms:
        if geom is None or geom.is_empty:
            continue
        parts = geom.geoms if geom.geom_type.startswith("Multi") else [geom]
        for part in parts:
            coords = list(part.coords)
            if len(coords) < 2:
                continue
            n += 1
            for (lon1, lat1), (lon2, lat2) in zip(coords, coords[1:]):
                steps = int(max(abs(lat2 - lat1) / step_lat,
                                abs(lon2 - lon1) / step_lon)) + 1
                for i in range(steps + 1):
                    f = i / steps
                    r, c = rowcol(spec, lat1 + (lat2 - lat1) * f,
                                  lon1 + (lon2 - lon1) * f)
                    ri, ci = int(r), int(c)
                    if 0 <= ri < rows and 0 <= ci < cols:
                        mask[ri, ci] = True
    return mask, n


# --------------------------------------------------------------------------
# stage: elevation
# --------------------------------------------------------------------------
def stage_elevation(bbox):
    import requests

    key = os.environ.get("OPENTOPO_API_KEY", "").strip()
    if not key:
        env = ROOT / ".env"
        if env.exists():
            for line in env.read_text(encoding="utf-8").splitlines():
                if line.startswith("OPENTOPO_API_KEY="):
                    key = line.split("=", 1)[1].strip()
    if not key:
        print("SKIP elevation: no OPENTOPO_API_KEY in environment or .env")
        print("  Get one free at https://opentopography.org (My Account -> API key)")
        print("  then:  python prep/fetch_terrain.py elevation")
        return False

    params = {"datasetName": OPENTOPO_DATASET, "API_Key": key,
              "west": bbox["west"], "east": bbox["east"],
              "south": bbox["south"], "north": bbox["north"],
              "outputFormat": "GTiff"}
    print("requesting {} from OpenTopography...".format(OPENTOPO_DATASET))
    r = requests.get(OPENTOPO_URL, params=params, timeout=600, stream=True)
    if r.status_code != 200:
        print("  FAILED {} - {}".format(r.status_code, r.text[:400]))
        return False
    out = DATA / "dem.tif"
    with open(out, "wb") as fh:
        for chunk in r.iter_content(1 << 20):
            fh.write(chunk)
    print("  wrote data/dem.tif  {:.1f} MB".format(out.stat().st_size / 1e6))
    return True


# --------------------------------------------------------------------------
# stage: arrays
# --------------------------------------------------------------------------
def stage_arrays(bbox):
    from scipy.ndimage import distance_transform_edt

    spec = grid_spec(bbox)
    rows, cols = spec["shape"]
    print("grid {} x {} at {} m/cell  ({:.2f}M cells)".format(
        rows, cols, spec["cell_m"], rows * cols / 1e6))

    written = []

    dem_path = DATA / "dem.tif"
    if dem_path.exists():
        import tifffile
        raw = tifffile.imread(str(dem_path)).astype(np.float32)
        if raw.ndim == 3:
            raw = raw[0]
        # DEM nodata is a large negative sentinel; fill with the local minimum
        # so slope does not explode at the edges.
        raw = np.where(raw < -1e4, np.nan, raw)
        if np.isnan(raw).any():
            raw = np.where(np.isnan(raw), np.nanmin(raw), raw)
        # Resample to our grid with nearest neighbour. The DEM is ~10 m and we
        # want 30 m, so this is a plain decimation.
        ri = np.clip((np.arange(rows) + 0.5) * raw.shape[0] / rows, 0,
                     raw.shape[0] - 1).astype(int)
        ci = np.clip((np.arange(cols) + 0.5) * raw.shape[1] / cols, 0,
                     raw.shape[1] - 1).astype(int)
        elev = np.ascontiguousarray(raw[np.ix_(ri, ci)], dtype=np.float32)
        np.save(DATA / "elevation.npy", elev)
        written.append("elevation.npy")
        print("  elevation {:.0f}..{:.0f} m  (relief {:.0f} m)".format(
            elev.min(), elev.max(), elev.max() - elev.min()))

        gy, gx = np.gradient(elev.astype(np.float64), spec["cell_m"])
        slope = np.degrees(np.arctan(np.hypot(gx, gy))).astype(np.float32)
        np.save(DATA / "slope.npy", slope)
        written.append("slope.npy")
        print("  slope mean {:.1f} deg, max {:.1f} deg".format(
            float(slope.mean()), float(slope.max())))
    else:
        print("  SKIP elevation.npy / slope.npy - data/dem.tif not present")

    for name, src in (("trail_dist.npy", DATA / "_trail_mask.npy"),
                      ("water_dist.npy", DATA / "_water_mask.npy")):
        if not src.exists():
            print("  SKIP {} - {} missing, run the osm stage first"
                  .format(name, src.name))
            continue
        mask = np.load(src)
        if mask.shape != (rows, cols):
            print("  SKIP {} - mask is {} but grid is {}; re-run the osm stage"
                  .format(name, mask.shape, (rows, cols)))
            continue
        if not mask.any():
            print("  SKIP {} - mask is empty".format(name))
            continue
        dist = (distance_transform_edt(~mask) * spec["cell_m"]).astype(np.float32)
        np.save(DATA / name, dist)
        written.append(name)
        print("  {:<15} {:.1f}% of cells on a line, median {:.0f} m, max {:.0f} m"
              .format(name, 100 * mask.mean(), float(np.median(dist)),
                      float(dist.max())))

    spec["arrays"] = written
    spec["source"] = {
        "elevation": "USGS 3DEP 1/3 arc-second via OpenTopography ({})".format(
            OPENTOPO_DATASET),
        "trails_water": "OpenStreetMap via OSMnx, network_type='all'",
        "bbox": "data/bbox.json",
    }
    json.dump(spec, open(DATA / "meta.json", "w"), indent=2)

    total = sum((DATA / w).stat().st_size for w in written)
    print("  wrote data/meta.json")
    print("  {} array(s), {:.1f} MB total{}".format(
        len(written), total / 1e6,
        "  <-- over the 50 MB snapshot budget" if total > 50e6 else ""))


def main():
    stage = sys.argv[1] if len(sys.argv) > 1 else "all"
    bbox = load_bbox()
    print("bbox {} -- {:.1f} x {:.1f} km".format(
        bbox["region"], bbox["width_km"], bbox["height_km"]))
    if stage in ("osm", "all"):
        stage_osm(bbox)
    if stage in ("elevation", "all"):
        stage_elevation(bbox)
    if stage in ("arrays", "all"):
        stage_arrays(bbox)


if __name__ == "__main__":
    main()
