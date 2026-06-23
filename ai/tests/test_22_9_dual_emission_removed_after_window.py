"""Phase 22.9 §22.9.7 — Proof test: dual-emission window expires correctly."""
import time
from common.telemetry import TelemetrySink

def test_dual_emission_window_expiration():
    """Verify that metric aliases expire after the configured window."""
    # Use a very short window for testing (0.1 seconds)
    sink = TelemetrySink()
    sink._metric_rename_alias_window_s = 0.1
    
    # Register an alias
    sink.register_alias("nlp_input_repair_total", "common_input_repair_total")
    assert sink.is_alias_active("nlp_input_repair_total")
    
    # Wait for window to expire
    time.sleep(0.2)
    
    # Should no longer be active
    assert not sink.is_alias_active("nlp_input_repair_total")


if __name__ == "__main__":
    test_dual_emission_window_expiration()
