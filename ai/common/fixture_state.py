"""Phase 10 §10.27 — closed fixture-state vocabulary."""

from __future__ import annotations

from enum import Enum

SCHEMA_VERSION = 1


class FixtureState(str, Enum):
    """Closed fixture lifecycle states used by the NLP dispatch layer."""

    SCHEDULED = "scheduled"
    PREMATCH_LOCKED = "prematch_locked"
    IN_PLAY_FIRST_HALF = "in_play_first_half"
    HALFTIME = "halftime"
    IN_PLAY_SECOND_HALF = "in_play_second_half"
    IN_PLAY_EXTRA_TIME = "in_play_extra_time"
    PENALTY_SHOOTOUT = "penalty_shootout"
    FINISHED = "finished"
    POSTPONED = "postponed"
    SUSPENDED = "suspended"
    ABANDONED = "abandoned"
    CANCELLED = "cancelled"
    AWARDED = "awarded"
    UNKNOWN = "unknown"
