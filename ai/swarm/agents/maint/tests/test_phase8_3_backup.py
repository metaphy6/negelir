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


# ── Per-table TTL prune notifications (§8.3 binding) ────────────────────


def test_quarantine_pruned_emits_with_ttl_days_when_rows_dropped() -> None:
    """§8.3 binding: when the prune phase removes
    ``quarantine_samples`` rows, the agent emits
    ``maint.event.v1{kind=quarantine_pruned}`` with the deleted row
    count and the configured TTL — separate from the aggregate
    ``prune_completed`` so dashboards / GDPR audits can hook
    table-scoped retention directly."""

    clock = _StubClock(_t(2025, 1, 1, 2, 30))
    agent = _build_agent(
        clock=clock,
        pruner_counts={"quarantine_samples": 7, "opsctl_audit": 1},
    )
    list(agent.flush_expired())
    clock.set(_t(2025, 1, 1, 3, 0))
    msgs = list(agent.flush_expired())
    payload = next(
        m.payload for m in msgs if m.payload["kind"] == "quarantine_pruned"
    )
    assert payload["row_count"] == 7
    assert payload["ttl_days"] == int(_cfg.sec_quarantine_ttl_days)
    assert payload["fire_window_id"]
    assert payload["dry_run"] is False


def test_pattern_allowlist_expired_emits_count_when_rows_dropped() -> None:
    """§8.3 binding: when the prune phase drops expired
    ``pattern_allowlist`` rows, the agent emits
    ``maint.event.v1{kind=pattern_allowlist_expired}`` with the
    deleted count and ``reason='ttl'``."""

    clock = _StubClock(_t(2025, 1, 1, 2, 30))
    agent = _build_agent(
        clock=clock,
        pruner_counts={"pattern_allowlist": 4},
    )
    list(agent.flush_expired())
    clock.set(_t(2025, 1, 1, 3, 0))
    msgs = list(agent.flush_expired())
    payload = next(
        m.payload for m in msgs
        if m.payload["kind"] == "pattern_allowlist_expired"
    )
    assert payload["count"] == 4
    assert payload["reason"] == "ttl"
    assert payload["fire_window_id"]


def test_no_per_table_notifications_when_nothing_pruned() -> None:
    """§8.3 binding: per-table TTL notifications are silent on the
    no-op path (an empty pruner produces ``prune_completed`` with
    all-zero counts but no ``quarantine_pruned`` /
    ``pattern_allowlist_expired`` events)."""

    clock = _StubClock(_t(2025, 1, 1, 2, 30))
    agent = _build_agent(clock=clock, pruner_counts={})
    list(agent.flush_expired())
    clock.set(_t(2025, 1, 1, 3, 0))
    msgs = list(agent.flush_expired())
    seen = _kinds(msgs)
    assert "prune_completed" in seen
    assert "quarantine_pruned" not in seen
    assert "pattern_allowlist_expired" not in seen


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


def test_verify_failure_emits_critical_sec_alert() -> None:
    """§8.3 binding: on restore-verify failure, emit
    ``sec.alert.v1{kind=backup_verify_failed, severity=critical}``
    so the operator pages. The alert must carry source =
    ``maint.backup.v1`` and reference the failing fire_window_id as
    its subject; severity ``critical`` bypasses the §7.4
    SecAlertDebouncer per the default-bypass rule.
    """

    clock = _StubClock(_t(2025, 1, 1, 2, 30))
    agent = _build_agent(clock=clock, verifier=NoopVerifier(fail=True))
    list(agent.flush_expired())
    clock.set(_t(2025, 1, 1, 3, 0))
    msgs = list(agent.flush_expired())
    alerts = [m for m in msgs if m.envelope.topic == "sec.alert.v1"]
    assert len(alerts) == 1, "exactly one sec.alert per verify-fail"
    a = alerts[0].payload
    assert a["kind"] == "backup_verify_failed"
    assert a["severity"] == "critical"
    assert a["source"] == "maint.backup.v1"
    assert a["subject"]  # fire_window_id, opaque to this assertion
    # The completed event must reference the (absent) quarantined dir.
    completed = next(
        m.payload for m in msgs if m.payload["kind"] == "backup_completed"
    )
    assert completed["outcome"] == "verify_failed"
    # In-memory shim path writes no dump dir, so quarantined_dir is None.
    assert completed["quarantined_dir"] is None


