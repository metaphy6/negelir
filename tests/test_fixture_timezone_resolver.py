"""Tests for Phase 19 §19.19 — Fixture lifecycle: timezone & deduplication."""

import pytest
from datetime import datetime, timedelta
import pytz
from common.fixture_timezone_resolver import (
    FixtureRecord, FixtureDeduplicator, FixtureTimezoneNormalizer, FixtureTimezone
)


class MockConfig:
    """Mock config for testing."""
    fixture_dedup_window_minutes = 120
    fixture_dedup_quarantine_hours = 6


class TestFixtureRecord:
    """§19.19: Fixture record UTC normalization."""
    
    def test_fixture_requires_utc_timezone(self):
        """Fixture must have UTC kickoff_utc."""
        with pytest.raises(ValueError):
            FixtureRecord(
                league_id="tr_super_lig",
                source="mackolik",
                home_canonical_id="team_1",
                away_canonical_id="team_2",
                kickoff_utc=datetime(2024, 9, 1, 16, 30),  # No timezone!
                kickoff_local=("19:30", "Europe/Istanbul")
            )
    
    def test_fixture_valid_utc(self):
        """Valid fixture with UTC timezone."""
        utc_time = datetime(2024, 9, 1, 16, 30, tzinfo=pytz.UTC)
        fixture = FixtureRecord(
            league_id="tr_super_lig",
            source="mackolik",
            home_canonical_id="team_1",
            away_canonical_id="team_2",
            kickoff_utc=utc_time,
            kickoff_local=("19:30", "Europe/Istanbul")
        )
        assert fixture.status == "scheduled"
    
    def test_fixture_valid_statuses(self):
        """Fixture status must be one of valid values."""
        utc_time = datetime(2024, 9, 1, 16, 30, tzinfo=pytz.UTC)
        
        # Valid statuses
        for status in ["scheduled", "postponed", "cancelled", "abandoned"]:
            fixture = FixtureRecord(
                league_id="tr_super_lig",
                source="mackolik",
                home_canonical_id="team_1",
                away_canonical_id="team_2",
                kickoff_utc=utc_time,
                kickoff_local=("19:30", "Europe/Istanbul"),
                status=status
            )
            assert fixture.status == status
        
        # Invalid status
        with pytest.raises(ValueError):
            FixtureRecord(
                league_id="tr_super_lig",
                source="mackolik",
                home_canonical_id="team_1",
                away_canonical_id="team_2",
                kickoff_utc=utc_time,
                kickoff_local=("19:30", "Europe/Istanbul"),
                status="invalid"
            )


class TestFixtureDeduplicator:
    """§19.19: Cross-source fixture deduplication."""
    
    def test_dedup_merges_within_window(self):
        """Fixtures within dedup window are merged."""
        cfg = MockConfig()
        dedup = FixtureDeduplicator(cfg)
        
        utc_time = datetime(2024, 9, 1, 16, 30, tzinfo=pytz.UTC)
        
        # Store first fixture
        fixture1 = FixtureRecord(
            league_id="tr_super_lig",
            source="mackolik",
            home_canonical_id="team_1",
            away_canonical_id="team_2",
            kickoff_utc=utc_time,
            kickoff_local=("19:30", "Europe/Istanbul")
        )
        dedup.existing_fixtures[fixture1.get_dedup_key()] = fixture1
        
        # Merge second fixture (same match, different source, within window)
        fixture2 = FixtureRecord(
            league_id="tr_super_lig",
            source="nesine",
            home_canonical_id="team_1",
            away_canonical_id="team_2",
            kickoff_utc=utc_time + timedelta(minutes=5),
            kickoff_local=("19:35", "Europe/Istanbul")
        )
        
        merged, action = dedup.try_merge_or_quarantine(fixture2)
        assert merged is True
        assert action == "merged"
        assert fixture1.secondary_source_data is not None
        assert "nesine" in fixture1.secondary_source_data


class TestFixtureTimezoneNormalizer:
    """§19.19: UTC normalization."""
    
    def test_normalize_with_registered_timezone(self):
        """Normalize local time using registered timezone."""
        cfg = MockConfig()
        normalizer = FixtureTimezoneNormalizer(cfg)
        
        # Register timezone
        normalizer.register_timezone("tr_super_lig", "mackolik", "Europe/Istanbul")
        
        # Normalize (using today's date)
        utc_dt, local_tuple = normalizer.normalize_to_utc(
            "tr_super_lig",
            "mackolik",
            "19:30"
        )
        
        # Result should be in UTC
        assert utc_dt.tzinfo == pytz.UTC
        assert local_tuple[0] == "19:30"
        assert local_tuple[1] == "Europe/Istanbul"
    
    def test_normalize_with_explicit_offset(self):
        """Explicit offset from source takes precedence."""
        cfg = MockConfig()
        normalizer = FixtureTimezoneNormalizer(cfg)
        
        # Register a timezone but provide explicit offset
        normalizer.register_timezone("kr_league", "goal", "Asia/Seoul")
        
        utc_dt, local_tuple = normalizer.normalize_to_utc(
            "kr_league",
            "goal",
            "19:30",
            explicit_offset="+09:00"  # Prefer source's offset
        )
        
        assert utc_dt.tzinfo == pytz.UTC
        assert local_tuple[1] == "+09:00"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
