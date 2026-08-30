"""Plan the hypothesis set for one incident.

CONTRACT.md section 4. Families come from the published ISRID priors; the
model varies behaviour WITHIN a family rather than inventing the statistical
structure. This module owns the part that is not the model's to choose.

Why durations are sampled, not fixed
------------------------------------
Run every hypothesis for a fixed four hours and every walker covers roughly
the same ground, so endpoint distances bunch: measured p50 4.79 km against an
ISRID p50 of 2.86 km, and a p95 of 6.98 km against 9.55 km. Too far in the
middle, too short in the tail.

That matters more than it looks. The whole claim is "the same published
statistics, applied through terrain instead of a circle". If the simulated
distance distribution does not reproduce the published quantiles, the claim is
rhetorical. Sampling duration from a lognormal restores the spread, and the
resulting distance distribution is then CHECKED against priors.json rather
than assumed -- see `calibrate` and prep/check_calibration.py.

This is calibration against published priors, which is the stated method. It
is emphatically NOT tuning against the validation score, which would be
circular and is warned about explicitly in the brief.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

# Lognormal spread of walking duration. sigma is set from the published
# quantile ratio p95/p50, since for a lognormal p95/p50 = exp(1.645 * sigma).
# Solved in calibrate() rather than hardcoded, so it follows priors.json if
# the priors are ever regenerated.
DEFAULT_DURATION_S = 14400.0
MIN_DURATION_S = 900.0
MAX_DURATION_S = 12 * 3600.0


def load_priors():
    return json.load(open(DATA / "priors.json"))


def duration_sigma(priors):
    """Lognormal sigma implied by the published p95/p50 distance ratio."""
    q = priors["distance_km"]
    ratio = max(1.05, q["p95"] / max(q["p50"], 1e-6))
    return math.log(ratio) / 1.645


def sample_durations(n, base_s, sigma, rng):
    """Lognormal durations with median `base_s`."""
    d = base_s * rng.lognormal(mean=0.0, sigma=sigma, size=n)
    return np.clip(d, MIN_DURATION_S, MAX_DURATION_S)


def sample_families(n, priors, rng):
    fam = priors["families"]
    names = list(fam)
    w = np.array([fam[k] for k in names], dtype=float)
    w = w / w.sum()
    idx = rng.choice(len(names), size=n, p=w)
    return [names[i] for i in idx], fam


def plan(ipp, n=200, n_runs=60, priors=None, rng=None, base_s=None,
         terrain=None):
    """Build `n` hypotheses for one incident.

    Returns a list of CONTRACT.md section 4 objects. `description` and
    `rationale` are filled from terrain when a Terrain is supplied, so the
    strings that surface on screen are site-specific rather than textbook --
    and they are honest, because they are derived from the arrays rather than
    written by a model that has not seen the ground.
    """
    priors = priors or load_priors()
    rng = rng or np.random.default_rng(0)
    base_s = base_s or DEFAULT_DURATION_S
    sigma = duration_sigma(priors)

    families, fam_w = sample_families(n, priors, rng)
    durations = sample_durations(n, base_s, sigma, rng)

    summary = terrain.summary(ipp[0], ipp[1]) if terrain is not None else None

    out = []
    for i, (f, dur) in enumerate(zip(families, durations)):
        h = {
            "hypothesis_id": "h_{:05d}".format(i),
            "family": f,
            "weight": round(float(fam_w[f]), 4),
            "start": [float(ipp[0]), float(ipp[1])],
            "duration_s": int(dur),
            "n_runs": int(n_runs),
            "seed_base": int(i) * 1000,
        }
        if summary:
            h["description"] = _describe(f, summary)
            h["rationale"] = _rationale(f, summary)
            h["source"] = {"kind": "terrain",
                           "label": "derived from the 30 m terrain arrays"}
        out.append(h)
    return out


def _describe(family, s):
    d = s["descends_to"]
    return {
        "route_travelling":
            "Stayed on the path network, {} m from the nearest way at the "
            "last known point".format(s["trail_dist_m"]),
        "direction_sampling":
            "Committed to a bearing off the trail across {} terrain, mean "
            "slope {} degrees".format(s["landform"], s["mean_slope_deg"]),
        "backtracking":
            "Went out, recognised the error, and turned back toward the last "
            "known point",
        "view_enhancing":
            "Climbed for a sightline or a phone signal, {} m of relief "
            "available nearby".format(s["relief_m"]),
        "staying_put":
            "Sheltered close to the last known point, water {} m away"
            .format(s["water_dist_m"]),
    }[family] if family != "direction_sampling" else (
        "Followed the fall line {} from the {} at the last known point"
        .format(d, s["landform"]))


def _rationale(family, s):
    return ("Ground around the IPP is {} at {} m with {} m of relief, mean "
            "slope {} degrees, {}% of it steeper than 30. Steepest descent "
            "runs {}. Nearest trail {} m, nearest water {} m.".format(
                s["landform"], s["elevation_m"], s["relief_m"],
                s["mean_slope_deg"], round(s["steep_fraction"] * 100),
                s["descends_to"], s["trail_dist_m"], s["water_dist_m"]))


def calibrate(ipp, terrain, priors=None, n=80, n_runs=40, rng=None,
              iterations=6):
    """Solve for the base duration whose endpoint distances match the priors.

    Runs short pilot fleets and scales the median duration until the simulated
    median distance lands on the published p50. Distance is not linear in
    duration -- fatigue and terrain both bite -- so this iterates rather than
    solving in closed form.

    Returns (base_s, report).
    """
    from worker.runner import run_hypothesis

    priors = priors or load_priors()
    rng = rng or np.random.default_rng(1)
    target = priors["distance_km"]["p50"]
    base = DEFAULT_DURATION_S
    report = []

    # The SAME pilot sample is re-run at each base duration. Drawing a fresh
    # sample every iteration made the measurement noisier than the correction,
    # and the solver oscillated (2.75 -> 3.99 -> 2.35 -> 3.49 km) instead of
    # converging, so the chosen base was luck. Fixing the seed makes the
    # measured median a deterministic function of base_s, which is the only
    # thing being solved for.
    seed = int(rng.integers(1 << 30))

    for _ in range(iterations):
        hs = plan(ipp, n=n, n_runs=n_runs, priors=priors,
                  rng=np.random.default_rng(seed), base_s=base)
        ends = []
        for h in hs:
            b, _ = run_hypothesis(h, terrain)
            ends += [r["endpoint"] for r in b["runs"] if r["endpoint"]]
        if not ends:
            break
        e = np.asarray(ends)
        d = np.hypot((e[:, 0] - ipp[0]) * terrain.m_lat,
                     (e[:, 1] - ipp[1]) * terrain.m_lon) / 1000.0
        med = float(np.median(d))
        report.append({"base_s": round(base), "median_km": round(med, 3)})
        if med <= 0.01:
            break
        # Distance grows sublinearly with time, so damp the correction.
        if abs(med - target) / target < 0.03:
            break                      # within 3%, stop rather than jitter
        base = float(np.clip(base * (target / med) ** 0.6,
                             MIN_DURATION_S, MAX_DURATION_S))
    return base, report
