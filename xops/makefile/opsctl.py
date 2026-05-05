#!/usr/bin/env python3
"""`make ops.*` — Phase 8 §8.1 ops console dispatcher.

Thin wrapper that shells out to ``python3 -m xops.opsctl <subcommand>``
so the Makefile stays one-line per target. Operator-supplied args
flow through the standard Make convention:

    make ops.denylist-clear TARGET=203.0.113.0/24

Adding a new subcommand is two edits: register a new ``cmd_*``
here AND add the ``ops.<name>`` Make target. The opsctl CLI itself
is the source of truth for argument shape.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import List

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from xops.makefile._common import dispatch, err  # noqa: E402

PYTHON = sys.executable or "python3"


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _run_opsctl(args: List[str]) -> int:
    """Invoke ``python -m xops.opsctl`` with the given argv tail."""
    cmd = [PYTHON, "-m", "xops.opsctl", *args]
    proc = subprocess.run(cmd, cwd=str(REPO_ROOT), check=False)
    return proc.returncode


def cmd_liveness(_argv: List[str]) -> int:
    """`make ops.liveness` — read-only smoke check (no bus publish)."""
    extra: List[str] = []
    if _env("JSON", "0") == "1":
        extra.append("--json")
    return _run_opsctl(["liveness", *extra])


def cmd_denylist_clear(_argv: List[str]) -> int:
    """`make ops.denylist-clear TARGET=<subject> [CLIENT_ID=<id>]`."""
    target = _env("TARGET")
    if not target:
        err("ops.denylist-clear: TARGET=<subject> is required")
        return 64
    args = ["denylist-clear", "--target", target]
    cid = _env("CLIENT_ID")
    if cid:
        args.extend(["--client-id", cid])
    if _env("DRY_RUN", "0") == "1":
        args.append("--dry-run")
    if _env("JSON", "0") == "1":
        args.append("--json")
    return _run_opsctl(args)


def cmd_quarantine_erase(_argv: List[str]) -> int:
    """`make ops.quarantine-erase TARGET=<sample_id> CONFIRM=<token>`."""
    target = _env("TARGET")
    if not target:
        err("ops.quarantine-erase: TARGET=<sample_id> is required")
        return 64
    args = ["quarantine-erase", "--target", target]
    confirm = _env("CONFIRM")
    if confirm:
        args.extend(["--confirm", confirm])
    cid = _env("CLIENT_ID")
    if cid:
        args.extend(["--client-id", cid])
    if _env("DRY_RUN", "0") == "1":
        args.append("--dry-run")
    if _env("JSON", "0") == "1":
        args.append("--json")
    return _run_opsctl(args)


def cmd_baseline_reset(_argv: List[str]) -> int:
    """`make ops.baseline-reset TARGET=<source_id>`."""
    target = _env("TARGET")
    if not target:
        err("ops.baseline-reset: TARGET=<source_id> is required")
        return 64
    args = ["baseline-reset", "--target", target]
    cid = _env("CLIENT_ID")
    if cid:
        args.extend(["--client-id", cid])
    if _env("DRY_RUN", "0") == "1":
        args.append("--dry-run")
    if _env("JSON", "0") == "1":
        args.append("--json")
    return _run_opsctl(args)


def cmd_quarantine_clear(_argv: List[str]) -> int:
    """`make ops.quarantine-clear TARGET=<sample_id>` (§8.7 consumer pending)."""
    target = _env("TARGET")
    if not target:
        err("ops.quarantine-clear: TARGET=<sample_id> is required")
        return 64
    args = ["quarantine-clear", "--target", target]
    cid = _env("CLIENT_ID")
    if cid:
        args.extend(["--client-id", cid])
    if _env("DRY_RUN", "0") == "1":
        args.append("--dry-run")
    if _env("JSON", "0") == "1":
        args.append("--json")
    return _run_opsctl(args)


def cmd_spool_flush(_argv: List[str]) -> int:
    """`make ops.spool-flush [MAX_ENTRIES=<n>]` — drain the bus-down spool."""
    args = ["spool-flush"]
    n = _env("MAX_ENTRIES")
    if n:
        args.extend(["--max-entries", n])
    if _env("DRY_RUN", "0") == "1":
        args.append("--dry-run")
    if _env("JSON", "0") == "1":
        args.append("--json")
    return _run_opsctl(args)


COMMANDS = {
    "liveness": cmd_liveness,
    "denylist-clear": cmd_denylist_clear,
    "baseline-reset": cmd_baseline_reset,
    "quarantine-clear": cmd_quarantine_clear,
    "quarantine-erase": cmd_quarantine_erase,
    "spool-flush": cmd_spool_flush,
}


if __name__ == "__main__":
    sys.exit(dispatch(sys.argv[1:], COMMANDS, "opsctl"))
