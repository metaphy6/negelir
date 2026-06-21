"""Phase 5.5 — predictor-swarm end-to-end demo test.

Mirrors `test_phase4_swarm_demo_end_to_end`: drives the four
must-status predictors + `consensus.v1` through the production
bus + AgentRunner stack against ``InMemoryBus``. Closes ROADMAP §5.5
DoD items:

  * "must-status predictors implemented + voting against InMemoryBus"
    — wires the same bus + runner path the production agents use.
  * "every Phase 5 agent registers in `agent_registry` and shows up in
    `swarmctl ps`; every Phase 5 topic shows up in `swarmctl topics`"
    — registry assertions + bus.topics() coverage at the end.
  * "All Phase 5 messages validate against their JSON Schema at the
    live emission point" — schema validation runs on every emitted
    `predict.*` message.

The test is intentionally synchronous (``runner.step()``) so it does
not flake on timing.
"""
from __future__ import annotations

from swarm.agents.consensus import ConsensusAgent
from swarm.agents.payloads import (
    PredictFinal,
    PredictRequest,
    PredictVote,
)
from swarm.agents.predictors import (
    DixonColesPredictor,
    EloPredictor,
    XgbFormPredictor,
    XgbXgPredictor,
)
from swarm.agents.reactor import InMemoryLedger
from swarm.agents.topics import (
    PREDICT_FINAL,
    PREDICT_REQUEST,
    PREDICT_VOTE,
    PROOF_FLAG,
)
from swarm.sdk.bus import InMemoryBus
from swarm.sdk.registry import AgentRegistry
from swarm.sdk.runner import AgentRunner
from swarm.sdk.schemas import known_topics, validate
from swarm.sdk.types import Message


def _make_runner(bus, agent, *, registry):
    runner = AgentRunner(
        agent=agent,
        bus=bus,
        registry=registry,
        max_in_flight=8,
        retry_budget=3,
        tick_sec=0.001,
    )
    runner.register()
    return runner


def _drain(runners, *, max_steps: int = 64) -> None:
    for _ in range(max_steps):
        progress = False
        for r in runners:
            if r.step():
                progress = True
        if not progress:
            return
    raise AssertionError(
        "phase 5 swarm did not quiesce within max_steps; possible loop"
    )


def _build_swarm(bus, registry):
    predictors = [
        EloPredictor(clock=lambda: "2026-01-01T00:00:00+00:00"),
        DixonColesPredictor(clock=lambda: "2026-01-01T00:00:00+00:00"),
        XgbFormPredictor(clock=lambda: "2026-01-01T00:00:00+00:00"),
        XgbXgPredictor(clock=lambda: "2026-01-01T00:00:00+00:00"),
    ]
    consensus = ConsensusAgent(
        expected_predictors=tuple(p.predictor_id for p in predictors),
        ledger=InMemoryLedger(),
        clock_ms=lambda: 0.0,
        clock_iso=lambda: "2026-01-01T00:00:00+00:00",
        min_voters=2,
    )
    runners = [_make_runner(bus, p, registry=registry) for p in predictors]
    runners.append(_make_runner(bus, consensus, registry=registry))
    return runners, predictors, consensus


def _seed_request(bus) -> PredictRequest:
    req = PredictRequest(
        request_id="phase5-demo-req-1",
        match_id="TR1:Galatasaray-Fenerbahce",
        market="1x2",
        league_id="TR1",
        features={"home_advantage": 0.55, "home_xg": 1.7, "away_xg": 1.1},
    )
    bus.publish(
        Message.new(
            PREDICT_REQUEST,
            req.as_dict(),
            producer="test.phase5",
            trace_id="trace-phase5",
        )
    )
    return req


def _validate_emissions(bus) -> None:
    """Assert every emitted message satisfies its registered schema."""
    registered = set(known_topics())
    for topic in bus.topics():
        topic_str = str(topic)
        if topic_str not in registered:
            continue
        for msg in bus.drain_topic(topic_str):
            errors = validate(topic_str, msg.payload)
            assert not errors, (
                f"phase5 emitted {topic_str} payload violates schema:\n  "
                + "\n  ".join(errors)
            )


