"""Phase 5.2 — `consensus.v1` agent tests.

Cover the must-have invariants from ROADMAP §5.2:

  * Single publication of ``predict.final`` per
    ``(match_id, market, request_id)``
  * Late-vote drop emits ``proof.flag`` (kind=late_vote_dropped)
  * Quorum-empty (zero votes after window flush) emits ``proof.flag``
    (kind=consensus_no_votes) — and **no** predict.final
  * At-least-once redelivery is a no-op (idempotency)
  * Weighted fusion respects per-predictor weights
  * Calibration table is applied + re-normalized
  * Score grid is averaged when ≥1 vote provides one, omitted otherwise
  * `degraded=true` when voters < cfg.consensus_min_voters
  * request_id round-trips unchanged from vote → final
  * prediction_id is deterministic across runs (sha256 invariant)
"""
from __future__ import annotations

import math

import pytest

from swarm.agents.consensus import ConsensusAgent
from swarm.agents.payloads import (
    PredictFinal,
    PredictVote,
    derive_prediction_id,
)
from swarm.agents.predictors._base import (
    CalibrationTable,
    InMemoryCalibrationStore,
)
from swarm.agents.reactor import InMemoryLedger
from swarm.agents.topics import PREDICT_FINAL, PREDICT_VOTE, PROOF_FLAG
from swarm.sdk.types import Message


def _vote(
    predictor_id: str,
    pmf: dict,
    *,
    market: str = "1x2",
    request_id: str = "r-1",
    match_id: str = "m-1",
    confidence: float = 0.7,
    score_grid=None,
    trace_id: str = "trace-Z",
) -> Message:
    distribution = {"market_outcomes": pmf, "score_grid": score_grid}
    return Message.new(
        PREDICT_VOTE,
        PredictVote(
            request_id=request_id,
            match_id=match_id,
            market=market,
            predictor_id=predictor_id,
            distribution=distribution,
            confidence=confidence,
        ).as_dict(),
        producer=predictor_id,
        trace_id=trace_id,
    )


def _make_consensus(**kw) -> ConsensusAgent:
    defaults = dict(
        expected_predictors=("p.a", "p.b", "p.c"),
        ledger=InMemoryLedger(),
        calibration_store=InMemoryCalibrationStore(),
        clock_ms=lambda: 0.0,
        clock_iso=lambda: "2025-01-01T00:00:00+00:00",
        window_ms=1_000,
        min_voters=2,
    )
    defaults.update(kw)
    return ConsensusAgent(**defaults)


# ── Single publication / quorum / fusion ────────────────────────


def test_finalizes_when_all_expected_voters_in():
    c = _make_consensus()
    out = []
    out += list(c.handle(_vote("p.a", {"H": 0.7, "D": 0.2, "A": 0.1})))
    out += list(c.handle(_vote("p.b", {"H": 0.6, "D": 0.3, "A": 0.1})))
    assert out == []  # not all in yet
    out += list(c.handle(_vote("p.c", {"H": 0.5, "D": 0.3, "A": 0.2})))
    assert len(out) == 1
    assert out[0].envelope.topic == PREDICT_FINAL
    final = PredictFinal.from_dict(out[0].payload)
    assert final.request_id == "r-1"
    assert final.match_id == "m-1"
    assert final.market == "1x2"
    assert sorted(final.contributing_models) == ["p.a", "p.b", "p.c"]
    pmf = final.distribution["market_outcomes"]
    assert math.isclose(sum(pmf.values()), 1.0, abs_tol=1e-9)
    assert pmf["H"] > pmf["D"] > pmf["A"]
    assert final.degraded is False


def test_publishes_only_once_late_vote_emits_proof_flag():
    c = _make_consensus()
    list(c.handle(_vote("p.a", {"H": 0.5, "D": 0.3, "A": 0.2})))
    list(c.handle(_vote("p.b", {"H": 0.5, "D": 0.3, "A": 0.2})))
    out = list(c.handle(_vote("p.c", {"H": 0.5, "D": 0.3, "A": 0.2})))
    assert len(out) == 1 and out[0].envelope.topic == PREDICT_FINAL

    late = list(c.handle(_vote("p.a", {"H": 0.99, "D": 0.005, "A": 0.005})))
    assert len(late) == 1
    assert late[0].envelope.topic == PROOF_FLAG
    assert late[0].payload["kind"] == "late_vote_dropped"
    assert late[0].payload["match_id"] == "m-1"
    assert late[0].payload["request_id"] == "r-1"


