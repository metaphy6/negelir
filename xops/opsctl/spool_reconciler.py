"""Phase 8 §8.16.2 — spool-flush ack reconciler.

Walks the opsctl audit CSV, identifies ``op=spool-flush`` rows
where ``received_acks < expected_acks``, and reports those whose
age exceeds ``cfg.opsctl_spool_ack_max_wait_h``. Read-only; never
mutates the audit log.

Used by:
  * ``make ops.spool-reconcile`` (operator-driven)
  * ``ai.swarm.agents.maint.deadmans`` cron-style hook (future)

Exit codes:
  * 0 — clean (no stale incomplete rows)
  * 9 — at least one stale incomplete row (operator attention)

Output is deterministic JSON when ``--json`` is given, otherwise a
short human-readable summary.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

from ai.common.config import Config

EXIT_OK = 0
EXIT_INCOMPLETE = 9
EXIT_USAGE = 64

_OP = "spool-flush"


@dataclass(frozen=True)
class IncompleteRow:
    timestamp_utc: str
    request_id: str
    target: str
    expected_acks: int
    received_acks: int
    age_s: int
    note: str

    def as_dict(self) -> dict[str, object]:
        return {
            "timestamp_utc": self.timestamp_utc,
            "request_id": self.request_id,
            "target": self.target,
            "expected_acks": self.expected_acks,
            "received_acks": self.received_acks,
            "age_s": self.age_s,
            "note": self.note,
        }


def _parse_iso(ts: str) -> Optional[datetime]:
    try:
        # Audit timestamps use ``isoformat(timespec='seconds')`` in UTC.
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def scan(
    audit_path: Path,
    *,
    horizon_s: int,
    now: Optional[datetime] = None,
) -> list[IncompleteRow]:
    """Return all ``op=spool-flush`` rows where acks are incomplete
    and the row's age exceeds ``horizon_s`` seconds.

    Robust against malformed rows: a row that fails to parse is
    silently skipped (the operator's eyes-on alert path is
    sec.alert, not the reconciler).
    """
    if not audit_path.exists():
        return []
    now_utc = now if now is not None else datetime.now(timezone.utc)
    out: list[IncompleteRow] = []
    with audit_path.open("r", newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            if (row.get("op") or "").strip() != _OP:
                continue
            try:
                expected = int(row.get("expected_acks") or 0)
                received = int(row.get("received_acks") or 0)
            except ValueError:
                continue
            if received >= expected:
                continue
            ts = (row.get("timestamp_utc") or "").strip()
            dt = _parse_iso(ts)
            if dt is None:
                continue
            age_s = int((now_utc - dt).total_seconds())
            if age_s < horizon_s:
                continue
            out.append(IncompleteRow(
                timestamp_utc=ts,
                request_id=(row.get("request_id") or "-").strip(),
                target=(row.get("target") or "-").strip(),
                expected_acks=expected,
                received_acks=received,
                age_s=age_s,
                note=(row.get("note") or "").strip(),
            ))
    return out


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="opsctl-spool-reconcile",
        description=(
            "Phase 8 §8.16.2 — scan opsctl audit for stale "
            "incomplete spool-flush ack reconciliations."
        ),
    )
    p.add_argument(
        "--audit-path",
        default="",
        help="Override audit CSV path (default: cfg.opsctl_audit_path_resolved).",
    )
    p.add_argument(
        "--horizon-h",
        type=int,
        default=-1,
        help="Override threshold in hours (default: cfg.opsctl_spool_ack_max_wait_h).",
    )
    p.add_argument("--json", action="store_true", help="Emit JSON on stdout.")
    return p


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    cfg = Config()
    audit_path = Path(args.audit_path or cfg.opsctl_audit_path_resolved)
    horizon_h = args.horizon_h if args.horizon_h >= 0 else int(cfg.opsctl_spool_ack_max_wait_h)
    horizon_s = max(1, horizon_h) * 3600

    rows = scan(audit_path, horizon_s=horizon_s)

    if args.json:
        sys.stdout.write(json.dumps({
            "audit_path": str(audit_path),
            "horizon_h": horizon_h,
            "incomplete_count": len(rows),
            "rows": [r.as_dict() for r in rows],
        }, sort_keys=True, ensure_ascii=False))
        sys.stdout.write("\n")
    else:
        sys.stdout.write(
            f"opsctl spool-reconcile audit={audit_path} horizon_h={horizon_h} "
            f"incomplete={len(rows)}\n"
        )
        for r in rows:
            sys.stdout.write(
                f"  [{r.timestamp_utc}] req={r.request_id} target={r.target} "
                f"acks={r.received_acks}/{r.expected_acks} age_s={r.age_s}\n"
            )

    return EXIT_INCOMPLETE if rows else EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = ["IncompleteRow", "scan", "main", "EXIT_OK", "EXIT_INCOMPLETE"]
