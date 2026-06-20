"""Test profile drift guard — schema versioning and shadow windows.

Per Phase 13.2 and Phase 11 §11.26: each profile edit bumps schema_version
and enters shadow window. Lint detects silent edits.
"""

from datetime import datetime, timedelta
import pytest
from ai.common.profile_drift_guard import (
    ProfilePromotionStatus,
    is_in_shadow_window,
    can_promote_from_shadow_to_live,
    detect_silent_edit,
    compute_shadow_duration,
)


class TestProfileDriftGuard:
    """Profile drift guard tests."""

    def test_shadow_duration(self) -> None:
        """Shadow window is 14 days."""
        duration = compute_shadow_duration()
        assert duration == timedelta(days=14)

    def test_in_shadow_window_just_published(self) -> None:
        """Profile is in shadow window immediately after publication."""
        now = datetime.utcnow().isoformat() + "Z"
        assert is_in_shadow_window(now, now)

    def test_in_shadow_window_7_days_later(self) -> None:
        """Profile still in shadow window after 7 days."""
        published = datetime.utcnow() - timedelta(days=7)
        now = datetime.utcnow()
        assert is_in_shadow_window(
            published.isoformat() + "Z",
            now.isoformat() + "Z",
        )

    def test_shadow_window_expired_15_days_later(self) -> None:
        """Profile exits shadow window after 14 days."""
        published = datetime.utcnow() - timedelta(days=15)
        now = datetime.utcnow()
        assert not is_in_shadow_window(
            published.isoformat() + "Z",
            now.isoformat() + "Z",
        )

    def test_can_promote_shadow_to_live_too_early(self) -> None:
        """Cannot promote from shadow to live before 14 days."""
        published = datetime.utcnow() - timedelta(days=5)
        now = datetime.utcnow()
        ok, reason = can_promote_from_shadow_to_live(
            profile_id="knockout_continental_club",
            current_status=ProfilePromotionStatus.SHADOW,
            schema_version=1,
            published_utc=published.isoformat() + "Z",
            current_utc=now.isoformat() + "Z",
        )
        assert not ok
        assert "shadow window" in reason.lower()

    def test_can_promote_shadow_to_live_after_window(self) -> None:
        """Can promote after 14 days have passed."""
        published = datetime.utcnow() - timedelta(days=15)
        now = datetime.utcnow()
        ok, reason = can_promote_from_shadow_to_live(
            profile_id="knockout_continental_club",
            current_status=ProfilePromotionStatus.SHADOW,
            schema_version=1,
            published_utc=published.isoformat() + "Z",
            current_utc=now.isoformat() + "Z",
        )
        assert ok and reason == "OK"

    def test_cannot_promote_if_not_shadow(self) -> None:
        """Cannot promote from non-shadow status."""
        now = datetime.utcnow()
        ok, reason = can_promote_from_shadow_to_live(
            profile_id="knockout_continental_club",
            current_status=ProfilePromotionStatus.LIVE,
            schema_version=1,
            published_utc=now.isoformat() + "Z",
            current_utc=now.isoformat() + "Z",
        )
        assert not ok
        assert "not in SHADOW status" in reason

    def test_detect_silent_edit_no_change(self) -> None:
        """No drift if checksums match."""
        ok, reason = detect_silent_edit(
            original_checksum="abc123",
            current_checksum="abc123",
            schema_version_unchanged=True,
        )
        assert not ok
        assert "no drift" in reason.lower()

    def test_detect_silent_edit_content_changed_version_same(self) -> None:
        """Drift detected: content changed but version not bumped."""
        ok, reason = detect_silent_edit(
            original_checksum="abc123",
            current_checksum="def456",
            schema_version_unchanged=True,
        )
        assert ok  # drift detected
        assert "drift detected" in reason.lower()
        assert "schema_version not bumped" in reason

    def test_detect_silent_edit_version_bumped(self) -> None:
        """No drift if version was bumped along with content change."""
        ok, reason = detect_silent_edit(
            original_checksum="abc123",
            current_checksum="def456",
            schema_version_unchanged=False,
        )
        assert not ok
        assert "ok" in reason.lower()

    def test_promotion_status_values(self) -> None:
        """Verify promotion status enum."""
        statuses = {s.value for s in ProfilePromotionStatus}
        assert statuses == {"live", "shadow", "deprecated", "rollback"}
