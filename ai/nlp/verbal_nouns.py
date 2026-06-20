from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from ai.common.text.turkish import lowercase_tr

_DEFAULT_VERBAL_NOUNS_PATH: Path = (
    Path(__file__).parent / "lang_tr" / "morph" / "verbal_nouns.tr.yaml"
)
_SCHEMA_VERSION = 1


class VerbalNounSchemaError(ValueError):
    pass


@dataclass(frozen=True)
class VerbalNounEntry:
    suffix: str
    kind: str
    source: str


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    if not isinstance(raw, dict):
        raise VerbalNounSchemaError(f"{path.name}: expected a YAML mapping at top level")
    meta = raw.get("_meta")
    if not isinstance(meta, dict):
        raise VerbalNounSchemaError(f"{path.name}: missing or malformed _meta block")
    version = meta.get("schema_version")
    if version != _SCHEMA_VERSION:
        raise VerbalNounSchemaError(
            f"{path.name}: expected schema_version={_SCHEMA_VERSION}, got {version!r}"
        )
    return raw


def load_verbal_nouns(path: Path | None = None) -> tuple[VerbalNounEntry, ...]:
    actual_path = path or _DEFAULT_VERBAL_NOUNS_PATH
    if not actual_path.exists():
        return ()
    raw = _load_yaml(actual_path)
    entries = raw.get("entries")
    if not isinstance(entries, list):
        raise VerbalNounSchemaError(f"{actual_path.name}: missing required 'entries' list")

    result: list[VerbalNounEntry] = []
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise VerbalNounSchemaError(f"{actual_path.name}: each entry must be a mapping")
        suffix = str(entry.get("suffix", "")).strip()
        kind = str(entry.get("kind", "")).strip()
        source = str(entry.get("source", "manual")).strip() or "manual"
        if not suffix or not kind:
            raise VerbalNounSchemaError(f"{actual_path.name}: invalid entry {entry!r}")
        key = lowercase_tr(suffix)
        if key in seen:
            raise VerbalNounSchemaError(f"{actual_path.name}: duplicate suffix entry {suffix!r}")
        seen.add(key)
        result.append(
            VerbalNounEntry(
                suffix=lowercase_tr(suffix),
                kind=kind,
                source=source,
            )
        )
    return tuple(result)


def load_verbal_noun_map(path: Path | None = None) -> dict[str, VerbalNounEntry]:
    return {entry.suffix: entry for entry in load_verbal_nouns(path)}
