"""Phase 10 §10.3 — Diacritic restoration table tests.

Covers:
  * Happy-path: DiacriticsTable.load() reads _diacritics.tr.yaml.
  * Schema-version mismatch raises DiacriticsSchemaError.
  * restore() replaces known ASCIIfied tokens; preserves unknowns.
  * restore() leaves already-correct Turkish forms unchanged.
  * Multi-word separators are preserved exactly.
  * Empty table passes text through unchanged.
  * SHA-256 of tr_word_freq.txt matches chart.json compatibility block.
  * Generated _diacritics.tr.yaml source_sha256 matches the live file.
  * Adversarial: partial-match within a longer token is NOT restored
    (e.g. "mackolik" should not become "maçkolik").

Per AGENTS.md Rule 10: new surface → happy path + adversarial tests.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
import yaml

# ---------------------------------------------------------------------------
# Fixtures / constants
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).parent.parent.parent
LEXICON_DIR = REPO_ROOT / "ai" / "nlp" / "lexicon"
DIACRITICS_YAML = LEXICON_DIR / "_diacritics.tr.yaml"
WORD_FREQ_FILE = REPO_ROOT / "ai" / "nlp" / "data" / "tr_word_freq.txt"
CHART_JSON = REPO_ROOT / "xops" / "versioning" / "chart.json"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_table_from_dict(data: dict):
    """Import and construct a DiacriticsTable from an already-parsed dict."""
    from nlp.diacritics import DiacriticsTable
    return DiacriticsTable(data)


def _minimal_yaml(schema_version: Any = 1, extra_mappings: dict | None = None) -> dict:
    """Build a minimal valid diacritics YAML dict for unit tests."""
    mappings = {"mac": {"canonical": "ma\u00e7", "frequency": 50000}}
    if extra_mappings:
        mappings.update(extra_mappings)
    return {
        "_meta": {
            "schema_version": schema_version,
            "lexicon_version": "1.0.0",
            "generated_at_utc": "2026-05-27T00:00:00Z",
            "generator": "nlp.diacritics-build",
            "source_sha256": "deadbeef",
        },
        "mappings": mappings,
    }


# ---------------------------------------------------------------------------
# File-existence tests
# ---------------------------------------------------------------------------


class TestDiacriticsFileExists:
    def test_diacritics_yaml_exists(self) -> None:
        assert DIACRITICS_YAML.is_file(), (
            f"_diacritics.tr.yaml not found: {DIACRITICS_YAML}; "
            "run `make nlp.diacritics-build`"
        )

    def test_word_freq_file_exists(self) -> None:
        assert WORD_FREQ_FILE.is_file(), (
            f"tr_word_freq.txt not found: {WORD_FREQ_FILE}"
        )

    def test_diacritics_yaml_is_valid_yaml(self) -> None:
        data = yaml.safe_load(DIACRITICS_YAML.read_text(encoding="utf-8"))
        assert isinstance(data, dict), "top-level must be a dict"
        assert "_meta" in data
        assert "mappings" in data


# ---------------------------------------------------------------------------
# Schema-version tests
# ---------------------------------------------------------------------------


class TestSchemaVersion:
    def test_load_correct_schema_version(self) -> None:
        from nlp.diacritics import DiacriticsTable, DIACRITICS_SCHEMA_VERSION

        table = _load_table_from_dict(_minimal_yaml(schema_version=DIACRITICS_SCHEMA_VERSION))
        assert isinstance(table, DiacriticsTable)

    def test_wrong_schema_version_raises(self) -> None:
        from nlp.diacritics import DiacriticsSchemaError

        with pytest.raises(DiacriticsSchemaError):
            _load_table_from_dict(_minimal_yaml(schema_version=99))

    def test_missing_schema_version_raises(self) -> None:
        from nlp.diacritics import DiacriticsSchemaError

        data = _minimal_yaml()
        del data["_meta"]["schema_version"]
        with pytest.raises(DiacriticsSchemaError):
            _load_table_from_dict(data)

    def test_string_schema_version_raises(self) -> None:
        """schema_version must be an integer, not a string."""
        from nlp.diacritics import DiacriticsSchemaError

        with pytest.raises(DiacriticsSchemaError):
            _load_table_from_dict(_minimal_yaml(schema_version="1"))


# ---------------------------------------------------------------------------
# Happy-path: load from real file
# ---------------------------------------------------------------------------


class TestRealTableLoad:
    def test_load_default_path(self) -> None:
        from nlp.diacritics import DiacriticsTable

        table = DiacriticsTable.load()
        assert len(table) > 0, "_diacritics.tr.yaml loaded but empty"

    def test_real_file_meta_version(self) -> None:
        from nlp.diacritics import DiacriticsTable, DIACRITICS_SCHEMA_VERSION

        table = DiacriticsTable.load()
        data = yaml.safe_load(DIACRITICS_YAML.read_text(encoding="utf-8"))
        assert data["_meta"]["schema_version"] == DIACRITICS_SCHEMA_VERSION

    def test_known_entries_present(self) -> None:
        """Key football-domain ASCIIfied forms must be in the table."""
        from nlp.diacritics import DiacriticsTable

        table = DiacriticsTable.load()
        # These are computed from tr_word_freq.txt and lexicon names.
        for ascii_form in ("besiktas", "mac", "super", "uc"):
            assert ascii_form in table, (
                f"Expected \'{ascii_form}\' in diacritics table; "
                "regenerate with `make nlp.diacritics-build`"
            )

    def test_known_canonicals_correct(self) -> None:
        from nlp.diacritics import DiacriticsTable

        table = DiacriticsTable.load()
        checks = {
            "besiktas": "be\u015fikta\u015f",  # beşiktaş
            "mac": "ma\u00e7",                  # maç
            "super": "s\u00fcper",              # süper
            "uc": "\u00fc\u00e7",              # üç
        }
        for ascii_form, expected in checks.items():
            entry = table.get(ascii_form)
            if entry is not None:  # entry may be absent on minimal builds
                assert entry.canonical == expected, (
                    f"\'{ascii_form}\' → got \'{entry.canonical}\', "
                    f"expected \'{expected}\'"
                )


# ---------------------------------------------------------------------------
# restore() behaviour
# ---------------------------------------------------------------------------


class TestRestoreFunction:
    def _make_table(self, extra: dict | None = None):
        from nlp.diacritics import DiacriticsTable

        data = {
            "_meta": {
                "schema_version": 1,
                "lexicon_version": "1.0.0",
                "generated_at_utc": "2026-05-27T00:00:00Z",
                "generator": "test",
                "source_sha256": "test",
            },
            "mappings": {
                "mac": {"canonical": "ma\u00e7", "frequency": 50000},
                "fenerbahce": {"canonical": "fenerbah\u00e7e", "frequency": 48000},
                "ust": {"canonical": "\u00fcst", "frequency": 65432},
                "besiktas": {"canonical": "be\u015fikta\u015f", "frequency": 121345},
            },
        }
        if extra:
            data["mappings"].update(extra)
        return DiacriticsTable(data)

    def test_single_token_replacement(self) -> None:
        table = self._make_table()
        assert table.restore("mac") == "ma\u00e7"

    def test_multi_token_sentence(self) -> None:
        table = self._make_table()
        result = table.restore("fenerbahce mac tahmini")
        assert result == "fenerbah\u00e7e ma\u00e7 tahmini"

    def test_unknown_token_preserved(self) -> None:
        table = self._make_table()
        assert table.restore("galatasaray") == "galatasaray"

    def test_already_canonical_unchanged(self) -> None:
        """A token that already has diacritics (e.g. 'fenerbahçe') must be
        left as-is; the ASCII-word regex won't even match it."""
        table = self._make_table()
        text = "fenerbah\u00e7e ma\u00e7"
        assert table.restore(text) == text

    def test_punctuation_preserved(self) -> None:
        """Non-word separators must be preserved exactly."""
        table = self._make_table()
        result = table.restore("mac, besiktas?")
        assert result == "ma\u00e7, be\u015fikta\u015f?"

    def test_partial_match_not_replaced(self) -> None:
        """'mac' inside 'mackolik' must NOT be replaced; the token is
        'mackolik' as a whole (no space boundary between them)."""
        table = self._make_table()
        # After tokenization rules, "mackolik" arrives as one token.
        # At step 6 (pre-tokenization) the text is "mackolik".
        # The ASCII-word RE splits on non-word chars; "mackolik" is one
        # pure-ASCII word → it is looked up as "mackolik" (not in map).
        result = table.restore("mackolik")
        assert result == "mackolik", (
            f"Expected 'mackolik' unchanged, got {result!r}"
        )

    def test_empty_table_passthrough(self) -> None:
        from nlp.diacritics import DiacriticsTable

        table = DiacriticsTable({
            "_meta": {
                "schema_version": 1,
                "lexicon_version": "1.0.0",
                "generated_at_utc": "2026-05-27T00:00:00Z",
                "generator": "test",
                "source_sha256": "test",
            },
            "mappings": {},
        })
        text = "fenerbahce mac"
        assert table.restore(text) == text

    def test_digits_and_punctuation_boundaries(self) -> None:
        """Numbers and punctuation around a token must not block restoration."""
        table = self._make_table()
        result = table.restore("(mac)")
        assert result == "(ma\u00e7)"


