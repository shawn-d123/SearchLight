"""
Generate the two payloads CONTRACT.md specifies but mocks/ does not yet carry.

    python3 scripts/make-frontend-mocks.py

Writes into frontend/public/mocks/ only. It does NOT touch ../mocks/ or ../prep/
— those are Person C's. These exist so the frontend can be built and rehearsed
before the orchestrator emits the real thing. When C ships them, drop them into
../mocks/, copy them across, and delete this script; nothing else changes,
because both arrive as the same envelopes.

  sim_started.json        CONTRACT §7 "Hypothesis surfacing"
  validation_result.json  CONTRACT §9

(case.json, extraction.json and transcript.txt now ship in ../mocks/ and are
copied straight across — this script no longer generates them.)

ON THE HYPOTHESIS TEXT — read this before showing it to anyone
---------------------------------------------------------------
Every `description` and `rationale` below is derived from the committed terrain
arrays: real elevation change, real mean slope, real distance to the nearest
mapped trail and to water, measured along a real bearing from the real IPP. The
numbers in the prose are the numbers this script computed, and re-running it
reproduces them exactly.

`source.kind` is therefore "terrain", and it carries NO label and NO url.

The Parallel research pass (CONTRACT §5) never ran, so there is no local
knowledge and nothing here claims any. No documented incident, no ranger
advisory, no trip report and no citation is invented — a fabricated citation
about real geography on a demo screen is exactly the thing a judge is entitled
to check, and exactly the thing that would sink the project's credibility if
they did. When data/local_knowledge.json exists, its findings supply
`source.kind == "local"` with a genuine label and url, and the rail already
renders the attribution line for it.
"""

import json
import math
import pathlib

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
FRONTEND = HERE.parent
REPO = FRONTEND.parent
DATA = REPO / "data"
OUT = FRONTEND / "public" / "mocks"

meta = json.loads((DATA / "meta.json").read_text())
priors = json.loads((DATA / "priors.json").read_text())
baseline = json.loads((DATA / "baseline.json").read_text())
case = json.loads((REPO / "mocks" / "case.json").read_text())

B = meta["bounds"]
ROWS, COLS = meta["shape"]
M_PER_DEG_LAT = meta["m_per_deg_lat"]
M_PER_DEG_LON = meta["m_per_deg_lon"]

elevation = np.load(DATA / "elevation.npy")
slope = np.load(DATA / "slope.npy")
trail_dist = np.load(DATA / "trail_dist.npy")
water_dist = np.load(DATA / "water_dist.npy")
assert elevation.shape == (ROWS, COLS), (elevation.shape, (ROWS, COLS))

# case.json is now the CONTRACT §8 extraction payload plus incident metadata.
IPP = case["last_known"]["ipp"]
DURATION_S = int(case["last_known"]["elapsed_min"]) * 60


def rc(lat, lon):
    """[lat, lon] -> (row, col). Row 0 is NORTH, col 0 is WEST."""
    r = (B["north"] - lat) / (B["north"] - B["south"]) * (ROWS - 1)
    c = (lon - B["west"]) / (B["east"] - B["west"]) * (COLS - 1)
    return int(round(np.clip(r, 0, ROWS - 1))), int(round(np.clip(c, 0, COLS - 1)))


