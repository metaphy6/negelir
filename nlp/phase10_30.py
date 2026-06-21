from __future__ import annotations

import datetime
import functools
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from common.config import cfg
from common.text.turkish import parse_number_word

_LANG_TR_DIR = Path(__file__).parent / "lang_tr"
_META_QUESTIONS_PATH = _LANG_TR_DIR / "meta_questions.tr.yaml"
_CONVERSATIONAL_META_PATH = _LANG_TR_DIR / "conversational_meta.tr.yaml"
_QUESTION_TAG_CLASSIFIER_PATH = _LANG_TR_DIR / "question_tag_classifier.tr.yaml"
_COMPLEMENTARY_ANAPHORA_PATH = _LANG_TR_DIR / "complementary_anaphora.tr.yaml"

GOVERNANCE_HIGH_LEVERAGE_LEXICON_FILES = frozenset({
    "idioms.tr.yaml",
    "offensive_obfuscated.tr.yaml",
})


def is_high_leverage_governance_lexicon(path: Path | str) -> bool:
    actual_name = Path(path).name if isinstance(path, (Path, str)) else str(path)
    return actual_name in GOVERNANCE_HIGH_LEVERAGE_LEXICON_FILES


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


def load_focus_particle_disambiguation(path: Path | None = None) -> frozenset[str]:
    actual_path = path or _LANG_TR_DIR / "focus_particle_disambiguation.tr.yaml"
    if not actual_path.exists():
        return frozenset()
    raw = _load_yaml(actual_path)
    particles = raw.get("particles")
    if not isinstance(particles, list):
        raise Phase10SchemaError(
            f"{actual_path.name}: missing required 'particles' list"
        )
    return frozenset(str(p).strip() for p in particles if isinstance(p, str) and p.strip())


_PRO_DROP_INTENT_CLASSES_PATH = _LANG_TR_DIR / "pro_drop_intent_classes.tr.yaml"
_PRO_DROP_RESOLUTION_STRATEGIES = frozenset({
    "cross_turn_anaphora_then_default_team",
    "cross_turn_anaphora_then_disambiguation",
    "time_context_only",
    "disambiguation_only",
})


def load_pro_drop_intent_classes(path: Path | None = None) -> dict[str, str]:
    actual_path = path or _PRO_DROP_INTENT_CLASSES_PATH
    if not actual_path.exists():
        return {}
    raw = _load_yaml(actual_path)
    entries = raw.get("entries")
    if not isinstance(entries, list):
        raise Phase10SchemaError(f"{actual_path.name}: missing required 'entries' list")

    result: dict[str, str] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise Phase10SchemaError(f"{actual_path.name}: each entry must be a mapping")
        intent = entry.get("intent")
        strategy = entry.get("pro_drop_resolution_strategy")
        if not isinstance(intent, str) or not intent:
            raise Phase10SchemaError(f"{actual_path.name}: invalid intent")
        if not isinstance(strategy, str) or strategy not in _PRO_DROP_RESOLUTION_STRATEGIES:
            raise Phase10SchemaError(
                f"{actual_path.name}: invalid pro_drop_resolution_strategy for intent {intent!r}"
            )
        result[intent] = strategy
    return result


def load_question_tag_classifier(path: Path | None = None) -> dict[str, str]:
    actual_path = path or _QUESTION_TAG_CLASSIFIER_PATH
    if not actual_path.exists():
        return {}
    raw = _load_yaml(actual_path)
    entries = raw.get("entries")
    if not isinstance(entries, list):
        raise Phase10SchemaError(f"{actual_path.name}: missing required 'entries' list")

    result: dict[str, str] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise Phase10SchemaError(f"{actual_path.name}: each entry must be a mapping")
        shape = entry.get("shape")
        pragmatic_class = entry.get("pragmatic_class")
        if not isinstance(shape, str) or not shape:
            raise Phase10SchemaError(f"{actual_path.name}: invalid shape")
        if pragmatic_class not in {"information_seeking", "confirmation_seeking"}:
            raise Phase10SchemaError(
                f"{actual_path.name}: invalid pragmatic_class for shape {shape!r}"
            )
        result[shape] = pragmatic_class
    return result


_NEGATIVE_QUESTION_OBJECT_MARKER_RE = re.compile(r"(?:'yi|'yı|'yu|'yü|yi|yı|yu|yü)$")
_NEGATIVE_QUESTION_VERB_RE = re.compile(
    r".*(?:madı|medi|maz|mez|mıyor|miyor|mıyordu|miyordu|muyor|müyor|mamış|memiş|mamıştı|memişti)$"
)


