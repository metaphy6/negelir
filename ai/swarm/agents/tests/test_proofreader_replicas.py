"""Tests for `ai/swarm/agents/proofreader/replicas.py` (§6.2)."""
from __future__ import annotations

from typing import Any

from swarm.agents.payloads import PredictFinal, ProofreaderVerdict
from swarm.agents.proofreader.replicas import (
    ConsistencyProofreader,
    PlausibilityProofreader,
    SanityProofreader,
)
from swarm.agents.topics import (
    PREDICT_FINAL,
    PROOFREADER_VERDICT,
    SCRAPE_REQUEST,
)
from swarm.sdk.types import Message


def _final(distribution: dict[str, Any]) -> PredictFinal:
    return PredictFinal(
        request_id="req-1",
        prediction_id="pid-1",
        match_id="match-abc",
        market="1x2",
        distribution=distribution,
        weights={"pred.elo.v1": 1.0},
        contributing_models=["pred.elo.v1"],
        calibration_version=1,
        swarm_confidence=0.65,
        produced_at="2026-04-28T12:00:02+00:00",
        league_id="tr_super_lig",
        profile_id="tr_super_lig",
    )


def _msg(d: dict[str, Any]) -> Message:
    return Message.new(PREDICT_FINAL, _final(d).as_dict(), producer="consensus")


# ── Contract / dispatch ───────────────────────────────────────


def test_replicas_have_distinct_names_and_correct_topics() -> None:
    for cls in (SanityProofreader, PlausibilityProofreader, ConsistencyProofreader):
        a = cls()
        assert a.subscribes == (PREDICT_FINAL,)
        assert a.publishes == (PROOFREADER_VERDICT,)
        assert a.name.startswith("proofreader.")
    names = {
        SanityProofreader().name,
        PlausibilityProofreader().name,
        ConsistencyProofreader().name,
    }
    assert len(names) == 3


def test_replica_ignores_unsubscribed_topic() -> None:
    a = SanityProofreader()
    out = list(a.handle(Message.new(SCRAPE_REQUEST, {}, producer="t")))
    assert out == []


def test_replica_drops_malformed_predict_final() -> None:
    a = SanityProofreader()
    out = list(a.handle(Message.new(PREDICT_FINAL, {"oops": True}, producer="t")))
    assert out == []


# ── Sanity replica ────────────────────────────────────────────


def test_sanity_replica_accepts_well_formed() -> None:
    a = SanityProofreader(eps=0.01)
    out = list(a.handle(_msg({"market_outcomes": {"H": 0.5, "D": 0.25, "A": 0.25}})))
    assert len(out) == 1
    v = ProofreaderVerdict.from_dict(out[0].payload)
    assert v.proofreader_id == "proofreader.sanity.v1"
    assert v.verdict == "accept"
    assert v.flags == []
    assert v.checks_run == ["sanity.probs_well_formed"]
    assert v.rationale == ""
    assert v.calibration_version == 1


def test_sanity_replica_rejects_bad_sum() -> None:
    a = SanityProofreader(eps=0.01)
    out = list(a.handle(_msg({"market_outcomes": {"H": 0.5, "D": 0.3, "A": 0.3}})))
    v = ProofreaderVerdict.from_dict(out[0].payload)
    assert v.verdict == "reject"
    # Structured: flags carries the rule_id (subset of checks_run).
    assert v.flags == ["sanity.probs_well_formed"]
    # Human: rationale carries the detail.
    assert "differs from 1.0" in v.rationale


# ── Plausibility replica ──────────────────────────────────────


def test_plausibility_replica_warns_on_dominant_outcome() -> None:
    a = PlausibilityProofreader(max_outcome_prob=0.85)
    out = list(a.handle(_msg({"market_outcomes": {"H": 0.92, "D": 0.05, "A": 0.03}})))
    v = ProofreaderVerdict.from_dict(out[0].payload)
    assert v.verdict == "warn"
    assert v.score < 1.0
    assert v.flags == ["plausibility.max_outcome_prob"]
    assert "exceeds cap" in v.rationale


def test_plausibility_replica_accepts_balanced() -> None:
    a = PlausibilityProofreader(max_outcome_prob=0.85)
    out = list(a.handle(_msg({"market_outcomes": {"H": 0.5, "D": 0.3, "A": 0.2}})))
    v = ProofreaderVerdict.from_dict(out[0].payload)
    assert v.verdict == "accept"


# ── Consistency replica ───────────────────────────────────────


def test_consistency_replica_accepts_when_no_grid() -> None:
    a = ConsistencyProofreader(tol=0.05)
    out = list(a.handle(_msg({"market_outcomes": {"H": 0.5, "D": 0.3, "A": 0.2}})))
    v = ProofreaderVerdict.from_dict(out[0].payload)
    assert v.verdict == "accept"


def test_consistency_replica_rejects_diverging_marginals() -> None:
    a = ConsistencyProofreader(tol=0.05)
    out = list(a.handle(_msg({
        "market_outcomes": {"H": 0.7, "D": 0.2, "A": 0.1},
        "score_grid": [
            {"home": 1, "away": 0, "prob": 0.3},
            {"home": 0, "away": 0, "prob": 0.5},
            {"home": 0, "away": 1, "prob": 0.2},
        ],
    })))
    v = ProofreaderVerdict.from_dict(out[0].payload)
    assert v.verdict == "reject"
    assert v.flags == ["consistency.score_grid_marginals"]


# ── Bus-loop integration: replicas → aggregator → predict.approved ──


def test_three_replicas_produce_quorum_for_aggregator() -> None:
    """End-to-end without a real bus: feed `predict.final` into all
    three replicas, collect their verdicts, feed them + the candidate
    into the aggregator. Default config (replicas=3, quorum=2) should
    produce one `predict.approved.v1` for a clean prediction."""
    from swarm.agents.proofreader.aggregator import ProofreaderAggregatorAgent
    from swarm.agents.reactor import InMemoryLedger
    from swarm.agents.topics import PREDICT_APPROVED

    final_msg = _msg({"market_outcomes": {"H": 0.5, "D": 0.3, "A": 0.2}})
    replicas = [
        SanityProofreader(),
        PlausibilityProofreader(),
        ConsistencyProofreader(),
    ]
    verdict_msgs: list[Message] = []
    for r in replicas:
        verdict_msgs.extend(r.handle(final_msg))
    assert len(verdict_msgs) == 3
    # All three accept on a clean distribution.
    assert all(
        ProofreaderVerdict.from_dict(m.payload).verdict == "accept"
        for m in verdict_msgs
    )

    agg = ProofreaderAggregatorAgent(
        ledger=InMemoryLedger(), quorum=2, window_ms=200,
    )
    out: list[Message] = []
    out.extend(agg.handle(final_msg))
    for vm in verdict_msgs:
        out.extend(agg.handle(vm))

    approvals = [m for m in out if m.envelope.topic == PREDICT_APPROVED]
    assert len(approvals) == 1
