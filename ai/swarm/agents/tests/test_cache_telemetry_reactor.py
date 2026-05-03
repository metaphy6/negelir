"""Tests for Phase 4.5 cache + 4.6 telemetry + 4.7 reactor agents."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from swarm.agents.cache import (
    CacheAgent,
    InMemoryCacheBackend,
    make_prediction_key,
    make_record_key,
)
from swarm.agents.payloads import (
    FreshnessEvent,
    MatchStored,
    PredictApproved,
    PredictFinal,
    derive_prediction_id,
)
from swarm.agents.reactor import (
    CacheInvalidationReactor,
    FeatureStoreReactor,
    InMemoryLedger,
    ReactorBase,
)
from swarm.agents.telemetry import TelemetryAgent, WATCHED_TOPICS
from swarm.agents.topics import (
    FRESHNESS_EVENTS,
    MATCH_STORED,
    PREDICT_APPROVED,
    SCRAPE_REQUEST,
)
from swarm.sdk.types import Message


# ── Cache ───────────────────────────────────────────────────────


def _stored(change_kind: str = "created") -> Message:
    payload = MatchStored(
        record_id=42,
        record_type="fixture",
        plane="schedule",
        source="mackolik",
        stable_id="abc123",
        change_kind=change_kind,
        stored_at="2025-01-01T00:00:00+00:00",
    )
    return Message.new(MATCH_STORED, payload.as_dict(), producer="t")


def test_cache_agent_writes_on_created() -> None:
    backend = InMemoryCacheBackend()
    agent = CacheAgent(backend=backend)
    out = list(agent.handle(_stored("created")))
    assert out == []
    assert backend.get(make_record_key("mackolik", "abc123", "fixture")) == "id=42"


def test_cache_agent_skips_unchanged() -> None:
    backend = InMemoryCacheBackend()
    agent = CacheAgent(backend=backend)
    list(agent.handle(_stored("unchanged")))
    assert len(backend) == 0


# ── Cache: predict.approved.v1 (Wave A.1) ──────────────────────


def _approved_msg(prediction_id: str = "pid-1") -> Message:
    final = PredictFinal(
        request_id="req-1",
        prediction_id=prediction_id,
        match_id="match-abc",
        market="1x2",
        distribution={
            "market_outcomes": {"H": 0.5, "D": 0.25, "A": 0.25},
            "score_grid": None,
        },
        weights={"pred.elo.v1": 1.0},
        contributing_models=["pred.elo.v1"],
        calibration_version=1,
        swarm_confidence=0.65,
        produced_at="2026-04-28T12:00:02+00:00",
        league_id="tr_super_lig",
        profile_id="tr_super_lig",
    ).as_dict()
    approved = PredictApproved(
        request_id=final["request_id"],
        prediction_id=final["prediction_id"],
        match_id=final["match_id"],
        market=final["market"],
        approved_at="2026-04-28T12:00:04+00:00",
        approved_by=["proof.sanity.v1", "proof.consistency.v1"],
        verdict_count=3,
        quorum=2,
        final=final,
        calibration_version=int(final["calibration_version"]),
    )
    return Message.new(PREDICT_APPROVED, approved.as_dict(), producer="t")


def test_cache_agent_writes_prediction_on_approved() -> None:
    backend = InMemoryCacheBackend()
    agent = CacheAgent(backend=backend)
    list(agent.handle(_approved_msg(prediction_id="pid-xyz")))
    key = make_prediction_key("match-abc", "1x2", "pid-xyz")
    cached = backend.get(key)
    assert cached is not None
    # The full predict.final payload must be retrievable verbatim.
    import json
    decoded = json.loads(cached)
    assert decoded["prediction_id"] == "pid-xyz"
    assert decoded["distribution"]["market_outcomes"] == {
        "H": 0.5, "D": 0.25, "A": 0.25
    }


def test_cache_agent_uses_prediction_ttl_for_approved(monkeypatch) -> None:
    """The cache must read `cfg.cache_prediction_ttl_sec`, not
    `cache_record_ttl_sec`. Override the cfg value and assert the
    backend.set call carried it through.
    """
    from common.config import cfg as _cfg

    seen: list[int] = []

    class _RecordingBackend:
        def set(self, key: str, value: str, *, ttl_sec: int) -> None:
            seen.append(ttl_sec)

        def get(self, key: str) -> str | None:
            return None

        def invalidate(self, key: str) -> None:
            pass

    monkeypatch.setattr(_cfg, "cache_prediction_ttl_sec", 777)
    agent = CacheAgent(backend=_RecordingBackend())
    list(agent.handle(_approved_msg()))
    assert seen == [777], (
        f"cache.v1 must use cache_prediction_ttl_sec for predict.approved.v1; "
        f"got ttl={seen}"
    )


def test_cache_agent_drops_malformed_approved(caplog) -> None:
    backend = InMemoryCacheBackend()
    agent = CacheAgent(backend=backend)
    bad = Message.new(PREDICT_APPROVED, {"not": "valid"}, producer="t")
    out = list(agent.handle(bad))
    assert out == []
    assert len(backend) == 0


# ── Telemetry ──────────────────────────────────────────────────


def test_telemetry_observes_topic_count() -> None:
    agent = TelemetryAgent()
    msg = Message.new(SCRAPE_REQUEST, {"hello": 1}, producer="t")
    list(agent.handle(msg))
    list(agent.handle(msg))
    text = agent.counters.render_prometheus()
    assert "scrape.request" in text
    assert "negelir_bus_messages_total" in text


def test_telemetry_subscribes_all_phase4_topics() -> None:
    agent = TelemetryAgent()
    assert set(agent.subscribes) == set(WATCHED_TOPICS)


def test_telemetry_watches_phase5_predictor_topics() -> None:
    """Phase 5 added 4 new topics (predict.request/vote/final + models.events.v1).
    Telemetry is the single observability surface; missing them meant
    the predictor swarm flowed past the Prometheus page silently.
    """
    agent = TelemetryAgent()
    subs = set(str(t) for t in agent.subscribes)
    assert "predict.request" in subs
    assert "predict.vote" in subs
    assert "predict.final" in subs
    assert "models.events.v1" in subs


def test_telemetry_watches_predict_approved() -> None:
    """Phase 6 (Wave A.1): the user-visible predict.approved.v1 topic
    must appear in the observability surface."""
    agent = TelemetryAgent()
    subs = set(str(t) for t in agent.subscribes)
    assert "predict.approved.v1" in subs


def test_telemetry_watches_phase6_proofreader_drift_topics() -> None:
    """Phase 6 (Wave A.2/A.3) — close §6.5 telemetry follow-up.

    Without these the proofreader gauntlet (per-replica verdicts) and
    the drift agent (retrain emissions and the match outcomes it
    consumes) flowed past Prometheus silently, so any quorum stall
    or runaway drift would only surface in agent logs.
    """
    agent = TelemetryAgent()
    subs = set(str(t) for t in agent.subscribes)
    assert "predict.proofreader_verdict.v1" in subs
    assert "maint.event.v1" in subs
    assert "match.outcome.v1" in subs


def test_telemetry_watches_phase7_defense_topics() -> None:
    """Phase 7 foundation — the defense-agent wire surface (qa.request,
    qa.request.v1, sec.alert.v1, sec.quarantine.v1, sec.denylist.v1)
    must be observable from day-1, before §7.1/§7.2/§7.3 producers turn
    on. Missing topics here would mean a production rollout of the
    defense agents silently bypasses the Prometheus page, defeating
    the whole point of the §7.4 alert envelope."""
    agent = TelemetryAgent()
    subs = set(str(t) for t in agent.subscribes)
    assert "qa.request" in subs
    assert "qa.request.v1" in subs
    assert "sec.alert.v1" in subs
    assert "sec.quarantine.v1" in subs
    assert "sec.denylist.v1" in subs


# ── Reactor base ───────────────────────────────────────────────


def _make_freshness_event(
    *,
    record_id: int = 7,
    plane: str = "schedule",
    source: str = "mackolik",
    stable_id: str = "abc123",
    record_type: str = "fixture",
    change_kind: str = "created",
    diff: dict | None = None,
) -> FreshnessEvent:
    diff = {} if diff is None else diff
    event_id = FreshnessEvent.derive_event_id(
        source=source,
        stable_id=stable_id,
        record_type=record_type,
        change_kind=change_kind,
        diff=diff,
    )
    return FreshnessEvent(
        event_id=event_id,
        record_id=record_id,
        source=source,
        stable_id=stable_id,
        record_type=record_type,
        plane=plane,
        change_kind=change_kind,
        diff=diff,
        emitted_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )


def _freshness_msg(record_id: int = 7, plane: str = "schedule") -> Message:
    ev = _make_freshness_event(record_id=record_id, plane=plane)
    return Message.new(FRESHNESS_EVENTS, ev.as_dict(), producer="t")


def test_feature_store_reactor_marks_dirty() -> None:
    r = FeatureStoreReactor()
    list(r.handle(_freshness_msg(record_id=99)))
    assert 99 in r.dirty_record_ids


def test_reactor_idempotent_on_event_id() -> None:
    r = FeatureStoreReactor()
    msg = _freshness_msg(record_id=7)
    list(r.handle(msg))
    list(r.handle(msg))  # same envelope.message_id
    # Side effect ran exactly once. The ledger key is the *content-derived*
    # event_id, not envelope.message_id, so identity holds across replays
    # too — see `test_reactor_idempotent_on_logical_replay` below.
    ev = FreshnessEvent.from_dict(msg.payload)
    assert r._ledger.already_processed(r.name, ev.event_id)


def test_reactor_idempotent_on_logical_replay() -> None:
    """Two distinct envelopes carrying the same event content must
    only trigger the side effect once. This is the CONTENT_FRESHNESS
    §15.2 contract: idempotency is keyed on the producer-derived
    event_id, not on the bus envelope id (which is fresh per send)."""
    r = FeatureStoreReactor()
    ev = _make_freshness_event(record_id=42)
    msg_a = Message.new(FRESHNESS_EVENTS, ev.as_dict(), producer="storage-a")
    msg_b = Message.new(FRESHNESS_EVENTS, ev.as_dict(), producer="storage-b")
    assert msg_a.envelope.message_id != msg_b.envelope.message_id
    list(r.handle(msg_a))
    list(r.handle(msg_b))
    # Side effect is a set, so this is also self-idempotent — the test
    # is documenting the *contract*, not the lucky data structure.
    assert r.dirty_record_ids == {42}


def test_reactor_drops_event_outside_plane_scope() -> None:
    r = FeatureStoreReactor()  # allowed: schedule, live
    list(r.handle(_freshness_msg(plane="market")))
    assert r.dirty_record_ids == set()


def test_reactor_back_emission_is_blocked_at_construction() -> None:
    class _Bad(ReactorBase):
        name = "bad"
        allowed_planes = ("schedule",)
        publishes = (FRESHNESS_EVENTS,)

        def react(self, ev, msg):
            return ()

    with pytest.raises(ValueError, match="back-emission"):
        _Bad()


def test_cache_invalidation_reactor_invalidates_known_records() -> None:
    backend = InMemoryCacheBackend()
    backend.set(make_record_key("mackolik", "abc", "fixture"), "id=1", ttl_sec=60)

    r = CacheInvalidationReactor(cache=backend)
    ev = _make_freshness_event(
        record_id=1,
        source="mackolik",
        stable_id="abc",
        record_type="fixture",
        change_kind="updated",
    )
    msg = Message.new(FRESHNESS_EVENTS, ev.as_dict(), producer="t")
    list(r.handle(msg))
    assert backend.get(make_record_key("mackolik", "abc", "fixture")) is None


def test_in_memory_ledger_is_thread_safe_smoke() -> None:
    ledger = InMemoryLedger()
    for i in range(100):
        ledger.mark_processed("r", f"e{i}")
    for i in range(100):
        assert ledger.already_processed("r", f"e{i}")
    assert not ledger.already_processed("r", "missing")


def test_reactor_does_not_mark_when_react_raises() -> None:
    """Regression for the mark-before-side-effect foot-gun.

    If `react()` raises (transient DB blip, network failure), the bus
    runner re-delivers. The retry MUST be allowed to succeed — the
    previous mark-before behavior would short-circuit on the second
    delivery and silently drop the side effect entirely.
    """
    from swarm.agents.reactor import ReactorBase

    calls = {"n": 0}

    class _Flaky(ReactorBase):
        name = "reactor.flaky"
        allowed_planes = ("schedule",)

        def react(self, ev, msg):  # noqa: D401
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("boom")
            return ()

    r = _Flaky()
    msg = _freshness_msg(record_id=11)

    with pytest.raises(RuntimeError):
        list(r.handle(msg))
    # Ledger must be empty so the redelivery actually runs.
    ev = FreshnessEvent.from_dict(msg.payload)
    assert not r._ledger.already_processed(r.name, ev.event_id)

    # Second delivery — succeeds, then marks.
    list(r.handle(msg))
    assert calls["n"] == 2
    assert r._ledger.already_processed(r.name, ev.event_id)

    # Third delivery — short-circuited by the ledger.
    list(r.handle(msg))
    assert calls["n"] == 2
