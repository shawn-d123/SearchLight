"""TASK 4 - generate the mock payloads Person A builds against.

Person A cannot start without these. They only need the right SHAPE, so the
movement model here is a crude corridor-biased random walk, not the real thing.
Everything is deterministic (fixed seed) so re-running produces byte-identical
files and never churns the diff.

Grids are REAL base64 float32, not placeholders, so A's decode path is exercised
for real. `field_area_pct` is computed through model/field.py -- the same code
production uses -- so the headline number cannot drift between mock and live.

Usage:  python prep/make_mocks.py [--runs-per-batch N]

Writes: mocks/case.json
        mocks/trajectories.json
        mocks/field.json
        mocks/field_partial.json
        mocks/field_collapsed.json
        mocks/fleet_status.json
"""
from __future__ import annotations

import argparse, base64, csv, json, math, sys
from pathlib import Path

import numpy as np
from scipy.ndimage import gaussian_filter

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from model.field import field_area_pct, normalise_for_display  # noqa: E402

DATA, MOCKS = ROOT / "data", ROOT / "mocks"

SEED = 20260830
RESOLUTION = 256
N_BATCHES = 200
RUNS_PER_BATCH = 12      # live is 60; see note in case.json
POINTS_PER_RUN = 34      # contract caps at 60
FAIL_RATE = 0.05

# Demo case. A real historical Hiker incident inside the chosen box, with a
# 6.6 km displacement -- long enough that the field has somewhere to go.
DEMO_CASE = "Arizona80"

FAMILIES = {
    "route_travelling": 0.41,
    "direction_sampling": 0.29,
    "backtracking": 0.17,
    "view_enhancing": 0.08,
    "staying_put": 0.05,
}

# Witness report used to build field_collapsed.json. Spatial AND temporal.
EVIDENCE = {
    "location": None,          # filled in below, on the eastern corridor
    "t_s": 5400,
    "radius_m": 900.0,
    "tolerance_s": 1800,
    "description": "Reported sighting - red jacket, eastern drainage",
}


def load_inputs():
    bbox = json.load(open(DATA / "bbox.json"))
    priors = json.load(open(DATA / "priors.json"))
    rows = list(csv.DictReader(open(DATA / "cases.csv", encoding="utf-8")))
    case = next(r for r in rows if r["case_id"] == DEMO_CASE)
    return bbox, priors, case


def m_per_deg(lat):
    return 110_574.0, 111_320.0 * math.cos(math.radians(lat))


def simulate(bbox, ipp, rng, runs_per_batch):
    """Corridor-biased random walk. Crude on purpose -- shape is what matters.

    Two 'drainage' corridors radiate from the IPP so endpoints cluster into two
    zones rather than a symmetric blob. That lets A tune the colour ramp against
    something shaped like the real thing.
    """
    lat0, lon0 = ipp
    mlat, mlon = m_per_deg(lat0)

    # Corridor bearings, degrees clockwise from north. Roughly the two valleys
    # a subject leaving this IPP would actually follow.
    corridors = (155.0, 65.0)

    batches, fam_names = [], list(FAMILIES)
    fam_w = np.array([FAMILIES[f] for f in fam_names], dtype=float)
    fam_w /= fam_w.sum()

    for b in range(N_BATCHES):
        family = fam_names[int(rng.choice(len(fam_names), p=fam_w))]
        corridor = corridors[b % len(corridors)]
        # ~5% of sandboxes fall back to the deterministic template because the
        # generated script failed. Counted on screen, not hidden.
        generated = bool(rng.random() > FAIL_RATE)

        runs = []
        for r in range(runs_per_batch):
            # Failure is per RUN and independent of `generated`: a script can be
            # model-written and still walk off the grid or time out. Roughly
            # FAIL_RATE of all runs fail, which is what the rail counts.
            if rng.random() < FAIL_RATE:
                runs.append({"run_index": r, "points": [], "endpoint": None,
                             "duration_s": 0, "status": "failed"})
                continue

            # Family sets speed, persistence and total duration.
            if family == "staying_put":
                speed, persist, dur = 0.15, 0.98, 3600
            elif family == "route_travelling":
                speed, persist, dur = 1.15, 0.94, 14400
            elif family == "direction_sampling":
                speed, persist, dur = 0.85, 0.75, 10800
            elif family == "backtracking":
                speed, persist, dur = 0.70, 0.60, 9000
            else:  # view_enhancing
                speed, persist, dur = 0.55, 0.80, 7200

            bearing = math.radians(corridor + rng.normal(0, 28))
            lat, lon = lat0, lon0
            dt = dur / (POINTS_PER_RUN - 1)
            pts = [[round(lat, 6), round(lon, 6), 0]]

            for i in range(1, POINTS_PER_RUN):
                bearing = (persist * bearing
                           + (1 - persist) * math.radians(corridor + rng.normal(0, 45))
                           + rng.normal(0, 0.20))
                if family == "backtracking" and i > POINTS_PER_RUN * 0.55:
                    bearing += math.pi          # turn around and head back
                step = max(0.0, rng.normal(speed, speed * 0.35)) * dt  # metres
                lat += (step * math.cos(bearing)) / mlat
                lon += (step * math.sin(bearing)) / mlon
                lat = min(max(lat, bbox["south"] + 1e-4), bbox["north"] - 1e-4)
                lon = min(max(lon, bbox["west"] + 1e-4), bbox["east"] - 1e-4)
                pts.append([round(lat, 6), round(lon, 6), int(round(i * dt))])

            runs.append({"run_index": r, "points": pts,
                         "endpoint": [pts[-1][0], pts[-1][1]],
                         "duration_s": int(dur), "status": "ok"})

        batches.append({
            "hypothesis_id": "h_{:05d}".format(b),
            "family": family,
            "weight": round(float(FAMILIES[family]), 4),
            "generated": generated,
            "runs": runs,
        })
    return batches


