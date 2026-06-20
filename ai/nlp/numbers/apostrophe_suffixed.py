from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from ai.common.text.turkish import lowercase_tr

_DEFAULT_SPEC_PATH: Path = (
    Path(__file__).resolve().parents[3] / "ai" / "common" / "text" / "numeric_apostrophe_spec.json"
)

_APOSTROPHE_SPEC: dict[str, Any] | None = None
_APOSTROPHE_SUFFIX_RE: re.Pattern[str] | None = None
_CASE_MAP: dict[str, str] | None = None


def _load_json(path: Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        raw = json.load(fh)
    return raw if isinstance(raw, dict) else {}


def load_numeric_apostrophe_spec(path: Path | None = None) -> dict[str, Any]:
    return _load_json(path or _DEFAULT_SPEC_PATH)


def numeric_apostrophe_spec_sha256(path: Path | None = None) -> str:
    effective = path or _DEFAULT_SPEC_PATH
    return hashlib.sha256(effective.read_bytes()).hexdigest()


def _initialize_spec() -> None:
    global _APOSTROPHE_SPEC, _APOSTROPHE_SUFFIX_RE, _CASE_MAP
    if _APOSTROPHE_SPEC is not None:
        return

    spec = load_numeric_apostrophe_spec()
    shape_regex = spec.get("shape_regex")
    case_map = spec.get("case_map")

    if not isinstance(shape_regex, str):
        raise ValueError("numeric_apostrophe_spec.json must define a shape_regex string")
    if not isinstance(case_map, dict):
        raise ValueError("numeric_apostrophe_spec.json must define a case_map mapping")

    _APOSTROPHE_SPEC = spec
    _APOSTROPHE_SUFFIX_RE = re.compile(shape_regex)
    _CASE_MAP = {
        lowercase_tr(str(key)): str(value)
        for key, value in case_map.items()
        if isinstance(key, str) and isinstance(value, str)
    }


def _resolve_case(suffix: str) -> str | None:
    _initialize_spec()
    canonical = lowercase_tr(suffix)
    return _CASE_MAP.get(canonical)


def parse_apostrophe_suffixed_numeric(token: str) -> dict[str, Any] | None:
    """Parse Turkish numeric tokens with apostrophe-bound suffixes.

    Examples:
        3'ü     -> cardinal accusative
        2008'de -> cardinal locative
        1-1'lik -> score_pair derivative_lik
        100.'sü -> ordinal genitive
    """
    _initialize_spec()
    assert _APOSTROPHE_SUFFIX_RE is not None

    match = _APOSTROPHE_SUFFIX_RE.fullmatch(token)
    if match is None:
        return None

    num = match.group("num")
    suffix = match.group("suffix")
    case = _resolve_case(suffix)
    if case is None:
        return None

    if "-" in num or "–" in num:
        left, right = re.split(r"[-–]", num)
        return {
            "value": (int(left), int(right)),
            "kind": "score_pair",
            "case": case,
        }

    if num.endswith("."):
        return {
            "value": int(num[:-1]),
            "kind": "ordinal",
            "case": case,
        }

    return {
        "value": int(num),
        "kind": "cardinal",
        "case": case,
    }
