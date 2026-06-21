"""Phase 10 §10.2 — Lexicon versioning tests.

Verifies that all 7 lexicon files carry a valid _meta block with
schema_version == LEXICON_SCHEMA_VERSION, and that load_lexicon_file()
refuses load on any schema-version mismatch or malformed header.

Per AGENTS.md Rule 10: new surface → happy path + adversarial tests.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from nlp.lexicon_loader import (
    LEXICON_SCHEMA_VERSION,
    LexiconMeta,
    LexiconSchemaError,
    load_lexicon_file,
)

LEXICON_DIR = Path(__file__).parent.parent / "nlp" / "lexicon"

_ALL_FILES = [
    "teams.tr.yaml",
    "players.tr.yaml",
    "leagues.tr.yaml",
    "competitions.tr.yaml",
    "markets.tr.yaml",
    "dialects.tr.yaml",
    "entities_negative.tr.yaml",
]

def _make_yaml(schema_version: Any = 1) -> str:
    """Construct a minimal valid lexicon YAML with the given schema_version."""
    return (
        f"_meta:\n"
        f"  schema_version: {schema_version!r}\n"
        f"  lexicon_version: 1.0.0\n"
        f'  generated_at_utc: "2026-05-27T00:00:00Z"\n'
        f"  generator: nlp.lexicon-build\n"
        f"entries:\n"
        f"  - canonical_id: test\n"
        f"    names:\n"
        f"      - Test\n"
        f"    aliases:\n"
        f"      - t\n"
    )


# Indented entry block suitable for appending after an ``entries:`` line.
_ENTRIES_YAML = (
    "  - canonical_id: test\n"
    "    names:\n"
    "      - Test\n"
    "    aliases:\n"
    "      - t\n"
)


# ── Happy-path: all shipped lexicon files load successfully ──────────────

class TestLexiconVersioningHappyPath:
    """All 7 lexicon files must carry schema_version == LEXICON_SCHEMA_VERSION
    and load without error via load_lexicon_file()."""

    @pytest.mark.parametrize("filename", _ALL_FILES)
    def test_load_lexicon_file_succeeds(self, filename: str) -> None:
        path = LEXICON_DIR / filename
        meta, entries = load_lexicon_file(path)
        assert isinstance(meta, LexiconMeta), (
            f"{filename}: load_lexicon_file must return LexiconMeta"
        )
        assert meta.schema_version == LEXICON_SCHEMA_VERSION, (
            f"{filename}: schema_version={meta.schema_version} != "
            f"LEXICON_SCHEMA_VERSION={LEXICON_SCHEMA_VERSION}"
        )
        assert isinstance(entries, list), (
            f"{filename}: entries must be a list"
        )
        assert len(entries) >= 1, f"{filename}: entries must be non-empty"

    @pytest.mark.parametrize("filename", _ALL_FILES)
    def test_meta_required_fields_populated(self, filename: str) -> None:
        path = LEXICON_DIR / filename
        meta, _ = load_lexicon_file(path)
        assert meta.lexicon_version, f"{filename}: lexicon_version must be non-empty"
        assert meta.generated_at_utc, f"{filename}: generated_at_utc must be non-empty"
        assert meta.generator == "nlp.lexicon-build", (
            f"{filename}: generator must be 'nlp.lexicon-build'"
        )

    @pytest.mark.parametrize("filename", _ALL_FILES)
    def test_meta_lexicon_version_looks_like_semver(self, filename: str) -> None:
        path = LEXICON_DIR / filename
        meta, _ = load_lexicon_file(path)
        parts = meta.lexicon_version.split(".")
        assert len(parts) == 3, (
            f"{filename}: lexicon_version '{meta.lexicon_version}' must be semver X.Y.Z"
        )
        for part in parts:
            assert part.isdigit(), (
                f"{filename}: lexicon_version part '{part}' must be numeric"
            )


# ── Adversarial: refuses load on schema-version mismatch or bad header ──

class TestLexiconVersioningRefusesLoad:
    """load_lexicon_file() must raise LexiconSchemaError on any violation."""

    def _write_tmp(self, tmp_path: Path, content: str) -> Path:
        p = tmp_path / "test_lexicon.yaml"
        p.write_text(content, encoding="utf-8")
        return p

    def test_schema_version_mismatch_raises(self, tmp_path: Path) -> None:
        """schema_version != LEXICON_SCHEMA_VERSION must refuse load."""
        future_version = LEXICON_SCHEMA_VERSION + 1
        p = self._write_tmp(tmp_path, _make_yaml(schema_version=future_version))
        with pytest.raises(LexiconSchemaError, match="schema_version"):
            load_lexicon_file(p)

    def test_schema_version_zero_raises(self, tmp_path: Path) -> None:
        """schema_version=0 is not valid."""
        p = self._write_tmp(tmp_path, _make_yaml(schema_version=0))
        with pytest.raises(LexiconSchemaError, match="schema_version"):
            load_lexicon_file(p)

    def test_schema_version_string_raises(self, tmp_path: Path) -> None:
        """schema_version must be an integer, not a string."""
        p = self._write_tmp(tmp_path, _make_yaml(schema_version='"1"'))
        with pytest.raises(LexiconSchemaError, match="integer"):
            load_lexicon_file(p)

    def test_missing_meta_raises(self, tmp_path: Path) -> None:
        """A file without _meta must be refused."""
        content = "entries:\n" + _ENTRIES_YAML
        p = self._write_tmp(tmp_path, content)
        with pytest.raises(LexiconSchemaError, match="_meta"):
            load_lexicon_file(p)

    def test_bare_list_format_raises(self, tmp_path: Path) -> None:
        """Pre-§10.2 bare list format must be refused (not a dict)."""
        content = "- canonical_id: galatasaray_sk\n  names:\n    - GS\n  aliases:\n    - gs\n"
        p = self._write_tmp(tmp_path, content)
        with pytest.raises(LexiconSchemaError, match="mapping"):
            load_lexicon_file(p)

    def test_missing_schema_version_key_raises(self, tmp_path: Path) -> None:
        """_meta without schema_version must be refused."""
        content = (
            "_meta:\n"
            "  lexicon_version: 1.0.0\n"
            '  generated_at_utc: "2026-05-27T00:00:00Z"\n'
            "  generator: nlp.lexicon-build\n"
            "entries:\n"
            + _ENTRIES_YAML
        )
        p = self._write_tmp(tmp_path, content)
        with pytest.raises(LexiconSchemaError, match="schema_version"):
            load_lexicon_file(p)

    def test_missing_entries_key_raises(self, tmp_path: Path) -> None:
        """File with _meta but no entries key must be refused."""
        content = (
            "_meta:\n"
            "  schema_version: 1\n"
            "  lexicon_version: 1.0.0\n"
            '  generated_at_utc: "2026-05-27T00:00:00Z"\n'
            "  generator: nlp.lexicon-build\n"
        )
        p = self._write_tmp(tmp_path, content)
        with pytest.raises(LexiconSchemaError, match="entries"):
            load_lexicon_file(p)

    def test_meta_not_a_dict_raises(self, tmp_path: Path) -> None:
        """_meta: 'scalar' must be refused."""
        content = (
            "_meta: not-a-dict\n"
            "entries:\n"
            + _ENTRIES_YAML
        )
        p = self._write_tmp(tmp_path, content)
        with pytest.raises(LexiconSchemaError, match="_meta.*mapping|mapping.*_meta"):
            load_lexicon_file(p)

    def test_file_not_found_raises(self, tmp_path: Path) -> None:
        """Non-existent path must raise FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            load_lexicon_file(tmp_path / "nonexistent.yaml")
