"""Phase 22.5 proof test — docker-compose files have no ai/ path references."""
from pathlib import Path


def test_22_5_docker_compose_no_ai_paths() -> None:
    """Verify docker-compose*.yml files have no ai/ references."""
    root = Path(__file__).parent.parent
    
    for compose_file in ["docker-compose.yml", "docker-compose.chaos.yml"]:
        path = root / compose_file
        if not path.exists():
            continue  # Skip if file doesn't exist
        
        content = path.read_text(encoding="utf-8")
        
        assert "PYTHONPATH=ai" not in content, \
            f"{compose_file}: must not have PYTHONPATH=ai"
        assert "/app/ai" not in content, \
            f"{compose_file}: must not have /app/ai volume mount"
        assert "python ai/" not in content, \
            f"{compose_file}: must not have python ai/ command"
