"""Phase 10 §10.28.1 — consonant alternation tolerance.

This module loads the closed consonant alternation table and applies a
small lexicon-probing repair pass for softened / unsoftened stem finals.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, NamedTuple, Optional

import yaml

from common.text.turkish import lowercase_tr

_DEFAULT_CONSONANT_ALTERNATION_PATH: Path = (
    Path(__file__).parent / "lang_tr" / "spelling" / "consonant_alternations.tr.yaml"
)
_SCHEMA_VERSION = 1

_VOWELS = set("aeıioöuü")
_SOFTENING_MAP = {"p": "b", "ç": "c", "t": "d", "k": "ğ"}
_UNSOFTENING_MAP = {soft: hard for hard, soft in _SOFTENING_MAP.items()}


class ConsonantAlternationRule(NamedTuple):
    stem: str
    final_char: str
    soften_to: str
    soften_blocked: bool
    source: str


class ConsonantAlternationSchemaError(ValueError):
    """Raised when the alternation YAML carries an unexpected schema version."""


def _load_yaml(path: Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    version = int(raw.get("_meta", {}).get("schema_version", 0))
    if version != _SCHEMA_VERSION:
        raise ConsonantAlternationSchemaError(
            f"{path.name}: expected schema_version={_SCHEMA_VERSION}, got {version}"
        )
    return raw


def load_consonant_alternations(
    path: Path = _DEFAULT_CONSONANT_ALTERNATION_PATH,
) -> tuple[ConsonantAlternationRule, ...]:
    raw = _load_yaml(path)
    alternations: list[ConsonantAlternationRule] = []
    for entry in raw.get("consonant_alternations", []):
        if not isinstance(entry, dict):
            continue
        stem = lowercase_tr(str(entry.get("stem", "")).strip())
        final_char = lowercase_tr(str(entry.get("final_char", "")).strip())
        soften_to = lowercase_tr(str(entry.get("soften_to", "")).strip())
        soften_blocked = bool(entry.get("soften_blocked", False))
        source = str(entry.get("source", "manual"))

        if not stem or not final_char or not soften_to:
            raise ValueError(f"Invalid consonant alternation row: {entry}")
        if stem[-1] != final_char:
            raise ValueError(
                f"consonant_alternations.tr.yaml: stem {stem!r} must end in final_char {final_char!r}"
            )
        if final_char not in _SOFTENING_MAP:
            raise ValueError(
                f"consonant_alternations.tr.yaml: final_char {final_char!r} must be one of {sorted(_SOFTENING_MAP)}"
            )
        if _SOFTENING_MAP[final_char] != soften_to:
            raise ValueError(
                f"consonant_alternations.tr.yaml: soften_to for {final_char!r} must be {_SOFTENING_MAP[final_char]!r}"
            )

        alternations.append(
            ConsonantAlternationRule(
                stem=stem,
                final_char=final_char,
                soften_to=soften_to,
                soften_blocked=soften_blocked,
                source=source,
            )
        )
    return tuple(alternations)


def _lookup_term(token: str, lookup: Any) -> Optional[str]:
    if lookup is None:
        return None
    candidate = lookup(token)
    if candidate is None:
        return None
    if isinstance(candidate, str):
        return candidate
    return getattr(candidate, "term", None)


def _find_stem_final_char_index(token: str) -> Optional[int]:
    i = len(token) - 1
    while i >= 0 and token[i] not in _VOWELS:
        i -= 1
    if i < 0:
        return None
    i -= 1
    if i < 0:
        return None
    if token[i] in _SOFTENING_MAP or token[i] in _UNSOFTENING_MAP:
        return i
    return None


def _matches_rule(token: str, index: int, rule: ConsonantAlternationRule) -> bool:
    token_prefix = token[: index + 1]
    softened_prefix = rule.stem[:-1] + rule.soften_to
    return token_prefix == rule.stem or token_prefix == softened_prefix


def _apply_alternation(token: str, index: int, char_map: dict[str, str]) -> str:
    replacement = char_map[token[index]]
    return token[:index] + replacement + token[index + 1 :]


def tolerate_consonant_alternation(
    token: str,
    lookup: Any,
    no_strip_canonicals: set[str] | None = None,
    alternations: tuple[ConsonantAlternationRule, ...] | None = None,
) -> tuple[str, dict[str, str] | None]:
    if not token:
        return token, None
    no_strip = no_strip_canonicals or set()
    if token in no_strip:
        return token, None

    exact_candidate = _lookup_term(token, lookup)
    if exact_candidate == token:
        return token, None

    alternations = alternations or load_consonant_alternations()
    index = _find_stem_final_char_index(token)
    if index is None:
        return token, None

    for rule in alternations:
        if not _matches_rule(token, index, rule):
            continue
        if rule.soften_blocked:
            return token, None

        if token[index] in _SOFTENING_MAP:
            softened = _apply_alternation(token, index, _SOFTENING_MAP)
            softened_candidate = _lookup_term(softened, lookup)
            if softened_candidate is not None:
                return (
                    softened_candidate,
                    {
                        "kind": "consonant_softening_repaired",
                        "original": token,
                        "repaired": softened_candidate,
                    },
                )

        if token[index] in _UNSOFTENING_MAP:
            unsoftened = _apply_alternation(token, index, _UNSOFTENING_MAP)
            unsoftened_candidate = _lookup_term(unsoftened, lookup)
            if unsoftened_candidate is not None:
                return (
                    unsoftened_candidate,
                    {
                        "kind": "consonant_softening_repaired",
                        "original": token,
                        "repaired": unsoftened_candidate,
                    },
                )

    return token, None
