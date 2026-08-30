"""Sandbox-side simulation runtime. numpy only -- see worker/README.md.

One sandbox holds ONE movement script and runs it many times with different
seeds, so this returns a BATCH (CONTRACT.md section 6).

The script -- whether written by the model or taken from worker/templates.py --
travels the SAME execution path. That is deliberate: if generation fails we swap
the source string and nothing else changes, so the demo can run with zero
successful generations.

    python worker/sim.py --job job.json --out batch.json --data-dir data

Inside a sandbox the defaults are /searchlight/job.json, /searchlight/batch.json
and /data. Both files are left on disk on purpose: if a judge asks whether this
is real, showing the generated script and the trajectory file sitting on a
machine you can then kill beats any diagram.

Job shape (written by the orchestrator):

    {"hypothesis": {<CONTRACT.md section 4 object>},
     "script": "def simulate(...): ...",
     "generated": true}
"""
from __future__ import annotations

import argparse, json, math, sys, time, traceback
from pathlib import Path

import numpy as np

MAX_POINTS = 60          # CONTRACT.md section 6
DT_S = 60                # simulation timestep
API_CALL_BUDGET = 400_000  # per run; catches infinite loops that touch the API
DEADLINE_CHECK_EVERY = 512


# --------------------------------------------------------------------------
# terrain
# --------------------------------------------------------------------------

class Terrain:
    """Row 0 is NORTH, col 0 is WEST. Get this backwards and every trajectory
    is mirrored, which stays invisible until validation fails."""

    def __init__(self, data_dir):
        d = Path(data_dir)
        self.meta = json.loads((d / "meta.json").read_text())
        b = self.meta["bounds"]
        self.north, self.south = b["north"], b["south"]
        self.east, self.west = b["east"], b["west"]
        self.nrows, self.ncols = self.meta["shape"]
        self.dlat = (self.north - self.south) / self.nrows
        self.dlon = (self.east - self.west) / self.ncols
        self.m_per_deg_lat = self.meta["m_per_deg_lat"]
        self.m_per_deg_lon = self.meta["m_per_deg_lon"]

        # mmap: 33.7 MB resident per sandbox is fine, but mmap starts faster
        # and 200 of these run at once.
        self.elevation = np.load(d / "elevation.npy", mmap_mode="r")
        self.slope = np.load(d / "slope.npy", mmap_mode="r")
        self.trail_dist = np.load(d / "trail_dist.npy", mmap_mode="r")
        self.water_dist = np.load(d / "water_dist.npy", mmap_mode="r")

    def rc(self, lat, lon):
        r = int((self.north - lat) / self.dlat)
        c = int((lon - self.west) / self.dlon)
        # Clamp rather than raise. A walker that leaves the box reads the edge
        # cell; in_bounds() is what decides whether the run is truncated.
        if r < 0:
            r = 0
        elif r >= self.nrows:
            r = self.nrows - 1
        if c < 0:
            c = 0
        elif c >= self.ncols:
            c = self.ncols - 1
        return r, c

    def in_bounds(self, lat, lon):
        return (self.south <= lat <= self.north) and (self.west <= lon <= self.east)


# --------------------------------------------------------------------------
# the narrow API handed to generated code
# --------------------------------------------------------------------------

class Budget(Exception):
    pass


