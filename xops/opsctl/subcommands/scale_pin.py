"""``ops.scale-pin`` — Phase 8 §8.1 sugar over ``ops.scale``.

Convenience wrapper that pins a target's replicas to a specific
count for a TTL window (the most common operator workflow during a
known-load event). Equivalent to::

    ops.scale --target <agent> --replicas <n> --ttl-s <seconds>

Routes through the same ``manual_scale_pin`` kind as
:mod:`xops.opsctl.subcommands.scale`, so the classifier flags and
ack contract are identical.
"""
from __future__ import annotations

import argparse
from typing import Any, Optional

from . import scale as _scale

NAME = "scale-pin"


def add_parser(
    subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]",
) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help="Pin replica count on a scalable agent (sugar over ops.scale).",
        description=(
            "Equivalent to `ops.scale --target <agent> --replicas <n> "
            "--ttl-s <seconds>`. Same classifier semantics."
        ),
    )
    parser.add_argument("--target", required=True)
    parser.add_argument("--replicas", type=int, required=True)
    parser.add_argument("--ttl-s", type=int, default=0)
    parser.add_argument("--current", type=int, default=-1)
    parser.add_argument("--reason", default="")
    parser.add_argument("--client-id", default="opsctl")
    parser.add_argument("--confirm", default="")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.set_defaults(func=run)
    return parser


def run(args: argparse.Namespace, *, bus: Optional[Any] = None) -> int:
    return _scale.run(args, bus=bus)


__all__ = ["NAME", "add_parser", "run"]
