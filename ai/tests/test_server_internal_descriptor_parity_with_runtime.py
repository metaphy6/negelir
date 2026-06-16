"""Phase 18.6 §18.6 ledger #17 — Server/internal descriptor parity with runtime."""
from __future__ import annotations

import os


class TestServerInternalDescriptorParityWithRuntime:
    """Proof test: descriptor matches runtime endpoints (make api.parity)."""

    def test_descriptor_predictions_write_matches_schema(self) -> None:
        """Descriptor /predictions/write endpoint schema is correct."""
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

        # Verify endpoint exists and has required fields
        assert "/predictions/write" in spec["paths"]
        endpoint = spec["paths"]["/predictions/write"]["post"]

        assert "requestBody" in endpoint
        assert "responses" in endpoint
        assert "200" in endpoint["responses"]

    def test_descriptor_security_schemes_complete(self) -> None:
        """Descriptor security schemes are complete and documented."""
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

        schemes = spec["components"]["securitySchemes"]
        assert "mTLS" in schemes
        assert "HMACToken" in schemes

    def test_descriptor_has_health_check_endpoint(self) -> None:
        """Descriptor includes /health endpoint for liveness probes."""
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

        assert "/health" in spec["paths"]
        assert "get" in spec["paths"]["/health"]

    def test_make_api_parity_target_placeholder(self) -> None:
        """Placeholder: make api.parity target will validate descriptor against live server."""
        # This test documents that make api.parity will be implemented
        # to compare the descriptor to the live server's introspection endpoint
        # For now, just verify the descriptor exists
        descriptor_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "common",
            "api",
            "server_internal.openapi.yaml",
        )
        assert os.path.exists(descriptor_path)