def _is_ambiguous_negative_question(tokens: list[str]) -> bool:
    if len(tokens) < 2:
        return False
    normalized = [token.lower() for token in tokens]
    # Remove trailing punctuation tokens.
    normalized = [token for token in normalized if token not in {"?", "!", ".", ",", ":", ";"}]
    if len(normalized) < 2:
        return False
    if normalized[-1] not in {"mi", "mı", "mu", "mü"}:
        return False
    if not _NEGATIVE_QUESTION_VERB_RE.fullmatch(normalized[-2]):
        return False
    if any(_NEGATIVE_QUESTION_OBJECT_MARKER_RE.search(tok) for tok in normalized[:-2]):
        return True
    return False


def detect_question_tag_pragmatic_class(
    tokens: list[str],
    *,
    path: Path | None = None,
    focus_particle_disambiguated: bool = False,
) -> str | None:
    if not tokens or focus_particle_disambiguated:
        return None

    normalized_tokens = [token.lower() for token in tokens]
    stripped = [token for token in normalized_tokens if token not in {"?", "!", ".", ",", ":", ";"}]
    if not stripped:
        return None

    if stripped[-1] not in {"mi", "mı", "mu", "mü"}:
        return None

    if len(stripped) >= 2 and stripped[-2] == "değil":
        return "confirmation_seeking"

    if _is_ambiguous_negative_question(stripped):
        return None

    table = load_question_tag_classifier(path)
    text = " ".join(stripped)
    for shape, pragmatic_class in table.items():
        if re.search(rf"\b{re.escape(shape)}\b", text):
            return pragmatic_class

    return "information_seeking"


_TELEGRAPHIC_INTENT_MAP_PATH = _LANG_TR_DIR / "intent_telegraphic.tr.yaml"
_TELEGRAPHIC_ENTITY_KINDS = frozenset({"team", "player", "league", "competition"})
_TELEGRAPHIC_TEMPORAL_KINDS = frozenset({"date", "time", "weekday"})
_TELEGRAPHIC_QUESTION_PARTICLES = frozenset({"mi", "mı", "mu", "mü"})


def load_telegraphic_intent_classes(path: Path | None = None) -> frozenset[str]:
    actual_path = path or _TELEGRAPHIC_INTENT_MAP_PATH
    if not actual_path.exists():
        return frozenset()
    raw = _load_yaml(actual_path)
    entries = raw.get("entries")
    if not isinstance(entries, list):
        raise Phase10SchemaError(f"{actual_path.name}: missing required 'entries' list")

    result: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        intent = entry.get("intent")
        if not isinstance(intent, str) or not intent:
            raise Phase10SchemaError(f"{actual_path.name}: invalid intent")
        result.add(intent)
    return frozenset(result)


def _entity_is_high_confidence_for_telegraphic(entity: dict[str, Any]) -> bool:
    if not isinstance(entity, dict):
        return False
    kind = entity.get("kind")
    if not isinstance(kind, str) or kind not in _TELEGRAPHIC_ENTITY_KINDS:
        return False
    confidence = entity.get("confidence")
    if isinstance(confidence, (float, int)) and float(confidence) >= float(cfg.nlp_telegraphic_min_entity_confidence):
        return True
    source = entity.get("source")
    return isinstance(source, str) and source == "gazetteer"


def _has_temporal_entity(entities: list[dict[str, Any]]) -> bool:
    for entity in entities:
        if not isinstance(entity, dict):
            continue
        kind = entity.get("kind")
        if isinstance(kind, str) and kind in _TELEGRAPHIC_TEMPORAL_KINDS:
            return True
    return False


def _contains_question_marker(text: str) -> bool:
    lower = text.lower()
    if "?" in lower:
        return True
    return any(re.search(rf"\b{re.escape(p)}\b", lower) for p in _TELEGRAPHIC_QUESTION_PARTICLES)


def infer_telegraphic_intent(
    entities: list[dict[str, Any]],
    intent_distribution: list[dict[str, Any]] | None,
    normalized_text: str,
    token_count: int,
    has_verb_form: bool,
) -> tuple[str, float, str] | None:
    if not cfg.nlp_telegraphic_inference_enabled:
        return None
    if token_count > int(cfg.nlp_telegraphic_max_tokens):
        return None
    if has_verb_form:
        return None
    if _contains_question_marker(normalized_text):
        return None
    if not any(_entity_is_high_confidence_for_telegraphic(entity) for entity in entities):
        return None
    if not _has_temporal_entity(entities):
        return None

    allowed_intents = load_telegraphic_intent_classes()
    if not allowed_intents:
        return None

    if intent_distribution is not None:
        for entry in intent_distribution:
            label = entry.get("label")
            if not isinstance(label, str):
                continue
            if label.startswith("predict."):
                continue
            if label in allowed_intents:
                return label, 0.65, "telegraphic_inference"

    return "data.fixture_lookup", 0.65, "telegraphic_inference"


_KI_CONTEXT_PATH = _LANG_TR_DIR / "spelling" / "ki_context.tr.yaml"


