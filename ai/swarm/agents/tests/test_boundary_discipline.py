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
    API_REQUEST_V1,
    API_RESPONSE_V1,
    DATA_REQUEST_V1,
    MAINT_ACK,
    MAINT_EVENT,
    MATCH_OUTCOME,
    NLP_ALERT_V1,
    NLP_EVENT_V1,
    PREDICT_APPROVED,
    PREDICT_FINAL,
    PREDICT_REQUEST_V1,
    PROOF_FLAG,
    PROOFREADER_VERDICT,
    QA_ANSWER_V1,
    QA_INTENT_V1,
    QA_REQUEST,
    QA_REQUEST_V1,
    SEC_ALERT,
    SEC_DENYLIST,
    SEC_QUARANTINE,
)
from swarm.sdk.wire_contracts import API_TOPIC_V1_ALLOWED_PRODUCERS
from swarm.sdk.wire_contracts import MAINT_EVENT_V1_ALLOWED_PRODUCERS
from swarm.sdk.wire_contracts import NLP_ALERT_V1_ALLOWED_PRODUCERS
from swarm.sdk.wire_contracts import NLP_EVENT_V1_ALLOWED_PRODUCERS
from swarm.sdk.wire_contracts import SEC_ALERT_V1_ALLOWED_KINDS_BY_PRODUCER
from swarm.sdk.wire_contracts import SEC_ALERT_V1_ALLOWED_PRODUCERS


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
    """7.3 / §8.9 SOLE-writer contract.

    ``sec.rate.v1`` is the *only* direct publisher of
    ``sec.denylist.v1`` on the bus.  The Phase 8.8 sweeper
    (``maint.sec.v1``) interacts with the denylist exclusively via
    the Lua atomic script (``sec_denylist_decimate.lua``) under the
    existing Redis key prefix — it never emits ``sec.denylist.v1``
    as a bus message.  No other agent may become a second direct
    producer.
    """
    from swarm.agents.maint.backup import MaintBackupAgent  # noqa: PLC0415
    from swarm.agents.maint.deadmans import MaintDeadmansSwitch  # noqa: PLC0415
    from swarm.agents.maint.dlq import MaintDlqSupervisor  # noqa: PLC0415
    from swarm.agents.maint.schema import MaintSchemaSentinel  # noqa: PLC0415
    from swarm.agents.maint.scaler import MaintScaler  # noqa: PLC0415
    from swarm.agents.maint.sec import MaintSecAgent  # noqa: PLC0415

    assert SEC_DENYLIST in tuple(SecRateAgent.publishes)
    _phase8_maint_agents = (
        MaintSecAgent,
        MaintScaler,
        MaintDlqSupervisor,
        MaintSchemaSentinel,
        MaintBackupAgent,
        MaintDeadmansSwitch,
    )
    for cls in (*_NON_SEC_AGENTS, SecInputAgent, SecScrapeAgent, *_phase8_maint_agents):
        assert SEC_DENYLIST not in tuple(getattr(cls, "publishes", ())), (
            f"{cls.__name__} must not publish sec.denylist.v1 - "
            "only sec.rate.v1 may (single-writer denylist). "
            "The §8.8 sweeper uses Lua under the existing key prefix "
            "and never emits a bus message on this topic."
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


# ── Rule 7 (Phase 7 §7.6 — enumerative coverage) ────────────────
#
# The tests above lock the contract for the agents that exist
# *today*. The tests below use the canonical agent registry
# (``build_agents()``) so adding a new agent in a later phase
# automatically participates in the boundary check — a future
# Phase 10 NLP agent that subscribes to ``qa.request`` (raw)
# instead of ``qa.request.v1`` (sanitized) will fail this suite
# at landing time, not in production.
#
# These tests deliberately exclude the Go gateway path (a Phase 7
# follow-up; not yet built under ``server/internal/sec/``). Go-side
# §7.6 items (XFF derivation, IPv6 prefix bucketing, password
# bypass, endpoint cost mapping) live in their own ``*_test.go``
# files when that surface lands.


def _registry_agents() -> tuple[object, ...]:
    """The canonical agent set used by ``bootstrap.build_swarm``.

    Importing here (function-local) keeps the import light and
    avoids a circular ``swarm.bootstrap`` dependency at module
    load. ``build_agents()`` is the single source of truth — any
    new agent class wired into a real swarm flows through here
    and inherits these checks for free.
    """
    from swarm.bootstrap import build_agents  # noqa: PLC0415

    return tuple(build_agents())


def _agent_label(agent: object) -> str:
    return getattr(agent, "name", agent.__class__.__name__)


# ``telemetry.v1`` is a counter-only meta-consumer (subscribes to
# the union of `_WATCHED_TOPICS` to emit Prometheus metrics; per
# the §4.6 cardinality contract it never inspects payload bytes).
# It is allow-listed in every consumer-set check below — telemetry
# subscribing is the *expected* state, not a contract violation.
# The positive `test_telemetry_watches_phase7_topics` assertion at
# the bottom of this section enforces it.
_TELEMETRY_LABEL = "telemetry.v1"


def test_qa_request_v1_consumer_set_is_bounded() -> None:
    """§7.6 + §10.0: ``qa.request.v1`` has exactly one data consumer:
    ``nlp.intent.v1`` (Phase 10, now landed).  ``telemetry.v1``
    legitimately watches for counter purposes (§4.6) and is excluded
    from the offender set.  Any agent other than these two subscribing
    to the sanitized QA stream would bypass the intent-classification
    gate and route raw (though sec-sanitized) user bytes to an
    unexpected consumer.
    """
    # ``nlp.intent.v1`` is the ONLY data consumer; telemetry is the
    # only allowed meta-consumer (counter-only, §4.6).
    allowed = {"nlp.intent.v1", _TELEMETRY_LABEL}
    offenders: list[str] = []
    for agent in _registry_agents():
        label = _agent_label(agent)
        if label in allowed:
            continue
        if QA_REQUEST_V1 in tuple(getattr(agent, "subscribes", ())):
            offenders.append(label)
    assert offenders == [], (
        "qa.request.v1 must have exactly one data consumer "
        "(nlp.intent.v1) plus telemetry.v1 as a meta-watcher. "
        "Any other subscriber bypasses the Phase 10 intent "
        f"classification gate. Unexpected consumers: {offenders}."
    )


def test_sec_quarantine_v1_consumer_set_is_storage_only() -> None:
    """§7.6: ``sec.quarantine.v1`` consumer set is ``{storage.v1}``
    only (no predictor / NLP / proofreader subscriber). Today
    ``StorageAgent`` does NOT yet subscribe (the parquet/Postgres
    persistence path is a separate Phase 7 deliverable that lands
    with migration ``007_quarantine.sql`` wiring); the contract we
    lock here is the negative — *no* non-storage agent may ever
    subscribe. When storage wires the consumer, this test still
    passes because the allow-list permits it.
    """
    allowed = {"storage.v1", _TELEMETRY_LABEL}
    offenders: list[str] = []
    for agent in _registry_agents():
        label = _agent_label(agent)
        if label in allowed:
            continue
        subs = tuple(getattr(agent, "subscribes", ()))
        if SEC_QUARANTINE in subs:
            offenders.append(label)
    assert offenders == [], (
        "sec.quarantine.v1 may only be consumed by storage.v1 "
        "(quarantine_samples persistence) or telemetry.v1 "
        "(counter-only). Other subscribers leak forensic payloads "
        "to predictors / NLP / proofreaders. "
        f"Offenders: {offenders}."
    )


def test_qa_request_consumer_set_is_sec_input_only() -> None:
    """§7.6 / §7.5: the raw ``qa.request`` (control-plane) is the
    gateway's escalation channel. Only ``sec.input.v1`` may
    consume; everything else (NLP, predictors, future operator
    consoles) must subscribe to the sanitized ``qa.request.v1``
    stream so they never see un-validated bytes.
    """
    allowed = {"sec.input.v1", _TELEMETRY_LABEL}
    offenders: list[str] = []
    for agent in _registry_agents():
        label = _agent_label(agent)
        if label in allowed:
            continue
        if QA_REQUEST in tuple(getattr(agent, "subscribes", ())):
            offenders.append(label)
    assert offenders == [], (
        "qa.request (raw) must only be consumed by sec.input.v1. "
        "(telemetry.v1 is allow-listed for counter-only watch.) "
        "Anyone else processing un-sanitized QA bytes bypasses the "
        f"defense pipeline. Offenders: {offenders}."
    )


def test_no_agent_publishes_both_qa_request_and_qa_request_v1() -> None:
    """§7.5: the gateway-pass path and the agent-pass path are
    *mutually exclusive* per ``request_id`` by construction. Inside
    the swarm, no single agent may emit on both topics — that would
    re-introduce the double-publish surface that the §7.5 dedup
    contract is designed to eliminate.
    """
    offenders: list[str] = []
    for agent in _registry_agents():
        pub = tuple(getattr(agent, "publishes", ()))
        if QA_REQUEST in pub and QA_REQUEST_V1 in pub:
            offenders.append(_agent_label(agent))
    assert offenders == [], (
        "No agent may publish both qa.request and qa.request.v1 — "
        "the two are exclusive halves of the gateway↔agent "
        f"contract (§7.5). Offenders: {offenders}."
    )


def test_sec_denylist_v1_no_unauthorised_writer_in_registry() -> None:
    """§7.6: ``sec.rate.v1`` is the SOLE writer of the denylist
    (bus side; the Lua-script side is locked by
    ``test_phase7_lua_scripts.py``). The class-level test above
    covers the known agent classes; this enumerative variant scans
    the registry so a future agent wired into ``build_agents()``
    cannot quietly become a second producer.
    """
    allowed = {"sec.rate.v1"}
    offenders: list[str] = []
    for agent in _registry_agents():
        label = _agent_label(agent)
        if label in allowed:
            continue
        if SEC_DENYLIST in tuple(getattr(agent, "publishes", ())):
            offenders.append(label)
    assert offenders == [], (
        "sec.denylist.v1 may only be published by sec.rate.v1; "
        f"second-producer offenders: {offenders}. Multi-replica "
        "denylist writers require Postgres-backed leader election "
        "(Phase 14.x) — not landing in v1."
    )


def test_sec_alert_v1_producer_set_is_sec_only() -> None:
    """§7.5 catalog row + §8.x extension: ``sec.alert.v1`` has an
    open producer set bounded to ``sec.*`` agents AND ``maint.*``
    reactors that surface defense-class operational alerts
    (e.g. ``dlq_backlog_high``, ``maint_storage_pressure``,
    ``maint_advisory_lock_held_long``). A predictor / proofreader /
    cache agent emitting a sec alert would smuggle non-defense
    events onto the operator pager channel.
    """
    from swarm.agents.maint.backup import MaintBackupAgent  # noqa: PLC0415
    from swarm.agents.maint.deadmans import MaintDeadmansSwitch  # noqa: PLC0415
    from swarm.agents.maint.dlq import MaintDlqSupervisor  # noqa: PLC0415
    from swarm.agents.maint.schema import MaintSchemaSentinel  # noqa: PLC0415
    from swarm.agents.maint.scaler import MaintScaler  # noqa: PLC0415

    offenders: list[str] = []
    classes = (
        *_NON_SEC_AGENTS,
        SecInputAgent,
        SecScrapeAgent,
        SecRateAgent,
        MaintDeadmansSwitch,
        MaintDlqSupervisor,
        MaintScaler,
        MaintSchemaSentinel,
        MaintBackupAgent,
    )
    for cls in classes:
        label = getattr(cls, "name", cls.__name__)
        if SEC_ALERT in tuple(getattr(cls, "publishes", ())):
            if label not in SEC_ALERT_V1_ALLOWED_PRODUCERS:
                offenders.append(label)
    assert offenders == [], (
        "sec.alert.v1 producer set must stay inside "
        f"SEC_ALERT_V1_ALLOWED_PRODUCERS={sorted(SEC_ALERT_V1_ALLOWED_PRODUCERS)}; "
        f"offenders: {offenders}."
    )

def test_telemetry_watches_phase7_topics() -> None:
    """§7.7 cross-phase: the telemetry watch-set must include every
    Phase 7 wire topic so the Prometheus page sees the security
    counters from day-1. The negative tests above allow-list
    ``telemetry.v1``; this positive test ensures that allowance is
    *earned* — telemetry actually subscribes to all four Phase 7
    surfaces (raw + sanitized QA, alert, quarantine, denylist).

    Cardinality bound: telemetry counts by topic only, never by
    payload field (the open-enum ``kind`` value is exposed via the
    dedicated dashboard counter, not as a metric label here — see
    ``_WATCHED_TOPICS`` docstring).
    """
    from swarm.agents.telemetry import WATCHED_TOPICS  # noqa: PLC0415

    required = {QA_REQUEST, QA_REQUEST_V1, SEC_ALERT, SEC_QUARANTINE, SEC_DENYLIST}
    missing = required - set(WATCHED_TOPICS)
    assert not missing, (
        "telemetry._WATCHED_TOPICS is missing Phase 7 topic(s): "
        f"{sorted(missing)}. The §7.7 cross-phase alignment requires "
        "all five sec topics on the Prometheus page."
    )


# ── Rule 8 (Phase 8 §8.9): maint.event.v1 producer set — registry ──


def test_maint_event_v1_producer_set_registry_bounded() -> None:
    """§8.9 boundary discipline: ``maint.event.v1`` producer set in
    the live registry must be a subset of
    ``MAINT_EVENT_V1_ALLOWED_PRODUCERS`` (Phase 8-expanded).

    Canonical permitted producers:
      * ``drift.v1``         — Phase 6.3 retrain_request
      * ``ops_console``      — Phase 8 CLI (not an in-process agent)
      * ``maint.scaler.v1``  — Phase 8 reactor
      * ``maint.backup.v1``  — Phase 8 reactor
      * ``maint.dlq.v1``     — Phase 8 reactor
      * ``maint.schema.v1``  — Phase 8 reactor
      * ``maint.sec.v1``     — Phase 8 reactor
      * ``source.watcher.v1`` — Phase 2.8 SDK-migrated producer

    Any future in-process agent that needs to publish
    ``maint.event.v1`` must add itself to
    ``swarm.sdk.wire_contracts.MAINT_EVENT_V1_ALLOWED_PRODUCERS``
    in a separate commit with a tracker row + minor version bump.
    This test will fail at landing time, not in production.
    """
    offenders: list[str] = []
    for agent in _registry_agents():
        label = _agent_label(agent)
        if MAINT_EVENT in tuple(getattr(agent, "publishes", ())):
            if label not in MAINT_EVENT_V1_ALLOWED_PRODUCERS:
                offenders.append(label)
    assert offenders == [], (
        "maint.event.v1 producer set must stay inside "
        f"MAINT_EVENT_V1_ALLOWED_PRODUCERS="
        f"{sorted(MAINT_EVENT_V1_ALLOWED_PRODUCERS)}; "
        f"unlisted producers found in registry: {offenders}. "
        "Add the producer name to wire_contracts.py with a tracker "
        "row + minor version bump."
    )


# ── Rule 9 (Phase 8 §8.9): maint.ack.v1 producer / consumer sets ─


def test_maint_ack_v1_producers_are_maint_event_consumers() -> None:
    """§8.9 boundary discipline: every in-process agent that
    publishes ``maint.ack.v1`` must also subscribe to
    ``maint.event.v1``.

    Rationale: an ack is a receipt for a command carried on
    ``maint.event.v1``.  Any agent that emits an ack without
    listening to the command channel is either wrong or bypassing
    the normal request→ack flow.  This test pins the invariant
    so a future refactor cannot silently break it.
    """
    offenders: list[str] = []
    for agent in _registry_agents():
        pubs = tuple(getattr(agent, "publishes", ()))
        subs = tuple(getattr(agent, "subscribes", ()))
        if MAINT_ACK in pubs and MAINT_EVENT not in subs:
            offenders.append(_agent_label(agent))
    assert offenders == [], (
        "maint.ack.v1 producers must also subscribe to "
        "maint.event.v1 (ack implies receipt of a command). "
        f"Offenders that publish ack without consuming event: {offenders}."
    )


def test_maint_ack_v1_no_in_process_consumer() -> None:
    """§8.9/§8.16 boundary discipline: only explicitly-audited in-process
    exceptions may subscribe to ``maint.ack.v1``.

    Only ``ops_console`` (an out-of-process CLI tool, not an agent
    in ``build_agents()``) is allowed to wait for acks.  Agents
    must NOT consume each other's acks — that would create
    implicit coupling between reactors and break the single-reader
    ops-console contract.

    ``telemetry.v1`` is an allowed exception because it is a meta-consumer
    (counter-only, per §4.6) that watches every topic for Prometheus
    metrics.  ``maint.dlq.v1`` is the other allowed exception (Phase
    §8.16.2), where it acts as the ack-only spool-flush reconciler.
    Any additional subscriber remains a boundary violation.
    """
    allowed = {_TELEMETRY_LABEL, "maint.dlq.v1"}
    offenders: list[str] = []
    for agent in _registry_agents():
        label = _agent_label(agent)
        if label in allowed:
            continue
        subs = tuple(getattr(agent, "subscribes", ()))
        if MAINT_ACK in subs:
            offenders.append(label)
    assert offenders == [], (
        "maint.ack.v1 must have no in-process consumer beyond the "
        "documented exceptions (telemetry.v1 and maint.dlq.v1). "
        "(only the out-of-process ops_console CLI waits for acks; "
        "all other in-process subscribers are forbidden). "
        f"In-registry subscribers found: {offenders}. "
        "Agents must not consume each others' acks."
    )


# ── Rule 9 (Phase 8 §8.9): telemetry.v1 as sec.alert.v1 producer ──────


def test_telemetry_is_allowed_sec_alert_producer() -> None:
    """§8.9 boundary (positive): ``telemetry.v1`` MUST appear in
    ``SEC_ALERT_V1_ALLOWED_PRODUCERS`` because the dead-mans-switch
    relay is its single publication on that topic.  Removing it from
    the set would silently break the Phase 8.10 silence alert.
    """
    assert "telemetry.v1" in SEC_ALERT_V1_ALLOWED_PRODUCERS, (
        "telemetry.v1 must be in SEC_ALERT_V1_ALLOWED_PRODUCERS — it is"
        " the dead-mans-switch relay for maint_silence_alert (§8.10).  "
        "Do not remove it without adding a replacement relay agent."
    )


def test_telemetry_sec_alert_kind_pin() -> None:
    """§8.9 boundary (pin): ``telemetry.v1`` may publish ``sec.alert.v1``
    ONLY with ``kind=maint_silence_alert``.  Any other kind from telemetry
    must fail the per-producer kind allow-list.

    This test has two assertions:
    (a) the pin set is exactly ``{maint_silence_alert}`` — no extras;
    (b) every other kind in ``KNOWN_SEC_ALERT_KINDS`` is excluded from
        the telemetry pin, so a coding error (adding a second kind to
        the pin) is caught immediately.
    """
    from swarm.agents.payloads import KNOWN_SEC_ALERT_KINDS  # noqa: PLC0415

    telemetry_pin: frozenset[str] = SEC_ALERT_V1_ALLOWED_KINDS_BY_PRODUCER[
        "telemetry.v1"
    ]

    # (a) Pin must equal exactly the one permitted kind.
    assert telemetry_pin == frozenset({"maint_silence_alert"}), (
        "SEC_ALERT_V1_ALLOWED_KINDS_BY_PRODUCER['telemetry.v1'] must be "
        "exactly {'maint_silence_alert'} — adding any other kind grants "
        "telemetry the ability to raise arbitrary operator alerts.  "
        f"Actual pin: {sorted(telemetry_pin)}"
    )

    # (b) All other known sec.alert kinds must be outside the pin.
    forbidden = KNOWN_SEC_ALERT_KINDS - telemetry_pin
    leaked = telemetry_pin & forbidden
    assert not leaked, (
        "telemetry.v1 kind-pin contains kinds that should be off-limits: "
        f"{sorted(leaked)}.  Only maint_silence_alert is permitted."
    )


# ── Rule 10 (Phase 9 §9.0): api.request.v1 + api.response.v1 ────
#   sole producer = api.gateway.v1 (Go gateway, never a swarm agent)


def test_api_topic_v1_allowed_producers_constant() -> None:
    """§9.0 wire-authority delta: the allowed-producers set for the
    api.* audit topics must be exactly ``{"api.gateway.v1"}``.

    The Go gateway is the *only* process that may write audit events
    onto these topics.  No Python swarm agent belongs here.  This
    test pins the constant so a future phase cannot silently add an
    in-process producer without a doctrine change + tracker row.
    """
    assert API_TOPIC_V1_ALLOWED_PRODUCERS == frozenset({"api.gateway.v1"}), (
        "API_TOPIC_V1_ALLOWED_PRODUCERS must be exactly "
        "{'api.gateway.v1'} — the api.* audit topics are a "
        "Go-gateway-only production surface (Phase 9 §9.0). "
        f"Actual: {sorted(API_TOPIC_V1_ALLOWED_PRODUCERS)}"
    )


def test_no_swarm_agent_publishes_api_request_v1() -> None:
    """§9.0: no in-process swarm agent may publish ``api.request.v1``.

    The sole producer is ``api.gateway.v1`` (the Go gateway process).
    This enumerative registry scan catches any future agent class that
    accidentally wires the audit topic into its publish set.
    """
    offenders: list[str] = []
    for agent in _registry_agents():
        if API_REQUEST_V1 in tuple(getattr(agent, "publishes", ())):
            offenders.append(_agent_label(agent))
    assert offenders == [], (
        "api.request.v1 may only be produced by api.gateway.v1 (Go). "
        "No Python swarm agent may publish here. "
        f"In-registry violators: {offenders}."
    )


def test_no_swarm_agent_publishes_api_response_v1() -> None:
    """§9.0: no in-process swarm agent may publish ``api.response.v1``.

    The sole producer is ``api.gateway.v1`` (the Go gateway process).
    """
    offenders: list[str] = []
    for agent in _registry_agents():
        if API_RESPONSE_V1 in tuple(getattr(agent, "publishes", ())):
            offenders.append(_agent_label(agent))
    assert offenders == [], (
        "api.response.v1 may only be produced by api.gateway.v1 (Go). "
        "No Python swarm agent may publish here. "
        f"In-registry violators: {offenders}."
    )


def test_api_audit_consumer_set_is_bounded() -> None:
    """§9.0: consumer set for both api.* audit topics is bounded today.

    Allowed: ``telemetry.v1`` (counter-only Prometheus watch, §4.6).
    ``audit.v1`` (Phase 8 §8.13.2 hash-chain mirror) is not yet in the
    Python swarm registry; when it lands it must be added to the
    allow-list here with a tracker row.

    This test locks the current non-telemetry consumer set to zero so a
    future phase cannot silently route a predictor or NLP agent onto the
    raw gateway audit stream.
    """
    allowed = {_TELEMETRY_LABEL}
    for topic, name in (
        (API_REQUEST_V1, "api.request.v1"),
        (API_RESPONSE_V1, "api.response.v1"),
    ):
        offenders: list[str] = []
        for agent in _registry_agents():
            label = _agent_label(agent)
            if label in allowed:
                continue
            if topic in tuple(getattr(agent, "subscribes", ())):
                offenders.append(label)
        assert offenders == [], (
            f"{name} consumer set must be empty today (telemetry.v1 "
            "is allowed as a counter-only watcher). When audit.v1 "
            "lands (Phase 8 §8.13.2), add it to the allow-list here. "
            f"Unexpected consumers: {offenders}."
        )


def test_telemetry_watches_phase9_api_audit_topics() -> None:
    """§9.0 positive: telemetry must include both Phase 9 api.* audit
    topics so the Prometheus page sees the gateway audit-trail counters
    from day-1, before the Go gateway is fully wired.
    """
    from swarm.agents.telemetry import WATCHED_TOPICS  # noqa: PLC0415

    required = {API_REQUEST_V1, API_RESPONSE_V1}
    missing = required - set(WATCHED_TOPICS)
    assert not missing, (
        "telemetry._WATCHED_TOPICS is missing Phase 9 api.* topic(s): "
        f"{sorted(missing)}. The §9.0 cross-phase alignment requires "
        "both api audit topics on the Prometheus page."
    )


# ── Rule 11 (Phase 10 §10.0): NLP plane boundary discipline ────────────
#
# Four invariants (binding, to be AST-asserted in §10.20):
#  a) NLP NEVER subscribes to raw ``qa.request`` (control-plane).
#     Only ``qa.request.v1`` (sanitized data-plane).  Mirrors §7.5.
#  b) NLP NEVER subscribes to ``predict.final`` (unvetted candidate).
#     Only ``predict.approved.v1`` (Phase 6 proofreader-gated).
#  c) NLP NEVER publishes to ``sec.*``, ``maint.*``, ``auth.*``,
#     ``payment.*``, ``patcher.*``.  Outbound topics bounded to
#     ``{qa.intent.v1, qa.answer.v1, nlp.event.v1, nlp.alert.v1,
#       predict.request.v1, data.request.v1}``.
#  d) ``nlp.event.v1`` / ``nlp.alert.v1`` producer set is bounded
#     to the three NLP agents in
#     ``NLP_EVENT_V1_ALLOWED_PRODUCERS`` /
#     ``NLP_ALERT_V1_ALLOWED_PRODUCERS``.
#
# The tests use the canonical registry (``build_agents()``) so any
# future NLP agent wired into bootstrap automatically inherits the
# guard at landing time, not in production.
# ────────────────────────────────────────────────────────────────────────


# The complete allowed outbound set for any NLP agent (§10.0).
_NLP_OUTBOUND_ALLOWED = frozenset({
    QA_INTENT_V1,
    QA_ANSWER_V1,
    NLP_EVENT_V1,
    NLP_ALERT_V1,
    PREDICT_REQUEST_V1,
    DATA_REQUEST_V1,
})

# Forbidden subscriptions for any NLP agent.
_NLP_SUBSCRIBE_FORBIDDEN = (QA_REQUEST, PREDICT_FINAL)

# Closed topic name prefixes that NLP must NEVER publish to.
_NLP_FORBIDDEN_PUBLISH_PREFIXES = (
    "sec.",
    "maint.",
    "auth.",
    "payment.",
    "patcher.",
)


def _is_nlp_agent(agent: object) -> bool:
    """True for agents whose name starts with ``nlp.``."""
    return str(getattr(agent, "name", "")).startswith("nlp.")


def test_nlp_agents_do_not_subscribe_to_raw_qa_request() -> None:
    """§10.0 boundary: NLP NEVER subscribes to ``qa.request`` (raw
    control-plane).  Only ``qa.request.v1`` (sanitized data-plane,
    after sec.input.v1 has run) is the legal NLP entry-point.
    Subscribing to the raw topic would expose un-validated bytes
    to the NLP stack, bypassing the defense tier entirely.
    """
    offenders: list[str] = []
    for agent in _registry_agents():
        if not _is_nlp_agent(agent):
            continue
        if QA_REQUEST in tuple(getattr(agent, "subscribes", ())):
            offenders.append(_agent_label(agent))
    assert offenders == [], (
        "NLP agent(s) must not subscribe to qa.request (raw). "
        "Use qa.request.v1 (the sec-sanitized data-plane topic). "
        f"Offenders: {offenders}."
    )


def test_nlp_agents_do_not_subscribe_to_predict_final() -> None:
    """§10.0 boundary: NLP NEVER subscribes to ``predict.final``
    (the un-vetted Phase 5 consensus candidate).  Using it would
    let un-proofread predictions reach the user-facing answer,
    bypassing the Phase 6 quorum gate entirely.  Only
    ``predict.approved.v1`` (post-quorum, post-proofreader) is the
    legal NLP subscription for predictions.
    """
    offenders: list[str] = []
    for agent in _registry_agents():
        if not _is_nlp_agent(agent):
            continue
        if PREDICT_FINAL in tuple(getattr(agent, "subscribes", ())):
            offenders.append(_agent_label(agent))
    assert offenders == [], (
        "NLP agent(s) must not subscribe to predict.final — that is "
        "the unvetted candidate. Subscribe to predict.approved.v1 "
        f"(post-quorum). Offenders: {offenders}."
    )


def test_nlp_agent_outbound_topics_are_bounded() -> None:
    """§10.0 boundary: any NLP agent's publish set must be a strict
    subset of
    ``{qa.intent.v1, qa.answer.v1, nlp.event.v1, nlp.alert.v1,
       predict.request.v1, data.request.v1}``.

    Publishing outside this set (e.g. to ``sec.alert.v1`` or
    ``maint.event.v1``) would break the topology by routing
    NLP-class events to operator channels meant exclusively for
    sec.*/maint.* actors.
    """
    offenders: list[str] = []
    for agent in _registry_agents():
        if not _is_nlp_agent(agent):
            continue
        publishes = frozenset(getattr(agent, "publishes", ()))
        forbidden = publishes - _NLP_OUTBOUND_ALLOWED
        if forbidden:
            offenders.append(
                f"{_agent_label(agent)} publishes forbidden topics: "
                f"{sorted(str(t) for t in forbidden)}"
            )
    assert offenders == [], (
        "NLP outbound set must be a subset of "
        f"{sorted(str(t) for t in _NLP_OUTBOUND_ALLOWED)}. "
        f"Violations: {offenders}."
    )


def test_nlp_agents_do_not_publish_to_forbidden_prefixes() -> None:
    """§10.0 boundary: NLP NEVER publishes to topics whose name
    starts with ``sec.``, ``maint.``, ``auth.``, ``payment.``, or
    ``patcher.``.  This is a belt-and-suspenders check on top of
    ``test_nlp_agent_outbound_topics_are_bounded``: even if the
    outbound allow-set above gains a mis-entry, this prefix guard
    catches it immediately.
    """
    offenders: list[str] = []
    for agent in _registry_agents():
        if not _is_nlp_agent(agent):
            continue
        for topic in getattr(agent, "publishes", ()):
            topic_str = str(topic)
            for prefix in _NLP_FORBIDDEN_PUBLISH_PREFIXES:
                if topic_str.startswith(prefix):
                    offenders.append(
                        f"{_agent_label(agent)} → {topic_str} "
                        f"(forbidden prefix '{prefix}')"
                    )
    assert offenders == [], (
        "NLP agent(s) must not publish to sec.*/maint.*/auth.*/"
        "payment.*/patcher.* topics (§10.0 boundary discipline). "
        f"Violations: {offenders}."
    )


def test_nlp_event_v1_producer_set_bounded() -> None:
    """§10.0 wire-authority: ``nlp.event.v1`` producer set in the live
    registry must be a subset of ``NLP_EVENT_V1_ALLOWED_PRODUCERS``.

    Producers today: ``nlp.intent.v1``, ``nlp.answer.v1``,
    ``nlp.proofreader.v1``.  Any future NLP agent that needs to emit
    ``nlp.event.v1`` must add itself to
    ``swarm.sdk.wire_contracts.NLP_EVENT_V1_ALLOWED_PRODUCERS`` in a
    separate commit with a tracker row + minor version bump.
    """
    offenders: list[str] = []
    for agent in _registry_agents():
        label = _agent_label(agent)
        if NLP_EVENT_V1 in tuple(getattr(agent, "publishes", ())):
            if label not in NLP_EVENT_V1_ALLOWED_PRODUCERS:
                offenders.append(label)
    assert offenders == [], (
        "nlp.event.v1 producer set must stay inside "
        f"NLP_EVENT_V1_ALLOWED_PRODUCERS="
        f"{sorted(NLP_EVENT_V1_ALLOWED_PRODUCERS)}; "
        f"unlisted producers in registry: {offenders}. "
        "Add the producer to wire_contracts.py with a tracker row "
        "+ minor version bump."
    )


def test_nlp_alert_v1_producer_set_bounded() -> None:
    """§10.0 wire-authority: ``nlp.alert.v1`` producer set in the live
    registry must be a subset of ``NLP_ALERT_V1_ALLOWED_PRODUCERS``.

    The alert channel and the event channel share the same producer tier
    (§10.0 boundary discipline) — both are bounded to the three NLP
    plane agents.
    """
    offenders: list[str] = []
    for agent in _registry_agents():
        label = _agent_label(agent)
        if NLP_ALERT_V1 in tuple(getattr(agent, "publishes", ())):
            if label not in NLP_ALERT_V1_ALLOWED_PRODUCERS:
                offenders.append(label)
    assert offenders == [], (
        "nlp.alert.v1 producer set must stay inside "
        f"NLP_ALERT_V1_ALLOWED_PRODUCERS="
        f"{sorted(NLP_ALERT_V1_ALLOWED_PRODUCERS)}; "
        f"unlisted producers in registry: {offenders}. "
        "Add the producer to wire_contracts.py with a tracker row "
        "+ minor version bump."
    )


def test_nlp_intent_agent_subscribes_to_qa_request_v1() -> None:
    """§10.0 positive: ``nlp.intent.v1`` MUST subscribe to
    ``qa.request.v1`` — that is its input from the sec-sanitization
    tier.  If this assertion fails it means the agent was wired to
    the wrong topic (e.g. raw ``qa.request``) and the previous
    negative test would also fire.
    """
    from swarm.agents.nlp import NlpIntentAgent  # noqa: PLC0415

    assert QA_REQUEST_V1 in tuple(NlpIntentAgent.subscribes), (
        "nlp.intent.v1 must subscribe to qa.request.v1 (the Phase 7 "
        "sec-sanitized data-plane envelope)."
    )


def test_nlp_answer_agent_subscribes_to_predict_approved_not_final() -> None:
    """§10.0 positive + negative pair: ``nlp.answer.v1`` MUST subscribe
    to ``predict.approved.v1`` (post-quorum) and MUST NOT subscribe to
    ``predict.final`` (pre-quorum candidate).
    """
    from swarm.agents.nlp import NlpAnswerAgent  # noqa: PLC0415

    assert PREDICT_APPROVED in tuple(NlpAnswerAgent.subscribes), (
        "nlp.answer.v1 must subscribe to predict.approved.v1 — the "
        "post-quorum, proofreader-gated prediction surface."
    )
    assert PREDICT_FINAL not in tuple(NlpAnswerAgent.subscribes), (
        "nlp.answer.v1 must NOT subscribe to predict.final — that is "
        "the unvetted candidate.  Subscribing here would expose "
        "un-proofread predictions to the user-facing answer."
    )
