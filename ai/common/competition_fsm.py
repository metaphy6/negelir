"""Competition lifecycle FSM — deterministic status transitions.

Per COMPETITIONS.md and Phase 13.2: Competition.status has deterministic
transitions that are append-only-audited. A competition refuses to transition
if predictor inflight requests reference it (drains first per §13.26).
"""

from dataclasses import dataclass
from enum import Enum
from typing import Set


class CompetitionStatus(Enum):
    """Competition lifecycle status."""
    PLANNED = "planned"         # Scheduled but not yet active
    ACTIVE = "active"           # Currently running
    SUSPENDED = "suspended"     # Paused (e.g., bad weather, medical timeout)
    COMPLETED = "completed"     # Finished, final results recorded
    CANCELLED = "cancelled"     # Removed from schedule


# Legal transitions per status
LEGAL_TRANSITIONS: dict[CompetitionStatus, Set[CompetitionStatus]] = {
    CompetitionStatus.PLANNED: {
        CompetitionStatus.ACTIVE,      # Start
        CompetitionStatus.CANCELLED,   # Cancel before start
    },
    CompetitionStatus.ACTIVE: {
        CompetitionStatus.SUSPENDED,   # Pause
        CompetitionStatus.COMPLETED,   # Finish
        CompetitionStatus.CANCELLED,   # Rare: cancel mid-tournament
    },
    CompetitionStatus.SUSPENDED: {
        CompetitionStatus.ACTIVE,      # Resume
        CompetitionStatus.CANCELLED,   # Cancel from suspension
        CompetitionStatus.COMPLETED,   # End from suspension (rare)
    },
    CompetitionStatus.COMPLETED: set(),  # No transitions from completed
    CompetitionStatus.CANCELLED: set(),  # No transitions from cancelled
}


@dataclass(frozen=True)
class CompetitionStatusTransition:
    """Record of a status transition (append-only audit log entry)."""
    competition_id: str
    from_status: CompetitionStatus
    to_status: CompetitionStatus
    reason: str  # "start", "suspend", "resume", "complete", "cancel", etc.
    timestamp_utc: str  # ISO-8601 UTC timestamp


def is_legal_transition(
    from_status: CompetitionStatus,
    to_status: CompetitionStatus,
) -> bool:
    """Check if a status transition is legal.
    
    Args:
        from_status: Current status.
        to_status: Desired status.
    
    Returns:
        True if the transition is allowed; False otherwise.
    """
    return to_status in LEGAL_TRANSITIONS.get(from_status, set())


def validate_transition(
    from_status: CompetitionStatus,
    to_status: CompetitionStatus,
    inflight_requests_count: int = 0,
) -> tuple[bool, str]:
    """Validate a status transition, checking legality and predicate conditions.
    
    Args:
        from_status: Current status.
        to_status: Desired status.
        inflight_requests_count: Number of predictor requests in flight
                                  (drains before transition if > 0).
    
    Returns:
        (allowed: bool, reason: str) — True if transition is allowed.
    """
    # Check legal transition
    if not is_legal_transition(from_status, to_status):
        return (
            False,
            f"Illegal transition: {from_status.value} → {to_status.value}",
        )
    
    # Check inflight request predicate
    if inflight_requests_count > 0:
        if to_status == CompetitionStatus.CANCELLED:
            return (
                False,
                f"Cannot cancel competition with {inflight_requests_count} "
                "inflight predictor requests (must drain first per §13.26)",
            )
    
    return (True, "OK")


# Convenience status-specific checks
def can_start(status: CompetitionStatus) -> bool:
    """True if competition can transition PLANNED → ACTIVE (start)."""
    return status == CompetitionStatus.PLANNED and is_legal_transition(
        status, CompetitionStatus.ACTIVE
    )


def can_suspend(status: CompetitionStatus) -> bool:
    """True if competition can transition ACTIVE → SUSPENDED."""
    return status == CompetitionStatus.ACTIVE and is_legal_transition(
        status, CompetitionStatus.SUSPENDED
    )


def can_resume(status: CompetitionStatus) -> bool:
    """True if competition can transition SUSPENDED → ACTIVE (resume)."""
    return status == CompetitionStatus.SUSPENDED and is_legal_transition(
        status, CompetitionStatus.ACTIVE
    )


def can_complete(status: CompetitionStatus) -> bool:
    """True if competition can transition to COMPLETED."""
    return is_legal_transition(status, CompetitionStatus.COMPLETED)


def can_cancel(status: CompetitionStatus) -> bool:
    """True if competition can transition to CANCELLED."""
    return is_legal_transition(status, CompetitionStatus.CANCELLED)
