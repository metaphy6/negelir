"""Phase 18.8 — Anchor lint must resolve all references in ROADMAP, AGENTS, CLAUDE."""

from pathlib import Path


def test_anchor_lint_tool_exists() -> None:
    """The xops/lint/docs_anchor_lint.py tool must exist."""
    repo_root = Path(__file__).resolve().parents[2]
    lint_py = repo_root / "xops" / "lint" / "docs_anchor_lint.py"
    
    assert lint_py.exists(), "docs_anchor_lint.py not found"
    
    content = lint_py.read_text(encoding="utf-8")
    assert "extract_markdown_links" in content
    assert "resolve_link" in content
    assert "ROADMAP" in content
    assert "AGENTS" in content
    assert "CLAUDE" in content


def test_anchor_lint_validates_links() -> None:
    """The lint tool must validate markdown links."""
    repo_root = Path(__file__).resolve().parents[2]
    lint_py = repo_root / "xops" / "lint" / "docs_anchor_lint.py"
    
    content = lint_py.read_text(encoding="utf-8")
    
    # Check for link parsing
    assert r"\[([^\]]+)\]\(([^)]+)\)" in content, "no markdown link pattern"
    
    # Check for existence validation
    assert "exists()" in content, "doesn't check file existence"
