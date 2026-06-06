from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from nlp.numbers.apostrophe_suffixed import parse_apostrophe_suffixed_numeric

_NUMERIC_CONTEXT_PATH = Path(__file__).resolve().parent / "lang_tr" / "numeric_context.tr.yaml"
_NUMERIC_CONTEXT_RULES: dict[str, set[str]] | None = None

_DECIMAL_NUMBER_RE = re.compile(r"^(\d+)[.,](\d+)$")
_SCORE_LINE_RE = re.compile(r"^(\d+)[-:,](\d+)$")


def _load_numeric_context_rules() -> dict[str, set[str]]:
    global _NUMERIC_CONTEXT_RULES
    if _NUMERIC_CONTEXT_RULES is None:
        raw = yaml.safe_load(_NUMERIC_CONTEXT_PATH.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise ValueError("numeric_context.tr.yaml must be a mapping")
        market_tokens = raw.get("market_line_context", [])
        thousands_tokens = raw.get("thousands_format_context", [])
        score_tokens = raw.get("score_line_context", [])
        if not isinstance(market_tokens, list) or not isinstance(thousands_tokens, list) or not isinstance(score_tokens, list):
            raise ValueError("numeric_context.tr.yaml entries must be lists")
        _NUMERIC_CONTEXT_RULES = {
            "market_line_context": {str(item).strip().lower() for item in market_tokens if isinstance(item, str)},
            "thousands_format_context": {str(item).strip().lower() for item in thousands_tokens if isinstance(item, str)},
            "score_line_context": {str(item).strip().lower() for item in score_tokens if isinstance(item, str)},
        }
    return _NUMERIC_CONTEXT_RULES


def score_parser(token: str) -> dict[str, int] | None:
    match = _SCORE_LINE_RE.match(token)
    if not match:
        return None
    home, away = match.group(1), match.group(2)
    return {"home": int(home), "away": int(away)}


def market_line_parser(token: str) -> dict[str, str] | None:
    match = _DECIMAL_NUMBER_RE.match(token)
    if not match:
        return None
    normalized = token.replace(",", ".")
    return {"market": "ou", "line": normalized}


def choose_numeric_parse(token: str, left: list[str], right: list[str]) -> tuple[str, dict[str, Any] | None]:
    rules = _load_numeric_context_rules()
    left_set = {t.lower() for t in left}
    right_set = {t.lower() for t in right}
    context = left_set | right_set

    apostrophe_parse = parse_apostrophe_suffixed_numeric(token)
    if apostrophe_parse is not None:
        return "apostrophe_numeric", apostrophe_parse

    score_parse = score_parser(token)
    market_parse = market_line_parser(token)

    if score_parse is not None:
        if context & rules["score_line_context"]:
            return "score_line", score_parse
        if token.count("-") or token.count(":"):
            # score-line separators are strong enough to classify as a score.
            return "score_line", score_parse

    if market_parse is not None:
        if context & rules["market_line_context"]:
            return "market_decimal", market_parse
        if context & rules["thousands_format_context"]:
            return "thousands_decimal", None

    if market_parse is not None and token.count(",") == 1:
        whole, fraction = token.split(",", 1)
        if whole.isdigit() and fraction.isdigit() and len(whole) <= 2 and len(fraction) <= 2:
            return "ambiguous_decimal", None

    if market_parse is not None and token.count(".") == 1 and token.count(",") == 0:
        whole, fraction = token.split(".", 1)
        if whole.isdigit() and fraction.isdigit() and len(whole) <= 2 and len(fraction) <= 2:
            return "ambiguous_decimal", None

    return "none", None
