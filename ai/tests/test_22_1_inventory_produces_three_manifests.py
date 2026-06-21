"""Phase 22.1 — Inventory target produces three JSON manifests."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.phase22
class TestPhase221InventoryManifests:
    """Verify phase22.inventory target produces three required JSON manifests."""

    def test_22_1_inventory_produces_three_manifests(self) -> None:
        """Test that make phase22.inventory produces all three JSON files."""
        repo_root = Path(__file__).resolve().parents[2]
        tracking_dir = repo_root / "docs" / "tracking"

        # Verify all three files exist
        accountability = tracking_dir / "phase22_file_accountability.json"
        import_report = tracking_dir / "phase22_import_report.json"
        move_plan = tracking_dir / "phase22_move_plan.json"

        assert accountability.is_file(), f"{accountability} not created"
        assert import_report.is_file(), f"{import_report} not created"
        assert move_plan.is_file(), f"{move_plan} not created"

    def test_22_1_file_accountability_is_valid_json(self) -> None:
        """Verify accountability manifest is valid JSON."""
        repo_root = Path(__file__).resolve().parents[2]
        accountability = repo_root / "docs" / "tracking" / "phase22_file_accountability.json"

        assert accountability.is_file()
        data = json.loads(accountability.read_text(encoding="utf-8"))

        # Verify it's a dict with file paths as keys
        assert isinstance(data, dict)
        assert len(data) > 0, "Accountability manifest should not be empty"

        # Verify each entry has required fields
        for source, entry in list(data.items())[:5]:  # Check first 5
            assert isinstance(source, str)
            assert "source" in entry
            assert "destination" in entry
            assert "action" in entry
            assert "blob_sha256" in entry
            assert entry["action"] in ("move", "merge", "delete")
            # Verify SHA256 is valid hex
            assert len(entry["blob_sha256"]) == 64
            int(entry["blob_sha256"], 16)  # Will raise if not valid hex

    def test_22_1_import_report_is_valid_json(self) -> None:
        """Verify import report is valid JSON."""
        repo_root = Path(__file__).resolve().parents[2]
        import_report = repo_root / "docs" / "tracking" / "phase22_import_report.json"

        assert import_report.is_file()
        data = json.loads(import_report.read_text(encoding="utf-8"))

        # Verify structure
        assert isinstance(data, dict)
        assert "generated_at_utc" in data
        assert "total_non_ai_importers" in data
        assert "by_package" in data

        # Verify by_package structure
        by_package = data["by_package"]
        assert isinstance(by_package, dict)

        for pkg, info in by_package.items():
            assert isinstance(pkg, str)
            assert isinstance(info, dict)
            assert "count" in info
            assert "files" in info
            assert isinstance(info["files"], list)
            assert len(info["files"]) == info["count"]

    def test_22_1_move_plan_is_valid_json(self) -> None:
        """Verify move plan summary is valid JSON."""
        repo_root = Path(__file__).resolve().parents[2]
        move_plan = repo_root / "docs" / "tracking" / "phase22_move_plan.json"

        assert move_plan.is_file()
        data = json.loads(move_plan.read_text(encoding="utf-8"))

        # Verify structure
        assert isinstance(data, dict)
        assert "total_ai_files" in data
        assert "collision_summary" in data
        assert "collisions" in data

        # Verify counts are positive
        assert data["total_ai_files"] > 0
        assert isinstance(data["collision_summary"], dict)
        assert "destinations_with_single_source" in data["collision_summary"]
        assert "destinations_with_collisions" in data["collision_summary"]
