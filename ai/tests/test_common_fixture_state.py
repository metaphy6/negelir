"""Tests for the Phase 10.27 fixture state closed enum."""

from __future__ import annotations

from common.fixture_state import FixtureState, SCHEMA_VERSION


def test_fixture_state_enum_values_are_exact_and_ordered() -> None:
    expected = [
        "scheduled",
        "prematch_locked",
        "in_play_first_half",
        "halftime",
        "in_play_second_half",
        "in_play_extra_time",
        "penalty_shootout",
        "finished",
        "postponed",
        "suspended",
        "abandoned",
        "cancelled",
        "awarded",
        "unknown",
    ]

    assert [state.value for state in FixtureState] == expected
    assert len(FixtureState) == 14


def test_fixture_state_can_be_constructed_from_string() -> None:
    assert FixtureState("scheduled") is FixtureState.SCHEDULED


def test_fixture_state_schema_version_is_one() -> None:
    assert SCHEMA_VERSION == 1
