"""Phase 8 §8.16.3 — destructive-prune ordering doctrine.

The audit ledger and the tables it references must never be pruned
in an order that leaves dangling foreign-key references, even
transiently inside a single maintenance run. ROADMAP §8.16.3 names
the canonical order; this module is the single source of truth so
the backup agent and any future cron path read the same list.

Order rationale (top = pruned first, bottom = pruned last):

1. ``opsctl_audit``       — operator command audit; references
                            ``maint_audit_log`` rows by trace_id.
2. ``schema_snapshots``   — references migration epochs.
3. ``pattern_allowlist``  — references ``maint_audit_log`` for
                            promotion provenance.
4. ``dlq_entries``        — references original-topic envelopes;
                            the ledger row outlives the entry.
5. ``quarantine_samples`` — references the ``maint_audit_log``
                            erasure proof row.
6. ``maint_audit_log``    — the ledger itself; pruned LAST so every
                            referencing row above is already gone.

The :func:`topo_check` helper accepts a caller-supplied DAG of
table → set-of-tables-it-references and verifies the order is a
valid reverse-topological cut (i.e. every table appears AFTER the
tables that reference it). This catches the obvious bug where a new
table is added with a stale references-column but the canonical
order was forgotten.
"""
from __future__ import annotations

from typing import Final, Mapping


PRUNE_ORDER: Final[tuple[str, ...]] = (
    "opsctl_audit",
    "schema_snapshots",
    "pattern_allowlist",
    "dlq_entries",
    "quarantine_samples",
    "maint_audit_log",
)


class PruneOrderError(ValueError):
    """Raised when :func:`topo_check` finds a violation."""


def topo_check(fk_dag: Mapping[str, frozenset[str]],
               order: tuple[str, ...] = PRUNE_ORDER) -> None:
    """Verify ``order`` is a valid reverse-topological cut of ``fk_dag``.

    ``fk_dag`` maps each table to the SET of tables IT REFERENCES
    (outgoing FK edges). For every edge ``A -> B`` we require
    ``order.index(A) < order.index(B)`` — i.e. A is pruned before B,
    so B never has a dangling row pointing at it from A.

    Tables that appear in ``fk_dag`` but not in ``order`` are
    treated as a configuration bug and raise — silent omission of a
    table from the prune order is the failure mode this guard
    exists to catch.
    """
    pos = {name: i for i, name in enumerate(order)}
    for source, refs in fk_dag.items():
        if source not in pos:
            raise PruneOrderError(
                f"table {source!r} appears in fk_dag but not in PRUNE_ORDER"
            )
        for target in refs:
            if target not in pos:
                raise PruneOrderError(
                    f"table {source!r} references {target!r} which is not "
                    f"in PRUNE_ORDER (add it or drop the FK)"
                )
            if pos[source] >= pos[target]:
                raise PruneOrderError(
                    f"prune-order violation: {source!r} (idx={pos[source]}) "
                    f"references {target!r} (idx={pos[target]}); "
                    f"{source!r} must be pruned BEFORE {target!r}"
                )


__all__ = ["PRUNE_ORDER", "PruneOrderError", "topo_check"]