def load_ki_context(path: Path | None = None) -> dict[str, str]:
    actual_path = path or _KI_CONTEXT_PATH
    if not actual_path.exists():
        return {}
    raw = _load_yaml(actual_path)
    entries = raw.get("entries")
    if not isinstance(entries, list):
        raise Phase10SchemaError(f"{actual_path.name}: missing required 'entries' list")

    result: dict[str, str] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        token = entry.get("token")
        common_reading = entry.get("common_reading")
        if not isinstance(token, str) or not token:
            raise Phase10SchemaError(f"{actual_path.name}: invalid token")
        if not isinstance(common_reading, str) or common_reading not in {"relative", "emphatic"}:
            raise Phase10SchemaError(f"{actual_path.name}: invalid common_reading for token {token!r}")
        result[token.lower()] = common_reading
    return result


def detect_ki_contexts(normalized_text: str, tokens: list[str], *, path: Path | None = None) -> list[str]:
    if not normalized_text or not tokens:
        return []

    token_forms = [token.lower() for token in tokens]
    ki_positions = [idx for idx, tok in enumerate(token_forms) if tok == "ki"]
    if not ki_positions:
        return []

    patterns = list(re.finditer(r"(?<!\w)ki(?!\w)", normalized_text, flags=re.IGNORECASE))
    if len(patterns) != len(ki_positions):
        return []

    ambiguous_defaults = load_ki_context(path)
    results: list[str] = []
    for pattern in patterns:
        start, end = pattern.span()
        before = ""
        i = start - 1
        while i >= 0 and normalized_text[i].isspace():
            i -= 1
        if i >= 0:
            before = normalized_text[i]

        after = ""
        j = end
        while j < len(normalized_text) and normalized_text[j].isspace():
            j += 1
        if j < len(normalized_text):
            after = normalized_text[j]

        if before == "," or after == ",":
            results.append("relative")
            continue
        if after == "!" or after == "":
            results.append("emphatic")
            continue
        token = pattern.group(0).lower()
        if token in ambiguous_defaults:
            results.append("ambiguous")
        else:
            results.append("relative")
    return results


