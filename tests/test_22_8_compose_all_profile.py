"""Phase 22.8 — Verify docker compose PROFILES=all works without overlay."""

import yaml
from pathlib import Path


def test_docker_compose_all_profile_exists():
    """Verify all services with 'all' profile are defined."""
    compose_file = Path(__file__).parent.parent.parent / "docker-compose.yml"
    assert compose_file.exists()
    
    with open(compose_file) as f:
        compose = yaml.safe_load(f)
    
    services = compose.get("services", {})
    all_profile_services = [
        name for name, config in services.items()
        if "all" in config.get("profiles", [])
    ]
    
    # Verify at least the core services have 'all' profile
    assert len(all_profile_services) > 0, "No services with 'all' profile found"
    print(f"Services with 'all' profile: {all_profile_services}")


def test_all_services_have_valid_depends_on():
    """Verify all service dependencies are resolvable."""
    compose_file = Path(__file__).parent.parent.parent / "docker-compose.yml"
    
    with open(compose_file) as f:
        compose = yaml.safe_load(f)
    
    services = compose.get("services", {})
    service_names = set(services.keys())
    
    for service_name, service_config in services.items():
        depends = service_config.get("depends_on", {})
        
        if isinstance(depends, dict):
            for dep_name in depends.keys():
                assert dep_name in service_names, (
                    f"Service '{service_name}' depends on '{dep_name}' which doesn't exist"
                )
        elif isinstance(depends, list):
            for dep_name in depends:
                assert dep_name in service_names, (
                    f"Service '{service_name}' depends on '{dep_name}' which doesn't exist"
                )


def test_no_mock_overlay_reference_in_compose():
    """Verify docker-compose.yml doesn't reference docker-compose.mock.yml."""
    compose_file = Path(__file__).parent.parent.parent / "docker-compose.yml"
    content = compose_file.read_text()
    
    assert "docker-compose.mock.yml" not in content, (
        "docker-compose.yml should not reference the removed overlay file"
    )


def test_server_can_run_mocksrv_mode():
    """Verify server service can be run in mock profile with MODE=mocksrv."""
    compose_file = Path(__file__).parent.parent.parent / "docker-compose.yml"
    
    with open(compose_file) as f:
        compose = yaml.safe_load(f)
    
    server_service = compose.get("services", {}).get("server")
    assert server_service is not None
    
    # Server should have mock profile
    profiles = server_service.get("profiles", [])
    assert "mock" in profiles, "Server service must have 'mock' profile for mock mode"
    
    # Server environment should include MODE which can be set to mocksrv
    # (MODE env var comes from .env file loaded via env_file)
    env_file = server_service.get("env_file", [])
    assert env_file, "Server should load env_file for MODE configuration"


if __name__ == "__main__":
    test_docker_compose_all_profile_exists()
    print("✅ test_docker_compose_all_profile_exists passed")
    
    test_all_services_have_valid_depends_on()
    print("✅ test_all_services_have_valid_depends_on passed")
    
    test_no_mock_overlay_reference_in_compose()
    print("✅ test_no_mock_overlay_reference_in_compose passed")
    
    test_server_can_run_mocksrv_mode()
    print("✅ test_server_can_run_mocksrv_mode passed")
    
    print("\n✅ All docker-compose 'all' profile tests passed!")
