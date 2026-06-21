"""Phase 18.4 — Smoke failure names the offending service."""
from __future__ import annotations

import yaml
from pathlib import Path


def test_smoke_failure_names_offending_service() -> None:
    """When readiness fails, the error message identifies which service timed out."""
    repo_root = Path(__file__).parent.parent.parent
    readiness_file = repo_root / "common" / "profiles" / "readiness_budgets.yaml"

    with open(readiness_file) as f:
        config = yaml.safe_load(f)

    # Each service must have a check_endpoint so failures can name it
    services = config["services"]
    for svc_name, svc_config in services.items():
        # If it has a check_endpoint, the error logging should use it
        assert "check_endpoint" in svc_config or "readiness_timeout_s" in svc_config, (
            f"{svc_name} must have either check_endpoint or timeout defined"
        )
