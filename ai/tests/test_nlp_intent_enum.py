"""Tests for Phase 10 §10.4 — closed intent enum (_intent_enum.json).

Covers:
    1.  _intent_enum.json exists at the expected path.
    2.  schema_version == 1.
    3.  `enum` key is present and is a list.
    4.  No duplicate labels.
    5.  `additionalProperties` is false (schema strictness).
    6.  All 15 canonical labels are present.
    7.  `meta.adversarial` is in the enum (auto-routing gate, §10.4).
    8.  `data.player_card_risk` is in the enum (Phase 21 gated, §10.4).
    9.  INTENT_LABELS in intent.py matches the JSON enum exactly.
    10. INTENT_LABELS is a frozenset.
    11. Adversarial: _load_intent_labels raises ValueError on wrong schema_version.
    12. Adversarial: _load_intent_labels raises ValueError on missing enum key.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

# Path to the single-source enum registry (mirrors _INTENT_ENUM_PATH in intent.py)
_SCHEMA_DIR = (
    Path(__file__).parent.parent
    / "swarm" / "sdk" / "schemas"
)
_INTENT_ENUM_PATH = _SCHEMA_DIR / "_intent_enum.json"

# Canonical label set derived from §10.4 design doc (source of truth).
_EXPECTED_LABELS = frozenset({
    "predict.match_outcome",
    "predict.over_under",
    "predict.btts",
    "predict.handicap",
    "predict.score_grid",
    "data.fixture_lookup",
    "data.kickoff_time",
    "data.standings",
    "data.head_to_head",
    "data.player_card_risk",
    "summary.next_week",
    "summary.matchday",
    "meta.help",
    "meta.unsupported",
    "meta.adversarial",
})


# ---------------------------------------------------------------------------
# §10.4 _intent_enum.json structure
# ---------------------------------------------------------------------------


class TestIntentEnumJson:
    def _load(self):
        return json.loads(_INTENT_ENUM_PATH.read_text(encoding="utf-8"))

    def test_file_exists(self):
        assert _INTENT_ENUM_PATH.exists(), (
            f"_intent_enum.json missing at {_INTENT_ENUM_PATH}"
        )

    def test_schema_version_is_1(self):
        raw = self._load()
        assert raw.get("schema_version") == 1

    def test_enum_key_present_and_is_list(self):
        raw = self._load()
        values = raw.get("enum")
        assert isinstance(values, list) and len(values) > 0

    def test_no_duplicate_labels(self):
        raw = self._load()
        values = raw["enum"]
        assert len(values) == len(set(values)), (
            f"Duplicate intent labels: {[v for v in values if values.count(v) > 1]}"
        )

    def test_additional_properties_false(self):
        raw = self._load()
        assert raw.get("additionalProperties") is False

    def test_exactly_15_labels(self):
        raw = self._load()
        assert len(raw["enum"]) == 15, (
            f"Expected 15 intent labels, got {len(raw['enum'])}: {raw['enum']}"
        )

    def test_all_expected_labels_present(self):
        raw = self._load()
        actual = frozenset(raw["enum"])
        missing = _EXPECTED_LABELS - actual
        extra = actual - _EXPECTED_LABELS
        assert not missing, f"Missing intent labels: {missing}"
        assert not extra, f"Unexpected intent labels: {extra}"

    def test_meta_adversarial_present(self):
        """meta.adversarial must be in the enum — it is the auto-routing gate for abuse."""
        raw = self._load()
        assert "meta.adversarial" in raw["enum"]

    def test_data_player_card_risk_present(self):
        """data.player_card_risk is Phase 21 enrichment-bound but must be in enum."""
        raw = self._load()
        assert "data.player_card_risk" in raw["enum"]

    def test_label_format_dot_separated(self):
        """All labels must match <namespace>.<name> pattern."""
        import re
        pattern = re.compile(r"^[a-z_]+\.[a-z_]+$")
        raw = self._load()
        bad = [v for v in raw["enum"] if not pattern.match(v)]
        assert not bad, f"Malformed intent labels: {bad}"


# ---------------------------------------------------------------------------
# §10.4 INTENT_LABELS in intent.py
# ---------------------------------------------------------------------------


class TestIntentLabelsModule:
    def test_intent_labels_is_frozenset(self):
        from nlp.intent import INTENT_LABELS
        assert isinstance(INTENT_LABELS, frozenset)

    def test_intent_labels_matches_json_enum(self):
        from nlp.intent import INTENT_LABELS
        raw = json.loads(_INTENT_ENUM_PATH.read_text(encoding="utf-8"))
        assert INTENT_LABELS == frozenset(raw["enum"])

    def test_intent_labels_contains_all_expected(self):
        from nlp.intent import INTENT_LABELS
        missing = _EXPECTED_LABELS - INTENT_LABELS
        assert not missing, f"INTENT_LABELS missing: {missing}"

    def test_intent_labels_count_15(self):
        from nlp.intent import INTENT_LABELS
        assert len(INTENT_LABELS) == 15

    def test_meta_adversarial_in_intent_labels(self):
        from nlp.intent import INTENT_LABELS
        assert "meta.adversarial" in INTENT_LABELS


# ---------------------------------------------------------------------------
# §10.4 _load_intent_labels adversarial paths
# ---------------------------------------------------------------------------


class TestLoadIntentLabelsAdversarial:
    def test_wrong_schema_version_raises_value_error(self, tmp_path, monkeypatch):
        from nlp import intent as intent_mod

        bad_enum = tmp_path / "_intent_enum.json"
        bad_enum.write_text(
            json.dumps({"schema_version": 99, "enum": ["meta.help"]}),
            encoding="utf-8",
        )
        monkeypatch.setattr(intent_mod, "_INTENT_ENUM_PATH", bad_enum)
        with pytest.raises(ValueError, match="schema_version mismatch"):
            intent_mod._load_intent_labels()

    def test_missing_enum_key_raises_value_error(self, tmp_path, monkeypatch):
        from nlp import intent as intent_mod

        bad_enum = tmp_path / "_intent_enum.json"
        bad_enum.write_text(
            json.dumps({"schema_version": 1}),
            encoding="utf-8",
        )
        monkeypatch.setattr(intent_mod, "_INTENT_ENUM_PATH", bad_enum)
        with pytest.raises(ValueError, match="missing or empty 'enum'"):
            intent_mod._load_intent_labels()

    def test_empty_enum_raises_value_error(self, tmp_path, monkeypatch):
        from nlp import intent as intent_mod

        bad_enum = tmp_path / "_intent_enum.json"
        bad_enum.write_text(
            json.dumps({"schema_version": 1, "enum": []}),
            encoding="utf-8",
        )
        monkeypatch.setattr(intent_mod, "_INTENT_ENUM_PATH", bad_enum)
        with pytest.raises(ValueError, match="missing or empty 'enum'"):
            intent_mod._load_intent_labels()

    def test_missing_file_raises_file_not_found(self, tmp_path, monkeypatch):
        from nlp import intent as intent_mod

        monkeypatch.setattr(
            intent_mod, "_INTENT_ENUM_PATH", tmp_path / "nonexistent.json"
        )
        with pytest.raises(FileNotFoundError):
            intent_mod._load_intent_labels()