def test_quorum_empty_after_flush_emits_proof_flag_no_final():
    """If a request was noted but zero votes arrived before the
    window closed, emit ``proof.flag`` (kind=consensus_no_votes) and
    NEVER emit ``predict.final``."""
    from swarm.agents.payloads import PredictRequest as _PR
    c = _make_consensus()
    c.note_request(_PR(
        request_id="r-empty", match_id="m-empty", market="1x2", features={},
    ))
    out = c.flush_all()
    assert len(out) == 1
    assert out[0].envelope.topic == PROOF_FLAG
    assert out[0].payload["kind"] == "consensus_no_votes"
    assert out[0].payload["match_id"] == "m-empty"
    assert out[0].payload["request_id"] == "r-empty"


def test_window_expiry_with_votes_finalizes():
    """If only some predictors voted but the window expires, finalize
    with whatever we have and mark degraded."""
    c = _make_consensus(min_voters=3)  # need 3 to be non-degraded
    list(c.handle(_vote("p.a", {"H": 0.6, "D": 0.3, "A": 0.1})))
    out = c.flush_all()
    assert len(out) == 1
    assert out[0].envelope.topic == PREDICT_FINAL
    final = PredictFinal.from_dict(out[0].payload)
    assert final.degraded is True
    assert "1/3" in final.degraded_reason
    assert final.contributing_models == ["p.a"]


def test_at_least_once_redelivery_is_idempotent():
    """Re-handling the *same* vote message twice must not double-count."""
    c = _make_consensus()
    msg = _vote("p.a", {"H": 0.5, "D": 0.3, "A": 0.2})
    list(c.handle(msg))
    list(c.handle(msg))  # exact replay
    list(c.handle(_vote("p.b", {"H": 0.5, "D": 0.3, "A": 0.2})))
    out = list(c.handle(_vote("p.c", {"H": 0.5, "D": 0.3, "A": 0.2})))
    assert len(out) == 1
    final = PredictFinal.from_dict(out[0].payload)
    # p.a should appear exactly once in contributing_models.
    assert final.contributing_models.count("p.a") == 1


# ── Fusion math ────────────────────────────────────────────────


def test_weighted_fusion_respects_per_predictor_weights():
    c = _make_consensus(
        expected_predictors=("p.a", "p.b"),
        weights={"p.a": 9.0, "p.b": 1.0},  # heavily favor p.a
        min_voters=2,
    )
    list(c.handle(_vote("p.a", {"H": 0.9, "D": 0.05, "A": 0.05})))
    out = list(c.handle(_vote("p.b", {"H": 0.1, "D": 0.45, "A": 0.45})))
    final = PredictFinal.from_dict(out[0].payload)
    pmf = final.distribution["market_outcomes"]
    # Weighted mean of H: (9*0.9 + 1*0.1)/10 = 0.82
    assert math.isclose(pmf["H"], 0.82, abs_tol=1e-9)


