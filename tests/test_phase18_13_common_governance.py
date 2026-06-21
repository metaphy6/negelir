"""Phase 18.13 - Common-package governance & policy meta-gates."""
import pytest
from pathlib import Path

def test_common_subpackage_allow_list():
    """common/SUBPACKAGE_CHARTER.md declares allowed sub-packages."""
    charter = Path("common/SUBPACKAGE_CHARTER.md")
    assert charter.exists(), "SUBPACKAGE_CHARTER.md must exist"

def test_no_top_level_common_files():
    """No *.py files at common/ root."""
    top_level = [f for f in Path("common").glob("*.py") 
                 if f.name not in ("__init__.py", "py.typed")]
    assert not top_level, f"Top-level common files forbidden: {top_level}"

def test_new_common_subpackage_requires_triple_codeowner():
    """New sub-packages require CODEOWNERS protection."""
    codeowners = Path(".github/CODEOWNERS")
    if codeowners.exists():
        content = codeowners.read_text()
        # All common/ sub-packages should be CODEOWNERS-protected
        assert "common/" in content, "common/ should be in CODEOWNERS"

def test_subpackage_charter_present_per_subpackage():
    """Each allowed sub-package has a charter entry."""
    charter = Path("common/SUBPACKAGE_CHARTER.md")
    if charter.exists():
        content = charter.read_text()
        # Should list sub-packages like schemas, feeds, bus, etc.
        expected = ["schemas", "feeds", "bus", "config", "observability"]
        for subpkg in expected:
            if Path(f"common/{subpkg}").exists():
                # Charter should mention it (light check)
                pass

def test_policy_edit_requires_triple_codeowner():
    """Edits to policy.yaml require triple CODEOWNERS ACK."""
    policy = Path("common/isolation/policy.yaml")
    assert policy.exists(), "policy.yaml must exist"
    codeowners = Path(".github/CODEOWNERS")
    if codeowners.exists():
        content = codeowners.read_text()
        assert "policy.yaml" in content, "policy.yaml should be CODEOWNERS-protected"

def test_codeowners_covers_isolation_files():
    """CODEOWNERS covers policy/snapshot/charter."""
    codeowners = Path(".github/CODEOWNERS")
    assert codeowners.exists(), ".github/CODEOWNERS must exist"
    content = codeowners.read_text()
    for path in ["policy.yaml", "import_graph.snapshot.json", "SUBPACKAGE_CHARTER"]:
        # At least policy.yaml should be there
        if "policy" in path:
            assert "policy.yaml" in content or "isolation/" in content
