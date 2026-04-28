"""Phase 12 forward-test (kept in Phase 5 per ROADMAP §5.5 DoD).

Simulate a 50% predictor kill: half the must-status predictors
silently drop their votes. Consensus must still publish
``predict.final`` and **must** mark it ``degraded=true`` with a
non-empty ``degraded_reason``. The actual ``make chaos-kill-predictor``
target ships in Phase 12; here we exercise the in-process invariant
that gate depends on.
"""
from __future__ import annotations

import math

import pytest

from swarm.agents.consensus import ConsensusAgent
from swarm.agents.payloads import PredictFinal, PredictRequest
from swarm.agents.predictors import (
    DixonColesPredictor,
    EloPredictor,
    XgbFormPredictor,
    XgbXgPredictor,
)
from swarm.agents.reactor import InMemoryLedger
from swarm.agents.topics import PREDICT_FINAL, PREDICT_REQUEST
from swarm.sdk.types import Message


_ALL_PREDICTOR_CLASSES = (
    EloPredictor,
    DixonColesPredictor,
    XgbFormPredictor,
    XgbXgPredictor,
)


def _drive(predictor_classes, *, min_voters=3):
    predictors = [cls() for cls in predictor_classes]
    consensus = ConsensusAgent(
        # Consensus *expects* the full roster — that's what makes
        # the surviving 2/4 a "degraded" finalization.
        expected_predictors=tuple(c.predictor_id for c in (
            EloPredictor, DixonColesPredictor,
            XgbFormPredictor, XgbXgPredictor,
        )),
        ledger=InMemoryLedger(),
        clock_ms=lambda: 0.0,
        min_voters=min_voters,
    )
    req = PredictRequest(
        request_id="chaos-1",
        match_id="match:chaos",
        market="1x2",
        features={"home_advantage": 0.55},
    )
    msg = Message.new(PREDICT_REQUEST, req.as_dict(), producer="chaos-test")
    finals: list[Message] = []
    for p in predictors:
        for vote in p.handle(msg):
            for out in consensus.handle(vote):
                if out.envelope.topic == PREDICT_FINAL:
                    finals.append(out)
    # Sweep any in-flight (under-quorum) keys that the all-voted
    # short-circuit didn't already finalize.
    for out in consensus.flush_all():
        if out.envelope.topic == PREDICT_FINAL:
            finals.append(out)
    return finals


def test_50pct_predictor_kill_degrades_but_still_publishes():
    """Half the predictors silenced → consensus.v1 still emits a
    finalized prediction, marked degraded with a populated reason."""
    survivors = _ALL_PREDICTOR_CLASSES[:2]  # 2 of 4 — exactly the kill rate
    out = _drive(survivors, min_voters=3)  # need 3 to NOT be degraded
    assert len(out) == 1
    final_msg = out[0]
    assert final_msg.envelope.topic == PREDICT_FINAL
    final = PredictFinal.from_dict(final_msg.payload)
    assert final.degraded is True
    assert final.degraded_reason
    assert "2/4" in final.degraded_reason
    pmf = final.distribution["market_outcomes"]
    assert math.isclose(sum(pmf.values()), 1.0, abs_tol=1e-9)


def test_full_roster_is_not_degraded():
    """Sanity check: the full roster never trips the degraded flag."""
    out = _drive(_ALL_PREDICTOR_CLASSES, min_voters=3)
    assert len(out) == 1
    final = PredictFinal.from_dict(out[0].payload)
    assert final.degraded is False
    assert final.degraded_reason == ""
    assert sorted(final.contributing_models) == [
        "pred.dixon_coles.v1",
        "pred.elo.v1",
        "pred.xgb_form.v1",
        "pred.xgb_xg.v1",
    ]
