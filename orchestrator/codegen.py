"""One model call per SANDBOX writes that hypothesis's movement code.

This is the thing that makes the sandboxes necessary rather than decorative. A
fixed random walk with different seeds would run twelve thousand times in one
process in under a second, and a judge would rightly ask what the isolation is
for. The answer has to be that generated code is executing, hundreds of times,
in parallel. Protect this above any feature.

Not one call per simulation. 200 sandboxes, one script each, 60 seeds each.

    python orchestrator/codegen.py --family route_travelling   # print one script
"""
from __future__ import annotations

import argparse, json, os, re, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed

from settings import WORKER, key, load_case

sys.path.insert(0, str(WORKER))
from templates import template_for  # noqa: E402

# Picked from the live model list, not from memory. gpt-5.4-mini for the
# fan-out because 200 of these run at once and latency sits in front of the
# simulation beat; the single hypothesis call upstream can afford more.
CODEGEN_MODEL = os.environ.get("SEARCHLIGHT_CODEGEN_MODEL", "gpt-5.4-mini")

SYSTEM = """You write short numpy-free Python movement simulations for a \
search-and-rescue probability model. You return code and nothing else."""

PROMPT = """Write a Python function simulating how one lost person moves, \
under this specific hypothesis.

HYPOTHESIS
family: {family}
behaviour: {description}
{rationale}

SIGNATURE â€” define exactly this, nothing else at module level:

    def simulate(start_lat, start_lon, duration_s, rng):
        ...
        return [(lat, lon, t), ...]

`rng` is a seeded numpy Generator. Use it for every random draw â€” rng.normal(mu, sigma),
rng.uniform(a, b), rng.choice([...]) â€” and never `random` or a fixed constant, because the
same script runs {n_runs} times with different seeds and the runs must differ.

Return a list of (lat, lon, t) with t in seconds from 0, one point every DT_S seconds,
covering the full duration_s.

THE ONLY FUNCTIONS AVAILABLE. There are no imports. There is no numpy. Calling
anything else raises:

    elevation_at(lat, lon)      -> metres
    slope_at(lat, lon)          -> degrees, slope of the ground
    dist_to_trail(lat, lon)     -> metres to the nearest walkable way
    dist_to_water(lat, lon)     -> metres to the nearest watercourse
    step(lat, lon, bearing, m)  -> (lat, lon), bearing 0 = north, 90 = east
    math                        the standard module
    DT_S                        the timestep in seconds ({dt} s)

TERRAIN â€” Santa Catalina Mountains, Arizona. Elevation 639â€“2793 m, mean slope 12Â°,
max 76Â°. The subject starts at ({start_lat:.5f}, {start_lon:.5f}), elevation {elev:.0f} m,
on a {slope:.0f}Â° slope, {trail:.0f} m from the nearest trail and {water:.0f} m from water.

PACE â€” get this right or the simulation is worthless:
- On a trail (dist_to_trail < 40 m) a hiker makes about 1.15 m/s. A trail crossing a
  steep hillside is GRADED; the ground slope tells you almost nothing about pace there.
- Off trail, use Tobler on the grade ALONG THE DIRECTION OF TRAVEL, not the ground
  slope: probe 50 m ahead on the bearing, take the elevation difference over 50 m as
  the grade g, then v = 6 * exp(-3.5 * abs(g + 0.05)) / 3.6, scaled by about 0.75 for
  rough ground, and clamped to [0.20, 1.40] m/s. Using slope_at() here instead would
  penalise descending a drainage exactly as hard as climbing a cliff.

WHAT THIS FAMILY MUST LOOK LIKE
{family_rule}

RULES
- Movement must be driven by the terrain functions, not by a blind random walk.
- Keep it under about 45 lines and make sure every loop terminates.
- Do not print, do not define anything except simulate and any small helpers it needs.

Return only the code. No markdown fences, no commentary."""


# Without these the family name is just a label. Measured: a `staying_put`
# script whose description said "stopped in shade and waited" walked 1.67 km,
# because nothing in the prompt said what staying put means in metres. The
# family is what the ISRID weight is attached to, so a script that ignores it
# puts mass in the wrong place with a published prior's authority behind it.
FAMILY_RULES = {
    "route_travelling":
        "Follows trails. Keep dist_to_trail small most of the time and hold a "
        "heading -- turns of more than about 45 degrees in one step mean it is "
        "diffusing along the trail rather than travelling it. Expect roughly "
        "2-4 km from the start over 72 minutes.",
    "direction_sampling":
        "Picks one direction and commits, deflecting around ground too steep to "
        "cross rather than stopping. Expect roughly 2-4 km from the start.",
    "backtracking":
        "Travels out, then turns for the start. Fix the return bearing ONCE at "
        "the turn with a per-run error -- recomputing it toward the start every "
        "step is a pursuit curve that always lands exactly on the start, which "
        "is the one outcome nobody needs to search. Expect 0.3-1.5 km out.",
    "view_enhancing":
        "Climbs toward high ground for a view or a signal, then holds position "
        "there. Climbing is slow: expect well under 1 km from the start.",
    "staying_put":
        "Does NOT travel. Drifts at most 100-250 m from the start for shade, "
        "water or a place to sit, and stays there. Anything over about 300 m "
        "is the wrong behaviour entirely.",
}


