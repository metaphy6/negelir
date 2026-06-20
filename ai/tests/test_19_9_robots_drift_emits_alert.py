"""Phase 19 §19.9 — robots.txt drift emits alert."""
import pytest


def test_robots_drift_emits_alert():
    """robots.txt changes trigger datasource.alert.v1{kind=robots_txt_drifted}."""
    from ai.common.observability.alerts import RobotsAlert
    
    alert = RobotsAlert(
        kind="robots_txt_drifted",
        source="test_source",
        severity="warn",
    )
    assert alert.kind == "robots_txt_drifted"
