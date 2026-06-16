"""Phase 18.1 §18.1 — Snapshot file existence and schema tests.

Tests verify:
- The snapshot file exists and is valid JSON
- The snapshot includes all expected components
- The snapshot contains expected fields
"""

import json
from pathlib import Path


class TestIsolationSnapshotFile:
    """Verify snapshot file exists and is valid."""

    def test_snapshot_file_exists(self) -> None:
        """Snapshot must be checked in at common/isolation/import_graph.snapshot.json."""
        snapshot_path = (
            Path(__file__).resolve().parents[2]
            / "common"
            / "isolation"
            / "import_graph.snapshot.json"
        )
        assert snapshot_path.exists(), f"Snapshot not found at {snapshot_path}"

    def test_snapshot_is_valid_json(self) -> None:
        """Snapshot file must be parseable as JSON."""
        snapshot_path = (
            Path(__file__).resolve().parents[2]
            / "common"
            / "isolation"
            / "import_graph.snapshot.json"
        )
        content = snapshot_path.read_text(encoding="utf-8")
        # Will raise JSONDecodeError if invalid
        snapshot = json.loads(content)
        assert isinstance(snapshot, dict)

    def test_snapshot_has_required_fields(self) -> None:
        """Snapshot must have version, generated_at, components, imports, violations."""
        snapshot_path = (
            Path(__file__).resolve().parents[2]
            / "common"
            / "isolation"
            / "import_graph.snapshot.json"
        )
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))

        required_fields = ["version", "generated_at", "components", "imports", "violations"]
        for field in required_fields:
            assert field in snapshot, f"Snapshot missing required field: {field}"

    def test_snapshot_version_is_18_1(self) -> None:
        """Snapshot version must be 18.1."""
        snapshot_path = (
            Path(__file__).resolve().parents[2]
            / "common"
            / "isolation"
            / "import_graph.snapshot.json"
        )
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        assert snapshot["version"] == "18.1"

    def test_snapshot_components_non_empty(self) -> None:
        """Snapshot must include at least one component."""
        snapshot_path = (
            Path(__file__).resolve().parents[2]
            / "common"
            / "isolation"
            / "import_graph.snapshot.json"
        )
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        assert len(snapshot["components"]) > 0

    def test_snapshot_imports_per_component(self) -> None:
        """Each component in the snapshot must have an imports list."""
        snapshot_path = (
            Path(__file__).resolve().parents[2]
            / "common"
            / "isolation"
            / "import_graph.snapshot.json"
        )
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))

        for component in snapshot["components"]:
            assert component in snapshot["imports"]
            assert isinstance(snapshot["imports"][component], list)

    def test_snapshot_imports_have_required_fields(self) -> None:
        """Each import entry must have file, line, type, and module/name."""
        snapshot_path = (
            Path(__file__).resolve().parents[2]
            / "common"
            / "isolation"
            / "import_graph.snapshot.json"
        )
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))

        for component, imports in snapshot["imports"].items():
            for import_entry in imports[:5]:  # Check first 5 of each component
                assert "file" in import_entry
                assert "line" in import_entry
                assert "type" in import_entry
                assert import_entry["type"] in ["import", "from"]
                assert "module" in import_entry

    def test_snapshot_generated_at_is_iso_format(self) -> None:
        """Generated timestamp must be ISO 8601 format with Z suffix."""
        snapshot_path = (
            Path(__file__).resolve().parents[2]
            / "common"
            / "isolation"
            / "import_graph.snapshot.json"
        )
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))

        generated_at = snapshot["generated_at"]
        # Check that it ends with Z and contains T (ISO format)
        assert generated_at.endswith("Z"), "generated_at must end with Z (UTC)"
        assert "T" in generated_at, "generated_at must be ISO 8601"
