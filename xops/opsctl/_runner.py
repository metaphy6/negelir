"""xops.opsctl — shared subcommand-runner helper (Phase 8 §8.1).

Centralizes the common shape of every publishing subcommand:

  1. classify (destructive? critical-target?) → SAFE / CONFIRM / REFUSE
  2. derive expected typed token; refuse early if missing/mismatched
  3. ``--dry-run`` short-circuit: print envelope + expected ack set,
     skip lock + publish + audit-row mutation
  4. acquire re-entrancy lock (host, kind, target) — refuse on
     contention with an audit row + non-zero exit
  5. publish + ack-wait via :mod:`xops.opsctl._publish`
  6. emit human/JSON summary; append audit row

Subcommand modules construct a :class:`SubcommandSpec`, call
:func:`run_publish`, and return the resulting exit code. The
denylist-clear / quarantine-erase modules wire through this
helper; spool-flush + liveness do not (they have distinct flows).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

from ai.common.config import Config

from ._audit import append_audit_row, make_row
from ._classify import Action, ClassifyRequest, classify
from ._exit_codes import ExitCode
from ._lock import reentrancy_lock
from ._publish import build_envelope, publish_event
from ._token import derive_confirm_token


@dataclass(frozen=True)
class SubcommandSpec:
    """Minimal description of a publishing subcommand.

    ``salient_args`` is the dict folded into the typed-token preimage
    plus the envelope's optional payload extras (subcommand decides
    which keys belong in each).
    """

    name: str
    kind: str
    target: str
    client_id: str
    salient_args: Mapping[str, Any] = field(default_factory=dict)
    extra_flags: frozenset[str] = field(default_factory=frozenset)
    extra_payload: Mapping[str, Any] = field(default_factory=dict)
    json_output: bool = False
    dry_run: bool = False
    confirm: str = ""
    target_agent: Optional[str] = None  # for critical-agent classifier


# Exit code emitted when the re-entrancy lock is contended. Routed
# through ``GENERIC_FAILURE`` so it remains clearly non-zero for the
# operator's runbook; the audit row carries the ``contended`` note.
LOCK_CONTENDED_EXIT: ExitCode = ExitCode.GENERIC_FAILURE


def _emit_summary(
    *,
    spec: SubcommandSpec,
    exit_code: int,
    request_id: str,
    expected: list[str],
    received: list[str],
    note: str,
    action: str,
) -> None:
    summary: dict[str, Any] = {
        "op": spec.name,
        "kind": spec.kind,
        "target": spec.target,
        "request_id": request_id,
        "exit_code": int(exit_code),
        "expected_acks": expected,
        "received_acks": received,
        "note": note,
        "action": action,
    }
    if spec.json_output:
        sys.stdout.write(json.dumps(summary, sort_keys=True, ensure_ascii=False))
        sys.stdout.write("\n")
    else:
        sys.stdout.write(
            f"opsctl {spec.name} target={spec.target} "
            f"request_id={request_id} exit={int(exit_code)} "
            f"acks={received}/{expected} action={action} note={note}\n"
        )


def run_publish(spec: SubcommandSpec, *, bus: Optional[Any] = None) -> int:
    """Execute the standard subcommand flow (see module docstring).

    Returns the int exit code suitable for ``sys.exit``.
    """
    cfg = Config()
    host = os.uname().nodename

    decision = classify(
        ClassifyRequest(
            subcommand=spec.name,
            target_agent=spec.target_agent,
            critical_agents=cfg.opsctl_critical_agents_set,
            flags=spec.extra_flags,
        )
    )
    expected_token = derive_confirm_token(
        subcommand=spec.name,
        target=spec.target,
        salient_args=spec.salient_args,
    )

    # ── Refuse classification (always blocks, even in dry-run) ───────
    if decision is Action.REFUSE:
        note = "classifier=REFUSE (operator path forbidden)"
        _emit_summary(
            spec=spec, exit_code=int(ExitCode.BAD_USAGE),
            request_id="-", expected=[], received=[],
            note=note, action="refuse",
        )
        append_audit_row(
            cfg.opsctl_audit_path_resolved,
            make_row(
                op=spec.name, target=spec.target, request_id="-",
                exit_code=int(ExitCode.BAD_USAGE),
                expected_acks=0, received_acks=0,
                note=note, host=host,
            ),
        )
        return int(ExitCode.BAD_USAGE)

    # ── Build envelope upfront so dry-run prints what would publish ──
    extras = dict(spec.extra_payload) if spec.extra_payload else None
    message = build_envelope(
        kind=spec.kind, target=spec.target, client_id=spec.client_id,
        extra_payload=extras,
    )
    request_id = str(message.payload["request_id"])

    # ── Dry-run short-circuit (no token gate, no lock, no publish,
    #    no audit row). Per ROADMAP §8.1: dry-run is the safe-preview
    #    path so operators can inspect the envelope before paying the
    #    destructive-token tax. ─────────────────────────────────────
    if spec.dry_run:
        from ai.swarm.agents.maint._ack_routing import (
            KNOWN_MAINT_EVENT_KINDS, expected_ack_set,
        )
        if spec.kind in KNOWN_MAINT_EVENT_KINDS:
            expected = sorted(expected_ack_set(spec.kind))
        else:
            expected = []
        note = "dry-run: validated; no publish, no audit row"
        summary: dict[str, Any] = {
            "op": spec.name,
            "kind": spec.kind,
            "target": spec.target,
            "client_id": spec.client_id,
            "request_id": request_id,
            "expected_acks": expected,
            "envelope": {
                "topic": str(message.envelope.topic),
                "producer": message.envelope.producer,
            },
            "payload": message.payload,
            "expected_confirm_token": expected_token,
            "action": "dry-run",
            "note": note,
        }
        if spec.json_output:
            sys.stdout.write(json.dumps(summary, sort_keys=True, ensure_ascii=False))
            sys.stdout.write("\n")
        else:
            sys.stdout.write(
                f"opsctl {spec.name} DRY-RUN target={spec.target} "
                f"request_id={request_id} expected_acks={expected} "
                f"confirm_token={expected_token}\n"
            )
        return int(ExitCode.OK)

    # ── Token gate (only blocks the real publish path) ───────────────
    if decision is Action.CONFIRM and spec.confirm != expected_token:
        # Operator-friendly: tell them the token they need. The token
        # is purely shell-history defense (see _token.py docstring),
        # NOT a secret — printing it on mismatch is intended.
        note = (
            f"destructive op refused: expected --confirm={expected_token}; "
            f"got {spec.confirm or '(empty)'!r}"
        )
        sys.stderr.write(f"opsctl {spec.name}: {note}\n")
        _emit_summary(
            spec=spec, exit_code=int(ExitCode.BAD_USAGE),
            request_id="-", expected=[], received=[],
            note=note, action="refuse",
        )
        append_audit_row(
            cfg.opsctl_audit_path_resolved,
            make_row(
                op=spec.name, target=spec.target, request_id="-",
                exit_code=int(ExitCode.BAD_USAGE),
                expected_acks=0, received_acks=0,
                note=note, host=host,
            ),
        )
        return int(ExitCode.BAD_USAGE)

    # ── Re-entrancy lock acquire ─────────────────────────────────────
    with reentrancy_lock(
        lock_dir=cfg.opsctl_lock_dir_resolved,
        host=host,
        kind=spec.kind,
        target=spec.target,
        ack_timeout_ms=cfg.opsctl_ack_timeout_ms,
        stale_factor=cfg.opsctl_lock_stale_factor,
    ) as lock_outcome:
        if not lock_outcome.acquired:
            note = f"lock contended: {lock_outcome.note}"
            sys.stderr.write(f"opsctl {spec.name}: {note}\n")
            _emit_summary(
                spec=spec, exit_code=int(LOCK_CONTENDED_EXIT),
                request_id=request_id, expected=[], received=[],
                note=note, action="lock-contended",
            )
            append_audit_row(
                cfg.opsctl_audit_path_resolved,
                make_row(
                    op=spec.name, target=spec.target,
                    request_id=request_id,
                    exit_code=int(LOCK_CONTENDED_EXIT),
                    expected_acks=0, received_acks=0,
                    note=note, host=host,
                ),
            )
            return int(LOCK_CONTENDED_EXIT)

        # ── Publish + ack-wait ───────────────────────────────────────
        result = publish_event(bus, message)

    _emit_summary(
        spec=spec,
        exit_code=int(result.exit_code),
        request_id=result.request_id,
        expected=sorted(result.expected_acks),
        received=sorted(result.received_acks),
        note=result.note,
        action="publish",
    )
    append_audit_row(
        cfg.opsctl_audit_path_resolved,
        make_row(
            op=spec.name,
            target=spec.target,
            request_id=result.request_id,
            exit_code=int(result.exit_code),
            expected_acks=len(result.expected_acks),
            received_acks=len(result.received_acks),
            note=result.note,
            host=host,
        ),
    )
    return int(result.exit_code)


def add_common_publish_args(
    parser: argparse.ArgumentParser, *, target_help: str
) -> None:
    """Register ``--target``, ``--client-id``, ``--confirm``,
    ``--dry-run``, and ``--json`` on ``parser``."""
    parser.add_argument("--target", required=True, help=target_help)
    parser.add_argument(
        "--client-id",
        default="opsctl",
        help="Operator identity tag carried in the envelope payload (default: opsctl).",
    )
    parser.add_argument(
        "--confirm",
        default="",
        help=(
            "Typed confirmation token for destructive ops. "
            "Computed as sha256(cmd|target|salient_args)[:8]; the CLI "
            "prints the expected value on mismatch."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate + compute expected ack set + print envelope; do NOT publish.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit a single JSON object on stdout (deterministic).",
    )


__all__ = [
    "LOCK_CONTENDED_EXIT",
    "SubcommandSpec",
    "add_common_publish_args",
    "run_publish",
]