def test_calibration_table_is_applied_and_renormalized():
    cal_store = InMemoryCalibrationStore()
    # Step-isotonic table that squashes the favorite's bucket.
    # Bins: (0.0,0.0), (0.45,0.10), (0.55,0.55), (1.0,1.0).
    # Effective mapping (step-lookup of y[max(lo-1,0)]):
    #   p ∈ [0,    0.45)  → 0.0
    #   p ∈ [0.45, 0.55)  → 0.0  (still y[0]; the upper bin only kicks in at exact 0.55)
    #   p ≥ 0.55          → 0.55
    # We pick raw probs that span both sides so renormalization
    # produces a non-trivial result.
    table = CalibrationTable(
        profile_id="default",
        market="1x2",
        version=7,
        x=(0.0, 0.45, 0.55, 1.0),
        y=(0.10, 0.40, 0.55, 1.0),
    )
    cal_store.upsert(table)
    c = _make_consensus(
        expected_predictors=("p.a", "p.b"),
        calibration_store=cal_store,
        min_voters=2,
    )
    list(c.handle(_vote("p.a", {"H": 0.5, "D": 0.3, "A": 0.2})))
    out = list(c.handle(_vote("p.b", {"H": 0.5, "D": 0.3, "A": 0.2})))
    final = PredictFinal.from_dict(out[0].payload)
    pmf = final.distribution["market_outcomes"]
    assert math.isclose(sum(pmf.values()), 1.0, abs_tol=1e-9)
    # D and A both fell into the lowest calibration bin (y[0]=0.10),
    # so after renormalization they must be equal — a fingerprint
    # that the table actually fired.
    assert math.isclose(pmf["D"], pmf["A"], abs_tol=1e-9)
    # H landed in a higher bin (y[1]=0.40), so it must outweigh D.
    assert pmf["H"] > pmf["D"]
    assert final.calibration_version == 7


def test_score_grid_averaged_only_when_some_vote_carries_one():
    c = _make_consensus(expected_predictors=("p.a", "p.b"), min_voters=2)
    grid = [[0.10, 0.20], [0.30, 0.40]]
    list(c.handle(_vote("p.a", {"H": 0.5, "D": 0.3, "A": 0.2}, score_grid=grid)))
    out = list(c.handle(_vote("p.b", {"H": 0.5, "D": 0.3, "A": 0.2})))
    final = PredictFinal.from_dict(out[0].payload)
    fused_grid = final.distribution["score_grid"]
    assert fused_grid is not None
    s = sum(c for row in fused_grid for c in row)
    assert math.isclose(s, 1.0, abs_tol=1e-9)


def test_score_grid_omitted_when_no_vote_carries_one():
    c = _make_consensus(expected_predictors=("p.a", "p.b"), min_voters=2)
    list(c.handle(_vote("p.a", {"H": 0.5, "D": 0.3, "A": 0.2})))
    out = list(c.handle(_vote("p.b", {"H": 0.5, "D": 0.3, "A": 0.2})))
    final = PredictFinal.from_dict(out[0].payload)
    assert final.distribution["score_grid"] is None


# ── Trace / id invariants ──────────────────────────────────────


def test_trace_id_passes_through_to_final():
    c = _make_consensus(expected_predictors=("p.a",), min_voters=1)
    out = list(c.handle(_vote("p.a", {"H": 0.5, "D": 0.3, "A": 0.2}, trace_id="trace-XYZ")))
    assert out[0].envelope.trace_id == "trace-XYZ"


def test_request_id_round_trips_unchanged():
    c = _make_consensus(expected_predictors=("p.a",), min_voters=1)
    rid = "r-roundtrip-7e9f"
    out = list(
        c.handle(_vote("p.a", {"H": 0.5, "D": 0.3, "A": 0.2}, request_id=rid))
    )
    final = PredictFinal.from_dict(out[0].payload)
    assert final.request_id == rid


def test_prediction_id_is_deterministic_sha256_of_inputs():
    """Two independent runs over identical input must yield the same
    prediction_id (the swarm-wide single-publication key)."""
    pid1 = derive_prediction_id(
        match_id="m", market="1x2", request_id="r", calibration_version=3
    )
    pid2 = derive_prediction_id(
        match_id="m", market="1x2", request_id="r", calibration_version=3
    )
    assert pid1 == pid2
    # Different inputs MUST produce different ids.
    pid3 = derive_prediction_id(
        match_id="m", market="1x2", request_id="r", calibration_version=4
    )
    assert pid3 != pid1
    # And it's hex (sha256-derived), 32 chars.
    assert len(pid1) == 32
    int(pid1, 16)  # raises if not hex


def test_prediction_id_in_final_matches_derive():
    c = _make_consensus(expected_predictors=("p.a",), min_voters=1)
    out = list(c.handle(_vote("p.a", {"H": 0.5, "D": 0.3, "A": 0.2})))
    final = PredictFinal.from_dict(out[0].payload)
    expected = derive_prediction_id(
        match_id="m-1",
        market="1x2",
        request_id="r-1",
        calibration_version=final.calibration_version,
    )
    assert final.prediction_id == expected


