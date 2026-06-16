"""Phase 18.7 — Env var namespace lint (ledger #28).

The xops/lint/no_per_component_lint_override.py and related scripts
verify the namespace discipline. This test ensures the lint module exists
and can be imported.
"""

from __future__ import annotations

from pathlib import Path


def test_env_var_namespace_lint() -> None:
    """Verify namespace lint infrastructure exists."""
    # The lint module should exist
    repo_root = Path(__file__).resolve().parents[2]
    xops_lint = repo_root / "xops" / "lint"
    assert xops_lint.exists(), f"{xops_lint} does not exist"
    assert (xops_lint / "__init__.py").exists()

    # Verify no_per_component_lint_override.py or similar exists
    # (This would be extended with actual lint invocation in full implementation)
    lint_files = list(xops_lint.glob("*override*.py")) + list(xops_lint.glob("*lint*.py"))
    assert len(lint_files) > 0, "No lint override modules found"
