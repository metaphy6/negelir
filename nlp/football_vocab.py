"""Phase 10 §10.26.10 — Football-specific bilingual vocabulary hinting."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from ai.common.config import cfg

_FOOTBALL_VOCAB_SCHEMA_VERSION = 1
_FOOTBALL_VOCAB_PATH = Path(__file__).parent / "lang_tr" / "football" / "vocab.tr.yaml"

_FOOTBALL_VOCAB_ENTRIES: list["FootballVocabEntry"] | None = None


@dataclass(frozen=True)
class FootballVocabEntry:
    canonical_concept: str
    surface_forms_tr: tuple[str, ...]
    surface_forms_en: tuple[str, ...]
    register: str
    intent_hint: str | None = None

    @property
    def all_surface_forms(self) -> list[str]:
        return [*self.surface_forms_tr, *self.surface_forms_en]


def _normalize_surface_forms(value: Any, path: Path, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError(f"{path.name}: {field_name} must be a list")
    normalized: list[str] = []
    for idx, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise ValueError(
                f"{path.name}: {field_name}[{idx}] must be a non-empty string"
            )
        normalized.append(item.strip())
    if not normalized:
        raise ValueError(f"{path.name}: {field_name} must contain at least one surface form")
    return tuple(normalized)


def _load_football_vocab(path: Path) -> list[FootballVocabEntry]:
    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)

    if not isinstance(raw, dict):
        raise ValueError(
            f"{path.name}: expected top-level mapping, got {type(raw).__name__!r}"
        )

    meta = raw.get("_meta")
    if not isinstance(meta, dict):
        raise ValueError(f"{path.name}: missing or malformed _meta block")

    schema_version = meta.get("schema_version")
    if schema_version != _FOOTBALL_VOCAB_SCHEMA_VERSION:
        raise ValueError(
            f"{path.name}: expected _meta.schema_version={_FOOTBALL_VOCAB_SCHEMA_VERSION}, "
            f"got {schema_version!r}"
        )

    entries = raw.get("entries")
    if not isinstance(entries, list):
        raise ValueError(f"{path.name}: missing required 'entries' list")

    parsed: list[FootballVocabEntry] = []
    seen_concepts: set[str] = set()
    allowed_registers = {"media", "fan", "formal"}

    for idx, item in enumerate(entries):
        if not isinstance(item, dict):
            raise ValueError(
                f"{path.name}: entries[{idx}] must be a mapping"
            )

        canonical_concept = item.get("canonical_concept")
        if not isinstance(canonical_concept, str) or not canonical_concept.strip():
            raise ValueError(
                f"{path.name}: entries[{idx}].canonical_concept must be a non-empty string"
            )
        canonical_concept = canonical_concept.strip()
        if canonical_concept in seen_concepts:
            raise ValueError(
                f"{path.name}: duplicate canonical_concept {canonical_concept!r}"
            )
        seen_concepts.add(canonical_concept)

        register = item.get("register")
        if register not in allowed_registers:
            raise ValueError(
                f"{path.name}: entries[{idx}].register must be one of {sorted(allowed_registers)}"
            )

        surface_forms_tr = _normalize_surface_forms(item.get("surface_forms_tr"), path, "surface_forms_tr")
        surface_forms_en = _normalize_surface_forms(item.get("surface_forms_en"), path, "surface_forms_en")
        intent_hint = item.get("intent_hint")
        if intent_hint is not None and not isinstance(intent_hint, str):
            raise ValueError(
                f"{path.name}: entries[{idx}].intent_hint must be a string"
            )

        parsed.append(
            FootballVocabEntry(
                canonical_concept=canonical_concept,
                surface_forms_tr=surface_forms_tr,
                surface_forms_en=surface_forms_en,
                register=register,
                intent_hint=intent_hint.strip() if isinstance(intent_hint, str) and intent_hint.strip() else None,
            )
        )

    return parsed


def load_football_vocab(path: Path | None = None) -> list[FootballVocabEntry]:
    global _FOOTBALL_VOCAB_ENTRIES
    if _FOOTBALL_VOCAB_ENTRIES is not None and path is None:
        return _FOOTBALL_VOCAB_ENTRIES

    actual_path = Path(path) if path is not None else _FOOTBALL_VOCAB_PATH
    if not actual_path.exists():
        return []

    entries = _load_football_vocab(actual_path)
    if path is None:
        _FOOTBALL_VOCAB_ENTRIES = entries
    return entries


def get_football_vocab_hint_prefix(text: str, path: Path | None = None) -> str | None:
    if not cfg.nlp_football_vocab_hints_enabled:
        return None

    entries = load_football_vocab(path)
    if not entries:
        return None

    query = text.lower()
    candidates: list[tuple[str, FootballVocabEntry]] = []
    for entry in entries:
        for surface_form in entry.all_surface_forms:
            candidates.append((surface_form.lower(), entry))
    candidates.sort(key=lambda item: len(item[0]), reverse=True)

    for surface_form, entry in candidates:
        if re.search(rf"(?<!\w){re.escape(surface_form)}(?!\w)", query):
            return f"__concept_{entry.canonical_concept}__"
    return None


def apply_football_vocab_hint(text: str, path: Path | None = None) -> str:
    prefix = get_football_vocab_hint_prefix(text, path=path)
    return f"{prefix} {text}" if prefix else text
