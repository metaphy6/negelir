"""``ops.maint-resume`` — Phase 8 §8.10.

Symmetric counterpart to ``ops.maint-pause``. Publishes
``maint.event.v1{kind=maint_resume, target, ...}`` and waits for
acks from the maintenance plane consumers.

Per ROADMAP §8.10 binding, ``maint_resume`` always succeeds at the
matrix level (see :class:`ai.swarm.agents.maint._pause_state.PauseState`):

* paused → resumed
* already running → already_resumed
* self_isolated → resumed_from_isolation (clears isolation; this is
  the operator's explicit re-arm after the dead-mans-switch flipped
  the agent into isolation per §8.16 D2).

Reversible (a follow-up pause re-pauses), so this subcommand is
SAFE for non-critical targets and CONFIRM-tier for critical ones.
"""
from __future__ import annotations

import argparse
from typing import Any, Optional

from .._runner import SubcommandSpec, run_publish

NAME = "maint-resume"
KIND = "maint_resume"


def add_parser(subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]") -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help="Resume one or all paused maint.* agents.",
        description=(
            "Publishes maint.event.v1{kind=maint_resume}. Clears "
            "self-isolation if set (operator's explicit re-arm "
            "after a dead-mans-switch event)."
        ),
    )
    parser.add_argument(
        "--target",
        required=True,
        help="'all' (broadcast) or a single maint.* agent id.",
    )
    parser.add_argument(
        "--reason",
        default="",
        help="Free-text justification carried in the envelope.",
    )
    parser.add_argument(
        "--client-id",
        default="opsctl",
        help="Operator identity tag (default: opsctl).",
    )
    parser.add_argument(
        "--confirm",
        default="",
        help=(
            "Typed confirmation token; required when --target is a "
            "critical agent (cfg.opsctl_critical_agents)."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate + print envelope; do NOT publish.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit a single JSON object on stdout (deterministic).",
    )
    parser.set_defaults(func=run)
    return parser


def run(args: argparse.Namespace, *, bus: Optional[Any] = None) -> int:
    target = str(args.target)
    reason = str(getattr(args, "reason", "") or "")
    extra_payload: dict[str, Any] = {}
    if reason:
        extra_payload["reason"] = reason
    spec = SubcommandSpec(
        name=NAME,
        kind=KIND,
        target=target,
        client_id=str(args.client_id),
        salient_args={},
        extra_payload=extra_payload,
        json_output=bool(getattr(args, "json", False)),
        dry_run=bool(getattr(args, "dry_run", False)),
        confirm=str(getattr(args, "confirm", "") or ""),
        target_agent=target if target != "all" else None,
    )
    return run_publish(spec, bus=bus)


__all__ = ["KIND", "NAME", "add_parser", "run"]
