"""Multi-stage composition gate — enforce proper tournament progression.

Per COMPETITIONS.md §5.4 and Phase 13.2: competitions with multiple stages
(especially group_then_knockout) must follow a deterministic progression.
A group_then_knockout competition cannot advance to its knockout stage until
all groups are completed and qualifiers are resolved.
"""

from enum import Enum
from typing import Optional


class StageStatus(Enum):
    """Stage status in a multi-stage competition."""
    PENDING = "pending"          # Not yet started
    IN_PROGRESS = "in_progress"  # Currently running
    COMPLETED = "completed"      # Finished, results final
    CANCELLED = "cancelled"      # Removed or abandoned


def can_advance_to_knockout(
    group_stage_statuses: dict[str, StageStatus],
    all_groups_completed: bool,
    qualifier_resolved: bool,
) -> tuple[bool, str]:
    """Check if a competition can advance from group stage to knockout.
    
    Per COMPETITIONS.md §5.4: a group_then_knockout competition refuses to
    advance to knockout stage until:
    1. Every group's round_robin is COMPLETED
    2. The qualifier set is fully resolved (all qualifying rounds done)
    
    Args:
        group_stage_statuses: Dict of group_id → StageStatus.
        all_groups_completed: True if all groups have completed.
        qualifier_resolved: True if all qualifiers are done.
    
    Returns:
        (allowed: bool, reason: str)
    """
    # Verify all groups are complete
    if not all(status == StageStatus.COMPLETED for status in group_stage_statuses.values()):
        incomplete_groups = [
            group_id for group_id, status in group_stage_statuses.items()
            if status != StageStatus.COMPLETED
        ]
        return (
            False,
            f"Cannot advance to knockout: groups still in progress: {incomplete_groups}",
        )
    
    # Verify qualifiers are resolved
    if not qualifier_resolved:
        return (
            False,
            "Cannot advance to knockout: qualifier set not fully resolved",
        )
    
    return (True, "OK")


def can_complete_group_stage(
    num_groups: int,
    num_groups_completed: int,
    num_fixtures_per_group: int,
    num_fixtures_played_per_group: Optional[dict[str, int]] = None,
) -> tuple[bool, str]:
    """Check if all groups can be marked complete.
    
    Args:
        num_groups: Total number of groups.
        num_groups_completed: How many groups are marked complete.
        num_fixtures_per_group: Expected matches per group (e.g., 6 for round-robin of 4 teams).
        num_fixtures_played_per_group: Optional dict of group_id → fixtures_played.
            If provided, each group must have played all its fixtures.
    
    Returns:
        (allowed: bool, reason: str)
    """
    if num_groups_completed < num_groups:
        return (
            False,
            f"Only {num_groups_completed}/{num_groups} groups complete",
        )
    
    if num_fixtures_played_per_group:
        incomplete_groups = [
            group_id for group_id, played in num_fixtures_played_per_group.items()
            if played < num_fixtures_per_group
        ]
        if incomplete_groups:
            return (
                False,
                f"Groups still have matches pending: {incomplete_groups}",
            )
    
    return (True, "OK")


def can_start_knockout_draw(
    num_qualifiers: int,
    min_teams_expected: int,
) -> tuple[bool, str]:
    """Check if KO draw can begin.
    
    Args:
        num_qualifiers: Number of teams that qualified.
        min_teams_expected: Minimum valid count (usually power of 2: 8, 16, 32).
    
    Returns:
        (allowed: bool, reason: str)
    """
    if num_qualifiers < min_teams_expected:
        return (
            False,
            f"Not enough qualifiers ({num_qualifiers}); need {min_teams_expected}",
        )
    
    # Warn if not a power of 2 (but allow it)
    if num_qualifiers & (num_qualifiers - 1) != 0:  # not a power of 2
        return (
            True,
            f"Unusual: KO draw with {num_qualifiers} teams (not power of 2) — "
            "seeding or byes may apply",
        )
    
    return (True, "OK")


def validate_group_then_knockout_progression(
    format_: str,
    current_stage_id: str,
    group_stage_complete: bool,
    all_groups_complete: bool,
    qualifiers_resolved: bool,
) -> tuple[bool, str]:
    """Validate that a group_then_knockout competition progresses correctly.
    
    Args:
        format_: Competition format (must be "group_then_knockout").
        current_stage_id: Current stage ("group_stage", "round_of_16", etc.).
        group_stage_complete: True if group_stage fixture is closed for new entries.
        all_groups_complete: True if all individual groups finished.
        qualifiers_resolved: True if KO bracket is set.
    
    Returns:
        (allowed: bool, reason: str)
    """
    if format_ != "group_then_knockout":
        return (False, f"Format must be group_then_knockout, got {format_}")
    
    if current_stage_id == "group_stage":
        # Still in groups; no additional validation needed
        return (True, "OK")
    
    # Moving to KO stage
    if not all_groups_complete:
        return (False, "Cannot start KO: groups not all complete")
    
    if not qualifiers_resolved:
        return (False, "Cannot start KO: qualifiers not resolved")
    
    return (True, "OK")