# ---------------------------------------------------------------------------
# SHA-256 integrity tests
# ---------------------------------------------------------------------------


class TestSha256Integrity:
    def test_chart_json_has_tr_word_freq_sha(self) -> None:
        """chart.json compatibility block must declare tr_word_freq SHA-256."""
        data = json.loads(CHART_JSON.read_text(encoding="utf-8"))
        compat = data.get("compatibility", {})
        data_files = compat.get("data_files", {})
        assert "tr_word_freq" in data_files, (
            "chart.json compatibility.data_files.tr_word_freq missing; "
            "expected per Phase 10 §10.3 doctrine"
        )
        entry = data_files["tr_word_freq"]
        assert "sha256" in entry, "tr_word_freq entry missing sha256 key"
        assert "path" in entry, "tr_word_freq entry missing path key"

    def test_word_freq_sha_matches_chart_json(self) -> None:
        """The actual SHA-256 of tr_word_freq.txt must match chart.json."""
        data = json.loads(CHART_JSON.read_text(encoding="utf-8"))
        declared = (
            data.get("compatibility", {})
            .get("data_files", {})
            .get("tr_word_freq", {})
            .get("sha256", "")
        )
        actual = hashlib.sha256(WORD_FREQ_FILE.read_bytes()).hexdigest()
        assert actual == declared, (
            f"tr_word_freq.txt SHA-256 mismatch: "
            f"chart.json declares {declared!r}, file is {actual!r}. "
            "Re-run `make nlp.diacritics-build` and update chart.json."
        )

    def test_diacritics_yaml_source_sha_matches_file(self) -> None:
        """source_sha256 in _diacritics.tr.yaml must equal actual file SHA."""
        data = yaml.safe_load(DIACRITICS_YAML.read_text(encoding="utf-8"))
        declared = data.get("_meta", {}).get("source_sha256", "")
        actual = hashlib.sha256(WORD_FREQ_FILE.read_bytes()).hexdigest()
        assert actual == declared, (
            f"_diacritics.tr.yaml source_sha256 mismatch: "
            f"YAML declares {declared!r}, file is {actual!r}. "
            "Re-run `make nlp.diacritics-build`."
        )


