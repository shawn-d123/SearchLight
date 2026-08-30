"""Model-written hypotheses and movement scripts.

This is the part that makes Searchlight a Daytona project rather than an
animation. A fixed random walk with different seeds runs 12,000 times in one
process in under a second, and a judge will rightly ask why sandboxes were
needed. The answer has to be that **a model writes the movement code**, so you
are executing generated code in parallel and isolation is the real requirement.

Two calls, at two different levels:

  generate_hypotheses  ONE call before the fan-out. Reads the subject, the
                       conditions and a terrain summary of the ground around
                       the IPP, and proposes behaviours specific to THIS place
                       and THIS person. Families still come from the published
                       priors -- the model varies within published categories,
                       it does not invent the statistical structure.

  generate_script      ONE call per sandbox, not per simulation. 200 sandboxes
                       x 60 seeds = 12,000 simulations from 200 calls.

**Everything is cached to data/generated/.** Cache the model outputs and say so
in four words -- nobody blinks at that, and they do blink at a suspiciously
fast live call, or at a demo stalling while one runs. Caching is also what
makes the fleet reproducible between rehearsals.

Nothing here is load-bearing for the demo: every failure path falls back to the
deterministic template in worker/templates.py, and the batch is marked
`generated: false` so the count on screen stays honest.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "generated"

# One call, high value, worth the better model.
HYPOTHESIS_MODEL = "gpt-4.1"
# 200 calls. Cheaper, and a bad script costs nothing -- it falls back.
SCRIPT_MODEL = "gpt-4.1-mini"

FAMILIES = ("route_travelling", "direction_sampling", "backtracking",
            "view_enhancing", "staying_put")

# The exact surface a generated script may use. Given verbatim to the model,
# because a script that calls something that does not exist is a wasted call.
TERRAIN_API = """
terrain.elev(lat, lon)        -> metres above sea level      (vectorised)
terrain.slope_deg(lat, lon)   -> slope in degrees            (vectorised)
terrain.to_trail(lat, lon)    -> metres to the nearest path  (vectorised)
terrain.to_water(lat, lon)    -> metres to the nearest watercourse (vectorised)
terrain.inside(lat, lon)      -> bool array, is the point inside the box
terrain.clamp(lat, lon)       -> (lat, lon) clipped into the box
terrain.offset(lat, lon, bearing_rad, dist_m) -> (lat, lon) moved along a bearing
terrain.tobler_speed_ms(d_elev_m, d_horiz_m)  -> walking speed, m/s
terrain.m_lat, terrain.m_lon  -> metres per degree at this latitude
terrain.cell_m                -> grid cell size in metres (30)
"""

SCRIPT_CONTRACT = """
Write a Python function with EXACTLY this signature:

    def move(terrain, start, duration_s, n_runs, seed):
        ...
        return points, ok

Rules, all of which are checked and any of which failing discards your script:

  * points is a numpy float array of shape (n_runs, 60, 3); each entry is
    [latitude, longitude, seconds_elapsed]. LATITUDE FIRST.
  * points[:, 0] must be the start point at t=0, for every run.
  * The third column must be non-decreasing along axis 1.
  * ok is a numpy bool array of shape (n_runs,), False where the walker left
    the terrain box.
  * Simulate ALL n_runs walkers together as arrays. Do not loop over runs; a
    per-run Python loop is far too slow at this scale.
  * numpy is available as np. Import nothing else. No file or network access.
  * Must finish well inside 10 seconds.
  * Use np.random.default_rng(seed) so the run is reproducible.

