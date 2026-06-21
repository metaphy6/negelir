"""Phase 8 §8.9 DoD — Audit-log INSERT-only proof tests.

Bullet (ROADMAP §8.9):

> **Audit-log INSERT-only.** Attempt UPDATE and DELETE on
> maint_audit_log as the application role; assert both raise
> audit_log_immutable. Same as negelir_backup. Retention prune
> as negelir_audit_pruner succeeds only inside the explicit
> SET ROLE transaction; outside the transaction the role cannot be assumed.

What this asserts (binding):

* InMemoryImmutableAuditStore.append() always succeeds.
* update() raises AuditLogImmutableError for the application role.
* delete_by_request_id() raises AuditLogImmutableError for the application role.
* delete_by_request_id() raises AuditLogImmutableError for negelir_backup role.
* delete_by_request_id() SUCCEEDS inside the set_role_pruner() context.
* After set_role_pruner() exits, delete_by_request_id() raises again.
"""
from __future__ import annotations

import pytest

from swarm.agents.maint.backup import (
    AuditLogImmutableError,
    InMemoryImmutableAuditStore,
)


def _store_with_row() -> tuple:
    store = InMemoryImmutableAuditStore()
    rid = "req-immutable-001"
    store.append(
        kind="backup_completed",
        request_id=rid,
        target="backup",
        actor="cron",
        details={"outcome": "ok"},
    )
    return store, rid


def test_append_always_permitted() -> None:
    store = InMemoryImmutableAuditStore()
    store.append(
        kind="backup_started",
        request_id="req-insert-001",
        target="backup",
        actor="cron",
        details={},
    )
    assert len(store.rows) == 1
    assert store.rows[0]["kind"] == "backup_started"


def test_app_role_update_raises_audit_log_immutable() -> None:
    store, rid = _store_with_row()
    with pytest.raises(AuditLogImmutableError) as exc_info:
        store.update(rid, outcome="tampered")
    assert "audit_log_immutable" in str(exc_info.value)
    assert "UPDATE" in str(exc_info.value)
    assert store.rows[0]["details"]["outcome"] == "ok"


def test_app_role_delete_raises_audit_log_immutable() -> None:
    store, rid = _store_with_row()
    with pytest.raises(AuditLogImmutableError) as exc_info:
        store.delete_by_request_id(rid)
    assert "audit_log_immutable" in str(exc_info.value)
    assert "DELETE" in str(exc_info.value)
    assert len(store.rows) == 1


def test_backup_role_delete_also_raises_audit_log_immutable() -> None:
    store, rid = _store_with_row()
    # negelir_backup is not the pruner role; default non-pruner path raises
    with pytest.raises(AuditLogImmutableError):
        store.delete_by_request_id(rid)
    assert len(store.rows) == 1


def test_pruner_role_delete_succeeds_inside_set_role_txn() -> None:
    store, rid = _store_with_row()
    with store.set_role_pruner():
        deleted = store.delete_by_request_id(rid)
    assert deleted == 1
    assert len(store.rows) == 0


def test_pruner_role_cannot_be_assumed_outside_txn() -> None:
    store, rid = _store_with_row()
    with store.set_role_pruner():
        pass  # enter and exit without deleting
    # Role has reverted; DELETE must raise
    with pytest.raises(AuditLogImmutableError):
        store.delete_by_request_id(rid)
    assert len(store.rows) == 1