# ---------------------------------------------------------------------------
# §10.3 Ambiguity policy (tie-break ratio)
# ---------------------------------------------------------------------------


def _make_ambiguous_table(tie_break_ratio: float = 1.5):
    """Build a table with a candidates-based ambiguous entry for 'kor'
    and a clear-winner entry for 'mac'."""
    from nlp.diacritics import DiacriticsTable

    data = {
        "_meta": {
            "schema_version": 1,
            "lexicon_version": "1.0.0",
            "generated_at_utc": "2026-05-27T00:00:00Z",
            "generator": "test",
            "source_sha256": "test",
        },
        "mappings": {
            # 'mac' → unambiguous (only one candidate / classic format)
            "mac": {"canonical": "maç", "frequency": 50000},
            # 'kor' → ambiguous: 45000 / 43000 = ~1.047 < 1.5 → preserve
            "kor": {
                "candidates": [
                    {"canonical": "kör", "frequency": 45000},
                    {"canonical": "kor", "frequency": 43000},
                ]
            },
            # 'ust' → clear winner: 65432 / 100 = 654.32 >> 1.5 → restore
            "ust": {
                "candidates": [
                    {"canonical": "üst", "frequency": 65432},
                    {"canonical": "ust", "frequency": 100},
                ]
            },
        },
    }
    return DiacriticsTable(data, tie_break_ratio=tie_break_ratio)


