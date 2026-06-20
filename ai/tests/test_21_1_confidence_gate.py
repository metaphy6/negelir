"""Phase 21.1 §21.1 — Confidence gate tests.

Tests for rumour/agreed/official confidence gate enforcement:
  - Rumours do not write to roster-state
  - Agreed records write with provisional=true flag
  - Official records write as final; clear provisional on earlier agreed
  - Missing confidence field raises ValueError
  - Unknown confidence levels rejected

Per ROADMAP §21.1 bullet 4 and ENRICHMENT_DATA.md §2.4.
Minimum 8 tests including ≥ 2 adversarial.
"""

from __future__ import annotations

import pytest

from ai.scraper.differs.transfers_feed.confidence_gate import (
    should_write,
    get_write_mode,
    apply_gate,
    RosterStateWriteInstruction,
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
    }


class TestConfidenceGateRumour:
    """Tests for rumour confidence level — no roster-state write."""
    
    def test_rumour_should_not_write(self, transfer_base: dict) -> None:
        """Rumours should not be written to roster-state."""
        record: TransferPayload = {**transfer_base, "confidence": "rumour"}  # type: ignore
        assert should_write(record) is False
    
    def test_rumour_write_mode_is_no_write(self, transfer_base: dict) -> None:
        """Rumour write mode indicates no roster-state write."""
        record: TransferPayload = {**transfer_base, "confidence": "rumour"}  # type: ignore
        mode = get_write_mode(record)
        
        assert mode["should_write"] is False
        assert mode["provisional"] is False
        assert mode["clear_provisional_for_player"] is None
        assert mode["confidence_level"] == "rumour"


class TestConfidenceGateAgreed:
    """Tests for agreed confidence level — provisional roster-state write."""
    
    def test_agreed_should_write(self, transfer_base: dict) -> None:
        """Agreed transfers should be written to roster-state."""
        record: TransferPayload = {**transfer_base, "confidence": "agreed"}  # type: ignore
        assert should_write(record) is True
    
    def test_agreed_write_mode_is_provisional(self, transfer_base: dict) -> None:
        """Agreed write mode indicates provisional roster-state write."""
        record: TransferPayload = {**transfer_base, "confidence": "agreed"}  # type: ignore
        mode = get_write_mode(record)
        
        assert mode["should_write"] is True
        assert mode["provisional"] is True
        assert mode["clear_provisional_for_player"] is None
        assert mode["confidence_level"] == "agreed"


class TestConfidenceGateOfficial:
    """Tests for official confidence level — final write, clear provisional."""
    
    def test_official_should_write(self, transfer_base: dict) -> None:
        """Official transfers should be written to roster-state."""
        record: TransferPayload = {**transfer_base, "confidence": "official"}  # type: ignore
        assert should_write(record) is True
    
    def test_official_write_mode_is_final(self, transfer_base: dict) -> None:
        """Official write mode indicates final roster-state write."""
        record: TransferPayload = {**transfer_base, "confidence": "official"}  # type: ignore
        mode = get_write_mode(record)
        
        assert mode["should_write"] is True
        assert mode["provisional"] is False
        assert mode["confidence_level"] == "official"
    
    def test_official_clears_provisional_for_same_player(self, transfer_base: dict) -> None:
        """Official record should clear provisional on same player."""
        record: TransferPayload = {**transfer_base, "confidence": "official"}  # type: ignore
        mode = get_write_mode(record)
        
        assert mode["clear_provisional_for_player"] == "P_100"
    
    def test_official_uses_correct_player_id(self, transfer_base: dict) -> None:
        """Clear provisional uses the correct player_id from record."""
        transfer_base["player_id"] = "P_999"
        record: TransferPayload = {**transfer_base, "confidence": "official"}  # type: ignore
        mode = get_write_mode(record)
        
        assert mode["clear_provisional_for_player"] == "P_999"


