"""Phase 8 §8.10 — leader-election boundary test.

Two complementary contracts are pinned here:

1. **Set parity.** The :data:`LEADER_REQUIRED_AGENTS` constant in
   :mod:`swarm.sdk.leader` is the single source of truth for which
   maint-plane agents must run with a leader gate. The maint-plane
   agent classes register themselves via the ``name`` class
   attribute. Renaming or removing one of them without updating the
   constant — or adding a new ``replicas: 1`` agent without listing
   it — fails this test loud. (Orphans on either side of the set are
   the threat model.)

2. **Emit-gating AST scan.** For each agent class that has been
   wired through the §8.10 gate so far (``_LEADER_GATED``), every
   function in the module that calls ``self._notify(...)`` (the
   leader-only decision emitter) must either contain an
   ``is_leader()`` reference itself, or be a private helper whose
   *every* in-module caller contains one. The contract intentionally
   excludes ``_ack`` because the §8.10 contract allows acks in
   non-leader paths (e.g. ``reason="non_leader_noop"``) — losing
   leadership must still drain in-flight requests.

   Adversarial counter-test (Rule 7): a synthetic agent module that
   calls ``self._notify`` from an unguarded function MUST be flagged
   by the same scanner.

   Schema/sec/backup are listed in :data:`LEADER_REQUIRED_AGENTS`
   but their leader gates are still being threaded through (Phase
   8.10 follow-up). They live in ``_LEADER_PENDING`` and are
   *not* AST-scanned yet. When their gates land, move them from
   ``_LEADER_PENDING`` into ``_LEADER_GATED`` in this test file —
   the scanner will then enforce the same contract on them.
"""
from __future__ import annotations

import ast
import importlib
import inspect
from pathlib import Path

import pytest

from swarm.sdk.leader import LEADER_REQUIRED_AGENTS

# Subset of LEADER_REQUIRED_AGENTS whose gates are wired through
# today. Move agents from PENDING to GATED as their gates land.
_LEADER_GATED: frozenset[str] = frozenset({
    "maint.scaler.v1",
    "maint.dlq.v1",
})
_LEADER_PENDING: frozenset[str] = LEADER_REQUIRED_AGENTS - _LEADER_GATED

# Map agent ids to their dotted module paths. Single-source so the
# discovery loop below imports each module exactly once.
_AGENT_MODULES: dict[str, str] = {
    "maint.scaler.v1": "swarm.agents.maint.scaler",
    "maint.dlq.v1": "swarm.agents.maint.dlq",
    "maint.schema.v1": "swarm.agents.maint.schema",
    "maint.sec.v1": "swarm.agents.maint.sec",
    "maint.backup.v1": "swarm.agents.maint.backup",
}


# ── Set-parity test ──────────────────────────────────────────────


def _discover_registered_agent_ids() -> frozenset[str]:
    """Import each declared maint-plane module and harvest the ``name``
    attribute of the agent class it defines. The class is identified
    as the one whose ``name`` matches the dict key — a rename forces
    this test to fail rather than silently mis-discover.
    """
    found: set[str] = set()
    for expected_name, dotted in _AGENT_MODULES.items():
        mod = importlib.import_module(dotted)
        match = None
        for _, obj in inspect.getmembers(mod, inspect.isclass):
            if obj.__module__ != dotted:
                continue
            if getattr(obj, "name", None) == expected_name:
                match = obj
                break
        assert match is not None, (
            f"could not locate a class with name={expected_name!r} "
            f"in module {dotted!r} — was the agent renamed?"
        )
        found.add(match.name)
    return frozenset(found)


def test_leader_required_set_matches_registered_agents() -> None:
    """The §8.10 LEADER_REQUIRED_AGENTS set must equal the set of
    agent ids actually registered by the maint-plane modules.

    Orphans on either side fail:
      * A constant entry with no live agent → stale config.
      * A live agent missing from the constant → ungated emit risk.
    """
    discovered = _discover_registered_agent_ids()
    assert discovered == LEADER_REQUIRED_AGENTS, (
        f"orphan(s) detected — constant={sorted(LEADER_REQUIRED_AGENTS)} "
        f"discovered={sorted(discovered)} "
        f"only_in_constant={sorted(LEADER_REQUIRED_AGENTS - discovered)} "
        f"only_in_registry={sorted(discovered - LEADER_REQUIRED_AGENTS)}"
    )


def test_leader_pending_subset_is_disjoint() -> None:
    """``_LEADER_GATED`` and ``_LEADER_PENDING`` partition
    :data:`LEADER_REQUIRED_AGENTS` — no overlaps, no gaps. This
    catches typos in the local subsets above without waiting for
    the AST scan to mis-fire.
    """
    assert _LEADER_GATED.isdisjoint(_LEADER_PENDING)
    assert _LEADER_GATED | _LEADER_PENDING == LEADER_REQUIRED_AGENTS


# ── AST scanner ──────────────────────────────────────────────────

# Method names that are gated emit paths. ``_ack`` is intentionally
# excluded — §8.10 allows acks in non-leader paths to drain in-flight
# requests gracefully.
_GATED_EMIT_METHODS: frozenset[str] = frozenset({"_notify"})


def _is_self_call(node: ast.AST, *, attr: str | None = None) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if not isinstance(func, ast.Attribute):
        return False
    if not isinstance(func.value, ast.Name) or func.value.id != "self":
        return False
    return attr is None or func.attr == attr


def _function_calls_method(funcdef: ast.AST, method: str) -> bool:
    for sub in ast.walk(funcdef):
        if _is_self_call(sub, attr=method):
            return True
    return False


