"""Phase 22.8 § Verify docker compose PROFILES work without docker-compose.mock.yml overlay."""

import subprocess
from pathlib import Path
import yaml


def test_docker_compose_yml_has_core_and_mock_profiles():
    """Verify docker-compose.yml defines 'core' and 'mock' profiles."""
    compose_file = Path(__file__).parent.parent.parent / "docker-compose.yml"
    assert compose_file.exists(), "docker-compose.yml not found"
    
    with open(compose_file) as f:
        compose = yaml.safe_load(f)
    
    services = compose.get("services", {})
    
    # Verify at least one service has 'core' profile
    has_core = False
    has_mock = False
    
    for service_name, service_config in services.items():
        profiles = service_config.get("profiles", [])
        if "core" in profiles:
            has_core = True
        if "mock" in profiles:
            has_mock = True
    
    assert has_core, "No service with 'core' profile found"
    assert has_mock, "No service with 'mock' profile found"


def test_docker_compose_no_mock_overlay_file():
    """Verify docker-compose.mock.yml does not exist."""
    repo_root = Path(__file__).parent.parent.parent
    mock_overlay = repo_root / "docker-compose.mock.yml"
    assert not mock_overlay.exists(), "docker-compose.mock.yml overlay should be deleted"


def test_mock_overlay_file_removed():
    """Verify the separate mock overlay file has been removed from repo."""
    repo_root = Path(__file__).parent.parent.parent
    overlay_path = repo_root / "docker-compose.mock.yml"
    
    # This file should not exist anymore; it was absorbed into docker-compose.yml
    assert not overlay_path.exists(), (
        "docker-compose.mock.yml should be removed; mock services now use 'mock' profile in docker-compose.yml"
    )


def test_server_has_mock_profile():
    """Verify server service includes 'mock' profile."""
    compose_file = Path(__file__).parent.parent.parent / "docker-compose.yml"
    
    with open(compose_file) as f:
        compose = yaml.safe_load(f)
    
    server_service = compose.get("services", {}).get("server")
    assert server_service is not None, "server service not found"
    
    profiles = server_service.get("profiles", [])
    assert "mock" in profiles, "'mock' profile not in server service"
    assert "core" in profiles, "'core' profile not in server service"


def test_redis_has_core_profile():
    """Verify redis service has 'core' profile for basic stack."""
    compose_file = Path(__file__).parent.parent.parent / "docker-compose.yml"
    
    with open(compose_file) as f:
        compose = yaml.safe_load(f)
    
    redis_service = compose.get("services", {}).get("redis")
    assert redis_service is not None, "redis service not found"
    
    profiles = redis_service.get("profiles", [])
    assert "core" in profiles, "'core' profile not in redis service"


if __name__ == "__main__":
    test_docker_compose_yml_has_core_and_mock_profiles()
    print("✅ test_docker_compose_yml_has_core_and_mock_profiles passed")
    
    test_docker_compose_no_mock_overlay_file()
    print("✅ test_docker_compose_no_mock_overlay_file passed")
    
    test_mock_overlay_file_removed()
    print("✅ test_mock_overlay_file_removed passed")
    
    test_server_has_mock_profile()
    print("✅ test_server_has_mock_profile passed")
    
    test_redis_has_core_profile()
    print("✅ test_redis_has_core_profile passed")
    
    print("\n✅ All PROFILES tests passed!")
