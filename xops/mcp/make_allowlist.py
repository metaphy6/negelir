#!/usr/bin/env python3
"""Read-only Make-target MCP wrapper (Phase A scaffolding).

Status
------
**Stub.** This module declares the allow-list and the audit-log
shape for the future ``negelir-make`` MCP server, plus a
``list-tools`` CLI subcommand for inspection. The ``serve``
subcommand is intentionally a no-op until we add the MCP stdio
JSON-RPC loop in a follow-up sitting (see
``xops/mcp/README.md``).

Why scaffolded now
------------------
1. Locks the **allow-list** as code so it can't drift from
   ``.vscode/settings.json``.
2. Establishes the **dispatcher shape** (`AGENTS.md` §5) so the
   future implementation slots in mechanically.
3. Establishes the **audit-log path** (``xops/mcp/.trace/``,
   gitignored) so the contract is visible.

Hard rules
----------
- Read-only Make targets only. **No** mutating targets, **no**
  ``git`` (`AGENTS.md` Rule 9), **no** ``sudo`` callers.
- New tools require a doctrine update in
  ``docs/coding/ai/automation.md`` §5 first.
- Note: ``test.fast`` from the roadmap does not exist as a Make
  target; the wrapper exposes ``test.ai`` (Python-only fast
  suite) instead. Adjust the roadmap if a real ``test.fast``
  alias is added.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

from xops.makefile._common import REPO_ROOT, dispatch, info, ok, warn

TRACE_DIR = Path(__file__).resolve().parent / ".trace"

# Allow-list: tool name -> (Make target, human description).
# Mirrors the auto-approve list in .vscode/settings.json.
ALLOWED_TOOLS: Dict[str, Dict[str, str]] = {
    "track.list": {
        "target": "track.list",
        "description": "Show current phase status from docs/tracking/phases.csv.",
    },
    "track.show": {
        "target": "track.show",
        "description": "Show full history for one phase. Args: PHASE=N.",
    },
    "version.show": {
        "target": "version.show",
        "description": "Show project + component versions from xops/versioning/chart.json.",
    },
    "lint": {
        "target": "lint",
        "description": "Run repo lint suite (read-only).",
    },
    "mock.verify": {
        "target": "mock.verify",
        "description": "Offline integrity check of the Phase 2 mock seed corpus.",
    },
    "mock.sources": {
        "target": "mock.sources",
        "description": "List configured mock data sources.",
    },
    "help": {
        "target": "help",
        "description": "Print all Make targets with their docstrings.",
    },
    "status": {
        "target": "status",
        "description": "Print current dev-stack status.",
    },
    "health": {
        "target": "health",
        "description": "Probe service health endpoints.",
    },
    "hosts.preview": {
        "target": "hosts.preview",
        "description": "Show the mock hostnames managed by hosts.install.",
    },
    "test.ai": {
        "target": "test.ai",
        "description": "Run the Python AI test suite (fast).",
    },
}


def _trace(event: str, payload: Dict[str, object]) -> None:
    """Append an event to today's trace log (best-effort)."""
    TRACE_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc)
    record = {
        "ts": stamp.isoformat(timespec="seconds"),
        "event": event,
        **payload,
    }
    log_path = TRACE_DIR / f"{stamp.strftime('%Y-%m-%d')}.jsonl"
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def cmd_list_tools(_argv: List[str]) -> int:
    """Print the allow-list as JSON for inspection."""
    out = {
        name: {"target": meta["target"], "description": meta["description"]}
        for name, meta in ALLOWED_TOOLS.items()
    }
    print(json.dumps(out, indent=2, ensure_ascii=False))
    _trace("list-tools", {"count": len(out)})
    return 0


def cmd_serve(_argv: List[str]) -> int:
    """Start the MCP stdio server (not yet implemented)."""
    warn("xops/mcp/make_allowlist.py: serve is not yet implemented.")
    info(f"REPO_ROOT={REPO_ROOT}")
    info(f"Allow-list size: {len(ALLOWED_TOOLS)}")
    info("See xops/mcp/README.md for the implementation plan.")
    info("Tracking under docs/coding/ai/automation.md §5.1.")
    _trace("serve-stub", {"allowlist_size": len(ALLOWED_TOOLS)})
    return 1


def cmd_check(_argv: List[str]) -> int:
    """Sanity-check the allow-list against the Makefile."""
    makefile = REPO_ROOT / "Makefile"
    if not makefile.exists():
        warn(f"Makefile not found at {makefile}")
        return 1
    text = makefile.read_text(encoding="utf-8", errors="replace")
    missing = [
        name
        for name, meta in ALLOWED_TOOLS.items()
        if f"\n{meta['target']}:" not in text and f"{meta['target']}:" not in text.split("\n", 1)[0]
    ]
    if missing:
        warn(f"Allow-listed targets not found in Makefile: {missing}")
        return 1
    ok(f"All {len(ALLOWED_TOOLS)} allow-listed Make targets resolve.")
    _trace("check", {"missing": missing})
    return 0


COMMANDS = {
    "list-tools": cmd_list_tools,
    "serve": cmd_serve,
    "check": cmd_check,
}


def main(argv: List[str]) -> int:
    return dispatch(argv, COMMANDS, script_name=__file__)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
