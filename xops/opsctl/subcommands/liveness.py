"""``ops.liveness`` — Phase 8 §8.1 read-only smoke check.

Confirms the operator's environment can:

  * import :mod:`ai.common.config` and resolve a Config snapshot;
  * resolve the audit + spool paths (and create their parents);
  * read the kind→consumer map from
    :mod:`ai.swarm.agents.maint._ack_routing` (the binding wire
    authority for §8.1).

This subcommand does NOT publish a ``maint.event.v1`` envelope and
does NOT contact the bus, so it is safe to run even when Redis is
down. Exit code is :attr:`ExitCode.OK` on success.

Output is JSON to stdout when ``--json`` is set, otherwise a short
human-readable summary. The output is deterministic modulo the
config snapshot — useful in dry-run runbooks.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Optional

from ai.common.config import Config
from ai.swarm.agents.maint._ack_routing import (
    KINDS_PENDING_CONSUMER_LANDING,
    KNOWN_MAINT_EVENT_KINDS,
)

from .._audit import append_audit_row, make_row
from .._exit_codes import ExitCode

NAME = "liveness"


def add_parser(subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]") -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help="Read-only smoke check (no bus publish).",
        description=(
            "Validate that the operator environment can resolve a "
            "Config snapshot and the maint kind routing map. Does "
            "NOT contact the bus."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit a single JSON object on stdout (deterministic).",
    )
    parser.set_defaults(func=run)
    return parser


def run(args: argparse.Namespace, *, bus: Optional[Any] = None) -> int:
    del bus  # liveness does not touch the bus
    cfg = Config()
    audit_path = cfg.opsctl_audit_path_resolved
    spool_dir = cfg.opsctl_spool_dir_resolved
    Path(audit_path).parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    Path(spool_dir).mkdir(parents=True, mode=0o700, exist_ok=True)
    summary: dict[str, Any] = {
        "ok": True,
        "audit_path": audit_path,
        "spool_dir": spool_dir,
        "ack_timeout_ms": cfg.opsctl_ack_timeout_ms,
        "spool_max_entries": cfg.opsctl_spool_max_entries,
        "critical_agents": sorted(cfg.opsctl_critical_agents_set),
        "known_kinds": sorted(KNOWN_MAINT_EVENT_KINDS),
        "pending_consumer_landings": dict(sorted(KINDS_PENDING_CONSUMER_LANDING.items())),
    }
    if getattr(args, "json", False):
        sys.stdout.write(json.dumps(summary, sort_keys=True, ensure_ascii=False))
        sys.stdout.write("\n")
    else:
        sys.stdout.write(
            f"opsctl liveness OK  audit={audit_path}  spool={spool_dir}  "
            f"kinds={len(KNOWN_MAINT_EVENT_KINDS)}\n"
        )
    append_audit_row(
        audit_path,
        make_row(
            op=NAME,
            target="-",
            request_id="-",
            exit_code=int(ExitCode.OK),
            expected_acks=0,
            received_acks=0,
            note="liveness ok",
            host=os.uname().nodename,
        ),
    )
    return int(ExitCode.OK)


__all__ = ["NAME", "add_parser", "run"]
