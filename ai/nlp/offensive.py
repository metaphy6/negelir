"""Phase 10 §10.22.9 — Offensive input taxonomy and slur stripping.

The offensive table is a closed list of Turkish offensive tokens with a
classification class. The NLP pipeline strips `slur` tokens to a generic
sentinel before the classifier sees them and proofreader scans rendered
answers for any table hits as a defense-in-depth gate.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

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
            from common.telemetry import get_sink

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
