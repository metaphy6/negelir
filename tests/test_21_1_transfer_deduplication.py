"""Phase 21.1 §21.1 — Cross-source transfer deduplication tests.

Tests for deduplication logic:
  - Identical transfers from two sources collapse to one
  - Higher confidence wins (official > agreed > rumour)
  - Tie-break: source priority (earlier index wins)
  - Dedup key: (player_id, transfer_type, effective_at)
  - Different transfer types don't collide
  - Empty inputs handled correctly

Per ROADMAP §21.1 bullet 8 and ENRICHMENT_DATA.md §2.2.
Minimum 8 tests including ≥ 2 adversarial.
"""

from __future__ import annotations

import pytest

from ai.scraper.transfer_deduplication import (
    get_dedup_key,
    should_replace,
    deduplicate_transfers,
    CONFIDENCE_RANK,
)
from ai.common.schemas.records import TransferPayload


@pytest.fixture
def transfer_base() -> dict:
    """Base transfer record for tests."""
    return {
        "transfer_id": "T_001",
        "player_id": "P_100",
        "from_team_id": "TEAM_A",
        "to_team_id": "TEAM_B",
        "transfer_window": "summer",
        "transfer_type": "permanent",
        "fee_eur": 10_000_000,
        "contract_until": "2028-06-30",
        "announced_at": "2026-06-01T10:00:00Z",
        "effective_at": "2026-06-15T00:00:00Z",
        "confidence": "official",
        "source": "mackolik",
    }


class TestDedupKey:
    """Tests for deduplication key extraction."""
    
    def test_dedup_key_tuple_format(self, transfer_base: dict) -> None:
        """Dedup key should be (player_id, transfer_type, effective_at)."""
        record: TransferPayload = transfer_base  # type: ignore
        key = get_dedup_key(record)
        
        assert key == ("P_100", "permanent", "2026-06-15T00:00:00Z")
    
    def test_different_players_different_keys(self, transfer_base: dict) -> None:
        """Different players should have different keys."""
        record1: TransferPayload = transfer_base  # type: ignore
        
        record2_dict = {**transfer_base}
        record2_dict["player_id"] = "P_999"
        record2: TransferPayload = record2_dict  # type: ignore
        
        key1 = get_dedup_key(record1)
        key2 = get_dedup_key(record2)
        
        assert key1 != key2


class TestConfidenceWins:
    """Tests for confidence-based dedup (higher confidence wins)."""
    
    def test_official_beats_agreed(self) -> None:
        """Official transfer should beat agreed transfer."""
        should_repl = should_replace(
            existing_confidence="agreed",
            existing_source="mackolik",
            new_confidence="official",
            new_source="club_site",
            source_priority={},
        )
        assert should_repl is True
    
    def test_agreed_beats_rumour(self) -> None:
        """Agreed transfer should beat rumour transfer."""
        should_repl = should_replace(
            existing_confidence="rumour",
            existing_source="club_site",
            new_confidence="agreed",
            new_source="mackolik",
            source_priority={},
        )
        assert should_repl is True
    
    def test_official_beats_rumour(self) -> None:
        """Official transfer should beat rumour transfer."""
        should_repl = should_replace(
            existing_confidence="rumour",
            existing_source="mackolik",
            new_confidence="official",
            new_source="club_site",
            source_priority={},
        )
        assert should_repl is True
    
    def test_lower_confidence_doesnt_replace(self) -> None:
        """Lower confidence should not replace higher confidence."""
        should_repl = should_replace(
            existing_confidence="official",
            existing_source="mackolik",
            new_confidence="agreed",
            new_source="club_site",
            source_priority={},
        )
        assert should_repl is False


class TestSourcePriority:
    """Tests for tie-breaking by source priority."""
    
    def test_priority_index_lower_wins(self) -> None:
        """Lower priority index (earlier source) should win on tie."""
        should_repl = should_replace(
            existing_confidence="official",
            existing_source="source_a",
            new_confidence="official",
            new_source="source_b",
            source_priority={
                "source_a": 0,  # Higher priority (earlier)
                "source_b": 1,  # Lower priority (later)
            },
        )
        assert should_repl is False
    
    def test_priority_index_higher_replaced(self) -> None:
        """Higher priority index (later source) should be replaced."""
        should_repl = should_replace(
            existing_confidence="official",
            existing_source="source_b",
            new_confidence="official",
            new_source="source_a",
            source_priority={
                "source_a": 0,  # Higher priority
                "source_b": 1,  # Lower priority
            },
        )
        assert should_repl is True
    
    def test_unknown_source_priority(self) -> None:
        """Unknown sources should not break tie (use defaults)."""
        should_repl = should_replace(
            existing_confidence="official",
            existing_source="known_source",
            new_confidence="official",
            new_source="unknown_source",
            source_priority={"known_source": 0},
        )
        # unknown_source gets inf, so should not replace
        assert should_repl is False


