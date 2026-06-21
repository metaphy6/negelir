"""Test multi-stage composition gate for group_then_knockout competitions.

Per COMPETITIONS.md §5.4 and Phase 13.2 DoD: verify that tournaments with
multiple stages enforce proper progression rules.
"""

import pytest
from common.competition_multistage import (
    StageStatus,
    can_advance_to_knockout,
    can_complete_group_stage,
    can_start_knockout_draw,
    validate_group_then_knockout_progression,
)


class TestMultistageAdvanceGate:
    """Multi-stage composition gate tests."""

    def test_stage_status_enum(self) -> None:
        """Verify stage status values."""
        statuses = {s.value for s in StageStatus}
        assert statuses == {"pending", "in_progress", "completed", "cancelled"}

    def test_advance_to_knockout_all_groups_complete(self) -> None:
        """Can advance to KO when all groups done and qualifiers resolved."""
        group_statuses = {
            "group_a": StageStatus.COMPLETED,
            "group_b": StageStatus.COMPLETED,
            "group_c": StageStatus.COMPLETED,
            "group_d": StageStatus.COMPLETED,
        }
        ok, reason = can_advance_to_knockout(
            group_statuses,
            all_groups_completed=True,
            qualifier_resolved=True,
        )
        assert ok and reason == "OK"

    def test_advance_to_knockout_some_groups_incomplete(self) -> None:
        """Cannot advance if some groups still in progress."""
        group_statuses = {
            "group_a": StageStatus.COMPLETED,
            "group_b": StageStatus.IN_PROGRESS,
            "group_c": StageStatus.COMPLETED,
            "group_d": StageStatus.PENDING,
        }
        ok, reason = can_advance_to_knockout(
            group_statuses,
            all_groups_completed=False,
            qualifier_resolved=True,
        )
        assert not ok
        assert "in progress" in reason.lower() or "pending" in reason.lower()

    def test_advance_to_knockout_qualifiers_not_resolved(self) -> None:
        """Cannot advance if qualifiers not resolved."""
        group_statuses = {
            "group_a": StageStatus.COMPLETED,
            "group_b": StageStatus.COMPLETED,
        }
        ok, reason = can_advance_to_knockout(
            group_statuses,
            all_groups_completed=True,
            qualifier_resolved=False,
        )
        assert not ok
        assert "qualifier" in reason.lower()

    def test_complete_group_stage_all_done(self) -> None:
        """Can complete group stage when all groups finished."""
        ok, reason = can_complete_group_stage(
            num_groups=4,
            num_groups_completed=4,
            num_fixtures_per_group=6,
        )
        assert ok and reason == "OK"

    def test_complete_group_stage_incomplete(self) -> None:
        """Cannot complete if some groups not done."""
        ok, reason = can_complete_group_stage(
            num_groups=4,
            num_groups_completed=3,
            num_fixtures_per_group=6,
        )
        assert not ok
        assert "only" in reason.lower()

    def test_complete_group_stage_with_fixture_verification(self) -> None:
        """Can verify individual group fixture counts before marking complete."""
        fixtures_played = {
            "group_a": 6,
            "group_b": 6,
            "group_c": 5,  # incomplete
            "group_d": 6,
        }
        ok, reason = can_complete_group_stage(
            num_groups=4,
            num_groups_completed=4,
            num_fixtures_per_group=6,
            num_fixtures_played_per_group=fixtures_played,
        )
        assert not ok
        assert "pending" in reason.lower()

    def test_knockout_draw_enough_qualifiers(self) -> None:
        """Can start KO draw with minimum required qualifiers."""
        ok, reason = can_start_knockout_draw(
            num_qualifiers=16,
            min_teams_expected=8,
        )
        assert ok

    def test_knockout_draw_power_of_two(self) -> None:
        """Power of 2 qualifiers is ideal."""
        for num in [8, 16, 32, 64]:
            ok, reason = can_start_knockout_draw(
                num_qualifiers=num,
                min_teams_expected=8,
            )
            assert ok

    def test_knockout_draw_insufficient_qualifiers(self) -> None:
        """Cannot start KO with fewer qualifiers than minimum."""
        ok, reason = can_start_knockout_draw(
            num_qualifiers=6,
            min_teams_expected=8,
        )
        assert not ok
        assert "enough" in reason.lower()

    def test_knockout_draw_non_power_of_two_warning(self) -> None:
        """Non-power-of-2 qualifiers is allowed but warned."""
        ok, reason = can_start_knockout_draw(
            num_qualifiers=24,
            min_teams_expected=8,
        )
        assert ok  # allowed
        assert "unusual" in reason.lower()  # but warned

    def test_validate_euro_progression_group_stage(self) -> None:
        """EURO can stay in group_stage while groups running."""
        ok, reason = validate_group_then_knockout_progression(
            format_="group_then_knockout",
            current_stage_id="group_stage",
            group_stage_complete=False,
            all_groups_complete=False,
            qualifiers_resolved=False,
        )
        assert ok

    def test_validate_euro_progression_to_knockout(self) -> None:
        """EURO can advance to KO only after groups done."""
        ok, reason = validate_group_then_knockout_progression(
            format_="group_then_knockout",
            current_stage_id="round_of_16",
            group_stage_complete=True,
            all_groups_complete=True,
            qualifiers_resolved=True,
        )
        assert ok

    def test_validate_euro_progression_premature_knockout(self) -> None:
        """EURO cannot start KO if groups incomplete."""
        ok, reason = validate_group_then_knockout_progression(
            format_="group_then_knockout",
            current_stage_id="round_of_16",
            group_stage_complete=False,
            all_groups_complete=False,
            qualifiers_resolved=False,
        )
        assert not ok

    def test_validate_wrong_format(self) -> None:
        """Validation rejects non-group_then_knockout formats."""
        ok, reason = validate_group_then_knockout_progression(
            format_="single_knockout",
            current_stage_id="round_of_16",
            group_stage_complete=True,
            all_groups_complete=True,
            qualifiers_resolved=True,
        )
        assert not ok
        assert "must be group_then_knockout" in reason
