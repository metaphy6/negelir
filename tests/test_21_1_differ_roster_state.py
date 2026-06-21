"""Phase 21.1 §21.1 — Roster-state differ tests.

Tests for TransferDiffer, ContractDiffer, SuspensionDiffer:
  - Idempotency: comparing identical records produces identical DiffEvent
  - Change detection: emits DiffEvent only when fields change
  - Key correctness: (player_id, effective_at, confidence) for transfers
  - Adversarial: edge cases, null handling, concurrent fetches

Per ROADMAP §21.1:
  - Test name: test_21_1_differ_roster_state.py
  - Minimum 8 tests including ≥ 2 adversarial
"""

from __future__ import annotations

import time
from datetime import datetime

import pytest

from datasource.scraper.differs.transfers_feed import (
    TransferDiffer,
    ContractDiffer,
    SuspensionDiffer,
    DiffEvent,
)
from common.schemas.records import (
    TransferPayload,
    ContractPayload,
    SuspensionPayload,
)


class TestTransferDiffer:
    """Tests for TransferDiffer idempotency and change detection."""

    @pytest.fixture
    def differ(self) -> TransferDiffer:
        """Create a TransferDiffer instance."""
        return TransferDiffer(source="mackolik")

    @pytest.fixture
    def transfer_payload_v1(self) -> TransferPayload:
        """First version of a transfer payload."""
        return {
            "transfer_id": "T_001",
            "player_id": "P_100",
            "from_team_id": "TEAM_A",
            "to_team_id": "TEAM_B",
            "transfer_window": "summer",
            "transfer_type": "permanent",
            "fee_eur": 5000000,
            "contract_until": "2028-06-30",
            "announced_at": "2026-06-20T10:00:00Z",
            "effective_at": "2026-06-20T10:00:00Z",
            "confidence": "official",
        }

    @pytest.fixture
    def transfer_payload_v2_fee_change(self, transfer_payload_v1: TransferPayload) -> TransferPayload:
        """Second version with fee change (field change)."""
        payload = dict(transfer_payload_v1)  # type: ignore
        payload["fee_eur"] = 5500000
        return payload  # type: ignore

    def test_transfer_differ_no_event_on_identical_refetch(
        self, differ: TransferDiffer, transfer_payload_v1: TransferPayload
    ) -> None:
        """Idempotency: comparing identical transfers produces no diff (None returned)."""
        # First comparison: None -> v1 = created
        event1 = differ.compare(None, transfer_payload_v1)
        assert event1 is not None
        assert event1["change_type"] == "created"

        # Second comparison: v1 -> v1 = no change (None returned)
        event2 = differ.compare(transfer_payload_v1, transfer_payload_v1)
        assert event2 is None

        # Third comparison: same payloads but different dict instances
        # Should still return None (idempotent on identical data)
        transfer_payload_v1_copy = dict(transfer_payload_v1)  # type: ignore
        event3 = differ.compare(transfer_payload_v1, transfer_payload_v1_copy)  # type: ignore
        assert event3 is None

    def test_transfer_differ_emits_event_on_field_change(
        self,
        differ: TransferDiffer,
        transfer_payload_v1: TransferPayload,
        transfer_payload_v2_fee_change: TransferPayload,
    ) -> None:
        """Happy path: differ emits DiffEvent when a field changes."""
        event = differ.compare(transfer_payload_v1, transfer_payload_v2_fee_change)
        
        assert event is not None
        assert event["change_type"] == "updated"
        assert event["source"] == "mackolik"
        assert event["entity_type"] == "transfer"
        assert event["old_record"] == transfer_payload_v1
        assert event["new_record"] == transfer_payload_v2_fee_change
        # Key should remain the same (change is not in key fields)
        assert event["key_tuple"] == (
            transfer_payload_v1["player_id"],
            transfer_payload_v1["effective_at"],
            transfer_payload_v1["confidence"],
        )

    def test_transfer_differ_key_includes_player_id_effective_at_confidence(
        self, differ: TransferDiffer, transfer_payload_v1: TransferPayload
    ) -> None:
        """Key correctness: key tuple is (player_id, effective_at, confidence)."""
        event = differ.compare(None, transfer_payload_v1)
        
        assert event is not None
        # Key should be exactly (player_id, effective_at, confidence)
        assert event["key_tuple"] == (
            "P_100",
            "2026-06-20T10:00:00Z",
            "official",
        )

    def test_transfer_differ_emits_on_new_transfer(
        self, differ: TransferDiffer, transfer_payload_v1: TransferPayload
    ) -> None:
        """Differ emits 'created' when comparing None -> new_transfer."""
        event = differ.compare(None, transfer_payload_v1)
        
        assert event is not None
        assert event["change_type"] == "created"
        assert event["old_record"] is None
        assert event["new_record"] == transfer_payload_v1

    def test_transfer_differ_emits_on_deleted_transfer(
        self, differ: TransferDiffer, transfer_payload_v1: TransferPayload
    ) -> None:
        """Differ emits 'deleted' when comparing old_transfer -> None."""
        event = differ.compare(transfer_payload_v1, None)
        
        assert event is not None
        assert event["change_type"] == "deleted"
        assert event["old_record"] == transfer_payload_v1
        assert event["new_record"] is None

    def test_transfer_differ_timestamp_iso_format(
        self, differ: TransferDiffer, transfer_payload_v1: TransferPayload
    ) -> None:
        """Diff event timestamp is ISO-8601 UTC format."""
        event = differ.compare(None, transfer_payload_v1)
        
        assert event is not None
        # Should be ISO-8601 UTC (either 'Z' suffix or '+00:00')
        timestamp = event["timestamp"]
        assert timestamp.endswith("Z") or timestamp.endswith("+00:00")
        # Should parse without error
        # Remove 'Z' suffix if present and use fromisoformat
        ts_str = timestamp.replace("Z", "+00:00")
        datetime.fromisoformat(ts_str)

    # Adversarial tests
    def test_transfer_differ_handles_null_optional_fields(
        self, differ: TransferDiffer
    ) -> None:
        """Adversarial: differ handles None in optional fields (from_team_id, to_team_id, fee_eur, etc.)."""
        transfer_with_nulls: TransferPayload = {
            "transfer_id": "T_002",
            "player_id": "P_101",
            "from_team_id": None,  # nullable
            "to_team_id": None,  # nullable (retirement)
            "transfer_window": "summer",
            "transfer_type": "free",
            "fee_eur": None,  # nullable
            "contract_until": None,  # nullable
            "announced_at": "2026-06-20T10:00:00Z",
            "effective_at": "2026-06-20T10:00:00Z",
            "confidence": "rumour",
        }
        
        # Should not raise; should handle None values correctly
        event = differ.compare(None, transfer_with_nulls)
        assert event is not None
        assert event["new_record"]["to_team_id"] is None
        assert event["new_record"]["fee_eur"] is None

    def test_transfer_differ_concurrent_identical_refetch_idempotent(
        self, differ: TransferDiffer, transfer_payload_v1: TransferPayload
    ) -> None:
        """Adversarial: concurrent identical re-fetches are idempotent.
        
        Simulates two concurrent fetches of the same transfer record:
        they should both produce no diff when compared to the stored version.
        """
        # Store: old -> new
        event_first_fetch = differ.compare(None, transfer_payload_v1)
        assert event_first_fetch is not None

        # Concurrent second fetch: compare stored to newly fetched (identical)
        event_concurrent = differ.compare(transfer_payload_v1, transfer_payload_v1)
        assert event_concurrent is None

        # Concurrent third fetch: same result
        event_concurrent_2 = differ.compare(transfer_payload_v1, transfer_payload_v1)
        assert event_concurrent_2 is None


