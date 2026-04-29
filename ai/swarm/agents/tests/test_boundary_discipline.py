"""Phase 6 (Wave A.3) — boundary-discipline tests.

Three rules this test set enforces:

1. **`match.outcome.v1` is storage-side only.** No predictor, no
   consensus agent, no proofreader / aggregator may publish it. The
   storage agent is the SOLE producer (mirrors the existing
   freshness.events back-emission ban). The drift agent (Phase 6.3)
   subscribes to it as its source of truth.

2. **`predict.final` is a CANDIDATE.** Per ROADMAP §736 it is never
   user-visible. The cache (`cache.v1`) must NOT subscribe to it;
   only the proofreader subscribes. User-visible publication uses
   `predict.approved.v1` (Wave A.1).

3. **`predict.approved.v1` is aggregator-only.** No predictor or
   consensus agent may emit it. Only the future
   ``proofreader_aggregator.v1`` (Phase 6.1) is allowed; the cache
   subscribes here.

These tests are cheap (import + introspect class attrs) and lock in
the topology decisions so a future refactor cannot quietly violate
them.
"""
from __future__ import annotations

import pytest

from swarm.agents.cache import CacheAgent
from swarm.agents.consensus import ConsensusAgent
from swarm.agents.drift import DriftAgent
from swarm.agents.predictors import dixon_coles, elo, xgb_form, xgb_xg
from swarm.agents.predictors.lgbm_market import LgbmMarketPredictor
from swarm.agents.proofreader.aggregator import ProofreaderAggregatorAgent
from swarm.agents.proofreader.replicas import (
    ConsistencyProofreader,
    PlausibilityProofreader,
    SanityProofreader,
)
from swarm.agents.storage import StorageAgent
from swarm.agents.topics import (
    MAINT_EVENT,
    MATCH_OUTCOME,
    PREDICT_APPROVED,
    PREDICT_FINAL,
    PROOFREADER_VERDICT,
)


# Predictor agent classes that exist today (Phase 5).
_PREDICTOR_CLASSES = (
    elo.EloPredictor,
    dixon_coles.DixonColesPredictor,
    xgb_form.XgbFormPredictor,
    xgb_xg.XgbXgPredictor,
    LgbmMarketPredictor,
)


# ── Rule 1: match.outcome.v1 is storage-only ────────────────────


def test_storage_publishes_match_outcome() -> None:
    """Sanity: the producer we expect is wired up."""
    assert MATCH_OUTCOME in StorageAgent.publishes


@pytest.mark.parametrize(
    "agent_cls", _PREDICTOR_CLASSES, ids=lambda c: c.__name__
)
def test_predictors_do_not_publish_match_outcome(agent_cls: type) -> None:
    publishes = tuple(getattr(agent_cls, "publishes", ()))
    assert MATCH_OUTCOME not in publishes, (
        f"{agent_cls.__name__} must not publish match.outcome.v1 "
        "— outcomes are storage-side data, not prediction-side. "
        "Allowing this would let a passed prediction corrupt the "
        "drift agent's reference baseline."
    )


def test_consensus_does_not_publish_match_outcome() -> None:
    publishes = tuple(getattr(ConsensusAgent, "publishes", ()))
    assert MATCH_OUTCOME not in publishes, (
        "consensus.v1 must not publish match.outcome.v1; "
        "boundary-discipline rule (Wave A.3)."
    )


# ── Rule 2: predict.final is a CANDIDATE; cache must not subscribe ──


def test_cache_does_not_subscribe_to_predict_final() -> None:
    """ROADMAP §736: predict.final is a CANDIDATE — never user-visible
    until the Phase 6 proofreader quorum approves it. Cache subscribing
    here would bypass the proofreader entirely.
    """
    subs = tuple(getattr(CacheAgent, "subscribes", ()))
    assert PREDICT_FINAL not in subs, (
        "cache.v1 must NOT subscribe to predict.final — that bypasses "
        "the proofreader. Subscribe to predict.approved.v1 instead."
    )


