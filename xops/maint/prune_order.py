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

:class:`PruneOrderValidator` provides the same check under the
``fail_safe_prune_order_invalid`` doctrine name (ROADMAP §8.16.3)
via :meth:`PruneOrderValidator.validate_from_schema_dict`, which
accepts a ``dict[str, list[str]]`` FK map (table → list of tables
it references). Boot validation that detects FK drift calls this
method; a :class:`PruneOrderViolation` signals the
``fail_safe_prune_order_invalid`` condition.
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


# ROADMAP §8.16.3 ``fail_safe_prune_order_invalid`` canonical exception.
# Alias kept separate so call-sites can catch the doctrine-named variant
# without importing the legacy ``PruneOrderError`` name.
PruneOrderViolation = PruneOrderError


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


class PruneOrderValidator:
    """Boot-time validator for the §8.16.3 prune-order doctrine.

    Validates that :data:`PRUNE_ORDER` is a valid topological sort
    of the tables' FK dependency graph so that no prune step leaves
    dangling FK references. A mismatch signals the
    ``fail_safe_prune_order_invalid`` condition — the caller should
    refuse-to-start and emit a critical alert.

    Usage::

        validator = PruneOrderValidator()
        # fk_map: table → list of tables it FK-references
        validator.validate_from_schema_dict(fk_map)
    """

    def validate_from_schema_dict(
        self,
        fk_map: dict[str, list[str]],
        order: tuple[str, ...] = PRUNE_ORDER,
    ) -> None:
        """Assert that ``order`` is a valid topological sort of ``fk_map``.

        ``fk_map`` maps each table to the list of tables it **references**
        (i.e. outgoing FK edges). For every FK edge ``A → B`` the validator
        requires ``order.index(A) < order.index(B)`` — A is pruned before B.

        Raises :class:`PruneOrderViolation` (``fail_safe_prune_order_invalid``)
        on any violation.
        """
        frozen: dict[str, frozenset[str]] = {
            tbl: frozenset(refs) for tbl, refs in fk_map.items()
        }
        topo_check(frozen, order)


__all__ = [
    "PRUNE_ORDER",
    "PruneOrderError",
    "PruneOrderViolation",
    "PruneOrderValidator",
    "topo_check",
]
