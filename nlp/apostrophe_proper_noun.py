"""Phase 10 §10.32.5 — Input-side apostrophe repair for proper nouns."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Callable, NamedTuple, Optional

import yaml

from ai.common.text.turkish import (
    lowercase_tr,
    strip_proper_noun_suffix,
    is_harmony_tolerant_suffix_candidate,
    _BACK_VOWELS,
    _FRONT_VOWELS,
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
_WORD_FREQ_PATH: Path = (
    Path(__file__).resolve().parents[1] / "nlp" / "data" / "tr_word_freq.txt"
)
_WORD_FREQ_CACHE: dict[str, int] | None = None
_LEXICON_STEM_CACHE: set[str] | None = None
_LEXICON_STEM_FOLD_CACHE: dict[str, str] | None = None

_TR_ASCII_FOLD_TABLE: dict[int, str] = str.maketrans({
    "ç": "c",
    "ğ": "g",
    "ı": "i",
    "ö": "o",
    "ş": "s",
    "ü": "u",
    "Ç": "c",
    "Ğ": "g",
    "İ": "i",
    "Ö": "o",
    "Ş": "s",
    "Ü": "u",
})

_LEXICON_DIR: Path = (
    Path(__file__).resolve().parents[1] / "nlp" / "lexicon"
)

_APOSTROPHE_TOKEN_SPLIT_RE = re.compile(r"[\s\?!\:\;\(\)\[\]/|\-]+")


def load_proper_noun_apostrophe_spec(path: Path | None = None) -> dict:
    return _load_json(path or _DEFAULT_SPEC_PATH)


def load_proper_noun_apostrophe_suffix_forms(path: Path | None = None) -> tuple[str, ...]:
    spec = load_proper_noun_apostrophe_spec(path)
    suffixes: list[str] = []
    for family in spec.get("suffix_families", []):
        if not isinstance(family, dict):
            continue
        for form in family.get("forms", []):
            if isinstance(form, str):
                normalized_form = form.strip()
                if normalized_form and normalized_form not in suffixes:
                    suffixes.append(normalized_form)
    return tuple(suffixes)


def proper_noun_apostrophe_spec_sha256(path: Path | None = None) -> str:
    spec_path = path or _DEFAULT_SPEC_PATH
    return hashlib.sha256(spec_path.read_bytes()).hexdigest()



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


def _load_word_frequency(path: Path | None = None) -> dict[str, int]:
    global _WORD_FREQ_CACHE
    effective = path or _WORD_FREQ_PATH
    if path is None and _WORD_FREQ_CACHE is not None:
        return _WORD_FREQ_CACHE

    word_freq: dict[str, int] = {}
    with open(effective, "r", encoding="utf-8") as fh:
        for line in fh:
            parts = line.strip().split("\t")
            if len(parts) != 2:
                continue
            token, count = parts
            try:
                word_freq[token] = int(count)
            except ValueError:
                continue

    if path is None:
        _WORD_FREQ_CACHE = word_freq
    return word_freq


def _ascii_fold_tr(text: str) -> str:
    return lowercase_tr(text).translate(_TR_ASCII_FOLD_TABLE)


def _load_lexicon_stems(path: Path | None = None) -> set[str]:
    global _LEXICON_STEM_CACHE
    effective = path or _LEXICON_DIR
    if path is None and _LEXICON_STEM_CACHE is not None:
        return _LEXICON_STEM_CACHE

    stems: set[str] = set()
    for child in effective.iterdir():
        if not child.is_file() or not child.name.endswith(('.tr.yaml', '.tr-TR.yaml')):
            continue
        raw = _load_yaml(child)
        entries = raw.get('entries', [])
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            for value in entry.values():
                if isinstance(value, str):
                    stems.add(lowercase_tr(value.strip()))
                elif isinstance(value, list):
                    for item in value:
                        if isinstance(item, str):
                            stems.add(lowercase_tr(item.strip()))
    if path is None:
        _LEXICON_STEM_CACHE = stems
    return stems


def _contains_turkish_diacritic(text: str) -> bool:
    return text != text.translate(_TR_ASCII_FOLD_TABLE)


def _load_lexicon_stem_map(path: Path | None = None) -> dict[str, str]:
    global _LEXICON_STEM_FOLD_CACHE
    effective = path or _LEXICON_DIR
    if path is None and _LEXICON_STEM_FOLD_CACHE is not None:
        return _LEXICON_STEM_FOLD_CACHE

    stem_map: dict[str, str] = {}
    stems = _load_lexicon_stems(path)
    for stem in stems:
        folded = _ascii_fold_tr(stem)
        if not folded:
            continue
        existing = stem_map.get(folded)
        if existing is None:
            stem_map[folded] = stem
            continue
        if _contains_turkish_diacritic(stem) and not _contains_turkish_diacritic(existing):
            stem_map[folded] = stem

    if path is None:
        _LEXICON_STEM_FOLD_CACHE = stem_map
    return stem_map


def load_apostrophe_repair_rules(path: Path = _DEFAULT_APOSTROPHE_RULE_PATH) -> dict:
    raw = _load_yaml(path)
    return raw.get("apostrophe_repair", {}) if isinstance(raw.get("apostrophe_repair"), dict) else {}

def _get_punctuation_substitution_chars(rules: dict) -> tuple[str, ...]:
    rule = rules.get("punctuation_substitution", {})
    if not isinstance(rule, dict):
        return (",", ".", "`")
    chars = rule.get("chars", [])
    if not isinstance(chars, list):
        return (",", ".", "`")
    return tuple(str(ch) for ch in chars if isinstance(ch, str) and len(ch) == 1)

def load_apostrophe_no_insert_allowlist(path: Path = _DEFAULT_APOSTROPHE_NO_INSERT_PATH) -> set[str]:
    raw = _load_yaml(path)
    items = raw.get("no_insert_allowlist", [])
    if not isinstance(items, list):
        return set()
    return {lowercase_tr(str(item).strip()) for item in items if isinstance(item, str) and item.strip()}


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
    shout: bool = False,
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
    spec = load_proper_noun_apostrophe_spec(spec_path)
    suffix_forms = load_proper_noun_apostrophe_suffix_forms(spec_path)
    internal_allowlist |= {
        lowercase_tr(str(value).strip())
        for value in spec.get("internal_apostrophe_allowlist", [])
        if isinstance(value, str)
    }
    no_insert_allowlist = load_apostrophe_no_insert_allowlist(no_insert_path or _DEFAULT_APOSTROPHE_NO_INSERT_PATH)
    substitution_chars = _get_punctuation_substitution_chars(rules)

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
            suffix_forms=suffix_forms,
            substitution_chars=substitution_chars,
            input_source=input_source,
            event_sink=event_sink,
            shout=shout,
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
    suffix_forms: tuple[str, ...],
    *,
    substitution_chars: tuple[str, ...] = (",", ".", "`"),
    input_source: str = "keyboard",
    event_sink: Callable[[dict[str, str]], None] | None = None,
    shout: bool = False,
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

    if shout and "'" not in original_token:
        return token, None

    if not original_token[0].isupper():
        return token, None

    substituted = _repair_punctuation_substitution(
        token,
        internal_allowlist,
        no_insert_allowlist,
        substitution_chars=substitution_chars,
        event_sink=event_sink,
    )
    if substituted is not None:
        candidate, found_char = substituted
        return candidate, ApostropheRepair(
            original=lowercase_tr(original_token),
            repaired=candidate,
            rule_id="punctuation_apostrophe_substitution",
            rule_class="punctuation_apostrophe_substitution",
            evidence=f"substituted={found_char}",
        )

    if len(token) < 7 or token in no_insert_allowlist:
        return token, None

    repaired = _repair_missing_apostrophe(
        token,
        internal_allowlist,
        no_insert_allowlist,
        suffix_forms,
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


def _repair_punctuation_substitution(
    token: str,
    internal_allowlist: set[str],
    no_insert_allowlist: set[str],
    *,
    substitution_chars: tuple[str, ...],
    event_sink: Callable[[dict[str, str]], None] | None = None,
) -> tuple[str, str] | None:
    for char in substitution_chars:
        if char not in token:
            continue
        candidate = token.replace(char, "'")
        if candidate in internal_allowlist or candidate in no_insert_allowlist:
            continue
        if _is_valid_apostrophe_token(candidate):
            if event_sink is not None:
                event_sink({"kind": "apostrophe_punctuation_substituted", "found": char})
            return candidate, char
    return None


def _repair_missing_apostrophe(
    token: str,
    internal_allowlist: set[str],
    no_insert_allowlist: set[str],
    suffix_forms: tuple[str, ...],
    event_sink: Callable[[dict[str, str]], None] | None = None,
    fallback_trailing_char: bool = True,
) -> str | None:
    candidates: list[tuple[int, int, int, str, str]] = []
    word_freq = _load_word_frequency()
    lexicon_stems = _load_lexicon_stems()
    lexicon_stem_map = _load_lexicon_stem_map()
    extra_vowel_final_dative = ("na", "ne")
    for suffix in (*suffix_forms, *extra_vowel_final_dative):
        if not token.endswith(suffix) or len(token) <= len(suffix):
            continue
        if suffix in extra_vowel_final_dative:
            stem_candidate = token[: len(token) - len(suffix)]
            if not stem_candidate:
                continue
            last_char = lowercase_tr(stem_candidate[-1])
            if last_char not in (_FRONT_VOWELS | _BACK_VOWELS):
                continue
        candidate = token[: len(token) - len(suffix)] + "'" + suffix
        if candidate in internal_allowlist or candidate in no_insert_allowlist:
            continue
        if _is_valid_apostrophe_token(candidate):
            stem, _ = strip_proper_noun_suffix(candidate, assume_proper=True)
            stem_lower = lowercase_tr(stem)
            stem_folded = _ascii_fold_tr(stem_lower)
            freq = word_freq.get(stem_lower, 0)
            lexicon_match = 1 if stem_lower in lexicon_stems or stem_folded in lexicon_stem_map else 0
            candidates.append((freq, lexicon_match, len(stem), candidate, stem_lower))

    if not candidates:
        if fallback_trailing_char and token and token[-1] in {"s", "y"}:
            token_folded = _ascii_fold_tr(token)
            if token in lexicon_stems or token_folded in lexicon_stem_map:
                return None
            shorter = token[:-1]
            shorter_folded = _ascii_fold_tr(shorter)
            if shorter in lexicon_stems or shorter_folded in lexicon_stem_map:
                return _repair_missing_apostrophe(
                    shorter,
                    internal_allowlist,
                    no_insert_allowlist,
                    suffix_forms,
                    event_sink=event_sink,
                    fallback_trailing_char=False,
                )
        return None

    best_freq = max(freq for freq, _, _, _, _ in candidates)
    best_by_freq = [
        (lexicon_match, stem_len, candidate, stem_lower)
        for freq, lexicon_match, stem_len, candidate, stem_lower in candidates
        if freq == best_freq
    ]
    if len(best_by_freq) == 1:
        repaired = _restore_lexicon_stem(best_by_freq[0][2], best_by_freq[0][3], lexicon_stem_map)
        _emit_suffix_harmony_repair_event(repaired, event_sink)
        return repaired

    best_lexicon_match = max(lexicon_match for lexicon_match, _, _, _ in best_by_freq)
    best_by_lexicon = [
        (stem_len, candidate, stem_lower)
        for lexicon_match, stem_len, candidate, stem_lower in best_by_freq
        if lexicon_match == best_lexicon_match
    ]
    if len(best_by_lexicon) == 1:
        repaired = _restore_lexicon_stem(best_by_lexicon[0][1], best_by_lexicon[0][2], lexicon_stem_map)
        _emit_suffix_harmony_repair_event(repaired, event_sink)
        return repaired

    best_stem_len = min(stem_len for stem_len, _, _ in best_by_lexicon)
    unique_best = {candidate for stem_len, candidate, _ in best_by_lexicon if stem_len == best_stem_len}
    if len(unique_best) == 1:
        repaired = unique_best.pop()
        _emit_suffix_harmony_repair_event(repaired, event_sink)
        return repaired
    return None


def _restore_lexicon_stem(candidate: str, stem_lower: str, stem_map: dict[str, str]) -> str:
    if not candidate or not stem_lower:
        return candidate

    canon = stem_map.get(_ascii_fold_tr(stem_lower))
    if canon is None:
        return candidate

    if "'" not in candidate:
        return candidate

    suffix = candidate.rsplit("'", 1)[1]
    return canon + "'" + suffix


def _repair_misplaced_apostrophe(
    token: str,
    internal_allowlist: set[str],
    no_insert_allowlist: set[str],
    event_sink: Callable[[dict[str, str]], None] | None = None,
    fallback_trailing_char: bool = True,
) -> str | None:
    raw = token.replace("'", "")
    if len(raw) < 7:
        return None

    candidates: list[tuple[int, int, str, str]] = []
    lexicon_stems = _load_lexicon_stems()
    lexicon_stem_map = _load_lexicon_stem_map()
    for split in range(1, len(raw)):
        candidate = raw[:split] + "'" + raw[split:]
        if candidate == token:
            continue
        if candidate in internal_allowlist or candidate in no_insert_allowlist:
            continue
        if _is_valid_apostrophe_token(candidate):
            stem, _ = strip_proper_noun_suffix(candidate, assume_proper=True)
            stem_lower = lowercase_tr(stem)
            stem_folded = _ascii_fold_tr(stem_lower)
            lexicon_match = 1 if stem_lower in lexicon_stems or stem_folded in lexicon_stem_map else 0
            candidates.append((lexicon_match, len(stem), candidate, stem_lower))

    if not candidates:
        if fallback_trailing_char and raw and raw[-1] in {"s", "y"}:
            return _repair_misplaced_apostrophe(
                token[:-1],
                internal_allowlist,
                no_insert_allowlist,
                event_sink=event_sink,
                fallback_trailing_char=False,
            )
        return None

    best_match = max(match for match, _, _, _ in candidates)
    best_by_match = [
        (stem_len, candidate, stem_lower)
        for match, stem_len, candidate, stem_lower in candidates
        if match == best_match
    ]
    if len(best_by_match) == 1:
        repaired = _restore_lexicon_stem(best_by_match[0][1], best_by_match[0][2], lexicon_stem_map)
        _emit_suffix_harmony_repair_event(repaired, event_sink)
        return repaired

    best_length = max(stem_len for stem_len, _, _ in best_by_match)
    best_candidates = [
        (candidate, stem_lower)
        for stem_len, candidate, stem_lower in best_by_match
        if stem_len == best_length
    ]
    if len(best_candidates) == 1:
        repaired = _restore_lexicon_stem(best_candidates[0][0], best_candidates[0][1], lexicon_stem_map)
        _emit_suffix_harmony_repair_event(repaired, event_sink)
        return repaired
    return None
