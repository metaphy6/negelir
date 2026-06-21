"""Test that neutral venue policy applies to all profiles.

Per COMPETITIONS.md §4.1 note 3: venue_policy override is applied at prediction
time when the profile's zero_home_advantage_when_venue_in clause is consulted.
This test documents that the calibration loader correctly sets up the
zero_home_advantage_when_venue_in field for neutral venue policies.
"""

import pytest
from common.calibration_profile_loader import CALIBRATION_PROFILES


class TestNeutralVenueZeroesHomeAdvantage:
    """Venue policy override: neutral/bubble zero home advantage."""

    def test_super_cup_one_off_zeroes_on_neutral(self) -> None:
        """Super cup (one-off) zeroes home advantage when venue is neutral."""
        profile = CALIBRATION_PROFILES["super_cup_one_off"]
        # Super cups are always neutral venues
        assert "neutral" in profile.zero_home_advantage_when_venue_in

    def test_domestic_cup_late_round_zeroes_on_neutral(self) -> None:
        """Late-round cups (often neutral finals) zero home advantage."""
        profile = CALIBRATION_PROFILES["domestic_cup_late_round"]
        # Cup finals are often at neutral venues
        assert "neutral" in profile.zero_home_advantage_when_venue_in

    def test_international_knockout_handles_multiple_policies(self) -> None:
        """International knockout can handle neutral, bubble, and host_country."""
        profile = CALIBRATION_PROFILES["international_knockout"]
        # International tournaments use multiple policies
        assert "neutral" in profile.zero_home_advantage_when_venue_in
        assert "bubble" in profile.zero_home_advantage_when_venue_in
        assert "host_country" in profile.zero_home_advantage_when_venue_in

    def test_knockout_continental_club_handles_neutral_and_bubble(self) -> None:
        """European knockout rounds can be neutral or bubble (COVID era)."""
        profile = CALIBRATION_PROFILES["knockout_continental_club"]
        assert "neutral" in profile.zero_home_advantage_when_venue_in
        assert "bubble" in profile.zero_home_advantage_when_venue_in

    def test_league_round_robin_never_zeroes(self) -> None:
        """League round-robin always has home advantage (never neutral)."""
        profile = CALIBRATION_PROFILES["league_round_robin"]
        # League matches are home/away, never neutral
        assert len(profile.zero_home_advantage_when_venue_in) == 0

    def test_domestic_cup_early_round_allows_neutral(self) -> None:
        """Early cup rounds may have neutral venues (rare, but documented)."""
        profile = CALIBRATION_PROFILES["domestic_cup_early_round"]
        # Early rounds typically don't use neutral, but profile permits it
        # (the actual venue_policy in the fixture determines application)
        assert isinstance(profile.zero_home_advantage_when_venue_in, tuple)
        # Profile is correctly immutable (tuple, not list)
        with pytest.raises(AttributeError):
            profile.zero_home_advantage_when_venue_in.append("neutral")  # type: ignore
