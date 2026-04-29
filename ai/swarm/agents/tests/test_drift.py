"""Tests for `ai/swarm/agents/drift.py` (Phase 6.3)."""
from __future__ import annotations

from typing import Any

import pytest

from swarm.agents.drift import DriftAgent, _brier_score
from swarm.agents.payloads import (
    MaintEvent,
    MatchOutcome,
    PredictApproved,
    PredictFinal,
)
from swarm.agents.topics import (
    MAINT_EVENT,
    MATCH_OUTCOME,
    PREDICT_APPROVED,
    SCRAPE_REQUEST,
)
from swarm.sdk.types import Message


# ── Fixtures ──────────────────────────────────────────────────


def _final(
    *,
    prediction_id: str = "pid-1",
    match_id: str = "match-abc",
    league_id: str | None = "tr_super_lig",
    distribution: dict[str, Any] | None = None,
    contributing: list[str] | None = None,
) -> PredictFinal:
    if distribution is None:
        distribution = {"market_outcomes": {"H": 0.5, "D": 0.3, "A": 0.2}}
    return PredictFinal(
        request_id="req-1",
        prediction_id=prediction_id,
        match_id=match_id,
        market="1x2",
        distribution=distribution,
        weights={"pred.elo.v1": 1.0},
        contributing_models=contributing or ["pred.elo.v1", "pred.poisson.v1"],
        calibration_version=1,
        swarm_confidence=0.65,
        produced_at="2026-04-28T12:00:02+00:00",
        league_id=league_id,
        profile_id=league_id,
    )


def _approved_msg(final: PredictFinal) -> Message:
    payload = PredictApproved(
        request_id=final.request_id,
        prediction_id=final.prediction_id,
        match_id=final.match_id,
        market=final.market,
        approved_at="2026-04-28T12:00:04+00:00",
        approved_by=["proof.sanity.v1", "proof.consistency.v1"],
        verdict_count=2,
        quorum=2,
        final=final.as_dict(),
        calibration_version=final.calibration_version,
    )
    return Message.new(PREDICT_APPROVED, payload.as_dict(), producer="agg")


def _outcome_msg(*, match_id: str, outcome_1x2: str = "A") -> Message:
    payload = MatchOutcome(
        match_id=match_id,
        stable_id=f"stable-{match_id}",
        source="mackolik",
        final_home=0,
        final_away=2 if outcome_1x2 == "A" else 0,
        outcome_1x2=outcome_1x2,
        settled_at="2026-04-28T22:00:00+00:00",
        league_id="tr_super_lig",
    )
    return Message.new(MATCH_OUTCOME, payload.as_dict(), producer="storage")


def _agent(*, window_size: int = 3, floor: float = 0.30) -> DriftAgent:
    return DriftAgent(
        clock_iso=lambda: "2026-04-28T22:01:00+00:00",
        window_size=window_size,
        accuracy_floor=floor,
    )


# ── Pure helper ───────────────────────────────────────────────


def test_brier_score_perfect_prediction_is_zero() -> None:
    assert _brier_score({"H": 1.0, "D": 0.0, "A": 0.0}, "H") == 0.0


def test_brier_score_uniform_is_two_thirds() -> None:
    """Uniform 1/3 each → Brier = 3·(1/3)² + 0² + ... wait recompute.

    p=(1/3,1/3,1/3), realized=H → y=(1,0,0).
    Brier = (1/3-1)² + (1/3)² + (1/3)² = 4/9 + 1/9 + 1/9 = 6/9 = 0.6667.
    """
    score = _brier_score({"H": 1 / 3, "D": 1 / 3, "A": 1 / 3}, "H")
    assert score == pytest.approx(0.6667, abs=0.001)


def test_brier_score_completely_wrong_is_two() -> None:
    """p=(1,0,0), realized=A → (1)² + 0² + (0-1)² = 2.0 (the max)."""
    assert _brier_score({"H": 1.0, "D": 0.0, "A": 0.0}, "A") == 2.0


# ── Contract / dispatch ───────────────────────────────────────


def test_drift_agent_subscribes_and_publishes_correctly() -> None:
    a = _agent()
    assert set(a.subscribes) == {PREDICT_APPROVED, MATCH_OUTCOME}
    assert set(a.publishes) == {MAINT_EVENT}
    assert a.name == "drift.v1"


def test_drift_rejects_invalid_window_size() -> None:
    with pytest.raises(ValueError, match="window_size"):
        DriftAgent(window_size=0)


def test_drift_ignores_unsubscribed_topic() -> None:
    a = _agent()
    out = list(a.handle(Message.new(SCRAPE_REQUEST, {}, producer="t")))
    assert out == []


def test_drift_drops_malformed_payloads() -> None:
    a = _agent()
    bad_a = Message.new(PREDICT_APPROVED, {"oops": True}, producer="t")
    bad_b = Message.new(MATCH_OUTCOME, {"oops": True}, producer="t")
    assert list(a.handle(bad_a)) == []
    assert list(a.handle(bad_b)) == []


# ── Window dynamics ───────────────────────────────────────────


def test_partial_window_does_not_trip() -> None:
    """Floor check fires only when the window is FULL — half-full mean is
    too noisy."""
    a = _agent(window_size=3, floor=0.30)
    # Even a horrible Brier (~2.0) should NOT trip a 1-sample window.
    list(a.handle(_approved_msg(_final(
        prediction_id="p1", match_id="m1",
        distribution={"market_outcomes": {"H": 1.0, "D": 0.0, "A": 0.0}},
    ))))
    out = list(a.handle(_outcome_msg(match_id="m1", outcome_1x2="A")))
    assert out == []
    assert a.window_size("tr_super_lig", "1x2") == 1


