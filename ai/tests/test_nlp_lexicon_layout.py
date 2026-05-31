"""Phase 10 §10.2 — Lexicon layout tests.

Verifies that all 7 required lexicon files exist under ai/nlp/lexicon/,
that each is valid YAML, and that each entry carries the required structural
keys as declared in the §10.2 Layout bullet.

Per AGENTS.md Rule 10: new surface → happy path + adversarial tests.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

LEXICON_DIR = Path(__file__).parent.parent / "nlp" / "lexicon"


def _load_entries(path: Path) -> list[Any]:
    """Load just the ``entries`` list from a lexicon file (§10.2 dict format)."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict), (
        f"{path.name}: expected top-level dict after §10.2 Versioning, "
        f"got {type(data).__name__}"
    )
    assert "entries" in data, f"{path.name}: missing 'entries' key"
    return data["entries"]

# ── Required files and their per-entry required keys ────────────────────
# dialects has a different schema (token → canonical_tokens), not canonical_id
# entities_negative has token instead of canonical_id
_FILE_REQUIRED_KEYS: dict[str, tuple[str, ...]] = {
    "teams.tr.yaml":           ("canonical_id", "names", "aliases"),
    "players.tr.yaml":         ("canonical_id", "names", "aliases"),
    "leagues.tr.yaml":         ("canonical_id", "names", "aliases"),
    "competitions.tr.yaml":    ("canonical_id", "names", "aliases"),
    "markets.tr.yaml":         ("canonical_id", "names", "aliases"),
    "dialects.tr.yaml":        ("token", "canonical_tokens"),
    "entities_negative.tr.yaml": ("token",),
}

_ALL_FILES = list(_FILE_REQUIRED_KEYS.keys())


class TestLexiconFilesExist:
    """All 7 lexicon files must be present under ai/nlp/lexicon/."""

    def test_lexicon_directory_exists(self) -> None:
        assert LEXICON_DIR.is_dir(), f"Missing directory: {LEXICON_DIR}"

    @pytest.mark.parametrize("filename", _ALL_FILES)
    def test_file_exists(self, filename: str) -> None:
        path = LEXICON_DIR / filename
        assert path.exists(), f"Missing lexicon file: {path}"
        assert path.is_file(), f"Expected a file, got directory: {path}"


class TestLexiconFilesAreValidYaml:
    """Each lexicon file must parse as valid YAML and be a non-empty list."""

    @pytest.mark.parametrize("filename", _ALL_FILES)
    def test_parses_as_yaml(self, filename: str) -> None:
        path = LEXICON_DIR / filename
        content = path.read_text(encoding="utf-8")
        try:
            data = yaml.safe_load(content)
        except yaml.YAMLError as exc:
            pytest.fail(f"{filename} is not valid YAML: {exc}")
        # §10.2 Versioning: top-level must be a dict with _meta + entries
        assert isinstance(data, dict), (
            f"{filename}: expected top-level dict {{_meta, entries}}, "
            f"got {type(data).__name__}"
        )
        assert "_meta" in data, f"{filename}: missing '_meta' key"
        assert "entries" in data, f"{filename}: missing 'entries' key"
        entries = data["entries"]
        assert isinstance(entries, list), (
            f"{filename}: 'entries' must be a list, got {type(entries).__name__}"
        )
        assert len(entries) >= 1, f"{filename}: entries list must have at least one entry"

    @pytest.mark.parametrize("filename", _ALL_FILES)
    def test_entries_are_dicts(self, filename: str) -> None:
        path = LEXICON_DIR / filename
        data: list[Any] = _load_entries(path)
        for i, entry in enumerate(data):
            assert isinstance(entry, dict), (
                f"{filename}[{i}]: expected dict entry, got {type(entry).__name__}"
            )


