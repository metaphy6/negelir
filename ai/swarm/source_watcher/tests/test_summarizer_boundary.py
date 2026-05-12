"""Phase 8 §8.4 — Boundary test (binding) for the LLM summarizer.

ROADMAP §8.4: "AST-and-runtime scan asserting ``summarizer.summarize(plan)``
cannot mutate the plan's classification / severity / actions /
diffs. Returns Turkish narration string only. Existing test extended;
failure on a future attempt to widen the summarizer's authority."

This test locks the contract before any of the §8.4 follow-on work
(SDK migration, summarizer graduation, cost cap) lands. Concretely
it guards three invariants:

1. **Static (AST):** the body of ``summarize`` contains NO assignment
   to any attribute of its first parameter (``up``), no call to
   ``setattr(up, ...)`` or ``object.__setattr__(up, ...)``, and no
   in-place mutating method call (``append``/``extend``/``pop``/
   ``remove``/``clear``/``sort``/``reverse``/``insert``) on any
   attribute of ``up``.
2. **Runtime:** invoking ``summarize`` against any plan leaves the
   plan deeply equal to a pre-call deepcopy. Holds for every code
   path: ``enabled=False``, ``enabled=True`` with no llm,
   ``enabled=True`` with a healthy llm, and ``enabled=True`` with a
   raising llm.
3. **Output contract:** the returned ``SummaryResult.text`` is a
   non-empty ``str`` (Turkish narration; we apply a Turkish-character
   heuristic to the deterministic-fallback text, which is what every
   safety path returns).

Adversarial case (Rule 7): a hand-crafted summarizer body that DOES
mutate the plan is fed through the same AST scanner — the scanner
must flag it. This proves the scan is not a no-op.
"""
from __future__ import annotations

import ast
import copy
import inspect
from dataclasses import fields
from typing import List

import pytest

from ai.swarm.source_watcher import summarizer as summarizer_module
from ai.swarm.source_watcher.classifier import classify
from ai.swarm.source_watcher.differ import diff_json
from ai.swarm.source_watcher.planner import UpdatePlan, plan
from ai.swarm.source_watcher.summarizer import SummaryResult, summarize


# Fields the summarizer must never touch, derived dynamically so that
# adding a field to UpdatePlan automatically extends the boundary.
_GUARDED_FIELDS = frozenset(f.name for f in fields(UpdatePlan))

# In-place list/dict mutators that, applied to ``up.<field>``, would
# corrupt the plan even when UpdatePlan itself is frozen.
_MUTATING_METHODS = frozenset(
    {
        "append", "extend", "insert", "pop", "remove",
        "clear", "sort", "reverse", "update", "setdefault",
    }
)

# Turkish-specific characters used as a low-false-positive heuristic
# that the deterministic fallback (and any future LLM output) is in TR.
_TURKISH_CHARS = frozenset("çğıöşüÇĞİÖŞÜ")


# ---------- Helpers --------------------------------------------------


def _make_plans() -> List[UpdatePlan]:
    """Return one plan per severity tier so every code path is exercised."""
    cosmetic = plan(
        "x.local",
        classify(diff_json({"a": 1}, {"a": 1, "b": 2})),  # added cosmetic key
    )
    semantic = plan(
        "x.local",
        classify(diff_json({"a": 1}, {"a": 2})),  # value flip
    )
    breaking = plan(
        "x.local",
        classify(diff_json({"a": 1, "b": 2}, {"a": "1"})),  # type flip + drop
    )
    return [cosmetic, semantic, breaking]