def cell_area_m2(bbox, resolution):
    mid = (bbox["north"] + bbox["south"]) / 2
    mlat, mlon = m_per_deg(mid)
    h = (bbox["north"] - bbox["south"]) / resolution * mlat
    w = (bbox["east"] - bbox["west"]) / resolution * mlon
    return w * h


def rasterise(batches, bbox, resolution, sigma):
    """Gaussian-splat KDE over trajectory endpoints, weighted by family prior.

    NOTE: this is the mock's own crude aggregator. The real one is
    model/field.py::build_field, built Sunday. Deliberately not shared.
    """
    acc = np.zeros((resolution, resolution), dtype=np.float64)
    n_total = n_ok = 0
    for batch in batches:
        w = batch["weight"]
        for run in batch["runs"]:
            n_total += 1
            if run["status"] != "ok" or not run["endpoint"]:
                continue
            n_ok += 1
            lat, lon = run["endpoint"]
            # row 0 is NORTH -- see CONTRACT.md
            row = (bbox["north"] - lat) / (bbox["north"] - bbox["south"]) * resolution
            col = (lon - bbox["west"]) / (bbox["east"] - bbox["west"]) * resolution
            r, c = int(row), int(col)
            if 0 <= r < resolution and 0 <= c < resolution:
                acc[r, c] += w
    return gaussian_filter(acc, sigma=sigma, mode="constant"), n_total, n_ok


def find_zones(grid, bbox, k=2, suppress=28):
    """Top-k density peaks with the share of total mass around each."""
    g = grid.copy()
    res = grid.shape[0]
    total = g.sum()
    zones = []
    for _ in range(k):
        r, c = np.unravel_index(int(np.argmax(g)), g.shape)
        r0, r1 = max(0, r - suppress), min(res, r + suppress + 1)
        c0, c1 = max(0, c - suppress), min(res, c + suppress + 1)
        pct = float(grid[r0:r1, c0:c1].sum() / total * 100) if total > 0 else 0.0
        lat = bbox["north"] - (r + 0.5) / res * (bbox["north"] - bbox["south"])
        lon = bbox["west"] + (c + 0.5) / res * (bbox["east"] - bbox["west"])
        zones.append({"row": r, "col": c, "pct": round(pct, 1),
                      "centroid": [round(lat, 6), round(lon, 6)]})
        g[r0:r1, c0:c1] = 0.0
    return zones


