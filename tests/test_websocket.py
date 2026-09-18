"""The socket, driven the way the client drives it.

Runs against the ASGI app in-process, so there is no port to bind and no server
to wait for. Everything it asserts is a promise CONTRACT section 9 makes to a
client that cannot see the server's internals.
"""
from __future__ import annotations

import json

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402


@pytest.fixture(scope="module")
def client():
    # Small run: this is about the envelope stream, not about the field.
    server.CONFIG["total_runs"] = 200
    server.CONFIG["n_hypotheses"] = 4
    with TestClient(server.app) as c:
        yield c


def _drain_until(ws, kind, limit=400, predicate=None):
    """Collect envelopes until `kind` arrives (optionally satisfying
    `predicate`). Returns everything seen, in wire order."""
    out = []
    for _ in range(limit):
        env = json.loads(ws.receive_text())
        out.append(env)
        if env["type"] == kind and (predicate is None or predicate(env["payload"])):
            return out
    raise AssertionError("never saw {} in {} messages".format(kind, limit))


def test_health_reports_the_mode_it_is_actually_in(client):
    body = client.get("/health").json()
    assert body["ok"] is True
    assert body["offline"] is True, "the suite must never reach the network"


def test_a_case_is_on_the_wire_before_anything_is_asked_for(client):
    """The map draws the ring, the IPP marker and its framing from case_loaded.
    Without one on connect there is nothing on screen between connecting and
    starting a run."""
    with client.websocket_connect("/ws") as ws:
        seen = _drain_until(ws, "state_change")
        kinds = [e["type"] for e in seen]
        assert "case_loaded" in kinds
        case = next(e for e in seen if e["type"] == "case_loaded")["payload"]
        assert case["ipp"], "case_loaded with no IPP is not a case"
        assert case["ring_radius_m"] > 0


def test_seq_never_goes_backwards(client):
    """Section 9: wire order and seq order always agree, so a client may order
    and de-duplicate on seq alone. The replayed history carries its original
    seq, so it has to precede anything stamped at connect time."""
    with client.websocket_connect("/ws") as ws:
        seen = _drain_until(ws, "state_change")
        ws.send_text(json.dumps({"type": "run", "payload": {
            "total_runs": 200, "n_hypotheses": 4}}))
        seen += _drain_until(
            ws, "field_update", limit=600,
            predicate=lambda p: p["progress"] >= 1.0)

    seqs = [e["seq"] for e in seen]
    backwards = [(a, b) for a, b in zip(seqs, seqs[1:]) if b <= a]
    assert not backwards, "seq went backwards at {}".format(backwards[:3])


def test_a_run_reaches_a_finished_field_over_the_socket(client):
    with client.websocket_connect("/ws") as ws:
        _drain_until(ws, "state_change")
        ws.send_text(json.dumps({"type": "run", "payload": {
            "total_runs": 200, "n_hypotheses": 4}}))
        seen = _drain_until(
            ws, "field_update", limit=600,
            predicate=lambda p: p["progress"] >= 1.0)

        field = seen[-1]["payload"]
        assert 0 < field["field_area_pct"] < 50
        assert field["zones"]

        # The witness report, aimed at the field that was actually produced.
        zone = field["zones"][0]
        ws.send_text(json.dumps({"type": "evidence", "payload": {
            "lat": zone["centroid"][0], "lon": zone["centroid"][1],
            "t": 5400, "radius_m": 1200, "tolerance_s": 900,
            "reliability": 1.0}}))
        applied = _drain_until(ws, "evidence_applied", limit=200)[-1]["payload"]

    assert applied["n_consistent"] < applied["n_total"]
    assert applied["field_area_pct"] < field["field_area_pct"]
    assert applied["ring_radius_m"] == field["ring_radius_m"], (
        "the ring moved when evidence arrived")
    assert applied["evidence"]["radius_m"] == 1200, (
        "evidence_applied has to echo the report it applied")


def test_ping_answers_pong(client):
    with client.websocket_connect("/ws") as ws:
        _drain_until(ws, "state_change")
        ws.send_text(json.dumps({"type": "ping", "payload": {}}))
        assert _drain_until(ws, "pong", limit=50)[-1]["payload"]["t"] > 0