def walk(bearing_deg, out_m=2000.0, steps=40):
    """Sample the arrays along a straight bearing from the IPP."""
    th = math.radians(bearing_deg)
    samples = []
    for i in range(steps + 1):
        d = out_m * i / steps
        lat = IPP[0] + (math.cos(th) * d) / M_PER_DEG_LAT
        lon = IPP[1] + (math.sin(th) * d) / M_PER_DEG_LON
        r, c = rc(lat, lon)
        samples.append((elevation[r, c], slope[r, c], trail_dist[r, c], water_dist[r, c]))
    a = np.array(samples, dtype=float)
    step_m = out_m / steps

    def first_contact(col, threshold):
        """Metres along the leg at which the array first drops under threshold.
        Skips the first two samples so the IPP's own cell cannot answer."""
        hit = np.nonzero(a[2:, col] <= threshold)[0]
        return float((hit[0] + 2) * step_m) if len(hit) else None

    return {
        "bearing": bearing_deg,
        "d_elev": float(a[-1, 0] - a[0, 0]),
        "drop": float(a[0, 0] - a[:, 0].min()),
        "gain": float(a[:, 0].max() - a[0, 0]),
        "mean_slope": float(a[:, 1].mean()),
        "mean_trail_dist": float(a[:, 2].mean()),
        "max_trail_dist": float(a[:, 2].max()),
        "min_water_dist": float(a[:, 3].min()),
        "trail_contact_m": first_contact(2, 30.0),
        "water_contact_m": first_contact(3, 30.0),
        "peak_elev": float(a[:, 0].max()),
        "peak_at_m": float(int(np.argmax(a[:, 0])) * step_m),
        "out_m": out_m,
    }


COMPASS = [
    ("north", 0), ("north-east", 45), ("east", 90), ("south-east", 135),
    ("south", 180), ("south-west", 225), ("west", 270), ("north-west", 315),
]
legs = {name: walk(b) for name, b in COMPASS}
# The climb hypothesis needs reach to find real high ground; 2 km from a
# 2,400 m shoulder barely leaves the shoulder.
far_legs = {name: walk(b, out_m=4500.0, steps=90) for name, b in COMPASS}

r0, c0 = rc(*IPP)
ipp_facts = {
    "elev_m": round(float(elevation[r0, c0])),
    "slope_deg": round(float(slope[r0, c0]), 1),
    "trail_dist_m": round(float(trail_dist[r0, c0])),
    "water_dist_m": round(float(water_dist[r0, c0])),
}

descend = min(legs.items(), key=lambda kv: kv[1]["d_elev"])
trailed = min(legs.items(), key=lambda kv: kv[1]["mean_trail_dist"])
watered = min(
    (kv for kv in legs.items() if kv[1]["water_contact_m"] is not None),
    key=lambda kv: kv[1]["water_contact_m"],
    default=min(legs.items(), key=lambda kv: kv[1]["min_water_dist"]),
)
ascend = max(far_legs.items(), key=lambda kv: kv[1]["peak_elev"])

m = lambda x: f"{round(x):,} m"
km = lambda x: f"{x / 1000:.1f} km"

HYPOTHESES = [
    {
        "family": "route_travelling",
        "description": (
            f"Followed the mapped trail {trailed[0]} from the last known point — "
            f"the corridor never leaves a path by more than "
            f"{m(trailed[1]['max_trail_dist'])}."
        ),
        "rationale": (
            f"The subject was {ipp_facts['trail_dist_m']} m from a mapped path at "
            f"the IPP, and mean distance to a trail along this bearing is "
            f"{m(trailed[1]['mean_trail_dist'])} — the lowest of the eight sampled."
        ),
    },
    {
        "family": "direction_sampling",
        "description": (
            f"Descended {descend[0]} on the path of least resistance, losing "
            f"{m(descend[1]['drop'])} over {km(descend[1]['out_m'])}."
        ),
        "rationale": (
            f"Steepest sustained descent from the IPP, mean "
            f"{descend[1]['mean_slope']:.0f}°. Tiring subjects go downhill, and "
            f"the reverse bearing climbs instead."
        ),
    },
    # The IPP may already sit on a local high — it does for this case, at
    # 2,450 m with every bearing descending. Forcing a "climbed toward the high
    # ground" line there would describe a climb the terrain does not offer, so
    # the description follows the ground rather than the template.
    (
        {
            "family": "view_enhancing",
            "description": (
                f"Climbed {ascend[0]} toward the high ground, gaining "
                f"{m(ascend[1]['gain'])} to reach {m(ascend[1]['peak_elev'])} at "
                f"{km(ascend[1]['peak_at_m'])}."
            ),
            "rationale": (
                f"Highest ground within {km(ascend[1]['out_m'])} of the IPP. A "
                f"subject trying to regain a landmark or a phone signal climbs; "
                f"mean slope on this bearing is {ascend[1]['mean_slope']:.0f}°, "
                f"walkable."
            ),
        }
        if ascend[1]["gain"] >= 80.0
        else {
            "family": "view_enhancing",
            "description": (
                f"Held to the high ground {ascend[0]} rather than dropping off it — "
                f"the last known point at {m(ipp_facts['elev_m'])} is already "
                f"within {m(ascend[1]['gain'])} of the local summit."
            ),
            "rationale": (
                f"Every bearing from the IPP descends. A subject seeking a view or "
                f"a signal has nowhere to climb, so this family keeps them on the "
                f"ridge line instead of committing to a descent."
            ),
        }
    ),
    {
        "family": "backtracking",
        "description": (
            f"Turned back along the ascent route, re-crossing the "
            f"{ipp_facts['slope_deg']:.0f}° slope at the last known point and "
            f"retracing toward the trailhead."
        ),
        "rationale": (
            "Retracing is a common response to recognising a wrong turn, and it "
            "keeps the subject on ground they have already walked."
        ),
    },
    {
        "family": "staying_put",
        "description": (
            f"Reached the drainage {watered[0]} after "
            f"{m(watered[1]['water_contact_m'] or watered[1]['min_water_dist'])} "
            "and stopped there."
        ),
        "rationale": (
            f"Nearest water to the IPP is {ipp_facts['water_dist_m']} m. Subjects "
            "who stop moving tend to stop at water."
        ),
    },
]

