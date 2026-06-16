"""Phase 18.1 §18.1 — Snapshot component coverage tests.

Verifies that the snapshot includes expected components and their imports.
Ledger #16, #30: tests verify snapshot captures all components.
"""

import json
from pathlib import Path


class TestIsolationSnapshotComponentCoverage:
    """Verify snapshot includes expected components."""

    def test_snapshot_includes_ai_component(self) -> None:
        """Snapshot must include ai component."""
        snapshot_path = (
            Path(__file__).resolve().parents[2]
            / "common"
            / "isolation"
            / "import_graph.snapshot.json"
        )
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        assert "ai" in snapshot["components"]
        assert "ai" in snapshot["imports"]

    def test_snapshot_includes_common_component(self) -> None:
        """Snapshot must include common component."""
        snapshot_path = (
            Path(__file__).resolve().parents[2]
            / "common"
            / "isolation"
            / "import_graph.snapshot.json"
        )
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        assert "common" in snapshot["components"]
        assert "common" in snapshot["imports"]

    def test_ai_component_has_imports(self) -> None:
        """AI component should have detected imports from scanning."""
        snapshot_path = (
            Path(__file__).resolve().parents[2]
            / "common"
            / "isolation"
            / "import_graph.snapshot.json"
        )
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        assert len(snapshot["imports"]["ai"]) > 0, "AI component should have imports"

    def test_snapshot_violations_list_exists(self) -> None:
        """Violations list must exist (even if empty)."""
        snapshot_path = (
            Path(__file__).resolve().parents[2]
            / "common"
            / "isolation"
            / "import_graph.snapshot.json"
        )
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        assert "violations" in snapshot
        assert isinstance(snapshot["violations"], list)

    def test_snapshot_roundtrip_json(self) -> None:
        """Snapshot must survive JSON roundtrip without data loss."""
        snapshot_path = (
            Path(__file__).resolve().parents[2]
            / "common"
            / "isolation"
            / "import_graph.snapshot.json"
        )
        original = snapshot_path.read_text(encoding="utf-8")
        snapshot = json.loads(original)
        roundtrip = json.dumps(snapshot, indent=2)

        # Parse both and compare dict structures (not exact strings due to formatting)
        assert json.loads(original) == json.loads(roundtrip)

    def test_snapshot_ai_includes_common_imports(self) -> None:
        """AI component should import from common subpackages."""
        snapshot_path = (
            Path(__file__).resolve().parents[2]
            / "common"
            / "isolation"
            / "import_graph.snapshot.json"
        )
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))

        ai_imports = snapshot["imports"]["ai"]
        # Find imports from common modules
        common_imports = [
            imp for imp in ai_imports
            if imp["type"] == "from" and imp["module"].startswith("common.")
        ]

        # AI should have some cross-component imports
        assert len(common_imports) > 0, "AI should import from common"

    def test_snapshot_import_entries_valid_structure(self) -> None:
        """All import entries must have consistent structure."""
        snapshot_path = (
            Path(__file__).resolve().parents[2]
            / "common"
            / "isolation"
            / "import_graph.snapshot.json"
        )
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))

        for component, imports in snapshot["imports"].items():
            for imp in imports:
                # Every import must have these fields
                assert isinstance(imp["file"], str)
                assert isinstance(imp["line"], int)
                assert imp["line"] > 0
                assert imp["type"] in ["import", "from"]
                assert isinstance(imp["module"], str)

                # From imports must have a name
                if imp["type"] == "from":
                    assert "name" in imp
                    assert isinstance(imp["name"], str)