def make_api(terrain, deadline):
    """The ONLY five functions generated code may call, plus math and rng.

    Every one of them burns budget, so a runaway loop that touches terrain
    dies here rather than eating the sandbox's whole 10 s.
    """
    state = {"calls": 0}

    def tick():
        state["calls"] += 1
        if state["calls"] > API_CALL_BUDGET:
            raise Budget("API call budget exhausted ({})".format(API_CALL_BUDGET))
        if state["calls"] % DEADLINE_CHECK_EVERY == 0 and time.monotonic() > deadline:
            raise Budget("wall-clock deadline exceeded")

    def elevation_at(lat, lon):
        tick()
        r, c = terrain.rc(lat, lon)
        return float(terrain.elevation[r, c])

    def slope_at(lat, lon):
        tick()
        r, c = terrain.rc(lat, lon)
        return float(terrain.slope[r, c])

    def dist_to_trail(lat, lon):
        tick()
        r, c = terrain.rc(lat, lon)
        return float(terrain.trail_dist[r, c])

    def dist_to_water(lat, lon):
        tick()
        r, c = terrain.rc(lat, lon)
        return float(terrain.water_dist[r, c])

    def step(lat, lon, bearing, m):
        """Bearing in degrees, 0 = north, 90 = east. Returns (lat, lon)."""
        tick()
        b = math.radians(bearing)
        return (lat + m * math.cos(b) / terrain.m_per_deg_lat,
                lon + m * math.sin(b) / terrain.m_per_deg_lon)

    return {"elevation_at": elevation_at, "slope_at": slope_at,
            "dist_to_trail": dist_to_trail, "dist_to_water": dist_to_water,
            "step": step}, state


def compile_script(source, terrain, deadline):
    """exec the script in a namespace holding only the five API functions,
    math, and the standard builtins it needs. Returns its simulate()."""
    api, state = make_api(terrain, deadline)
    ns = dict(api)
    ns["math"] = math
    ns["DT_S"] = DT_S

    # Models write `import math` however firmly the prompt says not to, and with
    # no __import__ that raises "ImportError: __import__ not found" and costs the
    # whole batch. Measured: 2 of 8 generated scripts died on exactly this.
    # Handing back the already-imported module turns a common, harmless habit
    # into a success. Isolation is the sandbox's job, not this namespace's.
    allowed = {"math": math, "numpy": np, "np": np}

    def _import(name, *a, **k):
        root = name.split(".")[0]
        if root in allowed:
            return allowed[root]
        raise ImportError(
            "{} is not available in a hypothesis script; the terrain API is "
            "already in scope".format(name))

    ns["__builtins__"] = {
        "__import__": _import,
        "abs": abs, "min": min, "max": max, "len": len, "range": range,
        "round": round, "int": int, "float": float, "bool": bool, "str": str,
        "list": list, "tuple": tuple, "dict": dict, "sum": sum, "sorted": sorted,
        "enumerate": enumerate, "zip": zip, "any": any, "all": all,
        "Exception": Exception, "ValueError": ValueError, "print": print,
    }
    exec(compile(source, "<hypothesis>", "exec"), ns)
    fn = ns.get("simulate")
    if not callable(fn):
        raise ValueError("script defines no simulate()")
    return fn, state


# --------------------------------------------------------------------------
# running
# --------------------------------------------------------------------------

def downsample(points, cap=MAX_POINTS):
    """Evenly spaced, always keeping first and last -- the endpoint is what
    the field is built from, so it must survive."""
    n = len(points)
    if n <= cap:
        return points
    idx = [int(round(i * (n - 1) / (cap - 1))) for i in range(cap)]
    seen, out = set(), []
    for i in idx:
        if i not in seen:
            seen.add(i)
            out.append(points[i])
    return out