weights = priors["families"]
hypotheses = [
    {
        "hypothesis_id": f"h_{i:05d}",
        "family": h["family"],
        "description": h["description"],
        "rationale": h["rationale"],
        # "terrain" is the honest label: every number above came from the
        # committed arrays. No label/url, because there is no citation to give.
        "source": {"kind": "terrain"},
        "weight": weights[h["family"]],
        "start": IPP,
        "duration_s": DURATION_S,
        "n_runs": case["runs_per_batch"],
        "seed_base": i * 1000,
    }
    for i, h in enumerate(HYPOTHESES)
]
hypotheses.sort(key=lambda h: -h["weight"])

sim_started = {
    "n_planned": case["n_hypotheses"],
    "hypotheses": hypotheses[:6],  # CONTRACT §7: at most 6, highest-weighted
    "_note": (
        "Generated by frontend/scripts/make-frontend-mocks.py from the committed "
        "terrain arrays. Every figure in the prose is measured, not invented, and "
        "re-running the script reproduces it. source.kind is 'terrain' with no "
        "citation because the Parallel research pass (CONTRACT §5) never ran. "
        "Replace with the orchestrator's real sim_started when it exists."
    ),
    "_ipp_facts": ipp_facts,
}

val = baseline["runs"]["derived (holdout)"]["validation"]
validation = {
    "n_cases": val["n"],
    # Unknown until Person C's validation run. Rendering a rehearsed number here
    # would be presenting a result we do not have.
    "our_score": None,
    "ring_baseline": round(val["mean_R"], 3),
    "ci95": val["ci95"],
    "per_case": val["per_case"],
    "_note": (
        "ring_baseline is the ring on these SAME six cases with the SAME metric. "
        "Quote 0.761, never the published 0.78 (n=376, different cases). "
        "our_score stays null until the real validation run fills it."
    ),
}

OUT.mkdir(parents=True, exist_ok=True)
(OUT / "sim_started.json").write_text(json.dumps(sim_started, indent=2))
(OUT / "validation_result.json").write_text(json.dumps(validation, indent=2))

print(f"IPP {IPP} — {ipp_facts}")
for name, leg in legs.items():
    print(
        f"  {name:<11} dElev {leg['d_elev']:+7.0f} m  slope {leg['mean_slope']:4.1f}°  "
        f"trail {leg['mean_trail_dist']:6.0f} m  water {leg['min_water_dist']:6.0f} m"
    )
print(f"\nwrote sim_started.json + validation_result.json to {OUT}")
for h in sim_started["hypotheses"]:
    print(f"  [{h['weight']:.2f}] {h['family']:<18} {h['description']}")
