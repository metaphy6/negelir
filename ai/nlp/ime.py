"""Phase 10 §10.26.3 — Turkish IME layout hint inference and autocorrect cascade support."""
from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Callable, Literal, NamedTuple, Optional

import yaml
from nlp.vendor.symspell import SymSpellIndex

KeyboardLayout = Literal["q", "f", "swipe", "unknown"]

_AUTOCORRECT_CASCADE_PATH = Path(__file__).resolve().parents[0] / "lang_tr" / "ime" / "autocorrect_cascade.tr.yaml"


class AutocorrectCascade(NamedTuple):
    wrong_form: str
    canonical_form: str
    layouts: tuple[KeyboardLayout, ...]


class KeyboardLayoutHintCache:
    """In-memory TTL cache for inferred keyboard layout hints."""

    def __init__(self, ttl_s: int = 3600, clock: Callable[[], float] = time.time) -> None:
        if ttl_s < 1:
            raise ValueError("KeyboardLayoutHintCache ttl_s must be >= 1")
        self._ttl_s = ttl_s
        self._clock = clock
        self._store: dict[str, tuple[float, KeyboardLayout]] = {}

    @staticmethod
    def _hash_client_id(client_id: str) -> str:
        return hashlib.sha256(client_id.encode("utf-8")).hexdigest()

    def get(self, client_id: str) -> KeyboardLayout | None:
        key = self._hash_client_id(client_id)
        entry = self._store.get(key)
        if entry is None:
            return None
        ts, layout = entry
        if self._clock() - ts > self._ttl_s:
            del self._store[key]
            return None
        return layout

    def set(self, client_id: str, layout: KeyboardLayout) -> None:
        self._store[self._hash_client_id(client_id)] = (self._clock(), layout)


class AutocorrectCascadeDebouncer:
    """Debounces autocorrect-cascade events per wrong form."""

    def __init__(self, cooldown_s: int = 60, clock: Callable[[], float] = time.time) -> None:
        if cooldown_s < 0:
            raise ValueError("AutocorrectCascadeDebouncer cooldown_s must be >= 0")
        self._cooldown_s = cooldown_s
        self._clock = clock
        self._last_emitted: dict[str, float] = {}

    def should_emit(self, wrong_form: str) -> bool:
        now = self._clock()
        last = self._last_emitted.get(wrong_form)
        if last is None or now - last > self._cooldown_s:
            self._last_emitted[wrong_form] = now
            return True
        return False


def normalize_keyboard_hint(value: str | None) -> KeyboardLayout | None:
    if value is None:
        return None
    hint = str(value).strip().lower()
    if hint in {"q", "f", "swipe", "unknown"}:
        return hint
    raise ValueError(
        f"keyboard_hint={value!r} not in {{'q','f','swipe','unknown'}}"
    )


def infer_keyboard_layout_hint(
    tokens: list[str],
    symspell: SymSpellIndex,
    *,
    explicit_hint: str | None = None,
    client_id: str | None = None,
    cache: KeyboardLayoutHintCache | None = None,
    max_ambiguous_tokens: int = 3,
    clock: Callable[[], float] = time.time,
) -> KeyboardLayout:
    explicit_hint_normalized = normalize_keyboard_hint(explicit_hint) if explicit_hint is not None else None
    if explicit_hint_normalized in {"q", "f", "swipe"}:
        return explicit_hint_normalized

    if client_id and cache is not None:
        cached = cache.get(client_id)
        if cached is not None and cached != "unknown":
            return cached

    q_hits = 0
    f_hits = 0
    ambiguous = 0

    for token in tokens:
        if len(token) <= 2:
            continue

        q_candidate = symspell.lookup(token, layout="q")
        f_candidate = symspell.lookup(token, layout="f")
        if q_candidate is None and f_candidate is None:
            continue

        ambiguous += 1
        if q_candidate is not None and f_candidate is None:
            q_hits += 1
        elif f_candidate is not None and q_candidate is None:
            f_hits += 1
        elif q_candidate is not None and f_candidate is not None:
            if q_candidate.edit_distance < f_candidate.edit_distance:
                q_hits += 1
            elif f_candidate.edit_distance < q_candidate.edit_distance:
                f_hits += 1

        if ambiguous >= max_ambiguous_tokens:
            break

    if q_hits > f_hits:
        inferred = "q"
    elif f_hits > q_hits:
        inferred = "f"
    else:
        inferred = "unknown"

    if client_id and cache is not None:
        cache.set(client_id, inferred)

    return inferred


def _load_autocorrect_cascades() -> dict[str, AutocorrectCascade]:
    raw = yaml.safe_load(_AUTOCORRECT_CASCADE_PATH.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError("autocorrect_cascade.tr.yaml must be a mapping")

    cascades: dict[str, AutocorrectCascade] = {}
    for wrong_form, data in raw.items():
        if not isinstance(data, dict):
            raise ValueError(f"autocorrect_cascade.tr.yaml.{wrong_form} must be a mapping")
        canonical_form = data.get("canonical_form")
        layouts = data.get("layouts")
        if not isinstance(canonical_form, str):
            raise ValueError(f"autocorrect_cascade.tr.yaml.{wrong_form}.canonical_form must be a string")
        if not isinstance(layouts, list) or not layouts:
            raise ValueError(f"autocorrect_cascade.tr.yaml.{wrong_form}.layouts must be a non-empty list")
        normalized_layouts: list[KeyboardLayout] = []
        for item in layouts:
            if not isinstance(item, str):
                raise ValueError(
                    f"autocorrect_cascade.tr.yaml.{wrong_form}.layouts entries must be strings"
                )
            normalized_layouts.append(normalize_keyboard_hint(item))
        cascades[wrong_form] = AutocorrectCascade(
            wrong_form=wrong_form,
            canonical_form=canonical_form,
            layouts=tuple(normalized_layouts),
        )
    return cascades


def find_autocorrect_cascade(token: str) -> AutocorrectCascade | None:
    return _load_autocorrect_cascades().get(token)
