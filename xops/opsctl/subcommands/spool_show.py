"""``ops.spool-show`` — Phase 8 §8.1 read-only spool inspector.

Lists envelopes pending in the bus-down spool directory without
modifying or replaying them. SAFE tier (read-only); does not
publish to the bus, does not write to the audit log.

Output formats:
* default: table-style ``<filename>  <kind>  <target>  <produced_at>``
* ``--json``: deterministic array of objects, sorted by filename
  (which is timestamp-prefixed so this is also chronological).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional

from ai.common.config import Config

from .._exit_codes import ExitCode

NAME = "spool-show"


def add_parser(
    subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]",
) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help="List envelopes pending in the bus-down spool (read-only).",
        description=(
            "Inspects cfg.opsctl_spool_dir without consuming or "
            "replaying any envelopes. Use ops.spool-flush to drain."
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Cap the number of entries shown (default: 100).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit a JSON array on stdout (deterministic).",
    )
    parser.set_defaults(func=run)
    return parser


def run(args: argparse.Namespace, *, bus: Optional[Any] = None) -> int:
    cfg = Config()
    spool_dir = Path(cfg.opsctl_spool_dir_resolved)
    limit = max(1, int(getattr(args, "limit", 100) or 100))

    entries: list[dict[str, Any]] = []
    if spool_dir.exists():
        for p in sorted(spool_dir.glob("*.envelope.json"))[:limit]:
            row: dict[str, Any] = {"file": p.name}
            try:
                doc = json.loads(p.read_text())
                payload = doc.get("payload") or {}
                env = doc.get("envelope") or {}
                row["kind"] = payload.get("kind", "")
                row["target"] = payload.get("target", "")
                row["produced_at"] = payload.get("produced_at", "")
                row["request_id"] = payload.get("request_id", "")
                row["topic"] = env.get("topic", "")
            except (OSError, json.JSONDecodeError) as exc:
                row["error"] = f"unreadable: {exc.__class__.__name__}"
            entries.append(row)

    if getattr(args, "json", False):
        sys.stdout.write(json.dumps(
            {"spool_dir": str(spool_dir), "count": len(entries), "entries": entries},
            sort_keys=True, ensure_ascii=False,
        ))
        sys.stdout.write("\n")
    else:
        sys.stdout.write(f"opsctl spool-show dir={spool_dir} count={len(entries)}\n")
        for row in entries:
            sys.stdout.write(
                f"  {row.get('file', '?')}  kind={row.get('kind', '?')}  "
                f"target={row.get('target', '?')}  "
                f"produced_at={row.get('produced_at', '?')}\n"
            )
    return int(ExitCode.OK)


__all__ = ["NAME", "add_parser", "run"]
