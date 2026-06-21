"""Phase 8.16.16 — cfg knobs for triangle test accessibility check.

All 16 §8.16.16 triangle-test cfg knobs must be declared in Config.
Follows the pattern of test_cfg_knobs_introduced_by_814_are_accessible.
"""
from common.config import Config


def test_cfg_knobs_introduced_by_8_16_16_are_accessible() -> None:
    """All 16 §8.16.16 triangle-test cfg knobs are declared in Config."""
    cfg = Config()
    # Pre-existing knobs (14) confirmed present
    assert hasattr(cfg, "maint_scaler_default_max_replicas")
    assert hasattr(cfg, "opsctl_spool_ack_max_wait_h")
    assert hasattr(cfg, "maint_backup_offsite_state_max_age_h")
    assert hasattr(cfg, "maint_backup_offsite_lifecycle_min_days")
    assert hasattr(cfg, "maint_backup_offsite_object_lock_required")
    assert hasattr(cfg, "maint_backup_offsite_preflight_interval_h")
    assert hasattr(cfg, "maint_dlq_replay_allow_overrides")
    assert hasattr(cfg, "sec_input_allowlist_hmac_key_path")
    assert hasattr(cfg, "sec_input_allowlist_hmac_key_max_age_days")
    assert hasattr(cfg, "sec_plane_lag_alert_ms")
    assert hasattr(cfg, "sec_plane_lag_alert_window_s")
    assert hasattr(cfg, "opsctl_ack_timeout_ms_live_demo")
    assert hasattr(cfg, "telemetry_debug_enabled")
    assert hasattr(cfg, "telemetry_debug_max_series")
    # New knobs (2) added in §8.16.16
    assert hasattr(cfg, "maint_scaler_vram_pessimistic_threshold_pct")
    assert hasattr(cfg, "maint_scaler_cpu_budget_pct")
    # Type and range checks for the two new float knobs
    assert isinstance(cfg.maint_scaler_vram_pessimistic_threshold_pct, float)
    assert isinstance(cfg.maint_scaler_cpu_budget_pct, float)
    assert 0.0 < cfg.maint_scaler_vram_pessimistic_threshold_pct <= 1.0
    assert 0.0 < cfg.maint_scaler_cpu_budget_pct <= 1.0