class TestAmbiguityPolicy:
    """§10.3 Ambiguity policy: tie-break ratio preserves ambiguous tokens."""

    def test_ambiguous_entry_is_flagged(self) -> None:
        """Entry with top-2 within ratio should have is_ambiguous=True."""
        table = _make_ambiguous_table(tie_break_ratio=1.5)
        entry = table.get("kor")
        assert entry is not None
        assert entry.is_ambiguous is True

    def test_unambiguous_single_format_not_flagged(self) -> None:
        """Classic single-canonical entry must have is_ambiguous=False."""
        table = _make_ambiguous_table(tie_break_ratio=1.5)
        entry = table.get("mac")
        assert entry is not None
        assert entry.is_ambiguous is False

    def test_clear_winner_candidate_not_flagged(self) -> None:
        """Candidates with a large frequency gap should have is_ambiguous=False."""
        table = _make_ambiguous_table(tie_break_ratio=1.5)
        entry = table.get("ust")
        assert entry is not None
        assert entry.is_ambiguous is False

    def test_restore_skips_ambiguous_token(self) -> None:
        """restore() must NOT replace an ambiguous token."""
        table = _make_ambiguous_table()
        result = table.restore("kor mac")
        # 'kor' is ambiguous → preserved; 'mac' is clear → restored
        assert result == "kor maç", repr(result)

    def test_restore_replaces_clear_winner_candidate(self) -> None:
        """restore() replaces the clear-winner multi-candidate entry."""
        table = _make_ambiguous_table()
        assert table.restore("ust") == "üst"

    def test_restore_with_flags_returns_ambiguous_set(self) -> None:
        """restore_with_flags() returns the ambiguous tokens as frozenset."""
        table = _make_ambiguous_table()
        text, ambiguous = table.restore_with_flags("kor mac ust")
        assert text == "kor maç üst", repr(text)
        assert "kor" in ambiguous
        assert "mac" not in ambiguous
        assert "ust" not in ambiguous

    def test_restore_with_flags_empty_when_no_ambiguous(self) -> None:
        """restore_with_flags() returns empty frozenset when nothing is ambiguous."""
        table = _make_ambiguous_table()
        text, ambiguous = table.restore_with_flags("mac ust")
        assert text == "maç üst"
        assert len(ambiguous) == 0

    def test_restore_with_flags_empty_table(self) -> None:
        """restore_with_flags() on an empty table returns unchanged text + empty set."""
        from nlp.diacritics import DiacriticsTable

        empty = DiacriticsTable({
            "_meta": {
                "schema_version": 1,
                "lexicon_version": "1.0.0",
                "generated_at_utc": "2026-05-27T00:00:00Z",
                "generator": "test",
                "source_sha256": "test",
            },
            "mappings": {},
        })
        text, ambiguous = empty.restore_with_flags("fenerbahce mac")
        assert text == "fenerbahce mac"
        assert len(ambiguous) == 0

    def test_boundary_ratio_exactly_at_limit(self) -> None:
        """Entry with top/second == tie_break_ratio exactly → ambiguous."""
        from nlp.diacritics import DiacriticsTable

        # 15000 / 10000 = 1.5 exactly → ambiguous at ratio=1.5
        data = {
            "_meta": {
                "schema_version": 1,
                "lexicon_version": "1.0.0",
                "generated_at_utc": "2026-05-27T00:00:00Z",
                "generator": "test",
                "source_sha256": "test",
            },
            "mappings": {
                "test": {
                    "candidates": [
                        {"canonical": "tëst", "frequency": 15000},
                        {"canonical": "test", "frequency": 10000},
                    ]
                }
            },
        }
        table = DiacriticsTable(data, tie_break_ratio=1.5)
        entry = table.get("test")
        assert entry is not None
        assert entry.is_ambiguous is True, (
            "15000/10000 == 1.5 <= ratio 1.5 → should be ambiguous"
        )

    def test_boundary_ratio_just_above_limit(self) -> None:
        """Entry with top/second just above tie_break_ratio → NOT ambiguous."""
        from nlp.diacritics import DiacriticsTable

        # 15001 / 10000 = 1.5001 > 1.5 → not ambiguous
        data = {
            "_meta": {
                "schema_version": 1,
                "lexicon_version": "1.0.0",
                "generated_at_utc": "2026-05-27T00:00:00Z",
                "generator": "test",
                "source_sha256": "test",
            },
            "mappings": {
                "test": {
                    "candidates": [
                        {"canonical": "tëst", "frequency": 15001},
                        {"canonical": "test", "frequency": 10000},
                    ]
                }
            },
        }
        table = DiacriticsTable(data, tie_break_ratio=1.5)
        entry = table.get("test")
        assert entry is not None
        assert entry.is_ambiguous is False, (
            "15001/10000 > ratio 1.5 → should NOT be ambiguous"
        )

    def test_second_freq_zero_not_ambiguous(self) -> None:
        """Second candidate frequency of 0 → unambiguous clear winner."""
        from nlp.diacritics import DiacriticsTable

        data = {
            "_meta": {
                "schema_version": 1,
                "lexicon_version": "1.0.0",
                "generated_at_utc": "2026-05-27T00:00:00Z",
                "generator": "test",
                "source_sha256": "test",
            },
            "mappings": {
                "ali": {
                    "candidates": [
                        {"canonical": "ali", "frequency": 50000},
                        {"canonical": "alı", "frequency": 0},
                    ]
                }
            },
        }
        table = DiacriticsTable(data, tie_break_ratio=1.5)
        entry = table.get("ali")
        assert entry is not None
        assert entry.is_ambiguous is False

    def test_config_key_present_with_correct_default(self) -> None:
        """cfg.nlp_diacritic_tie_break_ratio must default to 1.5."""
        from common.config import cfg

        assert hasattr(cfg, "nlp_diacritic_tie_break_ratio")
        assert cfg.nlp_diacritic_tie_break_ratio == 1.5

    def test_config_key_in_env_example(self) -> None:
        """NEGELIR_NLP_DIACRITIC_TIE_BREAK_RATIO must appear in .env.example."""
        env_example = (REPO_ROOT / "xops" / "env" / ".env.example").read_text(encoding="utf-8")
        assert "NEGELIR_NLP_DIACRITIC_TIE_BREAK_RATIO" in env_example

    def test_config_boot_validator_rejects_below_one(self) -> None:
        """Boot validator must reject nlp_diacritic_tie_break_ratio < 1.0."""
        import os
        from common.config import Config

        orig = os.environ.get("NEGELIR_NLP_DIACRITIC_TIE_BREAK_RATIO")
        try:
            os.environ["NEGELIR_NLP_DIACRITIC_TIE_BREAK_RATIO"] = "0.5"
            cfg_bad = Config()
            issues = cfg_bad.validate()
            assert any("nlp_diacritic_tie_break_ratio" in i for i in issues), issues
        finally:
            if orig is None:
                os.environ.pop("NEGELIR_NLP_DIACRITIC_TIE_BREAK_RATIO", None)
            else:
                os.environ["NEGELIR_NLP_DIACRITIC_TIE_BREAK_RATIO"] = orig
