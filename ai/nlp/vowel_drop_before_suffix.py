"""Phase 10 §10.29.2 — vowel-drop-before-suffix restoration."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, NamedTuple, Optional

import yaml

from common.text.turkish import _load_suffix_families, lowercase_tr

_DEFAULT_VOWEL_DROP_BEFORE_SUFFIX_PATH: Path = (
    Path(__file__).parent / "lang_tr" / "spelling" / "vowel_drop_before_suffix.tr.yaml"
)
_SCHEMA_VERSION = 1
_VOWELS = set("aeıioöuü")


class VowelDropBeforeSuffixRule(NamedTuple):
    stem: str
    dropped_form: str
    suffix_classes: tuple[str, ...]
    source: str


class VowelDropBeforeSuffixSchemaError(ValueError):
    """Raised when the vowel-drop-before-suffix YAML carries an unexpected schema version."""


def _load_yaml(path: Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    if not isinstance(raw, dict):
        raise VowelDropBeforeSuffixSchemaError(
            f"{path.name}: expected a YAML mapping at top level"
        )
    version = int(raw.get("_meta", {}).get("schema_version", 0))
    if version != _SCHEMA_VERSION:
        raise VowelDropBeforeSuffixSchemaError(
            f"{path.name}: expected schema_version={_SCHEMA_VERSION}, got {version}"
        )
    return raw


_SUFFIX_CLASS_ALIASES: dict[str, str] = {
    "acc": "accusative",
    "gen": "genitive",
    "dat": "dative",
    "loc": "locative",
    "abl": "ablative",
    "pl": "plural",
}


def _normalize_suffix_class(value: str) -> str:
    return _SUFFIX_CLASS_ALIASES.get(value, value)


def _suffix_candidates_for_classes(suffix_classes: tuple[str, ...]) -> set[str]:
    families = _load_suffix_families()
    normalized_classes = { _normalize_suffix_class(cls) for cls in suffix_classes }
    allowed: set[str] = set()
    for family in families:
        name = str(family.get("name", "")).strip()
        if name not in normalized_classes:
            continue
        allowed.update(str(s).strip() for s in family.get("vowel_final_forms", []) if isinstance(s, str))
        allowed.update(str(s).strip() for s in family.get("consonant_final_forms", []) if isinstance(s, str))
    return allowed


def load_vowel_drop_before_suffix_rules(
    path: Path | None = None,
) -> tuple[VowelDropBeforeSuffixRule, ...]:
    actual_path = path or _DEFAULT_VOWEL_DROP_BEFORE_SUFFIX_PATH
    raw = _load_yaml(actual_path)
    rules: list[VowelDropBeforeSuffixRule] = []

    families = _load_suffix_families()
    valid_classes = {str(family.get("name", "")).strip() for family in families}

    for entry in raw.get("vowel_drop_before_suffix", []):
        if not isinstance(entry, dict):
            continue
        stem = lowercase_tr(str(entry.get("stem", "")).strip())
        dropped_form = lowercase_tr(str(entry.get("dropped_form", "")).strip())
        source = str(entry.get("source", "manual"))
        suffix_classes_raw = entry.get("suffix_classes", [])
        if not isinstance(suffix_classes_raw, list):
            raise ValueError(f"Invalid suffix_classes for {entry}")
        suffix_classes = tuple(
            _normalize_suffix_class(str(item).strip())
            for item in suffix_classes_raw
            if isinstance(item, str) and item.strip()
        )

        if not stem or not dropped_form or not suffix_classes:
            raise ValueError(f"Invalid vowel-drop-before-suffix row: {entry}")
        for suffix_class in suffix_classes:
            if suffix_class not in valid_classes:
                raise ValueError(
                    f"vowel_drop_before_suffix.tr.yaml: unknown suffix_class {suffix_class!r}"
                )
        rules.append(
            VowelDropBeforeSuffixRule(
                stem=stem,
                dropped_form=dropped_form,
                suffix_classes=suffix_classes,
                source=source,
            )
        )
    return tuple(rules)


def _lookup_term(token: str, lookup: Any, exact_only: bool = False) -> Optional[str]:
    if lookup is None:
        return None
    candidate = lookup(token)
    if candidate is None:
        return None
    if isinstance(candidate, str):
        return candidate if not exact_only or candidate == token else None
    term = getattr(candidate, "term", None)
    if term is None:
        return None
    return term if not exact_only or term == token else None


def tolerate_vowel_drop_before_suffix(
    token: str,
    lookup: Any,
    rules: tuple[VowelDropBeforeSuffixRule, ...] | None = None,
) -> tuple[str, dict[str, str] | None]:
    if not token:
        return token, None
    exact_candidate = _lookup_term(token, lookup, exact_only=True)
    if exact_candidate == token:
        return token, None

    rules = rules or load_vowel_drop_before_suffix_rules()
    for rule in rules:
        if not token.startswith(rule.dropped_form):
            continue
        suffix = token[len(rule.dropped_form) :]
        if not suffix or suffix[0] not in _VOWELS:
            continue

        allowed_suffixes = _suffix_candidates_for_classes(rule.suffix_classes)
        if suffix not in allowed_suffixes:
            continue

        candidate = _lookup_term(rule.stem + suffix, lookup, exact_only=True)
        if candidate is not None:
            return (
                candidate,
                {
                    "kind": "vowel_drop_repaired",
                    "original": token,
                    "repaired": candidate,
                    "stem": rule.stem,
                    "suffix": suffix,
                    "source": rule.source,
                },
            )

    return token, None


def validate_vowel_drop_before_suffix_coverage(
    stems: list[str] | set[str],
    rules: tuple[VowelDropBeforeSuffixRule, ...] | None = None,
) -> list[str]:
    rules = rules or load_vowel_drop_before_suffix_rules()
    stem_set = {rule.stem for rule in rules}
    failures: list[str] = []
    pattern = re.compile(r"[pçtkbdg][lnrzm]$")

    for raw_stem in sorted({lowercase_tr(str(stem).strip()) for stem in stems if str(stem).strip()}):
        if not raw_stem or not pattern.search(raw_stem):
            continue
        if raw_stem not in stem_set:
            failures.append(
                f"vowel_drop_before_suffix.tr.yaml missing required LeagueCatalog stem {raw_stem!r}"
            )
    return failures
