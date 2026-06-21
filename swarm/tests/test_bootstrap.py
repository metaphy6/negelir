"""Phase-6 audit (F-1, F-2, F-10) — bootstrap + flush-tick tests.

These lock in the production wiring that the audit found missing:

* F-1 — `build_swarm()` registers every Phase 5 + 6 agent and an
  end-to-end `predict.request` reaches `predict.approved.v1`.
* F-2 — `AgentRunner` ticks `flush_expired()` so the proofreader
  aggregator window actually closes; a never-quorate candidate
  produces a `proofreader_no_quorum` proof.flag without any
  inbound message kicking `handle()`.
* F-10 — `build_swarm()` rejects two copies of any single-instance
  agent (consensus / aggregator / drift) at boot.
"""
from __future__ import annotations

import pytest

from common.config import cfg as _cfg
from swarm.agents.consensus import ConsensusAgent
from swarm.agents.drift import DriftAgent
from swarm.agents.payloads import PredictRequest
from swarm.agents.proofreader.aggregator import ProofreaderAggregatorAgent
from swarm.agents.reactor import InMemoryLedger
from swarm.agents.topics import (
    PREDICT_APPROVED,
    PREDICT_FINAL,
    PREDICT_REQUEST,
    PROOF_FLAG,
)
from swarm.bootstrap import (
    SINGLE_INSTANCE_AGENTS,
    SingleInstanceViolation,
    build_agents,
    build_swarm,
)
from swarm.sdk.bus import InMemoryBus
from swarm.sdk.registry import AgentRegistry
from swarm.sdk.types import Message


# ── F-1: bootstrap wires the whole pipeline ────────────────────


def _drain(runners, *, max_steps: int = 256) -> None:
    for _ in range(max_steps):
        progress = False
        for r in runners:
            if r.step():
                progress = True
        if not progress:
            return
    raise AssertionError("swarm did not quiesce within max_steps")


def test_build_agents_includes_every_phase5_and_phase6_agent() -> None:
    names = {a.name for a in build_agents()}
    # Phase 5
    assert "consensus.v1" in names
    assert any(n.startswith("pred.") for n in names)
    # Phase 6
    assert "proofreader.sanity.v1" in names
    assert "proofreader.plausibility.v1" in names
    assert "proofreader.consistency.v1" in names
    assert "proofreader_aggregator.v1" in names
    assert "drift.v1" in names
    # Phase-6 second-pass audit (F2-2): the Phase 4 *consumers* of the
    # predictor pipeline must be wired so a swarm built via
    # `build_swarm` actually serves predict.approved.v1 to the API
    # gateway and exposes Phase 6 metrics on the telemetry HTTP page.
    assert "cache.v1" in names
    assert "telemetry.v1" in names
    # Single-instance invariants are satisfied (audit F-10) for every
    # member of the contract that this bootstrap actually wires today.
    # `storage.v1` is part of the frozenset (third-pass audit M1) as
    # a forward-looking guard for the Phase R1 datasource bootstrap,
    # but it is not built by `build_agents()` in the current pivot —
    # so we assert "0 or 1", never "2+", for it here. The dedicated
    # `test_build_swarm_refuses_duplicate_storage` exercises the
    # frozenset contract for storage explicitly.
    for sole in SINGLE_INSTANCE_AGENTS:
        count = sum(1 for a in build_agents() if a.name == sole)
        if sole == "storage.v1":
            assert count == 0, "storage.v1 not yet wired by build_agents()"
        else:
            assert count == 1, sole


def test_build_swarm_predict_request_reaches_predict_approved() -> None:
    """End-to-end smoke test on the in-memory bus: a single
    `predict.request` should produce exactly one
    `predict.approved.v1` (Phase-6 audit F-1 — production wiring)."""
    bus = InMemoryBus()
    registry = AgentRegistry()
    runners = build_swarm(bus, registry, tick_sec=0.001, flush_interval_sec=0.0)
    for r in runners:
        r.register()
    try:
        req = PredictRequest(
            request_id="bootstrap-req-1",
            match_id="TR1:Galatasaray-Fenerbahce",
            market="1x2",
            league_id="TR1",
            features={"home_advantage": 0.55, "home_xg": 1.7, "away_xg": 1.1},
        )
        bus.publish(Message.new(
            PREDICT_REQUEST, req.as_dict(),
            producer="test.bootstrap", trace_id="trace-bootstrap",
        ))
        _drain(runners)

        finals = bus.drain_topic(PREDICT_FINAL)
        assert len(finals) == 1, f"expected 1 predict.final, got {len(finals)}"
        approvals = bus.drain_topic(PREDICT_APPROVED)
        assert len(approvals) == 1, (
            f"expected 1 predict.approved.v1, got {len(approvals)} — "
            "the bootstrap is missing a wire."
        )
    finally:
        for r in runners:
            r.deregister()


