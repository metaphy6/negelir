"""Phase 10 §10.32.4 — regional/diaspora dialect normalization.

This module performs a pre-tokenization normalization pass for regional
and diaspora Turkish dialect forms that break standard lexicon-driven
analysis. It uses a closed rule table and a no-rewrite allowlist for
standard-canonical exceptions.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Callable, Iterable, NamedTuple

import yaml

from common.text.turkish import lowercase_tr

_SCHEMA_VERSION = 1
_DEFAULT_REGIONAL_DIALECT_PATH: Path = (
    Path(__file__).parent / "lang_tr" / "regional_dialect_normalization.tr.yaml"
)
_DEFAULT_DIALECT_NO_REWRITE_PATH: Path = (
    Path(__file__).parent / "lang_tr" / "dialect_no_rewrite_canonicals.tr.yaml"
)


class RegionalDialectSchemaError(ValueError):
    """Raised when a regional dialect YAML carries an unexpected schema_version."""


class RegionalDialectRule(NamedTuple):
    rule_id: str
    spoken: str
    canonical: str
    dialect_class: str
    audit_only: bool


class RegionalDialectRewrite(NamedTuple):
    rule_id: str
    dialect_class: str
    audit_only: bool
    original: str
    canonical: str


def _load_yaml(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    version = int(raw.get("_meta", {}).get("schema_version", 0))
    if version != _SCHEMA_VERSION:
        raise RegionalDialectSchemaError(
            f"{path.name}: expected schema_version={_SCHEMA_VERSION}, got {version}"
        )
    return raw


def load_regional_dialect_rules(
    path: Path = _DEFAULT_REGIONAL_DIALECT_PATH,
) -> list[RegionalDialectRule]:
    raw = _load_yaml(path)
    rules: list[RegionalDialectRule] = []
    for entry in raw.get("dialect_rules", []):
        rules.append(
            RegionalDialectRule(
                rule_id=str(entry["id"]),
                spoken=lowercase_tr(str(entry["spoken"]).strip()),
                canonical=lowercase_tr(str(entry["canonical"]).strip()),
                dialect_class=str(entry["dialect_class"]),
                audit_only=bool(entry.get("audit_only", False)),
            )
        )
    return rules


def load_dialect_no_rewrite_canonicals(
    path: Path = _DEFAULT_DIALECT_NO_REWRITE_PATH,
) -> set[str]:
    raw = _load_yaml(path)
    items = raw.get("dialect_no_rewrite_canonicals", [])
    if not isinstance(items, list):
        return set()
    return {
        lowercase_tr(str(item).strip())
        for item in items
        if isinstance(item, str) and item.strip()
    }


def apply_regional_dialect_normalize(
    text: str,
    no_rewrite_canonicals: set[str] | None = None,
    rule_path: Path | None = None,
    allowlist_path: Path | None = None,
    event_sink: Callable[[dict[str, object]], None] | None = None,
) -> tuple[str, tuple[RegionalDialectRewrite, ...], tuple[tuple[str, str], ...]]:
    """Apply regional dialect rewrite rules to normalized text.

    Returns a tuple of:
      * normalized text after rewrites,
      * regional dialect rewrites performed,
      * dialect alternatives preserved for audit_only=false rewrites.
    """
    normalized = lowercase_tr(text.strip())
    if not normalized:
        return normalized, (), ()

    allowlist = no_rewrite_canonicals or load_dialect_no_rewrite_canonicals(
        allowlist_path or _DEFAULT_DIALECT_NO_REWRITE_PATH
    )
    if normalized in allowlist:
        return normalized, (), ()

    rules = load_regional_dialect_rules(rule_path or _DEFAULT_REGIONAL_DIALECT_PATH)
    rewrites: list[RegionalDialectRewrite] = []
    dialect_alternatives: list[tuple[str, str]] = []
    output = normalized

    for rule in rules:
        if rule.spoken in allowlist:
            continue
        pattern = re.compile(rf"\b{re.escape(rule.spoken)}\b", re.UNICODE)
        if pattern.search(output):
            output = pattern.sub(rule.canonical, output)
            rewrites.append(
                RegionalDialectRewrite(
                    rule_id=rule.rule_id,
                    dialect_class=rule.dialect_class,
                    audit_only=rule.audit_only,
                    original=rule.spoken,
                    canonical=rule.canonical,
                )
            )
            if rule.audit_only and event_sink is not None:
                event_sink(
                    {
                        "kind": "dialect_normalized",
                        "dialect_class": rule.dialect_class,
                        "rule_id": rule.rule_id,
                        "original": rule.spoken,
                        "canonical": rule.canonical,
                        "audit_only": rule.audit_only,
                    }
                )
            if not rule.audit_only:
                dialect_alternatives.append((rule.canonical, rule.spoken))

    return output, tuple(rewrites), tuple(dialect_alternatives)