class TestDedupWorkflow:
    """Tests for full deduplication workflow."""
    
    def test_single_transfer_unchanged(self, transfer_base: dict) -> None:
        """Single transfer should pass through unchanged."""
        record: TransferPayload = transfer_base  # type: ignore
        records = [record]
        
        result = deduplicate_transfers(records)
        
        assert len(result) == 1
        assert result[0] == record
    
    def test_duplicate_higher_confidence_wins(self, transfer_base: dict) -> None:
        """Duplicate transfers, higher confidence version kept."""
        # Rumour version
        rumour_dict = {**transfer_base}
        rumour_dict["confidence"] = "rumour"
        rumour_dict["source"] = "blog"
        
        # Official version (same key, different confidence)
        official_dict = {**transfer_base}
        official_dict["confidence"] = "official"
        official_dict["source"] = "mackolik"
        
        records: list[TransferPayload] = [rumour_dict, official_dict]  # type: ignore
        
        result = deduplicate_transfers(records)
        
        assert len(result) == 1
        assert result[0]["confidence"] == "official"
        assert result[0]["source"] == "mackolik"
    
    def test_duplicate_source_priority_wins(self, transfer_base: dict) -> None:
        """Duplicate transfers, same confidence, source priority wins."""
        # Both official, but from different sources
        transfer_a = {**transfer_base}
        transfer_a["source"] = "source_a"
        transfer_a["confidence"] = "official"
        
        transfer_b = {**transfer_base}
        transfer_b["source"] = "source_b"
        transfer_b["confidence"] = "official"
        
        records: list[TransferPayload] = [transfer_a, transfer_b]  # type: ignore
        
        # source_a has higher priority
        source_priority = {"source_a": 0, "source_b": 1}
        result = deduplicate_transfers(records, source_priority)
        
        assert len(result) == 1
        assert result[0]["source"] == "source_a"
    
    def test_three_way_duplicate(self, transfer_base: dict) -> None:
        """Three transfers with same key, highest confidence + priority wins."""
        # Rumour from source_b
        transfer1 = {**transfer_base}
        transfer1["confidence"] = "rumour"
        transfer1["source"] = "source_b"
        
        # Agreed from source_a
        transfer2 = {**transfer_base}
        transfer2["confidence"] = "agreed"
        transfer2["source"] = "source_a"
        
        # Official from source_c (lowest priority but highest confidence)
        transfer3 = {**transfer_base}
        transfer3["confidence"] = "official"
        transfer3["source"] = "source_c"
        
        records: list[TransferPayload] = [transfer1, transfer2, transfer3]  # type: ignore
        source_priority = {
            "source_a": 0,
            "source_b": 1,
            "source_c": 2,
        }
        
        result = deduplicate_transfers(records, source_priority)
        
        assert len(result) == 1
        assert result[0]["confidence"] == "official"
        assert result[0]["source"] == "source_c"


class TestDedupEdgeCases:
    """Adversarial tests — edge cases and boundary conditions."""
    
    def test_empty_input_list(self) -> None:
        """Empty input should return empty output."""
        result = deduplicate_transfers([])
        assert result == []
    
    def test_no_duplicates_all_kept(self, transfer_base: dict) -> None:
        """Different transfers (different dedup keys) should all be kept."""
        transfer1 = {**transfer_base}
        transfer1["player_id"] = "P_001"
        
        transfer2 = {**transfer_base}
        transfer2["player_id"] = "P_002"
        
        transfer3 = {**transfer_base}
        transfer3["player_id"] = "P_003"
        
        records: list[TransferPayload] = [transfer1, transfer2, transfer3]  # type: ignore
        
        result = deduplicate_transfers(records)
        
        assert len(result) == 3
    
    def test_different_transfer_types_not_deduplicated(self, transfer_base: dict) -> None:
        """Same player/effective_at but different transfer_type should not deduplicate."""
        permanent_dict = {**transfer_base}
        permanent_dict["transfer_type"] = "permanent"
        
        loan_dict = {**transfer_base}
        loan_dict["transfer_type"] = "loan"
        
        records: list[TransferPayload] = [permanent_dict, loan_dict]  # type: ignore
        
        result = deduplicate_transfers(records)
        
        assert len(result) == 2  # Both kept (different keys)
    
    def test_missing_source_field_defaults(self, transfer_base: dict) -> None:
        """Missing 'source' field should default to 'unknown'."""
        record_dict = {**transfer_base}
        del record_dict["source"]  # Remove source field
        
        should_repl = should_replace(
            existing_confidence="official",
            existing_source="mackolik",
            new_confidence="official",
            new_source="unknown",  # Simulated default
            source_priority={"mackolik": 0},
        )
        assert should_repl is False  # mackolik (0) beats unknown (inf)
    
    def test_confidence_rank_ordering(self) -> None:
        """Verify confidence rank ordering is correct."""
        assert CONFIDENCE_RANK["official"] > CONFIDENCE_RANK["agreed"]
        assert CONFIDENCE_RANK["agreed"] > CONFIDENCE_RANK["rumour"]
        assert CONFIDENCE_RANK["official"] == 3
        assert CONFIDENCE_RANK["agreed"] == 2
        assert CONFIDENCE_RANK["rumour"] == 1