def test_phase5_predictor_swarm_end_to_end() -> None:
    bus = InMemoryBus()
    registry = AgentRegistry()
    runners, predictors, _consensus = _build_swarm(bus, registry)

    try:
        _seed_request(bus)
        _drain(runners)

        # ── One predict.final emitted, with the canonical shape ──
        finals = bus.drain_topic(PREDICT_FINAL)
        assert len(finals) == 1, f"expected 1 predict.final, got {len(finals)}"
        pf = PredictFinal.from_dict(finals[0].payload)
        assert pf.request_id == "phase5-demo-req-1"
        assert pf.prediction_id, "prediction_id must be populated"
        assert pf.market == "1x2"
        assert set(pf.distribution["market_outcomes"].keys()) == {"H", "D", "A"}
        s = sum(pf.distribution["market_outcomes"].values())
        assert 0.99 <= s <= 1.01, f"market_outcomes must sum to 1, got {s}"
        # Score grid is contributed by Dixon-Coles + xgb_xg.
        assert pf.distribution["score_grid"] is not None
        assert not pf.degraded
        # All four must-predictors voted.
        assert len(pf.contributing_models) == 4

        # ── Per-predictor votes were emitted to the bus ──
        votes = bus.drain_topic(PREDICT_VOTE)
        assert len(votes) == 4, f"expected 4 predict.vote, got {len(votes)}"
        voter_ids = {PredictVote.from_dict(v.payload).predictor_id for v in votes}
        assert voter_ids == {p.predictor_id for p in predictors}

        # ── No proof.flag (no degradation, no late votes) ──
        flags = bus.drain_topic(PROOF_FLAG)
        assert flags == [], f"unexpected proof.flag emissions: {flags}"

        # ── No DLQ leakage on any Phase 5 topic ──
        for topic in (PREDICT_REQUEST, PREDICT_VOTE, PREDICT_FINAL):
            assert bus.drain_topic(f"{topic}.dlq") == [], (
                f"unexpected DLQ items on {topic}"
            )

    finally:
        for r in runners:
            r.deregister()


def test_phase5_swarm_visible_in_registry_and_topics() -> None:
    """ROADMAP §5.5 DoD: every Phase 5 agent appears in `swarmctl ps`
    (registry), every Phase 5 topic appears in `swarmctl topics`
    (bus stream listing). The Go binary reads these surfaces verbatim
    — asserting the in-memory equivalents proves the contract holds.
    """
    bus = InMemoryBus()
    registry = AgentRegistry()
    runners, predictors, _consensus = _build_swarm(bus, registry)

    try:
        # Registry: every Phase 5 agent is registered with its
        # subscribes/publishes (the same fields swarmctl ps prints).
        specs = registry.all_specs()
        agent_names = {s.name for s in specs.values()}
        expected_names = {p.predictor_id for p in predictors} | {"consensus.v1"}
        assert expected_names.issubset(agent_names), (
            f"missing from registry: {expected_names - agent_names}"
        )
        for spec in specs.values():
            if spec.name.startswith("pred."):
                assert PREDICT_REQUEST in spec.subscribes
                assert PREDICT_VOTE in spec.publishes
            if spec.name == "consensus.v1":
                assert PREDICT_VOTE in spec.subscribes
                assert PREDICT_FINAL in spec.publishes
                assert PROOF_FLAG in spec.publishes

        # Topics: drive one request through and assert each Phase 5
        # topic shows up in `bus.topics()` (the same iteration
        # swarmctl uses to list streams).
        _seed_request(bus)
        _drain(runners)

        topic_names = {str(t) for t in bus.topics()}
        for required in (PREDICT_REQUEST, PREDICT_VOTE, PREDICT_FINAL):
            assert required in topic_names, (
                f"topic {required!r} missing from bus.topics(): {topic_names}"
            )

        # ── Schema validation at live emission point ──
        # Phase 5 payloads must satisfy their registered JSON schemas
        # at the point they hit the bus. (Drain happens inside.)
        _validate_emissions(bus)

    finally:
        for r in runners:
            r.deregister()


def test_phase5_swarm_idempotent_on_replay() -> None:
    """Re-publishing the same predict.request must not emit a second
    predict.final (single-publication contract per ROADMAP §5.2)."""
    bus = InMemoryBus()
    registry = AgentRegistry()
    runners, _predictors, _consensus = _build_swarm(bus, registry)

    try:
        req = _seed_request(bus)
        _drain(runners)
        first = bus.drain_topic(PREDICT_FINAL)
        assert len(first) == 1

        # Re-publish identical request — every predictor will re-vote,
        # consensus's ledger must drop the late publication.
        bus.publish(
            Message.new(
                PREDICT_REQUEST,
                req.as_dict(),
                producer="test.phase5.replay",
                trace_id="trace-phase5",
            )
        )
        _drain(runners)
        second = bus.drain_topic(PREDICT_FINAL)
        assert second == [], (
            f"idempotency violated: predict.final re-emitted on replay: {second}"
        )
        # The replayed votes must surface as `late_vote_dropped` flags
        # so observability can count them.
        flags = [m for m in bus.drain_topic(PROOF_FLAG)]
        assert flags, "expected late_vote_dropped flags on replay"
        for f in flags:
            assert f.payload["kind"] == "late_vote_dropped"
            assert f.payload["request_id"] == req.request_id

    finally:
        for r in runners:
            r.deregister()
