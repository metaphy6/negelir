"""Phase 10 §10.29.7 — reduplication collapse support."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, NamedTuple, Optional

import yaml

from ai.common.text.turkish import lowercase_tr

_DEFAULT_REDUPLICATION_PATH: Path = (
    Path(__file__).parent / "lang_tr" / "morph" / "reduplication_pairs.tr.yaml"
)
_SCHEMA_VERSION = 1


class ReduplicationRule(NamedTuple):
    token: str
    source: str


class ReduplicationSchemaError(ValueError):
    pass


def _load_yaml(path: Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    if not isinstance(raw, dict):
        raise ReduplicationSchemaError(
            f"{path.name}: expected a YAML mapping at top level"
        )
    version = int(raw.get("_meta", {}).get("schema_version", 0))
    if version != _SCHEMA_VERSION:
        raise ReduplicationSchemaError(
            f"{path.name}: expected schema_version={_SCHEMA_VERSION}, got {version}"
        )
    return raw


def load_reduplication_pairs(path: Path | None = None) -> tuple[ReduplicationRule, ...]:
    actual_path = path or _DEFAULT_REDUPLICATION_PATH
    raw = _load_yaml(actual_path)
    rules: list[ReduplicationRule] = []
    for entry in raw.get("reduplication_pairs", []):
        if not isinstance(entry, dict):
            continue
        token = lowercase_tr(str(entry.get("token", "")).strip())
        source = str(entry.get("source", "manual"))
        if not token:
            raise ValueError(f"Invalid reduplication row: {entry}")
        rules.append(ReduplicationRule(token=token, source=source))
    return tuple(rules)


def collapse_reduplication(
    tokens: list[str],
    rules: tuple[ReduplicationRule, ...],
    event_sink: Callable[[dict[str, object]], None],
) -> list[str]:
    if not rules:
        return tokens

    allowed = {rule.token for rule in rules}
    collapsed: list[str] = []
    idx = 0
    while idx < len(tokens):
        token = tokens[idx]
        if (
            idx + 1 < len(tokens)
            and tokens[idx + 1] == token
            and token in allowed
        ):
            repeat_count = 2
            while idx + repeat_count < len(tokens) and tokens[idx + repeat_count] == token:
                repeat_count += 1
            collapsed.append(token)
            event_sink({
                "kind": "reduplication_collapsed",
                "token": token,
                "count": repeat_count,
            })
            idx += repeat_count
            continue
        collapsed.append(token)
        idx += 1
    return collapsed