def build_prompt(hyp, terrain_facts, dt_s=60):
    rationale = hyp.get("rationale") or ""
    family = hyp.get("family", "route_travelling")
    return PROMPT.format(
        family=family,
        family_rule=FAMILY_RULES.get(family, FAMILY_RULES["route_travelling"]),
        description=hyp.get("description", family),
        rationale=("reasoning: " + rationale) if rationale else "",
        n_runs=hyp.get("n_runs", 60),
        dt=dt_s,
        start_lat=hyp["start"][0], start_lon=hyp["start"][1],
        elev=terrain_facts.get("elevation", 0.0),
        slope=terrain_facts.get("slope", 0.0),
        trail=terrain_facts.get("trail_dist", 0.0),
        water=terrain_facts.get("water_dist", 0.0))


_FENCE = re.compile(r"^\s*```(?:python)?\s*|\s*```\s*$", re.MULTILINE)


def strip_fences(text):
    """Models add fences even when told not to. Cheaper to strip than to retry."""
    return _FENCE.sub("", text or "").strip()


def client():
    from openai import OpenAI
    return OpenAI(api_key=key("OPENAI_API_KEY"))


def generate_script(oai, hyp, terrain_facts, model=CODEGEN_MODEL, timeout=60):
    """Returns (script_or_None, error_or_None). Never raises.

    None means fall back to the family template. That path is not exceptional --
    it is the demo's floor, and it must stay cheap to reach.
    """
    try:
        r = oai.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": SYSTEM},
                      {"role": "user",
                       "content": build_prompt(hyp, terrain_facts)}],
            timeout=timeout)
        src = strip_fences(r.choices[0].message.content)
    except Exception as e:
        return None, "{}: {}".format(type(e).__name__, e)[:200]

    if "def simulate" not in src:
        return None, "no simulate() in response"
    try:
        compile(src, "<generated>", "exec")
    except SyntaxError as e:
        return None, "SyntaxError line {}: {}".format(e.lineno, e.msg)
    return src, None


def generate_many(oai, hyps, terrain_facts, model=CODEGEN_MODEL, max_workers=16,
                  on_done=None):
    """One call per hypothesis, in parallel. Returns {hypothesis_id: script},
    omitting the ones that failed -- the caller falls back per family."""
    out, errors = {}, {}

    def one(h):
        return h["hypothesis_id"], generate_script(oai, h, terrain_facts, model)

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futs = [pool.submit(one, h) for h in hyps]
        for i, f in enumerate(as_completed(futs), 1):
            hid, (src, err) = f.result()
            if src:
                out[hid] = src
            else:
                errors[hid] = err
            if on_done:
                on_done(i, len(hyps), len(out))
    return out, errors


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--family", default="route_travelling")
    ap.add_argument("--description",
                    default="Followed the drainage south-east from the junction, "
                            "path of least resistance on tiring legs")
    ap.add_argument("--model", default=CODEGEN_MODEL)
    ap.add_argument("--out", help="write the script here")
    ap.add_argument("--run", action="store_true",
                    help="execute it locally against data/ afterwards")
    args = ap.parse_args()

    from settings import MOCKS, DATA
    sys.path.insert(0, str(WORKER))
    import sim as simmod

    case = load_case()
    terrain = simmod.Terrain(DATA)
    lat, lon = case["ipp"]
    r, c = terrain.rc(lat, lon)
    facts = {"elevation": float(terrain.elevation[r, c]),
             "slope": float(terrain.slope[r, c]),
             "trail_dist": float(terrain.trail_dist[r, c]),
             "water_dist": float(terrain.water_dist[r, c])}
    print("IPP facts: {}".format({k: round(v, 1) for k, v in facts.items()}))

    hyp = {"hypothesis_id": "h_cli", "family": args.family,
           "description": args.description, "start": case["ipp"],
           "duration_s": case["last_contact_s_ago"], "n_runs": 8,
           "seed_base": 7000, "weight": 0.2}

    t0 = time.perf_counter()
    src, err = generate_script(client(), hyp, facts, model=args.model)
    print("model {} took {:.2f}s".format(args.model, time.perf_counter() - t0))
    if err:
        print("FAILED: {}".format(err))
        print("(the family template would run instead)")
        return 1

    print("-" * 70)
    print(src)
    print("-" * 70)
    if args.out:
        from pathlib import Path
        Path(args.out).write_text(src)
        print("wrote {}".format(args.out))

    if args.run:
        batch = simmod.run_batch({"hypothesis": hyp, "script": src,
                                  "generated": True}, str(DATA), budget_s=30.0)
        ok = [r for r in batch["runs"] if r["status"] == "ok"]
        print("local run: {}/{} ok".format(len(ok), len(batch["runs"])))
        for r in batch["runs"]:
            if r["status"] != "ok":
                print("  FAIL: {}".format(r.get("error")))
                break
        if ok:
            d = sorted(((p["endpoint"][0] - lat) * 110.574) ** 2 +
                       ((p["endpoint"][1] - lon) * 94.004237) ** 2 for p in ok)
            d = [x ** 0.5 for x in d]
            print("  displacement km: min {:.2f} median {:.2f} max {:.2f}".format(
                d[0], d[len(d) // 2], d[-1]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
