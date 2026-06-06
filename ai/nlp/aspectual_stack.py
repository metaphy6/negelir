"""Phase 10 §10.32.2 — aspectual-stack detection for Turkish modality routing.

This module detects closed Turkish aspectual-stack constructions that
must not be treated as ordinary future-predictive clauses. The rules are
loaded from a YAML table and are intentionally closed and deterministic.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, NamedTuple, Optional

import yaml

_ASPECTUAL_SCHEMA_VERSION = 1
_DEFAULT_ASPECTUAL_STACKS_PATH: Path = (
    Path(__file__).parent / "lang_tr" / "aspectual_stacks.tr.yaml"
)


class AspectualStackSchemaError(ValueError):
    """Raised when the aspectual stack YAML carries an unexpected schema_version."""


class AspectualStackRule(NamedTuple):
    """A single closed Turkish aspectual-stack rule."""

    inner_aspect: str
    outer_aspect: str
    modality_class: str
    patterns: list[re.Pattern[str]]
    confidence: float


class AspectualStackDetection(NamedTuple):
    """Result of aspectual-stack detection."""

    modality_class: str
    confidence: float
    matched_pattern: str


def _load_yaml(path: Path, expected_version: int) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    version = int(raw.get("_meta", {}).get("schema_version", 0))
    if version != expected_version:
        raise AspectualStackSchemaError(
            f"{path.name}: expected schema_version={expected_version}, got {version}"
        )
    return raw


def _compile_patterns(patterns: Iterable[str]) -> list[re.Pattern[str]]:
    return [re.compile(pattern, re.UNICODE | re.IGNORECASE) for pattern in patterns]


def load_aspectual_stack_rules(path: Path = _DEFAULT_ASPECTUAL_STACKS_PATH) -> list[AspectualStackRule]:
    raw = _load_yaml(path, _ASPECTUAL_SCHEMA_VERSION)
    rules: list[AspectualStackRule] = []
    for entry in raw["stack_rules"]:
        rules.append(
            AspectualStackRule(
                inner_aspect=str(entry["inner_aspect"]),
                outer_aspect=str(entry["outer_aspect"]),
                modality_class=str(entry["modality_class"]),
                patterns=_compile_patterns(entry["patterns"]),
                confidence=float(entry.get("confidence", 0.80)),
            )
        )
    return rules


def detect_aspectual_stack(text: str, max_depth: int = 3) -> Optional[AspectualStackDetection]:
    normalized = text.strip().casefold()
    if not normalized:
        return None

    aspectual_markers = re.findall(
        r"\b(?:olacak(?:sa|se)?|olur(?:sa|se)?|olabilir|olmuş|oluyor|oynuyor|oynayabilir|başlamak|kazanmak|girecek|gelecek|yenmiş|gelmiş|kazanmış|bitmiş|oynamış|bitiyor|kazanıyor)\b",
        normalized,
    )
    if len(aspectual_markers) > max_depth:
        return None

    candidates: list[AspectualStackDetection] = []
    for rule in load_aspectual_stack_rules():
        for pattern in rule.patterns:
            if pattern.search(normalized):
                candidates.append(
                    AspectualStackDetection(
                        modality_class=rule.modality_class,
                        confidence=rule.confidence,
                        matched_pattern=pattern.pattern,
                    )
                )
                break

    if not candidates:
        return None

    if len(candidates) == 1:
        return candidates[0]

    priority = [
        "counterfactual_past",
        "future_perfect_evidential",
        "perfect_modal_potential",
        "obligative",
        "evidential_hearsay",
        "progressive_epistemic",
        "epistemic_potential",
        "future_relative_clause_attributive",
        "inferential_past",
        "imminent_progressive",
    ]
    candidates.sort(
        key=lambda item: priority.index(item.modality_class)
        if item.modality_class in priority
        else len(priority)
    )
    return candidates[0]
