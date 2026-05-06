"""Phase 8 §8.16.3 — prune-order doctrine proof tests."""
from __future__ import annotations

import pytest

from xops.maint.prune_order import PRUNE_ORDER, PruneOrderError, topo_check


def test_prune_order_canonical_sequence() -> None:
    """ROADMAP §8.16.3 names this exact ordering — pin it."""
    assert PRUNE_ORDER == (
        "opsctl_audit",
        "schema_snapshots",
        "pattern_allowlist",
        "dlq_entries",
        "quarantine_samples",
        "maint_audit_log",
    )


def test_prune_order_has_no_duplicates() -> None:
    assert len(PRUNE_ORDER) == len(set(PRUNE_ORDER))


def test_topo_check_accepts_valid_dag() -> None:
    fk_dag = {
        "opsctl_audit":       frozenset({"maint_audit_log"}),
        "schema_snapshots":   frozenset(),
        "pattern_allowlist":  frozenset({"maint_audit_log"}),
        "dlq_entries":        frozenset(),
        "quarantine_samples": frozenset({"maint_audit_log"}),
        "maint_audit_log":    frozenset(),
    }
    topo_check(fk_dag)  # must not raise


def test_topo_check_rejects_inverted_edge() -> None:
    """If maint_audit_log claims to reference quarantine_samples, the
    canonical order would prune the referenced row first → violation."""
    bad = {
        "maint_audit_log": frozenset({"quarantine_samples"}),
    }
    with pytest.raises(PruneOrderError, match="prune-order violation"):
        topo_check(bad)


def test_topo_check_rejects_unknown_table_in_dag() -> None:
    bad = {
        "mystery_table": frozenset({"maint_audit_log"}),
    }
    with pytest.raises(PruneOrderError, match="not in PRUNE_ORDER"):
        topo_check(bad)


def test_topo_check_rejects_unknown_target() -> None:
    bad = {
        "opsctl_audit": frozenset({"mystery_target"}),
    }
    with pytest.raises(PruneOrderError, match="not in PRUNE_ORDER"):
        topo_check(bad)
