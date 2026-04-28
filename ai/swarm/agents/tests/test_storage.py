"""Tests for Phase 4.4 storage agent."""
from __future__ import annotations

from swarm.agents.payloads import (
    FreshnessEvent,
    MatchStored,
    NormalizedRecord,
)
from swarm.agents.storage import InMemoryRecordStore, StorageAgent
from swarm.agents.topics import FRESHNESS_EVENTS, MATCH_STORED
from swarm.sdk.types import Message


def _record(payload=None, src_id="m1") -> NormalizedRecord:
    return NormalizedRecord(
        record_type="fixture",
        plane="schedule",
        source="mackolik",
        source_match_id=src_id,
        stable_id="stable-" + src_id,
        extractor_version="phase4.v1",
        payload=payload or {"home_team": "GS", "away_team": "FB"},
    )


def _msg(rec: NormalizedRecord) -> Message:
    return Message.new("match.normalized", rec.as_dict(), producer="test")


def test_first_upsert_emits_created_and_freshness_event() -> None:
    agent = StorageAgent()
    out = list(agent.handle(_msg(_record())))
    assert len(out) == 2
    stored = MatchStored.from_dict(out[0].payload)
    assert out[0].envelope.topic == MATCH_STORED
    assert stored.change_kind == "created"
    assert out[1].envelope.topic == FRESHNESS_EVENTS
    ev = FreshnessEvent.from_dict(out[1].payload)
    assert ev.change_kind == "created"
    assert ev.record_id == stored.record_id


def test_idempotent_repeat_emits_unchanged_no_freshness() -> None:
    agent = StorageAgent()
    list(agent.handle(_msg(_record())))
    out = list(agent.handle(_msg(_record())))
    assert len(out) == 1
    assert MatchStored.from_dict(out[0].payload).change_kind == "unchanged"


def test_payload_change_emits_updated_with_diff() -> None:
    agent = StorageAgent()
    list(agent.handle(_msg(_record(payload={"home_team": "GS", "away_team": "FB"}))))
    out = list(agent.handle(_msg(_record(payload={"home_team": "GS", "away_team": "TS"}))))
    assert len(out) == 2
    assert MatchStored.from_dict(out[0].payload).change_kind == "updated"
    ev = FreshnessEvent.from_dict(out[1].payload)
    assert ev.diff_summary == {"away_team": ["FB", "TS"]}


def test_in_memory_store_thread_safety_smoke() -> None:
    # Quick sanity (real chaos test lives in 4.8 swarm-demo).
    store = InMemoryRecordStore()
    for i in range(50):
        store.upsert(_record(src_id=f"m{i}"))
    assert len(store.all_rows()) == 50


def test_storage_malformed_payload_returns_empty() -> None:
    out = list(StorageAgent().handle(Message.new("match.normalized", {}, producer="t")))
    assert out == []