def one_run(simulate, terrain, start, duration_s, seed, run_index, state=None):
    # The budget is PER RUN. The counter lives in the compiled namespace, which
    # is built once per batch, so without this reset it accumulates across every
    # run and a long batch starves its own tail: 162 of 1200 template runs died
    # as "budget exhausted" purely because they ran late in the batch.
    if state is not None:
        state["calls"] = 0
    rng = np.random.default_rng(seed)
    try:
        raw = simulate(float(start[0]), float(start[1]), int(duration_s), rng)
    except Budget as e:
        return {"run_index": run_index, "status": "failed", "error": str(e)}
    except Exception as e:
        return {"run_index": run_index, "status": "failed",
                "error": "{}: {}".format(type(e).__name__, e)[:200]}

    if raw is None:
        return {"run_index": run_index, "status": "failed",
                "error": "simulate() returned None"}

    pts = []
    for p in raw:
        try:
            lat, lon = float(p[0]), float(p[1])
            t = int(p[2]) if len(p) > 2 else len(pts) * DT_S
        except Exception:
            break
        if not (math.isfinite(lat) and math.isfinite(lon)):
            break
        if not terrain.in_bounds(lat, lon):
            break  # left the box: truncate here, keep what is real
        pts.append([round(lat, 6), round(lon, 6), t])
        if len(pts) > 5000:
            break

    if len(pts) < 2:
        return {"run_index": run_index, "status": "failed",
                "error": "fewer than 2 in-bounds points"}

    pts = downsample(pts)
    return {"run_index": run_index, "points": pts,
            "endpoint": [pts[-1][0], pts[-1][1]],
            "duration_s": pts[-1][2], "status": "ok"}


def run_batch(job, data_dir, budget_s):
    hyp = job["hypothesis"]
    terrain = Terrain(data_dir)
    deadline = time.monotonic() + budget_s

    n_runs = int(hyp.get("n_runs", 60))
    seed_base = int(hyp.get("seed_base", 0))
    duration_s = int(hyp.get("duration_s", 4320))
    start = hyp["start"]

    batch = {
        "hypothesis_id": hyp["hypothesis_id"],
        "family": hyp["family"],
        "weight": hyp.get("weight", 0.0),
        "generated": bool(job.get("generated", False)),
        "runs": [],
    }

    try:
        simulate, state = compile_script(job["script"], terrain, deadline)
    except Exception as e:
        # The whole script is bad. Every run fails; the orchestrator retries
        # with the family template. Counted, not plotted.
        batch["error"] = "compile: {}: {}".format(type(e).__name__, e)[:300]
        batch["runs"] = [{"run_index": i, "status": "failed",
                          "error": "script did not compile"} for i in range(n_runs)]
        return batch

    for i in range(n_runs):
        if time.monotonic() > deadline:
            batch["runs"] += [{"run_index": j, "status": "failed",
                               "error": "batch deadline"} for j in range(i, n_runs)]
            break
        batch["runs"].append(
            one_run(simulate, terrain, start, duration_s, seed_base + i, i,
                    state=state))

    return batch


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", default="/searchlight/job.json")
    ap.add_argument("--out", default="/searchlight/batch.json")
    ap.add_argument("--data-dir", default="/data")
    ap.add_argument("--budget-s", type=float, default=8.0,
                    help="internal deadline; stay under the orchestrator's "
                         "10 s hard timeout so a partial batch still returns")
    args = ap.parse_args()

    t0 = time.monotonic()
    job = json.loads(Path(args.job).read_text())
    try:
        batch = run_batch(job, args.data_dir, args.budget_s)
    except Exception:
        hyp = job.get("hypothesis", {})
        batch = {"hypothesis_id": hyp.get("hypothesis_id", "unknown"),
                 "family": hyp.get("family", "unknown"),
                 "weight": hyp.get("weight", 0.0),
                 "generated": bool(job.get("generated", False)),
                 "runs": [],
                 "error": traceback.format_exc()[-400:]}

    batch["elapsed_s"] = round(time.monotonic() - t0, 3)
    blob = json.dumps(batch, separators=(",", ":"))

    out = Path(args.out)
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(blob)
        # The script that produced it, next to it. If a judge asks whether this
        # is real, opening these two files on a live sandbox and then killing
        # the machine answers it better than a diagram.
        (out.parent / "hypothesis.py").write_text(job.get("script", ""))
    except Exception:
        pass  # stdout is the channel that matters

    # Sentinel-delimited so stray prints from generated code cannot corrupt it.
    sys.stdout.write("---SEARCHLIGHT-BATCH---\n")
    sys.stdout.write(blob)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
