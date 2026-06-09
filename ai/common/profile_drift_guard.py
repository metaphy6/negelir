"""Profile drift guard — schema versioning and shadow windows for calibration profiles.

Per Phase 13.2 and Phase 11 §11.26: editing a published calibration YAML bumps
the profile's schema_version and forces a 14-day shadow window before promotion
to live. This module enforces the guard: lint refuses in-place silent edits.
"""

from datetime import datetime, timedelta
from enum import Enum


class ProfilePromotionStatus(Enum):
    """Promotion status for a calibration profile version."""
    LIVE = "live"                  # In active use
    SHADOW = "shadow"              # Testing before promotion; used in shadow mode only
    DEPRECATED = "deprecated"      # No longer used
    ROLLBACK = "rollback"          # Previously live, now replaced


def compute_shadow_duration() -> timedelta:
    """Shadow window duration per Phase 11 §11.26."""
    return timedelta(days=14)


def is_in_shadow_window(
    schema_version_published_utc: str,  # ISO-8601 UTC timestamp
    current_utc: str,  # ISO-8601 UTC timestamp
) -> bool:
    """Check if a profile version is still in shadow window.
    
    Args:
        schema_version_published_utc: When this version was first published (shadow start).
        current_utc: Current timestamp.
    
    Returns:
        True if still in shadow window (< 14 days old); False otherwise.
    """
    published = datetime.fromisoformat(schema_version_published_utc.replace("Z", "+00:00"))
    now = datetime.fromisoformat(current_utc.replace("Z", "+00:00"))
    elapsed = now - published
    return elapsed < compute_shadow_duration()


def can_promote_from_shadow_to_live(
    profile_id: str,
    current_status: ProfilePromotionStatus,
    schema_version: int,
    published_utc: str,
    current_utc: str,
) -> tuple[bool, str]:
    """Check if a profile can be promoted from shadow to live.
    
    Args:
        profile_id: Profile identifier.
        current_status: Current promotion status.
        schema_version: Version number of the profile.
        published_utc: When this version was first published (shadow start).
        current_utc: Current time.
    
    Returns:
        (allowed: bool, reason: str)
    """
    if current_status != ProfilePromotionStatus.SHADOW:
        return (False, f"Profile {profile_id} is not in SHADOW status; current: {current_status.value}")
    
    if is_in_shadow_window(published_utc, current_utc):
        days_left = (compute_shadow_duration() -
                     (datetime.fromisoformat(current_utc.replace("Z", "+00:00")) -
                      datetime.fromisoformat(published_utc.replace("Z", "+00:00")))).days
        return (
            False,
            f"Profile {profile_id} v{schema_version} still in shadow window "
            f"({days_left} days remaining)",
        )
    
    return (True, "OK")


def detect_silent_edit(
    original_checksum: str,
    current_checksum: str,
    schema_version_unchanged: bool,
) -> tuple[bool, str]:
    """Detect if a profile YAML was edited without a schema version bump.
    
    Per doctrine: lint refuses in-place silent edits. Every non-documentation
    change must bump schema_version.
    
    Args:
        original_checksum: SHA256 checksum of the original published profile.
        current_checksum: SHA256 checksum of the current profile.
        schema_version_unchanged: True if schema_version field unchanged.
    
    Returns:
        (drift_detected: bool, reason: str)
    """
    if original_checksum == current_checksum:
        # No change
        return (False, "No drift (checksums match)")
    
    if schema_version_unchanged and original_checksum != current_checksum:
        return (
            True,
            "DRIFT DETECTED: Profile content changed but schema_version not bumped. "
            "Every meaningful edit must bump schema_version.",
        )
    
    if original_checksum != current_checksum and not schema_version_unchanged:
        # Changed AND version bumped; OK
        return (False, "OK: profile changed and version bumped")
    
    return (False, "OK")
