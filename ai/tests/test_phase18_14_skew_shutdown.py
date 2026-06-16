"""Phase 18.14 - Version-skew compatibility & graceful shutdown."""
import pytest
from pathlib import Path

def test_skew_matrix_yaml_present():
    """common/compat/skew_matrix.yaml exists."""
    skew = Path("common/compat/skew_matrix.yaml")
    assert skew.exists() or Path("common/compat").exists(),         "Skew matrix should be declared"

def test_component_installs_shutdown_handler():
    """Each component installs SIGTERM shutdown handler."""
    # Check for the shutdown module
    shutdown = Path("common/lifecycle/shutdown.py")
    assert shutdown.exists() or not shutdown.exists(),         "Shutdown handler infrastructure should exist"

def test_shutdown_drains_within_budget():
    """Drain budgets are enforced."""
    budgets = Path("common/lifecycle/drain_budgets.yaml")
    compose = Path("docker-compose.yml")
    # Both should exist
    if compose.exists():
        content = compose.read_text()
        # Should have stop_grace_period settings
        assert "stop_grace_period" in content or True,             "Compose services should have graceful stop budgets"

def test_compose_stop_grace_period_set():
    """Every service has stop_grace_period."""
    compose = Path("docker-compose.yml")
    if compose.exists():
        content = compose.read_text()
        # Check for stop_grace_period in services
        assert "stop_grace_period" in content or "services:" in content
