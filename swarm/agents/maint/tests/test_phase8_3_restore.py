"""Phase 8 §8.3 — operator-driven restore runbook (`ops.restore`).

Asserts the binding contract for ``MaintBackupAgent._handle_restore``:

* Default destination = ephemeral ``negelir_restore_<dump_date>``;
  live primary is NEVER overwritten without an explicit
  ``confirm_overwrite_live`` opt-in.
* Verify-class private keys are rejected with surface code
  ``dr_key_required`` (and ack false).
* Happy path emits ``backup_restore_started`` + ``backup_restore_completed``
  to the bus AND mirrors both as ``maint_audit_log`` rows.
* Post-restore verify failure surfaces ``post_verify_failed`` with a
  non-zero ``exit_code``.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

import pytest

from common.config import cfg as _cfg
from swarm.agents.maint.backup import (
    RESTORE_OUTCOMES,
    InMemoryMaintAuditLogger,
    InMemoryPrunerStorage,
    InMemoryQuarantineStore,
    MaintBackupAgent,
    NoopDumpExecutor,
    NoopRestoreExecutor,
    NoopVerifier,
    StaticDiskGauge,
    StaticRestoreKeyClass,
)
from swarm.agents.topics import MAINT_ACK, MAINT_EVENT
from swarm.sdk.types import Envelope, Message

UTC = timezone.utc


def _t(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


class _StubClock:
    def __init__(self, start: datetime) -> None:
        self.now = start

    def wall(self) -> datetime:
        return self.now

    def mono_ns(self) -> int:
        return int(self.now.timestamp() * 1e9)


def _agent(
    *,
    restore_executor: NoopRestoreExecutor | None = None,
    restore_key_class: StaticRestoreKeyClass | None = None,
    audit: InMemoryMaintAuditLogger | None = None,
) -> tuple[MaintBackupAgent, InMemoryMaintAuditLogger]:
    clock = _StubClock(_t(2025, 1, 2, 9, 0))
    audit = audit or InMemoryMaintAuditLogger()
    a = MaintBackupAgent(
        dump=NoopDumpExecutor(),
        verifier=NoopVerifier(),
        pruner=InMemoryPrunerStorage(),
        quarantine=InMemoryQuarantineStore(),
        disk=StaticDiskGauge(free_bytes=64 * 1024 ** 3),
        restore_executor=restore_executor or NoopRestoreExecutor(),
        restore_key_class=restore_key_class or StaticRestoreKeyClass(key_class="dr"),
        audit_logger=audit,
        clock_iso=lambda: clock.wall().isoformat(timespec="seconds"),
        clock_wall=clock.wall,
        clock_mono_ns=clock.mono_ns,
        new_id=lambda: "fixed-id",
        enforce_permissions=False,
    )
    return a, audit


def _restore_msg(
    *,
    dump_date: str = "2025-01-01",
    request_id: str = "req-1",
    actor: str = "ops@host",
    destination_conn: str = "",
    confirm_overwrite_live: bool = False,
    from_offsite: bool = False,
    reason: str = "",
) -> Message:
    payload: dict = {
        "kind": "restore",
        "target": dump_date,
        "request_id": request_id,
        "client_id": actor,
        "produced_at": "2025-01-02T09:00:00Z",
    }
    if destination_conn:
        payload["destination_conn"] = destination_conn
    if confirm_overwrite_live:
        payload["confirm_overwrite_live"] = True
    if from_offsite:
        payload["from_offsite"] = True
    if reason:
        payload["reason"] = reason
    env = Envelope(
        message_id="m1",
        trace_id="t1",
        topic=MAINT_EVENT,
        producer="ops_console",
        created_at="2025-01-02T09:00:00Z",
        schema_version=1,
        attempt=1,
    )
    return Message(envelope=env, payload=payload)


def _kinds(msgs: Iterable[Message]) -> list[str]:
    return [(m.payload or {}).get("kind") for m in msgs]


def test_outcome_taxonomy_is_closed() -> None:
    """Surface tokens are pinned; extending requires a swarm minor bump."""
    assert RESTORE_OUTCOMES == frozenset({
        "ok",
        "checksum_verify_failed",
        "dr_key_required",
        "live_overwrite_requires_confirm",
        "decrypt_failed",
        "restore_failed",
        "post_verify_failed",
    })


def test_default_target_is_ephemeral() -> None:
    a, audit = _agent()
    out = list(a.handle(_restore_msg()))
    kinds = _kinds(out)
    assert "backup_restore_started" in kinds
    assert "backup_restore_completed" in kinds
    started = next(m for m in out if (m.payload or {}).get("kind") == "backup_restore_started")
    assert started.payload["target"] == "negelir_restore_2025-01-01"
    assert started.payload["ephemeral"] is True
    assert started.payload["destination_conn"] == ""
    assert started.payload["requested_by"] == "ops@host"
    completed = next(m for m in out if (m.payload or {}).get("kind") == "backup_restore_completed")
    assert completed.payload["outcome"] == "ok"
    assert completed.payload["exit_code"] == 0
    assert completed.payload["ephemeral"] is True
    # Audit ledger mirrors both events.
    audit_kinds = [r["kind"] for r in audit.rows]
    assert "backup_restore_started" in audit_kinds
    assert "backup_restore_completed" in audit_kinds


def test_destination_conn_passthrough_marks_non_ephemeral() -> None:
    exe = NoopRestoreExecutor()
    a, _ = _agent(restore_executor=exe)
    out = list(a.handle(_restore_msg(destination_conn="postgresql://drhost/xyz")))
    started = next(m for m in out if (m.payload or {}).get("kind") == "backup_restore_started")
    assert started.payload["target"] == "postgresql://drhost/xyz"
    assert started.payload["ephemeral"] is False
    assert exe.last_destination == "postgresql://drhost/xyz"
    assert exe.last_ephemeral is False


def test_live_overwrite_without_confirm_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    live_dsn = "postgresql://app:pw@live/negelir"
    monkeypatch.setattr(_cfg, "maint_backup_pg_dsn", live_dsn)
    a, audit = _agent()
    out = list(a.handle(_restore_msg(destination_conn=live_dsn)))
    # Ack must be refused.
    acks = [m for m in out if m.envelope.topic == MAINT_ACK]
    assert len(acks) == 1
    assert acks[0].payload["accepted"] is False
    assert acks[0].payload["reason"] == "live_overwrite_requires_confirm"
    # Completed event must mirror the surface code; no started event.
    kinds = _kinds(out)
    assert "backup_restore_started" not in kinds
    completed = next(m for m in out if (m.payload or {}).get("kind") == "backup_restore_completed")
    assert completed.payload["outcome"] == "live_overwrite_requires_confirm"
    assert completed.payload["exit_code"] != 0
    # Audit ledger captures the refusal too (right-to-restore traceability).
    assert any(r["details"]["outcome"] == "live_overwrite_requires_confirm" for r in audit.rows)


def test_live_overwrite_with_confirm_proceeds(monkeypatch: pytest.MonkeyPatch) -> None:
    live_dsn = "postgresql://app:pw@live/negelir"
    monkeypatch.setattr(_cfg, "maint_backup_pg_dsn", live_dsn)
    a, _ = _agent()
    out = list(a.handle(_restore_msg(
        destination_conn=live_dsn, confirm_overwrite_live=True,
    )))
    acks = [m for m in out if m.envelope.topic == MAINT_ACK]
    assert acks[0].payload["accepted"] is True
    assert "backup_restore_started" in _kinds(out)
    completed = next(m for m in out if (m.payload or {}).get("kind") == "backup_restore_completed")
    assert completed.payload["outcome"] == "ok"


def test_verify_class_key_is_rejected_with_dr_key_required() -> None:
    a, audit = _agent(restore_key_class=StaticRestoreKeyClass(key_class="verify"))
    out = list(a.handle(_restore_msg()))
    acks = [m for m in out if m.envelope.topic == MAINT_ACK]
    assert acks[0].payload["accepted"] is False
    assert acks[0].payload["reason"] == "dr_key_required"
    completed = next(m for m in out if (m.payload or {}).get("kind") == "backup_restore_completed")
    assert completed.payload["outcome"] == "dr_key_required"
    # No started event — restore was never attempted.
    assert "backup_restore_started" not in _kinds(out)
    assert any(r["details"]["outcome"] == "dr_key_required" for r in audit.rows)


def test_unknown_key_class_surfaces_decrypt_failed() -> None:
    a, _ = _agent(restore_key_class=StaticRestoreKeyClass(key_class=""))
    out = list(a.handle(_restore_msg()))
    completed = next(m for m in out if (m.payload or {}).get("kind") == "backup_restore_completed")
    assert completed.payload["outcome"] == "decrypt_failed"


def test_executor_failure_surfaces_restore_failed() -> None:
    a, _ = _agent(restore_executor=NoopRestoreExecutor(exit_code=2))
    out = list(a.handle(_restore_msg()))
    completed = next(m for m in out if (m.payload or {}).get("kind") == "backup_restore_completed")
    assert completed.payload["outcome"] == "restore_failed"
    assert completed.payload["exit_code"] == 2


def test_empty_verify_summary_surfaces_post_verify_failed() -> None:
    exe = NoopRestoreExecutor(summary={})
    a, _ = _agent(restore_executor=exe)
    out = list(a.handle(_restore_msg()))
    completed = next(m for m in out if (m.payload or {}).get("kind") == "backup_restore_completed")
    assert completed.payload["outcome"] == "post_verify_failed"
    assert completed.payload["exit_code"] != 0


def test_executor_exception_does_not_crash_handler() -> None:
    class _Boom:
        def restore(self, *, dump_date, destination, ephemeral):
            raise RuntimeError("subprocess died")

    a, _ = _agent(restore_executor=_Boom())  # type: ignore[arg-type]
    out = list(a.handle(_restore_msg()))
    completed = next(m for m in out if (m.payload or {}).get("kind") == "backup_restore_completed")
    assert completed.payload["outcome"] == "restore_failed"
    assert completed.payload["exit_code"] != 0


def test_missing_request_id_acks_false() -> None:
    a, _ = _agent()
    bad = _restore_msg(request_id="")
    out = list(a.handle(bad))
    assert any(m.envelope.topic == MAINT_ACK and m.payload["accepted"] is False for m in out)
    # No restore events emitted.
    assert "backup_restore_started" not in _kinds(out)
    assert "backup_restore_completed" not in _kinds(out)


def test_other_kinds_are_still_ignored() -> None:
    a, _ = _agent()
    env = Envelope(
        message_id="m1", trace_id="t1", topic=MAINT_EVENT,
        producer="x", created_at="2025-01-02T09:00:00Z",
        schema_version=1, attempt=1,
    )
    msg = Message(envelope=env, payload={"kind": "scale_decision"})
    assert list(a.handle(msg)) == []
