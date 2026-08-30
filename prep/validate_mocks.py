"""Check every mock against CONTRACT.md. Run after any change to either.

Exists because the contract is frozen at 10:45 and the mocks are what Person A
builds against until 14:30. If they disagree, that is discovered at the hard
integration point with no time to fix it. This turns that into a failing check.

Usage:  python prep/validate_mocks.py     (exit 0 = clean, 1 = violations)
"""
from __future__ import annotations

import base64, json, math, sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
DATA, MOCKS = ROOT / "data", ROOT / "mocks"

FAMILIES = {"route_travelling", "direction_sampling", "backtracking",
            "view_enhancing", "staying_put"}
MAX_POINTS = 60          # contract: points downsampled to <= 60 per run
MAX_BATCH = 200          # contract: max 200 trajectories per WS message
RESOLUTION = 256

fails: list[str] = []
warns: list[str] = []


def bad(msg):
    fails.append(msg)


def warn(msg):
    warns.append(msg)


def check(cond, msg):
    if not cond:
        bad(msg)
    return cond


def inside(bbox, lat, lon, slack=1e-6):
    return (bbox["south"] - slack <= lat <= bbox["north"] + slack
            and bbox["west"] - slack <= lon <= bbox["east"] + slack)


def check_field(name, f, bbox):
    for k in ("bounds", "resolution", "grid", "progress", "zones",
              "n_total", "n_consistent", "ring_radius_m", "field_area_pct"):
        check(k in f, "{}: missing required key '{}'".format(name, k))
    if fails:
        return

    for k in ("north", "south", "east", "west"):
        check(abs(f["bounds"][k] - bbox[k]) < 1e-6,
              "{}: bounds.{} does not match data/bbox.json".format(name, k))

    res = f["resolution"]
    check(res == RESOLUTION, "{}: resolution {} != {}".format(name, res, RESOLUTION))

    raw = base64.b64decode(f["grid"])
    check(len(raw) == res * res * 4,
          "{}: grid is {} bytes, expected {} (float32 {}x{})".format(
              name, len(raw), res * res * 4, res, res))
    g = np.frombuffer(raw, dtype=np.float32)
    check(np.all(np.isfinite(g)), "{}: grid has NaN or inf".format(name))
    check(g.min() >= 0.0, "{}: grid has negative values".format(name))
    check(g.max() <= 1.0 + 1e-6,
          "{}: grid max {:.4f} exceeds 1.0 - contract says normalised 0..1"
          .format(name, float(g.max())))
    check(g.max() > 0.1,
          "{}: grid max {:.4f} is nearly flat - decode or splat bug"
          .format(name, float(g.max())))

    check(0.0 <= f["progress"] <= 1.0, "{}: progress out of range".format(name))
    check(f["n_consistent"] <= f["n_total"],
          "{}: n_consistent > n_total".format(name))
    check(f["ring_radius_m"] > 0, "{}: ring_radius_m must be positive".format(name))
    check(f["field_area_pct"] > 0, "{}: field_area_pct must be positive".format(name))

    check(len(f["zones"]) >= 2, "{}: contract expects two labelled zones".format(name))
    for z in f["zones"]:
        for k in ("name", "pct", "centroid"):
            check(k in z, "{}: zone missing '{}'".format(name, k))
        if "centroid" in z:
            check(inside(bbox, *z["centroid"]),
                  "{}: zone '{}' centroid outside bbox".format(name, z.get("name")))

    # The grid must actually be north-up: row 0 is the NORTH edge.
    grid2d = g.reshape(res, res)
    top = zones_row(f["zones"], bbox, res)
    if top is not None:
        r, expected = top
        peak = int(np.unravel_index(int(np.argmax(grid2d)), grid2d.shape)[0])
        check(abs(peak - expected) <= 6,
              "{}: densest row is {} but the top zone centroid implies row {} - "
              "grid may be flipped north/south".format(name, peak, expected))
        del r


