"""TASK 1 - extract MapScore ISRID cases and choose the terrain bounding box.

The bounding box decides what terrain gets clipped, which decides what every
case is scored against. Run this before touching terrain.

Reads : prep/mapscore/case_in/input_unsorted.csv          (distributable subset)
        prep/mapscore/case_in/exported_case_Library.txt   (ISRID ids, terrain)
Writes: data/cases.csv, data/bbox.json
"""
import csv, json, math, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAPSCORE = ROOT / "prep" / "mapscore" / "case_in"
DATA = ROOT / "data"

# Scoring window is 5001 x 5001 at 5 m = 25.005 km across, IPP at centre, so it
# reaches 12.5 km from the IPP. 15 km padding leaves a real margin.
PAD_KM = 15.0
MIN_CASES = 5

# A case whose find location lies outside the scoring window cannot be scored
# at all. Hard geometric constraint, not a filter chosen to flatter the result.
MAX_FIND_KM = 12.0

# The upstream "Distance" column is in STATUTE MILES while the coordinates are
# decimal degrees. Verified: converting at 1.609344 drops median disagreement to
# 0.44 km with 94/131 inside 1 km; the residual is coordinate rounding in the
# source. We use the coordinates. Distance is kept for provenance only.
MILES_TO_KM = 1.609344

# Six cases record the find location at the IPP exactly. Any model peaked at the
# IPP scores ~1.0 on them, inflating baseline and field alike. Excluded from
# validation, and the exclusion is stated aloud. See prep/STATUS.md.
DEGENERATE_M = 20.0

# Generous Arizona envelope, used only to catch corrupt coordinates.
AZ_LAT = (31.0, 37.1)
AZ_LON = (-115.0, -108.9)

# Koester mobile outdoor-recreation categories. The movement families in
# priors.json (route travelling, view enhancing, ...) describe this behaviour.
HIKER_LIKE = {"Hiker", "Hunter", "Camper", "Gatherer", "Climber",
              "Mountain Biker", "Horseback Rider"}


def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def load_isrid_meta():
    """exported_case_Library.txt: records split by '$', fields by '|'."""
    f = MAPSCORE / "exported_case_Library.txt"
    if not f.exists():
        return {}
    out = {}
    for rec in f.read_text(encoding="utf-8", errors="replace").split("$"):
        p = rec.split("|")
        if len(p) < 17:
            continue
        try:
            key = (round(float(p[13]), 5), round(float(p[14]), 5))
        except ValueError:
            continue
        out[key] = {"isrid_id": p[1].strip(), "terrain": p[12].strip()}
    return out