Return ONLY the function inside one ```python code block. No prose.
"""


def _distance_block(q):
    """Published distance statistics, handed to the model as a constraint.

    Without this the generated scripts each invent their own pace, and the
    endpoint distribution goes bimodal -- measured p50 1.69 km against a
    published 2.86, and p95 17.23 against 9.55. Most walkers barely moved and a
    few ran off the map. A single calibrated duration cannot fix that, because
    28 different model-written movement models each have their own speed.

    The project claims to apply the SAME published statistics, so the honest
    fix is to give the model those statistics rather than to tune around them.
    """
    if not q:
        return ""
    return """
PUBLISHED DISTANCE STATISTICS -- your walkers must reproduce these.

Straight-line distance from the start point to where the subject is finally
found, from {n} real ISRID cases for this subject category:

    25th percentile  {p25:.2f} km
    50th percentile  {p50:.2f} km
    75th percentile  {p75:.2f} km
    95th percentile  {p95:.2f} km

Choose pace and stopping behaviour so that your {{n_runs}} walkers, over the
duration you are given, land in roughly this spread. Do not let most of them
stall near the start, and do not let them run far past the 95th percentile.
This distribution is the published evidence base and is not yours to change.
""".format(n=q.get("n", ""), **{k: q[k] for k in ("p25", "p50", "p75", "p95")})


def _client():
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        env = ROOT / ".env"
        if env.exists():
            for ln in env.read_text(encoding="utf-8").splitlines():
                if ln.startswith("OPENAI_API_KEY="):
                    key = ln.split("=", 1)[1].strip()
    if not key:
        raise RuntimeError("no OPENAI_API_KEY in environment or .env")
    from openai import OpenAI
    return OpenAI(api_key=key)


def _cache_path(kind, payload):
    CACHE.mkdir(parents=True, exist_ok=True)
    h = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]
    return CACHE / "{}_{}.json".format(kind, h)


def _extract_code(text):
    m = re.search(r"```(?:python)?\s*(.*?)```", text, re.S)
    code = (m.group(1) if m else text).strip()
    if "def move" not in code:
        raise ValueError("no move() in the response")
    return code


# ---------------------------------------------------------------------------
# one call before the fan-out
# ---------------------------------------------------------------------------

def generate_hypotheses(case, terrain_summary, priors, n=8,
                        local_knowledge=None, model=HYPOTHESIS_MODEL,
                        use_cache=True, client=None):
    """Propose site-specific behaviours for this incident.

    Returns a list of dicts with family / description / rationale. The caller
    attaches weights from the priors and expands them into the full hypothesis
    set -- the model never sets a weight.
    """
    subject = case.get("subject", {})
    last = case.get("last_known", {})
    key = {"subject": subject, "last_known": last, "terrain": terrain_summary,
           "n": n, "model": model,
           "local": [f.get("claim") for f in (local_knowledge or [])]}
    cp = _cache_path("hypotheses", key)
    if use_cache and cp.exists():
        d = json.load(open(cp))
        d["cached"] = True
        return d

    local_txt = ""
    if local_knowledge:
        local_txt = "\n\nDocumented local knowledge for this area:\n" + "\n".join(
            "- {} [{}]".format(f.get("claim", ""), f.get("label", ""))
            for f in local_knowledge)

    prompt = """A person is missing in the Santa Catalina Mountains, Arizona.

SUBJECT: {name}, age {age}, category {cat}, experience {exp}, wearing {clo},
injuries {inj}.
LAST KNOWN: {place} at {time}, {elapsed} minutes ago.

TERRAIN AROUND THE LAST KNOWN POINT (from a 30 m elevation model):
  landform            {landform}
  elevation           {elevation_m} m
  local relief        {relief_m} m
  mean slope          {mean_slope_deg} degrees
  fraction over 30deg {steep_fraction}
  nearest trail       {trail_dist_m} m
  nearest water       {water_dist_m} m
  steepest descent    {descends_to}{local}

Propose {n} DISTINCT hypotheses for what this person did, each grounded in the
terrain above rather than in generic advice. Each must be assigned one of these
published ISRID strategy families:

{families}

Return JSON: {{"hypotheses": [{{"family": ..., "description": ..., "rationale": ...}}]}}

description: one sentence, plain English, shown on screen to a search team.
rationale: one sentence naming the specific terrain fact that motivates it.

Be concrete about direction and landform. "Followed the drainage south-east
from the junction" is useful; "wandered randomly" is not.""".format(
        name=subject.get("name", "unknown"), age=subject.get("age", "unknown"),
        cat=subject.get("category", "hiker"),
        exp=subject.get("experience", "unknown"),
        clo=subject.get("clothing", "unknown"),
        inj=subject.get("injuries", "unknown"),
        place=last.get("place", "unknown"), time=last.get("time", "unknown"),
        elapsed=last.get("elapsed_min", "unknown"),
        local=local_txt, n=n,
        families="\n".join("  - " + f for f in FAMILIES),
        **terrain_summary)

    client = client or _client()
    t0 = time.time()
    r = client.chat.completions.create(
        model=model, response_format={"type": "json_object"},
        messages=[{"role": "system", "content":
                   "You are a search and rescue planner. You reason from "
                   "terrain. You never invent statistics."},
                  {"role": "user", "content": prompt}])
    raw = json.loads(r.choices[0].message.content)

    out = []
    for h in raw.get("hypotheses", []):
        fam = str(h.get("family", "")).strip()
        if fam not in FAMILIES:
            continue          # unmappable to a published family -> dropped
        out.append({"family": fam,
                    "description": str(h.get("description", ""))[:240],
                    "rationale": str(h.get("rationale", ""))[:320]})

    result = {"hypotheses": out, "model": model, "cached": False,
              "elapsed_s": round(time.time() - t0, 2),
              "dropped": len(raw.get("hypotheses", [])) - len(out)}
    json.dump(result, open(cp, "w"), indent=2)
    return result


# ---------------------------------------------------------------------------
# one call per sandbox
# ---------------------------------------------------------------------------

def generate_script(hypothesis, priors=None, model=SCRIPT_MODEL,
                    use_cache=True, client=None):
    """Ask the model to write the movement code for one hypothesis.

    Returns (script_or_None, meta). None means the call failed; the caller
    falls back to the deterministic template.
    """
    # The published quantiles are part of the key: change the priors and every
    # cached script must be regenerated, because they are baked into the prompt.
    q = (priors or {}).get("distance_km") or {}
    key = {"family": hypothesis.get("family"),
           "description": hypothesis.get("description"),
           "rationale": hypothesis.get("rationale"), "model": model,
           "distance_km": q}
    cp = _cache_path("script", key)
    if use_cache and cp.exists():
        d = json.load(open(cp))
        return d.get("script"), {"cached": True, "model": d.get("model")}

    prompt = """Write the movement model for one hypothesis about a missing hiker.

HYPOTHESIS ({family}): {description}
WHY: {rationale}

You are given a terrain object with this API, all vectorised over numpy arrays:
{api}
{distance}
{contract}""".format(family=hypothesis.get("family"),
                     description=hypothesis.get("description", ""),
                     rationale=hypothesis.get("rationale", ""),
                     api=TERRAIN_API, distance=_distance_block(q),
                     contract=SCRIPT_CONTRACT)

    try:
        client = client or _client()
        t0 = time.time()
        r = client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content":
                       "You write terse, correct, vectorised numpy. You follow "
                       "the required signature exactly."},
                      {"role": "user", "content": prompt}])
        code = _extract_code(r.choices[0].message.content)
        meta = {"cached": False, "model": model,
                "elapsed_s": round(time.time() - t0, 2)}
        json.dump({"script": code, "model": model, "hypothesis": key},
                  open(cp, "w"), indent=2)
        return code, meta
    except Exception as e:
        return None, {"cached": False, "model": model,
                      "error": "{}: {}".format(type(e).__name__, str(e)[:200])}


def expand(generated, priors, ipp, n_total=200, n_runs=60, base_s=13504,
           rng=None):
    """Turn model hypotheses into the full CONTRACT.md section 4 set.

    Weights come from data/priors.json, NEVER from the model. Each generated
    hypothesis is repeated across the fleet with different seeds and durations,
    so 8 model-written behaviours become 200 sandbox jobs.
    """
    import numpy as np

    from .hypotheses import duration_sigma, sample_durations

    rng = rng or np.random.default_rng(0)
    fam_w = priors["families"]
    if not generated:
        return []
    durations = sample_durations(n_total, base_s, duration_sigma(priors), rng)

    out = []
    for i in range(n_total):
        g = generated[i % len(generated)]
        out.append({
            "hypothesis_id": "h_{:05d}".format(i),
            "family": g["family"],
            "weight": round(float(fam_w.get(g["family"], 0.1)), 4),
            "description": g.get("description", ""),
            "rationale": g.get("rationale", ""),
            "source": g.get("source", {"kind": "terrain",
                                       "label": "model-written from the "
                                                "30 m terrain arrays"}),
            "start": [float(ipp[0]), float(ipp[1])],
            "duration_s": int(durations[i]),
            "n_runs": int(n_runs),
            "seed_base": int(i) * 1000,
        })
    return out
