"""Put the orchestrator on the path and force offline before anything imports.

`orchestrator/` uses flat imports (`from settings import ...`) because its
modules are also uploaded to a sandbox, where there is no package around them.
That means the directory itself has to be importable, not just the repo root.

Offline is set here rather than in a fixture because `settings` reads the
environment at import time, and the first test module to touch it wins.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

os.environ["SEARCHLIGHT_OFFLINE"] = "1"
# Any key left in the developer's shell would otherwise let a test reach the
# network and quietly pass for the wrong reason.
for name in ("OPENAI_API_KEY", "DAYTONA_API_KEY", "PARALLEL_API_KEY",
             "OPENTOPO_API_KEY"):
    os.environ.pop(name, None)

for path in (ROOT, ROOT / "orchestrator", ROOT / "worker"):
    sys.path.insert(0, str(path))
