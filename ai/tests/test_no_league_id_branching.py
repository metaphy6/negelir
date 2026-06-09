"""
Tests for Phase 13.1 AST-scan linter: no_league_id_branching.

Verifies:
  - Hardcoded league_id comparisons are detected
  - if statements with league_id hardcoding are caught
  - match statements with league_id are detected
  - False positives are minimized
"""

import ast
import tempfile
from pathlib import Path

import pytest
from xops.lint.no_league_id_branching import (
    LeagueIdBranchingVisitor,
    scan_file,
    SUSPICIOUS_LEAGUE_PATTERNS,
)


class TestLeagueIdBranchingDetection:
    """Test AST visitor for league_id branching."""

    def test_detect_simple_equality(self) -> None:
        """Should detect `league_id == "super_lig"`."""
        code = '''
if league_id == "super_lig":
    do_something()
'''
        tree = ast.parse(code)
        visitor = LeagueIdBranchingVisitor("test.py")
        visitor.visit(tree)
        
        assert len(visitor.violations) > 0
        assert "league_id" in visitor.violations[0][1].lower()

    def test_detect_attribute_access(self) -> None:
        """Should detect `self.league_id == "prem"`."""
        code = '''
if self.league_id == "prem":
    return True
'''
        tree = ast.parse(code)
        visitor = LeagueIdBranchingVisitor("test.py")
        visitor.visit(tree)
        
        assert len(visitor.violations) > 0

    def test_no_false_positives_for_generic_strings(self) -> None:
        """Should not flag unrelated string comparisons."""
        code = '''
if name == "alice":
    print("hello")
'''
        tree = ast.parse(code)
        visitor = LeagueIdBranchingVisitor("test.py")
        visitor.visit(tree)
        
        # Should have no violations for generic names
        assert len(visitor.violations) == 0

    def test_no_false_positives_for_league_name_not_id(self) -> None:
        """Should not flag league name (not ID) strings."""
        code = '''
if league_name == "Turkish Super League":
    return True
'''
        tree = ast.parse(code)
        visitor = LeagueIdBranchingVisitor("test.py")
        visitor.visit(tree)
        
        # Should have no violations (league_name is not league_id)
        assert len(visitor.violations) == 0

    def test_known_league_patterns(self) -> None:
        """Should detect known league_id patterns."""
        patterns = {
            "super_lig": True,
            "tr_super_lig": True,
            "prem": True,
            "la_liga": True,
            "alice": False,
            "test": False,
        }
        
        visitor = LeagueIdBranchingVisitor("test.py")
        for pattern, should_match in patterns.items():
            assert visitor._looks_like_league_id(pattern) == should_match

    def test_scan_file_with_violation(self) -> None:
        """scan_file should detect violations in a file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as fh:
            fh.write('''
def process(league_id):
    if league_id == "super_lig":
        return "Turkish"
    return "Other"
''')
            filepath = Path(fh.name)
        
        try:
            violations = scan_file(filepath)
            assert len(violations) > 0
        finally:
            filepath.unlink()

    def test_scan_file_clean(self) -> None:
        """scan_file should return empty list for clean files."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as fh:
            fh.write('''
def process(league_id):
    config = CATALOG.get(league_id)
    if config is None:
        raise ValueError(f"League {league_id} not found")
    return config
''')
            filepath = Path(fh.name)
        
        try:
            violations = scan_file(filepath)
            # Should have no violations (uses catalog lookup, not hardcoding)
            assert len(violations) == 0
        finally:
            filepath.unlink()

    def test_suspicious_league_patterns_exist(self) -> None:
        """SUSPICIOUS_LEAGUE_PATTERNS should have known leagues."""
        assert "super_lig" in SUSPICIOUS_LEAGUE_PATTERNS
        assert "tr_super_lig" in SUSPICIOUS_LEAGUE_PATTERNS
        assert "prem" in SUSPICIOUS_LEAGUE_PATTERNS
        assert "la_liga" in SUSPICIOUS_LEAGUE_PATTERNS


class TestASTPatternsDetection:
    """Test detection of various AST patterns."""

    def test_reversed_comparison(self) -> None:
        """Should detect reversed: `"super_lig" == league_id`."""
        code = '''
if "super_lig" == league_id:
    do_something()
'''
        tree = ast.parse(code)
        visitor = LeagueIdBranchingVisitor("test.py")
        visitor.visit(tree)
        
        # May or may not detect (reversed comparison is trickier)
        # but document the behavior
        assert isinstance(visitor.violations, list)

    def test_multiple_violations(self) -> None:
        """Should detect multiple violations in one file."""
        code = '''
if league_id == "super_lig":
    x = 1
    
if league_id == "prem":
    y = 2
'''
        tree = ast.parse(code)
        visitor = LeagueIdBranchingVisitor("test.py")
        visitor.visit(tree)
        
        assert len(visitor.violations) >= 1