def test_cache_subscribes_to_predict_approved() -> None:
    subs = tuple(getattr(CacheAgent, "subscribes", ()))
    assert PREDICT_APPROVED in subs, (
        "cache.v1 must subscribe to predict.approved.v1 — that is the "
        "user-visible decision topic (Wave A.1)."
    )


# ── Rule 3: predict.approved.v1 is aggregator-only ──────────────


@pytest.mark.parametrize(
    "agent_cls", _PREDICTOR_CLASSES, ids=lambda c: c.__name__
)
def test_predictors_do_not_publish_predict_approved(agent_cls: type) -> None:
    publishes = tuple(getattr(agent_cls, "publishes", ()))
    assert PREDICT_APPROVED not in publishes, (
        f"{agent_cls.__name__} must not publish predict.approved.v1 "
        "— only the proofreader_aggregator (Phase 6.1) may emit there."
    )


def test_consensus_does_not_publish_predict_approved() -> None:
    publishes = tuple(getattr(ConsensusAgent, "publishes", ()))
    assert PREDICT_APPROVED not in publishes, (
        "consensus.v1 must not publish predict.approved.v1; "
        "consensus emits the CANDIDATE on predict.final, the "
        "aggregator emits the approval after quorum."
    )


def test_storage_does_not_publish_predict_approved() -> None:
    publishes = tuple(getattr(StorageAgent, "publishes", ()))
    assert PREDICT_APPROVED not in publishes


# ── Rule 4: maint.event.v1 is drift-agent-only (Phase 6.3) ──────


def test_drift_agent_publishes_maint_event() -> None:
    assert MAINT_EVENT in DriftAgent.publishes


@pytest.mark.parametrize(
    "agent_cls",
    (
        StorageAgent, CacheAgent, ConsensusAgent,
        ProofreaderAggregatorAgent,
        SanityProofreader, PlausibilityProofreader, ConsistencyProofreader,
        *_PREDICTOR_CLASSES,
    ),
    ids=lambda c: c.__name__,
)
def test_only_drift_agent_publishes_maint_event(agent_cls: type) -> None:
    publishes = tuple(getattr(agent_cls, "publishes", ()))
    assert MAINT_EVENT not in publishes, (
        f"{agent_cls.__name__} must not publish maint.event.v1 — only "
        "the drift agent (Phase 6.3) emits retrain_requests."
    )


# ── Rule 5: predict.proofreader_verdict.v1 is per-replica only ──


@pytest.mark.parametrize(
    "agent_cls",
    (
        StorageAgent, CacheAgent, ConsensusAgent,
        ProofreaderAggregatorAgent, DriftAgent,
        *_PREDICTOR_CLASSES,
    ),
    ids=lambda c: c.__name__,
)
def test_only_replicas_publish_proofreader_verdict(agent_cls: type) -> None:
    publishes = tuple(getattr(agent_cls, "publishes", ()))
    assert PROOFREADER_VERDICT not in publishes, (
        f"{agent_cls.__name__} must not publish "
        "predict.proofreader_verdict.v1 — only individual proofreader "
        "replicas (Phase 6.2) emit there. The aggregator is the SOLE "
        "consumer."
    )


def test_aggregator_subscribes_to_proofreader_verdict() -> None:
    subs = tuple(getattr(ProofreaderAggregatorAgent, "subscribes", ()))
    assert PROOFREADER_VERDICT in subs


def test_only_aggregator_subscribes_to_proofreader_verdict() -> None:
    """Per ROADMAP §6.1: the aggregator is the SOLE consumer of the
    per-replica verdict stream. Anyone else watching it would bypass
    the quorum gate."""
    for agent_cls in (
        StorageAgent, CacheAgent, ConsensusAgent, DriftAgent,
        SanityProofreader, PlausibilityProofreader, ConsistencyProofreader,
        *_PREDICTOR_CLASSES,
    ):
        subs = tuple(getattr(agent_cls, "subscribes", ()))
        assert PROOFREADER_VERDICT not in subs, (
            f"{agent_cls.__name__} must not subscribe to "
            "predict.proofreader_verdict.v1; only the aggregator may."
        )
