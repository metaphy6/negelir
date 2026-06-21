"""Phase 10 10.21.11 boundary: NLP runtime must not import LeagueCatalog.

NLP should consume generated lexicon files only; it must not directly import
``ai/common/league_catalog.py`` at runtime.
"""
from __future__ import annotations

import ast
from pathlib import Path


_NLP_ROOT = Path(__file__).parent.parent / "nlp"


def _iter_python_files(root: Path) -> list[Path]:
    return sorted(
        p for p in root.rglob("*.py") if p.is_file() and p.name != "__init__.py"
    )


def test_nlp_lexicon_does_not_query_league_catalog_at_runtime() -> None:
    """Reject direct imports of common.league_catalog from ai/nlp modules."""
    violations: list[str] = []

    for path in _iter_python_files(_NLP_ROOT):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    mod = alias.name
                    if mod in {"common.league_catalog", "ai.common.league_catalog"}:
                        violations.append(f"{path}:{node.lineno} imports {mod}")
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                if mod in {"common.league_catalog", "ai.common.league_catalog"}:
                    violations.append(f"{path}:{node.lineno} imports from {mod}")

    assert violations == [], (
        "NLP runtime must not query LeagueCatalog directly; "
        "consume generated lexicon files instead. Violations: "
        + "; ".join(violations)
    )


def test_phase12_catalogue_includes_authentic_turkish_floor_stubs() -> None:
    """Verify the Phase 12 chaos catalogue includes the new Phase 10 NLP stubs."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    catalogue = (root / "docs" / "testing" / "phase12_catalogue.md").read_text(encoding="utf-8")
    for stub in (
        "chaos.tr-pii-flood",
        "chaos.compound-flood",
        "chaos.lexicon-rebuild-storm",
        "chaos.runaway-normalize",
    ):
        assert stub in catalogue, f"Expected Phase 12 catalogue to define {stub}"
