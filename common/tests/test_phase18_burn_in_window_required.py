"""
Phase 18.9 §18.9 — 30-day burn-in window required after all gates green (ledger #29).

After all Phase 18 gates flip green, the phase enters a 30-day burn-in window.
Phase tracker row flips to completed only at burn-in end. This test validates the
burn-in window configuration.
"""


from common.config import cfg


def test_phase18_burn_in_window_required() -> None:
    """Test that burn-in window is configured (30 days)."""
    assert hasattr(cfg, "burn_in_window_days"), "cfg.burn_in_window_days not found"
    assert cfg.burn_in_window_days == 30, f"Expected burn_in_window_days=30, got {cfg.burn_in_window_days}"
    assert isinstance(cfg.burn_in_window_days, int), "burn_in_window_days should be int"
    
    # Also verify isolation_relax_max_hours exists
    assert hasattr(cfg, "isolation_relax_max_hours"), "cfg.isolation_relax_max_hours not found"
    assert cfg.isolation_relax_max_hours == 72, f"Expected isolation_relax_max_hours=72, got {cfg.isolation_relax_max_hours}"
