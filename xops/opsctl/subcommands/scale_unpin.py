"""``ops.scale-unpin`` — Phase 8 §8.1 sugar over ``ops.scale``.

Cancels an active manual scale pin on a target. Equivalent to::

    ops.scale --target <agent> --replicas -1

Per ``manual_scale_pin.json`` semantics, ``replicas=-1`` clears the
pin and the scaler resumes autonomous control.
"""
from __future__ import annotations

import argparse
from typing import Any, Optional

from . import scale as _scale

NAME = "scale-unpin"


def add_parser(
    subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]",
) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help="Cancel an active manual scale pin (sugar over ops.scale --replicas -1).",
        description=(
            "Equivalent to `ops.scale --target <agent> --replicas -1`. "
            "The scaler resumes autonomous control."
        ),
    )
    parser.add_argument("--target", required=True)
    parser.add_argument("--reason", default="resume autonomous scaler")
    parser.add_argument("--client-id", default="opsctl")
    parser.add_argument("--confirm", default="")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.set_defaults(func=run)
    return parser


def run(args: argparse.Namespace, *, bus: Optional[Any] = None) -> int:
    # Materialize as a scale-cancel request.
    cancel_args = argparse.Namespace(
        target=args.target,
        replicas=-1,
        ttl_s=0,
        current=-1,
        reason=args.reason,
        client_id=args.client_id,
        confirm=args.confirm,
        dry_run=getattr(args, "dry_run", False),
        json=getattr(args, "json", False),
    )
    return _scale.run(cancel_args, bus=bus)


__all__ = ["NAME", "add_parser", "run"]
