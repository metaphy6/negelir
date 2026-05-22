"""§8.14.1c — Partition pre-creation for maint_audit_log.

Runs at the §8.3 cron tick (before the dump) to ensure the next
``months_ahead`` (default 3) monthly partitions exist for both:
  - the standard family  : maint_audit_log_YYYY_MM
  - the PII sibling family: maint_audit_log_pii_YYYY_MM

If a partition is missing at INSERT time, PG raises
``no_partition_of_relation_for_row``.  The agent's response:
  1. Emit ``sec.alert.v1{kind=maint_audit_partition_missing,
                         severity=critical}`` via the optional
     ``alert_fn`` callback.
  2. Fall back to the ``maint_audit_log_default`` partition (which
     absorbs the row); the default partition is included in the next
     prune cycle and re-distributed when the named partition is
     created.

Caller injects a cursor for testability (no live PG in CI).

For PG 14 (no MAINTAIN privilege) the job also runs
``ALTER TABLE <partition> OWNER TO negelir_audit_pruner`` after each
``CREATE TABLE``, so the pruner can DETACH and DROP the partition.
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Callable, List, Optional, Protocol


# ── types ─────────────────────────────────────────────────────────────────────

class _Cursor(Protocol):
    def execute(self, sql: str, params: object = None) -> None: ...
    def fetchall(self) -> list: ...


AlertFn = Callable[[str, str], None]  # (kind, message) → None


@dataclass
class PartitionEnsureResult:
    created:  List[str] = field(default_factory=list)   # newly created partition names
    existing: List[str] = field(default_factory=list)   # already present (no-op)


# ── helpers ───────────────────────────────────────────────────────────────────

_FAMILIES = ("maint_audit_log", "maint_audit_log_pii")


def _next_month(d: date) -> date:
    """Return the first day of the month following ``d``."""
    if d.month == 12:
        return date(d.year + 1, 1, 1)
    return date(d.year, d.month + 1, 1)


def _partition_name(parent: str, month_start: date) -> str:
    return f"{parent}_{month_start.year:04d}_{month_start.month:02d}"


def _months_starting(from_month: date, count: int) -> List[date]:
    """Return ``count`` consecutive month-start dates beginning at ``from_month``."""
    result: List[date] = []
    cur = from_month
    for _ in range(count):
        result.append(cur)
        cur = _next_month(cur)
    return result


def _existing_partitions(cur: _Cursor, parent: str) -> frozenset[str]:
    cur.execute(
        """
        SELECT c.relname
        FROM   pg_inherits i
        JOIN   pg_class    c ON c.oid = i.inhrelid
        JOIN   pg_class    p ON p.oid = i.inhparent
        WHERE  p.relname = %s
        """,
        (parent,),
    )
    return frozenset(row[0] for row in cur.fetchall())


# ── public API ────────────────────────────────────────────────────────────────

def ensure_next_partitions(
    cur: _Cursor,
    *,
    months_ahead: int = 3,
    now: Optional[datetime] = None,
    grant_owner_to_pruner: bool = True,
    alert_fn: Optional[AlertFn] = None,
) -> PartitionEnsureResult:
    """Create the next ``months_ahead`` monthly partitions for both families.

    Args:
        cur:                  DI-injected DB cursor.
        months_ahead:         How many future months to guarantee (incl.
                              current month).
        now:                  Override current UTC time (useful in tests).
        grant_owner_to_pruner: When True, issue
                              ``ALTER TABLE … OWNER TO negelir_audit_pruner``
                              after each ``CREATE TABLE`` (required on PG 14
                              where MAINTAIN privilege is absent).
        alert_fn:             Optional callback for missing-partition alerts.
                              Signature: ``(kind: str, message: str) → None``.
                              When None, alerts are silently dropped.

    Returns:
        PartitionEnsureResult(created, existing).
    """
    if now is None:
        now = datetime.now(tz=timezone.utc)

    today = now.date()
    current_month_start = date(today.year, today.month, 1)
    target_months = _months_starting(current_month_start, months_ahead)

    result = PartitionEnsureResult()

    for parent in _FAMILIES:
        try:
            existing = _existing_partitions(cur, parent)
        except Exception:
            # pg_inherits not available (e.g. SQLite mock) — treat all as missing.
            existing = frozenset()

        for month_start in target_months:
            name = _partition_name(parent, month_start)
            lo = month_start.isoformat()
            hi = _next_month(month_start).isoformat()

            if name in existing:
                result.existing.append(name)
                continue

            # Partition is missing — emit alert before creation (§8.14.1c).
            if alert_fn is not None:
                alert_fn(
                    "maint_audit_partition_missing",
                    (
                        f"Creating missing audit partition {name!r} "
                        f"({lo} .. {hi}); default partition absorbs rows "
                        f"until this partition is attached."
                    ),
                )

            cur.execute(
                f"CREATE TABLE IF NOT EXISTS {name} "
                f"PARTITION OF {parent} "
                f"FOR VALUES FROM ('{lo}') TO ('{hi}')"
            )

            if grant_owner_to_pruner:
                cur.execute(
                    f"ALTER TABLE {name} OWNER TO negelir_audit_pruner"
                )

            result.created.append(name)

    return result