def test_full_window_breach_emits_one_retrain_per_contributor() -> None:
    """Three back-to-back terrible predictions on (tr_super_lig, 1x2)
    fill the window and trip the floor; we expect one MaintEvent per
    contributing model."""
    a = _agent(window_size=3, floor=0.30)
    contributors = ["pred.elo.v1", "pred.poisson.v1"]
    for i in range(3):
        list(a.handle(_approved_msg(_final(
            prediction_id=f"p{i}", match_id=f"m{i}",
            distribution={"market_outcomes": {"H": 1.0, "D": 0.0, "A": 0.0}},
            contributing=contributors,
        ))))
    out: list[Message] = []
    for i in range(3):
        out.extend(a.handle(_outcome_msg(match_id=f"m{i}", outcome_1x2="A")))
    # Trip happens on the 3rd outcome (window first becomes full).
    maint = [m for m in out if m.envelope.topic == MAINT_EVENT]
    assert len(maint) == len(contributors)
    targets = {MaintEvent.from_dict(m.payload).target for m in maint}
    assert targets == set(contributors)
    for m in maint:
        ev = MaintEvent.from_dict(m.payload)
        assert ev.kind == "retrain_request"
        assert ev.reason == "brier_floor"
        assert ev.metric == "brier"
        assert ev.metric_value == pytest.approx(2.0)
        assert ev.threshold == 0.30
        assert ev.sample_size == 3
        assert ev.league_id == "tr_super_lig"
        assert ev.market == "1x2"


def test_full_window_within_floor_does_not_trip() -> None:
    """Three near-perfect predictions → mean Brier ≈ 0; no event."""
    a = _agent(window_size=3, floor=0.30)
    out: list[Message] = []
    for i in range(3):
        list(a.handle(_approved_msg(_final(
            prediction_id=f"p{i}", match_id=f"m{i}",
            distribution={"market_outcomes": {"H": 0.05, "D": 0.05, "A": 0.9}},
        ))))
        out.extend(a.handle(_outcome_msg(match_id=f"m{i}", outcome_1x2="A")))
    assert all(m.envelope.topic != MAINT_EVENT for m in out)
    mean = a.mean_brier("tr_super_lig", "1x2")
    assert mean is not None and mean < 0.30


def test_breach_does_not_re_trip_until_recovered() -> None:
    """After tripping, additional bad outcomes do NOT spam the trainer
    until the window has rolled (mean dipped back below the floor)."""
    a = _agent(window_size=3, floor=0.30)
    contributors = ["pred.elo.v1"]
    # Fill window with three bad predictions → trips on outcome #3.
    for i in range(3):
        list(a.handle(_approved_msg(_final(
            prediction_id=f"p{i}", match_id=f"m{i}",
            distribution={"market_outcomes": {"H": 1.0, "D": 0.0, "A": 0.0}},
            contributing=contributors,
        ))))
    trips: list[Message] = []
    for i in range(3):
        trips.extend(a.handle(_outcome_msg(match_id=f"m{i}", outcome_1x2="A")))
    assert sum(1 for m in trips if m.envelope.topic == MAINT_EVENT) == 1

    # 4th & 5th equally bad predictions — should NOT emit a second trip.
    for i in range(3, 5):
        list(a.handle(_approved_msg(_final(
            prediction_id=f"p{i}", match_id=f"m{i}",
            distribution={"market_outcomes": {"H": 1.0, "D": 0.0, "A": 0.0}},
            contributing=contributors,
        ))))
    silent: list[Message] = []
    for i in range(3, 5):
        silent.extend(a.handle(_outcome_msg(match_id=f"m{i}", outcome_1x2="A")))
    assert all(m.envelope.topic != MAINT_EVENT for m in silent)


def test_redelivered_outcome_does_not_double_score() -> None:
    a = _agent(window_size=3, floor=0.30)
    list(a.handle(_approved_msg(_final(prediction_id="p1", match_id="m1"))))
    list(a.handle(_outcome_msg(match_id="m1", outcome_1x2="A")))
    list(a.handle(_outcome_msg(match_id="m1", outcome_1x2="A")))  # replay
    assert a.window_size("tr_super_lig", "1x2") == 1


def test_outcome_without_matching_prediction_is_silent() -> None:
    a = _agent()
    out = list(a.handle(_outcome_msg(match_id="never-predicted")))
    assert out == []
    assert a.window_size("tr_super_lig", "1x2") == 0


def test_buckets_are_isolated_per_league() -> None:
    """Drift in one league must not contaminate another's window."""
    a = _agent(window_size=2, floor=0.30)
    # tr breach
    for i in range(2):
        list(a.handle(_approved_msg(_final(
            prediction_id=f"tr-{i}", match_id=f"tr-m-{i}", league_id="tr_super_lig",
            distribution={"market_outcomes": {"H": 1.0, "D": 0.0, "A": 0.0}},
        ))))
    # en clean
    for i in range(2):
        list(a.handle(_approved_msg(_final(
            prediction_id=f"en-{i}", match_id=f"en-m-{i}", league_id="en_premier",
            distribution={"market_outcomes": {"H": 0.05, "D": 0.05, "A": 0.9}},
        ))))
    out: list[Message] = []
    for i in range(2):
        out.extend(a.handle(_outcome_msg(match_id=f"tr-m-{i}", outcome_1x2="A")))
    for i in range(2):
        out.extend(a.handle(_outcome_msg(match_id=f"en-m-{i}", outcome_1x2="A")))
    maint = [m for m in out if m.envelope.topic == MAINT_EVENT]
    # Exactly one trip — for tr_super_lig only.
    leagues_tripped = {MaintEvent.from_dict(m.payload).league_id for m in maint}
    assert leagues_tripped == {"tr_super_lig"}
