"""Phase 5 — predictor agent unit tests.

Cover the must-status predictors per ROADMAP §5.1:

  * deterministic outputs (idempotency on identical input)
  * 4-market coverage (1x2, ah, ou_2_5, btts)
  * pmf integrity (sum to 1.0 ± 1e-3)
  * vote envelope passthrough (trace_id, request_id round-trip)
  * unsupported-market silent drop (PredictorAgent.handle invariant)
"""
from __future__ import annotations

import math

import pytest

from swarm.agents.payloads import PredictRequest, PredictVote
from swarm.agents.predictors import (
    DixonColesPredictor,
    EloPredictor,
    LgbmMarketPredictor,
    XgbFormPredictor,
    XgbXgPredictor,
)
from swarm.agents.topics import PREDICT_REQUEST, PREDICT_VOTE
from swarm.sdk.types import Message


_BASE_FEATURES = {
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


_PREDICTOR_CLASSES = (
    EloPredictor,
    DixonColesPredictor,
    XgbFormPredictor,
    XgbXgPredictor,
)


def _request(market: str, *, request_id: str = "req-1", match_id: str = "match-1") -> Message:
    return Message.new(
        PREDICT_REQUEST,
        PredictRequest(
            request_id=request_id,
            match_id=match_id,
            market=market,
            features=_BASE_FEATURES,
        ).as_dict(),
        producer="test",
        trace_id="trace-X",
    )


@pytest.mark.parametrize("predictor_cls", _PREDICTOR_CLASSES)
@pytest.mark.parametrize("market", ["1x2", "ah", "ou_2_5", "btts"])
def test_predictor_emits_valid_pmf_for_every_market(predictor_cls, market):
    agent = predictor_cls()
    out = list(agent.handle(_request(market)))
    assert len(out) == 1, f"{agent.predictor_id}: expected one vote, got {len(out)}"
    vote_msg = out[0]
    assert vote_msg.envelope.topic == PREDICT_VOTE
    assert vote_msg.envelope.trace_id == "trace-X"
    vote = PredictVote.from_dict(vote_msg.payload)
    assert vote.market == market
    assert vote.request_id == "req-1"
    assert vote.match_id == "match-1"
    assert vote.predictor_id == agent.predictor_id
    pmf = vote.distribution["market_outcomes"]
    assert pmf, "market_outcomes must not be empty"
    s = sum(pmf.values())
    assert math.isclose(s, 1.0, abs_tol=1e-3), f"pmf sum={s} ∉ [0.999,1.001]"
    for k, v in pmf.items():
        assert 0.0 <= v <= 1.0, f"out-of-range probability {k}={v}"


@pytest.mark.parametrize("predictor_cls", _PREDICTOR_CLASSES)
def test_predictor_is_deterministic(predictor_cls):
    agent = predictor_cls()
    a = list(agent.handle(_request("1x2")))[0]
    b = list(agent.handle(_request("1x2")))[0]
    assert a.payload["distribution"] == b.payload["distribution"]
    assert a.payload["confidence"] == b.payload["confidence"]


@pytest.mark.parametrize("predictor_cls", _PREDICTOR_CLASSES)
def test_predictor_drops_unsupported_market_silently(predictor_cls):
    """Spec §5.2: unsupported markets MUST be filtered, not crash."""
    agent = predictor_cls()
    msg = Message.new(
        PREDICT_REQUEST,
        {
            "request_id": "r",
            "match_id": "m",
            "market": "1x2",  # placate dataclass validation
            "features": {},
        },
    )
    # Patch the message payload bypassing PredictRequest validation.
    msg.payload["market"] = "exotic_double_chance"
    out = list(agent.handle(msg))
    assert out == []


def test_lgbm_market_no_vote_when_no_odds_features():
    """Opt-in predictor: produces no vote when odds are absent."""
    agent = LgbmMarketPredictor()
    out = list(agent.handle(_request("1x2")))  # no odds_* features
    assert out == []


def test_lgbm_market_devigs_three_way_odds():
    agent = LgbmMarketPredictor()
    msg = Message.new(
        PREDICT_REQUEST,
        PredictRequest(
            request_id="r",
            match_id="m",
            market="1x2",
            features={
                "odds_home": 2.0,
                "odds_draw": 3.5,
                "odds_away": 4.0,
            },
        ).as_dict(),
    )
    out = list(agent.handle(msg))
    assert len(out) == 1
    pmf = out[0].payload["distribution"]["market_outcomes"]
    assert math.isclose(sum(pmf.values()), 1.0, abs_tol=1e-9)
    # Home should be the strongest after de-vig (highest implied prob).
    assert pmf["H"] > pmf["D"] > pmf["A"]


def test_dixon_coles_emits_score_grid():
    """Phase 5.2 cross-check requirement: DC + xG produce grids."""
    agent = DixonColesPredictor()
    out = list(agent.handle(_request("1x2")))
    grid = out[0].payload["distribution"]["score_grid"]
    assert grid is not None
    assert len(grid) >= 4 and len(grid[0]) >= 4
    s = sum(c for row in grid for c in row)
    assert math.isclose(s, 1.0, abs_tol=1e-3)


def test_xgb_xg_emits_score_grid():
    agent = XgbXgPredictor()
    out = list(agent.handle(_request("1x2")))
    grid = out[0].payload["distribution"]["score_grid"]
    assert grid is not None
    s = sum(c for row in grid for c in row)
    assert math.isclose(s, 1.0, abs_tol=1e-3)


def test_xgb_form_no_score_grid():
    """xgb_form is logits-over-features only — no Poisson grid."""
    agent = XgbFormPredictor()
    out = list(agent.handle(_request("1x2")))
    assert out[0].payload["distribution"]["score_grid"] is None
