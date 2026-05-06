"""Phase 8 §8.3 — `MaintBackupAgent` proof tests.

What this asserts (binding):

* Cron tick is armed on first ``flush_expired()`` and never fires
  before the cron expression matches a fresh wall clock.
* State machine ordering: ``backup_started`` →
  (``backup_verify_orphan_swept``? →) dump → verify → prune →
  ``backup_completed``. ``prune_skipped`` fires when verify fails,
  disk pressure trips, or wall clock steps backwards.
* PRUNE_ORDER discipline: ``prune_started.prune_order`` matches
  ``xops.maint.prune_order.PRUNE_ORDER`` verbatim.
* Disk-pressure refusal: free < ``max(2*last_dump, min_free_gb*GB)``
  → ``backup_completed{outcome=disk_pressure_skipped}``.
* Backwards wall-clock step > ``cfg.maint_backup_clock_step_back_alert_s``
  → ``backup_completed{outcome=skew_skipped}``.
* Safety floor: ``cfg.maint_backup_dry_run=True`` → every emit
  carries ``dry_run: true`` and ``would_delete_count`` is set on
  the prune event.
* PII erasure: ``maint.event.v1{kind=quarantine_erase}`` consumes
  through :class:`InMemoryQuarantineStore`, emits a sibling
  ``pii_erased`` notification with the originating ``request_id``,
  and pushes a ``MaintAck`` carrying ``accepted=true`` + a row
  count.
* Every emitted kind is in ``KNOWN_MAINT_EVENT_KINDS`` and
  validates against its sub-schema.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

import pytest

from common.config import cfg as _cfg

from ai.swarm.agents.maint import KNOWN_MAINT_EVENT_KINDS
from ai.swarm.agents.maint.backup import (
    InMemoryPrunerStorage,
    InMemoryQuarantineStore,
    MaintBackupAgent,
    NoopDumpExecutor,
    NoopVerifier,
    StaticDiskGauge,
)
from ai.swarm.agents.topics import MAINT_ACK, MAINT_EVENT
from ai.swarm.sdk import schemas
from ai.swarm.sdk.types import Envelope, Message
from xops.maint.prune_order import PRUNE_ORDER


UTC = timezone.utc


def _t(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


class _StubClock:
    """Test clock — wall + monotonic both driven from `set()`."""

    def __init__(self, start: datetime) -> None:
        self.now = start
        self._mono_origin_ns = int(start.timestamp() * 1e9)

    def wall(self) -> datetime:
        return self.now

    def mono_ns(self) -> int:
        return int(self.now.timestamp() * 1e9)

    def set(self, when: datetime) -> None:
        self.now = when


def _build_agent(
    *,
    clock: _StubClock,
    pruner_counts: dict[str, int] | None = None,
    verifier: NoopVerifier | None = None,
    disk_free_bytes: int = 64 * 1024 ** 3,
    disk_last_dump_bytes: int = 0,
    quarantine_seed: dict[str, int] | None = None,
) -> MaintBackupAgent:
    return MaintBackupAgent(
        dump=NoopDumpExecutor(bytes_written=4096),
        verifier=verifier or NoopVerifier(),
        pruner=InMemoryPrunerStorage(counts=dict(pruner_counts or {})),
        quarantine=InMemoryQuarantineStore(
            rows_per_client=dict(quarantine_seed or {}),
        ),
        disk=StaticDiskGauge(
            free_bytes=disk_free_bytes,
            last_dump_bytes=disk_last_dump_bytes,
        ),
        clock_iso=lambda: clock.wall().isoformat(timespec="seconds"),
        clock_wall=clock.wall,
        clock_mono_ns=clock.mono_ns,
        new_id=lambda: "fixed-id",
    )


def _kinds(msgs: Iterable[Message]) -> list[str]:
    return [(m.payload or {}).get("kind") for m in msgs]


# ── Static surface contracts ────────────────────────────────────────────


def test_agent_static_contract() -> None:
    a = _build_agent(clock=_StubClock(_t(2025, 1, 1, 2, 30)))
    assert a.name == "maint.backup.v1"
    assert MAINT_EVENT in a.subscribes
    assert MAINT_EVENT in a.publishes
    assert MAINT_ACK in a.publishes


# ── Cron arming ─────────────────────────────────────────────────────────


def test_first_flush_arms_next_fire_and_emits_nothing() -> None:
    clock = _StubClock(_t(2025, 1, 1, 2, 30))  # 2:30 AM, before 3 AM cron
    agent = _build_agent(clock=clock)
    out = list(agent.flush_expired())
    assert out == []
    # Move clock forward but still before fire — must stay silent.
    clock.set(_t(2025, 1, 1, 2, 59))
    assert list(agent.flush_expired()) == []


def test_fire_at_cron_moment_runs_full_state_machine() -> None:
    clock = _StubClock(_t(2025, 1, 1, 2, 30))
    agent = _build_agent(
        clock=clock,
        pruner_counts={"opsctl_audit": 5, "maint_audit_log": 0},
    )
    list(agent.flush_expired())  # arm
    clock.set(_t(2025, 1, 1, 3, 0))
    msgs = list(agent.flush_expired())
    seen = _kinds(msgs)
    # Order matters: started → prune_started → prune_completed → completed.
    assert seen == [
        "backup_started",
        "prune_started",
        "prune_completed",
        "backup_completed",
    ]
    completed = msgs[-1].payload
    assert completed["outcome"] == "ok"


# ── PRUNE_ORDER discipline ──────────────────────────────────────────────


def test_prune_started_pins_canonical_order() -> None:
    clock = _StubClock(_t(2025, 1, 1, 2, 30))
    agent = _build_agent(clock=clock, pruner_counts={"opsctl_audit": 1})
    list(agent.flush_expired())
    clock.set(_t(2025, 1, 1, 3, 0))
    msgs = list(agent.flush_expired())
    prune_started = next(m.payload for m in msgs if m.payload["kind"] == "prune_started")
    assert tuple(prune_started["prune_order"]) == PRUNE_ORDER


def test_prune_completed_includes_every_canonical_table() -> None:
    clock = _StubClock(_t(2025, 1, 1, 2, 30))
    agent = _build_agent(clock=clock, pruner_counts={"opsctl_audit": 2})
    list(agent.flush_expired())
    clock.set(_t(2025, 1, 1, 3, 0))
    msgs = list(agent.flush_expired())
    prune_completed = next(
        m.payload for m in msgs if m.payload["kind"] == "prune_completed"
    )
    assert set(prune_completed["deleted_per_table"].keys()) == set(PRUNE_ORDER)


# ── Verify failure → prune_skipped ──────────────────────────────────────


def test_verify_failure_skips_prune() -> None:
    clock = _StubClock(_t(2025, 1, 1, 2, 30))
    agent = _build_agent(
        clock=clock,
        verifier=NoopVerifier(fail=True),
        pruner_counts={"opsctl_audit": 99},
    )
    list(agent.flush_expired())
    clock.set(_t(2025, 1, 1, 3, 0))
    msgs = list(agent.flush_expired())
    seen = _kinds(msgs)
    assert "prune_started" not in seen
    assert "prune_skipped" in seen
    assert "backup_completed" in seen
    completed = next(m.payload for m in msgs if m.payload["kind"] == "backup_completed")
    assert completed["outcome"] == "verify_failed"


# ── Disk-pressure refusal ───────────────────────────────────────────────


def test_disk_pressure_refuses_dump() -> None:
    clock = _StubClock(_t(2025, 1, 1, 2, 30))
    # free = 1 MB, last_dump = 0; floor = max(0, 5 GB) = 5 GB → free < floor.
    agent = _build_agent(
        clock=clock,
        disk_free_bytes=1024 * 1024,
        disk_last_dump_bytes=0,
    )
    list(agent.flush_expired())
    clock.set(_t(2025, 1, 1, 3, 0))
    msgs = list(agent.flush_expired())
    completed = next(m.payload for m in msgs if m.payload["kind"] == "backup_completed")
    assert completed["outcome"] == "disk_pressure_skipped"
    skipped = next(m.payload for m in msgs if m.payload["kind"] == "prune_skipped")
    assert skipped["reason"] == "disk_pressure"


# ── Wall-clock skew detection ───────────────────────────────────────────


def test_backwards_wall_clock_step_skips_fire(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_cfg, "maint_backup_clock_step_back_alert_s", 60)
    clock = _StubClock(_t(2025, 1, 1, 2, 30))
    agent = _build_agent(clock=clock, pruner_counts={"opsctl_audit": 1})
    # First successful fire establishes _last_fire_wall.
    list(agent.flush_expired())
    clock.set(_t(2025, 1, 1, 3, 0))
    list(agent.flush_expired())  # ok run
    # Step the wall clock backwards by 10 minutes — beyond 60s threshold.
    clock.set(_t(2025, 1, 1, 2, 50))
    # The cron is armed for next 3:00 (tomorrow); we need to force a
    # fire by re-arming. Easiest: drive cron close to a fresh fire and
    # then yank the clock back AFTER arming. We re-construct a fresh
    # next-fire-at by setting clock past the arm-target and pulling
    # back: directly set the agent's _next_fire_at to "now" so the
    # backwards-step path is exercised.
    agent._next_fire_at = _t(2025, 1, 1, 2, 49)  # noqa: SLF001 — test
    msgs = list(agent.flush_expired())
    seen = _kinds(msgs)
    assert seen[0] == "backup_completed"
    completed = msgs[0].payload
    assert completed["outcome"] == "skew_skipped"
    assert any(
        m.payload["kind"] == "prune_skipped"
        and m.payload["reason"] == "skew_skipped"
        for m in msgs
    )


# ── Safety floor (dry_run) ──────────────────────────────────────────────


def test_dry_run_marks_every_event_and_emits_would_delete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_cfg, "maint_backup_dry_run", True)
    clock = _StubClock(_t(2025, 1, 1, 2, 30))
    agent = _build_agent(
        clock=clock,
        pruner_counts={"opsctl_audit": 7, "dlq_entries": 3},
    )
    list(agent.flush_expired())
    clock.set(_t(2025, 1, 1, 3, 0))
    msgs = list(agent.flush_expired())
    started = next(m.payload for m in msgs if m.payload["kind"] == "backup_started")
    assert started["dry_run"] is True
    completed = next(m.payload for m in msgs if m.payload["kind"] == "backup_completed")
    assert completed["outcome"] == "dry_run"
    assert completed["dry_run"] is True
    prune_completed = next(
        m.payload for m in msgs if m.payload["kind"] == "prune_completed"
    )
    assert prune_completed["dry_run"] is True
    assert prune_completed["would_delete_count"] == 10


# ── PII erasure (quarantine_erase consumer) ─────────────────────────────


def _make_erase_envelope(
    *, request_id: str, target: str, client_id: str = "ops@host"
) -> Message:
    env = Envelope(
        message_id="msg-001",
        trace_id="trace-001",
        topic=MAINT_EVENT,
        producer="ops_console",
        created_at="2025-01-01T12:00:00Z",
        schema_version=1,
        attempt=1,
    )
    payload = {
        "kind": "quarantine_erase",
        "target": target,
        "request_id": request_id,
        "client_id": client_id,
        "produced_at": "2025-01-01T12:00:00Z",
    }
    return Message(envelope=env, payload=payload)


def test_pii_erase_emits_pii_erased_and_ack_with_count() -> None:
    clock = _StubClock(_t(2025, 1, 1, 12, 0))
    agent = _build_agent(
        clock=clock, quarantine_seed={"user-42": 3, "user-99": 1}
    )
    msg = _make_erase_envelope(request_id="req-005", target="user-42")
    out = list(agent.handle(msg))
    kinds = [(m.payload or {}).get("kind") for m in out]
    assert kinds == ["pii_erased", None]  # second is the ack envelope
    pii = out[0].payload
    assert pii["request_id"] == "req-005"
    assert pii["client_id"] == "user-42"
    assert pii["row_count"] == 3
    assert pii["table"] == "quarantine_samples"
    ack = out[1].payload
    assert ack["accepted"] is True
    assert ack["request_id"] == "req-005"
    assert "erased 3 rows" in ack["reason"]
    assert ack["details"]["row_count"] == 3


def test_pii_erase_no_match_still_acks_accepted() -> None:
    clock = _StubClock(_t(2025, 1, 1, 12, 0))
    agent = _build_agent(clock=clock, quarantine_seed={})
    msg = _make_erase_envelope(request_id="req-006", target="ghost")
    out = list(agent.handle(msg))
    pii = out[0].payload
    assert pii["row_count"] == 0
    ack = out[1].payload
    assert ack["accepted"] is True
    assert ack["reason"] == "no rows matched"


def test_pii_erase_missing_fields_rejects() -> None:
    clock = _StubClock(_t(2025, 1, 1, 12, 0))
    agent = _build_agent(clock=clock)
    env = Envelope(
        message_id="msg-002",
        trace_id="trace-002",
        topic=MAINT_EVENT,
        producer="ops_console",
        created_at="2025-01-01T12:00:00Z",
        schema_version=1,
        attempt=1,
    )
    bad = Message(envelope=env, payload={"kind": "quarantine_erase"})
    out = list(agent.handle(bad))
    # Single ack envelope with accepted=false (no pii_erased emit).
    assert len(out) == 1
    assert out[0].payload["accepted"] is False


def test_handle_ignores_unrelated_kinds() -> None:
    clock = _StubClock(_t(2025, 1, 1, 12, 0))
    agent = _build_agent(clock=clock)
    env = Envelope(
        message_id="msg-003",
        trace_id="trace-003",
        topic=MAINT_EVENT,
        producer="maint.scaler.v1",
        created_at="2025-01-01T12:00:00Z",
        schema_version=1,
        attempt=1,
    )
    other = Message(envelope=env, payload={"kind": "scale_decision"})
    assert list(agent.handle(other)) == []


# ── Schema validation of every emit ─────────────────────────────────────


def test_every_emitted_kind_validates_against_sub_schema() -> None:
    """Run a full-fire + a PII-erase and validate every notification
    emit against `schemas.validate_kind`."""
    clock = _StubClock(_t(2025, 1, 1, 2, 30))
    agent = _build_agent(
        clock=clock,
        pruner_counts={"opsctl_audit": 1},
        quarantine_seed={"user-1": 2},
        verifier=NoopVerifier(orphans=("verify_2024_12_31",)),
    )
    list(agent.flush_expired())  # arm
    clock.set(_t(2025, 1, 1, 3, 0))
    fire_msgs = list(agent.flush_expired())
    erase_msgs = list(
        agent.handle(_make_erase_envelope(request_id="req-1", target="user-1"))
    )
    notification_msgs = [
        m
        for m in fire_msgs + erase_msgs
        if m.envelope.topic == MAINT_EVENT
    ]
    assert notification_msgs, "no notification messages produced"
    for m in notification_msgs:
        kind = m.payload["kind"]
        assert kind in KNOWN_MAINT_EVENT_KINDS, kind
        errors = schemas.validate_kind(MAINT_EVENT, m.payload)
        assert errors == [], f"kind={kind}: {errors}"


# ── Bootstrap wiring ───────────────────────────────────────────────────


def test_bootstrap_includes_backup_agent() -> None:
    from ai.swarm.bootstrap import SINGLE_INSTANCE_AGENTS, build_agents

    names = {a.name for a in build_agents()}
    assert "maint.backup.v1" in names
    assert "maint.backup.v1" in SINGLE_INSTANCE_AGENTS
