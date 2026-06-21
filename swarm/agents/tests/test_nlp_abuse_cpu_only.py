"""Phase 11 contract: `ai/swarm/agents/nlp/abuse.py` remains CPU-only.

This AST guard enforces the Phase 10 cross-phase contract that the
abuse detector cannot import GPU-specific runtime modules such as
`torch`, `cuda`, `mps`, or `rocm` until Phase 11 explicitly introduces a
GPU compute path.
"""
from __future__ import annotations

import ast
from pathlib import Path

_DISALLOWED_GPU_TOKENS = ("cuda", "mps", "rocm", "torch")


def _module_references_gpu_token(module: str | None) -> bool:
    if module is None:
        return False
    module = module.lower()
    return any(tok in module for tok in _DISALLOWED_GPU_TOKENS)


def test_nlp_abuse_agent_imports_no_gpu_runtime_modules() -> None:
    src = Path(__file__).resolve().parents[1] / "nlp" / "abuse.py"
    tree = ast.parse(src.read_text(encoding="utf-8"), filename=str(src))

    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _module_references_gpu_token(alias.name):
                    offenders.append(f"import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            if _module_references_gpu_token(node.module):
                offenders.append(f"from {node.module} import ...")
            for alias in node.names:
                if _module_references_gpu_token(alias.name):
                    offenders.append(f"from {node.module} import {alias.name}")

    assert not offenders, (
        "ai/swarm/agents/nlp/abuse.py must remain CPU-only; GPU runtime imports are forbidden: "
        + ", ".join(offenders)
    )


def _assert_module_imports_no_gpu_runtime_modules(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _module_references_gpu_token(alias.name):
                    offenders.append(f"import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            if _module_references_gpu_token(node.module):
                offenders.append(f"from {node.module} import ...")
            for alias in node.names:
                if _module_references_gpu_token(alias.name):
                    offenders.append(f"from {node.module} import {alias.name}")

    assert not offenders, (
        f"{path} must remain CPU-only; GPU runtime imports are forbidden: "
        + ", ".join(offenders)
    )


def test_nlp_budget_module_imports_no_gpu_runtime_modules() -> None:
    src = Path(__file__).resolve().parents[3] / "nlp" / "runtime" / "budget.py"
    _assert_module_imports_no_gpu_runtime_modules(src)


def test_nlp_intent_skew_detector_imports_no_gpu_runtime_modules() -> None:
    src = Path(__file__).resolve().parents[1] / "nlp" / "__init__.py"
    _assert_module_imports_no_gpu_runtime_modules(src)
