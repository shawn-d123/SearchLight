"""Paths and keys. Imported by everything else in orchestrator/."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
MOCKS = ROOT / "mocks"
WORKER = ROOT / "worker"

# 1 GiB, not 2. Measured against the live account: the binding limit is TOTAL
# MEMORY 10 GiB (and total CPU 10), so a 2 GiB worker caps the fleet at 5 while
# a 1 GiB worker caps it at 10. A worker mmaps 33.7 MB of terrain and holds a
# few thousand floats; 1 GiB is not close to tight. See prep/TIMINGS.md.
SNAPSHOT = "searchlight-worker-1g"
SNAPSHOT_CPU = 1
SNAPSHOT_MEM_GIB = 1

# The account tier's ceiling, measured not assumed. min(10 CPU, 10 GiB / 1 GiB).
MAX_SANDBOXES = 10

# Inside the sandbox. Both files are left in place on purpose -- see sim.py.
SB_DIR = "/searchlight"
SB_SIM = SB_DIR + "/sim.py"
SB_JOB = SB_DIR + "/job.json"
SB_OUT = SB_DIR + "/batch.json"
SB_DATA = "/data"

# CONTRACT.md section 6 / worker README: hard timeout per worker.
WORKER_TIMEOUT_S = 10
WORKER_BUDGET_S = 8.0   # sim.py's own deadline, inside the hard timeout


def _load_dotenv():
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


_load_dotenv()


def normalise_case(raw):
    """Flatten the CONTRACT section 8 extraction payload into what the
    simulation needs.

    `mocks/case.json` is now the intake payload -- nested `subject`,
    `last_known` and `assessment` objects -- rather than the old flat mock with
    `ipp` and `last_contact_s_ago` at the top level. Both shapes are accepted so
    a stale mock, or a live extraction, works without a second code path.
    """
    lk = raw.get("last_known") or {}
    subj = raw.get("subject") or {}
    assess = raw.get("assessment") or {}

    ipp = lk.get("ipp") or raw.get("ipp")
    if not ipp:
        raise ValueError("case has no IPP (last_known.ipp)")

    elapsed_min = lk.get("elapsed_min")
    duration_s = (int(round(elapsed_min * 60)) if elapsed_min is not None
                  else int(raw.get("last_contact_s_ago", 4320)))

    out = dict(raw)
    out["ipp"] = [float(ipp[0]), float(ipp[1])]
    out["last_contact_s_ago"] = duration_s
    out["subject_category"] = (subj.get("category")
                               or raw.get("subject_category") or "hiker")
    out["subject_name"] = subj.get("name") or raw.get("subject_name") or "unknown"
    out["conditions"] = (assess.get("conditions")
                         or raw.get("conditions") or "clear, daylight")
    out["ring_radius_m"] = (raw.get("ring_radius_m")
                            or assess.get("ring_radius_m"))
    out["terrain"] = raw.get("terrain", "Mountainous")
    return out


def load_case(path=None):
    import json
    p = path or (MOCKS / "case.json")
    return normalise_case(json.loads(open(p, encoding="utf-8").read()))


def key(name, required=True):
    v = os.environ.get(name, "").strip()
    if not v and required:
        raise SystemExit(
            "{} is not set. Put it in {} (gitignored).".format(name, ROOT / ".env"))
    return v