# ── Phase 5 review (2026-04-28): perf + dead-knob + bound ──────


class _CountingCalibrationStore(InMemoryCalibrationStore):
    """Wraps the in-memory store and counts ``latest()`` invocations.

    Used to lock in the ROADMAP §5.2 invariant: consensus hits the
    calibration store **at most once** per
    ``(match_id, market, request_id)`` regardless of how many votes
    arrive for it.
    """

    def __init__(self) -> None:
        super().__init__()
        self.latest_calls = 0

    def latest(self, profile_id: str, market: str) -> CalibrationTable:  # type: ignore[override]
        self.latest_calls += 1
        return super().latest(profile_id, market)


def test_calibration_store_is_hit_at_most_once_per_request():
    """ROADMAP §5.2: 'Single calibration-store hit per request.'

    Three votes for the same key must call ``CalibrationStore.latest``
    exactly once — the first vote caches the table on
    ``_PendingFusion`` and ``_finalize`` reuses it.
    """
    cal_store = _CountingCalibrationStore()
    c = _make_consensus(calibration_store=cal_store)
    list(c.handle(_vote("p.a", {"H": 0.7, "D": 0.2, "A": 0.1})))
    list(c.handle(_vote("p.b", {"H": 0.6, "D": 0.3, "A": 0.1})))
    list(c.handle(_vote("p.c", {"H": 0.5, "D": 0.3, "A": 0.2})))
    assert cal_store.latest_calls == 1, (
        f"expected exactly 1 calibration-store hit, got {cal_store.latest_calls}"
    )


def test_low_confidence_votes_are_dropped_silently():
    """SWARM.md consensus algo step 2 + new §5.2 bullet:
    votes with ``confidence < cfg.consensus_min_confidence`` are dropped
    without contributing to the fused pmf or to the voter set.
    """
    c = _make_consensus(min_confidence=0.5)
    # p.a votes confidently for H; p.b and p.c are below the floor.
    list(c.handle(_vote("p.a", {"H": 0.9, "D": 0.05, "A": 0.05}, confidence=0.9)))
    list(c.handle(_vote("p.b", {"H": 0.1, "D": 0.45, "A": 0.45}, confidence=0.30)))
    out = c.flush_all()
    assert len(out) == 1
    final = PredictFinal.from_dict(out[0].payload)
    # Only p.a's vote survives → fused pmf must equal p.a's pmf.
    pmf = final.distribution["market_outcomes"]
    assert math.isclose(pmf["H"], 0.9, abs_tol=1e-9)
    assert final.contributing_models == ["p.a"]


def test_low_confidence_vote_alone_yields_consensus_no_votes():
    """If every vote is below the confidence floor, the window flush
    must emit ``proof.flag(kind=consensus_no_votes)`` — same path as a
    truly empty window."""
    from swarm.agents.payloads import PredictRequest as _PR
    c = _make_consensus(min_confidence=0.95)
    c.note_request(_PR(
        request_id="r-low", match_id="m-low", market="1x2", features={},
    ))
    list(c.handle(_vote(
        "p.a", {"H": 0.5, "D": 0.3, "A": 0.2},
        request_id="r-low", match_id="m-low", confidence=0.5,
    )))
    out = c.flush_all()
    assert len(out) == 1
    assert out[0].envelope.topic == PROOF_FLAG
    assert out[0].payload["kind"] == "consensus_no_votes"


def test_pending_overflow_evicts_oldest_and_emits_proof_flag():
    """ROADMAP §5.2: ``_pending`` is bounded by ``cfg.consensus_max_pending``;
    overflow evicts the oldest insertion and emits
    ``proof.flag(kind=consensus_overflow)``."""
    c = _make_consensus(max_pending=2)
    # Fill: r-1 (oldest), r-2.
    list(c.handle(_vote("p.a", {"H": 0.5, "D": 0.3, "A": 0.2}, request_id="r-1", match_id="m-1")))
    list(c.handle(_vote("p.a", {"H": 0.5, "D": 0.3, "A": 0.2}, request_id="r-2", match_id="m-2")))
    # Third distinct key triggers eviction of r-1.
    out = list(c.handle(
        _vote("p.a", {"H": 0.5, "D": 0.3, "A": 0.2}, request_id="r-3", match_id="m-3")
    ))
    flags = [m for m in out if m.envelope.topic == PROOF_FLAG]
    assert len(flags) == 1
    assert flags[0].payload["kind"] == "consensus_overflow"
    assert flags[0].payload["request_id"] == "r-1"
    assert flags[0].payload["max_pending"] == 2


