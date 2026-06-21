from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from common.text.turkish import lowercase_tr

_DEFAULT_PRONOUN_IRREGULAR_PATH: Path = (
    Path(__file__).parent / "lang_tr" / "morph" / "pronouns_irregular.tr.yaml"
)
_SCHEMA_VERSION = 1


class PronounIrregularSchemaError(ValueError):
    pass


@dataclass(frozen=True)
class PronounIrregularEntry:
    pronoun: str
    case: str
    surface: str
    canonical: str
    source: str


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    if not isinstance(raw, dict):
        raise PronounIrregularSchemaError(f"{path.name}: expected a YAML mapping at top level")
    meta = raw.get("_meta")
    if not isinstance(meta, dict):
        raise PronounIrregularSchemaError(f"{path.name}: missing or malformed _meta block")
    version = meta.get("schema_version")
    if version != _SCHEMA_VERSION:
        raise PronounIrregularSchemaError(
            f"{path.name}: expected schema_version={_SCHEMA_VERSION}, got {version!r}"
        )
    return raw


def load_pronouns_irregular(path: Path | None = None) -> tuple[PronounIrregularEntry, ...]:
    actual_path = path or _DEFAULT_PRONOUN_IRREGULAR_PATH
    if not actual_path.exists():
        return ()
    raw = _load_yaml(actual_path)
    entries = raw.get("entries")
    if not isinstance(entries, list):
        raise PronounIrregularSchemaError(f"{actual_path.name}: missing required 'entries' list")

    result: list[PronounIrregularEntry] = []
    seen: set[tuple[str, str]] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise PronounIrregularSchemaError(f"{actual_path.name}: each entry must be a mapping")
        pronoun = str(entry.get("pronoun", "")).strip()
        case = str(entry.get("case", "")).strip()
        surface = str(entry.get("surface", "")).strip()
        canonical = str(entry.get("canonical", "")).strip()
        source = str(entry.get("source", "manual")).strip() or "manual"
        if not pronoun or not case or not surface or not canonical:
            raise PronounIrregularSchemaError(
                f"{actual_path.name}: invalid entry {entry!r}"
            )
        key = (lowercase_tr(surface), case)
        if key in seen:
            raise PronounIrregularSchemaError(
                f"{actual_path.name}: duplicate surface/case entry {surface!r} {case!r}"
            )
        seen.add(key)
        result.append(
            PronounIrregularEntry(
                pronoun=lowercase_tr(pronoun),
                case=case,
                surface=lowercase_tr(surface),
                canonical=lowercase_tr(canonical),
                source=source,
            )
        )
    return tuple(result)


def load_pronouns_irregular_map(path: Path | None = None) -> dict[str, PronounIrregularEntry]:
    return {entry.surface: entry for entry in load_pronouns_irregular(path)}
