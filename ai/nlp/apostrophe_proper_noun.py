"""Phase 10 §10.32.5 — Input-side apostrophe repair for proper nouns."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable, NamedTuple, Optional

import yaml

from common.text.turkish import (
    lowercase_tr,
    strip_proper_noun_suffix,
    is_harmony_tolerant_suffix_candidate,
)

_DEFAULT_APOSTROPHE_RULE_PATH: Path = (
    Path(__file__).parent / "lang_tr" / "apostrophe_proper_noun.tr.yaml"
)
_DEFAULT_APOSTROPHE_NO_INSERT_PATH: Path = (
    Path(__file__).parent / "lang_tr" / "apostrophe_no_insert.tr.yaml"
)
_DEFAULT_SPEC_PATH: Path = (
    Path(__file__).resolve().parents[1] / "common" / "text" / "proper_noun_apostrophe_spec.json"
)

_APOSTROPHE_TOKEN_SPLIT_RE = re.compile(r"[\s,\.\?!\:\;\(\)\[\]/|\-]+")
_MISSING_APOSTROPHE_SUFFIXES = (
    "nün",
    "nun",
    "nin",
    "nın",
    "den",
    "dan",
    "ye",
    "ya",
    "lü",
    "lu",
    "li",
    "lı",
    "de",
    "da",
    "e",
    "a",
)


class ApostropheRepair(NamedTuple):
    original: str
    repaired: str
    rule_id: str
    rule_class: str
    evidence: Optional[str] = None


def _load_yaml(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    return raw if isinstance(raw, dict) else {}


def _load_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        raw = json.load(fh)
    return raw if isinstance(raw, dict) else {}


def load_apostrophe_repair_rules(path: Path = _DEFAULT_APOSTROPHE_RULE_PATH) -> dict:
    raw = _load_yaml(path)
    return raw.get("apostrophe_repair", {}) if isinstance(raw.get("apostrophe_repair"), dict) else {}


def load_apostrophe_no_insert_allowlist(path: Path = _DEFAULT_APOSTROPHE_NO_INSERT_PATH) -> set[str]:
    raw = _load_yaml(path)
    items = raw.get("no_insert_allowlist", [])
    if not isinstance(items, list):
        return set()
    return {lowercase_tr(str(item).strip()) for item in items if isinstance(item, str) and item.strip()}


def load_proper_noun_apostrophe_spec(path: Path | None = None) -> dict:
    return _load_json(path or _DEFAULT_SPEC_PATH)


def _emit_suffix_harmony_repair_event(
    repaired: str,
    event_sink: Callable[[dict[str, str]], None] | None,
) -> None:
    if event_sink is None or "'" not in repaired:
        return
    resolved_suffix_class = is_harmony_tolerant_suffix_candidate(repaired)
    if resolved_suffix_class is None:
        return

    original_suffix = repaired.rsplit("'", 1)[1]
    event_sink(
        {
            "kind": "suffix_harmony_repaired",
            "original_suffix": original_suffix,
            "resolved_suffix_class": resolved_suffix_class,
        }
    )


def repair_apostrophe_proper_noun(
    text: str,
    *,
    rule_path: Path | None = None,
    no_insert_path: Path | None = None,
    spec_path: Path | None = None,
    original_text: str | None = None,
    event_sink: Callable[[dict[str, str]], None] | None = None,
    input_source: str = "keyboard",
) -> tuple[str, tuple[ApostropheRepair, ...]]:
    raw_text = text.strip()
    if not raw_text:
        return raw_text, ()

    rules = load_apostrophe_repair_rules(rule_path or _DEFAULT_APOSTROPHE_RULE_PATH)
    internal_allowlist = {
        lowercase_tr(str(rule).strip())
        for rule in rules.get("legitimate_internal_apostrophe", {}).get("allowlist", [])
        if isinstance(rule, str)
    }
    no_insert_allowlist = load_apostrophe_no_insert_allowlist(no_insert_path or _DEFAULT_APOSTROPHE_NO_INSERT_PATH)

    lower_tokens = _APOSTROPHE_TOKEN_SPLIT_RE.split(raw_text)
    tokens = [lowercase_tr(token) for token in lower_tokens]
    separators = _APOSTROPHE_TOKEN_SPLIT_RE.findall(raw_text)

    if original_text is not None:
        sanitized_original = original_text.replace("\u2013", " ").replace("\u2014", " ")
        original_tokens = _APOSTROPHE_TOKEN_SPLIT_RE.split(sanitized_original)
    else:
        original_tokens = lower_tokens

    repaired_tokens: list[str] = []
    repairs: list[ApostropheRepair] = []

    for lower_token, original_token in zip(tokens, original_tokens):
        if lower_token == "":
            repaired_tokens.append(lower_token)
            continue

        repaired, repair = _repair_token(
            lower_token,
            original_token,
            internal_allowlist,
            no_insert_allowlist,
            input_source=input_source,
            event_sink=event_sink,
        )
        repaired_tokens.append(repaired)
        if repair is not None:
            repairs.append(repair)

    output = []
    for idx, token in enumerate(repaired_tokens):
        output.append(token)
        if idx < len(separators):
            output.append(separators[idx])

    return "".join(output), tuple(repairs)


def _repair_token(
    token: str,
    original_token: str,
    internal_allowlist: set[str],
    no_insert_allowlist: set[str],
    *,
    input_source: str = "keyboard",
    event_sink: Callable[[dict[str, str]], None] | None = None,
) -> tuple[str, ApostropheRepair | None]:
    if token in internal_allowlist:
        return token, None

    if "'" in original_token:
        if _is_valid_apostrophe_token(token):
            return token, None
        repaired = _repair_misplaced_apostrophe(
            token,
            internal_allowlist,
            no_insert_allowlist,
            event_sink=event_sink,
        )
        if repaired is not None:
            return repaired, ApostropheRepair(
                original=lowercase_tr(original_token),
                repaired=repaired,
                rule_id="misplaced_apostrophe",
                rule_class="misplaced_apostrophe",
            )
        return token, None

    if not original_token:
        return token, None

    if input_source == "voice":
        return token, None

    if not original_token[0].isupper():
        return token, None

    if len(token) < 7 or token in no_insert_allowlist:
        return token, None

    repaired = _repair_missing_apostrophe(
        token,
        internal_allowlist,
        no_insert_allowlist,
        event_sink=event_sink,
    )
    if repaired is not None:
        return repaired, ApostropheRepair(
            original=token,
            repaired=repaired,
            rule_id="missing_apostrophe_suffix",
            rule_class="missing_apostrophe_suffix",
            evidence="lexicon_prefix_match",
        )

    return token, None


def _is_valid_apostrophe_token(token: str) -> bool:
    _, suffix = strip_proper_noun_suffix(
        token,
        assume_proper=True,
        allow_harmony_tolerance=True,
    )
    return suffix is not None


def _repair_missing_apostrophe(
    token: str,
    internal_allowlist: set[str],
    no_insert_allowlist: set[str],
    event_sink: Callable[[dict[str, str]], None] | None = None,
) -> str | None:
    candidates: list[tuple[int, str]] = []
    for suffix in _MISSING_APOSTROPHE_SUFFIXES:
        if not token.endswith(suffix) or len(token) <= len(suffix):
            continue
        candidate = token[: len(token) - len(suffix)] + "'" + suffix
        if candidate in internal_allowlist or candidate in no_insert_allowlist:
            continue
        if _is_valid_apostrophe_token(candidate):
            stem, _ = strip_proper_noun_suffix(candidate, assume_proper=True)
            candidates.append((len(stem), candidate))

    if not candidates:
        return None

    best_length = max(length for length, _ in candidates)
    unique_best = {candidate for length, candidate in candidates if length == best_length}
    if len(unique_best) == 1:
        repaired = unique_best.pop()
        _emit_suffix_harmony_repair_event(repaired, event_sink)
        return repaired
    return None


def _repair_misplaced_apostrophe(
    token: str,
    internal_allowlist: set[str],
    no_insert_allowlist: set[str],
    event_sink: Callable[[dict[str, str]], None] | None = None,
) -> str | None:
    raw = token.replace("'", "")
    if len(raw) < 7:
        return None

    candidates: list[tuple[int, str]] = []
    for split in range(1, len(raw)):
        candidate = raw[:split] + "'" + raw[split:]
        if candidate == token:
            continue
        if candidate in internal_allowlist or candidate in no_insert_allowlist:
            continue
        if _is_valid_apostrophe_token(candidate):
            stem, _ = strip_proper_noun_suffix(candidate, assume_proper=True)
            candidates.append((len(stem), candidate))

    if not candidates:
        return None

    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    best_length = candidates[0][0]
    best_candidates = [candidate for length, candidate in candidates if length == best_length]
    if len(best_candidates) == 1:
        repaired = best_candidates[0]
        _emit_suffix_harmony_repair_event(repaired, event_sink)
        return repaired
    return None