def name_zones(zones, ipp):
    """Compass-relative placeholder names.

    Real names come from the terrain on Sunday. These are geometric, so they
    are at least not wrong -- but they are not landmark names.
    """
    out = []
    for z in zones:
        dlat = z["centroid"][0] - ipp[0]
        dlon = z["centroid"][1] - ipp[1]
        ns = "North" if dlat > 0 else "South"
        ew = "east" if dlon > 0 else "west"
        primary = ns if abs(dlat) >= abs(dlon) else ("East" if dlon > 0 else "West")
        secondary = ew if abs(dlat) >= abs(dlon) else ns.lower()
        out.append({"name": "{} {}".format(primary, secondary),
                    "pct": z["pct"], "centroid": z["centroid"]})
    return out


def encode(grid):
    return base64.b64encode(
        np.ascontiguousarray(grid, dtype=np.float32).tobytes()).decode("ascii")


def field_payload(grid, bbox, priors, progress, n_total, n_consistent, ipp):
    disp = normalise_for_display(grid)
    ring_m = priors["ring_radius_km"] * 1000.0
    area_pct = field_area_pct(grid, cell_area_m2(bbox, RESOLUTION), ring_m)
    return {
        "bounds": {k: bbox[k] for k in ("north", "south", "east", "west")},
        "resolution": RESOLUTION,
        "grid": encode(disp),
        "progress": round(progress, 3),
        "zones": name_zones(find_zones(grid, bbox), ipp),
        "n_total": n_total,
        "n_consistent": n_consistent,
        "ring_radius_m": round(ring_m, 1),
        "field_area_pct": round(area_pct, 1),
    }


