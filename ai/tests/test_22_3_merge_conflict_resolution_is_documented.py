"""Phase 22.3 §22.3.0 — Merge conflict resolution playbook test.

Validates that the canonical merge-strategy documents exist and contain
all required decisions before any files move.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


_ROOT = Path(__file__).parent.parent.parent
_DECISIONS_DIR = _ROOT / "docs" / "decisions" / "phase22"


class TestPhase223PlaybookStructure:
    """Verify both playbook documents exist and have required sections."""

    def test_merge_strategy_playbook_exists(self) -> None:
        """Test that 22_3_merge_strategy.md exists."""
        path = _DECISIONS_DIR / "22_3_merge_strategy.md"
        assert path.exists(), f"Playbook missing: {path}"

    def test_common_merge_decisions_exists(self) -> None:
        """Test that common_merge_decisions.md exists."""
        path = _DECISIONS_DIR / "common_merge_decisions.md"
        assert path.exists(), f"Common merge decisions missing: {path}"

    def test_playbook_has_required_sections(self) -> None:
        """Test that 22_3_merge_strategy.md has all required sections."""
        path = _DECISIONS_DIR / "22_3_merge_strategy.md"
        content = path.read_text(encoding="utf-8")

        required_sections = [
            "Overview of the Four Merge Targets",
            "Heterogeneous Authority Principle",
            "Decision-Tree Algorithm",
            "Applying the Principle to §22.3a",
            "Symbol-Union Preservation Gate",
            "Ledger References",
            "Testing the Playbook",
            "Rollback Strategy",
        ]

        for section in required_sections:
            assert section in content, f"Missing section in playbook: {section}"

    def test_common_merge_has_required_sections(self) -> None:
        """Test that common_merge_decisions.md has all required sections."""
        path = _DECISIONS_DIR / "common_merge_decisions.md"
        content = path.read_text(encoding="utf-8")

        required_sections = [
            "Per-Sub-Package Authority & Merge Action",
            "Per-File Conflict Resolution",
            "Root-Only Isolation Files",
            "AI-Only Move-Ins",
            "Deprecation Calendar Entries",
            "Symbol-Union Audit Checklist",
            "Proof Tests",
            "Rollback Instructions",
            "Bookkeeping",
        ]

        for section in required_sections:
            assert section in content, f"Missing section in common_merge_decisions: {section}"


class TestPhase223MergeDecisions:
    """Verify all required merge decisions are documented."""

    def test_five_overlapping_common_subpackages_documented(self) -> None:
        """Test that all 5 overlapping sub-packages have documented authority."""
        path = _DECISIONS_DIR / "common_merge_decisions.md"
        content = path.read_text(encoding="utf-8")

        required_overlaps = [
            "common/bus/",
            "common/config/",
            "common/db/",
            "common/isolation/",
            "common/observability/",
            "common/security/",
        ]

        for overlap in required_overlaps:
            assert overlap in content, f"Missing documented overlap: {overlap}"

    def test_two_file_collisions_documented(self) -> None:
        """Test that both top-level file collisions are documented."""
        path = _DECISIONS_DIR / "common_merge_decisions.md"
        content = path.read_text(encoding="utf-8")

        required_files = [
            "common/logger.py",
            "common/international_tournament_profiles.py",
        ]

        for file in required_files:
            assert file in content, f"Missing documented file collision: {file}"

    def test_isolation_four_root_only_files_documented(self) -> None:
        """Test that the 4 root-only isolation files are documented."""
        path = _DECISIONS_DIR / "common_merge_decisions.md"
        content = path.read_text(encoding="utf-8")

        required_files = [
            "go_check.go",
            "graph_builder.py",
            "forbidden_deps.yaml",
            "import_graph.snapshot.json",
        ]

        for file in required_files:
            assert file in content, f"Missing documented root-only file: {file}"

    def test_heterogeneous_authority_principle_documented(self) -> None:
        """Test that the heterogeneous authority principle is explained."""
        path = _DECISIONS_DIR / "22_3_merge_strategy.md"
        content = path.read_text(encoding="utf-8")

        assert "heterogeneous" in content.lower(), "Heterogeneous authority not documented"
        assert "shim" in content.lower(), "Shim concept not documented"
        assert "authoritative" in content.lower(), "Authority decisions not documented"

    def test_ledger_references_cited(self) -> None:
        """Test that relevant ledger rows are referenced."""
        path = _DECISIONS_DIR / "22_3_merge_strategy.md"
        content = path.read_text(encoding="utf-8")

        required_ledger_refs = [
            "#2",   # Overlapping sub-packages verified
            "#27",  # Isolation per-file audit
            "#36",  # Heterogeneous authority
            "#43",  # File-accountability
            "#44",  # Symbol-union preservation
            "#45",  # Content-hash preservation
        ]

        for ref in required_ledger_refs:
            assert ref in content, f"Missing ledger reference: {ref}"

    def test_decision_tree_algorithm_documented(self) -> None:
        """Test that the decision-tree algorithm is present."""
        path = _DECISIONS_DIR / "22_3_merge_strategy.md"
        content = path.read_text(encoding="utf-8")

        required_keywords = [
            "Identify the overlap",
            "Classify the root version",
            "Real implementation",
            "Shim",
            "Stub",
        ]

        for keyword in required_keywords:
            assert keyword in content, f"Missing decision-tree keyword: {keyword}"


class TestPhase223SymbolUnionGate:
    """Verify symbol-union preservation gate is documented."""

    def test_symbol_union_gate_documented(self) -> None:
        """Test that symbol-union gate is described."""
        path = _DECISIONS_DIR / "22_3_merge_strategy.md"
        content = path.read_text(encoding="utf-8")

        assert "Symbol-Union Preservation Gate" in content, "Symbol-union gate not documented"
        assert "public surface" in content.lower(), "Public surface concept not documented"
        assert "merge" in content, "Merge concept not documented"

    def test_file_accountability_gate_documented(self) -> None:
        """Test that file-accountability gate is described."""
        path = _DECISIONS_DIR / "22_3_merge_strategy.md"
        content = path.read_text(encoding="utf-8")

        assert "File Accountability" in content, "File-accountability gate not documented"
        assert "source file" in content.lower(), "Source file tracking not documented"

    def test_content_hash_gate_documented(self) -> None:
        """Test that content-hash preservation gate is described."""
        path = _DECISIONS_DIR / "22_3_merge_strategy.md"
        content = path.read_text(encoding="utf-8")

        assert "Content-Hash" in content, "Content-hash gate not documented"
        assert "byte-identical" in content.lower(), "Byte-identity checking not documented"


class TestPhase223ProofTests:
    """Verify proof tests are enumerated."""

    def test_proof_tests_enumerated_in_playbook(self) -> None:
        """Test that common_merge_decisions.md lists all required proof tests."""
        path = _DECISIONS_DIR / "common_merge_decisions.md"
        content = path.read_text(encoding="utf-8")

        required_tests = [
            "test_22_3a_common_merge_no_duplicate_symbols",
            "test_22_3a_merge_preserves_symbol_union",
            "test_22_3a_file_accountability_complete",
            "test_22_3a_no_forced_git_mv",
            "test_22_3a_isolation_root_only_files_preserved",
            "test_22_3a_config_init_no_longer_imports_ai",
            "test_22_3a_bus_shim_flipped_no_reexport_from_ai",
            "test_22_3a_feeds_and_api_are_pure_move_ins",
            "test_22_3a_betting_markets_config_key_updated",
            "test_22_3a_entitlements_deduplicated",
        ]

        for test in required_tests:
            assert test in content, f"Missing proof test enumeration: {test}"


class TestPhase223RollbackGate:
    """Verify rollback instructions are documented."""

    def test_rollback_strategy_documented(self) -> None:
        """Test that rollback strategy is present."""
        path = _DECISIONS_DIR / "22_3_merge_strategy.md"
        content = path.read_text(encoding="utf-8")

        assert "Rollback Strategy" in content, "Rollback strategy not documented"
        assert "make phase22.rollback" in content, "Rollback command not documented"

    def test_rollback_instructions_per_subphase(self) -> None:
        """Test that rollback instructions exist in common_merge_decisions.md."""
        path = _DECISIONS_DIR / "common_merge_decisions.md"
        content = path.read_text(encoding="utf-8")

        assert "Rollback Instructions" in content, "Rollback instructions not documented"
        assert "git revert" in content, "Git revert not mentioned in rollback"


class TestPhase223Bookkeeping:
    """Verify bookkeeping instructions are documented."""

    def test_tracker_row_format_documented(self) -> None:
        """Test that tracker row format is documented."""
        path = _DECISIONS_DIR / "common_merge_decisions.md"
        content = path.read_text(encoding="utf-8")

        assert "make track.add" in content, "Tracker row format not documented"
        assert "PHASE=22" in content, "Phase number not in tracker example"

    def test_version_bump_format_documented(self) -> None:
        """Test that version bump format is documented."""
        path = _DECISIONS_DIR / "common_merge_decisions.md"
        content = path.read_text(encoding="utf-8")

        assert "make version.bump" in content, "Version bump format not documented"
        assert "COMPONENT=xops" in content, "Component not in version bump example"

    def test_roadmap_checkbox_flip_documented(self) -> None:
        """Test that ROADMAP checkbox flip is documented."""
        path = _DECISIONS_DIR / "common_merge_decisions.md"
        content = path.read_text(encoding="utf-8")

        assert "ROADMAP checkboxes" in content, "ROADMAP checkbox flip not documented"
        assert "[x]" in content, "Checkbox syntax not shown"


class TestPhase223LedgerConsistency:
    """Verify ledger references are consistent between documents."""

    def test_ledger_refs_consistent_across_documents(self) -> None:
        """Test that ledger refs cited in both docs refer to the same rows."""
        playbook_path = _DECISIONS_DIR / "22_3_merge_strategy.md"
        decisions_path = _DECISIONS_DIR / "common_merge_decisions.md"

        playbook_content = playbook_path.read_text(encoding="utf-8")
        decisions_content = decisions_path.read_text(encoding="utf-8")

        # Extract ledger refs from playbook
        playbook_refs = set()
        for line in playbook_content.split("\n"):
            if "Ledger" in line and "#" in line:
                # Simple extraction: look for #N patterns
                import re

                matches = re.findall(r"#(\d+)", line)
                playbook_refs.update(matches)

        # Extract ledger refs from decisions
        decisions_refs = set()
        for line in decisions_content.split("\n"):
            if "Ledger" in line and "#" in line:
                import re

                matches = re.findall(r"#(\d+)", line)
                decisions_refs.update(matches)

        # Both should cite at least overlapping references
        assert len(playbook_refs & decisions_refs) > 0, "No common ledger refs between documents"


class TestPhase223AuthorityTable:
    """Verify the authority table in common_merge_decisions.md is complete."""

    def test_authority_table_has_six_rows(self) -> None:
        """Test that authority table has entries for all 6 overlapping sub-packages."""
        path = _DECISIONS_DIR / "common_merge_decisions.md"
        content = path.read_text(encoding="utf-8")

        # The table should have 6 data rows (bus, config, db, isolation, observability, security)
        assert "common/bus/" in content, "Bus row missing"
        assert "common/config/" in content, "Config row missing"
        assert "common/db/" in content, "DB row missing"
        assert "common/isolation/" in content, "Isolation row missing"
        assert "common/observability/" in content, "Observability row missing"
        assert "common/security/" in content, "Security row missing"

    def test_authority_classification_present(self) -> None:
        """Test that each overlap is classified as Real/Shim/Stub."""
        path = _DECISIONS_DIR / "common_merge_decisions.md"
        content = path.read_text(encoding="utf-8")

        # Should classify bus and config as Shims
        assert "**Shim**" in content, "Shim classification not used"

        # Should classify others as Real implementations
        assert "**Real" in content or "Real root impl" in content, "Real impl classification not used"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