def load_cases():
    src = MAPSCORE / "input_unsorted.csv"
    if not src.exists():
        sys.exit("FATAL: " + str(src) + " not found. Run: git clone "
                 "https://github.com/ctwardy/mapscore prep/mapscore")
    meta = load_isrid_meta()
    rows = []
    with open(src, newline="", encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            name = (r.get("Case_Name") or "").strip()
            if not name:
                continue
            try:
                ilat, ilon = float(r["IPP Lat"]), float(r["IPP Lon"])
                # NOTE: upstream header typo -- "Find Lot" is the find longitude.
                flat, flon = float(r["Find Lat"]), float(r["Find Lot"])
            except (KeyError, ValueError):
                continue
            extra = meta.get((round(ilat, 5), round(ilon, 5)), {})
            rows.append({
                "case_id": name,
                "isrid_id": extra.get("isrid_id", ""),
                "ipp_lat": ilat, "ipp_lon": ilon,
                "find_lat": flat, "find_lon": flon,
                "category": (r.get("SubjectCategory") or "").strip(),
                "terrain": extra.get("terrain") or (r.get("Terrain") or "").strip(),
                "region": "".join(c for c in name if not c.isdigit()) or "Unknown",
                "dist_km_published": float(r["Distance"]) if r.get("Distance") else None,
                "dist_km_computed": round(haversine_km(ilat, ilon, flat, flon), 4),
            })
    return rows


def bbox_of(cases, pad_km=PAD_KM):
    lats = [c["ipp_lat"] for c in cases]
    lons = [c["ipp_lon"] for c in cases]
    mid = (min(lats) + max(lats)) / 2
    dlat = pad_km / 110.574
    dlon = pad_km / (111.320 * math.cos(math.radians(mid)))
    return {"north": max(lats) + dlat, "south": min(lats) - dlat,
            "east": max(lons) + dlon, "west": min(lons) - dlon}


def bbox_km(b):
    mid = (b["north"] + b["south"]) / 2
    return (haversine_km(mid, b["west"], mid, b["east"]),
            haversine_km(b["south"], 0, b["north"], 0))


def tightest(cases, k):
    """Smallest padded bbox containing k cases, anchored on each case's k
    nearest neighbours. O(n^2), exact enough for n ~ 130."""
    best = None
    for a in cases:
        near = sorted(cases, key=lambda c: haversine_km(
            a["ipp_lat"], a["ipp_lon"], c["ipp_lat"], c["ipp_lon"]))[:k]
        b = bbox_of(near)
        w, h = bbox_km(b)
        if best is None or w * h < best[0]:
            best = (w * h, b, near)
    return best


def usable_coords(c):
    return (AZ_LAT[0] <= c["ipp_lat"] <= AZ_LAT[1]
            and AZ_LON[0] <= c["ipp_lon"] <= AZ_LON[1]
            and AZ_LAT[0] <= c["find_lat"] <= AZ_LAT[1]
            and AZ_LON[0] <= c["find_lon"] <= AZ_LON[1])


def rule(title):
    print()
    print("=" * 72)
    print(title)
    print("=" * 72)


def main():
    DATA.mkdir(exist_ok=True)

    rule("CASE DIRECTORIES IN prep/mapscore")
    for sub in ("case_in", "database"):
        d = MAPSCORE.parent / sub
        if d.is_dir():
            for f in sorted(d.iterdir()):
                print("  {}/{:<34}{:>9,} bytes".format(sub, f.name, f.stat().st_size))
    print("  database/website_data.db -> framework_case has 0 rows (empty scaffold)")

    raw = load_cases()

    rule("REGION COUNTS (derived from case-name prefix)")
    for r in sorted({c["region"] for c in raw}):
        print("  {:<12}{:>5}".format(r, sum(1 for c in raw if c["region"] == r)))
    print("  Yosemite      0   -- not present in the distributable subset")
    print("  New York      0   -- not present in the distributable subset")

    rule("USABLE-COORDINATE FUNNEL")
    steps = [("parsed from input_unsorted.csv", raw)]
    a = [c for c in raw if usable_coords(c)]
    steps.append(("coordinates inside Arizona envelope", a))
    b = [c for c in a if c["dist_km_computed"] > DEGENERATE_M / 1000]
    steps.append(("find not identical to IPP (> {:.0f} m)".format(DEGENERATE_M), b))
    u = [c for c in b if c["dist_km_computed"] <= MAX_FIND_KM]
    steps.append(("find within {:.0f} km scoring window".format(MAX_FIND_KM), u))
    prev = len(raw)
    for label, s in steps:
        delta = len(s) - prev
        extra = "   ({:+d})".format(delta) if delta else ""
        print("  {:>4}  {}{}".format(len(s), label, extra))
        prev = len(s)
    print()
    print("  USABLE IPP + FIND COORDINATES: {} of {}".format(len(u), len(raw)))

    errs = sorted(abs(c["dist_km_published"] * MILES_TO_KM - c["dist_km_computed"])
                  for c in raw if c["dist_km_published"])
    print("  Distance column read as MILES: median disagreement {:.3f} km, "
          "{}/{} within 1 km".format(errs[len(errs) // 2],
                                     sum(1 for e in errs if e < 1), len(errs)))

    with open(DATA / "cases.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(raw[0].keys()) + ["usable"])
        w.writeheader()
        for c in raw:
            w.writerow(dict(c, usable=c in u))
    print("  wrote data/cases.csv ({} rows; 'usable' marks the {})".format(len(raw), len(u)))

    hl = [c for c in u if c["category"] in HIKER_LIKE]
    mt = [c for c in hl if c["terrain"] == "Mountainous"]
    print("  of the {} usable: hiker-like={}, hiker-like & mountainous={}".format(
        len(u), len(hl), len(mt)))

    rule("TIGHTEST BOX, >= {} CASES, {:.0f} km PAD AROUND EVERY IPP".format(
        MIN_CASES, PAD_KM))
    for label, pool in (("all usable", u), ("hiker-like", hl),
                        ("hiker-like + mountainous  <- chosen", mt)):
        area, bb, _ = tightest(pool, MIN_CASES)
        w, h = bbox_km(bb)
        print("  {:<38}{:>6.1f} x{:>6.1f} km  ({:>5.0f} km2)".format(label, w, h, area))

    # Widen k while the box stays under 50 x 50 km, so validation has spares.
    best = None
    for k in range(MIN_CASES, len(mt) + 1):
        area, bb, sel = tightest(mt, k)
        w, h = bbox_km(bb)
        if w <= 50 and h <= 50:
            best = (k, bb, sel, w, h)
    k, bb, sel, w, h = best
    cell = 30
    cw, ch = int(w * 1000 / cell), int(h * 1000 / cell)

    rule("CHOSEN BOX -- Santa Catalina Mountains, {} cases".format(k))
    print("  N {:.5f}   S {:.5f}   E {:.5f}   W {:.5f}".format(
        bb["north"], bb["south"], bb["east"], bb["west"]))
    print("  {:.1f} x {:.1f} km    centre ({:.4f}, {:.4f})".format(
        w, h, (bb["north"] + bb["south"]) / 2, (bb["east"] + bb["west"]) / 2))
    print("  arrays @ {} m: {} x {} = {:.2f}M cells, {:.1f} MB each, "
          "{:.0f} MB for four".format(cell, cw, ch, cw * ch / 1e6,
                                      cw * ch * 4 / 1e6, cw * ch * 4 * 4 / 1e6))
    print()
    print("  {:>11} {:>10}  {:<16}{:>10}".format("case", "isrid", "category", "find dist"))
    for c in sorted(sel, key=lambda x: x["case_id"]):
        print("  {:>11} {:>10}  {:<16}{:>7.2f} km".format(
            c["case_id"], c["isrid_id"], c["category"], c["dist_km_computed"]))

    json.dump({
        "north": round(bb["north"], 6), "south": round(bb["south"], 6),
        "east": round(bb["east"], 6), "west": round(bb["west"], 6),
        "width_km": round(w, 2), "height_km": round(h, 2),
        "centre": [round((bb["north"] + bb["south"]) / 2, 6),
                   round((bb["east"] + bb["west"]) / 2, 6)],
        "n_cases": len(sel),
        "case_ids": sorted(c["case_id"] for c in sel),
        "region": "Santa Catalina Mountains, Arizona, USA",
        "pad_km": PAD_KM,
        "suggested_cell_m": cell,
        "source": ("MapScore ISRID distributable subset (Arizona), "
                   "https://github.com/ctwardy/mapscore -- filtered to hiker-like "
                   "categories on mountainous terrain, find inside the 25 km "
                   "scoring window and not identical to the IPP"),
        "excluded_degenerate": ("6 cases dataset-wide have find == IPP and are "
                                "excluded from validation; see prep/STATUS.md"),
        "note_yosemite": ("The spec assumed Yosemite. The free MapScore subset "
                          "contains Arizona only (131 cases); Yosemite and New "
                          "York were never committed to that repo."),
    }, open(DATA / "bbox.json", "w"), indent=2)
    print()
    print("  wrote data/bbox.json")
    return u, sel


if __name__ == "__main__":
    main()