class TestConfidenceGateApplyGate:
    """Tests for the apply_gate() main entry point."""
    
    def test_apply_gate_rumour(self, transfer_base: dict) -> None:
        """apply_gate() with rumour should match get_write_mode()."""
        record: TransferPayload = {**transfer_base, "confidence": "rumour"}  # type: ignore
        instruction = apply_gate(record)
        
        assert instruction["should_write"] is False
        assert instruction["confidence_level"] == "rumour"
    
    def test_apply_gate_agreed(self, transfer_base: dict) -> None:
        """apply_gate() with agreed should match get_write_mode()."""
        record: TransferPayload = {**transfer_base, "confidence": "agreed"}  # type: ignore
        instruction = apply_gate(record)
        
        assert instruction["should_write"] is True
        assert instruction["provisional"] is True
        assert instruction["confidence_level"] == "agreed"
    
    def test_apply_gate_official(self, transfer_base: dict) -> None:
        """apply_gate() with official should match get_write_mode()."""
        record: TransferPayload = {**transfer_base, "confidence": "official"}  # type: ignore
        instruction = apply_gate(record)
        
        assert instruction["should_write"] is True
        assert instruction["provisional"] is False
        assert instruction["clear_provisional_for_player"] == "P_100"


class TestConfidenceGateErrorHandling:
    """Adversarial tests — error cases and edge conditions."""
    
    def test_missing_confidence_field_raises_error(self, transfer_base: dict) -> None:
        """Record without confidence field should raise ValueError."""
        record_dict = {k: v for k, v in transfer_base.items() if k != "confidence"}
        
        with pytest.raises(ValueError, match="missing required 'confidence' field"):
            apply_gate(record_dict)  # type: ignore
    
    def test_unknown_confidence_level_raises_error(self, transfer_base: dict) -> None:
        """Unknown confidence level should raise ValueError."""
        record: TransferPayload = {**transfer_base, "confidence": "unknown"}  # type: ignore
        
        with pytest.raises(ValueError, match="Unknown confidence level"):
            get_write_mode(record)
    
    def test_none_confidence_level_raises_error(self, transfer_base: dict) -> None:
        """None confidence level should raise ValueError."""
        record = {**transfer_base}
        record["confidence"] = None  # type: ignore
        
        with pytest.raises(ValueError):
            get_write_mode(record)  # type: ignore


class TestConfidenceGateWorkflow:
    """Integration tests — real-world workflow scenarios."""
    
    def test_workflow_rumour_to_agreed_to_official(self, transfer_base: dict) -> None:
        """Test complete workflow: rumour → agreed → official."""
        # Step 1: Rumour arrives — no roster-state write
        rumour: TransferPayload = {**transfer_base, "confidence": "rumour"}  # type: ignore
        mode_r = apply_gate(rumour)
        assert mode_r["should_write"] is False
        
        # Step 2: Same transfer confirmed as agreed — provisional write
        agreed: TransferPayload = {**transfer_base, "confidence": "agreed"}  # type: ignore
        mode_a = apply_gate(agreed)
        assert mode_a["should_write"] is True
        assert mode_a["provisional"] is True
        
        # Step 3: Same transfer confirmed as official — final write, clear provisional
        official: TransferPayload = {**transfer_base, "confidence": "official"}  # type: ignore
        mode_o = apply_gate(official)
        assert mode_o["should_write"] is True
        assert mode_o["provisional"] is False
        assert mode_o["clear_provisional_for_player"] == "P_100"
    
    def test_multiple_players_independent_provisional_flags(self) -> None:
        """Multiple players should have independent provisional status."""
        base = {
            "transfer_id": "T_001",
            "from_team_id": "TEAM_A",
            "to_team_id": "TEAM_B",
            "transfer_window": "summer",
            "transfer_type": "permanent",
            "fee_eur": 1_000_000,
            "contract_until": "2028-06-30",
            "announced_at": "2026-06-01T10:00:00Z",
            "effective_at": "2026-06-15T00:00:00Z",
        }
        
        # Player 1 official
        transfer_p1: TransferPayload = {**base, "player_id": "P_001", "confidence": "official"}  # type: ignore
        mode_p1 = apply_gate(transfer_p1)
        assert mode_p1["clear_provisional_for_player"] == "P_001"
        
        # Player 2 official
        transfer_p2: TransferPayload = {**base, "player_id": "P_002", "confidence": "official"}  # type: ignore
        mode_p2 = apply_gate(transfer_p2)
        assert mode_p2["clear_provisional_for_player"] == "P_002"
        
        # Both should have independently set clear_provisional_for_player
        assert mode_p1["clear_provisional_for_player"] != mode_p2["clear_provisional_for_player"]
