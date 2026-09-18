"""The whole product, end to end, with no keys and no network.

This is the smoke test. It drives the real pipeline -- real hypothesis
expansion against the published priors, the real movement code, the real
aggregation, the real evidence filter -- and asserts the things that would make
the project wrong rather than merely broken.

Deliberately not "it did not crash". A run that completes while putting the
probability mass in the wrong place, or while quietly reporting a ring that
moved when evidence arrived, is a worse failure than an exception.

    python -m pytest tests -q
"""
from __future__ import annotations

import socket

import pytest

import settings
from pipeline import Pipeline
from model.field import apply_evidence

# Small enough to run in a few seconds, large enough that the evidence filter
# has something to discriminate between. At 200 runs the witness report keeps
# everything and the collapse assertion passes for the wrong reason.
TOTAL_RUNS = 400
N_HYPOTHESES = 5
N_LANES = 4

# Aimed at the field's densest zone, which is how the client builds it: a fixed
# coordinate eventually falls where no simulation went, the filter discards
# everything, and the aggregation raises on an empty grid.
EVIDENCE_RADIUS_M = 1200
EVIDENCE_T_S = 5400


# --- no network ------------------------------------------------------------

@pytest.fixture(autouse=True)
def no_outbound_network(monkeypatch):
    """Fail loudly on any connection that leaves the machine.

    Without this, a developer with keys in their shell would exercise the live
    path and the suite would pass for a reason CI cannot reproduce.
    """
    real_connect = socket.socket.connect

    def guarded(self, address, *args, **kwargs):
        host = address[0] if isinstance(address, tuple) else ""
        if host in ("127.0.0.1", "::1", "localhost", ""):
            return real_connect(self, address, *args, **kwargs)
        raise AssertionError(
            "offline mode attempted an outbound connection to {}".format(host))

    monkeypatch.setattr(socket.socket, "connect", guarded)


# --- one run, shared by every assertion ------------------------------------

@pytest.fixture(scope="module")
def run():
    """One offline run. Returns (case, batches, envelopes)."""
    from settings import load_case

    envelopes = []
    pipe = Pipeline(emit=lambda t, p: envelopes.append((t, p)),
                    n_sandboxes=N_LANES)
    pipe.acquire_fleet()
    case = load_case()
    try:
        result = pipe.run(case, total_runs=TOTAL_RUNS,
                          n_hypotheses=N_HYPOTHESES)
    finally:
        pipe.release_fleet()
    return case, result, envelopes


def _fields(envelopes):
    return [p for t, p in envelopes if t == "field_update"]


# --- the guarantees --------------------------------------------------------

def test_no_key_is_needed_or_used():
    assert settings.offline()
    import codegen
    # The one that used to raise SystemExit from inside a function argument.
    assert codegen.client() is None
    for name in ("OPENAI_API_KEY", "DAYTONA_API_KEY", "PARALLEL_API_KEY"):
        assert not settings.have_key(name)


def test_every_planned_simulation_runs(run):
    _, result, _ = run
    runs = [r for b in result["batches"] for r in b["runs"]]
    ok = [r for r in runs if r["status"] == "ok"]
    assert len(runs) == TOTAL_RUNS, "planned and executed run counts disagree"
    # Individual runs may fail on their own merits; a wholesale failure means
    # the terrain, the templates or the budget is wrong.
    assert len(ok) >= 0.95 * TOTAL_RUNS, "{} of {} runs failed".format(
        len(runs) - len(ok), len(runs))


def test_offline_batches_are_reported_as_ungenerated(run):
    """The honesty rule. Nothing may claim model-written code that never ran."""
    _, result, _ = run
    assert all(b["generated"] is False for b in result["batches"])
    assert result["n_generated"] == 0


def test_the_field_concentrates_inside_the_ring(run):
    """The claim the project exists to make.

    field_area_pct is the smallest region holding 50% of the probability mass,
    as a percentage of the ISRID ring's area. A terrain-aware field has to be a
    fraction of the circle, or the circle was the right answer all along.
    """
    _, _, envelopes = run
    field = _fields(envelopes)[-1]
    assert 0 < field["field_area_pct"] < 50, (
        "field covers {}% of the ring".format(field["field_area_pct"]))
    assert field["zones"], "no named zones on a completed field"
    assert sum(z["pct"] for z in field["zones"]) <= 100.5


def test_the_final_field_says_it_is_final(run):
    """The client sizes its progress and decides the field has settled on this."""
    _, _, envelopes = run
    assert _fields(envelopes)[-1]["progress"] == 1.0


def test_evidence_shrinks_the_field_and_leaves_the_ring_alone(run):
    """A ring cannot respond to evidence. That is the whole argument.

    The witness report must discard runs, shrink the 50%-mass region, and leave
    the published ring radius untouched -- the comparison is only honest if the
    ring is the same ring before and after.
    """
    case, result, envelopes = run
    before = _fields(envelopes)[-1]
    zone = before["zones"][0]

    evidence = {"lat": zone["centroid"][0], "lon": zone["centroid"][1],
                "t": EVIDENCE_T_S, "radius_m": EVIDENCE_RADIUS_M,
                "tolerance_s": 900, "reliability": 1.0}
    _filtered, after = apply_evidence(
        result["batches"], evidence, bounds=case["bounds"], resolution=256,
        ring_radius_m=case.get("ring_radius_m"))

    assert after["n_consistent"] < after["n_total"], (
        "evidence discarded nothing; the filter is not filtering")
    assert after["n_consistent"] > 0, "evidence discarded everything"
    assert after["field_area_pct"] < before["field_area_pct"], (
        "field did not collapse: {}% -> {}%".format(
            before["field_area_pct"], after["field_area_pct"]))
    assert after["ring_radius_m"] == before["ring_radius_m"], (
        "the ring moved when evidence arrived")


def test_the_ring_radius_comes_from_the_priors_not_the_model(run):
    """`ring_radius_m` is derived from ISRID quantiles keyed on the subject
    category. A search radius invented by a language model is the thing this
    project is arguing against."""
    import json

    import extract
    from settings import DATA

    priors = json.loads((DATA / "priors.json").read_text(encoding="utf-8"))
    expected = round(priors["ring_radius_km"] * 1000.0, 1)

    _, _, envelopes = run
    assert _fields(envelopes)[-1]["ring_radius_m"] == expected
    assert extract.ring_radius_m("hiker", priors) == expected


def test_offline_extraction_never_claims_to_be_live():
    """With no model, intake falls back to the recorded report -- and says so.
    Presenting a canned card as a live extraction is the one thing in this
    product a reader can catch by asking to speak into the microphone."""
    import extract

    transcript = (settings.FIXTURES / "transcript.txt").read_text(
        encoding="utf-8")
    payload, error = extract.extract(transcript)

    assert payload["source"] == "fallback"
    assert error and "offline" in error
    assert payload["last_known"]["ipp"], "fallback still has to carry an IPP"
