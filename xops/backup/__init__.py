"""Phase 8 §8.3 — backup-agent helpers (stdlib-only).

This package houses the utility surfaces the
:class:`swarm.agents.maint.backup.MaintBackupAgent` reactor
depends on but which are intentionally bus-free:

* :mod:`xops.backup.cron`          — 5-field cron parser/evaluator
* :mod:`xops.backup.disk_guard`    — free-space + dump-size headroom
* :mod:`xops.backup.file_manifest` — per-file SHA-256 manifest
                                     (§8.14.2 silent-corruption gate)
* :mod:`xops.backup.skew`          — wall-clock skew detector

Heavy production drivers (real ``pg_dump``, ``age`` encryption,
``pg_restore``) are intentionally NOT here — the agent talks to
them through Protocol-typed adapters injected by the Phase-14
runtime layer. The v1 vertical slice ships in-memory shims so the
state machine (dump → verify → prune) is testable without a live
Postgres.
"""

__all__: list[str] = []
