"""
Phase 13.4.5.2 — Player on-loan dual eligibility.

Per ROADMAP §13.4.5.2: A player on loan from club A to club B retains
eligibility for both clubs' competitions until `loan_end_date`; predictor's
lineup feature reads `eligible_at(date)` rather than a static list.

Proof test: (a) on-loan player eligible for both clubs during loan period,
(b) after loan ends, eligible for parent club only,
(c) non-loaned player eligible for current club only.
"""

from datetime import datetime, timedelta

import pytest

from tqu.player_registry import PlayerRecord


class TestLoanDualEligibility:
    """Test on-loan dual eligibility (13.4.5.2)."""

    def test_loaned_player_dual_eligible_during_loan(self) -> None:
        """Loaned player is eligible for both clubs during loan period."""
        today = datetime.now().date()
        loan_end = today + timedelta(days=30)
        
        player = PlayerRecord(
            source_id="player_001",
            name="Rodrigo Silva",
            team_id="arsenal_en",           # Current club (on loan to)
            on_loan_from="benfica_pt",      # Parent club
            loan_end_date=loan_end.isoformat(),
        )
        
        # During loan period, eligible for both
        eligible = player.eligible_at(today.isoformat())
        assert "arsenal_en" in eligible
        assert "benfica_pt" in eligible
        assert len(eligible) == 2

    def test_loaned_player_single_eligible_after_loan(self) -> None:
        """After loan ends, player eligible for parent club only."""
        today = datetime.now().date()
        loan_end = today - timedelta(days=1)  # Loan ended yesterday
        
        player = PlayerRecord(
            source_id="player_002",
            name="João Pereira",
            team_id="manchester_city_en",   # Was on loan here
            on_loan_from="porto_pt",        # Parent club
            loan_end_date=loan_end.isoformat(),
        )
        
        # After loan ends, eligible for parent club only
        eligible = player.eligible_at(today.isoformat())
        assert eligible == ["porto_pt"]

    def test_loaned_player_eligible_on_loan_end_date(self) -> None:
        """On the last day of loan, player is still eligible for both clubs."""
        today = datetime.now().date()
        
        player = PlayerRecord(
            source_id="player_003",
            name="Raheem Sterling",
            team_id="chelsea_en",
            on_loan_from="manchester_city_en",
            loan_end_date=today.isoformat(),  # Loan ends today
        )
        
        # On loan_end_date (inclusive), still eligible for both
        eligible = player.eligible_at(today.isoformat())
        assert "chelsea_en" in eligible
        assert "manchester_city_en" in eligible

    def test_non_loaned_player_single_eligible(self) -> None:
        """Non-loaned player eligible for current club only."""
        player = PlayerRecord(
            source_id="player_004",
            name="Erling Haaland",
            team_id="manchester_city_en",
            # on_loan_from=None (default)
        )
        
        today = datetime.now().date()
        eligible = player.eligible_at(today.isoformat())
        assert eligible == ["manchester_city_en"]

    def test_loan_eligibility_handles_invalid_date(self) -> None:
        """Invalid date input conservatively returns current club only."""
        player = PlayerRecord(
            source_id="player_005",
            name="Player Name",
            team_id="club_a",
            on_loan_from="club_b",
            loan_end_date="2025-12-31",
        )
        
        # Invalid date format
        eligible = player.eligible_at("not-a-date")
        assert eligible == ["club_a"]  # Conservative fallback

    def test_is_on_loan_flag(self) -> None:
        """Player.is_on_loan() correctly identifies loan status."""
        on_loan = PlayerRecord(
            source_id="p1",
            name="Loaned Player",
            team_id="current_club",
            on_loan_from="parent_club",
        )
        assert on_loan.is_on_loan()
        
        not_on_loan = PlayerRecord(
            source_id="p2",
            name="Regular Player",
            team_id="home_club",
        )
        assert not not_on_loan.is_on_loan()

    def test_loan_without_end_date(self) -> None:
        """Loan without end_date treated as permanent move."""
        player = PlayerRecord(
            source_id="p3",
            name="Permanent Transfer",
            team_id="new_club",
            on_loan_from="old_club",
            loan_end_date=None,  # No end date
        )
        
        today = datetime.now().date()
        eligible = player.eligible_at(today.isoformat())
        # No end date: treat as permanent move (current club only)
        assert eligible == ["new_club"]

    def test_multiple_fixtures_in_loan_window(self) -> None:
        """Multiple fixtures during loan window show dual eligibility."""
        today = datetime.now().date()
        loan_end = today + timedelta(days=60)
        
        player = PlayerRecord(
            source_id="p4",
            name="Multi-Fixture Player",
            team_id="loan_club",
            on_loan_from="parent_club",
            loan_end_date=loan_end.isoformat(),
        )
        
        # Check eligibility across multiple dates in loan period
        for days_offset in [0, 15, 30, 45, 59]:
            date = today + timedelta(days=days_offset)
            eligible = player.eligible_at(date.isoformat())
            assert len(eligible) == 2, f"Day {days_offset}: expected dual eligibility"
            assert "loan_club" in eligible
            assert "parent_club" in eligible


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
