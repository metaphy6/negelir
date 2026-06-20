"""Tests for Phase 19 §19.14 — Season calendar & fixture handling."""

import pytest
from datetime import date
from ai.common.season_calendar import SeasonCalendar, SeasonCalendarRegistry


class TestSeasonCalendar:
    """§19.14: Season calendar boundaries and fixtures."""
    
    def test_season_calendar_validates_boundaries(self):
        """Season end must be after start."""
        with pytest.raises(ValueError):
            SeasonCalendar(
                league_id="tr_super_lig",
                season="2024-2025",
                start_date=date(2025, 1, 1),
                end_date=date(2024, 1, 1),  # Invalid: end before start
                primary_timezone="Europe/Istanbul"
            )
    
    def test_contains_date_basic(self):
        """Date containment check works."""
        cal = SeasonCalendar(
            league_id="tr_super_lig",
            season="2024-2025",
            start_date=date(2024, 8, 1),
            end_date=date(2025, 5, 31),
            primary_timezone="Europe/Istanbul"
        )
        
        assert cal.contains_date(date(2024, 9, 1))
        assert cal.contains_date(date(2025, 3, 1))
        assert not cal.contains_date(date(2024, 7, 1))
        assert not cal.contains_date(date(2025, 6, 1))
    
    def test_split_season_excludes_break(self):
        """Split seasons exclude break period."""
        cal = SeasonCalendar(
            league_id="australian_league",
            season="2024-2025",
            start_date=date(2024, 8, 1),
            end_date=date(2025, 5, 31),
            primary_timezone="Australia/Sydney",
            is_split_season=True,
            split_break_start=date(2024, 12, 1),
            split_break_end=date(2025, 1, 31)
        )
        
        assert cal.contains_date(date(2024, 9, 1))  # Before break
        assert not cal.contains_date(date(2024, 12, 15))  # During break
        assert cal.contains_date(date(2025, 2, 1))  # After break
    
    def test_timezone_resolution(self):
        """Timezone is properly resolved."""
        cal = SeasonCalendar(
            league_id="tr_super_lig",
            season="2024-2025",
            start_date=date(2024, 8, 1),
            end_date=date(2025, 5, 31),
            primary_timezone="Europe/Istanbul"
        )
        
        tz = cal.get_timezone()
        assert str(tz) == "Europe/Istanbul"
    
    def test_invalid_timezone_raises(self):
        """Invalid timezone raises error."""
        cal = SeasonCalendar(
            league_id="test",
            season="2024-2025",
            start_date=date(2024, 8, 1),
            end_date=date(2025, 5, 31),
            primary_timezone="Invalid/Timezone"
        )
        
        with pytest.raises(ValueError):
            cal.get_timezone()


class TestSeasonCalendarRegistry:
    """§19.14: Season calendar registry."""
    
    def test_registry_stores_calendars(self):
        """Registry can register and retrieve calendars."""
        registry = SeasonCalendarRegistry()
        
        cal = SeasonCalendar(
            league_id="tr_super_lig",
            season="2024-2025",
            start_date=date(2024, 8, 1),
            end_date=date(2025, 5, 31),
            primary_timezone="Europe/Istanbul"
        )
        
        registry.register(cal)
        assert len(registry.calendars) == 1
    
    def test_registry_prevents_duplicates(self):
        """Cannot register same season twice."""
        registry = SeasonCalendarRegistry()
        
        cal = SeasonCalendar(
            league_id="tr_super_lig",
            season="2024-2025",
            start_date=date(2024, 8, 1),
            end_date=date(2025, 5, 31),
            primary_timezone="Europe/Istanbul"
        )
        
        registry.register(cal)
        with pytest.raises(ValueError):
            registry.register(cal)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
