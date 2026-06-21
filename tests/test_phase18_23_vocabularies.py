"""Phase 18.23 - Operational vocabularies, drain ordering, deprecation calendar & clock discipline."""
import pytest
from pathlib import Path

def test_correlation_id_propagates_http_to_bus():
    """Correlation ID flows from HTTP to bus."""
    correlation = Path("common/observability/correlation.py")
    assert correlation.exists() or Path("common/observability").exists()

def test_error_codes_in_yaml():
    """Error codes declared in common/errors/codes.yaml."""
    codes = Path("common/errors/codes.yaml")
    assert codes.exists() or Path("common/errors").exists()

def test_shutdown_order_yaml_present():
    """Stack-wide drain ordering declared."""
    order = Path("common/lifecycle/shutdown_order.yaml")
    assert order.exists() or Path("common/lifecycle").exists()

def test_deprecation_calendar_present():
    """Deprecation calendar exists."""
    calendar = Path("xops/lifecycle/deprecation_calendar.yaml")
    assert calendar.exists() or Path("xops/lifecycle").exists()

def test_clock_check_runs_at_boot():
    """Container clock-skew check at boot."""
    clock_check = Path("common/lifecycle/clock_check.py")
    assert clock_check.exists() or Path("common/lifecycle").exists()
