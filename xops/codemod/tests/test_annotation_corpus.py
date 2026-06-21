"""Phase 22.2 bullet 4 — Annotation corpus validation tests.

Tests the annotation_corpus.py entries:
  1. test_annotation_corpus_entries_match_expected_output() — byte-for-byte comparison
  2. test_annotation_corpus_non_targets_unchanged() — verify non-targets are unchanged
"""

from __future__ import annotations

import pytest
from xops.codemod.phase22_rewriter import Phase22ImportRewriter
from xops.codemod.tests.annotation_corpus import CORPUS, NON_TARGET_EXAMPLES


class TestAnnotationCorpus:
    """Validate all corpus entries against expected outputs."""

    def test_annotation_corpus_entries_match_expected_output(self) -> None:
        """
        Iterate all corpus entries and verify each produces byte-for-byte
        matching expected output when passed through Phase22ImportRewriter.
        
        Fails with line-by-line diff on any mismatch.
        """
        failures: list[tuple[str, str]] = []
        
        for entry in CORPUS:
            name = entry["name"]
            input_code = entry["input_code"]
            expected_output = entry["expected_output"]
            
            # Run rewriter on input (with no package filter to rewrite all ai.* patterns)
            rewritten = Phase22ImportRewriter.rewrite_source(input_code, package="")
            
            # Byte-for-byte comparison
            if rewritten != expected_output:
                # Prepare detailed diff for debugging
                input_lines = input_code.split("\n")
                expected_lines = expected_output.split("\n")
                actual_lines = rewritten.split("\n")
                
                # Line-by-line comparison
                diff_lines: list[str] = [f"\nCorpus entry '{name}' mismatch:"]
                max_line_count = max(len(expected_lines), len(actual_lines))
                
                for i in range(max_line_count):
                    exp = expected_lines[i] if i < len(expected_lines) else "<missing>"
                    act = actual_lines[i] if i < len(actual_lines) else "<missing>"
                    
                    if exp != act:
                        diff_lines.append(f"  Line {i + 1}:")
                        diff_lines.append(f"    Expected: {exp!r}")
                        diff_lines.append(f"    Actual:   {act!r}")
                
                failures.append((name, "\n".join(diff_lines)))
        
        # Report all failures
        if failures:
            error_msg = "\n".join(f"[{name}]{diff}" for name, diff in failures)
            pytest.fail(f"Corpus validation failed:\n{error_msg}")

    def test_annotation_corpus_non_targets_unchanged(self) -> None:
        """
        Verify that non-target examples (SQL strings, log messages, comments)
        are NOT rewritten by the codemod.
        
        Fails if any non-target is modified.
        """
        failures: list[tuple[str, str]] = []
        
        for example in NON_TARGET_EXAMPLES:
            name = example["name"]
            code = example["code"]
            description = example["description"]
            
            # Run rewriter (should not modify this code)
            rewritten = Phase22ImportRewriter.rewrite_source(code, package="")
            
            # Verify unchanged
            if rewritten != code:
                failure_msg = (
                    f"Non-target example '{name}' was modified (should be unchanged):\n"
                    f"  Description: {description}\n"
                    f"  Original:  {code!r}\n"
                    f"  Rewritten: {rewritten!r}"
                )
                failures.append((name, failure_msg))
        
        # Report all failures
        if failures:
            error_msg = "\n".join(msg for _, msg in failures)
            pytest.fail(f"Non-target validation failed:\n{error_msg}")

    def test_annotation_corpus_has_minimum_15_entries(self) -> None:
        """Verify corpus has at least 15 representative patterns."""
        assert len(CORPUS) >= 15, (
            f"Corpus must have ≥15 entries (ROADMAP §22.2 bullet 4), "
            f"found {len(CORPUS)}"
        )

    def test_annotation_corpus_covers_all_7_patterns(self) -> None:
        """
        Verify corpus covers all 7 rewrite patterns.
        
        Patterns:
          1. from ai.<pkg>.<mod> import X
          2. import ai.<pkg>
          3. Quoted type annotations "ai.<pkg>.<Class>"
          4. TYPE_CHECKING block imports
          5. __all__ re-exports
          6. Pydantic model_rebuild() calls
          7. Provenance headers # negelir-generated-from: ai/
        """
        pattern_markers = {
            1: ("from ai.", "pattern_1"),
            2: ("import ai.", "pattern_2"),
            3: ('ai.', "pattern_3"),  # Quoted types
            4: ("TYPE_CHECKING", "pattern_4"),
            5: ("__all__", "pattern_5"),
            6: ("model_rebuild", "pattern_6"),
            7: ("negelir-generated-from:", "pattern_7"),
        }
        
        found_patterns: set[int] = set()
        
        for entry in CORPUS:
            name = entry["name"]
            input_code = entry["input_code"]
            
            # Check for pattern markers
            if "from ai." in input_code and ("import" in input_code or "TYPE_CHECKING" not in input_code):
                found_patterns.add(1)
            if "import ai." in input_code and "from ai." not in input_code:
                found_patterns.add(2)
            if '"ai.' in input_code or "'ai." in input_code:
                found_patterns.add(3)
            if "TYPE_CHECKING" in input_code:
                found_patterns.add(4)
            if "__all__" in input_code:
                found_patterns.add(5)
            if "model_rebuild" in input_code or "update_forward_refs" in input_code:
                found_patterns.add(6)
            if "negelir-generated-from:" in input_code:
                found_patterns.add(7)
        
        missing = set(range(1, 8)) - found_patterns
        assert not missing, (
            f"Corpus is missing coverage for patterns: {sorted(missing)}. "
            f"All 7 patterns must be represented (ROADMAP §22.2 bullet 4)"
        )

    def test_annotation_corpus_entries_have_all_required_fields(self) -> None:
        """Verify each corpus entry has required fields."""
        required_fields = {"name", "input_code", "expected_output"}
        
        for i, entry in enumerate(CORPUS):
            missing = required_fields - set(entry.keys())
            assert not missing, (
                f"Corpus entry {i} ({entry.get('name', '?')}) missing fields: {missing}"
            )


