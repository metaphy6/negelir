"""Phase 6 bug-fix regression tests (pre-Phase-6 round-5 audit).

Three real correctness/leak issues fixed in this turn — each one
gets a dedicated test so a future refactor cannot quietly re-leak:

1. **Drift `_settled` LRU bound.** Without this, every settled
   ``(match_id, market)`` key sat in a `set` forever; a multi-season
   swarm leaked one entry per match.
2. **Drift `_pending` LRU bound.** Predictions for any market other
   than ``1x2`` (over/under, BTTS, AH) currently never get scored
   because the ``MatchOutcome`` payload only carries the 1X2 label
   in v1 — they sat in `_pending` forever.
3. **Drift `models_in_window` staleness.** When an entry rolled out
   of the rolling window via ``popleft``, its contributing models
   were *not* removed from the union — so on a long-running swarm
   the retrain-target list grew to include every model that had
   ever voted for the bucket, even ones long since retired.
4. **Aggregator overflow proof.flag.** When the aggregator's
   `_pending` saturated and it LRU-evicted a candidate, the
   ``proofreader_overflow`` flag was logged but never published on
   the bus — the operator had no observability into the fact.
"""
from __future__ import annotations

from typing import Any

import pytest

from swarm.agents.drift import DriftAgent
from swarm.agents.payloads import (
    MatchOutcome,
    PredictApproved,
    PredictFinal,
    ProofFlagKind,
    ProofreaderVerdict,
)
from swarm.agents.proofreader.aggregator import ProofreaderAggregatorAgent
from swarm.agents.topics import (
    MATCH_OUTCOME,
    PREDICT_APPROVED,
    PREDICT_FINAL,
    PROOF_FLAG,
    PROOFREADER_VERDICT,
)
from swarm.sdk.types import Message


# ── Helpers ───────────────────────────────────────────────────


