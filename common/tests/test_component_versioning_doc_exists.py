"""Phase 18.8 — docs/coding/component_versioning.md must exist with deprecation policy."""

from pathlib import Path


def test_component_versioning_doc_exists() -> None:
    """The component versioning doc must exist."""
    repo_root = Path(__file__).resolve().parents[2]
    doc = repo_root / "docs" / "coding" / "component_versioning.md"
    
    assert doc.exists(), "docs/coding/component_versioning.md not found"


def test_component_versioning_defines_deprecation_policy() -> None:
    """The doc must define the deprecation policy."""
    repo_root = Path(__file__).resolve().parents[2]
    doc = repo_root / "docs" / "coding" / "component_versioning.md"
    
    content = doc.read_text(encoding="utf-8")
    
    # Check for key sections
    assert "deprecation" in content.lower(), "no deprecation section"
    assert "removal" in content.lower(), "no removal policy"
    assert "minor" in content.lower() or "version" in content.lower(), "no version info"
    
    # Check for specific policy details
    assert "1.0.0" in content, "no stable version threshold"


def test_component_versioning_covers_stable_components() -> None:
    """The policy must cover stable (1.0.0+) components."""
    repo_root = Path(__file__).resolve().parents[2]
    doc = repo_root / "docs" / "coding" / "component_versioning.md"
    
    content = doc.read_text(encoding="utf-8")
    
    # Must address stability tiers
    assert "stable" in content.lower(), "doesn't mention stable"
    assert "pre-stable" in content.lower() or "0.x" in content, "doesn't address pre-stable"
    
    # Must require migration window
    assert "deprecation" in content.lower() or "migration" in content.lower()
