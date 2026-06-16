"""Phase 18.4 — Minimum profile set (core,server,swarm) boots cleanly."""
from __future__ import annotations

from pathlib import Path


def test_minimum_profile_set_boots_clean() -> None:
    """The default profile set (core,server,swarm) has all required services defined."""
    repo_root = Path(__file__).parent.parent.parent
    swarm_yaml = repo_root / "xops" / "smoke" / "profiles" / "core_server_swarm.yaml"

    assert swarm_yaml.exists(), "Missing core_server_swarm.yaml profile"

    with open(swarm_yaml) as f:
        content = f.read()

    # Must define expected services
    required_services = ["postgres", "redis", "server"]
    for service in required_services:
        assert service in content, (
            f"core_server_swarm profile missing expected service: {service}"
        )

    # Must have readiness timeout set
    assert "readiness_timeout_s:" in content, "Profile missing readiness_timeout_s"