def _final(
    *,
    prediction_id: str,
    match_id: str | None = None,
    league_id: str = "tr_super_lig",
    market: str = "1x2",
    contributing: list[str] | None = None,
    home_prob: float = 0.5,
) -> PredictFinal:
    return PredictFinal(
        request_id=f"req-{prediction_id}",
        prediction_id=prediction_id,
        match_id=match_id or f"m-{prediction_id}",
        market=market,
        distribution={"market_outcomes": {"H": home_prob, "D": 0.3, "A": 1 - home_prob - 0.3}},
        weights={"pred.elo.v1": 1.0},
        contributing_models=contributing or ["pred.elo.v1"],
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


def _outcome_msg(match_id: str, outcome: str = "A") -> Message:
    payload = MatchOutcome(
        match_id=match_id,
        stable_id=f"stable-{match_id}",
        source="mackolik",
        final_home=0,
        final_away=2 if outcome == "A" else 0,
        outcome_1x2=outcome,
        settled_at="2026-04-28T22:00:00+00:00",
        league_id="tr_super_lig",
    )
    return Message.new(MATCH_OUTCOME, payload.as_dict(), producer="storage")


# ── Bug 1: _settled LRU bound ─────────────────────────────────


def test_drift_settled_set_is_bounded() -> None:
    """Settling more than `max_settled` distinct matches must not
    grow `_settled` beyond the bound (LRU evicts the oldest)."""
    agent = DriftAgent(window_size=3, accuracy_floor=0.30, max_settled=5, max_pending=1000)
    for i in range(20):
        mid = f"match-{i:04d}"
        list(agent.handle(_approved_msg(_final(prediction_id=f"p{i}", match_id=mid))))
        list(agent.handle(_outcome_msg(mid, "H")))
    # Internal invariant: bounded.
    assert len(agent._settled) == 5, f"_settled grew past bound: {len(agent._settled)}"


# ── Bug 2: _pending LRU bound ─────────────────────────────────


def test_drift_pending_lru_evicts_when_full() -> None:
    """Predictions for non-1X2 markets sit in `_pending` until Phase 9
    adds their realized labels. The map MUST be bounded so a busy
    swarm doesn't OOM on long-tail markets."""
    agent = DriftAgent(window_size=3, accuracy_floor=0.30, max_pending=4)
    for i in range(10):
        list(agent.handle(_approved_msg(
            _final(prediction_id=f"p{i}", match_id=f"m{i}", market="ou_2_5")
        )))
    assert len(agent._pending) == 4, (
        f"_pending should be capped at 4; got {len(agent._pending)}"
    )
    # The most recent insertions survive (LRU evicts oldest).
    keys = list(agent._pending.keys())
    assert keys[-1] == ("m9", "ou_2_5")
    assert keys[0] == ("m6", "ou_2_5")


# ── Bug 3: models_in_window staleness ─────────────────────────


def test_drift_models_in_window_drops_evicted_models() -> None:
    """When the rolling window evicts an old entry, models that
    *only* contributed to that entry must be removed from
    `models_in_window`. Otherwise a long-running swarm's retrain
    target list grows to include every model that ever voted."""
    agent = DriftAgent(window_size=2, accuracy_floor=0.30, max_pending=100, max_settled=100)
    # First 2 predictions: only model_A contributes.
    for i in range(2):
        mid = f"a{i}"
        list(agent.handle(_approved_msg(
            _final(prediction_id=f"pa{i}", match_id=mid, contributing=["model_A"])
        )))
        list(agent.handle(_outcome_msg(mid, "H")))
    # After 2 settlements, window is full and contains only model_A.
    bucket = ("tr_super_lig", "1x2")
    assert agent._windows[bucket].models_in_window == {"model_A"}
    # Now 2 more predictions with only model_B → window now contains
    # only model_B (the model_A entries rolled out).
    for i in range(2):
        mid = f"b{i}"
        list(agent.handle(_approved_msg(
            _final(prediction_id=f"pb{i}", match_id=mid, contributing=["model_B"])
        )))
        list(agent.handle(_outcome_msg(mid, "H")))
    assert agent._windows[bucket].models_in_window == {"model_B"}, (
        f"Expected only model_B in window, got "
        f"{agent._windows[bucket].models_in_window} — model_A "
        "leaked past its window"
    )


def test_drift_retrain_request_targets_only_in_window_models() -> None:
    """End-to-end: only models currently in the rolling window are
    targeted by retrain_request emission. Without the popleft fix,
    `model_A` would also be retrained even though its contribution
    has already rolled out of the window."""
    agent = DriftAgent(window_size=2, accuracy_floor=0.30, max_pending=100, max_settled=100)
    # 2 correct predictions by model_A (no trip; Brier=0).
    for i in range(2):
        mid = f"a{i}"
        list(agent.handle(_approved_msg(
            _final(prediction_id=f"pa{i}", match_id=mid,
                   contributing=["model_A"], home_prob=0.95)
        )))
        list(agent.handle(_outcome_msg(mid, "H")))
    # 2 correct predictions by model_C — flushes model_A entries out
    # of the window without tripping.
    for i in range(2):
        mid = f"c{i}"
        list(agent.handle(_approved_msg(
            _final(prediction_id=f"pc{i}", match_id=mid,
                   contributing=["model_C"], home_prob=0.95)
        )))
        list(agent.handle(_outcome_msg(mid, "H")))
    # By here, model_A MUST be gone from `models_in_window` (the bug
    # we're fixing). Now 2 wrong model_B predictions trip the bucket.
    out: list[Message] = []
    for i in range(2):
        mid = f"b{i}"
        list(agent.handle(_approved_msg(
            _final(prediction_id=f"pb{i}", match_id=mid,
                   contributing=["model_B"], home_prob=0.95)
        )))
        out.extend(agent.handle(_outcome_msg(mid, "A")))
    targets = {m.payload["target"] for m in out}
    assert "model_A" not in targets, (
        f"retrain targeted model_A even though its contribution had "
        f"already rolled out of the window; targets={sorted(targets)}"
    )
    # model_B must be targeted (it's currently in the window).
    assert "model_B" in targets, f"missing model_B in targets={sorted(targets)}"


# ── Bug 4: Aggregator overflow proof.flag ─────────────────────


def _verdict_msg(*, prediction_id: str, match_id: str, proofreader_id: str,
                 verdict: str = "accept") -> Message:
    payload = ProofreaderVerdict(
        request_id=f"req-{prediction_id}",
        prediction_id=prediction_id,
        match_id=match_id,
        market="1x2",
        proofreader_id=proofreader_id,
        verdict=verdict,
        score=1.0,
        checked_at="2026-04-28T12:00:03+00:00",
        flags=[],
        checks_run=["x"],
        rationale="",
        calibration_version=1,
    )
    return Message.new(PROOFREADER_VERDICT, payload.as_dict(), producer=proofreader_id)


def _final_msg(final: PredictFinal) -> Message:
    return Message.new(PREDICT_FINAL, final.as_dict(), producer="consensus.v1")


def test_aggregator_overflow_emits_proof_flag() -> None:
    """When the aggregator's `_pending` LRU-evicts a candidate to
    accept a new one, it MUST publish a `proofreader_overflow`
    proof.flag so operators can see the eviction. Previously the
    eviction was logged but silent on the bus."""
    agg = ProofreaderAggregatorAgent(max_pending=2, quorum=2)
    # Push 2 candidates — both pending, no quorum yet.
    list(agg.handle(_final_msg(_final(prediction_id="p1"))))
    list(agg.handle(_final_msg(_final(prediction_id="p2"))))
    # The 3rd candidate evicts p1; overflow proof.flag must be emitted.
    out = list(agg.handle(_final_msg(_final(prediction_id="p3"))))
    overflow_flags = [
        m for m in out
        if m.envelope.topic == PROOF_FLAG
        and m.payload.get("kind") == ProofFlagKind.PROOFREADER_OVERFLOW
    ]
    assert len(overflow_flags) == 1, (
        f"expected exactly one proofreader_overflow flag; got {out}"
    )
    flag = overflow_flags[0].payload
    assert flag["prediction_id"] == "p1"
    assert flag["agent"] == "proofreader_aggregator.v1"
    assert flag["final_present"] is True
