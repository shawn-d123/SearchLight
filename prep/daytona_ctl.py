"""Look at the fleet, and kill anything left running.

Idle sandboxes bill by the second and fail silently -- nothing on screen tells
you they are up. Run `status` after any interrupted run.

    python prep/daytona_ctl.py status     # what exists, what it is costing
    python prep/daytona_ctl.py clean      # delete everything tagged searchlight
    python prep/daytona_ctl.py snapshots  # what images exist
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from orchestrator.fleet import COST_PER_SANDBOX_HOUR, load_env, reap  # noqa: E402


def _client():
    load_env()
    import os
    from daytona import Daytona, DaytonaConfig
    key = os.environ.get("DAYTONA_API_KEY", "").strip()
    if not key:
        sys.exit("No DAYTONA_API_KEY in environment or .env")
    return Daytona(DaytonaConfig(api_key=key))


def status():
    d = _client()
    sbs = list(d.list())
    print("{} sandbox(es)".format(len(sbs)))
    running = 0
    for s in sbs:
        state = str(getattr(s, "state", "?"))
        tag = (getattr(s, "labels", None) or {}).get("searchlight", "-")
        if "STARTED" in state.upper() or "RUNNING" in state.upper():
            running += 1
        print("   {:<38} {:<22} searchlight={}".format(
            str(getattr(s, "id", "?")), state, tag))
    if not sbs:
        print("   none - nothing is billing")
        return
    print()
    print("   {} appear to be running: about ${:.3f}/hour, ${:.2f}/day"
          .format(running, running * COST_PER_SANDBOX_HOUR,
                  running * COST_PER_SANDBOX_HOUR * 24))
    if running:
        print("   delete them with: python prep/daytona_ctl.py clean")


def snapshots():
    d = _client()
    page = d.snapshot.list()
    items = getattr(page, "items", None) or []
    print("{} snapshot(s)".format(len(items)))
    for s in items:
        print("   {:<34} {}".format(str(getattr(s, "name", "?")),
                                    str(getattr(s, "state", "?"))))


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "status":
        status()
    elif cmd == "clean":
        reap(dry_run=False)
    elif cmd == "snapshots":
        snapshots()
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
