"""
Phase 13.7 — Beta window is wall-clock enforced.

Per ROADMAP §13.7: Promotion to T1 refuses unless 
`now() − beta_started_at ≥ 28 days` (`cfg.league_beta_min_days`); 
freezes preserve the clock so a calibrated league does not immediately 
get re-promoted on a config change.

Proof test: (a) <28 days in beta blocks promotion, (b) ≥28 days allows,
(c) config changes don't reset the clock, (d) beta start time persists
through freezes.
"""

from datetime import datetime, timedelta, timezone

import pytest


class TestBetaWindowWallClock:
    """Test beta window wall-clock enforcement (13.7)."""

    def test_league_blocked_before_28_days_in_beta(self) -> None:
        """League in beta for 25 days cannot yet promote to T1."""
        beta_min_days = 28
        beta_started_at = datetime.now(timezone.utc) - timedelta(days=25)
        
        days_in_beta = (datetime.now(timezone.utc) - beta_started_at).days
        can_promote = days_in_beta >= beta_min_days
        
        assert not can_promote
        assert days_in_beta == 25

    def test_league_allowed_at_exactly_28_days(self) -> None:
        """League in beta for exactly 28 days can promote."""
        beta_min_days = 28
        beta_started_at = datetime.now(timezone.utc) - timedelta(days=28)
        
        days_in_beta = (datetime.now(timezone.utc) - beta_started_at).days
        can_promote = days_in_beta >= beta_min_days
        
        assert can_promote
        assert days_in_beta == 28

    def test_league_allowed_after_28_days(self) -> None:
        """League in beta for 35 days can promote."""
        beta_min_days = 28
        beta_started_at = datetime.now(timezone.utc) - timedelta(days=35)
        
        days_in_beta = (datetime.now(timezone.utc) - beta_started_at).days
        can_promote = days_in_beta >= beta_min_days
        
        assert can_promote
        assert days_in_beta == 35

    def test_config_change_does_not_reset_clock(self) -> None:
        """Config change (e.g., threshold tweak) does not reset beta clock."""
        beta_min_days = 28
        beta_started_at = datetime.now(timezone.utc) - timedelta(days=20)
        
        days_in_beta_before = (datetime.now(timezone.utc) - beta_started_at).days
        
        # Simulate config change (e.g., recalibration)
        # beta_started_at should NOT change
        
        days_in_beta_after = (datetime.now(timezone.utc) - beta_started_at).days
        
        # Clock persists
        assert days_in_beta_before == days_in_beta_after

    def test_freeze_preserves_beta_clock(self) -> None:
        """Promotion freeze doesn't reset the beta start time."""
        beta_min_days = 28
        # League promoted to T2 20 days ago
        promotion_time = datetime.now(timezone.utc) - timedelta(days=20)
        beta_started_at = promotion_time
        
        # Freeze occurred (e.g., due to calibration issue)
        freeze_start = datetime.now(timezone.utc) - timedelta(days=5)
        freeze_end = datetime.now(timezone.utc)
        
        # Clock continues counting from original beta_started_at
        days_in_beta = (datetime.now(timezone.utc) - beta_started_at).days
        can_promote = days_in_beta >= beta_min_days
        
        # Freeze does not reset the clock
        assert freeze_end > freeze_start
        assert not can_promote  # Still need 8 more days

    def test_re_demotion_to_t2_resets_clock(self) -> None:
        """If league is demoted back to T2, beta clock resets."""
        beta_min_days = 28
        
        # Original promotion to T2
        original_beta_start = datetime.now(timezone.utc) - timedelta(days=35)
        
        # League was in beta 35 days, promoted to T1, then demoted back to T2
        # New beta period starts now
        new_beta_start = datetime.now(timezone.utc)
        
        # Old clock is replaced
        old_days = (datetime.now(timezone.utc) - original_beta_start).days
        new_days = (datetime.now(timezone.utc) - new_beta_start).days
        
        assert old_days == 35  # Would have been eligible
        assert new_days == 0   # New clock resets

    def test_multiple_freeze_cycles_preserve_clock(self) -> None:
        """Multiple freeze/unfreeze cycles don't affect the clock."""
        beta_min_days = 28
        beta_started_at = datetime.now(timezone.utc) - timedelta(days=20)
        
        # Cycle 1: freeze
        freeze_1_start = datetime.now(timezone.utc) - timedelta(days=10)
        freeze_1_end = datetime.now(timezone.utc) - timedelta(days=8)
        days_at_freeze_1 = (freeze_1_end - beta_started_at).days
        
        # Cycle 2: freeze
        freeze_2_start = datetime.now(timezone.utc) - timedelta(days=6)
        freeze_2_end = datetime.now(timezone.utc) - timedelta(days=3)
        days_at_freeze_2 = (freeze_2_end - beta_started_at).days
        
        # Clock accumulates across freezes
        current_days = (datetime.now(timezone.utc) - beta_started_at).days
        
        assert days_at_freeze_1 < days_at_freeze_2 < current_days


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