# ─────────────────────────────────────────────────────────────────────────
# Integration: Verify individual patterns with focused tests
# ─────────────────────────────────────────────────────────────────────────

class TestCorpusPatternIndividual:
    """Focused tests for individual patterns to aid debugging."""

    def test_pattern_1_basic_from_import(self) -> None:
        """Pattern 1: from ai.<pkg>.<mod> import X"""
        # Find the pattern 1 corpus entry
        entry = next((e for e in CORPUS if e["name"] == "pattern_1_basic_from_import"), None)
        assert entry is not None, "Corpus missing pattern_1_basic_from_import entry"
        
        rewritten = Phase22ImportRewriter.rewrite_source(entry["input_code"], package="")
        assert rewritten == entry["expected_output"], (
            f"Pattern 1 mismatch:\n"
            f"Expected:\n{entry['expected_output']!r}\n"
            f"Got:\n{rewritten!r}"
        )

    def test_pattern_2_import_with_alias(self) -> None:
        """Pattern 2: import ai.<pkg> → import <pkg> as <pkg>"""
        entry = next((e for e in CORPUS if e["name"] == "pattern_2_import_with_alias"), None)
        assert entry is not None, "Corpus missing pattern_2_import_with_alias entry"
        
        rewritten = Phase22ImportRewriter.rewrite_source(entry["input_code"], package="")
        assert rewritten == entry["expected_output"]

    def test_pattern_3_quoted_type_in_annotation(self) -> None:
        """Pattern 3: Quoted type annotations"""
        entry = next((e for e in CORPUS if e["name"] == "pattern_3_quoted_type_in_annotation"), None)
        assert entry is not None, "Corpus missing pattern_3_quoted_type_in_annotation entry"
        
        rewritten = Phase22ImportRewriter.rewrite_source(entry["input_code"], package="")
        assert rewritten == entry["expected_output"]

    def test_pattern_4_type_checking_import(self) -> None:
        """Pattern 4: TYPE_CHECKING block imports"""
        entry = next((e for e in CORPUS if e["name"] == "pattern_4_type_checking_import"), None)
        assert entry is not None, "Corpus missing pattern_4_type_checking_import entry"
        
        rewritten = Phase22ImportRewriter.rewrite_source(entry["input_code"], package="")
        assert rewritten == entry["expected_output"]

    def test_pattern_5_all_tuple_reexport(self) -> None:
        """Pattern 5: __all__ re-exports"""
        entry = next((e for e in CORPUS if e["name"] == "pattern_5_all_tuple_reexport"), None)
        assert entry is not None, "Corpus missing pattern_5_all_tuple_reexport entry"
        
        rewritten = Phase22ImportRewriter.rewrite_source(entry["input_code"], package="")
        assert rewritten == entry["expected_output"]

    def test_pattern_6_pydantic_model_rebuild(self) -> None:
        """Pattern 6: Pydantic model_rebuild() calls"""
        entry = next((e for e in CORPUS if e["name"] == "pattern_6_pydantic_model_rebuild"), None)
        assert entry is not None, "Corpus missing pattern_6_pydantic_model_rebuild entry"
        
        rewritten = Phase22ImportRewriter.rewrite_source(entry["input_code"], package="")
        assert rewritten == entry["expected_output"]

    def test_pattern_7_provenance_header(self) -> None:
        """Pattern 7: Provenance headers"""
        entry = next((e for e in CORPUS if e["name"] == "pattern_7_provenance_header"), None)
        assert entry is not None, "Corpus missing pattern_7_provenance_header entry"
        
        rewritten = Phase22ImportRewriter.rewrite_source(entry["input_code"], package="")
        assert rewritten == entry["expected_output"]


__all__ = [
    "TestAnnotationCorpus",
    "TestCorpusPatternIndividual",
]