def filter_evidence(batches, ev):
    """Keep runs that passed near the sighting at roughly the right time."""
    lat0, lon0 = ev["location"]
    mlat, mlon = m_per_deg(lat0)
    kept = []
    for b in batches:
        runs = []
        for run in b["runs"]:
            if run["status"] != "ok":
                continue
            for lat, lon, t in run["points"]:
                if abs(t - ev["t_s"]) > ev["tolerance_s"]:
                    continue
                dy, dx = (lat - lat0) * mlat, (lon - lon0) * mlon
                if math.hypot(dx, dy) <= ev["radius_m"]:
                    runs.append(run)
                    break
        if runs:
            kept.append(dict(b, runs=runs))
    return kept


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs-per-batch", type=int, default=RUNS_PER_BATCH)
    args = ap.parse_args()

    bbox, priors, case = load_inputs()
    MOCKS.mkdir(exist_ok=True)
    ipp = [float(case["ipp_lat"]), float(case["ipp_lon"])]
    rng = np.random.default_rng(SEED)

    print("demo case {}  IPP {:.5f}, {:.5f}".format(DEMO_CASE, *ipp))
    batches = simulate(bbox, ipp, rng, args.runs_per_batch)
    n_runs = sum(len(b["runs"]) for b in batches)
    n_fail = sum(1 for b in batches for r in b["runs"] if r["status"] != "ok")
    print("  {} batches, {} runs, {} failed ({:.1f}%)".format(
        len(batches), n_runs, n_fail, 100 * n_fail / n_runs))

    # Put the witness sighting on a real trajectory so the filter keeps a
    # sensible fraction rather than an arbitrary one.
    donor = next(r for b in batches if b["family"] == "route_travelling"
                 for r in b["runs"] if r["status"] == "ok")
    mid = min(donor["points"], key=lambda p: abs(p[2] - EVIDENCE["t_s"]))
    EVIDENCE["location"] = [mid[0], mid[1]]

    # Widen the sighting radius until roughly a third of runs survive. The demo
    # beat needs most of the map to go dark while the surviving count stays
    # credible; the spec pitch quotes 12,000 -> 3,800, i.e. ~32%. This is a
    # MOCK, so the radius is chosen to produce a representative collapse rather
    # than measured from anything. The real filter is model/field.py.
    n_ok_all = sum(1 for b in batches for r in b["runs"] if r["status"] == "ok")
    for radius in range(500, 12001, 250):
        EVIDENCE["radius_m"] = float(radius)
        if sum(len(b["runs"]) for b in filter_evidence(batches, EVIDENCE)) \
                >= 0.33 * n_ok_all:
            break
    EVIDENCE["radius_m_note"] = ("tuned so ~1/3 of mock runs survive, matching "
                                 "the demo beat. Not a measured quantity.")

    full, n_total, n_ok = rasterise(batches, bbox, RESOLUTION, sigma=3.4)
    partial, _, _ = rasterise(batches[:70], bbox, RESOLUTION, sigma=7.0)
    kept = filter_evidence(batches, EVIDENCE)
    n_cons = sum(len(b["runs"]) for b in kept)
    collapsed, _, _ = rasterise(kept, bbox, RESOLUTION, sigma=2.6)

    print("  evidence at {:.5f}, {:.5f} t={}s -> {} of {} runs consistent "
          "({:.0f}%)".format(*EVIDENCE["location"], EVIDENCE["t_s"],
                             n_cons, n_ok, 100 * n_cons / n_ok))

    payloads = {
        "field.json": field_payload(full, bbox, priors, 1.0, n_total, n_ok, ipp),
        "field_partial.json": field_payload(partial, bbox, priors, 0.35,
                                            n_total, n_ok, ipp),
        "field_collapsed.json": field_payload(collapsed, bbox, priors, 1.0,
                                              n_total, n_cons, ipp),
    }
    payloads["field_collapsed.json"]["evidence"] = EVIDENCE

    case_payload = {
        "case_id": DEMO_CASE,
        "subject_name": "SUBJECT AZ-80",
        "subject_name_note": ("Case designator, not a person's name. The source "
                              "records carry no personal details and none are "
                              "invented here."),
        "subject_category": case["category"],
        "terrain": case["terrain"],
        "last_contact_s_ago": 4320,
        "last_contact_display": "72 min",
        "ipp": ipp,
        "ring_radius_m": round(priors["ring_radius_km"] * 1000.0, 1),
        "ring_label": priors["ring_label"],
        "bounds": {k: bbox[k] for k in ("north", "south", "east", "west")},
        "region": bbox["region"],
        "find_location": [float(case["find_lat"]), float(case["find_lon"])],
        "find_location_note": ("Ground truth. For validation scoring only -- "
                               "never render this before the reveal."),
        "n_hypotheses": len(batches),
        "runs_per_batch": args.runs_per_batch,
        "runs_per_batch_note": ("Live is 60 per sandbox (200 x 60 = 12,000). "
                                "Mocks ship fewer to keep the file loadable; "
                                "regenerate with --runs-per-batch 60 to stress "
                                "test the TripsLayer."),
        "source": bbox["source"],
    }

    frames, target = [], len(batches)
    for i in range(20):
        f = (i + 1) / 20
        ready = int(target * min(1.0, f * 1.35))
        done = int(target * max(0.0, f * 1.15 - 0.15))
        frames.append({
            "elapsed_s": round(i * 0.5, 1),
            "sandboxes_requested": target,
            "sandboxes_ready": ready,
            "sandboxes_active": max(0, ready - done),
            "hypotheses_completed": done,
            "runs_completed": done * args.runs_per_batch,
            "runs_failed": int(done * args.runs_per_batch * FAIL_RATE),
            "progress": round(f, 3),
        })

    out = {"case.json": case_payload, "fleet_status.json": frames,
           "trajectories.json": batches, **payloads}

    # Next.js serves /public, so the frontend needs its own copy. Written here
    # rather than copied by hand so the two can never drift apart.
    public = ROOT / "frontend" / "public" / "mocks"
    public.mkdir(parents=True, exist_ok=True)

    for name, obj in out.items():
        compact = "traj" in name
        text = json.dumps(obj, separators=(",", ":")) if compact \
            else json.dumps(obj, indent=2)
        for d in (MOCKS, public):
            (d / name).write_text(text, encoding="utf-8")
        print("  wrote {:<22} {:>8.1f} KB  (mocks/ and frontend/public/mocks/)"
              .format(name, (MOCKS / name).stat().st_size / 1024))

    # bbox.json is imported directly by frontend/lib/config.ts.
    (ROOT / "frontend" / "lib" / "bbox.json").write_text(
        (DATA / "bbox.json").read_text(encoding="utf-8"), encoding="utf-8")

    print("  field_area_pct: full {}%  partial {}%  collapsed {}%".format(
        payloads["field.json"]["field_area_pct"],
        payloads["field_partial.json"]["field_area_pct"],
        payloads["field_collapsed.json"]["field_area_pct"]))


if __name__ == "__main__":
    main()
