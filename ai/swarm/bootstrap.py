"""Phase 6 audit (F-1, F-10) — single-entry-point swarm bootstrap.

`build_swarm()` constructs every Phase 5 + Phase 6 agent the
predictor / proofreader / drift pipeline needs, wraps each in an
`AgentRunner`, and returns the runners ready for `register()` +
`run()` (or `step()` in tests). Without this, the audit found that
the proofreader replicas, aggregator, and drift agent all existed
as classes but had no production wiring — the API would have been
emitting `predict.final` to nobody and `predict.approved.v1` would
never appear.

The bootstrap also enforces the "single instance" invariants that
the boundary-discipline tests assume but did not previously police
in production code:

* `consensus.v1` — exactly one
* `proofreader_aggregator.v1` — exactly one
* `drift.v1` — exactly one

These three agents own per-window or per-prediction state that is
NOT shared via the bus, so running two replicas would silently
produce duplicate `predict.final` / `predict.approved.v1` /
`maint.event.v1` emissions. A second copy must run as a hot-spare
behind a leader election (Phase 12+); v1 ships single-leader.

This module is import-safe: building the swarm does not touch the
network or Redis. The bus and registry are injected by the caller
(`InMemoryBus` for tests, the Redis-backed bus for production).

Doctrine references: AGENTS.md §2 (Rules 1, 5, 7, 10);
docs/design/SWARM.md (single-instance agents);
docs/reports/phase6-implementation.md F-1 / F-10.
"""
from __future__ import annotations

import logging
from typing import Iterable

from common.config import cfg as _cfg

from .agents.cache import CacheAgent
from .agents.consensus import ConsensusAgent
from .agents.drift import DriftAgent
from .agents.predictors import dixon_coles, elo, xgb_form, xgb_xg
from .agents.predictors.lgbm_market import LgbmMarketPredictor
from .agents.proofreader.aggregator import ProofreaderAggregatorAgent
from .agents.proofreader.replicas import PROOFREADER_POLICY_CLASSES
from .agents.reactor import InMemoryLedger
from .agents.telemetry import TelemetryAgent
from .sdk.agent import Agent
from .sdk.bus import Bus
from .sdk.registry import AgentRegistry
from .sdk.runner import AgentRunner

_log = logging.getLogger("swarm.bootstrap")


# Agent names that may only have one runner per swarm. A second copy
# would silently produce duplicate emissions because they hold per-
# window / per-prediction state outside the bus. Hot-spare deployment
# must wait until a leader-election layer lands (Phase 12+).
SINGLE_INSTANCE_AGENTS: frozenset[str] = frozenset({
    "consensus.v1",
    "proofreader_aggregator.v1",
    "drift.v1",
})


class SingleInstanceViolation(RuntimeError):
    """Raised by `build_swarm` if a single-instance agent name appears
    more than once in the assembled runner set."""


def _build_predictors() -> list[Agent]:
    """The four must-vote predictors for `cfg.consensus_min_voters`
    quorum, plus the optional LGBM market predictor when its market-
    features flag is on. The set matches the boundary-discipline test
    catalog so adding a new predictor only requires updating both
    sites in lockstep.
    """
    predictors: list[Agent] = [
        elo.EloPredictor(),
        dixon_coles.DixonColesPredictor(),
        xgb_form.XgbFormPredictor(),
        xgb_xg.XgbXgPredictor(),
    ]
    if _cfg.predictor_market_features_enabled:
        predictors.append(LgbmMarketPredictor())
    return predictors


def _build_proofreader_replicas() -> list[Agent]:
    """One instance of each policy class declared in
    ``PROOFREADER_POLICY_CLASSES``.

    The roster is the single source of truth for the replica count;
    ``cfg.proofreader_quorum`` derives quorum from
    ``len(PROOFREADER_POLICY_CLASSES)`` so an operator cannot drift
    the two. Phase-6 audit F3-1 retired the standalone
    ``cfg.proofreader_replicas`` env knob because it was disconnected
    from this list. Horizontal fan-out moves to consumer-group
    sharding (Phase 14), which scales throughput without changing
    vote count.
    """
    return [cls() for cls in PROOFREADER_POLICY_CLASSES]


