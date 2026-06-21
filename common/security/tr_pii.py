"""Turkish-specific PII detection and redaction helpers.

This module is a Phase 10 addition for the authentic-Turkish floor.
It supports redaction of Turkish national IDs, TR IBANs, local phone
numbers, Turkish license plates, and VKN tax numbers.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Iterable, List, Optional, Pattern, Tuple

REDACTED_TOKEN_RE = re.compile(r"\[REDACTED:([A-Z_]+):sha8=([0-9a-f]{8})\]")

TC_KIMLIK_RE = re.compile(r"(^|[^0-9])([1-9][0-9]{10})(?![0-9])")
IBAN_TR_RE = re.compile(r"(TR\d{2}(?:\s?\d{4}){5}\s?\d{2})", re.IGNORECASE)
PHONE_TR_RE = re.compile(
    r"(?:\+90|0090|0)\s?\d{3}[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}"
)
PLATE_TR_RE = re.compile(
    r"\b(0[1-9]|[1-7][0-9]|8[01])\s?[A-ZÇĞİÖŞÜ]{1,3}\s?\d{2,4}\b",
    re.IGNORECASE,
)
VKN_RE = re.compile(r"(^|[^0-9])(\d{10})(?![0-9])")

@dataclass(frozen=True)
class TrPiiSpan:
    kind: str
    start: int
    end: int


def _sha8(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]


def _validate_tc_kimlik(value: str) -> bool:
    digits = [int(ch) for ch in value]
    if digits[0] == 0:
        return False
    if len(digits) != 11:
        return False
    if sum(digits[:10]) % 10 != digits[10]:
        return False
    odd_sum = sum(digits[i] for i in range(0, 9, 2))
    even_sum = sum(digits[i] for i in range(1, 8, 2))
    return ((odd_sum * 7 - even_sum) % 10) == digits[9]


def _validate_vkn(value: str) -> bool:
    if len(value) != 10 or not value.isdigit():
        return False
    weights = [1, 2, 1, 2, 1, 2, 1, 2, 1, 2]
    total = 0
    for digit, weight in zip(value, weights):
        product = int(digit) * weight
        total += product // 10 + product % 10
    return total % 10 == 0


def _append_span(spans: list[TrPiiSpan], candidate: TrPiiSpan) -> None:
    if any(candidate.start < existing.end and existing.start < candidate.end for existing in spans):
        return
    spans.append(candidate)


def detect_tr_pii_spans(text: str) -> list[TrPiiSpan]:
    spans: list[TrPiiSpan] = []

    for match in TC_KIMLIK_RE.finditer(text):
        value = match.group(2)
        if _validate_tc_kimlik(value):
            _append_span(spans, TrPiiSpan("tc_kimlik", match.start(2), match.end(2)))

    for match in IBAN_TR_RE.finditer(text):
        _append_span(spans, TrPiiSpan("iban_tr", match.start(1), match.end(1)))

    for match in PHONE_TR_RE.finditer(text):
        _append_span(spans, TrPiiSpan("phone_tr", match.start(0), match.end(0)))

    for match in PLATE_TR_RE.finditer(text):
        _append_span(spans, TrPiiSpan("plate_tr", match.start(0), match.end(0)))

    for match in VKN_RE.finditer(text):
        value = match.group(2)
        if _validate_vkn(value):
            _append_span(spans, TrPiiSpan("vkn", match.start(2), match.end(2)))

    spans.sort(key=lambda s: (s.start, s.end))
    return spans


def redact_tr_pii(text: str) -> tuple[str, list[TrPiiSpan]]:
    spans = detect_tr_pii_spans(text)
    if not spans:
        return text, []

    redacted: list[str] = []
    offset = 0
    for span in spans:
        redacted.append(text[offset:span.start])
        snippet = text[span.start:span.end]
        redacted.append(f"[REDACTED:{span.kind.upper()}:sha8={_sha8(snippet)}]")
        offset = span.end
    redacted.append(text[offset:])
    return "".join(redacted), spans


def parse_redacted_tr_pii(text: str) -> list[tuple[str, str]]:
    return [
        (kind.lower(), sha8)
        for kind, sha8 in REDACTED_TOKEN_RE.findall(text)
    ]
