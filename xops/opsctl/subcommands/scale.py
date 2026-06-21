"""``ops.scale`` — Phase 8 §8.1 / §8.2.

Operator pin of replica count on a scalable agent. Publishes
``maint.event.v1{kind=manual_scale_pin, target, replicas, ttl_s}``
and waits for the ack from ``maint.scaler.v1``.

Per ROADMAP §8.1 destructive set + :mod:`xops.opsctl._classify`:

* ``--replicas 0`` is destructive (drains the agent class to zero
  capacity); the classifier flags ``replicas_zero``.
* A reduction of more than 50% from the agent's current replicas
  is destructive; the classifier flags ``reduction_over_50pct``.
  We do NOT poll the live runtime to compute the percentage at
  CLI time — that would race against the scaler. Instead the
  operator passes ``--current N`` (best-effort, audited) and the
  classifier compares; absent ``--current``, we conservatively
  flag any non-zero reduction as needing confirmation when
  ``--replicas`` is below ``cfg.maint_scaler_default_max_replicas``.
* ``replicas == -1`` cancels an active pin (matches the sub-schema's
  semantics) and is SAFE (the scaler returns to autonomous control).

Critical-agent gate is automatic via :func:`SubcommandSpec.target_agent`.
"""
from __future__ import annotations

import argparse
from typing import Any, Optional

from common.config import Config

from .._runner import SubcommandSpec, run_publish

NAME = "scale"
KIND = "manual_scale_pin"


def add_parser(
    subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]",
) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help="Pin replica count on a scalable agent (manual override).",
        description=(
            "Publishes maint.event.v1{kind=manual_scale_pin}. The "
            "scaler suspends autonomous decisions for this target "
            "until ttl_s elapses or replicas=-1 cancels the pin."
        ),
    )
    parser.add_argument(
        "--target",
        required=True,
        help="Agent id (e.g. 'predictor.elo.v1') or worker class.",
    )
    parser.add_argument(
        "--replicas",
        type=int,
        required=True,
        help="Desired replica count (-1 cancels an active pin).",
    )
    parser.add_argument(
        "--ttl-s",
        type=int,
        default=0,
        help=(
            "Override pin TTL (1..604800 = 7d). 0 means use cfg "
            "maint_scaler_manual_pin_ttl_s."
        ),
    )
    parser.add_argument(
        "--current",
        type=int,
        default=-1,
        help=(
            "Best-effort current replica count (operator-provided; "
            "audited). Used by the classifier to detect >50% "
            "reductions; absent, the classifier conservatively flags "
            "below-default targets."
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
            "Typed confirmation token; required for --replicas 0, "
            ">50%% reduction, or critical-agent targets."
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


def _classify_flags(replicas: int, current: int, default_max: int) -> frozenset[str]:
    flags: set[str] = set()
    if replicas == 0:
        flags.add("replicas_zero")
    if replicas > 0 and current > 0:
        # >50% reduction.
        if replicas * 2 < current:
            flags.add("reduction_over_50pct")
    elif replicas > 0 and current < 0 and replicas < default_max:
        # Operator did not supply --current and target is below the
        # default ceiling — conservatively flag as a likely reduction.
        flags.add("reduction_over_50pct")
    return frozenset(flags)


def run(args: argparse.Namespace, *, bus: Optional[Any] = None) -> int:
    cfg = Config()
    target = str(args.target)
    replicas = int(args.replicas)
    ttl_s = int(getattr(args, "ttl_s", 0) or 0)
    current = int(getattr(args, "current", -1))
    reason = str(getattr(args, "reason", "") or "")

    extra_payload: dict[str, Any] = {"replicas": replicas}
    if ttl_s > 0:
        extra_payload["ttl_s"] = ttl_s
    if reason:
        extra_payload["reason"] = reason

    salient: dict[str, Any] = {"replicas": replicas}
    if ttl_s > 0:
        salient["ttl_s"] = ttl_s

    # When the operator opt-in default is unset (0), fall back to the
    # global per-target ceiling for the conservative-reduction heuristic.
    default_max = int(cfg.maint_scaler_default_max_replicas) or int(
        cfg.maint_scaler_max_replicas
    )
    flags = _classify_flags(
        replicas=replicas,
        current=current,
        default_max=default_max,
    )

    spec = SubcommandSpec(
        name=NAME,
        kind=KIND,
        target=target,
        client_id=str(args.client_id),
        salient_args=salient,
        extra_flags=flags,
        extra_payload=extra_payload,
        json_output=bool(getattr(args, "json", False)),
        dry_run=bool(getattr(args, "dry_run", False)),
        confirm=str(getattr(args, "confirm", "") or ""),
        target_agent=target,
    )
    return run_publish(spec, bus=bus)


__all__ = ["KIND", "NAME", "add_parser", "run"]
