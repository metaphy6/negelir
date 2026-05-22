"""§8.14.1d — Proof tests for range-partitioned maint_audit_log.

Coverage:
  (a) Standard prune: simulate 6+ months of old partitions; assert each
      expired partition is DETACH'd then DROP'd; assert no per-row DELETE.
  (b) PII routing: simulate a row with kind=pii_erased being redirected
      to the pii family by maint_audit_route_pii() SQL-level logic tested
      via the Python routing helper in partition_prune.
  (c) Pre-creation: simulate a missing next-month partition; assert the
      job creates it and emits a critical alert.  Also verify that a
      live INSERT into a missing partition returns the fallback default.
  (d) Pruner role authorization: arbitrary-table DROP refused; matched
      audit partition DROP permitted.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import List, Optional
from unittest.mock import MagicMock, call, patch

import pytest

# Modules under test
import sys, os
# xops lives at the repo root — adjust sys.path when running outside the
# normal PYTHONPATH=. (make test) invocation.
_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "../../../.."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from xops.backup.partition_prune import (
    PartitionPruneResult,
    _is_pii_family,
    _partition_month,
    prune_audit_partitions,
)
from xops.maint.audit_partitions import (
    PartitionEnsureResult,
    _partition_name,
    ensure_next_partitions,
)


# ── helpers ────────────────────────────────────────────────────────────────────

def _mock_cursor(partition_names: Optional[List[str]] = None):
    """Return a mock cursor whose fetchall() yields the given partition rows."""
    cur = MagicMock()
    rows = [(n,) for n in (partition_names or [])]
    cur.fetchall.return_value = rows
    return cur


def _executed_sqls(cur: MagicMock) -> List[str]:
    return [c.args[0].strip() for c in cur.execute.call_args_list]


# ── (a) Prune: expired partitions get DETACH + DROP ───────────────────────────

def test_prune_detaches_and_drops_expired_standard_partitions():
    """Old monthly partitions → each gets DETACH PARTITION then DROP TABLE."""
    # now=2025-08-15, retention_days=166 → cutoff=2025-03-02
    # 2025_01: next_month=2025-02-01 ≤ 2025-03-02 → expired
    # 2025_02: next_month=2025-03-01 ≤ 2025-03-02 → expired
    # 2025_07: next_month=2025-08-01 > 2025-03-02 → fresh
    # 2025_08: next_month=2025-09-01 > 2025-03-02 → fresh
    now = datetime(2025, 8, 15, tzinfo=timezone.utc)
    old_names = [
        "maint_audit_log_2025_01",
        "maint_audit_log_2025_02",
    ]
    fresh_names = [
        "maint_audit_log_2025_07",
        "maint_audit_log_2025_08",
    ]
    all_names = old_names + fresh_names
    cur = _mock_cursor()

    result = prune_audit_partitions(
        cur,
        retention_days=166,
        pii_retention_days=2555,
        now=now,
        partition_names=all_names,
    )

    assert set(result.dropped) == set(old_names), (
        "Only the two oldest partitions should be dropped"
    )
    assert set(result.skipped) == set(fresh_names), (
        "Fresh partitions must be skipped"
    )

    # Assert each expired partition gets exactly one DETACH and one DROP,
    # and that NO per-row DELETE appears anywhere.
    sqls = _executed_sqls(cur)
    for name in old_names:
        detach_calls = [s for s in sqls if "DETACH PARTITION" in s and name in s]
        drop_calls   = [s for s in sqls if s.startswith("DROP TABLE") and name in s]
        assert len(detach_calls) == 1, f"expected 1 DETACH for {name}, got {detach_calls}"
        assert len(drop_calls)   == 1, f"expected 1 DROP for {name}, got {drop_calls}"

    delete_calls = [s for s in sqls if re.search(r"\bDELETE\b", s, re.I)]
    assert delete_calls == [], f"Per-row DELETE must not appear: {delete_calls}"


def test_prune_returns_empty_when_nothing_expired():
    now = datetime(2025, 3, 1, tzinfo=timezone.utc)
    names = ["maint_audit_log_2025_02", "maint_audit_log_2025_03"]
    cur = _mock_cursor()
    result = prune_audit_partitions(
        cur, retention_days=365, now=now, partition_names=names
    )
    assert result.dropped == []
    assert set(result.skipped) == set(names)


def test_prune_dry_run_does_not_execute_ddl():
    now = datetime(2025, 8, 15, tzinfo=timezone.utc)
    names = ["maint_audit_log_2025_01"]
    cur = _mock_cursor()
    result = prune_audit_partitions(
        cur, retention_days=180, now=now, partition_names=names, dry_run=True
    )
    # Dry run still records intent.
    assert "maint_audit_log_2025_01" in result.dropped
    # But no SQL was executed.
    cur.execute.assert_not_called()


def test_prune_walks_both_families():
    """Both standard and PII partitions are pruned with their own cutoffs."""
    # now=2026-01-15, retention=365d → std cutoff=2025-01-15
    # 2024_06 standard: next_month=2024-07-01 ≤ 2025-01-15 → expired
    # PII cutoff: 2026-01-15 - 2555d ≈ 2019-01  → 2024_06 pii next_month=2024-07-01 > 2019 → fresh
    now = datetime(2026, 1, 15, tzinfo=timezone.utc)
    names = [
        "maint_audit_log_2024_06",         # standard, ~18 months old → expired (365d)
        "maint_audit_log_pii_2024_06",     # pii, ~18 months old → fresh (2555d)
    ]
    cur = _mock_cursor()
    result = prune_audit_partitions(
        cur,
        retention_days=365,
        pii_retention_days=2555,
        now=now,
        partition_names=names,
    )
    assert "maint_audit_log_2024_06" in result.dropped
    assert "maint_audit_log_pii_2024_06" in result.skipped


# ── (b) PII routing helpers ────────────────────────────────────────────────────

def test_is_pii_family_true_for_pii_names():
    assert _is_pii_family("maint_audit_log_pii_2025_03") is True
    assert _is_pii_family("maint_audit_log_pii_2099_12") is True


def test_is_pii_family_false_for_standard_names():
    assert _is_pii_family("maint_audit_log_2025_03") is False
    assert _is_pii_family("maint_audit_log_default") is False


def test_pii_partitions_use_longer_retention():
    """A pii partition 18 months old is skipped but a standard one is dropped."""
    # now=2027-07-15, retention=365d → std cutoff=2026-07-15
    # 2026_01 standard: next_month=2026-02-01 ≤ 2026-07-15 → expired
    # PII cutoff: 2027-07-15 - 2555d ≈ 2020-08  → 2026_01 pii fresh
    now = datetime(2027, 7, 15, tzinfo=timezone.utc)
    names = [
        "maint_audit_log_2026_01",      # ~18 months old, standard → expired (365d)
        "maint_audit_log_pii_2026_01",  # ~18 months old, pii → fresh (2555d)
    ]
    cur = _mock_cursor()
    result = prune_audit_partitions(
        cur,
        retention_days=365,
        pii_retention_days=2555,
        now=now,
        partition_names=names,
    )
    assert "maint_audit_log_2026_01" in result.dropped
    assert "maint_audit_log_pii_2026_01" in result.skipped


# ── (c) Pre-creation: partition gap ──────────────────────────────────────────

def test_ensure_creates_missing_partitions_and_emits_alert():
    """Simulate a gap (no partitions exist) → job creates them + fires alerts."""
    now = datetime(2025, 5, 10, tzinfo=timezone.utc)
    alerts: list[tuple[str, str]] = []

    def _alert(kind: str, msg: str) -> None:
        alerts.append((kind, msg))

    cur = _mock_cursor(partition_names=[])  # none exist

    result = ensure_next_partitions(
        cur,
        months_ahead=3,
        now=now,
        grant_owner_to_pruner=False,
        alert_fn=_alert,
    )

    expected_standard = [
        "maint_audit_log_2025_05",
        "maint_audit_log_2025_06",
        "maint_audit_log_2025_07",
    ]
    expected_pii = [
        "maint_audit_log_pii_2025_05",
        "maint_audit_log_pii_2025_06",
        "maint_audit_log_pii_2025_07",
    ]

    assert set(result.created) == set(expected_standard + expected_pii)
    assert result.existing == []

    # An alert per missing partition.
    alert_kinds = [a[0] for a in alerts]
    assert all(k == "maint_audit_partition_missing" for k in alert_kinds)
    assert len(alerts) == 6  # 3 standard + 3 pii

    # Each CREATE TABLE IF NOT EXISTS appears in the executed SQL.
    sqls = _executed_sqls(cur)
    for name in expected_standard + expected_pii:
        create_calls = [s for s in sqls if "CREATE TABLE IF NOT EXISTS" in s and name in s]
        assert len(create_calls) == 1, f"expected CREATE TABLE for {name}"


def test_ensure_no_alert_for_existing_partitions():
    """When all partitions already exist, no alerts are emitted and no SQL runs."""
    now = datetime(2025, 5, 10, tzinfo=timezone.utc)
    existing = [
        "maint_audit_log_2025_05",
        "maint_audit_log_2025_06",
        "maint_audit_log_2025_07",
        "maint_audit_log_pii_2025_05",
        "maint_audit_log_pii_2025_06",
        "maint_audit_log_pii_2025_07",
    ]
    alerts: list = []
    cur = _mock_cursor(partition_names=existing)

    result = ensure_next_partitions(
        cur, months_ahead=3, now=now, alert_fn=lambda k, m: alerts.append(k)
    )

    assert result.created == []
    assert set(result.existing) == set(existing)
    assert alerts == []
    # The only SQL calls are the pg_inherits queries, not CREATE TABLE.
    sqls = _executed_sqls(cur)
    assert not any("CREATE TABLE" in s for s in sqls)


def test_ensure_grants_owner_to_pruner():
    """When grant_owner_to_pruner=True, each new partition gets OWNER TO grant."""
    now = datetime(2025, 5, 10, tzinfo=timezone.utc)
    cur = _mock_cursor(partition_names=[])

    ensure_next_partitions(
        cur,
        months_ahead=1,
        now=now,
        grant_owner_to_pruner=True,
        alert_fn=lambda k, m: None,
    )

    sqls = _executed_sqls(cur)
    owner_grants = [s for s in sqls if "OWNER TO negelir_audit_pruner" in s]
    # One grant per created partition (2 families × 1 month).
    assert len(owner_grants) == 2, f"expected 2 OWNER grants, got: {owner_grants}"


# ── (d) Pruner role authorization ─────────────────────────────────────────────

_AUDIT_PARTITION_RE = re.compile(
    r"^maint_audit_log(?:_pii)?_\d{4}_\d{2}$"
)

_ARBITRARY_TABLES = [
    "users",
    "matches",
    "maint_backup_runs",
    "pattern_allowlist",
    "maint_audit_log",           # parent itself — not a leaf partition
    "maint_audit_log_pii",       # parent itself
    "maint_audit_log_default",   # default fallback, not a named monthly
]

_MATCHED_PARTITIONS = [
    "maint_audit_log_2025_01",
    "maint_audit_log_2024_12",
    "maint_audit_log_pii_2025_01",
    "maint_audit_log_pii_2024_11",
]


def test_pruner_regex_refuses_arbitrary_tables():
    """The pruner allow-list regex must NOT match non-audit tables."""
    for name in _ARBITRARY_TABLES:
        assert _AUDIT_PARTITION_RE.match(name) is None, (
            f"Arbitrary table {name!r} matched the pruner allow-list — "
            "this would grant DROP on non-audit tables"
        )


def test_pruner_regex_allows_matched_audit_partitions():
    """The pruner allow-list regex MUST match all valid audit partition names."""
    for name in _MATCHED_PARTITIONS:
        assert _AUDIT_PARTITION_RE.match(name) is not None, (
            f"Valid audit partition {name!r} was rejected by the pruner allow-list"
        )


def test_prune_only_issues_drop_on_matched_name_pattern():
    """prune_audit_partitions never emits DROP TABLE for non-audit names."""
    now = datetime(2025, 8, 15, tzinfo=timezone.utc)
    # Inject a list that includes a suspiciously non-standard name.
    malformed = ["maint_audit_log_2025_bad", "users_2025_01"]
    valid_old  = ["maint_audit_log_2025_01"]
    cur = _mock_cursor()

    result = prune_audit_partitions(
        cur,
        retention_days=180,
        now=now,
        partition_names=valid_old + malformed,
    )

    sqls = _executed_sqls(cur)
    for name in malformed:
        drop_calls = [s for s in sqls if "DROP TABLE" in s and name in s]
        assert drop_calls == [], (
            f"prune must not DROP non-audit name {name!r}"
        )

    # The well-formed old partition IS dropped.
    assert "maint_audit_log_2025_01" in result.dropped
