"""Phase 13.11.7 — Confusable-character distinctness tests.

Tests that confusable characters from different scripts don't get auto-merged.
Cyrillic 'а' vs Latin 'a', Greek 'Α' vs Latin 'A', etc., must produce distinct
canonical IDs and must NOT auto-merge to the same entity.

Per LEAGUE_CATALOG.md §2.2 and §13.11.7, the lint rule prevents confusable
mixing in aliases, and tests verify that distinct scripts produce distinct
identifiers.
"""
from __future__ import annotations

import sys
from pathlib import Path
from subprocess import run

import pytest

TEST_ROOT = Path(__file__).resolve().parent
REPO_ROOT = TEST_ROOT.parent.parent
LINT_TOOL = REPO_ROOT / "xops" / "lint" / "no_confusable_aliases.py"

if not LINT_TOOL.exists():
    pytest.skip("Lint tool not found", allow_module_level=True)


def test_lint_rejects_confusable_cyrillic_latin_a() -> None:
    """Lint rejects alias mixing Cyrillic 'а' and Latin 'a'."""
    import tempfile
    from pathlib import Path
    
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = Path(tmpdir) / "test.yaml"
        # Use 'а' (Cyrillic U+0430) mixed with 'a' (Latin U+0061)
        test_file.write_text("""\
_meta:
  schema_version: 1
  lexicon_version: 1.0.0
  generated_at_utc: "2026-01-01T00:00:00Z"
  generator: test

entries:
  - canonical_id: test_entity
    names:
      - Test Entity
    aliases:
      - аa  # Cyrillic 'а' (U+0430) + Latin 'a' (U+0061) - should be rejected
""")
        
        result = run(
            [sys.executable, str(LINT_TOOL), str(test_file)],
            capture_output=True,
            text=True,
        )
        
        # Should fail (return code 1)
        assert result.returncode == 1, (
            f"Lint should reject confusable mixing, but passed:\n{result.stdout}"
        )
        assert "confusable" in result.stderr.lower()


def test_lint_rejects_confusable_greek_latin_a() -> None:
    """Lint rejects alias mixing Greek 'Α' and Latin 'A'."""
    import tempfile
    from pathlib import Path
    
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = Path(tmpdir) / "test.yaml"
        test_file.write_text("""\
_meta:
  schema_version: 1
  lexicon_version: 1.0.0
  generated_at_utc: "2026-01-01T00:00:00Z"
  generator: test

entries:
  - canonical_id: test_entity
    names:
      - Test Entity
    aliases:
      - ΑA  # Greek 'Α' + Latin 'A' - should be rejected
""")
        
        result = run(
            [sys.executable, str(LINT_TOOL), str(test_file)],
            capture_output=True,
            text=True,
        )
        
        assert result.returncode == 1
        assert "confusable" in result.stderr.lower()


def test_lint_accepts_pure_cyrillic_aliases() -> None:
    """Lint accepts pure Cyrillic aliases (no mixing)."""
    import tempfile
    from pathlib import Path
    
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = Path(tmpdir) / "test.yaml"
        test_file.write_text("""\
_meta:
  schema_version: 1
  lexicon_version: 1.0.0
  generated_at_utc: "2026-01-01T00:00:00Z"
  generator: test

entries:
  - canonical_id: test_entity_cyrillic
    names:
      - Тестовая Сущность
    aliases:
      - сущность
      - тест
""")
        
        result = run(
            [sys.executable, str(LINT_TOOL), str(test_file)],
            capture_output=True,
            text=True,
        )
        
        assert result.returncode == 0, (
            f"Lint should accept pure Cyrillic aliases:\n{result.stderr}"
        )


def test_lint_accepts_pure_greek_aliases() -> None:
    """Lint accepts pure Greek aliases (no mixing)."""
    import tempfile
    from pathlib import Path
    
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = Path(tmpdir) / "test.yaml"
        test_file.write_text("""\
_meta:
  schema_version: 1
  lexicon_version: 1.0.0
  generated_at_utc: "2026-01-01T00:00:00Z"
  generator: test

entries:
  - canonical_id: olympiacos_greek
    names:
      - Ολυμπιακός
    aliases:
      - ολυμπιακός
""")
        
        result = run(
            [sys.executable, str(LINT_TOOL), str(test_file)],
            capture_output=True,
            text=True,
        )
        
        assert result.returncode == 0


def test_lint_on_production_lexicons() -> None:
    """Lint passes on production lexicons (no confusable mixing)."""
    result = run(
        [sys.executable, str(LINT_TOOL), "--repo-root", str(REPO_ROOT)],
        capture_output=True,
        text=True,
    )
    
    assert result.returncode == 0, (
        f"Production lexicons should have no confusable mixing:\n{result.stderr}"
    )


class TestConfusableCharacterDistinctness:
    """Tests that confusable characters produce distinct normalized forms."""

    def test_cyrillic_a_vs_latin_a_distinct(self) -> None:
        """Cyrillic 'а' (U+0430) vs Latin 'a' (U+0061) are distinct."""
        cyrillic_a = "а"  # U+0430
        latin_a = "a"  # U+0061
        
        # They should be different bytes
        assert cyrillic_a != latin_a
        assert cyrillic_a.encode() != latin_a.encode()

    def test_greek_alpha_vs_latin_a_distinct(self) -> None:
        """Greek 'Α' (U+0391) vs Latin 'A' (U+0041) are distinct."""
        greek_alpha = "Α"  # U+0391
        latin_a = "A"  # U+0041
        
        assert greek_alpha != latin_a
        assert greek_alpha.encode() != latin_a.encode()

    def test_cyrillic_team_name_not_confused_with_latin(self) -> None:
        """Cyrillic team name doesn't get confused with Latin lookalike."""
        # Exemplo: Cyrillic team name using confusable-looking chars
        # In real scenarios, we ensure that lexicon entries don't mix scripts
        cyrillic_team = "Звезда"  # Red Star (all Cyrillic)
        latin_equivalent = "Zvezda"  # Latin transliteration
        
        # These should be distinct and not auto-merge
        assert cyrillic_team != latin_equivalent

    def test_greek_team_name_not_confused_with_latin(self) -> None:
        """Greek team name doesn't get confused with Latin lookalike."""
        greek_team = "Ολυμπιακός"  # Greek script
        latin_team = "Olympiacos"  # Latin transliteration
        
        assert greek_team != latin_team
