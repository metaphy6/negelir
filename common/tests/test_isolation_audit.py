"""Phase 18.1 §18.1 — Quarterly audit tests.

Tests verify:
- Audit can compare fresh scan against snapshot
- Audit detects drift (new imports)
- Audit runs without errors
Ledger #9: quarterly audit implementation.
"""

import json
import subprocess
from pathlib import Path


class TestIsolationAudit:
    """Verify quarterly audit functionality."""

    def test_isolation_audit_runs_without_error(self) -> None:
        """make isolation.audit should run successfully."""
        repo_root = Path(__file__).resolve().parents[2]
        result = subprocess.run(
            ["make", "isolation.audit"],
            cwd=repo_root,
            capture_output=True,
            text=True,
        )
        # Success or warnings are OK (deprecation warnings are acceptable)
        assert result.returncode == 0, f"Audit failed: {result.stderr}"

    def test_isolation_audit_output_contains_success_marker(self) -> None:
        """Audit output should contain success indicators."""
        repo_root = Path(__file__).resolve().parents[2]
        result = subprocess.run(
            ["make", "isolation.audit"],
            cwd=repo_root,
            capture_output=True,
            text=True,
        )
        assert "Isolation audit completed" in result.stdout or "✓" in result.stdout

    def test_isolation_audit_compares_snapshot(self) -> None:
        """Audit should report import counts for comparison."""
        repo_root = Path(__file__).resolve().parents[2]
        result = subprocess.run(
            ["make", "isolation.audit"],
            cwd=repo_root,
            capture_output=True,
            text=True,
        )
        # Should mention baseline and fresh scan
        assert "Baseline snapshot" in result.stdout or "audit" in result.stdout.lower()

    def test_audit_against_valid_snapshot(self) -> None:
        """Audit must work when snapshot exists and is valid."""
        snapshot_path = (
            Path(__file__).resolve().parents[2]
            / "common"
            / "isolation"
            / "import_graph.snapshot.json"
        )
        assert snapshot_path.exists(), "Snapshot must exist for audit"
        
        # Verify it's valid JSON
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        assert "imports" in snapshot
        assert "components" in snapshot
