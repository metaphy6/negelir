from __future__ import annotations

import datetime
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from common.config import cfg
from common.text.turkish import parse_number_word

_LANG_TR_DIR = Path(__file__).parent / "lang_tr"

GOVERNANCE_HIGH_LEVERAGE_LEXICON_FILES = frozenset({
    "idioms.tr.yaml",
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


def detect_sarcastic_modifier(tokens: list[str]) -> str:
    markers = load_sarcasm_markers()
    if not markers:
        return "none"

    lower_tokens = [token.lower() for token in tokens]
    cue_positions: list[int] = []
    for marker in markers:
        cue_positions.extend(_find_phrase_positions(lower_tokens, marker.lower()))

    if not cue_positions:
        return "none"

    negative_positions: list[int] = []
    for phrase in _SARCASM_NEGATIVE_PHRASES:
        negative_positions.extend(_find_phrase_positions(lower_tokens, phrase))

    if not negative_positions:
        return "none"

    for cue_pos in cue_positions:
        for neg_pos in negative_positions:
            if abs(cue_pos - neg_pos) <= _SARCASM_CONTEXT_WINDOW_TOKENS:
                return "sarcastic"

    return "none"


def detect_conditional_modifier(tokens: list[str]) -> tuple[str | tuple[str, ...], str]:
    markers = load_conditional_markers()
    token_text = " ".join(tokens).lower()
    has_conditional = any(re.search(rf"\b{re.escape(marker)}\b", token_text) for marker in markers)
    if not has_conditional:
        return "none", "none"
    comparative = re.search(r"\b(daha|en|kadar|gibi|önde|geride|fazla|az)\b", token_text)
    modifier = ("conditional", "comparative") if comparative else "conditional"
    future = re.search(r"\b(kazanırsa|olursa|gelirse|atarsa)\b", token_text)
    past = re.search(r"\b(kazansaydı|olurdu|gelirseyd[iı])\b", token_text)
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
    if not table:
        return ()
    lower = normalized_text.lower()
    matches: list[tuple[int, str]] = []
    for pronoun in sorted(table.keys(), key=len, reverse=True):
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

    entry = load_anaphora_pronouns().get(pronoun)
    if entry is None:
        return None, 0.0

    allowed_kinds = ANAPHORA_TYPE_CONSTRAINTS.get(entry.type_constraint)
    best_candidate: dict[str, object] | None = None
    best_score = 0.0
    now_dt = None
    if current_time_iso is not None:
        try:
            now_dt = datetime.datetime.fromisoformat(current_time_iso)
        except ValueError:
            now_dt = None

    for mention in reversed(mention_stack):
        if not isinstance(mention, dict):
            continue
        kind = mention.get("kind")
        canonical_id = mention.get("canonical_id")
        if not isinstance(kind, str) or not isinstance(canonical_id, str):
            continue
        if allowed_kinds is not None and kind not in allowed_kinds:
            continue

        if current_turn_index is not None and isinstance(mention.get("mentioned_turn"), int):
            age_turns = current_turn_index - mention["mentioned_turn"]
            if age_turns < 0:
                age_turns = 0
            if age_turns >= int(cfg.nlp_anaphora_lookback_turns):
                continue
        else:
            age_turns = 0

        if now_dt is not None and isinstance(mention.get("mentioned_at"), str):
            try:
                when = datetime.datetime.fromisoformat(mention["mentioned_at"])
                age_seconds = (now_dt - when).total_seconds()
            except ValueError:
                age_seconds = 0.0
            if age_seconds >= int(cfg.nlp_anaphora_lookback_seconds):
                continue
        else:
            age_seconds = 0.0

        if int(cfg.nlp_anaphora_lookback_turns) > 0:
            recency_weight = max(0.0, 1.0 - (age_turns / float(cfg.nlp_anaphora_lookback_turns)))
        else:
            recency_weight = 1.0

        salience = 0.5
        if isinstance(mention.get("confidence"), (float, int)):
            salience = min(1.0, max(0.0, float(mention["confidence"])))

        score = recency_weight * salience
        if score > best_score:
            best_score = score
            best_candidate = mention

    if best_score < float(cfg.nlp_anaphora_min_antecedent_confidence):
        return None, best_score
    return best_candidate, best_score


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