def test_verify_failure_quarantines_existing_dump_dir(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§8.3 binding: when a real dump dir exists at
    ``<backup_dir>/<safe_window>/`` and verify fails, the agent
    renames it to ``<safe_window>.failed/`` so the next nightly cron
    does not see it as today's success and the disk-usage guard
    still accounts for the on-disk bytes."""

    monkeypatch.setattr(_cfg, "maint_backup_dir", str(tmp_path))
    clock = _StubClock(_t(2025, 1, 1, 2, 30))
    agent = _build_agent(clock=clock, verifier=NoopVerifier(fail=True))
    list(agent.flush_expired())  # arm
    clock.set(_t(2025, 1, 1, 3, 0))

    # Pre-create the per-window dir keyed by the agent's pod_instance_id
    # + the current fire wall ISO; the in-memory NoopDumpExecutor does
    # NOT write a dir, so this stand-in mimics what
    # LocalPgDumpExecutor would have produced. Quarantine then renames
    # it on verify-fail.
    fire_window_id = f"{agent._pod_instance_id}:{clock.wall().isoformat()}"  # noqa: SLF001
    safe_window = fire_window_id.replace(":", "_").replace("/", "_")
    window_dir = tmp_path / safe_window
    window_dir.mkdir(parents=True)
    (window_dir / "evidence.txt").write_text("partial dump")

    msgs = list(agent.flush_expired())
    completed = next(
        m.payload for m in msgs if m.payload["kind"] == "backup_completed"
    )
    assert completed["outcome"] == "verify_failed"
    assert completed["quarantined_dir"] == safe_window + ".failed"
    assert not window_dir.exists()
    failed_dir = tmp_path / (safe_window + ".failed")
    assert failed_dir.is_dir()
    assert (failed_dir / "evidence.txt").read_text() == "partial dump"


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
    # §8.3 disk-usage guard: a `sec.alert.v1{kind=backup_disk_pressure,
    # severity=error}` MUST be emitted alongside the skip — operator
    # paging signal, debounced by §7.4.
    alerts = [m for m in msgs if m.envelope.topic == "sec.alert.v1"]
    disk_alerts = [a for a in alerts if a.payload["kind"] == "backup_disk_pressure"]
    assert len(disk_alerts) == 1
    alert = disk_alerts[0]
    assert alert.payload["severity"] == "error"
    assert alert.payload["source"] == "maint.backup.v1"
    assert "free" in alert.payload["reason"] and "floor" in alert.payload["reason"]


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
    # Backwards-skew path emits sec.alert.v1{backup_clock_skew, error}
    # FIRST so operators see the cause of the skip; then the
    # bus-level backup_completed{skew_skipped} + prune_skipped pair.
    seen = _kinds(msgs)
    assert seen[0] == "backup_clock_skew"
    assert msgs[0].envelope.topic == "sec.alert.v1"
    assert msgs[0].payload["severity"] == "error"
    assert msgs[0].payload["source"] == "maint.backup.v1"
    completed = next(
        m.payload for m in msgs if m.payload["kind"] == "backup_completed"
    )
    assert completed["outcome"] == "skew_skipped"
    assert any(
        m.payload["kind"] == "prune_skipped"
        and m.payload["reason"] == "skew_skipped"
        for m in msgs
    )


# ── Forward-leap detection ──────────────────────────────────────────────


def test_forward_wall_clock_leap_flags_backup_started(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Forward leap > cfg.maint_backup_clock_step_forward_alert_h is
    operator-visibility only — the catch-up policy still owns the
    missed window. The marker must surface as `forward_leap_h` on
    the next `backup_started` event so it is discoverable in the
    audit ledger (binding §8.3 prose: `scope=forward`)."""
    monkeypatch.setattr(_cfg, "maint_backup_clock_step_forward_alert_h", 24)
    monkeypatch.setattr(_cfg, "maint_backup_max_skew_h", 36)
    clock = _StubClock(_t(2025, 1, 1, 2, 30))
    agent = _build_agent(clock=clock, pruner_counts={"opsctl_audit": 1})
    # Arm + first successful fire establishes _last_fire_wall.
    list(agent.flush_expired())
    clock.set(_t(2025, 1, 1, 3, 0))
    first = list(agent.flush_expired())
    started_first = next(m.payload for m in first if m.payload["kind"] == "backup_started")
    assert started_first["forward_leap_h"] is None  # adjacent fire — no leap

    # Force a forward leap by ~30h (above 24h threshold, below 36h
    # catch-up so we exercise leap detection independently of catch-up).
    clock.set(_t(2025, 1, 2, 9, 0))
    agent._next_fire_at = _t(2025, 1, 2, 8, 59)  # noqa: SLF001 — test
    leaped = list(agent.flush_expired())
    started = next(m.payload for m in leaped if m.payload["kind"] == "backup_started")
    assert started["forward_leap_h"] is not None
    assert started["forward_leap_h"] > 24.0
    # Catch-up policy is NOT triggered (delta < max_skew_h=36).
    assert started["catch_up"] is False


def test_forward_wall_clock_small_step_does_not_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A normal cron-cadence forward step (<= threshold) MUST leave
    `forward_leap_h` null — the marker is reserved for actual leaps."""
    monkeypatch.setattr(_cfg, "maint_backup_clock_step_forward_alert_h", 24)
    clock = _StubClock(_t(2025, 1, 1, 2, 30))
    agent = _build_agent(clock=clock, pruner_counts={"opsctl_audit": 1})
    list(agent.flush_expired())
    clock.set(_t(2025, 1, 1, 3, 0))
    list(agent.flush_expired())
    # Next nightly cadence (~24h later, exactly at threshold — strictly-greater
    # comparison means this is NOT flagged).
    clock.set(_t(2025, 1, 2, 3, 0))
    agent._next_fire_at = _t(2025, 1, 2, 2, 59)  # noqa: SLF001 — test
    msgs = list(agent.flush_expired())
    started = next(m.payload for m in msgs if m.payload["kind"] == "backup_started")
    assert started["forward_leap_h"] is None


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


# ── Verify-mode escape hatch (ROADMAP §8.3) ─────────────────────────────


def test_verify_mode_default_full_propagates_to_verifier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`cfg.maint_backup_verify_mode` defaults to ``"full"`` and the
    agent passes that mode to ``RestoreVerifier.verify``; the value
    surfaces on ``backup_completed.verify_mode`` for operator
    visibility."""
    monkeypatch.setattr(_cfg, "maint_backup_verify_mode", "full")
    clock = _StubClock(_t(2025, 1, 1, 2, 30))
    verifier = NoopVerifier()
    agent = _build_agent(clock=clock, verifier=verifier)
    list(agent.flush_expired())  # arm
    clock.set(_t(2025, 1, 1, 3, 0))
    msgs = list(agent.flush_expired())
    completed = next(
        m.payload for m in msgs if m.payload["kind"] == "backup_completed"
    )
    assert completed["verify_mode"] == "full"
    assert verifier.last_mode == "full"


def test_verify_mode_toc_only_passes_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`cfg.maint_backup_verify_mode='toc_only'` is the §8.3 escape
    hatch: the agent passes ``mode='toc_only'`` to the verifier and
    surfaces it on the completed event so dashboards can flag the
    downgraded run."""
    monkeypatch.setattr(_cfg, "maint_backup_verify_mode", "toc_only")
    clock = _StubClock(_t(2025, 1, 1, 2, 30))
    verifier = NoopVerifier()
    agent = _build_agent(clock=clock, verifier=verifier)
    list(agent.flush_expired())  # arm
    clock.set(_t(2025, 1, 1, 3, 0))
    msgs = list(agent.flush_expired())
    completed = next(
        m.payload for m in msgs if m.payload["kind"] == "backup_completed"
    )
    assert completed["outcome"] == "ok"
    assert completed["verify_mode"] == "toc_only"
    assert verifier.last_mode == "toc_only"
    # NoopVerifier returns the toc-only sentinel summary; the agent
    # must surface it verbatim (no synthesis).
    assert completed["verify_summary"].get("_toc_only") == 1


def test_verify_mode_invalid_value_refuses_boot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Any value outside ``VALID_VERIFY_MODES`` refuses the agent at
    construction time \u2014 a typo cannot silently downgrade the
    nightly verify."""
    from ai.swarm.agents.maint.backup import BackupConfigError

    monkeypatch.setattr(_cfg, "maint_backup_verify_mode", "row_count_only")
    clock = _StubClock(_t(2025, 1, 1, 2, 30))
    with pytest.raises(BackupConfigError, match="maint_backup_verify_mode"):
        _build_agent(clock=clock)


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


# ── Audit ledger persistence + boot replay ─────────────────────────────


def test_audit_csv_records_every_fire(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every fire \u2014 ok, skew_skipped, disk_pressure, verify_failed \u2014
    appends a single row to ``cfg.maint_backup_dir/audit.csv`` with
    both ``wall_clock_utc`` and ``monotonic_ns_at_fire`` populated
    (binding \u00a78.3 Scheduler prose)."""
    import csv as _csv

    monkeypatch.setattr(_cfg, "maint_backup_dir", str(tmp_path))
    clock = _StubClock(_t(2025, 1, 1, 2, 30))
    agent = _build_agent(clock=clock, pruner_counts={"opsctl_audit": 1})
    list(agent.flush_expired())  # arm
    clock.set(_t(2025, 1, 1, 3, 0))
    list(agent.flush_expired())  # ok run

    audit_path = tmp_path / "audit.csv"
    assert audit_path.exists()
    rows = list(_csv.DictReader(audit_path.open()))
    assert len(rows) == 1
    row = rows[0]
    assert row["outcome"] == "ok"
    assert row["verified"] == "1"
    assert row["wall_clock_utc"].startswith("2025-01-01T03:00:00")
    assert int(row["monotonic_ns_at_fire"]) > 0
    assert row["fire_window_id"]
    # File mode must be 0o600 per \u00a78.3 binding contract (umask 0o077
    # plus the explicit ``os.open`` flag in :func:`append_row`).
    assert (audit_path.stat().st_mode & 0o777) == 0o600


def test_audit_replay_seeds_last_completed_so_no_double_fire(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A restart-mid-day must NOT re-fire today's dump. Boot replay
    of ``audit.csv`` re-seeds ``_last_completed_wall`` /
    ``_last_verified_wall`` so :meth:`backup_age_hours` returns a
    sensible value and the catch-up policy sees today's dump as
    already done (binding idempotency on
    ``(job_id, backup_date_utc)``)."""
    monkeypatch.setattr(_cfg, "maint_backup_dir", str(tmp_path))
    monkeypatch.setattr(_cfg, "maint_backup_max_skew_h", 36)
    # First agent fires once at 03:00 then "crashes".
    clock = _StubClock(_t(2025, 1, 1, 2, 30))
    agent_a = _build_agent(clock=clock, pruner_counts={"opsctl_audit": 1})
    list(agent_a.flush_expired())
    clock.set(_t(2025, 1, 1, 3, 0))
    list(agent_a.flush_expired())
    # New agent boots later the same day, sharing the same audit.csv.
    clock_b = _StubClock(_t(2025, 1, 1, 12, 0))
    agent_b = _build_agent(clock=clock_b, pruner_counts={"opsctl_audit": 1})
    # Boot replay should have seeded the verified anchor.
    age = agent_b.backup_age_hours(verified=True)
    assert age is not None
    # ~9h between 03:00 and 12:00 \u2014 within reasonable rounding.
    assert 8.0 < age < 10.0


# ── sec.alert.v1 emissions on skew / late catch-up ─────────────────────


def test_forward_leap_emits_sec_alert_warn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Forward leap above
    ``cfg.maint_backup_clock_step_forward_alert_h`` emits
    ``sec.alert.v1{kind=backup_clock_skew, severity=warn}`` so the
    leap is operator-visible (binding \u00a78.3 prose)."""
    monkeypatch.setattr(_cfg, "maint_backup_clock_step_forward_alert_h", 24)
    monkeypatch.setattr(_cfg, "maint_backup_max_skew_h", 36)
    clock = _StubClock(_t(2025, 1, 1, 2, 30))
    agent = _build_agent(clock=clock, pruner_counts={"opsctl_audit": 1})
    list(agent.flush_expired())
    clock.set(_t(2025, 1, 1, 3, 0))
    list(agent.flush_expired())
    clock.set(_t(2025, 1, 2, 9, 0))
    agent._next_fire_at = _t(2025, 1, 2, 8, 59)  # noqa: SLF001 \u2014 test
    msgs = list(agent.flush_expired())
    alerts = [m for m in msgs if m.envelope.topic == "sec.alert.v1"]
    assert any(
        a.payload["kind"] == "backup_clock_skew"
        and a.payload["severity"] == "warn"
        and a.payload["source"] == "maint.backup.v1"
        for a in alerts
    )


def test_late_catch_up_emits_backup_age_alert_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Make-up run more than ``cfg.maint_backup_max_skew_h`` late
    emits ``sec.alert.v1{kind=backup_age_alert, severity=error}``
    AND still fires the dump (binding \u00a78.3 prose)."""
    monkeypatch.setattr(_cfg, "maint_backup_max_skew_h", 36)
    monkeypatch.setattr(_cfg, "maint_backup_clock_step_forward_alert_h", 240)
    clock = _StubClock(_t(2025, 1, 1, 2, 30))
    agent = _build_agent(clock=clock, pruner_counts={"opsctl_audit": 1})
    list(agent.flush_expired())
    clock.set(_t(2025, 1, 1, 3, 0))
    list(agent.flush_expired())
    # ~50h later \u2014 above 36h max_skew_h, triggers catch-up + late alert.
    clock.set(_t(2025, 1, 3, 5, 0))
    agent._next_fire_at = _t(2025, 1, 3, 4, 59)  # noqa: SLF001 \u2014 test
    msgs = list(agent.flush_expired())
    alerts = [m for m in msgs if m.envelope.topic == "sec.alert.v1"]
    assert any(
        a.payload["kind"] == "backup_age_alert"
        and a.payload["severity"] == "error"
        and a.payload["source"] == "maint.backup.v1"
        for a in alerts
    )
    started = next(m.payload for m in msgs if m.payload["kind"] == "backup_started")
    assert started["catch_up"] is True
    # The dump still fires \u2014 backup_completed{ok} appears.
    assert any(
        m.payload["kind"] == "backup_completed"
        and m.payload["outcome"] in ("ok", "dry_run")
        for m in msgs
    )


def test_sec_alert_payloads_validate_against_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every ``sec.alert.v1`` envelope the backup agent emits must
    validate against ``ai/swarm/sdk/schemas/sec.alert.v1.json`` \u2014
    catches a stale ``source`` enum or a missing field at producer
    time, not just at consumer time."""
    from ai.swarm.agents.topics import SEC_ALERT

    monkeypatch.setattr(_cfg, "maint_backup_clock_step_back_alert_s", 60)
    clock = _StubClock(_t(2025, 1, 1, 2, 30))
    agent = _build_agent(clock=clock, pruner_counts={"opsctl_audit": 1})
    list(agent.flush_expired())
    clock.set(_t(2025, 1, 1, 3, 0))
    list(agent.flush_expired())
    clock.set(_t(2025, 1, 1, 2, 50))
    agent._next_fire_at = _t(2025, 1, 1, 2, 49)  # noqa: SLF001 \u2014 test
    msgs = list(agent.flush_expired())
    alerts = [m for m in msgs if m.envelope.topic == SEC_ALERT]
    assert alerts, "expected at least one sec.alert.v1 emission"
    for a in alerts:
        errors = schemas.validate(SEC_ALERT, a.payload)
        assert errors == [], f"sec.alert validation failed: {errors}"


# ── Bootstrap wiring ───────────────────────────────────────────────────


def test_bootstrap_includes_backup_agent() -> None:
    from ai.swarm.bootstrap import SINGLE_INSTANCE_AGENTS, build_agents

    names = {a.name for a in build_agents()}
    assert "maint.backup.v1" in names
    assert "maint.backup.v1" in SINGLE_INSTANCE_AGENTS


# ── §8.3 fail_safe_no_encryption_in_prod ────────────────────────────────


def test_prod_profile_with_runtime_refuses_unencrypted_backup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ROADMAP §8.3 binding: prod profile + non-trivial maint runtime
    + no encryption surface configured → boot refuses-to-start with
    :class:`BackupConfigError` (``fail_safe_no_encryption_in_prod``)."""
    from ai.swarm.agents.maint.backup import BackupConfigError

    monkeypatch.setattr(_cfg, "profile", "prod", raising=False)
    monkeypatch.setattr(_cfg, "maint_runtime", "compose", raising=False)
    monkeypatch.setattr(
        _cfg, "maint_backup_encryption_key_dir", "", raising=False,
    )
    monkeypatch.setattr(
        _cfg, "maint_backup_age_recipients_file", "", raising=False,
    )

    with pytest.raises(BackupConfigError, match="fail_safe_no_encryption_in_prod"):
        _build_agent(clock=_StubClock(_t(2025, 1, 1, 2, 30)))


def test_prod_profile_with_recipients_file_boots(
    monkeypatch: pytest.MonkeyPatch, tmp_path,
) -> None:
    """Either encryption surface (``encryption_key_dir`` or
    ``age_recipients_file``) being set satisfies the fail-safe."""
    monkeypatch.setattr(_cfg, "profile", "prod", raising=False)
    monkeypatch.setattr(_cfg, "maint_runtime", "compose", raising=False)
    monkeypatch.setattr(
        _cfg, "maint_backup_encryption_key_dir", "", raising=False,
    )
    monkeypatch.setattr(
        _cfg, "maint_backup_age_recipients_file",
        str(tmp_path / "recipients.txt"), raising=False,
    )

    agent = _build_agent(clock=_StubClock(_t(2025, 1, 1, 2, 30)))
    assert agent.name == "maint.backup.v1"


def test_mock_profile_unencrypted_boots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mock profile (default) keeps the existing warn-only path —
    unencrypted nightly dumps must NOT refuse-to-start in dev/CI."""
    monkeypatch.setattr(_cfg, "profile", "mock", raising=False)
    monkeypatch.setattr(_cfg, "maint_runtime", "compose", raising=False)
    monkeypatch.setattr(
        _cfg, "maint_backup_encryption_key_dir", "", raising=False,
    )
    monkeypatch.setattr(
        _cfg, "maint_backup_age_recipients_file", "", raising=False,
    )

    agent = _build_agent(clock=_StubClock(_t(2025, 1, 1, 2, 30)))
    assert agent.name == "maint.backup.v1"


def test_prod_profile_runtime_none_boots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Prod profile without a wired runtime (``maint_runtime=none``)
    is the observer-only mode — the refusal is gated on real runtime
    intent, not the profile alone."""
    monkeypatch.setattr(_cfg, "profile", "prod", raising=False)
    monkeypatch.setattr(_cfg, "maint_runtime", "none", raising=False)
    monkeypatch.setattr(
        _cfg, "maint_backup_encryption_key_dir", "", raising=False,
    )
    monkeypatch.setattr(
        _cfg, "maint_backup_age_recipients_file", "", raising=False,
    )

    agent = _build_agent(clock=_StubClock(_t(2025, 1, 1, 2, 30)))
    assert agent.name == "maint.backup.v1"


# ── Dump-on-disk retention (GFS-light, §8.3) ───────────────────────────


def _seed_dump_dir(base, name: str) -> None:
    d = base / name
    d.mkdir()
    (d / "dump.tar.age").write_bytes(b"x")


def test_retention_keeps_recent_and_weekly_sundays(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Successful fire prunes dumps older than ``retention_days``
    while preserving the most recent ``retention_weeks`` Sunday
    dumps. Quarantined ``.failed`` dirs are never touched."""
    monkeypatch.setattr(_cfg, "maint_backup_dir", str(tmp_path))
    monkeypatch.setattr(_cfg, "maint_backup_retention_days", 3)
    monkeypatch.setattr(_cfg, "maint_backup_retention_weeks", 2)

    # Today = Wed 2025-04-30. Fresh window (within 3 days):
    _seed_dump_dir(tmp_path, "pod_2025-04-30T03_00_00+00_00")  # today
    _seed_dump_dir(tmp_path, "pod_2025-04-29T03_00_00+00_00")  # yesterday
    # Sundays beyond the day window:
    _seed_dump_dir(tmp_path, "pod_2025-04-27T03_00_00+00_00")  # Sun, kept (w1)
    _seed_dump_dir(tmp_path, "pod_2025-04-20T03_00_00+00_00")  # Sun, kept (w2)
    _seed_dump_dir(tmp_path, "pod_2025-04-13T03_00_00+00_00")  # Sun, prune
    # Old non-Sunday dumps — pruned.
    _seed_dump_dir(tmp_path, "pod_2025-04-21T03_00_00+00_00")  # Mon, prune
    _seed_dump_dir(tmp_path, "pod_2025-04-15T03_00_00+00_00")  # Tue, prune
    # Quarantined dir — must be preserved.
    _seed_dump_dir(tmp_path, "pod_2025-04-10T03_00_00+00_00.failed")
    # Operator-managed sibling (audit ledger) — ignored.
    (tmp_path / "audit.csv").write_text("header\n")

    clock = _StubClock(_t(2025, 4, 30, 2, 30))
    agent = _build_agent(clock=clock, pruner_counts={"opsctl_audit": 0})
    list(agent.flush_expired())  # arm
    clock.set(_t(2025, 4, 30, 3, 0))
    msgs = list(agent.flush_expired())

    completed = next(
        m.payload for m in msgs if m.payload["kind"] == "backup_completed"
    )
    assert completed["outcome"] == "ok"
    assert completed["verified"] is True
    rt = completed["dump_retention"]
    pruned = set(rt["pruned"])
    assert "pod_2025-04-13T03_00_00+00_00" in pruned
    assert "pod_2025-04-21T03_00_00+00_00" in pruned
    assert "pod_2025-04-15T03_00_00+00_00" in pruned
    # Recent dumps + 2 most-recent Sundays + quarantine all kept.
    kept = set(rt["kept"])
    assert "pod_2025-04-30T03_00_00+00_00" in kept
    assert "pod_2025-04-29T03_00_00+00_00" in kept
    assert "pod_2025-04-27T03_00_00+00_00" in kept
    assert "pod_2025-04-20T03_00_00+00_00" in kept
    assert "pod_2025-04-10T03_00_00+00_00.failed" in rt["skipped_quarantine"]
    # On-disk reality matches the report.
    survivors = {p.name for p in tmp_path.iterdir() if p.is_dir()}
    assert "pod_2025-04-13T03_00_00+00_00" not in survivors
    assert "pod_2025-04-21T03_00_00+00_00" not in survivors
    assert "pod_2025-04-30T03_00_00+00_00" in survivors
    assert "pod_2025-04-10T03_00_00+00_00.failed" in survivors


def test_retention_dry_run_reports_but_does_not_delete(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``cfg.maint_backup_dry_run=True`` propagates to the on-disk
    retention pruner: the partition is reported but no dir is
    removed, mirroring the DB-row prune safety floor."""
    monkeypatch.setattr(_cfg, "maint_backup_dir", str(tmp_path))
    monkeypatch.setattr(_cfg, "maint_backup_retention_days", 1)
    monkeypatch.setattr(_cfg, "maint_backup_retention_weeks", 0)
    monkeypatch.setattr(_cfg, "maint_backup_dry_run", True)

    _seed_dump_dir(tmp_path, "pod_2025-04-30T03_00_00+00_00")  # today, kept
    _seed_dump_dir(tmp_path, "pod_2025-04-15T03_00_00+00_00")  # would prune

    clock = _StubClock(_t(2025, 4, 30, 2, 30))
    agent = _build_agent(clock=clock, pruner_counts={"opsctl_audit": 0})
    list(agent.flush_expired())
    clock.set(_t(2025, 4, 30, 3, 0))
    msgs = list(agent.flush_expired())

    completed = next(
        m.payload for m in msgs if m.payload["kind"] == "backup_completed"
    )
    assert completed["outcome"] == "dry_run"
    # ROADMAP §8.3: dry_run NEVER reports `verified: true` so
    # dashboards never count it as a verified backup.
    assert completed["verified"] is False
    rt = completed["dump_retention"]
    assert "pod_2025-04-15T03_00_00+00_00" in rt["pruned"]
    # Disk untouched.
    assert (tmp_path / "pod_2025-04-15T03_00_00+00_00").is_dir()


def test_backup_completed_carries_verified_flag_on_ok(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ROADMAP §8.3 binding: success path emits
    ``backup_completed{verified: true}``; the verifier-failed path
    omits the success summary entirely (already covered) and never
    advances the gauge."""
    monkeypatch.setattr(_cfg, "maint_backup_dir", str(tmp_path))
    clock = _StubClock(_t(2025, 1, 1, 2, 30))
    agent = _build_agent(clock=clock, pruner_counts={"opsctl_audit": 0})
    list(agent.flush_expired())
    clock.set(_t(2025, 1, 1, 3, 0))
    msgs = list(agent.flush_expired())
    completed = next(
        m.payload for m in msgs if m.payload["kind"] == "backup_completed"
    )
    assert completed["outcome"] == "ok"
    assert completed["verified"] is True


# ── §8.3 weekly cold-verify ─────────────────────────────────────────


def _mk_dump_dir(base, name: str) -> None:
    p = base / name
    p.mkdir()
    (p / "dump.tar.age").write_bytes(b"\x00")


def test_cold_verify_arms_silently_when_no_sunday_dump_exists(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """First flush after boot must not fire cold-verify even past
    the cron moment when no retained Sunday dump exists yet."""
    monkeypatch.setattr(_cfg, "maint_backup_dir", str(tmp_path))
    # Friday 04:30 UTC — before the 05:00 Sunday cron, nothing armed.
    clock = _StubClock(_t(2025, 5, 2, 4, 30))
    agent = _build_agent(clock=clock)
    list(agent.flush_expired())  # arm
    # Move past the next cold-verify cron moment (Sun 2025-05-04 05:00).
    clock.set(_t(2025, 5, 4, 5, 1))
    msgs = list(agent.flush_expired())
    cold_kinds = [
        k for k in _kinds(msgs)
        if k in {"backup_cold_verify_completed", "backup_cold_verify_failed"}
    ]
    assert cold_kinds == []  # nothing to cold-verify yet


def test_cold_verify_emits_completed_for_oldest_sunday_dump(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When at least one Sunday dump is on disk, the cold-verify
    cron tick fires the verifier against the oldest Sunday and
    emits backup_cold_verify_completed{dump_date, verified=true}."""
    monkeypatch.setattr(_cfg, "maint_backup_dir", str(tmp_path))
    # Three retained Sunday dumps; oldest is 2025-04-13.
    _mk_dump_dir(tmp_path, "pod_2025-04-27")
    _mk_dump_dir(tmp_path, "pod_2025-04-20")
    _mk_dump_dir(tmp_path, "pod_2025-04-13")
    # Saturday boot, Sunday morning fire.
    clock = _StubClock(_t(2025, 5, 3, 12, 0))
    verifier = NoopVerifier()
    agent = _build_agent(clock=clock, verifier=verifier)
    list(agent.flush_expired())  # arm
    clock.set(_t(2025, 5, 4, 5, 1))  # Sun 05:01 UTC — cold-verify due
    msgs = list(agent.flush_expired())
    cold = [
        m.payload for m in msgs
        if m.payload["kind"] == "backup_cold_verify_completed"
    ]
    assert len(cold) == 1, _kinds(msgs)
    payload = cold[0]
    assert payload["dump_date"] == "2025-04-13"
    assert payload["verified"] is True
    assert payload["fire_window_id"].startswith("cold:")
    assert "verify_summary" in payload
    # No backup_cold_verify_failed and no sec.alert.
    assert all(m.payload["kind"] != "backup_cold_verify_failed" for m in msgs)


def test_cold_verify_failed_emits_event_and_critical_sec_alert_no_prune(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the verifier returns an empty row-count map for the
    cold-verify dump, emit kind=backup_cold_verify_failed plus a
    sec.alert.v1{kind=backup_verify_failed, severity=critical,
    scope=cold} and DO NOT prune the dump from disk."""
    from ai.swarm.agents.topics import SEC_ALERT
    monkeypatch.setattr(_cfg, "maint_backup_dir", str(tmp_path))
    _mk_dump_dir(tmp_path, "pod_2025-04-13")  # the only Sunday
    target = tmp_path / "pod_2025-04-13"
    assert target.exists()
    clock = _StubClock(_t(2025, 5, 3, 12, 0))
    verifier = NoopVerifier(fail=True)
    agent = _build_agent(clock=clock, verifier=verifier)
    list(agent.flush_expired())  # arm
    clock.set(_t(2025, 5, 4, 5, 1))
    msgs = list(agent.flush_expired())

    failed = [
        m.payload for m in msgs
        if m.payload["kind"] == "backup_cold_verify_failed"
    ]
    assert len(failed) == 1
    fp = failed[0]
    assert fp["dump_date"] == "2025-04-13"
    assert fp["error"]
    assert fp["fire_window_id"].startswith("cold:")

    # Among sec.alerts emitted this tick, exactly ONE carries
    # scope=cold (the nightly fire on the same heartbeat may also
    # emit its own backup_verify_failed alert without scope=cold).
    cold_alerts = [
        m.payload for m in msgs
        if m.envelope.topic == SEC_ALERT
        and m.payload["kind"] == "backup_verify_failed"
        and "scope=cold" in m.payload["reason"]
    ]
    assert len(cold_alerts) == 1
    apl = cold_alerts[0]
    assert apl["severity"] == "critical"
    assert "2025-04-13" in apl["reason"]

    # Cold-verify must NEVER prune — operator decides.
    assert target.exists()


def test_cold_verify_kinds_validate_against_subschemas(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The two new kinds emitted on the cold-verify cron path
    validate against their JSON sub-schemas (boundary discipline)."""
    monkeypatch.setattr(_cfg, "maint_backup_dir", str(tmp_path))
    _mk_dump_dir(tmp_path, "pod_2025-04-13")
    clock = _StubClock(_t(2025, 5, 3, 12, 0))
    agent = _build_agent(clock=clock)  # NoopVerifier success
    list(agent.flush_expired())
    clock.set(_t(2025, 5, 4, 5, 1))
    msgs = list(agent.flush_expired())
    for m in msgs:
        kind = m.payload.get("kind")
        if kind in {"backup_cold_verify_completed", "backup_cold_verify_failed"}:
            errors = schemas.validate_kind(MAINT_EVENT, m.payload)
            assert errors == [], (kind, errors)
        assert kind in KNOWN_MAINT_EVENT_KINDS
