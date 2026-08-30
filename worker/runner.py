"""Run one hypothesis inside the sandbox and return a trajectory batch.

This is the entry point Daytona executes. One sandbox holds ONE generated
movement script and runs it many times with different seeds, so the unit of
work is a batch, not a trajectory: 200 sandboxes x 60 seeds = 12,000
simulations from 200 model calls.

The contract with the rest of the system is total:

  - a batch ALWAYS comes back, whatever the generated code did
  - failures are counted, never plotted
  - `generated: false` means the deterministic template ran instead

**The demo must be able to run with zero successful generations.** That is not
a nice-to-have; it is the reason the fallback exists and why it was built
first. A failure count on screen is credibility, not weakness.

    python -m worker.runner hypothesis.json > batch.json
    echo '{...}' | python -m worker.runner
"""
from __future__ import annotations

import json
import sys
import traceback

import numpy as np

from .templates import FAMILIES, PARAMS, simulate, to_batch
from .terrain import Terrain

# Hard timeout per worker. Generated code can loop forever; the fleet cannot
# wait for it. POSIX only -- inside the sandbox that is fine, and on Windows
# (local testing) execution simply runs untimed.
TIMEOUT_S = 10


class _Timeout(Exception):
    pass


class time_limit:
    """SIGALRM guard. A no-op where signals are unavailable."""

    def __init__(self, seconds):
        self.seconds = seconds
        self.ok = False

    def __enter__(self):
        try:
            import signal
            self._signal = signal
            self._old = signal.signal(signal.SIGALRM, self._fire)
            signal.alarm(self.seconds)
            self.ok = True
        except (ImportError, AttributeError, ValueError):
            self.ok = False       # Windows, or not the main thread
        return self

    def _fire(self, signum, frame):
        raise _Timeout("generated script exceeded {}s".format(self.seconds))

    def __exit__(self, *exc):
        if self.ok:
            self._signal.alarm(0)
            self._signal.signal(self._signal.SIGALRM, self._old)
        return False


def validate_hypothesis(h):
    """Reject a malformed hypothesis loudly rather than guessing at it."""
    if not isinstance(h, dict):
        raise ValueError("hypothesis must be an object")
    family = h.get("family")
    if family not in FAMILIES:
        raise ValueError("family {!r} not one of {}".format(
            family, ", ".join(FAMILIES)))
    start = h.get("start")
    if not (isinstance(start, (list, tuple)) and len(start) == 2):
        raise ValueError("start must be [lat, lon]")
    if not (-90 <= float(start[0]) <= 90 and -180 <= float(start[1]) <= 180):
        raise ValueError("start {} is not a plausible [lat, lon] -- check the "
                         "ordering, the contract is lat first".format(start))
    return {
        "hypothesis_id": h.get("hypothesis_id", "h_unknown"),
        "family": family,
        "start": (float(start[0]), float(start[1])),
        "duration_s": int(h.get("duration_s", 14400)),
        "n_runs": int(h.get("n_runs", 60)),
        "seed_base": int(h.get("seed_base", 0)),
        "weight": float(h.get("weight", 0.0)) or 1.0,
        "params": h.get("params") or None,
    }


def _check_output(points, ok, n_runs, points_out):
    """A generated script is not trusted until its output is checked."""
    points = np.asarray(points, dtype=np.float64)
    ok = np.asarray(ok, dtype=bool)
    if points.shape != (n_runs, points_out, 3):
        raise ValueError("points shape {} != {}".format(
            points.shape, (n_runs, points_out, 3)))
    if ok.shape != (n_runs,):
        raise ValueError("ok shape {} != {}".format(ok.shape, (n_runs,)))
    if not np.all(np.isfinite(points)):
        raise ValueError("points contain NaN or inf")
    if np.abs(points[:, :, 0]).max() > 90 or np.abs(points[:, :, 1]).max() > 180:
        raise ValueError("points outside plausible lat/lon -- likely lon/lat swapped")
    if (np.diff(points[:, :, 2], axis=1) < 0).any():
        raise ValueError("timestamps are not monotonically increasing")
    return points, ok


