"""Phase 10 §10.26.3 — Tests for IME layout hint inference and autocorrect cascades."""
from __future__ import annotations

import time
from pathlib import Path

from nlp.ime import (
    AutocorrectCascade,
    AutocorrectCascadeDebouncer,
    KeyboardLayoutHintCache,
    find_autocorrect_cascade,
    infer_keyboard_layout_hint,
    normalize_keyboard_hint,
)
from nlp.vendor.symspell import AliasHit, SymSpellIndex


def _build_symspell(terms: list[tuple[str, str]]) -> SymSpellIndex:
    idx = SymSpellIndex(max_edit_distance=2)
    for term, cid in terms:
        idx.add_term(term, AliasHit(canonical_id=cid, kind="team", lexicon_version="1.0.0"))
    return idx


class TestKeyboardLayoutHintCache:
    def test_cache_key_is_sha256_hex(self):
        cache = KeyboardLayoutHintCache(ttl_s=3600)
        cache.set("client-1", "q")
        key = cache._hash_client_id("client-1")
        assert len(key) == 64
        assert all(c in "0123456789abcdef" for c in key)

    def test_cache_expires_after_ttl(self):
        now = [0.0]
        cache = KeyboardLayoutHintCache(ttl_s=10, clock=lambda: now[0])
        cache.set("client-1", "f")
        assert cache.get("client-1") == "f"

        now[0] = 11.0
        assert cache.get("client-1") is None


class TestKeyboardLayoutInference:
    def test_infer_keyboard_layout_prefers_f_when_q_has_higher_cost(self):
        idx = _build_symspell([("abc", "team-1")])
        inferred = infer_keyboard_layout_hint(["fbc"], idx, client_id="client-1", cache=KeyboardLayoutHintCache(ttl_s=3600))
        assert inferred == "f"

    def test_infer_keyboard_layout_uses_explicit_hint(self):
        idx = _build_symspell([("abc", "team-1")])
        inferred = infer_keyboard_layout_hint(["fbc"], idx, explicit_hint="q", client_id="client-1", cache=KeyboardLayoutHintCache(ttl_s=3600))
        assert inferred == "q"

    def test_infer_keyboard_layout_uses_client_cache(self):
        clock = [0.0]
        cache = KeyboardLayoutHintCache(ttl_s=3600, clock=lambda: clock[0])
        idx = _build_symspell([("abc", "team-1")])

        first = infer_keyboard_layout_hint(["fbc"], idx, client_id="client-1", cache=cache)
        assert first == "f"
        clock[0] = 100.0
        second = infer_keyboard_layout_hint(["abc"], idx, client_id="client-1", cache=cache)
        assert second == "f"


class TestAutocorrectCascadeLoader:
    def test_find_autocorrect_cascade_returns_known_entry(self):
        cascade = find_autocorrect_cascade("beşiktas")
        assert cascade is not None
        assert cascade.canonical_form == "beşiktaş"
        assert "q" in cascade.layouts
        assert "f" in cascade.layouts

    def test_find_autocorrect_cascade_returns_none_for_unknown_token(self):
        assert find_autocorrect_cascade("unknown-token") is None


class TestAutocorrectCascadeDebouncer:
    def test_debouncer_blocks_within_cooldown(self):
        now = [0.0]
        debouncer = AutocorrectCascadeDebouncer(cooldown_s=60, clock=lambda: now[0])
        assert debouncer.should_emit("beşiktas") is True
        assert debouncer.should_emit("beşiktas") is False
        now[0] = 61.0
        assert debouncer.should_emit("beşiktas") is True


class TestNormalizeKeyboardHint:
    def test_normalize_keyboard_hint_accepts_known_values(self):
        assert normalize_keyboard_hint("q") == "q"
        assert normalize_keyboard_hint("unknown") == "unknown"

    def test_normalize_keyboard_hint_rejects_invalid_values(self):
        try:
            normalize_keyboard_hint("dvorak")
        except ValueError as exc:
            assert "keyboard_hint='dvorak'" in str(exc)
        else:
            raise AssertionError("Expected ValueError")
