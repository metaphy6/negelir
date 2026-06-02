from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from common.config import cfg

_LANG_TR_DIR = Path(__file__).parent / "lang_tr"


class Phase10SchemaError(ValueError):
    pass


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    if not isinstance(raw, dict):
        raise Phase10SchemaError(f"{path.name}: expected a YAML mapping at top level")
    meta = raw.get("_meta")
    if not isinstance(meta, dict):
        raise Phase10SchemaError(f"{path.name}: missing or malformed _meta block")
    version = meta.get("schema_version")
    if version != 1:
        raise Phase10SchemaError(
            f"{path.name}: expected schema_version=1, got {version!r}"
        )
    return raw


@dataclass(frozen=True)
class WhIntentMapEntry:
    wh_word: str
    intent_candidates: tuple[str, ...]
    prior_log_odds: float


def load_wh_intent_map(path: Path | None = None) -> dict[str, WhIntentMapEntry]:
    actual_path = path or _LANG_TR_DIR / "wh_intent_map.tr.yaml"
    if not actual_path.exists():
        return {}
    raw = _load_yaml(actual_path)
    entries = raw.get("entries")
    if not isinstance(entries, list):
        raise Phase10SchemaError(f"{actual_path.name}: missing required 'entries' list")
    result: dict[str, WhIntentMapEntry] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise Phase10SchemaError(f"{actual_path.name}: each entry must be a mapping")
        wh_word = entry.get("wh_word")
        candidates = entry.get("intent_candidates")
        prior = entry.get("prior_log_odds")
        if not isinstance(wh_word, str) or not wh_word:
            raise Phase10SchemaError(f"{actual_path.name}: invalid wh_word")
        if not isinstance(candidates, list) or not candidates:
            raise Phase10SchemaError(f"{actual_path.name}: invalid intent_candidates for {wh_word!r}")
        if not isinstance(prior, (float, int)):
            raise Phase10SchemaError(f"{actual_path.name}: invalid prior_log_odds for {wh_word!r}")
        result[wh_word] = WhIntentMapEntry(
            wh_word=wh_word,
            intent_candidates=tuple(str(c) for c in candidates),
            prior_log_odds=float(prior),
        )
    return result


def load_wh_words(path: Path | None = None) -> list[str]:
    actual_path = path or _LANG_TR_DIR / "wh_words.tr.yaml"
    if not actual_path.exists():
        return []
    raw = _load_yaml(actual_path)
    words = raw.get("wh_words")
    if not isinstance(words, list):
        raise Phase10SchemaError(f"{actual_path.name}: missing required 'wh_words' list")
    return [str(w) for w in words if isinstance(w, str) and w]


def _prob_to_logit(prob: float) -> float:
    p = min(max(prob, 1e-15), 1.0 - 1e-15)
    return math.log(p / (1.0 - p))


def _logit_to_prob(logit: float) -> float:
    if logit > 500:
        return 1.0
    if logit < -500:
        return 0.0
    return 1.0 / (1.0 + math.exp(-logit))


def detect_wh_token(normalized_text: str) -> str | None:
    table = load_wh_intent_map()
    lower = normalized_text.lower()
    for wh in sorted(table.keys(), key=len, reverse=True):
        if re.search(rf"\b{re.escape(wh)}\b", lower):
            return wh
    return None