def _function_has_leader_check(funcdef: ast.AST) -> bool:
    for sub in ast.walk(funcdef):
        if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute):
            if sub.func.attr == "is_leader":
                return True
    return False


def _function_self_callees(funcdef: ast.AST) -> set[str]:
    out: set[str] = set()
    for sub in ast.walk(funcdef):
        if _is_self_call(sub):
            assert isinstance(sub.func, ast.Attribute)  # narrowed by helper
            out.add(sub.func.attr)
    return out


def find_unguarded_emit_paths(source: str) -> list[str]:
    """Return the names of functions that emit on a leader-only
    path without a guard.

    A function ``F`` is *guarded* if either:
      * ``F``'s body contains an ``is_leader()`` reference, or
      * every in-module caller of ``F`` is itself guarded (transitive
        closure, capped to the module — we deliberately do not chase
        cross-module dispatch).

    A function ``F`` is *emitting* if it calls one of
    :data:`_GATED_EMIT_METHODS` (``self._notify(...)``) **and** is
    not the helper definition itself (``_notify``).
    """
    tree = ast.parse(source)
    funcs: dict[str, ast.AST] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            funcs[node.name] = node

    emit_funcs: set[str] = {
        name
        for name, fn in funcs.items()
        if name not in _GATED_EMIT_METHODS
        and any(_function_calls_method(fn, m) for m in _GATED_EMIT_METHODS)
    }
    guarded_direct: set[str] = {
        name for name, fn in funcs.items() if _function_has_leader_check(fn)
    }

    # Build callers map: for each function name, who calls it (within
    # this module, via ``self.<name>(...)``).
    callers: dict[str, set[str]] = {name: set() for name in funcs}
    for caller_name, caller_def in funcs.items():
        for callee in _function_self_callees(caller_def):
            if callee in callers:
                callers[callee].add(caller_name)

    # Transitive closure: a function is "effectively guarded" if it
    # is directly guarded, or every caller is effectively guarded.
    # Compute via fixed-point iteration over the callers map.
    effectively_guarded: set[str] = set(guarded_direct)
    changed = True
    while changed:
        changed = False
        for name in funcs:
            if name in effectively_guarded:
                continue
            cs = callers.get(name, set())
            if cs and all(c in effectively_guarded for c in cs):
                effectively_guarded.add(name)
                changed = True

    return sorted(name for name in emit_funcs if name not in effectively_guarded)


# ── Per-agent gate scan ──────────────────────────────────────────


@pytest.mark.parametrize("agent_id", sorted(_LEADER_GATED))
def test_gated_agent_emit_paths_are_leader_guarded(agent_id: str) -> None:
    """Every ``self._notify(...)`` call site in a gated agent must
    sit inside a function with an ``is_leader()`` check, or be
    reached only through callers that have one.
    """
    dotted = _AGENT_MODULES[agent_id]
    mod = importlib.import_module(dotted)
    source_path = Path(inspect.getsourcefile(mod) or "")
    assert source_path.is_file(), f"could not locate source for {dotted!r}"
    source = source_path.read_text(encoding="utf-8")

    violations = find_unguarded_emit_paths(source)
    assert violations == [], (
        f"{agent_id}: unguarded leader-only emit path(s) — every "
        f"function calling self._notify(...) must contain an "
        f"is_leader() check (or be reached only through guarded "
        f"callers). Offenders: {violations!r}"
    )


# ── Adversarial counter-test ────────────────────────────────────


_ADVERSARIAL_BAD_SOURCE = """\
class RogueAgent:
    name = "maint.rogue.v1"

    def handle(self, msg):
        # Missing is_leader() guard — must be flagged.
        yield self._notify("rogue_decision", target="t")

    def _notify(self, kind, *, target):
        return (kind, target)
"""

_ADVERSARIAL_GOOD_SOURCE = """\
class CleanAgent:
    name = "maint.clean.v1"

    def handle(self, msg):
        if not self._leader.is_leader():
            return
        yield self._notify("clean_decision", target="t")

    def _notify(self, kind, *, target):
        return (kind, target)
"""

_ADVERSARIAL_TRANSITIVE_SOURCE = """\
class TransitivelyGated:
    name = "maint.transitive.v1"

    def handle(self, msg):
        if not self._leader.is_leader():
            return
        yield from self._emit_decision()

    def _emit_decision(self):
        # No direct is_leader() — but the only caller is gated.
        yield self._notify("transitive_decision", target="t")

    def _notify(self, kind, *, target):
        return (kind, target)
"""


def test_ast_scanner_flags_unguarded_emit() -> None:
    violations = find_unguarded_emit_paths(_ADVERSARIAL_BAD_SOURCE)
    assert "handle" in violations, (
        "adversarial source: scanner must flag the unguarded handle() "
        f"emit, got violations={violations!r}"
    )


def test_ast_scanner_passes_guarded_emit() -> None:
    violations = find_unguarded_emit_paths(_ADVERSARIAL_GOOD_SOURCE)
    assert violations == [], (
        f"clean source: scanner must not flag a directly-guarded "
        f"emit, got violations={violations!r}"
    )


def test_ast_scanner_passes_transitively_guarded_emit() -> None:
    violations = find_unguarded_emit_paths(_ADVERSARIAL_TRANSITIVE_SOURCE)
    assert violations == [], (
        f"transitive source: scanner must accept emits whose only "
        f"in-module caller is guarded, got violations={violations!r}"
    )
