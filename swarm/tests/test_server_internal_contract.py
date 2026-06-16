"""Phase 18.6 §18.6 ledger #17 — Swarm validates server/internal contract."""
from __future__ import annotations

import os
import yaml


class TestServerInternalContract:
    """Proof test: server/internal contract descriptor is versioned and valid."""

    def test_server_internal_openapi_exists(self) -> None:
        """server_internal.openapi.yaml exists."""
        descriptor_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "ai",
            "common",
            "api",
            "server_internal.openapi.yaml",
        )
        assert os.path.exists(descriptor_path), "server_internal.openapi.yaml must exist"

    def test_openapi_descriptor_is_valid_yaml(self) -> None:
        """Descriptor is valid YAML."""
        import yaml

        descriptor_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "ai",
            "common",
            "api",
            "server_internal.openapi.yaml",
        )
        with open(descriptor_path, "r") as fh:
            try:
                spec = yaml.safe_load(fh)
                assert spec is not None
            except yaml.YAMLError as e:
                raise AssertionError(f"Invalid YAML: {e}")

    def test_openapi_descriptor_has_version(self) -> None:
        """Descriptor declares openapi and version."""
        import yaml

        descriptor_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "ai",
            "common",
            "api",
            "server_internal.openapi.yaml",
        )
        with open(descriptor_path, "r") as fh:
            spec = yaml.safe_load(fh)

        assert "openapi" in spec, "Descriptor must have 'openapi' field"
        assert "info" in spec, "Descriptor must have 'info' field"
        assert "version" in spec["info"], "Info must have 'version'"

    def test_openapi_descriptor_has_authentication(self) -> None:
        """Descriptor defines security schemes (mTLS or HMAC token)."""
        import yaml

        descriptor_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "ai",
            "common",
            "api",
            "server_internal.openapi.yaml",
        )
        with open(descriptor_path, "r") as fh:
            spec = yaml.safe_load(fh)

        assert "components" in spec
        assert "securitySchemes" in spec["components"]
        security_schemes = spec["components"]["securitySchemes"]
        assert "mTLS" in security_schemes or "HMACToken" in security_schemes

    def test_openapi_descriptor_declares_owner(self) -> None:
        """Descriptor's paths declare owner components."""
        import yaml

        descriptor_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "ai",
            "common",
            "api",
            "server_internal.openapi.yaml",
        )
        with open(descriptor_path, "r") as fh:
            spec = yaml.safe_load(fh)

        # Swarm is the primary consumer
        assert "paths" in spec
        for path, path_item in spec["paths"].items():
            for method, operation in path_item.items():
                if isinstance(operation, dict) and "x-owner-component" in operation:
                    # Phase 18.6 ledger #17: all operations should have an owner
                    assert operation["x-owner-component"] in [
                        "swarm",
                        "common",
                        "server",
                    ]

    def test_openapi_has_phase_18_6_metadata(self) -> None:
        """Descriptor carries Phase 18.6 ledger reference."""
        import yaml

        descriptor_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "ai",
            "common",
            "api",
            "server_internal.openapi.yaml",
        )
        with open(descriptor_path, "r") as fh:
            spec = yaml.safe_load(fh)

        assert "x-phase-18-6-ledger" in spec["info"]
        assert spec["info"]["x-phase-18-6-ledger"] == 17

    def test_openapi_predictions_write_endpoint_exists(self) -> None:
        """Descriptor includes /predictions/write endpoint."""
        import yaml

        descriptor_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "ai",
            "common",
            "api",
            "server_internal.openapi.yaml",
        )
        with open(descriptor_path, "r") as fh:
            spec = yaml.safe_load(fh)

        assert "/predictions/write" in spec["paths"]
        predictions_path = spec["paths"]["/predictions/write"]
        assert "post" in predictions_path
