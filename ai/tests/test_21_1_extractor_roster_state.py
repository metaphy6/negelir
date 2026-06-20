"""Phase 21.1 — Roster-state extractor tests (happy path + adversarial).

Tests for TransferExtractor, ContractExtractor, SuspensionExtractor.
Covers: Mackolik JSON parsing, club HTML extraction, error handling,
string field capping, date validation.
"""

from __future__ import annotations

import pytest
from datetime import datetime

from ai.scraper.extractors.transfers_feed import (
    TransferExtractor,
    ContractExtractor,
    SuspensionExtractor,
    ExtractionError,
)


class TestTransferExtractor:
    """Tests for TransferExtractor."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.extractor = TransferExtractor(max_string_length=500)

    def test_extract_valid_transfer_from_mackolik_json(self) -> None:
        """Happy path: parse valid transfer from Mackolik JSON."""
        data = {
            "transfers": [
                {
                    "id": "TR_12345",
                    "player_id": "P_67890",
                    "from_team_id": "TEAM_FB",
                    "to_team_id": "TEAM_GS",
                    "window": "summer",
                    "type": "permanent",
                    "fee_eur": 10_000_000,
                    "contract_until": "2026-06-30",
                    "announced_at": "2026-06-20T10:30:00Z",
                    "effective_at": "2026-06-20T10:30:00Z",
                    "confidence": "official",
                }
            ]
        }

        results = self.extractor.extract_from_mackolik_json(data)

        assert len(results) == 1
        payload = results[0]
        assert payload["transfer_id"] == "TR_12345"
        assert payload["player_id"] == "P_67890"
        assert payload["from_team_id"] == "TEAM_FB"
        assert payload["to_team_id"] == "TEAM_GS"
        assert payload["transfer_window"] == "summer"
        assert payload["transfer_type"] == "permanent"
        assert payload["fee_eur"] == 10_000_000
        assert payload["contract_until"] == "2026-06-30"
        assert payload["confidence"] == "official"

    def test_extract_transfer_with_null_fee(self) -> None:
        """Happy path: transfer with undisclosed fee (null)."""
        data = {
            "transfers": [
                {
                    "id": "TR_12345",
                    "player_id": "P_67890",
                    "from_team_id": "TEAM_FB",
                    "to_team_id": "TEAM_GS",
                    "window": "summer",
                    "type": "free",
                    "fee_eur": None,
                    "contract_until": None,
                    "announced_at": "2026-06-20T10:30:00Z",
                    "effective_at": "2026-06-20T10:30:00Z",
                    "confidence": "rumour",
                }
            ]
        }

        results = self.extractor.extract_from_mackolik_json(data)

        assert len(results) == 1
        assert results[0]["fee_eur"] is None
        assert results[0]["contract_until"] is None
        assert results[0]["confidence"] == "rumour"

    def test_extract_transfer_first_pro_contract(self) -> None:
        """Happy path: first pro contract (from_team_id null)."""
        data = {
            "transfers": [
                {
                    "id": "TR_12345",
                    "player_id": "P_67890",
                    "from_team_id": None,
                    "to_team_id": "TEAM_GS",
                    "window": "summer",
                    "type": "permanent",
                    "fee_eur": None,
                    "contract_until": "2027-06-30",
                    "announced_at": "2026-06-20T10:30:00Z",
                    "effective_at": "2026-06-20T10:30:00Z",
                    "confidence": "official",
                }
            ]
        }

        results = self.extractor.extract_from_mackolik_json(data)

        assert len(results) == 1
        assert results[0]["from_team_id"] is None
        assert results[0]["to_team_id"] == "TEAM_GS"

    def test_extract_transfer_retirement(self) -> None:
        """Happy path: retirement (to_team_id null)."""
        data = {
            "transfers": [
                {
                    "id": "TR_12345",
                    "player_id": "P_67890",
                    "from_team_id": "TEAM_GS",
                    "to_team_id": None,
                    "window": "summer",
                    "type": "permanent",
                    "fee_eur": None,
                    "contract_until": None,
                    "announced_at": "2026-06-20T10:30:00Z",
                    "effective_at": "2026-06-20T10:30:00Z",
                    "confidence": "official",
                }
            ]
        }

        results = self.extractor.extract_from_mackolik_json(data)

        assert len(results) == 1
        assert results[0]["from_team_id"] == "TEAM_GS"
        assert results[0]["to_team_id"] is None

    def test_extract_multiple_transfers(self) -> None:
        """Happy path: extract multiple transfers in one payload."""
        data = {
            "transfers": [
                {
                    "id": "TR_1",
                    "player_id": "P_1",
                    "from_team_id": "TEAM_A",
                    "to_team_id": "TEAM_B",
                    "window": "summer",
                    "type": "permanent",
                    "fee_eur": 5_000_000,
                    "contract_until": "2026-06-30",
                    "announced_at": "2026-06-20T10:30:00Z",
                    "effective_at": "2026-06-20T10:30:00Z",
                    "confidence": "official",
                },
                {
                    "id": "TR_2",
                    "player_id": "P_2",
                    "from_team_id": "TEAM_C",
                    "to_team_id": "TEAM_D",
                    "window": "winter",
                    "type": "loan",
                    "fee_eur": None,
                    "contract_until": "2027-06-30",
                    "announced_at": "2026-01-15T14:00:00Z",
                    "effective_at": "2026-01-15T14:00:00Z",
                    "confidence": "agreed",
                },
            ]
        }

        results = self.extractor.extract_from_mackolik_json(data)

        assert len(results) == 2
        assert results[0]["transfer_id"] == "TR_1"
        assert results[1]["transfer_id"] == "TR_2"

    def test_string_field_capping(self) -> None:
        """Happy path: long string fields are capped."""
        long_string = "x" * 1000
        data = {
            "transfers": [
                {
                    "id": long_string,
                    "player_id": long_string,
                    "from_team_id": long_string,
                    "to_team_id": long_string,
                    "window": "summer",
                    "type": "permanent",
                    "fee_eur": None,
                    "contract_until": None,
                    "announced_at": "2026-06-20T10:30:00Z",
                    "effective_at": "2026-06-20T10:30:00Z",
                    "confidence": "official",
                }
            ]
        }

        results = self.extractor.extract_from_mackolik_json(data)

        assert len(results) == 1
        payload = results[0]
        assert len(payload["transfer_id"]) == 500
        assert len(payload["player_id"]) == 500
        assert len(payload["from_team_id"]) == 500
        assert len(payload["to_team_id"]) == 500

    # Adversarial tests

    def test_missing_required_field_id_raises_error(self) -> None:
        """Adversarial: missing 'id' field raises ExtractionError."""
        data = {
            "transfers": [
                {
                    # missing "id"
                    "player_id": "P_67890",
                    "from_team_id": "TEAM_FB",
                    "to_team_id": "TEAM_GS",
                    "window": "summer",
                    "type": "permanent",
                    "fee_eur": None,
                    "contract_until": None,
                    "announced_at": "2026-06-20T10:30:00Z",
                    "effective_at": "2026-06-20T10:30:00Z",
                    "confidence": "official",
                }
            ]
        }

        with pytest.raises(ExtractionError, match="missing required field: id"):
            self.extractor.extract_from_mackolik_json(data)

    def test_wrong_type_window_raises_error(self) -> None:
        """Adversarial: wrong type for 'window' field."""
        data = {
            "transfers": [
                {
                    "id": "TR_12345",
                    "player_id": "P_67890",
                    "from_team_id": "TEAM_FB",
                    "to_team_id": "TEAM_GS",
                    "window": 123,  # Should be string
                    "type": "permanent",
                    "fee_eur": None,
                    "contract_until": None,
                    "announced_at": "2026-06-20T10:30:00Z",
                    "effective_at": "2026-06-20T10:30:00Z",
                    "confidence": "official",
                }
            ]
        }

        with pytest.raises(ExtractionError, match="has wrong type"):
            self.extractor.extract_from_mackolik_json(data)

    def test_invalid_window_value_raises_error(self) -> None:
        """Adversarial: invalid window value raises ExtractionError."""
        data = {
            "transfers": [
                {
                    "id": "TR_12345",
                    "player_id": "P_67890",
                    "from_team_id": "TEAM_FB",
                    "to_team_id": "TEAM_GS",
                    "window": "autumn",  # Invalid (must be summer/winter/emergency)
                    "type": "permanent",
                    "fee_eur": None,
                    "contract_until": None,
                    "announced_at": "2026-06-20T10:30:00Z",
                    "effective_at": "2026-06-20T10:30:00Z",
                    "confidence": "official",
                }
            ]
        }

        with pytest.raises(ExtractionError, match="invalid window value"):
            self.extractor.extract_from_mackolik_json(data)

    def test_invalid_transfer_type_raises_error(self) -> None:
        """Adversarial: invalid transfer type raises ExtractionError."""
        data = {
            "transfers": [
                {
                    "id": "TR_12345",
                    "player_id": "P_67890",
                    "from_team_id": "TEAM_FB",
                    "to_team_id": "TEAM_GS",
                    "window": "summer",
                    "type": "partial_loan",  # Invalid type
                    "fee_eur": None,
                    "contract_until": None,
                    "announced_at": "2026-06-20T10:30:00Z",
                    "effective_at": "2026-06-20T10:30:00Z",
                    "confidence": "official",
                }
            ]
        }

        with pytest.raises(ExtractionError, match="invalid transfer type"):
            self.extractor.extract_from_mackolik_json(data)

    def test_invalid_confidence_raises_error(self) -> None:
        """Adversarial: invalid confidence value raises ExtractionError."""
        data = {
            "transfers": [
                {
                    "id": "TR_12345",
                    "player_id": "P_67890",
                    "from_team_id": "TEAM_FB",
                    "to_team_id": "TEAM_GS",
                    "window": "summer",
                    "type": "permanent",
                    "fee_eur": None,
                    "contract_until": None,
                    "announced_at": "2026-06-20T10:30:00Z",
                    "effective_at": "2026-06-20T10:30:00Z",
                    "confidence": "uncertain",  # Invalid (must be rumour/agreed/official)
                }
            ]
        }

        with pytest.raises(ExtractionError, match="invalid confidence value"):
            self.extractor.extract_from_mackolik_json(data)

    def test_malformed_iso_date_raises_error(self) -> None:
        """Adversarial: malformed ISO date raises ExtractionError."""
        data = {
            "transfers": [
                {
                    "id": "TR_12345",
                    "player_id": "P_67890",
                    "from_team_id": "TEAM_FB",
                    "to_team_id": "TEAM_GS",
                    "window": "summer",
                    "type": "permanent",
                    "fee_eur": None,
                    "contract_until": None,
                    "announced_at": "20/06/2026 10:30",  # Wrong format
                    "effective_at": "2026-06-20T10:30:00Z",
                    "confidence": "official",
                }
            ]
        }

        with pytest.raises(ExtractionError, match="invalid ISO date format"):
            self.extractor.extract_from_mackolik_json(data)

    def test_invalid_contract_until_date_raises_error(self) -> None:
        """Adversarial: malformed contract_until date raises ExtractionError."""
        data = {
            "transfers": [
                {
                    "id": "TR_12345",
                    "player_id": "P_67890",
                    "from_team_id": "TEAM_FB",
                    "to_team_id": "TEAM_GS",
                    "window": "summer",
                    "type": "permanent",
                    "fee_eur": None,
                    "contract_until": "30-06-2026",  # Wrong date format
                    "announced_at": "2026-06-20T10:30:00Z",
                    "effective_at": "2026-06-20T10:30:00Z",
                    "confidence": "official",
                }
            ]
        }

        with pytest.raises(ExtractionError, match="contract_until has invalid date format"):
            self.extractor.extract_from_mackolik_json(data)

    def test_non_integer_fee_raises_error(self) -> None:
        """Adversarial: non-integer fee_eur raises ExtractionError."""
        data = {
            "transfers": [
                {
                    "id": "TR_12345",
                    "player_id": "P_67890",
                    "from_team_id": "TEAM_FB",
                    "to_team_id": "TEAM_GS",
                    "window": "summer",
                    "type": "permanent",
                    "fee_eur": "10 million",  # Should be int or null
                    "contract_until": None,
                    "announced_at": "2026-06-20T10:30:00Z",
                    "effective_at": "2026-06-20T10:30:00Z",
                    "confidence": "official",
                }
            ]
        }

        with pytest.raises(ExtractionError, match="fee_eur must be int or null"):
            self.extractor.extract_from_mackolik_json(data)

    def test_transfers_not_list_raises_error(self) -> None:
        """Adversarial: transfers field is not a list."""
        data = {"transfers": {"id": "TR_1"}}  # Should be a list

        with pytest.raises(ExtractionError, match="transfers field must be a list"):
            self.extractor.extract_from_mackolik_json(data)


class TestContractExtractor:
    """Tests for ContractExtractor."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.extractor = ContractExtractor(max_string_length=500)

    def test_extract_valid_contract(self) -> None:
        """Happy path: parse valid contract."""
        data = {
            "contracts": [
                {
                    "id": "C_12345",
                    "player_id": "P_67890",
                    "team_id": "TEAM_FB",
                    "starts_at": "2024-07-01",
                    "expires_at": "2026-06-30",
                    "extension": False,
                }
            ]
        }

        results = self.extractor.extract_from_json(data)

        assert len(results) == 1
        payload = results[0]
        assert payload["contract_id"] == "C_12345"
        assert payload["player_id"] == "P_67890"
        assert payload["team_id"] == "TEAM_FB"
        assert payload["starts_at"] == "2024-07-01"
        assert payload["expires_at"] == "2026-06-30"
        assert payload["extension"] is False

    def test_extract_contract_extension(self) -> None:
        """Happy path: parse contract extension."""
        data = {
            "contracts": [
                {
                    "id": "C_12346",
                    "player_id": "P_67890",
                    "team_id": "TEAM_FB",
                    "starts_at": "2024-07-01",
                    "expires_at": "2027-06-30",
                    "extension": True,
                }
            ]
        }

        results = self.extractor.extract_from_json(data)

        assert len(results) == 1
        assert results[0]["extension"] is True

    def test_missing_contract_field_raises_error(self) -> None:
        """Adversarial: missing required contract field."""
        data = {
            "contracts": [
                {
                    "id": "C_12345",
                    "player_id": "P_67890",
                    # missing team_id
                    "starts_at": "2024-07-01",
                    "expires_at": "2026-06-30",
                    "extension": False,
                }
            ]
        }

        with pytest.raises(ExtractionError, match="missing required field: team_id"):
            self.extractor.extract_from_json(data)

    def test_invalid_date_contract_raises_error(self) -> None:
        """Adversarial: invalid date format in contract."""
        data = {
            "contracts": [
                {
                    "id": "C_12345",
                    "player_id": "P_67890",
                    "team_id": "TEAM_FB",
                    "starts_at": "01/07/2024",  # Wrong format
                    "expires_at": "2026-06-30",
                    "extension": False,
                }
            ]
        }

        with pytest.raises(ExtractionError, match="invalid date format"):
            self.extractor.extract_from_json(data)


