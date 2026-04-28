"""Tests for Phase 4.5 cache + 4.6 telemetry + 4.7 reactor agents."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from swarm.agents.cache import (
    CacheAgent,
    InMemoryCacheBackend,
    make_record_key,
)
from swarm.agents.payloads import (
    FreshnessEvent,
    MatchStored,
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