def zones_row(zones, bbox, res):
    if not zones or "centroid" not in zones[0]:
        return None
    lat = zones[0]["centroid"][0]
    row = (bbox["north"] - lat) / (bbox["north"] - bbox["south"]) * res
    return zones[0], int(row)


def main():
    bbox = json.load(open(DATA / "bbox.json"))
    priors = json.load(open(DATA / "priors.json"))

    missing = [n for n in ("case.json", "trajectories.json", "field.json",
                           "field_partial.json", "field_collapsed.json",
                           "fleet_status.json", "extraction.json",
                           "transcript.txt") if not (MOCKS / n).exists()]
    if missing:
        print("MISSING MOCKS: " + ", ".join(missing))
        return 1

    # case.json IS the CONTRACT.md s8 extraction payload plus render extras.
    case = json.load(open(MOCKS / "case.json"))
    for k in ("transcript", "subject", "last_known", "assessment",
              "ring_radius_m", "bounds", "incident"):
        check(k in case, "case.json: missing '{}'".format(k))
    for k in ("name", "age", "category", "experience", "clothing"):
        check(k in case.get("subject", {}), "case.json: subject missing '{}'".format(k))
    for k in ("place", "time", "elapsed_min", "ipp"):
        check(k in case.get("last_known", {}), "case.json: last_known missing '{}'".format(k))
    ipp = case["last_known"]["ipp"]
    check(inside(bbox, *ipp), "case.json: IPP is outside the bbox")
    check(abs(case["ring_radius_m"] - priors["ring_radius_km"] * 1000) < 1.0,
          "case.json: ring_radius_m disagrees with data/priors.json")
    check(abs(case["assessment"]["ring_radius_m"] - case["ring_radius_m"]) < 1.0,
          "case.json: assessment.ring_radius_m disagrees with the top-level one")

    # extraction.json must be the same incident, or intake and map disagree.
    ext = json.load(open(MOCKS / "extraction.json"))
    check(ext.get("last_known", {}).get("ipp") == ipp,
          "extraction.json: IPP differs from case.json - intake would place the "
          "subject somewhere the trajectories do not start")
    check(ext.get("subject", {}).get("name") == case["subject"]["name"],
          "extraction.json: subject name differs from case.json")
    check(abs(ext["assessment"]["ring_radius_m"]
              - priors["ring_radius_km"] * 1000) < 1.0,
          "extraction.json: ring_radius_m must be DERIVED from priors.json")

    tr = (MOCKS / "transcript.txt").read_text(encoding="utf-8")
    check(len(tr) > 200, "transcript.txt: too short to be the demo script")
    for phrase in ("Alex Morgan", "Marshall Gulch", "red jacket"):
        check(phrase in tr,
              "transcript.txt: missing '{}' - every detail in the script drives "
              "something visible".format(phrase))
    check(ext.get("transcript", "").strip() == tr.strip(),
          "extraction.json: transcript differs from transcript.txt")

    # --- trajectories -------------------------------------------------------
    batches = json.load(open(MOCKS / "trajectories.json"))
    check(isinstance(batches, list), "trajectories.json: expected a list")
    check(len(batches) <= MAX_BATCH,
          "trajectories.json: {} batches exceeds the {}-per-message cap"
          .format(len(batches), MAX_BATCH))

    n_runs = n_failed = n_pts_over = n_outside = 0
    off_ipp = 0
    for b in batches:
        for k in ("hypothesis_id", "family", "weight", "generated", "runs"):
            check(k in b, "trajectories.json: batch missing '{}'".format(k))
        check(b.get("family") in FAMILIES,
              "trajectories.json: unknown family {!r}".format(b.get("family")))
        check(isinstance(b.get("generated"), bool),
              "trajectories.json: 'generated' must be a bool")
        for run in b.get("runs", []):
            n_runs += 1
            for k in ("run_index", "points", "endpoint", "duration_s", "status"):
                check(k in run, "trajectories.json: run missing '{}'".format(k))
            if run.get("status") not in ("ok", "failed"):
                bad("trajectories.json: bad status {!r}".format(run.get("status")))
            if run.get("status") != "ok":
                n_failed += 1
                continue
            pts = run["points"]
            if len(pts) > MAX_POINTS:
                n_pts_over += 1
            for p in pts:
                if len(p) != 3 or not isinstance(p[2], int):
                    bad("trajectories.json: point must be [lat, lon, int t]")
                    break
                if not inside(bbox, p[0], p[1]):
                    n_outside += 1
                    break
            if pts and (abs(pts[0][0] - ipp[0]) > 1e-4
                        or abs(pts[0][1] - ipp[1]) > 1e-4):
                off_ipp += 1

    check(n_pts_over == 0,
          "trajectories.json: {} runs exceed {} points".format(n_pts_over, MAX_POINTS))
    check(n_outside == 0,
          "trajectories.json: {} runs leave the bbox".format(n_outside))
    check(off_ipp == 0,
          "trajectories.json: {} runs do not start at the IPP".format(off_ipp))

    rate = n_failed / n_runs * 100 if n_runs else 0
    if not 2.0 <= rate <= 9.0:
        warn("failure rate {:.1f}% is outside the ~5% the spec asks for".format(rate))

    # --- fields -------------------------------------------------------------
    fields = {}
    for n in ("field.json", "field_partial.json", "field_collapsed.json"):
        fields[n] = json.load(open(MOCKS / n))
        check_field(n, fields[n], bbox)

    check(fields["field_partial.json"]["progress"] < 1.0,
          "field_partial.json: progress must be < 1.0")
    check(fields["field.json"]["progress"] == 1.0,
          "field.json: progress must be 1.0")

    col, full = fields["field_collapsed.json"], fields["field.json"]
    check(col["n_consistent"] < col["n_total"],
          "field_collapsed.json: evidence did not discard anything")
    frac = col["n_consistent"] / col["n_total"]
    if not 0.20 <= frac <= 0.45:
        warn("collapsed n_consistent is {:.0f}% of n_total; spec wants about a "
             "third".format(frac * 100))
    check(col["field_area_pct"] < full["field_area_pct"],
          "field_collapsed.json: collapsed field is not tighter than the full one")
    check(fields["field_partial.json"]["field_area_pct"] > full["field_area_pct"],
          "field_partial.json: partial field should be blurrier than the final one")

    # --- fleet status -------------------------------------------------------
    frames = json.load(open(MOCKS / "fleet_status.json"))
    check(isinstance(frames, list) and len(frames) >= 10,
          "fleet_status.json: expected ~20 frames")
    prev = -1
    for f in frames:
        for k in ("sandboxes_active", "hypotheses_completed", "runs_completed",
                  "progress"):
            check(k in f, "fleet_status.json: frame missing '{}'".format(k))
        if f.get("hypotheses_completed", 0) < prev:
            bad("fleet_status.json: hypotheses_completed decreases")
        prev = f.get("hypotheses_completed", 0)

    # --- report -------------------------------------------------------------
    print("mocks checked against CONTRACT.md")
    print("  {} batches, {} runs, {:.1f}% failed".format(len(batches), n_runs, rate))
    print("  field_area_pct  partial {}%  full {}%  collapsed {}%".format(
        fields["field_partial.json"]["field_area_pct"],
        full["field_area_pct"], col["field_area_pct"]))
    print("  evidence keeps {}/{} runs ({:.0f}%)".format(
        col["n_consistent"], col["n_total"], frac * 100))
    for w in warns:
        print("  WARN  " + w)
    if fails:
        print()
        for f in fails:
            print("  FAIL  " + f)
        print("\n{} contract violation(s)".format(len(fails)))
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
