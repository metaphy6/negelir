"""Tests for Phase 4.5 cache + 4.6 telemetry + 4.7 reactor agents."""
from __future__ import annotations

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


# ── Reactor base ───────────────────────────────────────────────


def _freshness_msg(record_id: int = 7, plane: str = "schedule") -> Message:
    ev = FreshnessEvent(
        record_id=record_id,
        plane=plane,
        record_type="fixture",
        change_kind="created",
        diff_summary={},
    )
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
    # Side effect ran exactly once (set semantics also makes it idempotent,
    # but the ledger is what guarantees it for non-set side effects).
    assert r._ledger.already_processed(r.name, msg.envelope.message_id)


def test_reactor_drops_event_outside_plane_scope() -> None:
    r = FeatureStoreReactor()  # allowed: schedule, live
    list(r.handle(_freshness_msg(plane="market")))
    assert r.dirty_record_ids == set()


def test_reactor_back_emission_is_blocked_at_construction() -> None:
    class _Bad(ReactorBase):
        name = "bad"
        allowed_planes = ("schedule",)
        publishes = [FRESHNESS_EVENTS]

        def react(self, ev, msg):
            return ()

    with pytest.raises(ValueError, match="back-emission"):
        _Bad()


def test_cache_invalidation_reactor_invalidates_known_records() -> None:
    backend = InMemoryCacheBackend()
    backend.set(make_record_key("mackolik", "abc", "fixture"), "id=1", ttl_sec=60)

    def lookup(record_id: int):
        return ("mackolik", "abc", "fixture") if record_id == 1 else None

    r = CacheInvalidationReactor(cache=backend, store_lookup=lookup)
    ev = FreshnessEvent(record_id=1, plane="schedule", record_type="fixture",
                        change_kind="updated")
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
