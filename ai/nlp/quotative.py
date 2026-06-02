"""Phase 10 §10.32.1 — quotative frame detection for reported-speech firewall.

This module is a small, deterministic guard that detects Turkish quotative
frames and routes them away from predict.* when the frame is sufficiently
confident. The rule tables are closed and loaded from YAML.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, NamedTuple, Optional

import yaml

_QUOTATIVE_SCHEMA_VERSION = 1
_QUOTATIVE_NEGATION_SCHEMA_VERSION = 1

_DEFAULT_QUOTATIVE_FRAMES_PATH: Path = (
    Path(__file__).parent / "lang_tr" / "quotative_frames.tr.yaml"
)
_DEFAULT_QUOTATIVE_NEGATION_PATH: Path = (
    Path(__file__).parent / "lang_tr" / "quotative_negation.tr.yaml"
)


class QuotativeSchemaError(ValueError):
    """Raised when the quoted-rule YAML carries an unexpected schema_version."""


class QuotativeDetection(NamedTuple):
    """Result of quotative frame detection."""

    frame_class: str
    confidence: float
    negated: bool


def _load_yaml(path: Path, schema_key: str, expected_version: int) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    version = int(raw.get("_meta", {}).get("schema_version", 0))
    if version != expected_version:
        raise QuotativeSchemaError(
            f"{path.name}: expected schema_version={expected_version}, got {version}"
        )
    return raw


def _compile_patterns(patterns: Iterable[str]) -> list[re.Pattern[str]]:
    return [re.compile(pattern, re.UNICODE | re.IGNORECASE) for pattern in patterns]


def load_quotative_frame_rules(path: Path = _DEFAULT_QUOTATIVE_FRAMES_PATH) -> list[tuple[str, list[re.Pattern[str]], float]]:
    raw = _load_yaml(path, "quotative_frames", _QUOTATIVE_SCHEMA_VERSION)
    rules = []
    for frame_class, entry in raw["frame_classes"].items():
        patterns = _compile_patterns(entry["patterns"])
        confidence = float(entry.get("confidence", 0.75))
        rules.append((frame_class, patterns, confidence))
    return rules


def load_quotative_negation_patterns(path: Path = _DEFAULT_QUOTATIVE_NEGATION_PATH) -> list[re.Pattern[str]]:
    raw = _load_yaml(path, "quotative_negation", _QUOTATIVE_NEGATION_SCHEMA_VERSION)
    return _compile_patterns(raw["negation_patterns"])


def detect_quotative_frame(text: str) -> Optional[QuotativeDetection]:
    """Detect a quotative frame in normalized Turkish text.

    Returns a QuotativeDetection if a quotative frame is found, otherwise None.
    """
    normalized = text.strip().casefold()
    if not normalized:
        return None

    negation_patterns = load_quotative_negation_patterns()
    negated = any(pattern.search(normalized) for pattern in negation_patterns)

    best_class: Optional[str] = None
    best_confidence = 0.0
    for frame_class, patterns, confidence in load_quotative_frame_rules():
        for pattern in patterns:
            if pattern.search(normalized):
                if confidence > best_confidence:
                    best_confidence = confidence
                    best_class = frame_class
                break

    if best_class is None:
        if not negated:
            return None
        best_class = "attributed_source"
        best_confidence = 0.70

    return QuotativeDetection(
        frame_class=best_class,
        confidence=best_confidence,
        negated=negated,
    )
