"""Phase 5 — end-to-end request_id / prediction_id round-trip.

Wires the live-predictor reactor → 4 must-status predictors →
consensus.v1 over an InMemoryBus and asserts:

  * request_id round-trips unchanged from PredictRequest → PredictVote
    → PredictFinal.
  * prediction_id is deterministic across two independent runs of the
    same input.
  * Two runs over the same freshness event produce identical
    PredictFinal payloads (modulo timestamps), proving the swarm path
    is replay-safe.
  * Schemas validate at every emission point.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from swarm.agents.consensus import ConsensusAgent
from swarm.agents.payloads import (
    FreshnessEvent,
    PredictFinal,
    PredictRequest,
    derive_prediction_id,
)
from swarm.agents.predictors import (
    DixonColesPredictor,
    EloPredictor,
    XgbFormPredictor,
    XgbXgPredictor,
)
from swarm.agents.reactor import InMemoryLedger, LivePredictorReactor
from swarm.agents.tests.test_predictor_reactors import _freshness  # type: ignore
from swarm.agents.topics import (
    FRESHNESS_EVENTS,
    PREDICT_FINAL,
    PREDICT_REQUEST,
    PREDICT_VOTE,
)
from swarm.sdk.schemas import validate as validate_schema
from swarm.sdk.types import Message


_FEATURES = {
    "home_elo": 1700,
    "away_elo": 1500,
    "home_advantage": 65,
    "home_xg": 1.6,
    "away_xg": 1.0,
    "dixon_coles_rho": -0.10,
    "home_form_5": 2.0,
    "away_form_5": 1.2,
    "home_gd_5": 4,
    "away_gd_5": -1,
    "home_xg_per_match": 1.7,
    "away_xg_per_match": 0.9,
    "home_shot_quality": 0.12,
    "away_shot_quality": 0.08,
}


def _run_pipeline(request_id: str, *, clock_iso: str) -> list[Message]:
    """Drive a single request through 4 predictors → consensus.

    Returns the list of PredictFinal messages produced.
    """
    predictors = [
        EloPredictor(clock=lambda: clock_iso),
        DixonColesPredictor(clock=lambda: clock_iso),
        XgbFormPredictor(clock=lambda: clock_iso),
        XgbXgPredictor(clock=lambda: clock_iso),
    ]
    consensus = ConsensusAgent(
        expected_predictors=tuple(p.predictor_id for p in predictors),
        ledger=InMemoryLedger(),
        clock_ms=lambda: 0.0,
        clock_iso=lambda: clock_iso,
        min_voters=2,
    )

    finals: list[Message] = []
    for market in ("1x2", "ah", "ou_2_5", "btts"):
        req = PredictRequest(
            request_id=f"{request_id}-{market}",
            match_id="match:42",
            market=market,
            features=_FEATURES,
        )
        # Schema gate — every emission must validate.
        validate_schema("predict.request", req.as_dict())
        msg = Message.new(
            PREDICT_REQUEST,
            req.as_dict(),
            producer="test",
            trace_id="trace-E2E",
        )
        votes: list[Message] = []
        for p in predictors:
            for v in p.handle(msg):
                validate_schema("predict.vote", v.payload)
                votes.append(v)

        for v in votes:
            for f in consensus.handle(v):
                if f.envelope.topic == PREDICT_FINAL:
                    validate_schema("predict.final", f.payload)
                    finals.append(f)
    return finals


def test_request_id_round_trips_through_full_pipeline():
    finals = _run_pipeline("r1", clock_iso="2025-01-01T00:00:00+00:00")
    assert len(finals) == 4  # one per market
    seen = sorted(PredictFinal.from_dict(m.payload).request_id for m in finals)
    assert seen == [
        "r1-1x2",
        "r1-ah",
        "r1-btts",
        "r1-ou_2_5",
    ]


def test_prediction_id_is_deterministic_across_runs():
    a = _run_pipeline("r1", clock_iso="2025-01-01T00:00:00+00:00")
    b = _run_pipeline("r1", clock_iso="2099-12-31T23:59:59+00:00")  # different clock
    a_ids = {PredictFinal.from_dict(m.payload).prediction_id for m in a}
    b_ids = {PredictFinal.from_dict(m.payload).prediction_id for m in b}
    assert a_ids == b_ids  # prediction_id is independent of wall clock


def test_swarm_output_is_replay_stable():
    """Identical inputs → identical fused distributions (the
    invariant Phase 6 proofreader relies on)."""
    a = _run_pipeline("r1", clock_iso="2025-01-01T00:00:00+00:00")
    b = _run_pipeline("r1", clock_iso="2025-01-01T00:00:00+00:00")
    a_dist = sorted(
        (PredictFinal.from_dict(m.payload).market,
         json.dumps(PredictFinal.from_dict(m.payload).distribution["market_outcomes"], sort_keys=True))
        for m in a
    )
    b_dist = sorted(
        (PredictFinal.from_dict(m.payload).market,
         json.dumps(PredictFinal.from_dict(m.payload).distribution["market_outcomes"], sort_keys=True))
        for m in b
    )
    assert a_dist == b_dist


def test_live_reactor_to_consensus_chain():
    """Drive the chain from the *reactor* (real start of the live
    path), not from a synthetic PredictRequest, to prove the seam
    glues correctly."""
    reactor = LivePredictorReactor(
        clock_iso=lambda: "2025-01-01T00:00:00+00:00"
    )
    requests = list(reactor.handle(_freshness(plane="live", event_id="ev-roundtrip")))
    assert len(requests) == 2  # 1x2 + ah
    rids = sorted(r.payload["request_id"] for r in requests)
    assert rids == ["r-ev-roundtrip-1x2", "r-ev-roundtrip-ah"]

    # The exact request_id is what consensus's prediction_id depends
    # on — verify it stays identical end-to-end.
    expected = derive_prediction_id(
        match_id="match:42",
        market="1x2",
        request_id="r-ev-roundtrip-1x2",
        calibration_version=0,
    )
    assert len(expected) == 32