def build_agents() -> list[Agent]:
    """Construct the full Phase 4 (consumer) + Phase 5 + Phase 6 agent
    set in dependency order. Useful for tests that want the agents
    without runners.

    Phase 4 *consumers* (`cache.v1`, `telemetry.v1`) are included so a
    swarm built via `build_swarm()` actually serves the Phase 6
    `predict.approved.v1` topic to the Phase 9 API gateway and exposes
    Phase 6 metrics on the telemetry HTTP page (Phase-6 second-pass
    audit F2-2). The Phase 4 *producers* (`storage.v1`, `processor.*`,
    `categorizer.v1`, `scraper.*`) live upstream of `scrape.classified`
    / `match.normalized` and are wired by the (separate) datasource
    bootstrap that lands with Phase R1.
    """
    predictors = _build_predictors()
    consensus = ConsensusAgent(
        expected_predictors=tuple(p.predictor_id for p in predictors),  # type: ignore[attr-defined]
        ledger=InMemoryLedger(),
    )
    aggregator = ProofreaderAggregatorAgent(ledger=InMemoryLedger())
    drift = DriftAgent()
    # Phase 4 consumers of the predictor pipeline. Neither is single-
    # instance (cache replicas each own a process-local LRU; telemetry
    # replicas each count what they see). Hot-spare deployment for
    # both is safe; the Postgres-backed cache lift in Phase 9 will
    # need leader election on the *invalidation* path, not here.
    cache = CacheAgent()
    telemetry = TelemetryAgent.from_config(start_http=False)
    return [
        *predictors,
        consensus,
        *_build_proofreader_replicas(),
        aggregator,
        drift,
        cache,
        telemetry,
    ]


def build_swarm(
    bus: Bus,
    registry: AgentRegistry,
    *,
    agents: Iterable[Agent] | None = None,
    flush_interval_sec: float | None = None,
    tick_sec: float = 0.05,
) -> list[AgentRunner]:
    """Wrap each agent in an `AgentRunner` and return them.

    Callers are responsible for `runner.register()` + driving the loop
    (`runner.run()` in production, `runner.step()` in tests).

    `flush_interval_sec` defaults to `cfg.swarm_flush_interval_ms / 1000`
    so the F-2 fix (aggregator window flush tick) is in effect by
    default. Tests that need deterministic flush behaviour pass `0.0`
    and call `runner.step()` after monkeypatching the agent clock.
    """
    agent_list = list(agents) if agents is not None else build_agents()
    _enforce_single_instance(agent_list)
    if flush_interval_sec is None:
        flush_interval_sec = _cfg.swarm_flush_interval_ms / 1000.0

    runners: list[AgentRunner] = []
    for agent in agent_list:
        runners.append(
            AgentRunner(
                agent=agent,
                bus=bus,
                registry=registry,
                tick_sec=tick_sec,
                flush_interval_sec=flush_interval_sec,
                max_in_flight=_cfg.swarm_max_in_flight,
                retry_budget=_cfg.swarm_retry_budget,
                pending_claim_sec=_cfg.swarm_pending_claim_sec,
                heartbeat_sec=_cfg.swarm_heartbeat_sec,
            )
        )
    _log.info(
        "swarm bootstrap: %d agents wired (%d single-instance, "
        "flush_interval=%.3fs)",
        len(runners),
        sum(1 for a in agent_list if a.name in SINGLE_INSTANCE_AGENTS),
        flush_interval_sec,
    )
    return runners


def _enforce_single_instance(agents: list[Agent]) -> None:
    """Phase-6 audit (F-10): refuse to build a swarm where any single-
    instance agent name appears more than once. Catches a configuration
    bug at boot rather than producing duplicate emissions in
    production.
    """
    seen: dict[str, int] = {}
    for a in agents:
        if a.name in SINGLE_INSTANCE_AGENTS:
            seen[a.name] = seen.get(a.name, 0) + 1
    duplicates = {name: count for name, count in seen.items() if count > 1}
    if duplicates:
        raise SingleInstanceViolation(
            "swarm bootstrap: single-instance agents may have at most one "
            f"replica per swarm; got {duplicates}. Hot-spare deployment "
            "requires a leader-election layer (Phase 12+)."
        )


__all__ = [
    "SINGLE_INSTANCE_AGENTS",
    "SingleInstanceViolation",
    "build_agents",
    "build_swarm",
]