def _distance_sane(points, ok, start, terrain, max_median_km):
    """Reject a generated script whose walkers run away.

    Shape validation is not enough. Scripts that satisfy every structural rule
    still invented their own pace, and the fleet-wide p95 came out at 18 km
    against a published 9.55 -- the tail was wrong even though p25/p50/p75 were
    close.

    The bound is deliberately loose (a MULTIPLE of the published p95, applied to
    the batch MEDIAN) because families legitimately differ: staying_put should
    barely move and route_travelling should travel. This catches runaway
    scripts, not long ones.
    """
    import numpy as np
    if max_median_km <= 0 or not ok.any():
        return True, 0.0
    end = points[ok][:, -1, :2]
    d = np.hypot((end[:, 0] - start[0]) * terrain.m_lat,
                 (end[:, 1] - start[1]) * terrain.m_lon) / 1000.0
    med = float(np.median(d))
    return med <= max_median_km, med


def run_hypothesis(h, terrain, script=None, timeout_s=TIMEOUT_S,
                   max_median_km=0.0):
    """Execute one hypothesis. Returns (batch, note).

    `script` is model-written Python defining `move(terrain, start, duration_s,
    n_runs, seed) -> (points, ok)`. Anything at all going wrong -- syntax
    error, exception, timeout, wrong shape, NaN, swapped coordinates -- falls
    back to the family template and marks the batch `generated: false`.
    """
    spec = validate_hypothesis(h)
    generated = False
    note = ""
    points = ok = None

    if script:
        try:
            ns = {"np": np, "numpy": np}
            with time_limit(timeout_s) as guard:
                exec(compile(script, "<generated>", "exec"), ns)
                fn = ns.get("move")
                if not callable(fn):
                    raise ValueError("script defines no callable move()")
                points, ok = fn(terrain, spec["start"], spec["duration_s"],
                                spec["n_runs"], spec["seed_base"])
            points, ok = _check_output(points, ok, spec["n_runs"],
                                       len(points[0]) if len(points) else 0)
            sane, med = _distance_sane(points, ok, spec["start"], terrain,
                                       max_median_km)
            if not sane:
                raise ValueError(
                    "median endpoint {:.1f} km exceeds the {:.1f} km sanity "
                    "bound".format(med, max_median_km))
            generated = True
            if not guard.ok:
                note = "ran untimed: no SIGALRM on this platform"
        except _Timeout as e:
            note = str(e)
            points = ok = None
        except Exception as e:
            # One line, not a traceback. 200 sandboxes failing verbosely is
            # unreadable, and the count is what goes on screen.
            note = "{}: {}".format(type(e).__name__, str(e).split("\n")[0][:160])
            points = ok = None

    if points is None:
        points, ok = simulate(terrain, spec["family"], spec["start"],
                              spec["duration_s"], spec["n_runs"],
                              seed=spec["seed_base"], params=spec["params"])

    batch = to_batch(points, ok, spec["hypothesis_id"], spec["family"],
                     spec["weight"], spec["duration_s"], generated=generated)
    if note:
        batch["note"] = note
    return batch, note


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    raw = open(argv[0]).read() if argv else sys.stdin.read()
    payload = json.loads(raw)
    h = payload.get("hypothesis", payload)
    script = payload.get("script")

    try:
        terrain = Terrain(payload.get("data_dir"))
    except Exception as e:
        # No terrain means no work. Say so in the batch rather than crashing
        # the sandbox, so the fleet counts it instead of hanging on it.
        json.dump({"hypothesis_id": h.get("hypothesis_id", "h_unknown"),
                   "family": h.get("family", "route_travelling"),
                   "weight": 0.0, "generated": False, "runs": [],
                   "note": "terrain unavailable: {}".format(e)}, sys.stdout)
        return 1

    batch, _ = run_hypothesis(h, terrain, script)
    json.dump(batch, sys.stdout, separators=(",", ":"))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc(file=sys.stderr)
        sys.exit(2)