def _normalize_conversational_meta_text(text: str) -> str:
    normalized = text.casefold()
    normalized = re.sub(r"[^\wığüşöçĞÜŞÖÇİ]+", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


@functools.lru_cache(maxsize=1)
def load_conversational_meta_patterns(path: Path | None = None) -> dict[str, tuple[str, ...]]:
    actual_path = path or (_META_QUESTIONS_PATH if _META_QUESTIONS_PATH.exists() else _CONVERSATIONAL_META_PATH)
    if not actual_path.exists():
        return {}
    raw = _load_yaml(actual_path)
    entries = raw.get("entries")
    if not isinstance(entries, list):
        raise Phase10SchemaError(f"{actual_path.name}: missing required 'entries' list")

    result: dict[str, tuple[str, ...]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise Phase10SchemaError(f"{actual_path.name}: each entry must be a mapping")
        intent = entry.get("intent")
        examples = entry.get("examples")
        if not isinstance(intent, str) or not intent:
            raise Phase10SchemaError(f"{actual_path.name}: invalid intent")
        if not isinstance(examples, list) or not examples:
            raise Phase10SchemaError(
                f"{actual_path.name}: invalid examples for intent {intent!r}"
            )
        result[intent] = tuple(str(example) for example in examples if isinstance(example, str) and example.strip())

    if len(result) > cfg.nlp_meta_question_table_max:
        raise Phase10SchemaError(
            f"{actual_path.name}: contains {len(result)} entries, exceeding cfg.nlp_meta_question_table_max"
        )
    return result


def classify_conversational_meta(normalized_text: str, path: Path | None = None) -> str | None:
    patterns = load_conversational_meta_patterns(path)
    if not patterns:
        return None
    normalized_text = _normalize_conversational_meta_text(normalized_text)
    for intent, examples in patterns.items():
        for example in examples:
            normalized_example = _normalize_conversational_meta_text(example)
            if not normalized_example:
                continue
            if re.search(rf"\b{re.escape(normalized_example)}\b", normalized_text):
                return intent
    return None


def detect_focus_particle_disambiguation(tokens: list[str], path: Path | None = None) -> bool:
    if not tokens:
        return False
    particles = load_focus_particle_disambiguation(path)
    if not particles:
        return False
    normalized_tokens = [token.lower() for token in tokens]
    if not any(token in particles for token in normalized_tokens):
        return False
    text = " ".join(normalized_tokens)
    wh_words = load_wh_words()
    for wh in wh_words:
        if re.search(rf"\b{re.escape(wh)}\b", text):
            return True
    return False


@dataclass(frozen=True)
class AsrPunctuationEntry:
    phrase: tuple[str, ...]
    replacement: str


_ASR_PUNCTUATION_REPLACEMENTS: dict[str, str] = {
    "virgül": ",",
    "nokta": ".",
    "noktalı virgül": ";",
    "iki nokta": ":",
    "soru işareti": "?",
    "ünlem işareti": "!",
    "tire": "-",
    "kısa çizgi": "-",
    "parantez": "(",
    "tırnak": '"',
}


def load_asr_punctuation_words(path: Path | None = None) -> list[AsrPunctuationEntry]:
    actual_path = path or _LANG_TR_DIR / "asr_punctuation_words.tr.yaml"
    if not actual_path.exists():
        return []
    raw = _load_yaml(actual_path)
    entries = raw.get("entries")
    if not isinstance(entries, list):
        raise Phase10SchemaError(f"{actual_path.name}: missing required 'entries' list")
    result: list[AsrPunctuationEntry] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise Phase10SchemaError(f"{actual_path.name}: each entry must be a mapping")
        word = entry.get("word")
        if not isinstance(word, str) or not word:
            raise Phase10SchemaError(f"{actual_path.name}: invalid word entry")
        replacement = _ASR_PUNCTUATION_REPLACEMENTS.get(word.lower())
        if replacement is None:
            raise Phase10SchemaError(
                f"{actual_path.name}: unsupported punctuation word {word!r}"
            )
        phrase = tuple(word.lower().split())
        result.append(AsrPunctuationEntry(phrase=phrase, replacement=replacement))
    return result


def _parse_voice_number_token(token: str | None) -> str | None:
    if token is None:
        return None
    if token.isdigit():
        return token
    parsed = parse_number_word(token)
    if parsed is not None:
        return str(parsed)
    return None


def apply_asr_punctuation_words(
    tokens: list[str], *,
    input_source: str = "keyboard",
) -> tuple[list[str], list[dict[str, Any]]]:
    if input_source != "voice":
        return tokens, []

    entries = sorted(
        load_asr_punctuation_words(),
        key=lambda entry: len(entry.phrase),
        reverse=True,
    )
    if not entries:
        return tokens, []

    out: list[str] = []
    events: list[dict[str, Any]] = []
    i = 0
    while i < len(tokens):
        matched = False
        for entry in entries:
            phrase_len = len(entry.phrase)
            if i + phrase_len > len(tokens):
                continue
            if tuple(tokens[i : i + phrase_len]) == entry.phrase:
                left_value = _parse_voice_number_token(out[-1]) if out else None
                right_token = tokens[i + phrase_len] if i + phrase_len < len(tokens) else None
                right_value = _parse_voice_number_token(right_token)
                if left_value is not None and right_value is not None:
                    out[-1] = f"{left_value}{entry.replacement}{right_value}"
                    i += phrase_len + 1
                else:
                    events.append(
                        {
                            "kind": "asr_punctuation_word_stripped",
                            "punctuation_phrase": " ".join(entry.phrase),
                        }
                    )
                    i += phrase_len
                matched = True
                break
        if not matched:
            out.append(tokens[i])
            i += 1
    return out, events


@dataclass(frozen=True)
class VoiceNumberContextEntry:
    context: str
    resolution: str
    keywords: tuple[str, ...] = ()


def load_voice_number_context(path: Path | None = None) -> dict[str, VoiceNumberContextEntry]:
    actual_path = path or _LANG_TR_DIR / "voice_number_context.tr.yaml"
    if not actual_path.exists():
        return {}
    raw = _load_yaml(actual_path)
    entries = raw.get("entries")
    if not isinstance(entries, list):
        raise Phase10SchemaError(f"{actual_path.name}: missing required 'entries' list")
    result: dict[str, VoiceNumberContextEntry] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise Phase10SchemaError(f"{actual_path.name}: each entry must be a mapping")
        context = entry.get("context")
        resolution = entry.get("resolution")
        keywords = entry.get("keywords", [])
        if not isinstance(context, str) or not context:
            raise Phase10SchemaError(f"{actual_path.name}: invalid context entry")
        if not isinstance(resolution, str) or not resolution:
            raise Phase10SchemaError(f"{actual_path.name}: invalid resolution for {context!r}")
        if not isinstance(keywords, list):
            raise Phase10SchemaError(f"{actual_path.name}: invalid keywords list for {context!r}")
        keyword_tuple = tuple(
            str(keyword).lower()
            for keyword in keywords
            if isinstance(keyword, str) and keyword.strip()
        )
        result[context] = VoiceNumberContextEntry(
            context=context,
            resolution=resolution,
            keywords=keyword_tuple,
        )
    return result


def detect_voice_number_context(tokens: list[str], path: Path | None = None) -> str | None:
    table = load_voice_number_context(path)
    if not table:
        return None
    lower_tokens = [token.lower() for token in tokens]
    joined = " ".join(lower_tokens)
    for entry in table.values():
        for keyword in entry.keywords:
            if " " in keyword:
                if keyword in joined:
                    return entry.context
            elif keyword in lower_tokens:
                return entry.context
    return None


def resolve_voice_number_context(tokens: list[str], *, input_source: str = "keyboard") -> list[str]:
    if input_source != "voice":
        return tokens
    context = detect_voice_number_context(tokens)
    if not context:
        return tokens
    entry = load_voice_number_context().get(context)
    if entry is None:
        return tokens
    out: list[str] = []
    i = 0
    while i < len(tokens):
        matched = False
        for j in range(min(len(tokens), i + 5), i, -1):
            phrase = " ".join(tokens[i:j])
            parsed = parse_number_word(phrase)
            if parsed is None:
                continue
            if entry.resolution == "ordinal":
                replacement = f"{parsed}."
            elif entry.resolution == "year":
                replacement = str(parsed) if (j - i == 4 and 1000 <= parsed <= 2999) else None
            else:
                replacement = str(parsed)
            if replacement is not None:
                out.append(replacement)
                i = j
                matched = True
                break
        if not matched:
            out.append(tokens[i])
            i += 1
    return out


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


def should_fire_wh_prior_drift_alert(previous_week_mean: float, current_week_mean: float) -> bool:
    """Return True when WH prior drift exceeds the configured threshold in percentage points."""
    drift_pp = abs(current_week_mean - previous_week_mean) * 100.0
    return drift_pp > float(cfg.nlp_wh_prior_drift_alert_pp)


def should_fire_politeness_distribution_drift_alert(
    previous_week_distribution: dict[str, float],
    current_week_distribution: dict[str, float],
) -> bool:
    """Return True when politeness class distribution drift exceeds the configured threshold in percentage points."""
    all_classes = set(previous_week_distribution) | set(current_week_distribution)
    if not all_classes:
        return False
    drift_pp = max(
        abs(current_week_distribution.get(politeness_class, 0.0) - previous_week_distribution.get(politeness_class, 0.0)) * 100.0
        for politeness_class in all_classes
    )
    return drift_pp > float(cfg.nlp_politeness_distribution_drift_pp)


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
    if not markers:
        return tokens, "neutral"

    marker_sequences = sorted(
        ((tuple(marker.lower().split()), cls) for marker, cls in markers.items()),
        key=lambda pair: len(pair[0]),
        reverse=True,
    )
    stripped_tokens: list[str] = []
    highest = "neutral"
    lower_tokens = [token.lower() for token in tokens]
    i = 0
    while i < len(tokens):
        matched = False
        for token_seq, cls in marker_sequences:
            seq_len = len(token_seq)
            if seq_len == 0 or i + seq_len > len(tokens):
                continue
            if tuple(lower_tokens[i : i + seq_len]) == token_seq:
                matched = True
                if cls == "very_polite":
                    highest = cls
                elif cls == "polite" and highest == "neutral":
                    highest = cls
                elif cls == "curt":
                    highest = "curt"
                i += seq_len
                break
        if not matched:
            stripped_tokens.append(tokens[i])
            i += 1

    return stripped_tokens, highest


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


def _compile_coordinating_particle_pattern(form: str) -> re.Pattern[str]:
    if "..." in form:
        parts = [part.strip() for part in form.split("...")]
        if len(parts) != 2 or not parts[0] or not parts[1]:
            raise Phase10SchemaError(
                "coordinating_particles.tr.yaml: invalid 'form' with ellipsis"
            )
        left, right = parts
        regex = rf"\b{re.escape(left)}\b(?:\s+\S+){{1,6}}\s+\b{re.escape(right)}\b"
    else:
        regex = rf"\b{re.escape(form)}\b"
    return re.compile(regex, re.IGNORECASE | re.UNICODE)


def load_coordinating_particles(path: Path | None = None) -> list[re.Pattern[str]]:
    actual_path = path or _LANG_TR_DIR / "morph" / "coordinating_particles.tr.yaml"
    if not actual_path.exists():
        return []
    raw = _load_yaml(actual_path)
    entries = raw.get("particles")
    if not isinstance(entries, list):
        raise Phase10SchemaError(f"{actual_path.name}: missing 'particles' list")
    result: list[re.Pattern[str]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise Phase10SchemaError(f"{actual_path.name}: each particle entry must be a mapping")
        form = entry.get("form")
        if not isinstance(form, str) or not form:
            raise Phase10SchemaError(f"{actual_path.name}: invalid particle form")
        result.append(_compile_coordinating_particle_pattern(form))
    return result


def detect_coordinating_particles(text: str) -> bool:
    patterns = load_coordinating_particles()
    if not patterns:
        return False
    lowered = text.lower()
    return any(pattern.search(lowered) for pattern in patterns)


def load_sarcasm_markers(path: Path | None = None) -> list[str]:
    actual_path = path or _LANG_TR_DIR / "sarcasm_markers.tr.yaml"
    if not actual_path.exists():
        return []
    raw = _load_yaml(actual_path)
    entries = raw.get("markers")
    if not isinstance(entries, list):
        raise Phase10SchemaError(f"{actual_path.name}: missing 'markers' list")
    return [str(item) for item in entries if isinstance(item, str)]


_SARCASM_CONTEXT_WINDOW_TOKENS = 10
_SARCASM_NEGATIVE_PHRASES = [
    "mağlubiyet",
    "kaybetti",
    "yenilgi",
    "kırmızı kart",
    "kovuldu",
    "ayrıldı",
    "sakatlık",
    "penaltı kaçırdı",
    "dağıldı",
    "çöktü",
    "hata",
]


def _find_phrase_positions(tokens: list[str], phrase: str) -> list[int]:
    phrase_tokens = tuple(phrase.split())
    if not phrase_tokens:
        return []
    positions: list[int] = []
    for idx in range(len(tokens) - len(phrase_tokens) + 1):
        if tuple(tokens[idx : idx + len(phrase_tokens)]) == phrase_tokens:
            positions.append(idx)
    return positions


def find_sarcasm_cue_ids(tokens: list[str]) -> list[str]:
    markers = load_sarcasm_markers()
    if not markers:
        return []

    lower_tokens = [token.lower() for token in tokens]
    cue_ids: list[str] = []
    for marker in markers:
        phrase_tokens = marker.lower().split()
        if not phrase_tokens:
            continue
        for idx in range(len(lower_tokens) - len(phrase_tokens) + 1):
            if tuple(lower_tokens[idx : idx + len(phrase_tokens)]) == tuple(phrase_tokens):
                cue_ids.append(marker)
    return cue_ids


def detect_sarcastic_modifier(tokens: list[str]) -> str:
    cue_ids = find_sarcasm_cue_ids(tokens)
    if not cue_ids:
        return "none"

    lower_tokens = [token.lower() for token in tokens]
    negative_positions: list[int] = []
    for phrase in _SARCASM_NEGATIVE_PHRASES:
        negative_positions.extend(_find_phrase_positions(lower_tokens, phrase))

    if not negative_positions:
        return "none"

    cue_positions: list[int] = []
    for cue_id in cue_ids:
        cue_positions.extend(_find_phrase_positions(lower_tokens, cue_id.lower()))

    for cue_pos in cue_positions:
        for neg_pos in negative_positions:
            if abs(cue_pos - neg_pos) <= _SARCASM_CONTEXT_WINDOW_TOKENS:
                return "sarcastic"

    return "none"


def find_sarcasm_cues_without_context(tokens: list[str]) -> list[dict[str, object]]:
    cue_ids = find_sarcasm_cue_ids(tokens)
    if not cue_ids:
        return []

    lower_tokens = [token.lower() for token in tokens]
    negative_positions: list[int] = []
    for phrase in _SARCASM_NEGATIVE_PHRASES:
        negative_positions.extend(_find_phrase_positions(lower_tokens, phrase))

    if negative_positions:
        return []

    results: list[dict[str, object]] = []
    for cue_id in cue_ids:
        phrase_tokens = cue_id.lower().split()
        if not phrase_tokens:
            continue
        for idx in range(len(lower_tokens) - len(phrase_tokens) + 1):
            if tuple(lower_tokens[idx : idx + len(phrase_tokens)]) == tuple(phrase_tokens):
                results.append(
                    {
                        "kind": "sarcasm_cue_no_context",
                        "cue_id": cue_id,
                        "cue_phrase": cue_id,
                        "span": (idx, idx + len(phrase_tokens)),
                    }
                )
    return results

    return [
        {
            "kind": "sarcasm_cue_no_context",
            "cue_id": marker,
            "cue_phrase": marker,
            "span": (pos, pos + length),
        }
        for marker, pos, length in cue_positions
    ]

def detect_conditional_modifier(tokens: list[str]) -> tuple[str | tuple[str, ...], str]:
    markers = load_conditional_markers()
    token_text = " ".join(tokens).lower()
    has_conditional = any(re.search(rf"\b{re.escape(marker)}\b", token_text) for marker in markers)
    if not has_conditional:
        return "none", "none"
    comparative = re.search(r"\b(daha|en|kadar|gibi|önde|geride|fazla|az)\b", token_text)
    modifier = ("conditional", "comparative") if comparative else "conditional"
    future = re.search(r"\b(kazanırsa|olursa|gelirse|atarsa)\b", token_text)
    past = re.search(r"\b(yenseydi|kazansaydı|olsaydı|olurdu|gelirseyd[iı])\b", token_text)
    if past:
        return modifier, "past"
    if future:
        return modifier, "future"
    return modifier, "present"


@dataclass(frozen=True)
class AnaphoraPronounEntry:
    pronoun: str
    type_constraint: str


ANAPHORA_TYPE_CONSTRAINTS: dict[str, frozenset[str] | None] = {
    "team_set": frozenset({"team", "player"}),
    "ambiguous": None,
    "person": frozenset({"player", "person", "coach", "referee"}),
    "venue": frozenset({"venue"}),
    "venue_direction": frozenset({"venue"}),
    "venue_or_group": frozenset({"venue", "team", "player"}),
}


def load_anaphora_pronouns(path: Path | None = None) -> dict[str, AnaphoraPronounEntry]:
    actual_path = path or _LANG_TR_DIR / "anaphora_pronouns.tr.yaml"
    if not actual_path.exists():
        return {}
    raw = _load_yaml(actual_path)
    entries = raw.get("entries")
    if not isinstance(entries, list):
        raise Phase10SchemaError(f"{actual_path.name}: missing required 'entries' list")
    result: dict[str, AnaphoraPronounEntry] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise Phase10SchemaError(f"{actual_path.name}: each entry must be a mapping")
        pronoun = entry.get("pronoun")
        type_constraint = entry.get("type_constraint")
        if not isinstance(pronoun, str) or not pronoun:
            raise Phase10SchemaError(f"{actual_path.name}: invalid pronoun")
        if not isinstance(type_constraint, str) or not type_constraint:
            raise Phase10SchemaError(f"{actual_path.name}: invalid type_constraint for {pronoun!r}")
        if pronoun in result:
            raise Phase10SchemaError(f"{actual_path.name}: duplicate pronoun {pronoun!r}")
        result[pronoun] = AnaphoraPronounEntry(pronoun=pronoun, type_constraint=type_constraint)
    return result


def detect_anaphora_pronouns(normalized_text: str) -> tuple[str, ...]:
    table = load_anaphora_pronouns()
    complementary = load_complementary_anaphora()
    if not table and not complementary:
        return ()
    lower = normalized_text.lower()
    matches: list[tuple[int, str]] = []
    for pronoun in sorted(
        list(table.keys()) + list(complementary), key=len, reverse=True
    ):
        for m in re.finditer(rf"\b{re.escape(pronoun)}\b", lower):
            matches.append((m.start(), pronoun))
    matches.sort(key=lambda item: item[0])
    return tuple(pronoun for _, pronoun in matches)


def resolve_anaphora_pronoun(
    pronoun: str,
    mention_stack: list[dict[str, object]],
    current_turn_index: int | None = None,
    current_time_iso: str | None = None,
) -> tuple[dict[str, object] | None, float]:
    if not pronoun or not mention_stack:
        return None, 0.0

    table = load_anaphora_pronouns()
    entry = table.get(pronoun)
    complementary = pronoun in load_complementary_anaphora()
    if entry is None and not complementary:
        return None, 0.0

    allowed_kinds = None if complementary else ANAPHORA_TYPE_CONSTRAINTS.get(entry.type_constraint)
    now_dt = None
    if current_time_iso is not None:
        try:
            now_dt = datetime.datetime.fromisoformat(current_time_iso)
        except ValueError:
            now_dt = None

    def _score_mention(mention: dict[str, object], *, skip_recency: bool = False) -> float:
        if current_turn_index is not None and isinstance(mention.get("mentioned_turn"), int):
            age_turns = current_turn_index - mention["mentioned_turn"]
            if age_turns < 0:
                age_turns = 0
            if age_turns >= int(cfg.nlp_anaphora_lookback_turns):
                return -1.0
        else:
            age_turns = 0

        if now_dt is not None and isinstance(mention.get("mentioned_at"), str):
            try:
                when = datetime.datetime.fromisoformat(mention["mentioned_at"])
                age_seconds = (now_dt - when).total_seconds()
            except ValueError:
                age_seconds = 0.0
            if age_seconds >= int(cfg.nlp_anaphora_lookback_seconds):
                return -1.0
        else:
            age_seconds = 0.0

        salience = 0.5
        if isinstance(mention.get("confidence"), (float, int)):
            salience = min(1.0, max(0.0, float(mention["confidence"])))

        if skip_recency:
            return salience

        if int(cfg.nlp_anaphora_lookback_turns) > 0:
            recency_weight = max(0.0, 1.0 - (age_turns / float(cfg.nlp_anaphora_lookback_turns)))
        else:
            recency_weight = 1.0

        return recency_weight * salience

    def _best_candidate(mentions: list[dict[str, object]]) -> tuple[dict[str, object] | None, float]:
        best_candidate: dict[str, object] | None = None
        best_score = 0.0
        for mention in reversed(mentions):
            if not isinstance(mention, dict):
                continue
            kind = mention.get("kind")
            canonical_id = mention.get("canonical_id")
            if not isinstance(kind, str) or not isinstance(canonical_id, str):
                continue
            if allowed_kinds is not None and kind not in allowed_kinds:
                continue

            score = _score_mention(mention)
            if score <= best_score:
                continue
            best_score = score
            best_candidate = mention

        return best_candidate, best_score

    user_mentions = [m for m in mention_stack if isinstance(m, dict) and m.get("mentioned_by") == "user"]
    system_mentions = [m for m in mention_stack if isinstance(m, dict) and m.get("mentioned_by") != "user"]

    user_candidate, user_score = _best_candidate(user_mentions)

    complementary = pronoun in load_complementary_anaphora()
    eligible_system_mentions = [
        mention
        for mention in system_mentions
        if isinstance(mention, dict)
        and isinstance(mention.get("kind"), str)
        and isinstance(mention.get("canonical_id"), str)
        and (allowed_kinds is None or mention["kind"] in allowed_kinds)
    ]

    if not complementary:
        if user_candidate is not None and user_score >= float(cfg.nlp_anaphora_min_antecedent_confidence):
            return user_candidate, user_score
        if user_mentions:
            return None, 0.0
        if len(eligible_system_mentions) > 1:
            return None, 0.0
        if len(eligible_system_mentions) == 1:
            mention = eligible_system_mentions[0]
            score = _score_mention(mention)
            if score >= float(cfg.nlp_anaphora_min_antecedent_confidence):
                return mention, score
        return None, 0.0

    if user_candidate is not None and user_score >= float(cfg.nlp_anaphora_min_antecedent_confidence):
        for mention in reversed(eligible_system_mentions):
            if (
                mention.get("canonical_id") != user_candidate.get("canonical_id")
                or mention.get("kind") != user_candidate.get("kind")
            ):
                score = _score_mention(mention, skip_recency=True)
                if score >= float(cfg.nlp_anaphora_min_antecedent_confidence):
                    mention["mentioned_by"] = "system"
                    return mention, score
        return None, 0.0

    # Resolve to the previous system entity when the pronoun itself indicates "the other one".
    if len(eligible_system_mentions) >= 2:
        latest = eligible_system_mentions[-1]
        for mention in reversed(eligible_system_mentions[:-1]):
            if (
                mention.get("canonical_id") != latest.get("canonical_id")
                or mention.get("kind") != latest.get("kind")
            ):
                score = _score_mention(mention, skip_recency=True)
                if score >= float(cfg.nlp_anaphora_min_antecedent_confidence):
                    mention["mentioned_by"] = "system"
                    return mention, score
    return None, 0.0

    if user_candidate is not None and user_score >= float(cfg.nlp_anaphora_min_antecedent_confidence):
        return user_candidate, user_score

    system_candidate, system_score = _best_candidate(system_mentions)
    if system_candidate is not None and system_score >= float(cfg.nlp_anaphora_min_antecedent_confidence):
        return system_candidate, system_score

    return None, max(user_score, system_score)


def load_complementary_anaphora(path: Path | None = None) -> frozenset[str]:
    actual_path = path or _COMPLEMENTARY_ANAPHORA_PATH
    if not actual_path.exists():
        return frozenset()
    raw = _load_yaml(actual_path)
    entries = raw.get("entries")
    if not isinstance(entries, list):
        raise Phase10SchemaError(f"{actual_path.name}: missing required 'entries' list")

    result: set[str] = set()
    for entry in entries:
        if not isinstance(entry, str) or not entry.strip():
            raise Phase10SchemaError(f"{actual_path.name}: each entry must be a non-empty string")
        result.add(entry.strip().lower())
    return frozenset(result)


def load_anaphora_compose(path: Path | None = None) -> set[frozenset[str]]:
    actual_path = path or _LANG_TR_DIR / "anaphora_compose.yaml"
    if not actual_path.exists():
        return set()
    raw = _load_yaml(actual_path)
    entries = raw.get("entries")
    if not isinstance(entries, list):
        raise Phase10SchemaError(f"{actual_path.name}: missing required 'entries' list")

    result: set[frozenset[str]] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise Phase10SchemaError(f"{actual_path.name}: each entry must be a mapping")
        pronouns = entry.get("pronouns")
        if not isinstance(pronouns, list) or len(pronouns) < 2:
            raise Phase10SchemaError(
                f"{actual_path.name}: invalid pronouns list {pronouns!r}"
            )
        normalized = frozenset(str(item).strip().lower() for item in pronouns if isinstance(item, str) and item)
        if len(normalized) != len(pronouns):
            raise Phase10SchemaError(
                f"{actual_path.name}: pronouns must be unique strings, got {pronouns!r}"
            )
        result.add(normalized)
    return result


def is_legal_anaphora_composition(pronouns: tuple[str, ...]) -> bool:
    if len(pronouns) < 2:
        return True
    table = load_anaphora_compose()
    if not table:
        return False
    return frozenset(pronouns) in table


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
        match_key: tuple[int, tuple[str, ...]] = (-1, ())
        for entry in phrasebook:
            idiom = str(entry.get("idiom", "")).split()
            if not idiom or len(idiom) > max_len:
                continue
            if i + len(idiom) > len(tokens):
                continue
            idiom_lower = tuple(w.lower() for w in idiom)
            if lowered[i:i + len(idiom)] == list(idiom_lower):
                candidate_key = (len(idiom), idiom_lower)
                if candidate_key > match_key:
                    match = entry
                    match_len = len(idiom)
                    match_key = candidate_key
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
