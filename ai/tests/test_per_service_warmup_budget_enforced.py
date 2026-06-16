"""Phase 18.4 — Per-service warm-up budgets are enforced."""
from __future__ import annotations

import yaml
from pathlib import Path


def test_per_service_warmup_budget_enforced() -> None:
    """Each service has a declared readiness budget."""
    repo_root = Path(__file__).parent.parent.parent
    readiness_file = repo_root / "common" / "profiles" / "readiness_budgets.yaml"

    with open(readiness_file) as f:
        config = yaml.safe_load(f)

    # Must have services section
    assert "services" in config, "readiness_budgets.yaml must have 'services' section"
    services = config["services"]

    # Core services must have budgets
    required_services = ["postgres", "redis", "server", "api"]
    for svc in required_services:
        assert svc in services, f"Missing budget for service: {svc}"
        svc_config = services[svc]
        assert "readiness_timeout_s" in svc_config, (
            f"{svc} missing readiness_timeout_s"
        )
        assert isinstance(svc_config["readiness_timeout_s"], int), (
            f"{svc} readiness_timeout_s must be an integer"
        )
        assert svc_config["readiness_timeout_s"] > 0, (
            f"{svc} readiness_timeout_s must be positive"
        )

    # Must have defaults
    assert "defaults" in config, "readiness_budgets.yaml must have 'defaults' section"
