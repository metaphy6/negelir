"""Phase 18.6 §18.6 ledger #17 — Server/internal descriptor is versioned."""
from __future__ import annotations

import os


class TestServerInternalContractDescriptorVersioned:
    """Proof test: descriptor carries semantic version."""

    def test_descriptor_openapi_version_matches_semver(self) -> None:
        """OpenAPI descriptor version is semantic (major.minor.patch)."""
        import yaml

        descriptor_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "common",
            "api",
            "server_internal.openapi.yaml",
        )
        with open(descriptor_path, "r") as fh:
            spec = yaml.safe_load(fh)

        version_str = spec["info"]["version"]
        parts = version_str.split(".")
        assert (
            len(parts) == 3
        ), f"Version {version_str} must be X.Y.Z (semantic)"
        for part in parts:
            assert part.isdigit(), f"Version part {part} must be numeric"

    def test_descriptor_carries_phase_ledger_metadata(self) -> None:
        """Descriptor has Phase 18.6 ledger reference for change tracking."""
        import yaml

        descriptor_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "common",
            "api",
            "server_internal.openapi.yaml",
        )
        with open(descriptor_path, "r") as fh:
            spec = yaml.safe_load(fh)

        assert "x-phase-18-6-ledger" in spec["info"]
        assert spec["info"]["x-phase-18-6-ledger"] == 17

    def test_descriptor_root_has_phase_18_6_metadata(self) -> None:
        """Descriptor root has x-phase-18-6 object with dual CODEOWNER flag."""
        import yaml

        descriptor_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "common",
            "api",
            "server_internal.openapi.yaml",
        )
        with open(descriptor_path, "r") as fh:
            spec = yaml.safe_load(fh)

        assert "x-phase-18-6" in spec
        assert "dual_codeowner_required" in spec["x-phase-18-6"]
        assert spec["x-phase-18-6"]["dual_codeowner_required"] is True
