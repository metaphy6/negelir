"""Phase 10 §10.22.9 — Offensive input taxonomy and slur stripping.

The offensive table is a closed list of Turkish offensive tokens with a
classification class. The NLP pipeline strips `slur` tokens to a generic
sentinel before the classifier sees them and proofreader scans rendered
answers for any table hits as a defense-in-depth gate.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import yaml

_OFFENSIVE_SCHEMA_VERSION = 1
_DEFAULT_OFFENSIVE_PATH = Path(__file__).parent / "lang_tr" / "offensive.tr.yaml"

_OFFENSIVE_TABLE: dict[str, str] | None = None

SLUR_SENTINEL = "<STRIPPED>"
OFFENSIVE_CLASS_MILD = "mild"
OFFENSIVE_CLASS_SLUR = "slur"
OFFENSIVE_CLASS_SEVERE_THREAT = "severe_threat"


class OffensiveSchemaError(ValueError):
    """Raised when the offensive taxonomy file is malformed."""


def _load_offensive_table(path: Path) -> dict[str, str]:
    with open(path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)

    if not isinstance(raw, dict):
        raise OffensiveSchemaError(
            f"{path.name}: expected a YAML mapping at top level, "
            f"got {type(raw).__name__!r}."
        )

    meta = raw.get("_meta")
    if not isinstance(meta, dict):
        raise OffensiveSchemaError(
            f"{path.name}: missing or malformed _meta block."
        )

    schema_version = meta.get("schema_version")
    if not isinstance(schema_version, int):
        raise OffensiveSchemaError(
            f"{path.name}: _meta.schema_version must be an int."
        )
    if schema_version != _OFFENSIVE_SCHEMA_VERSION:
        raise OffensiveSchemaError(
            f"{path.name}: expected schema_version={_OFFENSIVE_SCHEMA_VERSION}, "
            f"got {schema_version}."
        )

    entries = raw.get("offensive")
    if entries is None:
        raise OffensiveSchemaError(f"{path.name}: missing required 'offensive' key.")
    if not isinstance(entries, list):
        raise OffensiveSchemaError(
            f"{path.name}: 'offensive' must be a list, got {type(entries).__name__!r}."
        )

    table: dict[str, str] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise OffensiveSchemaError(
                f"{path.name}: offensive entries must be mappings."
            )
        token = entry.get("token")
        offense_class = entry.get("class")
        if not isinstance(token, str) or not token:
            raise OffensiveSchemaError(
                f"{path.name}: offensive entry missing non-empty 'token'."
            )
        if offense_class not in {
            OFFENSIVE_CLASS_MILD,
            OFFENSIVE_CLASS_SLUR,
            OFFENSIVE_CLASS_SEVERE_THREAT,
        }:
            raise OffensiveSchemaError(
                f"{path.name}: offensive entry {token!r} has invalid class {offense_class!r}."
            )
        token_key = token.lower()
        if token_key in table:
            raise OffensiveSchemaError(
                f"{path.name}: duplicate offensive token {token!r}."
            )
        table[token_key] = offense_class
    return table


def load_offensive_table(path: Path | None = None) -> dict[str, str]:
    global _OFFENSIVE_TABLE
    if _OFFENSIVE_TABLE is not None:
        return _OFFENSIVE_TABLE
    actual_path = path or _DEFAULT_OFFENSIVE_PATH
    if not actual_path.exists():
        _OFFENSIVE_TABLE = {}
        return _OFFENSIVE_TABLE
    _OFFENSIVE_TABLE = _load_offensive_table(actual_path)
    return _OFFENSIVE_TABLE


_DEFAULT_OFFENSIVE_OBFUSCATED_PATH = Path(__file__).parent / "lang_tr" / "offensive_obfuscated.tr.yaml"
_OFFENSIVE_OBFUSCATED_PATTERNS: dict[str, list["_ObfuscatedSlurPattern"]] | None = None
_OBFUSCATED_CANONICAL_ALIAS: dict[str, str] = {
    "oran": "oç",
}


def _compile_obfuscated_pattern(pattern: str) -> re.Pattern[str]:
    escaped_chars: list[str] = []
    for char in pattern:
        if char == "*":
            escaped_chars.append(".*")
        elif char == "?":
            escaped_chars.append(".")
        else:
            escaped_chars.append(re.escape(char))
    return re.compile(rf"\b{''.join(escaped_chars)}\b", re.IGNORECASE)


@dataclass(frozen=True)
class _ObfuscatedSlurPattern:
    pattern: str
    canonical: str
    context_negation_regex: str
    regex: re.Pattern[str]
    negation_regex: re.Pattern[str] | None
    pattern_id: str


def _load_offensive_obfuscated_patterns(path: Path) -> list[_ObfuscatedSlurPattern]:
    with open(path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)

    if not isinstance(raw, dict):
        raise OffensiveSchemaError(
            f"{path.name}: expected a YAML mapping at top level, got {type(raw).__name__!r}."
        )

    meta = raw.get("_meta")
    if not isinstance(meta, dict):
        raise OffensiveSchemaError(
            f"{path.name}: missing or malformed _meta block."
        )

    schema_version = meta.get("schema_version")
    if not isinstance(schema_version, int):
        raise OffensiveSchemaError(
            f"{path.name}: _meta.schema_version must be an int."
        )
    if schema_version != _OFFENSIVE_SCHEMA_VERSION:
        raise OffensiveSchemaError(
            f"{path.name}: expected schema_version={_OFFENSIVE_SCHEMA_VERSION}, "
            f"got {schema_version}."
        )

    entries = raw.get("entries")
    if entries is None:
        raise OffensiveSchemaError(f"{path.name}: missing required 'entries' key.")
    if not isinstance(entries, list):
        raise OffensiveSchemaError(
            f"{path.name}: 'entries' must be a list, got {type(entries).__name__!r}."
        )

    patterns: list[_ObfuscatedSlurPattern] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise OffensiveSchemaError(
                f"{path.name}: entries must be mappings."
            )

        pattern = entry.get("pattern")
        canonical = entry.get("canonical")
        context_negation_regex = entry.get("context_negation_regex", "")

        if not isinstance(pattern, str) or not pattern:
            raise OffensiveSchemaError(
                f"{path.name}: obfuscated entry missing non-empty 'pattern'."
            )
        if not isinstance(canonical, str) or not canonical:
            raise OffensiveSchemaError(
                f"{path.name}: obfuscated entry {pattern!r} missing non-empty 'canonical'."
            )
        if not isinstance(context_negation_regex, str):
            raise OffensiveSchemaError(
                f"{path.name}: obfuscated entry {pattern!r} has invalid 'context_negation_regex'."
            )

        regex = _compile_obfuscated_pattern(pattern)
        negation_re = (
            re.compile(context_negation_regex, re.IGNORECASE)
            if context_negation_regex
            else None
        )
        patterns.append(_ObfuscatedSlurPattern(
            pattern=pattern,
            canonical=canonical,
            context_negation_regex=context_negation_regex,
            regex=regex,
            negation_regex=negation_re,
            pattern_id=f"{path.name}:{index}",
        ))
    return patterns


def load_offensive_obfuscated_patterns(path: Path | None = None) -> list[_ObfuscatedSlurPattern]:
    global _OFFENSIVE_OBFUSCATED_PATTERNS
    actual_path = (path or _DEFAULT_OFFENSIVE_OBFUSCATED_PATH).resolve()
    cache_key = str(actual_path)
    if _OFFENSIVE_OBFUSCATED_PATTERNS is None:
        _OFFENSIVE_OBFUSCATED_PATTERNS = {}
    if cache_key in _OFFENSIVE_OBFUSCATED_PATTERNS:
        return _OFFENSIVE_OBFUSCATED_PATTERNS[cache_key]
    if not actual_path.exists():
        _OFFENSIVE_OBFUSCATED_PATTERNS[cache_key] = []
        return _OFFENSIVE_OBFUSCATED_PATTERNS[cache_key]
    _OFFENSIVE_OBFUSCATED_PATTERNS[cache_key] = _load_offensive_obfuscated_patterns(actual_path)
    return _OFFENSIVE_OBFUSCATED_PATTERNS[cache_key]


def replace_obfuscated_slurs(
    text: str,
    path: Path | None = None,
    event_sink: Callable[[dict[str, object]], None] | None = None,
) -> str:
    patterns = load_offensive_obfuscated_patterns(path)
    if not patterns:
        return text

    normalized = text
    normalized_lower = normalized.lower()

    for rule in patterns:
        if rule.negation_regex and rule.negation_regex.search(normalized_lower):
            if event_sink is not None:
                event_sink({
                    "kind": "obfuscated_slur_negated",
                    "pattern_id": rule.pattern_id,
                })
            continue

        if rule.regex.search(normalized_lower):
            canonical = _OBFUSCATED_CANONICAL_ALIAS.get(rule.canonical, rule.canonical)
            normalized = rule.regex.sub(canonical, normalized)
            normalized_lower = normalized.lower()

    return normalized


def classify_offensive_token(token: str, path: Path | None = None) -> str | None:
    return load_offensive_table(path).get(token.lower())


def strip_offensive_slurs(tokens: list[str], path: Path | None = None) -> tuple[list[str], list[str]]:
    table = load_offensive_table(path)
    stripped: list[str] = []
    out: list[str] = []
    counts: dict[str, int] = {
        OFFENSIVE_CLASS_MILD: 0,
        OFFENSIVE_CLASS_SLUR: 0,
        OFFENSIVE_CLASS_SEVERE_THREAT: 0,
    }
    for tok in tokens:
        offense_class = table.get(tok.lower())
        if offense_class is not None:
            counts[offense_class] += 1
        if offense_class == OFFENSIVE_CLASS_SLUR:
            out.append(SLUR_SENTINEL)
            stripped.append(tok)
        else:
            out.append(tok)

    if any(counts.values()):
        try:
            from ai.common.telemetry import get_sink

            sink = get_sink()
            for offense_class, count in counts.items():
                if count:
                    sink.record_nlp_offensive_input(offense_class, count)
        except Exception:  # noqa: BLE001
            pass  # non-blocking

    return out, stripped


def contains_offensive_phrase(text: str, path: Path | None = None) -> bool:
    table = load_offensive_table(path)
    if not table:
        return False
    text_lower = text.lower()
    for phrase in table:
        if re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", text_lower):
            return True
    return False
