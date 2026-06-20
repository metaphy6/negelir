"""Test competition lifecycle FSM (finite state machine).

Per COMPETITIONS.md and Phase 13.2 DoD: verify that the competition status
FSM correctly enforces legal transitions and audit requirements.
"""

import pytest
from ai.common.competition_fsm import (
    CompetitionStatus,
    is_legal_transition,
    validate_transition,
    can_start,
    can_suspend,
    can_resume,
    can_complete,
    can_cancel,
)


class TestCompetitionStatusFSM:
    """Competition status finite state machine tests."""

    def test_status_enum_values(self) -> None:
        """Verify status enum has all required values."""
        statuses = {s.value for s in CompetitionStatus}
        assert statuses == {"planned", "active", "suspended", "completed", "cancelled"}

    # Legal transitions from PLANNED
    def test_planned_to_active(self) -> None:
        """Planned competition can transition to active (start)."""
        assert is_legal_transition(CompetitionStatus.PLANNED, CompetitionStatus.ACTIVE)
        assert can_start(CompetitionStatus.PLANNED)

    def test_planned_to_cancelled(self) -> None:
        """Planned competition can be cancelled before start."""
        assert is_legal_transition(CompetitionStatus.PLANNED, CompetitionStatus.CANCELLED)
        assert can_cancel(CompetitionStatus.PLANNED)

    def test_planned_to_suspended_illegal(self) -> None:
        """Planned competition cannot transition to suspended (must be active first)."""
        assert not is_legal_transition(CompetitionStatus.PLANNED, CompetitionStatus.SUSPENDED)

    # Legal transitions from ACTIVE
    def test_active_to_suspended(self) -> None:
        """Active competition can suspend (e.g., weather delay)."""
        assert is_legal_transition(CompetitionStatus.ACTIVE, CompetitionStatus.SUSPENDED)
        assert can_suspend(CompetitionStatus.ACTIVE)

    def test_active_to_completed(self) -> None:
        """Active competition can be completed."""
        assert is_legal_transition(CompetitionStatus.ACTIVE, CompetitionStatus.COMPLETED)
        assert can_complete(CompetitionStatus.ACTIVE)

    def test_active_to_cancelled_rare(self) -> None:
        """Active competition can be cancelled (rare, e.g., natural disaster)."""
        assert is_legal_transition(CompetitionStatus.ACTIVE, CompetitionStatus.CANCELLED)

    def test_active_to_planned_illegal(self) -> None:
        """Active competition cannot go back to planned."""
        assert not is_legal_transition(CompetitionStatus.ACTIVE, CompetitionStatus.PLANNED)

    # Legal transitions from SUSPENDED
    def test_suspended_to_active(self) -> None:
        """Suspended competition can resume (transition back to active)."""
        assert is_legal_transition(CompetitionStatus.SUSPENDED, CompetitionStatus.ACTIVE)
        assert can_resume(CompetitionStatus.SUSPENDED)

    def test_suspended_to_cancelled(self) -> None:
        """Suspended competition can be cancelled."""
        assert is_legal_transition(CompetitionStatus.SUSPENDED, CompetitionStatus.CANCELLED)

    def test_suspended_to_completed_rare(self) -> None:
        """Suspended competition can be completed (rare, after cancellation)."""
        assert is_legal_transition(CompetitionStatus.SUSPENDED, CompetitionStatus.COMPLETED)

    def test_suspended_to_planned_illegal(self) -> None:
        """Suspended competition cannot go back to planned."""
        assert not is_legal_transition(CompetitionStatus.SUSPENDED, CompetitionStatus.PLANNED)

    # No transitions FROM final states
    def test_completed_terminal(self) -> None:
        """Completed competition has no outgoing transitions."""
        for status in CompetitionStatus:
            assert not is_legal_transition(CompetitionStatus.COMPLETED, status)

    def test_cancelled_terminal(self) -> None:
        """Cancelled competition has no outgoing transitions."""
        for status in CompetitionStatus:
            assert not is_legal_transition(CompetitionStatus.CANCELLED, status)

    # Validation with predicate checks
    def test_validate_legal_transition_no_inflight(self) -> None:
        """Legal transition with no inflight requests should pass."""
        ok, reason = validate_transition(
            CompetitionStatus.PLANNED,
            CompetitionStatus.ACTIVE,
            inflight_requests_count=0,
        )
        assert ok and reason == "OK"

    def test_validate_cancel_with_inflight_blocked(self) -> None:
        """Cannot cancel if predictor requests are inflight."""
        ok, reason = validate_transition(
            CompetitionStatus.ACTIVE,
            CompetitionStatus.CANCELLED,
            inflight_requests_count=5,
        )
        assert not ok
        assert "inflight" in reason.lower()
        assert "drain" in reason.lower()

    def test_validate_cancel_no_inflight_allowed(self) -> None:
        """Can cancel if no inflight requests."""
        ok, reason = validate_transition(
            CompetitionStatus.ACTIVE,
            CompetitionStatus.CANCELLED,
            inflight_requests_count=0,
        )
        assert ok

    def test_validate_illegal_transition(self) -> None:
        """Illegal transition should fail regardless of inflight state."""
        ok, reason = validate_transition(
            CompetitionStatus.ACTIVE,
            CompetitionStatus.PLANNED,
            inflight_requests_count=0,
        )
        assert not ok
        assert "illegal" in reason.lower()

    # State-specific predicates
    def test_can_start_only_from_planned(self) -> None:
        """Only PLANNED competitions can start."""
        for status in CompetitionStatus:
            if status == CompetitionStatus.PLANNED:
                assert can_start(status)
            else:
                assert not can_start(status)

    def test_can_suspend_only_from_active(self) -> None:
        """Only ACTIVE competitions can suspend."""
        assert can_suspend(CompetitionStatus.ACTIVE)
        for status in {CompetitionStatus.PLANNED, CompetitionStatus.SUSPENDED,
                       CompetitionStatus.COMPLETED, CompetitionStatus.CANCELLED}:
            assert not can_suspend(status)

    def test_can_resume_only_from_suspended(self) -> None:
        """Only SUSPENDED competitions can resume."""
        assert can_resume(CompetitionStatus.SUSPENDED)
        for status in {CompetitionStatus.PLANNED, CompetitionStatus.ACTIVE,
                       CompetitionStatus.COMPLETED, CompetitionStatus.CANCELLED}:
            assert not can_resume(status)

    def test_realistic_workflow_planned_active_completed(self) -> None:
        """Test typical workflow: planned → active → completed."""
        status = CompetitionStatus.PLANNED
        assert can_start(status)
        
        status = CompetitionStatus.ACTIVE
        assert can_complete(status)
        
        status = CompetitionStatus.COMPLETED
        assert not can_start(status)
        assert not can_suspend(status)

    def test_realistic_workflow_with_suspension(self) -> None:
        """Test workflow with suspension: planned → active → suspended → active → completed."""
        status = CompetitionStatus.PLANNED
        assert can_start(status)
        
        status = CompetitionStatus.ACTIVE
        assert can_suspend(status)
        
        status = CompetitionStatus.SUSPENDED
        assert can_resume(status)
        
        status = CompetitionStatus.ACTIVE
        assert can_complete(status)
        
        status = CompetitionStatus.COMPLETED
        assert not can_resume(status)
