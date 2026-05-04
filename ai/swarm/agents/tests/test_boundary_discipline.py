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
from swarm.agents.sec import SecInputAgent, SecRateAgent, SecScrapeAgent
from swarm.agents.storage import StorageAgent
from swarm.agents.topics import (
    MAINT_EVENT,
    MATCH_OUTCOME,
    PREDICT_APPROVED,
    PREDICT_FINAL,
    PROOF_FLAG,
    PROOFREADER_VERDICT,
    QA_REQUEST,
    QA_REQUEST_V1,
    SEC_ALERT,
    SEC_DENYLIST,
    SEC_QUARANTINE,
)
from swarm.sdk.wire_contracts import MAINT_EVENT_V1_ALLOWED_PRODUCERS


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
        SecInputAgent, SecScrapeAgent, SecRateAgent,
        *_PREDICTOR_CLASSES,
    ),
    ids=lambda c: c.__name__,
)
def test_only_drift_agent_publishes_maint_event(agent_cls: type) -> None:
    """`maint.event.v1` is the operator/control-plane channel.
    Only producers in :data:`MAINT_EVENT_V1_ALLOWED_PRODUCERS` may
    publish; everyone else may consume (sec.scrape.v1 + sec.rate.v1
    consume `baseline_reset` / `denylist_clear`).

    The allow-list lives in `swarm/sdk/wire_contracts.py` so the
    Phase 17 patcher and the operator console (the only two
    legitimate producers today) cannot drift from this guard.
    """
    publishes = tuple(getattr(agent_cls, "publishes", ()))
    name = getattr(agent_cls, "name", agent_cls.__name__)
    if MAINT_EVENT in publishes:
        assert name in MAINT_EVENT_V1_ALLOWED_PRODUCERS, (
            f"{agent_cls.__name__} ({name!r}) publishes maint.event.v1 "
            f"but is not in MAINT_EVENT_V1_ALLOWED_PRODUCERS="
            f"{sorted(MAINT_EVENT_V1_ALLOWED_PRODUCERS)}. Add it to "
            "the wire-contracts allow-list with a tracker row "
            "explaining why."
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


# ── Rule 6 (Phase 7 §7.6): defense-agent boundaries ─────────────


# All non-sec agents that exist today. Used to assert "nobody else
# touches the sec.* topology".
_NON_SEC_AGENTS = (
    StorageAgent, CacheAgent, ConsensusAgent,
    ProofreaderAggregatorAgent, DriftAgent,
    SanityProofreader, PlausibilityProofreader, ConsistencyProofreader,
    *_PREDICTOR_CLASSES,
)


def test_sec_input_publishes_qa_request_v1_and_sec_topics() -> None:
    pub = tuple(SecInputAgent.publishes)
    assert QA_REQUEST_V1 in pub
    assert SEC_QUARANTINE in pub
    assert SEC_ALERT in pub


def test_sec_input_does_not_publish_proof_flag() -> None:
    """7.6: defense agents do NOT cross into the predictor-side
    proof.flag stream. The narrow exception is sec.scrape.v1
    publishing parse-failure flags so the Phase 17 patcher can
    pick up DOM-shape drift."""
    assert PROOF_FLAG not in tuple(SecInputAgent.publishes)


def test_sec_rate_does_not_publish_proof_flag() -> None:
    assert PROOF_FLAG not in tuple(SecRateAgent.publishes)


def test_sec_rate_is_sole_producer_of_denylist() -> None:
    """7.3 SOLE-writer contract."""
    assert SEC_DENYLIST in tuple(SecRateAgent.publishes)
    for cls in (*_NON_SEC_AGENTS, SecInputAgent, SecScrapeAgent):
        assert SEC_DENYLIST not in tuple(getattr(cls, "publishes", ())), (
            f"{cls.__name__} must not publish sec.denylist.v1 - "
            "only sec.rate.v1 may (single-writer denylist)."
        )


def test_qa_request_v1_producers_bounded() -> None:
    """7.5: qa.request.v1 has at most two producers (the gateway
    pass path - not an in-process agent - and sec.input.v1's
    sanitized path). Inside the swarm, only sec.input.v1 may emit."""
    for cls in _NON_SEC_AGENTS + (SecScrapeAgent, SecRateAgent):
        assert QA_REQUEST_V1 not in tuple(getattr(cls, "publishes", ())), (
            f"{cls.__name__} must not publish qa.request.v1 - only "
            "sec.input.v1 (or the Go gateway pass path) may."
        )


def test_qa_request_consumer_is_only_sec_input() -> None:
    """7.5: qa.request is the gateway escalation channel; only
    sec.input.v1 consumes it."""
    for cls in _NON_SEC_AGENTS + (SecScrapeAgent, SecRateAgent):
        assert QA_REQUEST not in tuple(getattr(cls, "subscribes", ())), (
            f"{cls.__name__} must not subscribe to qa.request - "
            "only sec.input.v1 (the escalation tier) may."
        )


def test_sec_quarantine_is_sec_only_publish() -> None:
    """7.5: sec.quarantine.v1 is published by sec.input.v1 only
    today (sec.scrape.v1 may add evidence in a future revision; the
    contract permits it). The predictor side never publishes."""
    for cls in _NON_SEC_AGENTS + (SecRateAgent,):
        assert SEC_QUARANTINE not in tuple(getattr(cls, "publishes", ())), (
            f"{cls.__name__} must not publish sec.quarantine.v1."
        )


def test_sec_scrape_does_not_consume_proof_flag() -> None:
    """7.6: scrape detector does NOT loop on its own proof.flag
    output - that is the patcher lane (Phase 17)."""
    assert PROOF_FLAG not in tuple(SecScrapeAgent.subscribes)


def test_sec_rate_consumes_sec_alert_for_burst() -> None:
    """7.3: rate agent burst counter is fed by sec.alert.v1."""
    assert SEC_ALERT in tuple(SecRateAgent.subscribes)


def test_sec_agents_consume_maint_event_for_overrides() -> None:
    """7.2 (baseline_reset) + 7.3 (denylist_clear)."""
    assert MAINT_EVENT in tuple(SecScrapeAgent.subscribes)
    assert MAINT_EVENT in tuple(SecRateAgent.subscribes)


def test_sec_input_does_not_consume_maint_event() -> None:
    """sec.input.v1 has no operator override surface in v1; reload
    of classifier patterns happens via mtime watch, not a maint
    event."""
    assert MAINT_EVENT not in tuple(SecInputAgent.subscribes)

