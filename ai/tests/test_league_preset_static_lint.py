"""Test Phase 13.3.4: Structural-only lint for league presets.

Proves that linter refuses computed values (os.environ, function calls,
list comprehensions, etc.) in preset files.
"""

import pytest
from pathlib import Path


def test_preset_static_lint_passes_for_tr_super_lig():
    """Verify that TR Super Lig preset passes structural lint."""
    from xops.lint.league_preset_static import lint_preset_file

    leagues_dir = Path(__file__).parent.parent / "common" / "leagues"
    tr_preset = leagues_dir / "tr_super_lig.py"

    violations = lint_preset_file(str(tr_preset))
    assert len(violations) == 0, f"TR Super Lig preset has violations: {violations}"


def test_all_presets_pass_structural_lint():
    """Verify that all existing presets pass structural lint."""
    from xops.lint.league_preset_static import lint_all_presets

    leagues_dir = Path(__file__).parent.parent / "common" / "leagues"
    violations = lint_all_presets(leagues_dir)

    assert len(violations) == 0, f"Presets with violations: {violations}"


def test_linter_detects_os_environ():
    """Verify that linter detects os.environ usage."""
    import tempfile
    from xops.lint.league_preset_static import lint_preset_file

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write("import os\nCONFIG = {'key': os.environ.get('VAR')}")
        f.flush()
        temp_path = f.name

    try:
        violations = lint_preset_file(temp_path)
        assert len(violations) > 0, "Linter should detect os.environ"
        assert any("computed" in v.lower() or "environ" in v.lower() for v in violations)
    finally:
        Path(temp_path).unlink()


def test_linter_detects_function_calls():
    """Verify that linter detects function calls."""
    import tempfile
    from xops.lint.league_preset_static import lint_preset_file

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write("CONFIG = {'teams': get_teams()}")
        f.flush()
        temp_path = f.name

    try:
        violations = lint_preset_file(temp_path)
        assert len(violations) > 0, "Linter should detect function calls"
    finally:
        Path(temp_path).unlink()


def test_linter_allows_frozenset():
    """Verify that linter allows safe built-ins like frozenset."""
    import tempfile
    from xops.lint.league_preset_static import lint_preset_file

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write("CONFIG = {'derbies': frozenset([('A', 'B')])}")
        f.flush()
        temp_path = f.name

    try:
        violations = lint_preset_file(temp_path)
        # Should not report frozenset() as a violation
        assert not any("frozenset" in v for v in violations)
    finally:
        Path(temp_path).unlink()


def test_linter_detects_non_empty_aliases_list():
    """Verify that linter detects non-empty aliases field assignment."""
    import tempfile
    from xops.lint.league_preset_static import lint_preset_file

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write("aliases = ['Team A', 'Team B']\nCONFIG = {}")
        f.flush()
        temp_path = f.name

    try:
        violations = lint_preset_file(temp_path)
        assert len(violations) > 0, "Linter should detect non-empty aliases"
        assert any("aliases" in v.lower() for v in violations)
    finally:
        Path(temp_path).unlink()


def test_linter_detects_non_empty_aliases_frozenset():
    """Verify that linter detects non-empty aliases in frozenset form."""
    import tempfile
    from xops.lint.league_preset_static import lint_preset_file

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write("aliases = frozenset(['Alias 1', 'Alias 2'])\nCONFIG = {}")
        f.flush()
        temp_path = f.name

    try:
        violations = lint_preset_file(temp_path)
        assert len(violations) > 0, "Linter should detect non-empty aliases in frozenset"
        assert any("aliases" in v.lower() for v in violations)
    finally:
        Path(temp_path).unlink()


def test_linter_allows_empty_aliases():
    """Verify that linter allows empty aliases (no violation)."""
    import tempfile
    from xops.lint.league_preset_static import lint_preset_file

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write("aliases = []\nCONFIG = {}")
        f.flush()
        temp_path = f.name

    try:
        violations = lint_preset_file(temp_path)
        # Empty aliases should not trigger a violation
        assert not any("aliases" in v.lower() for v in violations)
    finally:
        Path(temp_path).unlink()