def _scan_function_body(func) -> List[str]:
    """Return a list of human-readable boundary violations.

    Pure stdlib ``ast`` walk over the function source. We accept the
    function's first positional parameter name as the "plan" alias to
    cover refactors that rename ``up`` → ``plan``.
    """
    src = inspect.getsource(func)
    src = inspect.cleandoc(src) if src.lstrip().startswith(("'''", '"""')) else src
    # ``inspect.getsource`` can return code indented inside its
    # enclosing block; ``ast.parse`` rejects that. Dedent to be safe.
    import textwrap
    tree = ast.parse(textwrap.dedent(src))

    func_def = next(
        (n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))),
        None,
    )
    if func_def is None:
        return ["could not locate FunctionDef in source"]

    if not func_def.args.args:
        return ["summarize() has no positional parameters; cannot bind plan alias"]
    plan_alias = func_def.args.args[0].arg

    violations: List[str] = []

    def _is_plan_attr(node: ast.AST) -> bool:
        return (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == plan_alias
        )

    for node in ast.walk(func_def):
        # 1. Direct attribute assignment:   up.<field> = ...
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if _is_plan_attr(tgt) and tgt.attr in _GUARDED_FIELDS:
                    violations.append(
                        f"assigns to {plan_alias}.{tgt.attr} at line {node.lineno}"
                    )
        if isinstance(node, ast.AugAssign) and _is_plan_attr(node.target):
            if node.target.attr in _GUARDED_FIELDS:
                violations.append(
                    f"aug-assigns to {plan_alias}.{node.target.attr} at line {node.lineno}"
                )
        if isinstance(node, ast.AnnAssign) and _is_plan_attr(node.target):
            if node.target.attr in _GUARDED_FIELDS:
                violations.append(
                    f"ann-assigns to {plan_alias}.{node.target.attr} at line {node.lineno}"
                )

        # 2. setattr / object.__setattr__ that targets the plan alias.
        if isinstance(node, ast.Call):
            func_node = node.func
            # setattr(up, "field", value)
            if (
                isinstance(func_node, ast.Name)
                and func_node.id == "setattr"
                and node.args
                and isinstance(node.args[0], ast.Name)
                and node.args[0].id == plan_alias
            ):
                violations.append(
                    f"setattr({plan_alias}, ...) at line {node.lineno}"
                )
            # object.__setattr__(up, "field", value)  — frozen dataclass escape hatch
            if (
                isinstance(func_node, ast.Attribute)
                and func_node.attr == "__setattr__"
                and node.args
                and isinstance(node.args[0], ast.Name)
                and node.args[0].id == plan_alias
            ):
                violations.append(
                    f"object.__setattr__({plan_alias}, ...) at line {node.lineno}"
                )
            # 3. up.<field>.<mutating_method>(...)
            if (
                isinstance(func_node, ast.Attribute)
                and func_node.attr in _MUTATING_METHODS
                and isinstance(func_node.value, ast.Attribute)
                and isinstance(func_node.value.value, ast.Name)
                and func_node.value.value.id == plan_alias
                and func_node.value.attr in _GUARDED_FIELDS
            ):
                violations.append(
                    f"in-place {plan_alias}.{func_node.value.attr}.{func_node.attr}(...) "
                    f"at line {node.lineno}"
                )

    return violations


# ---------- 1. Static (AST) scan -------------------------------------


def test_ast_summarize_does_not_mutate_plan() -> None:
    violations = _scan_function_body(summarizer_module.summarize)
    assert violations == [], (
        "summarize() must not mutate the plan. Boundary violations:\n  - "
        + "\n  - ".join(violations)
    )


def test_ast_scanner_catches_an_actual_mutator() -> None:
    """Adversarial (Rule 7): the scanner MUST flag a real mutator.

    We define a synthetic ``summarize`` that mutates the plan in three
    of the forbidden ways and confirm the scanner returns at least one
    violation per technique. Without this, a green AST test would
    prove nothing.
    """
    def naughty_summarize(up, *, enabled=False, llm=None):  # noqa: ANN001
        up.actions.append("page_human")          # in-place list mutation
        setattr(up, "summary", "rewritten")      # setattr escape
        object.__setattr__(up, "severity", "x")  # frozen-dataclass escape
        return "tr text"

    violations = _scan_function_body(naughty_summarize)
    assert any("actions.append" in v for v in violations), violations
    assert any("setattr(up" in v for v in violations), violations
    assert any("object.__setattr__" in v for v in violations), violations


# ---------- 2. Runtime scan ------------------------------------------


@pytest.mark.parametrize("up", _make_plans())
def test_runtime_summarize_disabled_does_not_mutate(up: UpdatePlan) -> None:
    snapshot = copy.deepcopy(up)
    summarize(up, enabled=False)
    assert up == snapshot


@pytest.mark.parametrize("up", _make_plans())
def test_runtime_summarize_enabled_no_llm_does_not_mutate(up: UpdatePlan) -> None:
    snapshot = copy.deepcopy(up)
    summarize(up, enabled=True, llm=None)
    assert up == snapshot


@pytest.mark.parametrize("up", _make_plans())
def test_runtime_summarize_enabled_healthy_llm_does_not_mutate(up: UpdatePlan) -> None:
    snapshot = copy.deepcopy(up)

    def healthy(_p: UpdatePlan) -> str:
        return "Kaynakta değişiklik var."  # plausible TR narration

    summarize(up, enabled=True, llm=healthy)
    assert up == snapshot


@pytest.mark.parametrize("up", _make_plans())
def test_runtime_summarize_enabled_raising_llm_does_not_mutate(up: UpdatePlan) -> None:
    snapshot = copy.deepcopy(up)

    def broken(_p: UpdatePlan) -> str:
        raise RuntimeError("boom")

    summarize(up, enabled=True, llm=broken)
    assert up == snapshot


# ---------- 3. Output contract ---------------------------------------


@pytest.mark.parametrize("up", _make_plans())
def test_summarize_returns_nonempty_string_text(up: UpdatePlan) -> None:
    result = summarize(up, enabled=False)
    assert isinstance(result, SummaryResult)
    assert isinstance(result.text, str)
    assert result.text  # non-empty


def test_summarize_fallback_text_is_turkish() -> None:
    """The deterministic fallback — taken on every safety path —
    must contain at least one Turkish-specific character. Future LLM
    output is judged by humans; this only pins the fallback."""
    up = plan(
        "x.local",
        classify(diff_json({"a": 1, "b": 2}, {"a": "1"})),
    )
    text = summarize(up, enabled=False).text
    assert any(ch in _TURKISH_CHARS for ch in text), (
        f"deterministic fallback should be Turkish-language; got: {text!r}"
    )