def test_build_swarm_predict_request_lands_in_cache_backend() -> None:
    """Phase-6 second-pass audit (F2-2).

    Asserting that `predict.approved.v1` reaches the *bus* (the
    F-1 test above) is necessary but not sufficient: a missing
    `cache.v1` registration in the bootstrap means the API gateway
    has nothing to serve. This test drives one prediction end-to-end
    and confirms the `CacheAgent` backend has the approval keyed
    by `make_prediction_key`.
    """
    from swarm.agents.cache import CacheAgent, make_prediction_key

    bus = InMemoryBus()
    registry = AgentRegistry()
    runners = build_swarm(bus, registry, tick_sec=0.001, flush_interval_sec=0.0)
    cache_runners = [r for r in runners if isinstance(r.agent, CacheAgent)]
    assert len(cache_runners) == 1, (
        "build_swarm() must register exactly one CacheAgent — without "
        "it predict.approved.v1 vanishes off the bus and the API "
        "serves stale results."
    )
    cache_agent: CacheAgent = cache_runners[0].agent  # type: ignore[assignment]

    for r in runners:
        r.register()
    try:
        req = PredictRequest(
            request_id="cache-req-1",
            match_id="TR1:Galatasaray-Fenerbahce",
            market="1x2",
            league_id="TR1",
            features={"home_advantage": 0.55, "home_xg": 1.7, "away_xg": 1.1},
        )
        bus.publish(Message.new(
            PREDICT_REQUEST, req.as_dict(),
            producer="test.bootstrap.cache", trace_id="trace-cache",
        ))
        _drain(runners)

        approvals = bus.drain_topic(PREDICT_APPROVED)
        # Drain consumes the bus copy; we still need the approval id
        # to probe the cache. drain_topic does not affect what the
        # CacheAgent already consumed via its consumer group.
        assert len(approvals) == 1, "expected exactly one approval"
        approved_payload = approvals[0].payload
        key = make_prediction_key(
            approved_payload["match_id"],
            approved_payload["market"],
            approved_payload["prediction_id"],
        )
        cached = cache_agent.backend.get(key)
        assert cached is not None, (
            f"CacheAgent backend missing key {key!r} — the cache wire "
            "is broken; the Phase 9 API gateway will see no data."
        )
    finally:
        for r in runners:
            r.deregister()


# ── F-10: single-instance guard ────────────────────────────────


def test_build_swarm_refuses_duplicate_single_instance_agent() -> None:
    bus = InMemoryBus()
    registry = AgentRegistry()
    agents = build_agents()
    # Add a second drift agent — must be refused.
    agents.append(DriftAgent())
    with pytest.raises(SingleInstanceViolation, match="drift.v1"):
        build_swarm(bus, registry, agents=agents)


def test_build_swarm_refuses_duplicate_consensus() -> None:
    bus = InMemoryBus()
    registry = AgentRegistry()
    # Minimal agent set with two consensus agents.
    agents = [
        ConsensusAgent(expected_predictors=("pred.elo.v1",), ledger=InMemoryLedger()),
        ConsensusAgent(expected_predictors=("pred.elo.v1",), ledger=InMemoryLedger()),
    ]
    with pytest.raises(SingleInstanceViolation, match="consensus.v1"):
        build_swarm(bus, registry, agents=agents)


def test_build_swarm_refuses_duplicate_aggregator() -> None:
    bus = InMemoryBus()
    registry = AgentRegistry()
    agents = [
        ProofreaderAggregatorAgent(ledger=InMemoryLedger()),
        ProofreaderAggregatorAgent(ledger=InMemoryLedger()),
    ]
    with pytest.raises(SingleInstanceViolation, match="proofreader_aggregator.v1"):
        build_swarm(bus, registry, agents=agents)


def test_build_swarm_refuses_duplicate_storage() -> None:
    """Third-pass audit (M1): `storage.v1` is the canonical writer to
    `match.outcome.v1` (drift's training oracle) and `freshness.event.v1`
    (the source watcher's signal). Two replicas would double-emit
    outcomes, splitting the drift counter and triggering false retrains.
    The frozenset must reject duplicates even though `build_agents()`
    does not currently wire a StorageAgent — the contract is the
    bootstrap surface, not the default agent set."""
    from swarm.agents.storage import StorageAgent

    bus = InMemoryBus()
    registry = AgentRegistry()
    agents = [StorageAgent(), StorageAgent()]
    with pytest.raises(SingleInstanceViolation, match="storage.v1"):
        build_swarm(bus, registry, agents=agents)


# ── F-2: runner drives flush_expired ───────────────────────────