class TestSuspensionExtractor:
    """Tests for SuspensionExtractor."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.extractor = SuspensionExtractor(max_string_length=500)

    def test_extract_valid_suspension(self) -> None:
        """Happy path: parse valid suspension."""
        data = {
            "suspensions": [
                {
                    "id": "S_12345",
                    "player_id": "P_67890",
                    "team_id": "TEAM_FB",
                    "competition_id": "TR_SUPER_LIG",
                    "reason": "accumulated_yellows",
                    "matches_remaining": 2,
                    "starts_at": "2026-06-20",
                    "expires_after_match_id": "MATCH_54321",
                }
            ]
        }

        results = self.extractor.extract_from_json(data)

        assert len(results) == 1
        payload = results[0]
        assert payload["suspension_id"] == "S_12345"
        assert payload["player_id"] == "P_67890"
        assert payload["team_id"] == "TEAM_FB"
        assert payload["competition_id"] == "TR_SUPER_LIG"
        assert payload["reason"] == "accumulated_yellows"
        assert payload["matches_remaining"] == 2
        assert payload["starts_at"] == "2026-06-20"
        assert payload["expires_after_match_id"] == "MATCH_54321"

    def test_suspension_without_expires_after_match_id(self) -> None:
        """Happy path: suspension with null expires_after_match_id."""
        data = {
            "suspensions": [
                {
                    "id": "S_12345",
                    "player_id": "P_67890",
                    "team_id": "TEAM_FB",
                    "competition_id": "TR_SUPER_LIG",
                    "reason": "red",
                    "matches_remaining": 1,
                    "starts_at": "2026-06-20",
                    "expires_after_match_id": None,
                }
            ]
        }

        results = self.extractor.extract_from_json(data)

        assert len(results) == 1
        assert results[0]["expires_after_match_id"] is None

    def test_invalid_suspension_reason_raises_error(self) -> None:
        """Adversarial: invalid suspension reason."""
        data = {
            "suspensions": [
                {
                    "id": "S_12345",
                    "player_id": "P_67890",
                    "team_id": "TEAM_FB",
                    "competition_id": "TR_SUPER_LIG",
                    "reason": "injury",  # Invalid reason
                    "matches_remaining": 2,
                    "starts_at": "2026-06-20",
                    "expires_after_match_id": None,
                }
            ]
        }

        with pytest.raises(ExtractionError, match="invalid reason value"):
            self.extractor.extract_from_json(data)

    def test_negative_matches_remaining_raises_error(self) -> None:
        """Adversarial: negative matches_remaining raises error."""
        data = {
            "suspensions": [
                {
                    "id": "S_12345",
                    "player_id": "P_67890",
                    "team_id": "TEAM_FB",
                    "competition_id": "TR_SUPER_LIG",
                    "reason": "red",
                    "matches_remaining": -1,  # Invalid
                    "starts_at": "2026-06-20",
                    "expires_after_match_id": None,
                }
            ]
        }

        with pytest.raises(ExtractionError, match="matches_remaining must be >= 0"):
            self.extractor.extract_from_json(data)

    def test_missing_suspension_field_raises_error(self) -> None:
        """Adversarial: missing required suspension field."""
        data = {
            "suspensions": [
                {
                    "id": "S_12345",
                    "player_id": "P_67890",
                    # missing team_id
                    "competition_id": "TR_SUPER_LIG",
                    "reason": "red",
                    "matches_remaining": 1,
                    "starts_at": "2026-06-20",
                    "expires_after_match_id": None,
                }
            ]
        }

        with pytest.raises(ExtractionError, match="missing required field: team_id"):
            self.extractor.extract_from_json(data)