class TestLexiconEntryRequiredKeys:
    """Each entry in a lexicon file must have the declared required keys."""

    @pytest.mark.parametrize("filename,required_keys", list(_FILE_REQUIRED_KEYS.items()))
    def test_required_keys_present(self, filename: str, required_keys: tuple[str, ...]) -> None:
        path = LEXICON_DIR / filename
        data: list[dict[str, Any]] = _load_entries(path)
        for i, entry in enumerate(data):
            for key in required_keys:
                assert key in entry, (
                    f"{filename}[{i}]: missing required key '{key}'. "
                    f"Entry keys: {list(entry.keys())}"
                )

    @pytest.mark.parametrize("filename", ["teams.tr.yaml", "players.tr.yaml",
                                           "leagues.tr.yaml", "competitions.tr.yaml",
                                           "markets.tr.yaml"])
    def test_names_is_nonempty_list(self, filename: str) -> None:
        path = LEXICON_DIR / filename
        data: list[dict[str, Any]] = _load_entries(path)
        for i, entry in enumerate(data):
            names = entry.get("names")
            assert isinstance(names, list) and len(names) >= 1, (
                f"{filename}[{i}]: 'names' must be a non-empty list"
            )

    @pytest.mark.parametrize("filename", ["teams.tr.yaml", "players.tr.yaml",
                                           "leagues.tr.yaml", "competitions.tr.yaml",
                                           "markets.tr.yaml"])
    def test_aliases_is_list(self, filename: str) -> None:
        path = LEXICON_DIR / filename
        data: list[dict[str, Any]] = _load_entries(path)
        for i, entry in enumerate(data):
            aliases = entry.get("aliases")
            assert isinstance(aliases, list), (
                f"{filename}[{i}]: 'aliases' must be a list (may be empty)"
            )

    @pytest.mark.parametrize("filename", ["teams.tr.yaml", "players.tr.yaml",
                                           "leagues.tr.yaml", "competitions.tr.yaml",
                                           "markets.tr.yaml"])
    def test_canonical_id_is_nonempty_string(self, filename: str) -> None:
        path = LEXICON_DIR / filename
        data: list[dict[str, Any]] = _load_entries(path)
        for i, entry in enumerate(data):
            cid = entry.get("canonical_id")
            assert isinstance(cid, str) and len(cid) > 0, (
                f"{filename}[{i}]: 'canonical_id' must be a non-empty string"
            )

    def test_dialects_canonical_tokens_is_nonempty_list(self) -> None:
        path = LEXICON_DIR / "dialects.tr.yaml"
        data: list[dict[str, Any]] = _load_entries(path)
        for i, entry in enumerate(data):
            tokens = entry.get("canonical_tokens")
            assert isinstance(tokens, list) and len(tokens) >= 1, (
                f"dialects.tr.yaml[{i}]: 'canonical_tokens' must be a non-empty list"
            )

    def test_entities_negative_token_is_string(self) -> None:
        path = LEXICON_DIR / "entities_negative.tr.yaml"
        data: list[dict[str, Any]] = _load_entries(path)
        for i, entry in enumerate(data):
            token = entry.get("token")
            assert isinstance(token, str) and len(token) > 0, (
                f"entities_negative.tr.yaml[{i}]: 'token' must be a non-empty string"
            )


class TestLexiconNoDuplicateCanonicalIds:
    """canonical_id values must be unique within each lexicon file."""

    @pytest.mark.parametrize("filename", ["teams.tr.yaml", "players.tr.yaml",
                                           "leagues.tr.yaml", "competitions.tr.yaml",
                                           "markets.tr.yaml"])
    def test_no_duplicate_canonical_ids(self, filename: str) -> None:
        path = LEXICON_DIR / filename
        data: list[dict[str, Any]] = _load_entries(path)
        ids = [entry["canonical_id"] for entry in data]
        seen: set[str] = set()
        for cid in ids:
            assert cid not in seen, (
                f"{filename}: duplicate canonical_id '{cid}'"
            )
            seen.add(cid)


class TestLexiconMarketsCanonicalIdsInClosedEnum:
    """Market canonical_ids must exist in ai/common/betting_markets.json."""

    def test_market_canonical_ids_in_betting_markets_enum(self) -> None:
        import json

        betting_markets_path = (
            Path(__file__).parent.parent / "common" / "betting_markets.json"
        )
        betting_data = json.loads(betting_markets_path.read_text(encoding="utf-8"))
        valid_ids: set[str] = {
            m["id"]
            for cat in betting_data["categories"]
            for m in cat["markets"]
        }

        markets_path = LEXICON_DIR / "markets.tr.yaml"
        markets_data: list[dict[str, Any]] = _load_entries(markets_path)
        for entry in markets_data:
            cid = entry["canonical_id"]
            assert cid in valid_ids, (
                f"markets.tr.yaml: canonical_id '{cid}' is not in "
                f"betting_markets.json closed enum. "
                f"Valid ids: {sorted(valid_ids)}"
            )


# ── Adversarial ──────────────────────────────────────────────────────────

class TestLexiconAdversarial:
    """Adversarial / regression cases for the lexicon layout."""

    def test_no_lexicon_file_is_empty(self) -> None:
        """An all-whitespace or zero-byte lexicon file must not silently pass."""
        for filename in _ALL_FILES:
            path = LEXICON_DIR / filename
            text = path.read_text(encoding="utf-8").strip()
            assert len(text) > 0, f"{filename} is empty"

    def test_no_none_top_level(self) -> None:
        """yaml.safe_load on a comments-only file returns None; reject that."""
        for filename in _ALL_FILES:
            path = LEXICON_DIR / filename
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            assert data is not None, (
                f"{filename}: yaml.safe_load returned None (file may be comments-only)"
            )

    def test_dialects_no_empty_canonical_tokens(self) -> None:
        path = LEXICON_DIR / "dialects.tr.yaml"
        data: list[dict[str, Any]] = _load_entries(path)
        for i, entry in enumerate(data):
            tokens = entry.get("canonical_tokens", [])
            for j, t in enumerate(tokens):
                assert isinstance(t, str) and len(t.strip()) > 0, (
                    f"dialects.tr.yaml[{i}].canonical_tokens[{j}]: empty token string"
                )
