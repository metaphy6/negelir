"""Phase 18.4 — Per-profile-tuple smoke matrix tests."""
from __future__ import annotations

from pathlib import Path


def test_per_profile_smoke_matrix() -> None:
    """Each required profile tuple has a smoke YAML file."""
    required_tuples = [
        "core_server",
        "core_mock_datasource",
        "core_server_swarm",
        "core_mock_datasource_patcher",
        "core_server_internal_swarm_observability",
        "all",
    ]
    repo_root = Path(__file__).parent.parent.parent
    profiles_dir = repo_root / "xops" / "smoke" / "profiles"

    for tuple_name in required_tuples:
        yaml_file = profiles_dir / f"{tuple_name}.yaml"
        assert yaml_file.exists(), f"Missing smoke profile: {yaml_file}"

        with open(yaml_file) as f:
            content = f.read()
        assert "profiles:" in content, f"{yaml_file} missing 'profiles:' field"
        assert "checks:" in content, f"{yaml_file} missing 'checks:' field"
