"""Phase 18.4 — Swarm profile can run independently of datasource."""
from __future__ import annotations

from pathlib import Path


def test_swarm_profile_does_not_require_datasource() -> None:
    """The core,server,swarm profile tuple does not require the datasource profile."""
    repo_root = Path(__file__).parent.parent.parent
    swarm_yaml = repo_root / "xops" / "smoke" / "profiles" / "core_server_swarm.yaml"

    with open(swarm_yaml) as f:
        content = f.read()

    # Verify the profile tuple doesn't include 'datasource' or 'mock'
    assert '"datasource"' not in content and "'datasource'" not in content, (
        "core,server,swarm must not require datasource profile"
    )
    assert '"mock"' not in content and "'mock'" not in content, (
        "core,server,swarm must not require mock profile"
    )

    # Verify it includes the expected profiles
    assert "core" in content and "server" in content and "swarm" in content, (
        "core,server,swarm profile tuple must declare all three profiles"
    )
