from __future__ import annotations

import yaml
from pathlib import Path
from typing import NamedTuple

from ai.common.text.turkish import lowercase_tr

_SCHEMA_VERSION = 1
_DEFAULT_POSTPOSITION_STACK_PATH: Path = (
    Path(__file__).parent / "lang_tr" / "postposition_stacks.tr.yaml"
)


class PostpositionStackSchemaError(ValueError):
    """Raised when the postposition stack YAML carries an unexpected schema_version."""


class PostpositionStackRule(NamedTuple):
    rule_id: str
    first_token: str
    second_token: str
    stack_class: str
    role: str | None


class PostpositionStackMatch(NamedTuple):
    rule_id: str
    span_start: int
    span_end: int
    stack_class: str
    role: str | None
    tokens: tuple[str, str]


class UnknownPostpositionStack(NamedTuple):
    span_start: int
    span_end: int
    tokens: tuple[str, str]


def _load_yaml(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    version = int(raw.get("_meta", {}).get("schema_version", 0))
    if version != _SCHEMA_VERSION:
        raise PostpositionStackSchemaError(
            f"{path.name}: expected schema_version={_SCHEMA_VERSION}, got {version}"
        )
    return raw


def load_postposition_stack_rules(path: Path = _DEFAULT_POSTPOSITION_STACK_PATH) -> list[PostpositionStackRule]:
    raw = _load_yaml(path)
    rules: list[PostpositionStackRule] = []
    for entry in raw.get("stacks", []):
        rules.append(
            PostpositionStackRule(
                rule_id=str(entry["id"]),
                first_token=lowercase_tr(str(entry["first_token"]).strip()),
                second_token=lowercase_tr(str(entry["second_token"]).strip()),
                stack_class=str(entry["stack_class"]),
                role=str(entry["role"]).strip() if entry.get("role") is not None else None,
            )
        )
    return rules


def detect_postposition_stacks(
    tokens: list[str],
    path: Path = _DEFAULT_POSTPOSITION_STACK_PATH,
) -> tuple[list[PostpositionStackMatch], list[UnknownPostpositionStack]]:
    """Detect closed 2-postposition stacks in a token sequence.

    Valid stacks are preserved verbatim; unknown marker pairs are recorded
    so the pipeline can emit an event and fall through to the normal path.
    """
    normalized_tokens = [lowercase_tr(tok) for tok in tokens]
    rules = load_postposition_stack_rules(path)
    rule_map: dict[tuple[str, str], PostpositionStackRule] = {
        (rule.first_token, rule.second_token): rule for rule in rules
    }
    marker_tokens = {rule.first_token for rule in rules} | {rule.second_token for rule in rules}

    matches: list[PostpositionStackMatch] = []
    unknowns: list[UnknownPostpositionStack] = []
    idx = 0
    while idx + 1 < len(normalized_tokens):
        head = normalized_tokens[idx]
        tail = normalized_tokens[idx + 1]
        if head in marker_tokens and tail in marker_tokens:
            rule = rule_map.get((head, tail))
            if rule is not None:
                matches.append(
                    PostpositionStackMatch(
                        rule_id=rule.rule_id,
                        span_start=idx,
                        span_end=idx + 2,
                        stack_class=rule.stack_class,
                        role=rule.role,
                        tokens=(tokens[idx], tokens[idx + 1]),
                    )
                )
                idx += 2
                continue
            unknowns.append(
                UnknownPostpositionStack(
                    span_start=idx,
                    span_end=idx + 2,
                    tokens=(tokens[idx], tokens[idx + 1]),
                )
            )
            idx += 2
            continue
        idx += 1
    return matches, unknowns
