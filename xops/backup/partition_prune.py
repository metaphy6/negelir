"""§8.14.1 — O(1) partition prune for maint_audit_log.

Replaces per-row DELETE with:
  1. ALTER TABLE <parent> DETACH PARTITION <name> CONCURRENTLY
  2. DROP TABLE <name>   (only after detach; never holds row locks)

Both the standard family (maint_audit_log_YYYY_MM) and the PII sibling
family (maint_audit_log_pii_YYYY_MM) are walked; each uses the
appropriate cutoff:
  - standard:  retention_days  (cfg.maint_audit_retention_days, default 365)
  - pii family: pii_retention_days (cfg.maint_audit_retention_days_overrides
                                      ["pii_erased"], default 2555)

The caller injects a cursor for testability — no live PG is required in
tests; pass a mock or sqlite3 cursor wrapped by a thin adapter.

The pruner role (negelir_audit_pruner) must be SET before calling this
function when running against a live database:
    conn.execute("SET ROLE negelir_audit_pruner")

Dry-run mode records the operations it *would* perform without executing
the destructive DDL — safe to use in dev/CI environments.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional, Protocol


# ── public types ─────────────────────────────────────────────────────────────

@dataclass
class PartitionPruneResult:
    """Summary of a single prune pass over both audit partition families."""
    detached: List[str] = field(default_factory=list)  # names successfully detached
    dropped:  List[str] = field(default_factory=list)  # names successfully dropped
    skipped:  List[str] = field(default_factory=list)  # names skipped (too recent / error)

    @property
    def total(self) -> int:
        return len(self.dropped)


class _Cursor(Protocol):
    """Minimal cursor protocol; real psycopg2 and mock objects both satisfy it."""
    def execute(self, sql: str, params: object = None) -> None: ...
    def fetchall(self) -> list: ...


# ── internals ────────────────────────────────────────────────────────────────

_PARTITION_RE = re.compile(
    r"^(maint_audit_log(?:_pii)?)_(\d{4})_(\d{2})$"
)

_PARENT_OF: dict[str, str] = {
    "maint_audit_log":     "maint_audit_log",
    "maint_audit_log_pii": "maint_audit_log_pii",
}


def _list_monthly_partitions(cur: _Cursor) -> List[str]:
    """Return all maint_audit_log_YYYY_MM and maint_audit_log_pii_YYYY_MM names.

    Queries pg_inherits + pg_class. In tests, the caller pre-populates
    the mock cursor's fetchall return value instead.
    """
    cur.execute(
        """
        SELECT c.relname
        FROM   pg_inherits i
        JOIN   pg_class    c ON c.oid = i.inhrelid
        JOIN   pg_class    p ON p.oid = i.inhparent
        WHERE  p.relname IN ('maint_audit_log', 'maint_audit_log_pii')
          AND  c.relname  ~ '^maint_audit_log(_pii)?_[0-9]{4}_[0-9]{2}$'
        ORDER  BY c.relname
        """
    )
    return [row[0] for row in cur.fetchall()]


def _partition_month(name: str) -> Optional[date]:
    """Parse YYYY_MM suffix of a partition name → first day of that month."""
    m = _PARTITION_RE.match(name)
    if not m:
        return None
    try:
        return date(int(m.group(2)), int(m.group(3)), 1)
    except ValueError:
        return None


def _is_pii_family(name: str) -> bool:
    return name.startswith("maint_audit_log_pii_")


def _cutoff_date(retention_days: int, now: datetime) -> date:
    return (now - timedelta(days=retention_days)).date()


# ── public API ───────────────────────────────────────────────────────────────

def prune_audit_partitions(
    cur: _Cursor,
    *,
    retention_days: int = 365,
    pii_retention_days: int = 2555,
    now: Optional[datetime] = None,
    dry_run: bool = False,
    partition_names: Optional[List[str]] = None,
) -> PartitionPruneResult:
    """Detach-and-drop expired audit partitions.

    Args:
        cur:               DI-injected DB cursor (must be connected as pruner
                           role in production).
        retention_days:    Standard-family cutoff in calendar days.
        pii_retention_days: PII-family cutoff in calendar days.
        now:               Override current UTC time (useful in tests).
        dry_run:           When True, compute the would-prune list but do not
                           execute any DDL.
        partition_names:   Explicit list of partition names (bypasses the
                           pg_inherits query; inject in tests).

    Returns:
        PartitionPruneResult with detached / dropped / skipped lists.
    """
    if now is None:
        now = datetime.now(tz=timezone.utc)

    std_cutoff = _cutoff_date(retention_days, now)
    pii_cutoff = _cutoff_date(pii_retention_days, now)

    names = partition_names if partition_names is not None else _list_monthly_partitions(cur)

    result = PartitionPruneResult()

    for name in sorted(names):
        month_start = _partition_month(name)
        if month_start is None:
            result.skipped.append(name)
            continue

        # A partition whose entire month-range falls before the cutoff is expired.
        # We use the first day of the *next* month as the partition upper bound.
        if month_start.month == 12:
            next_month = date(month_start.year + 1, 1, 1)
        else:
            next_month = date(month_start.year, month_start.month + 1, 1)

        cutoff = pii_cutoff if _is_pii_family(name) else std_cutoff

        if next_month > cutoff:
            # Partition contains rows newer than the cutoff — keep it.
            result.skipped.append(name)
            continue

        parent = (
            "maint_audit_log_pii" if _is_pii_family(name) else "maint_audit_log"
        )

        if not dry_run:
            # Step 1 — detach concurrently (no table lock on the parent).
            # CONCURRENTLY is only valid outside a transaction block; the
            # caller is responsible for not wrapping this in BEGIN/COMMIT
            # when using CONCURRENTLY mode on real PG.
            cur.execute(
                f"ALTER TABLE {parent} DETACH PARTITION {name} CONCURRENTLY"
            )
            result.detached.append(name)

            # Step 2 — drop the now-detached orphan table.
            cur.execute(f"DROP TABLE {name}")
            result.dropped.append(name)
        else:
            # Dry-run: record intent only.
            result.detached.append(name)
            result.dropped.append(name)

    return result
