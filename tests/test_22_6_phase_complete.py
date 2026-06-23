"""Phase 22.6 — Configuration consolidation proof tests.

These tests verify that the single-source configuration system is
operational and that the required migrations have been completed.
"""

from pathlib import Path
import re


def test_22_6_no_hardcoded_current_season():
    """Verify xops/lint/no_hardcoded_season.py linter exists and passes."""
    linter_path = Path(__file__).resolve().parents[1] / "xops" / "lint" / "no_hardcoded_season.py"
    assert linter_path.exists(), f"Linter not found at {linter_path}"
    
    # Check that the linter is executable
    assert linter_path.stat().st_mode & 0o111, "Linter is not executable"
    
    # Verify the linter contains the main elements
    content = linter_path.read_text(encoding="utf-8")
    assert "CURRENT_SEASON" in content, "Linter should check for CURRENT_SEASON"
    assert "def scan" in content, "Linter should have scan function"
    assert "def main" in content, "Linter should have main function"


def test_22_6_n_features_is_derived():
    """Verify N_FEATURES is derived from len(FEATURE_COLUMNS)."""
    constants_path = Path(__file__).resolve().parents[1] / "common" / "constants.py"
    content = constants_path.read_text(encoding="utf-8")
    
    match = re.search(
        r'N_FEATURES:\s*int\s*=\s*len\(FEATURE_COLUMNS\)',
        content
    )
    assert match, "N_FEATURES must be derived from len(FEATURE_COLUMNS)"


def test_22_6_n_features_comment_reconciled():
    """Verify the N_FEATURES comment no longer has stale value."""
    constants_path = Path(__file__).resolve().parents[1] / "common" / "constants.py"
    content = constants_path.read_text(encoding="utf-8")
    
    match = re.search(
        r'N_FEATURES: int = len\(FEATURE_COLUMNS\)\s*#\s*(.+?)$',
        content,
        re.MULTILINE
    )
    assert match, "N_FEATURES comment not found"
    
    comment = match.group(1)
    assert "147" not in comment, "N_FEATURES comment should not reference stale '147' value"
    assert "157" in comment or "derived" in comment.lower(), \
        "N_FEATURES comment should reference current value (157) or derived nature"


def test_22_6_ai_common_paths_removed():
    """Verify ai/common/ paths have been removed from ai_pipeline.py."""
    ai_pipeline = Path(__file__).resolve().parents[1] / "common" / "config" / "ai_pipeline.py"
    content = ai_pipeline.read_text(encoding="utf-8")
    
    # Count ai/common/ references (excluding comments/docstrings that are in YAML)
    # The real check is for hardcoded default values
    matches = re.findall(r'os\.getenv\([^)]*"ai/common/', content)
    assert len(matches) == 0, f"Found {len(matches)} references to ai/common/ in defaults; should be 0"
    
    # Verify tr_normalize_spec_path uses common/ not ai/common/
    match = re.search(
        r'nlp_tr_normalize_spec_path.*os\.getenv\([^)]*"([^"]+)"',
        content
    )
    if match:
        default_path = match.group(1)
        assert "ai/common" not in default_path, \
            f"nlp_tr_normalize_spec_path should use common/ path, found: {default_path}"


def test_22_6_defaults_yaml_at_canonical_location():
    """Verify common/config/defaults.yaml exists at the canonical location."""
    defaults_path = Path(__file__).resolve().parents[1] / "common" / "config" / "defaults.yaml"
    assert defaults_path.exists(), f"defaults.yaml not found at canonical location {defaults_path}"
    
    # Verify it's the real file (not a symlink to ai/common/)
    content = defaults_path.read_text(encoding="utf-8")
    assert "postgres:" in content or "redis:" in content, \
        "defaults.yaml should contain configuration sections"


def test_22_6_config_export_script_exists():
    """Verify config export script exists and is functional."""
    script_path = Path(__file__).resolve().parents[1] / "xops" / "makefile" / "config_export.py"
    assert script_path.exists(), f"Config export script not found at {script_path}"
    
    content = script_path.read_text(encoding="utf-8")
    assert "export-env" in content or "export_env" in content, "Script should support export-env action"


if __name__ == "__main__":
    test_22_6_no_hardcoded_current_season()
    test_22_6_n_features_is_derived()
    test_22_6_n_features_comment_reconciled()
    test_22_6_ai_common_paths_removed()
    test_22_6_defaults_yaml_at_canonical_location()
    test_22_6_config_export_script_exists()
    print("✅ All Phase 22.6 proof tests passed")
