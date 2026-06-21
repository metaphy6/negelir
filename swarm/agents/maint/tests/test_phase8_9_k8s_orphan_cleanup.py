"""Phase 8 §8.9 DoD — second-pass proof test: K8s verify-Job orphan cleanup.

Simulates agent crash mid-watch (kill-9 during pg_restore); on next agent
boot asserts:

* Orphaned Job + ephemeral PVC entries under ``negelir-maint-verify`` are
  swept by calling ``verifier.sweep_orphans()`` on the **first**
  ``flush_expired()`` call after construction.
* ``maint.event.v1{kind=backup_verify_orphan_swept}`` is published exactly
  once (the boot-sweep flag prevents re-emission on subsequent ticks).
* The event payload carries ``count``, ``swept_jobs``, ``scope="boot"``,
  and ``ttl_h`` equal to ``cfg.maint_backup_verify_orphan_ttl_h``.
* ``cfg.maint_backup_verify_orphan_ttl_h`` defaults to ``6.0`` hours
  (ROADMAP §8.3 binding).

The real K8s ``SidecarVerifier`` (Phase 14) implements TTL filtering inside
``sweep_orphans()`` using ``cfg.maint_backup_verify_orphan_ttl_h``; the
``NoopVerifier`` shim returns its pre-configured ``orphans`` tuple directly
so the boot-sweep path is exercised end-to-end at the Protocol level.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

from common.config import cfg as _cfg
from swarm.agents.maint.backup import (
    InMemoryPrunerStorage,
    InMemoryQuarantineStore,
    MaintBackupAgent,
    NoopDumpExecutor,
    NoopVerifier,
    StaticDiskGauge,
)

UTC = timezone.utc

_ORPHAN_NAMES = (
    "restore-verify-abc123",
    "restore-verify-def456",
)


def _build_agent(verifier: NoopVerifier) -> MaintBackupAgent:
    prior_dir = _cfg.maint_backup_dir
    _cfg.maint_backup_dir = "/nonexistent/negelir_test_orphan_cleanup"
    try:
        return MaintBackupAgent(
            dump=NoopDumpExecutor(),
            verifier=verifier,
            pruner=InMemoryPrunerStorage(),
            quarantine=InMemoryQuarantineStore(),
            disk=StaticDiskGauge(free_bytes=64 * 1024 ** 3),
            clock_iso=lambda: "2026-05-21T02:00:00+00:00",
            clock_wall=lambda: datetime(2026, 5, 21, 2, 0, tzinfo=UTC),
            clock_mono_ns=lambda: int(2 * 3600 * 1e9),
            new_id=lambda: "test-id",
            enforce_permissions=False,
        )
    finally:
        _cfg.maint_backup_dir = prior_dir


def test_verify_orphan_ttl_h_default() -> None:
    old = os.environ.pop("NEGELIR_MAINT_BACKUP_VERIFY_ORPHAN_TTL_H", None)
    try:
        from common.config import Config
        fresh = Config()
        assert fresh.maint_backup_verify_orphan_ttl_h == 6.0
    finally:
        if old is not None:
            os.environ["NEGELIR_MAINT_BACKUP_VERIFY_ORPHAN_TTL_H"] = old


def test_boot_sweep_emits_orphan_swept_event() -> None:
    verifier = NoopVerifier(orphans=_ORPHAN_NAMES)
    agent = _build_agent(verifier)
    msgs = list(agent.flush_expired())
    swept = [m for m in msgs if m.payload.get("kind") == "backup_verify_orphan_swept"]
    assert len(swept) == 1, f"expected 1 backup_verify_orphan_swept on first flush; got {len(swept)}"
    payload = swept[0].payload
    assert payload["count"] == 2
    assert set(payload["swept_jobs"]) == set(_ORPHAN_NAMES)
    assert payload["scope"] == "boot"
    assert payload["ttl_h"] == float(_cfg.maint_backup_verify_orphan_ttl_h)


def test_boot_sweep_emits_nothing_when_no_orphans() -> None:
    verifier = NoopVerifier(orphans=())
    agent = _build_agent(verifier)
    msgs = list(agent.flush_expired())
    swept = [m for m in msgs if m.payload.get("kind") == "backup_verify_orphan_swept"]
    assert len(swept) == 0, "must not emit when there are no orphans"


def test_boot_sweep_fires_exactly_once() -> None:
    verifier = NoopVerifier(orphans=_ORPHAN_NAMES)
    agent = _build_agent(verifier)
    first = list(agent.flush_expired())
    first_swept = [m for m in first if m.payload.get("kind") == "backup_verify_orphan_swept"]
    assert len(first_swept) == 1, "expected 1 on first flush"
    second = list(agent.flush_expired())
    second_swept = [m for m in second if m.payload.get("kind") == "backup_verify_orphan_swept"]
    assert len(second_swept) == 0, "must not emit a second time"
