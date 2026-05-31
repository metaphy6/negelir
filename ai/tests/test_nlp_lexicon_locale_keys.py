"""Phase 10 §10.19 — Lexicon locale future-keying tests.

Verifies that symlinks exist for locale-keyed variants (`teams.tr-TR.yaml`
→ `teams.tr.yaml`, etc.) and that LexiconLoader can resolve both patterns
(forward compatibility for the rename deferred to §R-locale).

Per AGENTS.md Rule 10: new surface → happy path + adversarial tests.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from nlp.lexicon_loader import LexiconStore

LEXICON_DIR = Path(__file__).parent.parent / "nlp" / "lexicon"

# The 7 main lexicon files (excluding `_aliases_delta` and `_diacritics`).
_BASE_LEXICONS = [
    "teams",
    "players",
    "leagues",
    "competitions",
    "markets",
    "dialects",
    "entities_negative",
]


class TestLexiconLocaleSymlinks:
    """Verify symlinks exist for locale-keyed variants (§10.19)."""

    @pytest.mark.parametrize("base_name", _BASE_LEXICONS)
    def test_symlink_exists_for_locale_variant(self, base_name: str) -> None:
        """Each `.tr.yaml` file has a symlink `.tr-TR.yaml` variant."""
        tr_file = LEXICON_DIR / f"{base_name}.tr.yaml"
        tr_TR_file = LEXICON_DIR / f"{base_name}.tr-TR.yaml"

        assert tr_file.exists(), f"Base file missing: {tr_file}"
        assert tr_TR_file.exists(), f"Symlink missing: {tr_TR_file}"
        assert tr_TR_file.is_symlink(), (
            f"{tr_TR_file.name} must be a symlink (§10.19 forward path)"
        )
        # Verify the symlink target is correct.
        assert tr_TR_file.resolve() == tr_file.resolve(), (
            f"{tr_TR_file.name} symlink target mismatch"
        )


class TestLexiconStoreFallback:
    """LexiconStore.get() resolves both `.tr.yaml` and `.tr-TR.yaml` (§10.19)."""

    def test_get_resolves_base_tr_yaml(self) -> None:
        """Requesting `.tr.yaml` works."""
        store = LexiconStore(LEXICON_DIR, reload_s=999)
        alerts = store.maybe_reload()
        assert alerts == [], f"Unexpected alerts during load: {alerts}"

        result = store.get("teams.tr.yaml")
        assert result is not None, "teams.tr.yaml should be loaded"
        meta, entries = result
        assert meta.schema_version == 1
        assert isinstance(entries, list)

    def test_get_resolves_tr_TR_yaml_via_fallback(self) -> None:
        """Requesting `.tr-TR.yaml` falls back to `.tr.yaml` (forward compat)."""
        store = LexiconStore(LEXICON_DIR, reload_s=999)
        alerts = store.maybe_reload()
        assert alerts == [], f"Unexpected alerts during load: {alerts}"

        # Request the `.tr-TR.yaml` variant.
        result = store.get("teams.tr-TR.yaml")
        assert result is not None, (
            "teams.tr-TR.yaml should resolve (either directly or via fallback)"
        )
        meta, entries = result
        assert meta.schema_version == 1
        assert isinstance(entries, list)

    def test_get_alias_index_resolves_both_patterns(self) -> None:
        """get_alias_index() also resolves both `.tr.yaml` and `.tr-TR.yaml`."""
        store = LexiconStore(LEXICON_DIR, reload_s=999)
        alerts = store.maybe_reload()
        assert alerts == [], f"Unexpected alerts during load: {alerts}"

        # Base pattern.
        idx_tr = store.get_alias_index("teams.tr.yaml")
        assert idx_tr is not None, "teams.tr.yaml alias index should be loaded"
        assert isinstance(idx_tr, dict)

        # Locale-keyed pattern.
        idx_tr_TR = store.get_alias_index("teams.tr-TR.yaml")
        assert idx_tr_TR is not None, (
            "teams.tr-TR.yaml alias index should resolve (fallback or direct)"
        )
        assert isinstance(idx_tr_TR, dict)


class TestLocaleKeyingAdversarial:
    """Adversarial: requesting non-existent locale should return None (§10.19)."""

    def test_get_returns_none_for_unsupported_locale(self) -> None:
        """Requesting an unsupported locale (e.g. `.en-GB.yaml`) returns None."""
        store = LexiconStore(LEXICON_DIR, reload_s=999)
        alerts = store.maybe_reload()
        assert alerts == [], f"Unexpected alerts during load: {alerts}"

        result = store.get("teams.en-GB.yaml")
        assert result is None, (
            "Unsupported locale variant should return None (not loaded)"
        )
