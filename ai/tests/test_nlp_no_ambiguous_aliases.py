"""Phase 13.11.2 — Lint test for unambiguous lexicon aliases.

Ensures that no alias in the competition or team lexicon maps to multiple
canonical_ids (no ambiguous shortcuts).

Per LEAGUE_CATALOG.md §2.2 and §13.11.2, ambiguous aliases are forbidden.
"""
from __future__ import annotations

import sys
from pathlib import Path
from subprocess import run

import pytest

TEST_ROOT = Path(__file__).resolve().parent
REPO_ROOT = TEST_ROOT.parent.parent
LINT_TOOL = REPO_ROOT / "xops" / "lint" / "no_ambiguous_competition_aliases.py"

if not LINT_TOOL.exists():
    pytest.skip("Lint tool not found", allow_module_level=True)


def test_no_ambiguous_competition_aliases() -> None:
    """Lint: competition lexicon aliases are unambiguous."""
    result = run(
        [sys.executable, str(LINT_TOOL), "--repo-root", str(REPO_ROOT)],
        capture_output=True,
        text=True,
    )
    
    if result.returncode != 0:
        pytest.fail(
            f"Ambiguous aliases detected in lexicons:\n{result.stderr}"
        )
    
    assert "OK" in result.stdout, f"Unexpected output: {result.stdout}"


def test_lint_tool_rejects_ambiguous_aliases(tmp_path: Path) -> None:
    """Lint tool correctly rejects ambiguous aliases."""
    # Create a test lexicon with ambiguous aliases
    test_lexicon = tmp_path / "test_ambiguous.yaml"
    test_lexicon.write_text("""\
_meta:
  schema_version: 1
  lexicon_version: 1.0.0
  generated_at_utc: "2026-01-01T00:00:00Z"
  generator: test

entries:
  - canonical_id: comp_a
    names:
      - Competition A
    aliases:
      - kupa

  - canonical_id: comp_b
    names:
      - Competition B
    aliases:
      - kupa
""")
    
    result = run(
        [sys.executable, str(LINT_TOOL), str(test_lexicon)],
        capture_output=True,
        text=True,
    )
    
    # Lint should fail (return code 1)
    assert result.returncode == 1, (
        f"Lint should reject ambiguous aliases, but passed:\n{result.stdout}"
    )
    
    # Error message should mention the ambiguous alias
    assert "ambiguous" in result.stderr.lower(), (
        f"Error message should mention ambiguity:\n{result.stderr}"
    )


def test_lint_tool_accepts_distinct_aliases(tmp_path: Path) -> None:
    """Lint tool accepts lexicon with distinct aliases."""
    test_lexicon = tmp_path / "test_distinct.yaml"
    test_lexicon.write_text("""\
_meta:
  schema_version: 1
  lexicon_version: 1.0.0
  generated_at_utc: "2026-01-01T00:00:00Z"
  generator: test

entries:
  - canonical_id: comp_a
    names:
      - Competition A
    aliases:
      - kupa_a

  - canonical_id: comp_b
    names:
      - Competition B
    aliases:
      - kupa_b
""")
    
    result = run(
        [sys.executable, str(LINT_TOOL), str(test_lexicon)],
        capture_output=True,
        text=True,
    )
    
    assert result.returncode == 0, (
        f"Lint should accept distinct aliases, but failed:\n{result.stderr}"
    )
