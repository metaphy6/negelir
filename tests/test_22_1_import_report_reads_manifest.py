"""Phase 22.1 §22.1 bullet 2 — Import report target reads manifest and prints summary."""
from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture
def sample_import_report() -> dict[str, Any]:
    """Sample import report structure matching phase22_import_report.json format."""
    return {
        "generated_at_utc": "1782039847.551548",
        "total_non_ai_importers": 69,
        "by_package": {
            "X": {
                "count": 1,
                "files": ["xops/makefile/phase22.py"],
            },
            "common": {
                "count": 45,
                "files": [
                    "common/bus/__init__.py",
                    "xops/backup/credential_provider.py",
                    "xops/opsctl/subcommands/scale.py",
                ],
            },
            "nlp": {
                "count": 1,
                "files": ["xops/makefile/nlp.py"],
            },
            "swarm": {
                "count": 21,
                "files": [
                    "docs/testing/_demos/source_watcher_60pct.py",
                    "xops/lint/no_fault_injection_in_prod_paths.py",
                    "xops/opsctl/subcommands/dlq_show.py",
                ],
            },
            "tests": {
                "count": 1,
                "files": ["xops/makefile/calibration.py"],
            },
        },
    }


class TestImportReportReadsManifest:
    """Test that make phase22.import-report reads manifest and prints summary."""

    def test_import_report_reads_existing_manifest(
        self, tmp_path: Path, sample_import_report: dict[str, Any]
    ) -> None:
        """Verify import-report command reads manifest and exits 0."""
        tracking_dir = tmp_path / "docs" / "tracking"
        tracking_dir.mkdir(parents=True, exist_ok=True)
        
        manifest = tracking_dir / "phase22_import_report.json"
        manifest.write_text(json.dumps(sample_import_report, indent=2), encoding="utf-8")
        
        # Mock the REPO_ROOT to point to tmp_path
        import sys
        import xops.makefile.phase22 as phase22_module
        
        orig_repo_root = phase22_module.REPO_ROOT
        try:
            phase22_module.REPO_ROOT = tmp_path
            result = phase22_module.cmd_import_report([])
            assert result == 0
        finally:
            phase22_module.REPO_ROOT = orig_repo_root

    def test_import_report_includes_total_count(
        self, tmp_path: Path, sample_import_report: dict[str, Any], capsys: Any
    ) -> None:
        """Verify output includes total non-ai/ importer count."""
        tracking_dir = tmp_path / "docs" / "tracking"
        tracking_dir.mkdir(parents=True, exist_ok=True)
        
        manifest = tracking_dir / "phase22_import_report.json"
        manifest.write_text(json.dumps(sample_import_report, indent=2), encoding="utf-8")
        
        import xops.makefile.phase22 as phase22_module
        orig_repo_root = phase22_module.REPO_ROOT
        try:
            phase22_module.REPO_ROOT = tmp_path
            phase22_module.cmd_import_report([])
            captured = capsys.readouterr()
            output = captured.out
            
            # Verify total count is printed
            assert "Total non-ai/ files importing from ai.*: 69" in output
        finally:
            phase22_module.REPO_ROOT = orig_repo_root

    def test_import_report_includes_per_package_breakdown(
        self, tmp_path: Path, sample_import_report: dict[str, Any], capsys: Any
    ) -> None:
        """Verify output includes per-package caller counts."""
        tracking_dir = tmp_path / "docs" / "tracking"
        tracking_dir.mkdir(parents=True, exist_ok=True)
        
        manifest = tracking_dir / "phase22_import_report.json"
        manifest.write_text(json.dumps(sample_import_report, indent=2), encoding="utf-8")
        
        import xops.makefile.phase22 as phase22_module
        orig_repo_root = phase22_module.REPO_ROOT
        try:
            phase22_module.REPO_ROOT = tmp_path
            phase22_module.cmd_import_report([])
            captured = capsys.readouterr()
            output = captured.out
            
            # Verify per-package counts
            assert "common" in output and "45" in output
            assert "nlp" in output and "1" in output
            assert "swarm" in output and "21" in output
        finally:
            phase22_module.REPO_ROOT = orig_repo_root

    def test_import_report_includes_file_breakdown(
        self, tmp_path: Path, sample_import_report: dict[str, Any], capsys: Any
    ) -> None:
        """Verify output includes file-level breakdown for each package."""
        tracking_dir = tmp_path / "docs" / "tracking"
        tracking_dir.mkdir(parents=True, exist_ok=True)
        
        manifest = tracking_dir / "phase22_import_report.json"
        manifest.write_text(json.dumps(sample_import_report, indent=2), encoding="utf-8")
        
        import xops.makefile.phase22 as phase22_module
        orig_repo_root = phase22_module.REPO_ROOT
        try:
            phase22_module.REPO_ROOT = tmp_path
            phase22_module.cmd_import_report([])
            captured = capsys.readouterr()
            output = captured.out
            
            # Verify individual files are listed
            assert "xops/makefile/phase22.py" in output
            assert "common/bus/__init__.py" in output
            assert "xops/backup/credential_provider.py" in output
        finally:
            phase22_module.REPO_ROOT = orig_repo_root

    def test_import_report_groups_by_root_package(
        self, tmp_path: Path, sample_import_report: dict[str, Any], capsys: Any
    ) -> None:
        """Verify output includes summary grouped by root package."""
        tracking_dir = tmp_path / "docs" / "tracking"
        tracking_dir.mkdir(parents=True, exist_ok=True)
        
        manifest = tracking_dir / "phase22_import_report.json"
        manifest.write_text(json.dumps(sample_import_report, indent=2), encoding="utf-8")
        
        import xops.makefile.phase22 as phase22_module
        orig_repo_root = phase22_module.REPO_ROOT
        try:
            phase22_module.REPO_ROOT = tmp_path
            phase22_module.cmd_import_report([])
            captured = capsys.readouterr()
            output = captured.out
            
            # Verify summary by root package is present
            assert "Summary by root package:" in output
            # xops is the root package for most files
            assert "xops" in output
            assert "common" in output
            assert "docs" in output
        finally:
            phase22_module.REPO_ROOT = orig_repo_root

    def test_import_report_missing_manifest_returns_error(self, tmp_path: Path) -> None:
        """Verify command returns 1 when manifest is missing."""
        tracking_dir = tmp_path / "docs" / "tracking"
        tracking_dir.mkdir(parents=True, exist_ok=True)
        
        import xops.makefile.phase22 as phase22_module
        orig_repo_root = phase22_module.REPO_ROOT
        try:
            phase22_module.REPO_ROOT = tmp_path
            # Don't create the manifest file
            result = phase22_module.cmd_import_report([])
            assert result == 1
        finally:
            phase22_module.REPO_ROOT = orig_repo_root

    def test_import_report_handles_corrupted_manifest(self, tmp_path: Path) -> None:
        """Verify command returns 1 when manifest is corrupted JSON."""
        tracking_dir = tmp_path / "docs" / "tracking"
        tracking_dir.mkdir(parents=True, exist_ok=True)
        
        manifest = tracking_dir / "phase22_import_report.json"
        manifest.write_text("not valid json {[", encoding="utf-8")
        
        import xops.makefile.phase22 as phase22_module
        orig_repo_root = phase22_module.REPO_ROOT
        try:
            phase22_module.REPO_ROOT = tmp_path
            result = phase22_module.cmd_import_report([])
            assert result == 1
        finally:
            phase22_module.REPO_ROOT = orig_repo_root

    def test_import_report_output_is_readable(
        self, tmp_path: Path, sample_import_report: dict[str, Any], capsys: Any
    ) -> None:
        """Verify output is well-formatted and human-readable."""
        tracking_dir = tmp_path / "docs" / "tracking"
        tracking_dir.mkdir(parents=True, exist_ok=True)
        
        manifest = tracking_dir / "phase22_import_report.json"
        manifest.write_text(json.dumps(sample_import_report, indent=2), encoding="utf-8")
        
        import xops.makefile.phase22 as phase22_module
        orig_repo_root = phase22_module.REPO_ROOT
        try:
            phase22_module.REPO_ROOT = tmp_path
            phase22_module.cmd_import_report([])
            captured = capsys.readouterr()
            output = captured.out
            
            # Verify formatting
            assert "=" * 70 in output
            assert "Phase 22.1" in output
            assert "Inventory" in output
            # Verify bullets for files
            assert "•" in output
        finally:
            phase22_module.REPO_ROOT = orig_repo_root