class TestContractDiffer:
    """Tests for ContractDiffer."""

    @pytest.fixture
    def differ(self) -> ContractDiffer:
        """Create a ContractDiffer instance."""
        return ContractDiffer(source="club_site")

    @pytest.fixture
    def contract_payload_v1(self) -> ContractPayload:
        """First version of a contract payload."""
        return {
            "contract_id": "C_001",
            "player_id": "P_100",
            "team_id": "TEAM_A",
            "starts_at": "2024-07-01",
            "expires_at": "2026-06-30",
            "extension": False,
        }

    def test_contract_differ_detects_extension_flag_change(
        self, differ: ContractDiffer, contract_payload_v1: ContractPayload
    ) -> None:
        """Contract-specific: detect extension flag changes."""
        # Original contract
        event_created = differ.compare(None, contract_payload_v1)
        assert event_created is not None

        # Extended contract
        extended: ContractPayload = {
            "contract_id": "C_001",
            "player_id": "P_100",
            "team_id": "TEAM_A",
            "starts_at": "2024-07-01",
            "expires_at": "2027-06-30",  # extended expiry
            "extension": True,  # flag set
        }

        event_extended = differ.compare(contract_payload_v1, extended)
        assert event_extended is not None
        assert event_extended["change_type"] == "updated"
        assert event_extended["old_record"]["extension"] is False
        assert event_extended["new_record"]["extension"] is True