def test_runner_calls_flush_expired_for_aggregator_without_inbound_msg() -> None:
    """Phase-6 audit (F-2): the runner must tick `flush_expired` even
    when no inbound message arrives, otherwise the aggregator's
    window never closes and `no_quorum` candidates leak forever.

    We construct an aggregator with a tiny window, push a `predict.final`
    candidate, then advance the agent's clock past the window WITHOUT
    publishing more messages. After enough `step()` calls, the runner
    must invoke `flush_expired` and a `proofreader_no_quorum` flag
    must appear on the bus.
    """
    bus = InMemoryBus()
    registry = AgentRegistry()

    # Mutable monotonic-ms clock the test controls.
    now_ms = [1_000_000.0]
    agg = ProofreaderAggregatorAgent(
        ledger=InMemoryLedger(),
        clock_ms=lambda: now_ms[0],
        window_ms=50,
    )
    runner = build_swarm(
        bus, registry, agents=[agg],
        tick_sec=0.001, flush_interval_sec=0.0,
    )[0]
    runner.register()
    try:
        from swarm.agents.payloads import PredictFinal

        final = PredictFinal(
            request_id="req-flush-1",
            prediction_id="pid-flush-1",
            match_id="TR1:A-B",
            market="1x2",
            distribution={
                "market_outcomes": {"H": 0.5, "D": 0.3, "A": 0.2},
                "score_grid": None,
            },
            weights={"pred.elo.v1": 1.0},
            contributing_models=["pred.elo.v1"],
            calibration_version=0,
            swarm_confidence=0.9,
            produced_at="2026-01-01T00:00:00+00:00",
        )
        bus.publish(Message.new(
            PREDICT_FINAL, final.as_dict(),
            producer="test.flush", trace_id="trace-flush",
        ))
        # First step ingests the predict.final into _pending.
        runner.step()

        # Advance synthetic clock past the window — but publish nothing.
        now_ms[0] += 200.0
        # Several steps to give the runner a chance to tick flush.
        for _ in range(8):
            runner.step()

        flags = bus.drain_topic(PROOF_FLAG)
        kinds = [f.payload.get("kind") for f in flags]
        assert "proofreader_no_quorum" in kinds, (
            f"flush_expired tick did not fire: {kinds}"
        )
    finally:
        runner.deregister()


def test_runner_flush_interval_throttles_calls() -> None:
    """flush_expired must NOT be called every step; with
    `flush_interval_sec` > 0, calls are spaced. We assert by counting
    invocations through a wrapped agent.
    """
    bus = InMemoryBus()
    registry = AgentRegistry()
    agg = ProofreaderAggregatorAgent(ledger=InMemoryLedger())
    calls = [0]
    real_flush = agg.flush_expired

    def _counting_flush(*a, **k):
        calls[0] += 1
        return real_flush(*a, **k)

    agg.flush_expired = _counting_flush  # type: ignore[assignment]
    runner = build_swarm(
        bus, registry, agents=[agg],
        flush_interval_sec=10.0, tick_sec=0.001,
    )[0]
    runner.register()
    try:
        # Tight loop of empty steps — interval is 10s so flush should
        # be called at most once.
        for _ in range(50):
            runner.step()
        assert calls[0] <= 1, f"flush_expired called {calls[0]}× in 50 steps"
    finally:
        runner.deregister()


def test_aggregator_uses_dedicated_max_pending_knob() -> None:
    """Phase-6 audit (F-9): `proofreader_aggregator_max_pending` is the
    default cap for the aggregator's _pending map (was previously
    aliased to `consensus_max_pending`)."""
    agg = ProofreaderAggregatorAgent(ledger=InMemoryLedger())
    assert agg._max_pending == _cfg.proofreader_aggregator_max_pending


# ── F-7: market key normalisation ──────────────────────────────


def test_predict_approved_normalises_market_key_to_lowercase() -> None:
    """Phase-6 audit (F-7): `PredictApproved.__post_init__` lowercases
    the market key so a stray `"1X2"` from a future predictor does not
    silently bypass DriftAgent (which settles only on `"1x2"`)."""
    from swarm.agents.payloads import PredictApproved

    final_dict = {
        "request_id": "r1",
        "prediction_id": "pid-norm",
        "match_id": "TR1:A-B",
        "market": "1X2",
        "distribution": {"market_outcomes": {"H": 0.5, "D": 0.3, "A": 0.2}},
        "weights": {"pred.elo.v1": 1.0},
        "contributing_models": ["pred.elo.v1"],
        "calibration_version": 0,
        "swarm_confidence": 0.9,
        "produced_at": "2026-01-01T00:00:00+00:00",
    }
    approved = PredictApproved(
        request_id="r1",
        prediction_id="pid-norm",
        match_id="TR1:A-B",
        market="1X2",  # uppercase — must normalise.
        approved_at="2026-01-01T00:00:01+00:00",
        approved_by=["proofreader.sanity.v1", "proofreader.consistency.v1"],
        verdict_count=2,
        quorum=2,
        final=final_dict,
    )
    assert approved.market == "1x2"
