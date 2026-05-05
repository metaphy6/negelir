"""xops.opsctl — Phase 8 §8.1 ops console.

Stateless operator CLI for the maint plane. Publishes ``maint.event.v1``
envelopes (with ``producer=ops_console``) and waits for the per-consumer
``maint.ack.v1`` set defined in
:mod:`ai.swarm.agents.maint._ack_routing`. Bus-down replays land in the
spool dir and are drained by ``make ops.spool-flush``.

Boundary discipline (binding, per ROADMAP §8.1 + §8.10):

* This package MUST NOT import ``psycopg``, ``redis`` mutators, or
  shell out to ``psql`` / ``redis-cli``. The bus is the only
  sanctioned write surface; storage agents own their tables.
  Enforced by an AST scan in
  ``xops/opsctl/tests/test_opsctl_boundary.py``.

* Subcommands MUST be deterministic in their dry-run + JSON output —
  no wall-clock leakage, no random salt — so operator runbooks are
  reproducible.

* Every successful or refused subcommand writes one row to the audit
  log (``opsctl_audit_path_resolved``) with ``fsync`` after each
  write and ``fsync`` of the parent dir on first creation. Audit
  rows are append-only; redaction is a downstream concern.

Public surface is intentionally minimal — the CLI is the API.
"""
from __future__ import annotations

from ._exit_codes import ExitCode

__all__ = ["ExitCode"]