def apply_wh_prior_to_scores(normalized_text: str, scores: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not cfg.nlp_wh_prior_log_odds_max:
        return scores
    wh_token = detect_wh_token(normalized_text)
    if not wh_token:
        return scores
    entry = load_wh_intent_map().get(wh_token)
    if entry is None:
        return scores
    cap = float(cfg.nlp_wh_prior_log_odds_max)
    prior = max(-cap, min(cap, entry.prior_log_odds))
    out: list[dict[str, Any]] = []
    for score in scores:
        raw_prob = float(score["raw_prob"])
        raw_logit = _prob_to_logit(raw_prob)
        logit_after = raw_logit + prior
        adjusted_prob = _logit_to_prob(logit_after)
        out.append({
            **score,
            "raw_logit": raw_logit,
            "raw_logit_after_wh_prior": logit_after,
            "adjusted_raw_prob": adjusted_prob,
        })
    return out


def load_politeness_markers(path: Path | None = None) -> dict[str, str]:
    actual_path = path or _LANG_TR_DIR / "politeness_markers.tr.yaml"
    if not actual_path.exists():
        return {}
    raw = _load_yaml(actual_path)
    markers = raw.get("entries")
    if not isinstance(markers, list):
        raise Phase10SchemaError(f"{actual_path.name}: missing 'entries' list")
    result: dict[str, str] = {}
    for entry in markers:
        if not isinstance(entry, dict):
            raise Phase10SchemaError(f"{actual_path.name}: entries must be objects")
        token = entry.get("token")
        cls = entry.get("class")
        if not isinstance(token, str) or not isinstance(cls, str):
            raise Phase10SchemaError(f"{actual_path.name}: invalid politeness entry")
        result[token.lower()] = cls
    return result


def strip_politeness_markers(tokens: list[str]) -> tuple[list[str], str]:
    if not cfg.nlp_politeness_marker_strip_enabled:
        return tokens, "neutral"
    markers = load_politeness_markers()
    stripped: list[str] = []
    highest = "neutral"
    for token in tokens:
        lower = token.lower()
        polite = markers.get(lower)
        if polite is not None:
            stripped.append(token)
            if polite == "very_polite":
                highest = polite
            elif polite == "polite" and highest == "neutral":
                highest = polite
            elif polite == "curt":
                highest = "curt"
        else:
            stripped.append(token)
    if not stripped:
        stripped = tokens
    return [t for t in tokens if t.lower() not in markers], highest


def load_search_operator_patterns(path: Path | None = None) -> list[re.Pattern]:
    actual_path = path or _LANG_TR_DIR / "search_operator_patterns.tr.yaml"
    if not actual_path.exists():
        return []
    raw = _load_yaml(actual_path)
    entries = raw.get("patterns")
    if not isinstance(entries, list):
        raise Phase10SchemaError(f"{actual_path.name}: missing 'patterns' list")
    return [re.compile(item, re.IGNORECASE) for item in entries if isinstance(item, str)]


def detect_search_query_style(text: str) -> str:
    if not cfg.nlp_search_operator_detection_enabled:
        return "natural"
    for pattern in load_search_operator_patterns():
        if pattern.search(text):
            if re.search(r'"[^"]+"', text):
                return "quoted_exact_search"
            return "search"
    return "natural"


def load_conditional_markers(path: Path | None = None) -> list[str]:
    actual_path = path or _LANG_TR_DIR / "conditional_markers.tr.yaml"
    if not actual_path.exists():
        return []
    raw = _load_yaml(actual_path)
    entries = raw.get("markers")
    if not isinstance(entries, list):
        raise Phase10SchemaError(f"{actual_path.name}: missing 'markers' list")
    return [str(item) for item in entries if isinstance(item, str)]


def detect_conditional_modifier(tokens: list[str]) -> tuple[str, str]:
    markers = load_conditional_markers()
    token_text = " ".join(tokens).lower()
    has_conditional = any(re.search(rf"\b{re.escape(marker)}\b", token_text) for marker in markers)
    if not has_conditional:
        return "none", "none"
    future = re.search(r"\b(kazanırsa|olursa|gelirse|atarsa)\b", token_text)
    past = re.search(r"\b(kazansaydı|olurdu|gelirseyd[iı])\b", token_text)
    if past:
        return "conditional", "past"
    if future:
        return "conditional", "future"
    return "conditional", "present"


def load_idiom_phrasebook(path: Path | None = None) -> list[dict[str, Any]]:
    actual_path = path or _LANG_TR_DIR / "idioms.tr.yaml"
    if not actual_path.exists():
        return []
    raw = _load_yaml(actual_path)
    entries = raw.get("entries")
    if not isinstance(entries, list):
        raise Phase10SchemaError(f"{actual_path.name}: missing 'entries' list")
    result: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise Phase10SchemaError(f"{actual_path.name}: entries must be objects")
        result.append(entry)
    return result


def load_idiom_context(path: Path | None = None) -> dict[str, list[str]]:
    actual_path = path or _LANG_TR_DIR / "idiom_context.tr.yaml"
    if not actual_path.exists():
        return {}
    raw = _load_yaml(actual_path)
    entries = raw.get("entries")
    if not isinstance(entries, list):
        raise Phase10SchemaError(f"{actual_path.name}: missing 'entries' list")
    result: dict[str, list[str]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise Phase10SchemaError(f"{actual_path.name}: entries must be objects")
        idiom = entry.get("idiom")
        triggers = entry.get("triggers")
        if not isinstance(idiom, str) or not isinstance(triggers, list):
            raise Phase10SchemaError(f"{actual_path.name}: invalid idiom context entry")
        result[idiom] = [str(t) for t in triggers if isinstance(t, str)]
    return result


def expand_idioms(tokens: list[str], normalized_text: str) -> tuple[list[str], list[dict[str, Any]]]:
    phrasebook = load_idiom_phrasebook()
    context_map = load_idiom_context()
    if not phrasebook:
        return tokens, []
    lowered = [t.lower() for t in tokens]
    max_len = int(cfg.nlp_idiom_max_phrase_len_tokens)
    out: list[str] = []
    events: list[dict[str, Any]] = []
    i = 0
    while i < len(tokens):
        match = None
        match_len = 0
        best = None
        for entry in phrasebook:
            idiom = str(entry.get("idiom", "")).split()
            if not idiom or len(idiom) > max_len:
                continue
            if i + len(idiom) > len(tokens):
                continue
            if lowered[i:i + len(idiom)] == [w.lower() for w in idiom]:
                if len(idiom) > match_len:
                    match = entry
                    match_len = len(idiom)
        if match is None:
            out.append(tokens[i])
            i += 1
            continue
        idiom_text = " ".join(tokens[i:i + match_len])
        context_ok = True
        if idiom_text.lower() in context_map:
            triggers = context_map[idiom_text.lower()]
            context_ok = any(re.search(rf"\b{re.escape(trigger)}\b", normalized_text.lower()) for trigger in triggers)
            if not context_ok:
                events.append({
                    "kind": "idiom_ambiguous",
                    "idiom": idiom_text,
                    "span": (i, i + match_len),
                })
                out.extend(tokens[i:i + match_len])
                i += match_len
                continue
        slot = match.get("slot")
        if slot:
            out.append(match.get("expansion", idiom_text))
        else:
            out.append(match.get("expansion", idiom_text))
        events.append({
            "kind": "idiom_expansion",
            "idiom": idiom_text,
            "span": (i, i + match_len),
            "replaced_tokens": tokens[i:i + match_len],
        })
        i += match_len
    return out, events


def detect_search_operator_syntax_in_text(text: str) -> str:
    if not cfg.nlp_search_operator_detection_enabled:
        return "natural"
    for pattern in load_search_operator_patterns():
        if pattern.search(text):
            if re.search(r'"[^"]*"', text):
                return "quoted_exact_search"
            return "search"
    return "natural"