class TestSuspensionDiffer:
    """Tests for SuspensionDiffer."""

    @pytest.fixture
    def differ(self) -> SuspensionDiffer:
        """Create a SuspensionDiffer instance."""
        return SuspensionDiffer(source="official")

    @pytest.fixture
    def suspension_payload_v1(self) -> SuspensionPayload:
        """First version of a suspension payload."""
        return {
            "suspension_id": "S_001",
            "player_id": "P_200",
            "team_id": "TEAM_A",
            "competition_id": "COMP_001",
            "reason": "accumulated_yellows",
            "matches_remaining": 2,
            "starts_at": "2026-06-21",
            "expires_after_match_id": "M_999",
        }

    def test_suspension_differ_tracks_matches_remaining_change(
        self, differ: SuspensionDiffer, suspension_payload_v1: SuspensionPayload
    ) -> None:
        """Suspension-specific: track matches_remaining changes."""
        event_created = differ.compare(None, suspension_payload_v1)
        assert event_created is not None

        # After one match, matches_remaining decremented by post-match reactor
        suspension_v2: SuspensionPayload = {
            "suspension_id": "S_001",
            "player_id": "P_200",
            "team_id": "TEAM_A",
            "competition_id": "COMP_001",
            "reason": "accumulated_yellows",
            "matches_remaining": 1,  # decremented
            "starts_at": "2026-06-21",
            "expires_after_match_id": "M_999",
        }

        event_decremented = differ.compare(suspension_payload_v1, suspension_v2)
        assert event_decremented is not None
        assert event_decremented["change_type"] == "updated"
        assert event_decremented["old_record"]["matches_remaining"] == 2
        assert event_decremented["new_record"]["matches_remaining"] == 1


class TestDifferErrorHandling:
    """Error handling and edge cases."""

    def test_transfer_differ_raises_on_both_none(self) -> None:
        """Differ raises ValueError when both payloads are None."""
        differ = TransferDiffer(source="test")
        
        with pytest.raises(ValueError, match="Both.*cannot be None"):
            differ.compare(None, None)

    def test_contract_differ_key_tuple_structure(self) -> None:
        """Verify contract differ key tuple is (player_id, team_id, contract_id)."""
        differ = ContractDiffer(source="test")
        contract: ContractPayload = {
            "contract_id": "C_123",
            "player_id": "P_456",
            "team_id": "T_789",
            "starts_at": "2024-01-01",
            "expires_at": "2026-01-01",
            "extension": False,
        }

        event = differ.compare(None, contract)
        assert event is not None
        assert event["key_tuple"] == ("P_456", "T_789", "C_123")

    def test_suspension_differ_key_tuple_structure(self) -> None:
        """Verify suspension differ key tuple is (player_id, competition_id, suspension_id)."""
        differ = SuspensionDiffer(source="test")
        suspension: SuspensionPayload = {
            "suspension_id": "S_111",
            "player_id": "P_222",
            "team_id": "T_333",
            "competition_id": "COMP_444",
            "reason": "red",
            "matches_remaining": 3,
            "starts_at": "2026-06-21",
            "expires_after_match_id": None,
        }

        event = differ.compare(None, suspension)
        assert event is not None
        assert event["key_tuple"] == ("P_222", "COMP_444", "S_111")
