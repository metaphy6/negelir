"""Phase 22.9 §22.9.7 — Proof test: dual-emission window is active."""
from common.telemetry import TelemetrySink

def test_dual_emission_active_within_window():
    """Verify that metric aliases are active and tracked within the window."""
    sink = TelemetrySink()
    
    # Register an alias
    sink.register_alias("nlp_pipeline_latency_seconds", "common_pipeline_latency_seconds")
    
    # Check it's active
    assert sink.is_alias_active("nlp_pipeline_latency_seconds")
    
    # Get active aliases
    active = sink.get_active_aliases()
    assert "nlp_pipeline_latency_seconds" in active
    assert active["nlp_pipeline_latency_seconds"] == "common_pipeline_latency_seconds"


if __name__ == "__main__":
    test_dual_emission_active_within_window()
