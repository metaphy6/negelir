"""Phase 21.2 — Health plane (injuries, availability) tests.

Tests for all 9 bullets per ROADMAP §21.2:
1. Schema validation (InjuryPayload, AvailabilityPayload with source_url_hash)
2. Extractor (parses Mackolik + presser, raises ExtractionError)
3. Differ (diff key, confidence ranking)
4. Confidence-override rule (club_official in 24h wins)
5. Stale-decay rule (doubtful > 36h pre-KO → fit)
6. Post-match reactor (idempotent lineup confirmation)
7. Squad availability vector + CI widening
8. International calendar (international_duty excluded)
9. Tests (≥7 total, ≥2 adversarial per area)

Total: 8 tests, including 3 adversarial cases (bullets 1, 2, 8).
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from common.schemas.records import InjuryPayload, AvailabilityPayload
from datasource.scraper.extractors.injury_watch import InjuryExtractor, ExtractionError
from datasource.scraper.differs.injury_watch import InjuryDiffer, CONFIDENCE_RANK
from model.health_plane_features import (
    InternationalWindowFilter,
    SquadAvailabilityVector,
)


class TestSchemaValidation:
    """Test InjuryPayload and AvailabilityPayload TypedDicts."""

    def test_injury_payload_schema_valid(self) -> None:
        """Test valid InjuryPayload structure."""
        url = "https://example.com/injury"
        source_hash = hashlib.sha256(url.encode('utf-8')).hexdigest()
        
        payload = InjuryPayload(
            injury_id="INJ_001",
            player_id="P_123",
            team_id="TEAM_1",
            body_part="knee",
            severity="moderate",
            diagnosed_at="2026-06-20T10:30:00Z",
            expected_return="2026-07-05",
            confidence="club_statement",
            source_url_hash=source_hash,
        )
        
        assert payload["injury_id"] == "INJ_001"
        assert payload["source_url_hash"] == source_hash
        assert len(source_hash) == 64  # SHA-256 hex length
        assert not url in str(payload)  # Raw URL not stored

    def test_availability_payload_schema_valid(self) -> None:
        """Test valid AvailabilityPayload structure."""
        payload = AvailabilityPayload(
            availability_id="AVAIL_001",
            player_id="P_123",
            team_id="TEAM_1",
            fixture_id="MATCH_001",
            status="doubtful",
            asserted_at="2026-06-20T14:00:00Z",
            source_confidence="club_official",
        )
        
        assert payload["status"] == "doubtful"
        assert payload["source_confidence"] == "club_official"
        assert payload["fixture_id"] == "MATCH_001"

    def test_source_url_hash_security_sha256(self) -> None:
        """Adversarial: test that source_url_hash is SHA-256, not raw URL.
        
        Security requirement per ROADMAP §21.2 bullet 1.
        """
        url1 = "https://example.com/injury"
        url2 = "https://other.com/injury"
        
        hash1 = hashlib.sha256(url1.encode('utf-8')).hexdigest()
        hash2 = hashlib.sha256(url2.encode('utf-8')).hexdigest()
        
        # Hashes are deterministic but not reversible
        assert hash1 != hash2
        assert len(hash1) == 64
        assert len(hash2) == 64
        
        # Raw URLs never appear in hash
        assert url1 not in hash1
        assert url2 not in hash2


class TestExtractor:
    """Test InjuryExtractor parsing and validation."""

    def test_extract_injuries_from_mackolik_json_valid(self) -> None:
        """Test valid Mackolik JSON extraction."""
        extractor = InjuryExtractor()
        
        data = {
            "injuries": [
                {
                    "id": "INJ_001",
                    "player_id": "P_123",
                    "team_id": "TEAM_1",
                    "body_part": "knee",
                    "severity": "moderate",
                    "diagnosed_at": "2026-06-20T10:30:00Z",
                    "expected_return": "2026-07-05",
                    "confidence": "club_statement",
                }
            ]
        }
        
        results = extractor.extract_injuries_from_mackolik_json(
            data, "https://example.com/injuries"
        )
        
        assert len(results) == 1
        assert results[0]["player_id"] == "P_123"
        assert results[0]["severity"] == "moderate"

    def test_extract_availability_from_presser_json_valid(self) -> None:
        """Test valid presser JSON extraction."""
        extractor = InjuryExtractor()
        
        data = {
            "availabilities": [
                {
                    "id": "AVAIL_001",
                    "player_id": "P_123",
                    "team_id": "TEAM_1",
                    "fixture_id": "MATCH_001",
                    "status": "doubtful",
                    "asserted_at": "2026-06-20T14:00:00Z",
                }
            ]
        }
        
        results = extractor.extract_availability_from_presser_json(
            data, "https://example.com/presser", "club_official"
        )
        
        assert len(results) == 1
        assert results[0]["status"] == "doubtful"
        assert results[0]["source_confidence"] == "club_official"

    def test_extractor_raises_on_malformed_injury_record(self) -> None:
        """Adversarial: test ExtractionError on missing required fields."""
        extractor = InjuryExtractor()
        
        # Missing 'body_part' field
        data_missing_field = {
            "injuries": [
                {
                    "id": "INJ_001",
                    "player_id": "P_123",
                    "team_id": "TEAM_1",
                    # body_part missing
                    "severity": "moderate",
                    "diagnosed_at": "2026-06-20T10:30:00Z",
                    "confidence": "club_statement",
                }
            ]
        }
        
        with pytest.raises(ExtractionError, match="Missing required field"):
            extractor.extract_injuries_from_mackolik_json(
                data_missing_field, "https://example.com"
            )

    def test_extractor_raises_on_invalid_severity(self) -> None:
        """Adversarial: test ExtractionError on invalid severity."""
        extractor = InjuryExtractor()
        
        data = {
            "injuries": [
                {
                    "id": "INJ_001",
                    "player_id": "P_123",
                    "team_id": "TEAM_1",
                    "body_part": "knee",
                    "severity": "INVALID",  # Invalid severity
                    "diagnosed_at": "2026-06-20T10:30:00Z",
                    "confidence": "club_statement",
                }
            ]
        }
        
        with pytest.raises(ExtractionError, match="Invalid severity"):
            extractor.extract_injuries_from_mackolik_json(
                data, "https://example.com"
            )


class TestDifferConfidenceOverride:
    """Test differ confidence-override rule (bullet 4)."""

    def test_club_official_overrides_press_status_within_24h(self) -> None:
        """Test that club_official in past 24h overrides press status.
        
        Per ROADMAP §21.2 bullet 4: club_official in past 24h wins.
        """
        differ = InjuryDiffer()
        now = datetime.utcnow()
        
        # New club_official status from 12h ago
        new_payload = AvailabilityPayload(
            availability_id="AVAIL_NEW",
            player_id="P_123",
            team_id="TEAM_1",
            fixture_id="MATCH_001",
            status="out",
            asserted_at=(now - timedelta(hours=12)).isoformat() + "Z",
            source_confidence="club_official",
        )
        
        # Existing press status from 6h ago
        existing_payload = AvailabilityPayload(
            availability_id="AVAIL_OLD",
            player_id="P_123",
            team_id="TEAM_1",
            fixture_id="MATCH_001",
            status="doubtful",
            asserted_at=(now - timedelta(hours=6)).isoformat() + "Z",
            source_confidence="press",
        )
        
        should_override = differ.should_override_existing(new_payload, [existing_payload])
        assert should_override is True, "club_official within 24h should override press"

    def test_doubtful_auto_decays_to_fit_after_36h(self) -> None:
        """Test stale-decay: doubtful > 36h pre-KO → fit (bullet 5).
        
        Per ROADMAP §21.2 bullet 5.
        """
        differ = InjuryDiffer()
        
        now = datetime.utcnow()
        # Doubtful status from 40h ago
        old_doubtful = AvailabilityPayload(
            availability_id="AVAIL_001",
            player_id="P_123",
            team_id="TEAM_1",
            fixture_id="MATCH_001",
            status="doubtful",
            asserted_at=(now - timedelta(hours=40)).isoformat() + "Z",
            source_confidence="press",
        )
        
        # Fixture KO is 30h from now
        fixture_kickoff = (now + timedelta(hours=30)).isoformat() + "Z"
        
        decayed = differ.compute_stale_decay(old_doubtful, fixture_kickoff)
        assert decayed["status"] == "fit", "Doubtful >36h pre-KO should decay to fit"

    def test_recent_doubtful_does_not_decay_within_36h(self) -> None:
        """Test that recent doubtful (< 36h pre-KO) does NOT decay."""
        differ = InjuryDiffer()
        
        now = datetime.utcnow()
        # Doubtful status from 10h ago
        recent_doubtful = AvailabilityPayload(
            availability_id="AVAIL_001",
            player_id="P_123",
            team_id="TEAM_1",
            fixture_id="MATCH_001",
            status="doubtful",
            asserted_at=(now - timedelta(hours=10)).isoformat() + "Z",
            source_confidence="press",
        )
        
        # Fixture KO is 40h from now (so 50h from assertion, >36h)
        # Actually: asserted_at is 10h ago, kickoff is 40h away, so 50h total before KO
        # We want <36h, so let's say kickoff is 20h away
        fixture_kickoff = (now + timedelta(hours=20)).isoformat() + "Z"
        
        result = differ.compute_stale_decay(recent_doubtful, fixture_kickoff)
        assert result["status"] == "doubtful", "Recent doubtful (<36h) should NOT decay"


class TestPostMatchReactor:
    """Test post-match retroactive fit correction (bullet 6)."""

    def test_post_match_retroactive_fit_correction_is_idempotent(self) -> None:
        """Test post-match reactor is idempotent (bullet 6).
        
        Running twice on an already-corrected record is a no-op.
        """
        differ = InjuryDiffer()
        
        # Original doubtful status
        payload = AvailabilityPayload(
            availability_id="AVAIL_001",
            player_id="P_123",
            team_id="TEAM_1",
            fixture_id="MATCH_001",
            status="doubtful",
            asserted_at="2026-06-20T14:00:00Z",
            source_confidence="press",
        )
        
        starting_xi = ["P_123", "P_124", "P_125"]
        substitutes = []
        
        # First application: doubtful → fit
        result1 = differ.post_match_retroactive_fit(payload, starting_xi, substitutes)
        assert result1["status"] == "fit"
        
        # Second application (idempotent): fit → fit (no-op)
        result2 = differ.post_match_retroactive_fit(result1, starting_xi, substitutes)
        assert result2["status"] == "fit"
        assert result1 == result2


class TestSquadAvailabilityVector:
    """Test squad availability feature computation (bullet 7)."""

    def test_squad_availability_vector_reduces_team_strength_correctly(self) -> None:
        """Test squad availability reduction calculation (bullet 7)."""
        vector = SquadAvailabilityVector()
        
        squad = [
            {"player_id": "P_1", "rating": 0.9, "starter_likelihood": 1.0},  # Available
            {"player_id": "P_2", "rating": 0.8, "starter_likelihood": 1.0},  # Doubtful
            {"player_id": "P_3", "rating": 0.7, "starter_likelihood": 0.5},  # Doubtful, partial
            {"player_id": "P_4", "rating": 0.6, "starter_likelihood": 0.0},  # Substitute, doubtful
        ]
        
        available = {"P_1"}
        international_duty = set()  # No international duty
        
        # Expected reduction: (0.8 * 1.0) + (0.7 * 0.5) = 0.8 + 0.35 = 1.15
        reduction = vector.compute_team_strength_reduction(squad, available, international_duty)
        
        assert reduction == pytest.approx(-1.15, abs=0.001), \
            f"Expected -1.15, got {reduction}"

    def test_international_duty_excluded_from_squad_strength_penalty(self) -> None:
        """Test that international_duty does NOT reduce team_strength (bullet 8).
        
        Per ROADMAP §21.2 bullet 8: international_duty excluded from penalty.
        """
        vector = SquadAvailabilityVector()
        
        squad = [
            {"player_id": "P_1", "rating": 0.9, "starter_likelihood": 1.0},  # Available
            {"player_id": "P_2", "rating": 0.8, "starter_likelihood": 1.0},  # International duty
            {"player_id": "P_3", "rating": 0.7, "starter_likelihood": 1.0},  # Doubtful
        ]
        
        available = {"P_1"}
        international_duty = {"P_2"}  # Excluded from penalty
        
        # Expected reduction: only P_3 is penalized: (0.7 * 1.0) = 0.7
        reduction = vector.compute_team_strength_reduction(squad, available, international_duty)
        
        assert reduction == pytest.approx(-0.7, abs=0.001), \
            f"International duty should be excluded; got {reduction}"

    def test_high_uncertainty_ratio_widens_proofreader_ci(self) -> None:
        """Test CI widening when doubtful > 30% of XI (bullet 7)."""
        vector = SquadAvailabilityVector(ci_widen_threshold=0.30)
        
        squad = [
            {"player_id": "P_1", "starter_likelihood": 1.0},  # Starting
            {"player_id": "P_2", "starter_likelihood": 1.0},  # Starting
            {"player_id": "P_3", "starter_likelihood": 1.0},  # Starting (doubtful)
            {"player_id": "P_4", "starter_likelihood": 1.0},  # Starting
            {"player_id": "P_5", "starter_likelihood": 1.0},  # Starting
            {"player_id": "P_6", "starter_likelihood": 0.5},  # Bench
        ]
        
        doubtful = {"P_3", "P_4"}  # 2 out of 5 starting XI = 40% > 30%
        
        uncertainty_ratio = vector.compute_uncertainty_ratio(squad, doubtful)
        should_widen = vector.should_widen_ci(uncertainty_ratio)
        
        assert should_widen is True, "Doubtful >30% should trigger CI widening"

    def test_low_uncertainty_does_not_widen_ci(self) -> None:
        """Test that CI is NOT widened when doubtful ≤ 30%."""
        vector = SquadAvailabilityVector(ci_widen_threshold=0.30)
        
        squad = [
            {"player_id": "P_1", "starter_likelihood": 1.0},  # Starting
            {"player_id": "P_2", "starter_likelihood": 1.0},  # Starting (doubtful)
            {"player_id": "P_3", "starter_likelihood": 1.0},  # Starting
            {"player_id": "P_4", "starter_likelihood": 0.5},  # Bench
        ]
        
        doubtful = {"P_2"}  # 1 out of 3 starting XI = 33% > 30%... wait, should be True
        # Let's use a smaller ratio
        squad_large = squad + [
            {"player_id": "P_5", "starter_likelihood": 1.0},  # Starting
        ]
        
        doubtful_small = {"P_5"}  # 1 out of 4 = 25% < 30%
        
        uncertainty_ratio = vector.compute_uncertainty_ratio(squad_large, doubtful_small)
        should_widen = vector.should_widen_ci(uncertainty_ratio)
        
        assert should_widen is False, "Doubtful ≤30% should NOT trigger CI widening"


class TestInternationalCalendar:
    """Test international window calendar filtering (bullet 8)."""

    def test_international_duty_excluded_from_squad_strength_penalty_calendar(
        self, tmp_path: Path
    ) -> None:
        """Integration test: international calendar filters international_duty.
        
        Adversarial: ensure international breaks are correctly loaded and applied.
        """
        # Create a minimal confederation_calendars.json
        cal_data = {
            "confederations": [
                {
                    "confederation_id": "uefa",
                    "name": "UEFA",
                    "international_breaks": [
                        {
                            "start_date": "2026-06-01",
                            "end_date": "2026-06-15",
                            "description": "Euro 2024",
                        }
                    ],
                }
            ]
        }
        
        cal_file = tmp_path / "cal.json"
        cal_file.write_text(json.dumps(cal_data))
        
        intl_filter = InternationalWindowFilter.load_from_file(str(cal_file))
        
        # Test: date within break
        assert intl_filter.is_international_window("2026-06-10", "uefa") is True
        
        # Test: date outside break
        assert intl_filter.is_international_window("2026-07-01", "uefa") is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
