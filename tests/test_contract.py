"""The wire format, checked against docs/CONTRACT.md rather than against habit.

Two producers emit these envelopes -- the orchestrator over a socket and the
client's own fixture source -- and the client reduces one message shape without
knowing which sent it. So the fixtures and the live path have to agree, and the
place they agree is this file.
"""
from __future__ import annotations

import json

import pytest

from server import STATES
from settings import DATA, FIXTURES

# CONTRACT section 9. Every type the orchestrator is allowed to put on the wire.
SERVER_TO_CLIENT = {
    "transcript_partial", "extraction_update", "extraction_complete",
    "case_loaded", "sim_started", "fleet_status", "trajectory_batch",
    "field_update", "evidence_applied", "validation_result", "state_change",
    "fleet_ready", "hypotheses_ready", "log", "pong",
}

# STATES is imported from server.py above rather than restated here, so this
# file cannot become a third copy that agrees with neither end.

MAX_RUNS_PER_MESSAGE = 200


@pytest.fixture(scope="module")
def envelopes():
    """Reuse the offline run from the smoke test rather than doing a second."""
    from pipeline import Pipeline
    from settings import load_case

    out = []
    pipe = Pipeline(emit=lambda t, p: out.append((t, p)), n_sandboxes=4)
    pipe.acquire_fleet()
    try:
        pipe.run(load_case(), total_runs=200, n_hypotheses=4)
    finally:
        pipe.release_fleet()
    return out


def test_no_undocumented_message_types(envelopes):
    emitted = {t for t, _ in envelopes}
    assert emitted <= SERVER_TO_CLIENT, "undocumented types: {}".format(
        sorted(emitted - SERVER_TO_CLIENT))


def test_trajectory_batches_respect_the_run_cap(envelopes):
    """Twelve thousand individual messages will kill the browser, so the
    orchestrator batches. A message over the cap is a frame drop on screen."""
    for kind, payload in envelopes:
        if kind != "trajectory_batch":
            continue
        n = sum(len(b["runs"]) for b in payload["batches"])
        assert n <= MAX_RUNS_PER_MESSAGE, "{} runs in one message".format(n)


def test_a_field_update_carries_everything_the_client_draws(envelopes):
    fields = [p for t, p in envelopes if t == "field_update"]
    assert fields, "a run produced no field at all"
    for f in fields:
        assert set(f["bounds"]) == {"north", "south", "east", "west"}
        assert f["resolution"] == 256
        assert isinstance(f["grid"], str), "grid is base64, not an array"
        assert 0.0 <= f["progress"] <= 1.0
        assert f["n_consistent"] <= f["n_total"]
        assert f["ring_radius_m"] > 0


def test_every_run_carries_an_endpoint_and_a_status(envelopes):
    for kind, payload in envelopes:
        if kind != "trajectory_batch":
            continue
        for batch in payload["batches"]:
            assert isinstance(batch["generated"], bool)
            for run in batch["runs"]:
                assert run["status"] == "ok", "only ok runs go on the wire"
                assert len(run["endpoint"]) == 2


def test_committed_fixtures_still_match_the_contract():
    """The client runs entirely off these with no backend. If they drift from
    the live shape, the offline path rots without anything failing."""
    case = json.loads((FIXTURES / "case.json").read_text(encoding="utf-8"))
    assert case["last_known"]["ipp"]
    assert case["assessment"]["ring_radius_m"] > 0
    assert case["subject"]["category"]

    field = json.loads((FIXTURES / "field.json").read_text(encoding="utf-8"))
    assert set(field["bounds"]) == {"north", "south", "east", "west"}
    assert isinstance(field["grid"], str)
    assert field["zones"]

    fleet = json.loads((FIXTURES / "fleet_status.json").read_text(
        encoding="utf-8"))
    assert isinstance(fleet, list) and fleet, "fleet_status ships a timeline"


def test_the_client_and_the_server_agree_on_the_state_machine():
    """`web/lib/contract.ts` and `orchestrator/server.py` each hold the list.
    They are the two ends of the same keypress, so a divergence is a dead key
    that no typecheck and no Python test would catch on its own."""
    import re
    from pathlib import Path

    ts = Path("web/lib/contract.ts").read_text(encoding="utf-8")
    match = re.search(r"STATES:\s*DemoState\[\]\s*=\s*\[([^\]]+)\]", ts)
    assert match, "could not find STATES in web/lib/contract.ts"
    client_states = tuple(re.findall(r'"([a-z_]+)"', match.group(1)))
    assert client_states == STATES, "client {} vs server {}".format(
        client_states, STATES)


def test_the_bounds_the_client_draws_are_the_bounds_the_worker_walks():
    """web/lib/bbox.json is generated from data/bbox.json. A drift between
    them puts the field on different ground from the trajectories, and nothing
    in either stack would notice."""
    a = json.loads((DATA / "bbox.json").read_text(encoding="utf-8"))
    from pathlib import Path
    b = json.loads(Path("web/lib/bbox.json").read_text(encoding="utf-8"))
    for edge in ("north", "south", "east", "west"):
        assert a[edge] == b[edge], "bbox drift on {}".format(edge)
