"""Phase 22.2 bullet 11 — Proof: annotation corpus byte-equal output.

All 15+ corpus entries match their expected output exactly.
This validates byte-for-byte consistency of rewrite transformations.
"""

from __future__ import annotations

import pytest
from xops.codemod.tests.annotation_corpus import CORPUS
from xops.codemod.phase22_rewriter import Phase22ImportRewriter


class TestAnnotationCorpusByteEqual:
    """Proof: annotation corpus entries produce byte-identical output."""

    @pytest.mark.parametrize(
        "entry",
        CORPUS,
        ids=[e["name"] for e in CORPUS],
    )
    def test_corpus_entry_byte_equal(self, entry: dict) -> None:
        """Each corpus entry matches expected output exactly."""
        name = entry["name"]
        input_code = entry["input_code"]
        expected_output = entry["expected_output"]

        # Determine package from entry (infer from input)
        # For multi-package files, use package="" to rewrite all packages
        packages_found = []
        for pkg in ["common", "nlp", "swarm", "datasource", "model", "scraper"]:
            if f"ai.{pkg}" in input_code:
                packages_found.append(pkg)
        
        # If multiple packages found, use empty package to rewrite all
        # If single package found, use that package for focused testing
        # If no packages found, use empty string
        if len(packages_found) > 1:
            package = ""
        elif len(packages_found) == 1:
            package = packages_found[0]
        else:
            package = ""

        result, status = Phase22ImportRewriter.rewrite_source(input_code, package=package)

        # Verify exact match
        assert result == expected_output, f"Corpus entry '{name}' mismatch:\n" \
                                          f"Expected:\n{repr(expected_output)}\n" \
                                          f"Got:\n{repr(result)}"

    def test_corpus_count_minimum(self) -> None:
        """At least 15 corpus entries exist."""
        assert len(CORPUS) >= 15, f"Corpus must have ≥15 entries, got {len(CORPUS)}"

    def test_corpus_entries_have_required_fields(self) -> None:
        """All corpus entries have required fields."""
        for entry in CORPUS:
            assert "name" in entry, "Missing 'name' field"
            assert "input_code" in entry, "Missing 'input_code' field"
            assert "expected_output" in entry, "Missing 'expected_output' field"
