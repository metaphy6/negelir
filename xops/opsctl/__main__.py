"""``python -m xops.opsctl`` — Phase 8 §8.1 ops console entry point.

The CLI is intentionally argparse-only (no third-party deps) so it
ships in the operator's stdlib-only Python and the boundary scan
in ``test_opsctl_boundary.py`` does not need to allow extra imports.
"""
from __future__ import annotations

import argparse
import sys
from typing import Optional, Sequence

from ._exit_codes import ExitCode
from .subcommands import SUBCOMMANDS


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="xops.opsctl",
        description=(
            "Negelir ops console (Phase 8 §8.1). Publishes maint.event.v1 "
            "envelopes and waits for maint.ack.v1 replies from the "
            "registered consumers."
        ),
    )
    subparsers = parser.add_subparsers(dest="subcommand", required=True)
    for mod in SUBCOMMANDS:
        mod.add_parser(subparsers)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    func = getattr(args, "func", None)
    if func is None:
        parser.print_help(sys.stderr)
        return int(ExitCode.BAD_USAGE)
    # bus=None ⇒ subcommand decides whether to construct a default
    # (currently: spool fallback). Tests inject a bus by calling
    # ``run(args, bus=...)`` directly; that wiring lands in §8.1.b.
    return int(func(args))


if __name__ == "__main__":  # pragma: no cover — invoked via -m
    raise SystemExit(main())