# ── predict.request subscription (production wire-up) ───────────


def _request_msg(
    *,
    request_id: str = "r-empty",
    match_id: str = "m-empty",
    market: str = "1x2",
    league_id: str | None = "L1",
    profile_id: str | None = None,
    trace_id: str = "trace-Z",
):
    from swarm.agents.payloads import PredictRequest as _PR
    from swarm.agents.topics import PREDICT_REQUEST as _PREDICT_REQUEST

    return Message.new(
        _PREDICT_REQUEST,
        _PR(
            request_id=request_id,
            match_id=match_id,
            market=market,
            league_id=league_id,
            profile_id=profile_id,
            features={},
        ).as_dict(),
        producer="reactor.live_predictor",
        trace_id=trace_id,
    )


def test_handle_predict_request_notes_window_for_quorum_empty_path():
    """Production wire-up: consensus subscribes to predict.request so the
    §5.2 quorum-empty fallback fires even when zero votes ever arrive
    (every predictor crashes / DLQs). Without this subscription,
    ``note_request`` is unreachable from the bus."""
    c = _make_consensus()
    out_req = list(c.handle(_request_msg()))
    assert out_req == []  # request handling is silent
    # Window now expires with zero votes → consensus_no_votes flag.
    out = c.flush_all()
    assert len(out) == 1
    assert out[0].envelope.topic == PROOF_FLAG
    assert out[0].payload["kind"] == "consensus_no_votes"
    assert out[0].payload["request_id"] == "r-empty"


def test_predict_request_redelivery_after_finalization_is_a_noop():
    """At-least-once redelivery: a predict.request that re-arrives after
    finalization must not trigger a phantom consensus_no_votes (the
    ledger guard in _finalize is the safety net)."""
    c = _make_consensus()
    # Open the window via predict.request, then satisfy quorum.
    list(c.handle(_request_msg(request_id="r-1", match_id="m-1")))
    list(c.handle(_vote("p.a", {"H": 0.5, "D": 0.3, "A": 0.2})))
    list(c.handle(_vote("p.b", {"H": 0.5, "D": 0.3, "A": 0.2})))
    out = list(c.handle(_vote("p.c", {"H": 0.5, "D": 0.3, "A": 0.2})))
    assert len(out) == 1 and out[0].envelope.topic == PREDICT_FINAL

    # Replay the request — the bus may at-least-once redeliver it.
    list(c.handle(_request_msg(request_id="r-1", match_id="m-1")))
    # Flush should NOT emit a phantom consensus_no_votes.
    flush_out = c.flush_all()
    assert flush_out == [], (
        f"redelivered predict.request after finalize must not emit, got "
        f"{[m.envelope.topic for m in flush_out]}"
    )


def test_consensus_subscribes_to_both_request_and_vote_topics():
    """ROADMAP §3.4: every Phase 5 topic shows in `swarmctl topics`.
    Consensus's `subscribes` is the wire-authority — it must declare
    both predict.request and predict.vote so the runner / registry
    surfaces the right routing."""
    from swarm.agents.topics import PREDICT_REQUEST as _PREQ
    assert _PREQ in ConsensusAgent.subscribes
    assert PREDICT_VOTE in ConsensusAgent.subscribes


def test_malformed_predict_request_is_logged_and_dropped():
    """Hardening: a bad predict.request payload must not raise."""
    from swarm.agents.topics import PREDICT_REQUEST as _PREQ
    c = _make_consensus()
    bad = Message.new(_PREQ, {"not": "a request"}, producer="x", trace_id="t")
    out = list(c.handle(bad))
    assert out == []

