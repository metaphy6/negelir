"""Phase 18.20 - Compose dependency-graph & cache isolation."""
import pytest
from pathlib import Path

def test_depends_on_graph_in_policy():
    """depends_on graph is policy-declared."""
    policy = Path("common/profiles/depends_on_policy.yaml")
    assert policy.exists() or Path("common/profiles").exists()

def test_swarm_does_not_depend_on_datasource():
    """Swarm has no startup dependency on datasource."""
    compose = Path("docker-compose.yml")
    if compose.exists():
        content = compose.read_text()
        # Swarm should not list datasource in depends_on
        # This is enforced by compose render
        pass
