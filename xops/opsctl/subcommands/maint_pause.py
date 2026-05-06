"""``ops.maint-pause`` — Phase 8 §8.10.

Operator-driven planned-maintenance pause for the maintenance plane.
Publishes ``maint.event.v1{kind=maint_pause, target, ttl_s, ...}``
and waits for an ack from every consumer in
:func:`ai.swarm.agents.maint._ack_routing.expected_ack_set`
(``{maint.scaler.v1, maint.dlq.v1, maint.schema.v1, maint.sec.v1}``).

Per ROADMAP §8.10 binding:

* ``--target`` is either ``all`` (broadcast) or a single agent id.
  Non-targeted agents still emit ``maint.ack.v1`` with
  ``reason=not_targeted`` so the publisher receives a deterministic
  complete ack set.
* ``--ttl-s`` defaults to ``cfg.maint_pause_default_ttl_s`` and is
  capped at the per-kind sub-schema maximum (86400s = 24h). An
  agent that is already paused widens its deadline only.
* Critical agents (``cfg.opsctl_critical_agents_set``) bump the
  classifier into the CONFIRM tier — operator must pass the typed
  ``--confirm`` token. Non-critical targets are SAFE.
* Reversible (``ops.maint-resume`` clears it; the deadline auto-
  resumes regardless), so the subcommand is **not** in
  :data:`xops.opsctl._classify.ALWAYS_DESTRUCTIVE`.
"""
from __future__ import annotations

import argparse
from typing import Any, Optional

from ai.common.config import Config

from .._runner import SubcommandSpec, run_publish

NAME = "maint-pause"
KIND = "maint_pause"

# Per the per-kind sub-schema upper bound.
_TTL_MAX_S = 86_400


def add_parser(subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]") -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help="Pause one or all maint.* agents (planned maintenance).",
        description=(
            "Publishes maint.event.v1{kind=maint_pause}. The targeted "
            "agent(s) stop emitting decisions until ops.maint-resume "
            "or ttl_s elapses. Self-isolated agents refuse pause "
            "until an operator explicitly resumes them."
        ),
    )
    parser.add_argument(
        "--target",
        required=True,
        help="'all' (broadcast) or a single maint.* agent id.",
    )
    parser.add_argument(
        "--ttl-s",
        type=int,
        default=0,
        help=(
            "Auto-resume after this many seconds (1..86400). "
            "Defaults to cfg.maint_pause_default_ttl_s."
        ),
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


def _resolve_ttl_s(requested: int) -> int:
    cfg = Config()
    base = int(requested) if int(requested) > 0 else int(cfg.maint_pause_default_ttl_s)
    return max(1, min(base, _TTL_MAX_S))


def run(args: argparse.Namespace, *, bus: Optional[Any] = None) -> int:
    target = str(args.target)
    ttl_s = _resolve_ttl_s(int(getattr(args, "ttl_s", 0) or 0))
    reason = str(getattr(args, "reason", "") or "")
    extra_payload: dict[str, Any] = {"ttl_s": ttl_s}
    if reason:
        extra_payload["reason"] = reason
    spec = SubcommandSpec(
        name=NAME,
        kind=KIND,
        target=target,
        client_id=str(args.client_id),
        salient_args={"ttl_s": ttl_s},
        extra_payload=extra_payload,
        json_output=bool(getattr(args, "json", False)),
        dry_run=bool(getattr(args, "dry_run", False)),
        confirm=str(getattr(args, "confirm", "") or ""),
        # Single-agent targets route through the critical-agent gate
        # in :mod:`xops.opsctl._classify`; 'all' is broadcast and not
        # tied to a single critical id.
        target_agent=target if target != "all" else None,
    )
    return run_publish(spec, bus=bus)


__all__ = ["KIND", "NAME", "add_parser", "run"]
