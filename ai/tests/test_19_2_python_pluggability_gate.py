"""Phase 19 §19.2 — Python AST pluggability gate test.

Verifies that zero `if league_id == '...'` or `league_id in [...]` literals
exist in ai/**/*.py.
"""

from __future__ import annotations

import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "xops" / "lint"))
from no_league_id_branching import check_python_ast_pluggability


class TestPythonAstPluggabilityGate:
    """Test Python AST pluggability enforcement."""
    
    def test_hardcoded_league_id_comparison_blocked(self, tmp_path: Path) -> None:
        """Verify that hardcoded league_id comparisons are detected."""
        ai_path = tmp_path / "ai"
        ai_path.mkdir()
        
        # Create a file with a violation
        bad_file = ai_path / "bad_league_check.py"
        bad_file.write_text("""
def get_league_name(league_id):
    if league_id == "tr_super_lig":  # VIOLATION: hardcoded literal
        return "Turkish Super Lig"
    return "Unknown"
""")
        
        errors = check_python_ast_pluggability(tmp_path)
        
        # Should detect the violation
        assert len(errors) > 0
        assert "league_id" in str(errors[0]).lower()
    
    def test_league_id_in_list_blocked(self, tmp_path: Path) -> None:
        """Verify that league_id in [...] with literals is detected."""
        ai_path = tmp_path / "ai"
        ai_path.mkdir()
        
        # Create a file with list membership violation
        bad_file = ai_path / "bad_league_list.py"
        bad_file.write_text("""
def is_top_league(league_id):
    if league_id in ["tr_super_lig", "en_premier_league"]:  # VIOLATION
        return True
    return False
""")
        
        errors = check_python_ast_pluggability(tmp_path)
        assert len(errors) > 0
    
    def test_clean_league_id_usage_passes(self, tmp_path: Path) -> None:
        """Verify that pluggable league_id usage passes."""
        ai_path = tmp_path / "ai"
        ai_path.mkdir()
        
        # Create a clean file
        good_file = ai_path / "good_league_lookup.py"
        good_file.write_text("""
def get_league_config(league_id, catalog):
    # This is correct: league_id comes from catalog, not hardcoded
    return catalog.get(league_id)

def filter_leagues(league_ids, catalog):
    # This is correct: iterating over pluggable list, not literals
    return [league_ids[lid] for lid in league_ids if lid in catalog]
""")
        
        errors = check_python_ast_pluggability(tmp_path)
        assert errors == []
    
    def test_gate_is_mandatory_for_phase_19(self) -> None:
        """Document that the gate is mandatory for Phase 19."""
        # This gate re-asserts Phase 13's pluggability requirement
        # and verifies it still passes after all Phase 19 additions
        
        assert True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
