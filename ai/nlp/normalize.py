"""Phase 10 §10.1 -- Input normalization pipeline (9-step, ordered, idempotent).

Steps (order is BINDING; any reordering breaks downstream tests):

  1. Length cap: reject inputs that exceed ``cfg.nlp_input_max_codepoints``.
  2. NFC normalize.
  3. Control-char + zero-width + RTL-override strip.
     (Steps 2+3 are fused into ``canonical_normalize`` for Python/Go parity.)
  3.5. Unicode confusables fold (§10.21.5): Cyrillic/Greek lookalikes -> ASCII-Turkish.
  4. Turkish-aware lowercase (I->dotless-i, dotted-I->i; NEVER ``str.lower()``).
  5. Punctuation normalization (curly quotes, em/en-dash, multiple spaces).
  6. Diacritic restoration (table-driven).  [\u00a7 10.3 stub -- pass-through]
  7. Tokenization (whitespace + punctuation split).
  8. Token-level typo correction.             [\u00a7 10.3 stub -- pass-through]

Usage::

    from nlp.normalize import normalize_input, InputTooLongError
    from common.config import cfg

    try:
        result = normalize_input("Galatasaray mac tahmini", cfg=cfg)
    except InputTooLongError:
        ...

"""
from __future__ import annotations

import re
import time
import unicodedata
from dataclasses import dataclass
from typing import Any, Callable, Optional

from common.text.normalize import canonical_normalize, confusables_fold
from common.text.turkish import lowercase_tr
from nlp._particle_normalize import (
    _is_valid_stem as _is_valid_particle_stem,
    _last_vowel as _particle_last_vowel,
    load_rules as _load_particle_rules,
    normalize_particles as _normalize_particles,
)
from nlp.dialect_normalize import (
    apply_dialect_normalize as _apply_dialect_normalize,
    _DialectNormalizer,
)
from nlp.postposition_stack import (
    detect_postposition_stacks,
    PostpositionStackMatch,
    UnknownPostpositionStack,
)
from nlp.phase10_30 import (
    detect_conditional_modifier,
    detect_search_operator_syntax_in_text,
    expand_idioms,
    strip_politeness_markers,
)
from nlp.apostrophe_proper_noun import (
    ApostropheRepair,
    repair_apostrophe_proper_noun,
)
from nlp.assimilation import (
    AssimilationRules,
    fold_assimilated_suffixes,
    load_assimilation_pairs,
)
from nlp.compound_splitter import split_compound_tokens
from nlp.consonant_alternation import (
    ConsonantAlternationRule,
    load_consonant_alternations,
    tolerate_consonant_alternation,
)
from nlp.regional_dialect_normalize import (
    apply_regional_dialect_normalize,
    load_dialect_no_rewrite_canonicals,
    RegionalDialectRewrite,
)

# ---------------------------------------------------------------------------
# Step 5 -- punctuation normalization
# ---------------------------------------------------------------------------
# Codepoint -> replacement-string table for str.translate().
# Values are strings (Python str.translate supports str values).
_PUNCT_TABLE: dict[int, str] = {
    ord("\u201C"): '"',    # LEFT DOUBLE QUOTATION MARK  -> straight "
    ord("\u201D"): '"',    # RIGHT DOUBLE QUOTATION MARK -> straight "
    ord("\u201E"): '"',    # DOUBLE LOW-9 QUOTATION MARK -> straight "
    ord("\u2018"): "'",    # LEFT SINGLE QUOTATION MARK  -> straight apostrophe
    ord("\u2019"): "'",    # RIGHT SINGLE QUOTATION MARK -> straight apostrophe
    ord("\u02BC"): "'",    # MODIFIER LETTER APOSTROPHE  -> straight apostrophe (§10.22.2)
    ord("\u0060"): "'",    # GRAVE ACCENT                -> straight apostrophe (§10.22.2)
    ord("\u00B4"): "'",    # ACUTE ACCENT                -> straight apostrophe (§10.22.2)
    ord("\u201A"): ",",    # SINGLE LOW-9 QUOTATION MARK -> comma
    ord("\u2014"): " - ",  # EM DASH  -> hyphen-space-hyphen
    ord("\u2013"): " - ",  # EN DASH  -> hyphen-space-hyphen
    ord("\u2026"): "...",  # HORIZONTAL ELLIPSIS -> three dots
    ord("\u00B7"): ".",    # MIDDLE DOT -> period
}

# Collapse multiple consecutive spaces produced after em/en-dash expansion.
_MULTI_SPACE_RE = re.compile(r" {2,}")

# ---------------------------------------------------------------------------
# Step 5a -- Unicode space collapse (Phase 10 §10.33.3)
# ---------------------------------------------------------------------------
# Collapse every Unicode Zs category to ASCII space before tokenization.
# This prevents invisible whitespace from silently joining tokens.
def _collapse_unicode_spaces(text: str, enabled: bool) -> str:
    if not enabled:
        return text
    return "".join(
        " " if unicodedata.category(ch) == "Zs" else ch for ch in text
    )

# ---------------------------------------------------------------------------
# Step 7 -- tokenization
# ---------------------------------------------------------------------------
# Split on sequences of whitespace + common punctuation boundaries.
# Apostrophes inside tokens are preserved (e.g. Turkish suffix "yarin'ki").
_TOKEN_SPLIT_RE = re.compile(r"[\s,\.\?!\:;()\[\]/|]+")


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------
class InputTooLongError(ValueError):
    """Raised by step 1 when input exceeds ``cfg.nlp_input_max_codepoints``."""


@dataclass(frozen=True)
class NormalizedInput:
    """Result of the 8-step normalization pipeline.

    Attributes
    ----------
    tokens:
        Ordered tuple of normalized tokens (post all 8 steps).
    steps_run:
        Ordered tuple of step names that were executed.  Consumers use
        this for forensic tracing and to assert ordering in tests.
    original_codepoint_count:
        ``len(raw_text)`` before any transforms.
    typo_budget_exhausted:
        ``True`` when the per-query fuzzy-lookup budget was hit during
        step 8 (§10.3 Per-query budget).  Callers should emit
        ``nlp.event.v1{kind=did_you_mean_offered}`` and return a
        "Did you mean?" response rather than treating the partial
        correction as authoritative.
    """

    tokens: tuple[str, ...]
    steps_run: tuple[str, ...]
    original_codepoint_count: int
    typo_budget_exhausted: bool = False
    stage_timed_out: bool = False
    """True when the normalize+diacritic+typo stage exceeded
    ``cfg.nlp_normalize_stage_timeout_ms``.  The caller is responsible
    for emitting ``nlp.event.v1{kind=normalize_timeout}``.
    """
    particle_repairs: frozenset = frozenset()
    """Set of original token strings split by step 8a (§10.22.4 particle
    disambiguation).  Consumers can use this to detect which tokens were
    reconstructed from attached particles.
    """
    dialect_repairs: frozenset = frozenset()
    """Set of (original_token, rule_id) pairs where a token was rewritten
    by a dialect rule in step 8b (§10.22.5 colloquial normalization).
    """
    regional_dialect_rewrites: tuple[RegionalDialectRewrite, ...] = tuple()
    """Regional dialect rewrites applied before tokenization (§10.32.4)."""
    dialect_alternatives: tuple[tuple[str, str], ...] = tuple()
    """Canonicalized alternatives preserved for audit_only=false rewrites."""
    apostrophe_repairs: tuple[tuple[str, str, str], ...] = tuple()
    """Set of (original_token, repaired_token, rule_id) repairs applied in step 6.7."""
    consonant_alternation_repairs: tuple[tuple[str, str], ...] = tuple()
    """Set of (original_token, repaired_token) repairs applied in step 8a.1."""
    consonant_alternation_events: tuple[dict[str, str], ...] = tuple()
    """Telemetry-friendly events emitted by consonant alternation repairs."""
    politeness_class: str = "neutral"
    """Detected politeness marker class after normalizing polite/casual tokens."""
    query_style: str = "natural"
    """Detected query style for the input, e.g. natural, search, quoted_exact_search."""
    intent_modifier: str = "none"
    """Detected intent modifier such as conditional or comparative."""
    idiom_events: tuple[dict[str, Any], ...] = tuple()
    """Logged idiom expansion/ambiguity events discovered during normalization."""
    vocatives_stripped: tuple = ()
    """Tokens removed by the vocative/filler-strip sub-step of step 8b
    (§10.22.5).  The classifier never sees these tokens.
    """
    abbreviations_expanded: frozenset = frozenset()
    """Set of (abbrev_token, expansion_id) pairs where a hard abbreviation
    was expanded in step 8b (§10.22.5).
    """
    soft_abbreviations_tagged: frozenset = frozenset()
    """Set of (abbrev_token, expansion_id, frozenset(co_tokens)) for soft
    abbreviations that need downstream resolution (§10.5 conflict resolver).
    """
    slurs_stripped: tuple[str, ...] = tuple()
    """Tokens stripped from the query as offensive slurs before classifier.
    """
    compound_split_events: tuple[dict[str, object], ...] = tuple()
    """Telemetry-friendly events emitted by the compound splitter in step 7.5."""
    postposition_stack_matches: tuple[PostpositionStackMatch, ...] = tuple()
    """Detected closed postposition stacks in the token stream."""
    postposition_stack_unknowns: tuple[UnknownPostpositionStack, ...] = tuple()
    """Unknown marker stacks that should fall through and emit an event."""


def _classify_particle_repairs(repaired_originals: frozenset[str]) -> dict[str, int]:
    """Classify repaired particle tokens into the Phase 10 repair buckets."""
    if not repaired_originals:
        return {}

    rules = _load_particle_rules()
    mi_cfg = rules["mi_variants"]
    mi_all: list[str] = list(mi_cfg["all_variants"])
    mi_harmony: dict[str, str] = mi_cfg["four_way_harmony"]
    all_vowels = frozenset(rules["vowel_sets"]["all_vowels"])
    front_vowels = frozenset(rules["vowel_sets"]["front"])
    mi_min_stem = int(mi_cfg["min_stem_length"])

    de_da_cfg = rules["de_da"]
    front_p = de_da_cfg["front_variant"]
    back_p = de_da_cfg["back_variant"]
    de_da_particles = (front_p, back_p)
    de_da_min_stem = int(de_da_cfg["min_stem_length"])

    ki_cfg = rules["ki"]
    ki_particle = ki_cfg["particle"]
    ki_min_stem = int(ki_cfg["min_stem_length"])

    counts = {
        "particle_detached_mi": 0,
        "particle_repaired_de_da": 0,
        "particle_repaired_ki": 0,
    }

    for tok in repaired_originals:
        classified = False
        for variant in mi_all:
            if len(tok) <= len(variant) or not tok.endswith(variant):
                continue
            stem = tok[: -len(variant)]
            if not _is_valid_particle_stem(stem, mi_min_stem, all_vowels):
                continue
            last_v = _particle_last_vowel(stem, all_vowels)
            if last_v is None:
                continue
            harmony_base = variant[:2]
            if mi_harmony.get(last_v) == harmony_base:
                counts["particle_detached_mi"] += 1
                classified = True
                break
        if classified:
            continue

        if len(tok) > 2 and tok[-2:] in de_da_particles:
            stem = tok[:-2]
            if _is_valid_particle_stem(stem, de_da_min_stem, all_vowels):
                last_v = _particle_last_vowel(stem, all_vowels)
                if last_v is not None:
                    expected_p = front_p if last_v in front_vowels else back_p
                    if expected_p == tok[-2:]:
                        counts["particle_repaired_de_da"] += 1
                        classified = True
        if classified:
            continue

        if len(tok) > len(ki_particle) and tok.endswith(ki_particle):
            stem = tok[: -len(ki_particle)]
            if _is_valid_particle_stem(stem, ki_min_stem, all_vowels):
                counts["particle_repaired_ki"] += 1
                continue

    return counts


def _record_nlp_input_repair_metrics(
    result: "NormalizedInput",
    token_count: int,
    confusables_folded: bool,
    ascii_restored: bool,
) -> None:
    from common.telemetry import get_sink

    sink = get_sink()
    if confusables_folded:
        sink.record_nlp_input_repair("confusables_folded")

    if ascii_restored:
        sink.record_nlp_input_repair("ascii_restored")

    if result.particle_repairs:
        counts = _classify_particle_repairs(result.particle_repairs)
        for repair_class, count in counts.items():
            if count:
                sink.record_nlp_input_repair(repair_class, count)

    if result.apostrophe_repairs:
        sink.record_nlp_input_repair("apostrophe_inserted", len(result.apostrophe_repairs))

    if result.dialect_repairs:
        sink.record_nlp_input_repair("dialect_expanded", len(result.dialect_repairs))

    if result.abbreviations_expanded:
        sink.record_nlp_input_repair("abbreviation_expanded", len(result.abbreviations_expanded))

    if result.vocatives_stripped:
        sink.record_nlp_input_repair("vocative_dropped", len(result.vocatives_stripped))

    if result.slurs_stripped:
        sink.record_nlp_input_repair("slur_stripped", len(result.slurs_stripped))

    total_repairs = sum(
        [
            int(confusables_folded),
            len(result.particle_repairs),
            len(result.apostrophe_repairs),
            len(result.dialect_repairs),
            len(result.abbreviations_expanded),
            len(result.vocatives_stripped),
            len(result.slurs_stripped),
        ]
    )
    sink.record_nlp_input_repair_density(total_repairs, token_count)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------
def normalize_input(
    text: str,
    cfg=None,
    *,
    _diacritic_restore: Optional[Callable[[str], str]] = None,
    _typo_correct: "Optional[Callable[[list[str]], tuple[list[str], bool]]]" = None,
    _compound_splitter_lookup: Optional[Callable[[str], Any]] = None,
    _compound_splitter_top_words: Optional[set[str]] = None,
    _compound_splitter_skip_if_pii: Optional[Callable[[str], bool]] = None,
    _assimilation_lookup: Optional[Callable[[str], Any]] = None,
    _assimilation_pairs: Optional[AssimilationRules] = None,
    _consonant_alternation_lookup: Optional[Callable[[str], Any]] = None,
    _consonant_alternation_alternations: Optional[tuple[ConsonantAlternationRule, ...]] = None,
    _clock: Optional[Callable[[], float]] = None,
    _dialect_normalizer: Optional[_DialectNormalizer] = None,
) -> NormalizedInput:
    """Run the 8-step normalization pipeline on *text*.

    Parameters
    ----------
    text:
        Raw user input from ``qa.request.v1.raw_text``.
    cfg:
        Config instance.  Defaults to the module-level singleton.
    _diacritic_restore:
        Optional step-6 hook (str -> str).  When ``None``, step 6 is a
        pass-through.  Will be wired to the §10.3 implementation
        once that bullet lands.
    _typo_correct:
        Optional step-8 hook ``(list[str]) -> (list[str], bool)``.
        Returns ``(corrected_tokens, budget_exhausted)``.  When ``None``,
        step 8 is a pass-through with ``typo_budget_exhausted=False``.
    _consonant_alternation_lookup:
        Optional per-token lexicon lookup hook for consonant alternation
        repair.  When ``None``, step 8a.1 is a no-op.
    _consonant_alternation_alternations:
        Optional cached closed alternation table.  When ``None``, the
        default YAML loader is used.
    _clock:
        Injectable monotonic-time source (``() -> float``, seconds).
        Defaults to ``time.monotonic``.  Override in tests to control
        the deadline without sleeping.
    _dialect_normalizer:
        Injectable :class:`~nlp.dialect_normalize._DialectNormalizer` for
        testing.  Defaults to the module-level singleton.

    Returns
    -------
    NormalizedInput

    Raises
    ------
    InputTooLongError
        When ``len(text)`` (in codepoints) exceeds
        ``cfg.nlp_input_max_codepoints``.
    """
    if cfg is None:
        from common.config import cfg as _cfg
        cfg = _cfg

    _get_time = _clock if _clock is not None else time.monotonic
    _deadline_s = cfg.nlp_normalize_stage_timeout_ms / 1000.0

    steps: list[str] = []
    raw_cp = len(text)

    # -- Step 1: Length cap --------------------------------------------------
    if raw_cp > cfg.nlp_input_max_codepoints:
        raise InputTooLongError(
            f"Input length {raw_cp} codepoints exceeds "
            f"nlp_input_max_codepoints={cfg.nlp_input_max_codepoints}"
        )
    steps.append("length_cap")

    # -- Steps 2+3: NFC + control-char / zero-width / RTL strip -------------
    # canonical_normalize is the Python/Go parity surface; NEVER inline here.
    normalized = canonical_normalize(text)
    steps.append("canonical_normalize")

    # -- Step 3.5: Unicode confusables fold (Phase 10 §10.21.5) ------------
    # Defense-in-depth against homoglyph attacks (Cyrillic/Greek lookalikes).
    # Folds to ASCII-Turkish-extended before lowercase so "Galаtasaray" (Cyrillic а)
    # -> "Galatasaray" -> gazetteer exact-match succeeds.
    pre_confusables = normalized
    normalized = confusables_fold(normalized)
    confusables_folded = normalized != pre_confusables
    steps.append("confusables_fold")
    caseful_normalized = normalized
    # -- Step 4: Turkish-aware lowercase ------------------------------------
    normalized = lowercase_tr(normalized)
    steps.append("lowercase_tr")

    # -- Step 5: Punctuation normalization ----------------------------------
    normalized = normalized.translate(_PUNCT_TABLE)
    normalized = _collapse_unicode_spaces(normalized, cfg.nlp_collapse_unicode_spaces)
    normalized = _MULTI_SPACE_RE.sub(" ", normalized).strip()
    steps.append("punct_normalize")
    query_style = detect_search_operator_syntax_in_text(normalized)

    # -- Steps 6-8 are the bounded "normalize+typo+diacritic" stage. --------
    # Start the stage clock here; deadline is cfg.nlp_normalize_stage_timeout_ms.
    _stage_start = _get_time()

    # -- Step 6: Diacritic restoration (§10.3 hook) -------------------------
    ascii_restored = False
    if _diacritic_restore is not None:
        pre_diacritic = normalized
        normalized = _diacritic_restore(normalized)
        ascii_restored = normalized != pre_diacritic
    steps.append("diacritic_restore")

    # -- Step 6.5: Regional / diaspora dialect normalization (§10.32.4) -----
    normalized, regional_dialect_rewrites, dialect_alternatives = apply_regional_dialect_normalize(normalized)
    steps.append("regional_dialect_normalize")

    # -- Step 6.7: Apostrophe repair for proper nouns (§10.32.5) ------------
    normalized, apostrophe_repairs = repair_apostrophe_proper_noun(
        normalized,
        original_text=caseful_normalized,
    )
    steps.append("apostrophe_proper_noun_repair")

    # -- Step 7: Tokenization -----------------------------------------------
    # Full zemberek suffix-aware rules will be layered in via §10.2 (vendored
    # snapshot in ai/nlp/vendor/zemberek_rules.json).  This basic split is
    # the binding baseline for step ordering.
    raw_tokens: list[str] = [t for t in _TOKEN_SPLIT_RE.split(normalized) if t]
    steps.append("tokenize")

    # -- Step 7.5: No-space compound splitting (§10.28.3) ----------------------
    compound_split_events: list[dict[str, object]] = []
    if _compound_splitter_lookup is not None:
        raw_tokens = split_compound_tokens(
            raw_tokens,
            _compound_splitter_lookup,
            top_words=_compound_splitter_top_words or set(),
            max_splits=cfg.nlp_compound_split_max_splits,
            max_lookups=cfg.nlp_compound_split_max_lookups_per_query,
            skip_if_pii=_compound_splitter_skip_if_pii,
            event_sink=compound_split_events.append,
        )
        steps.append("compound_split")

    # Deadline check after step 6+7: if we are already over budget, skip the
    # expensive steps 8a+8 and return the raw token sequence.  The caller emits
    # nlp.event.v1{kind=normalize_timeout} upon seeing stage_timed_out=True.
    if (_get_time() - _stage_start) * 1000.0 >= _deadline_s * 1000.0:
        steps.append("particle_normalize")
        steps.append("postposition_stack")
        steps.append("dialect_normalize")
        steps.append("typo_correct")
        return NormalizedInput(
            tokens=tuple(raw_tokens),
            steps_run=tuple(steps),
            original_codepoint_count=raw_cp,
            typo_budget_exhausted=False,
            stage_timed_out=True,
            compound_split_events=tuple(compound_split_events),
            regional_dialect_rewrites=(),
            dialect_alternatives=(),
            apostrophe_repairs=(),
            postposition_stack_matches=(),
            postposition_stack_unknowns=(),
        )

    # -- Step 8a: Particle normalization (§10.22.4) -------------------------
    # Detaches mi/mı/mu/mü question particles and annotates de/da/ki.
    # Runs before typo correction so the classifier (§10.4) sees the canonical
    # (always-detached) particle form.  Fixpoint: idempotent on its own output.
    particle_tokens, _particle_repairs = _normalize_particles(raw_tokens)
    steps.append("particle_normalize")

    # -- Step 8a.1: Assimilation normalization (§10.28.2) ----------------------
    if _assimilation_lookup is not None:
        particle_tokens = fold_assimilated_suffixes(
            particle_tokens,
            _assimilation_lookup,
            _assimilation_pairs or load_assimilation_pairs(),
        )
        steps.append("assimilation_fold")

    # -- Step 8a.5: Postposition stack detection (§10.32.3) -------------------
    # Recognises closed 2-postposition stacks and preserves the token stream.
    postposition_stack_matches, postposition_stack_unknowns = detect_postposition_stacks(
        particle_tokens
    )
    steps.append("postposition_stack")

    # -- Step 8a.1: Consonant-alternation tolerance (§10.28.1) ------------
    # Accept a token with softened/unsoftened Turkish consonants if a
    # lexicon lookup proves the alternated form exists and the token is not
    # a canonical exception in the no-rewrite allowlist.
    consonant_alternation_repairs: list[tuple[str, str]] = []
    consonant_alternation_events: list[dict[str, str]] = []
    if _consonant_alternation_lookup is not None:
        alternations = _consonant_alternation_alternations or load_consonant_alternations()
        no_strip_canonicals = load_dialect_no_rewrite_canonicals()
        corrected_tokens: list[str] = []
        for tok in particle_tokens:
            repaired_token, event = tolerate_consonant_alternation(
                tok,
                _consonant_alternation_lookup,
                no_strip_canonicals=no_strip_canonicals,
                alternations=alternations,
            )
            corrected_tokens.append(repaired_token)
            if event is not None:
                consonant_alternation_repairs.append((tok, repaired_token))
                consonant_alternation_events.append(event)
        particle_tokens = corrected_tokens
    steps.append("consonant_alternation")

    # -- Step 8b: Dialect / abbreviation / vocative normalization (§10.22.5) --
    # Applied after particle normalization and before typo correction so the
    # classifier sees canonical spoken-Turkish forms and team entity IDs.
    # Sub-steps (in order):
    #   i.  Multi-token compound rules (negation_q_compound, etc.)
    #   i.  Single-token phonological rules (gerund_r_drop, future_contracted)
    #   i.  Seed-lookup fallback for non-rule forms
    #   ii. Vocative/filler stripping (abi, reis, hocam, …)
    #   iii.Hard abbreviation expansion (GS → galatasaray, etc.)
    _dialect_result = _apply_dialect_normalize(
        particle_tokens, _normalizer=_dialect_normalizer
    )
    dialect_tokens: list[str] = list(_dialect_result.tokens)
    steps.append("dialect_normalize")

    politeness_tokens, politeness_class = strip_politeness_markers(dialect_tokens)
    idiom_tokens, idiom_events = expand_idioms(politeness_tokens, normalized)
    intent_modifier, _modifier_tense = detect_conditional_modifier(idiom_tokens)

    # -- Step 8: Token-level typo correction (§10.3 hook) -------------------
    budget_exhausted = False
    if _typo_correct is not None:
        tokens, budget_exhausted = _typo_correct(idiom_tokens)
    else:
        tokens = idiom_tokens
    steps.append("typo_correct")

    # Final deadline check: step 8 itself may have consumed the remaining
    # budget.  Flag the result so the caller can act accordingly.
    stage_timed_out = (_get_time() - _stage_start) * 1000.0 >= _deadline_s * 1000.0

    result = NormalizedInput(
        tokens=tuple(tokens),
        steps_run=tuple(steps),
        original_codepoint_count=raw_cp,
        typo_budget_exhausted=budget_exhausted,
        stage_timed_out=stage_timed_out,
        compound_split_events=tuple(compound_split_events),
        particle_repairs=_particle_repairs,
        dialect_repairs=_dialect_result.dialect_repairs,
        regional_dialect_rewrites=regional_dialect_rewrites,
        dialect_alternatives=dialect_alternatives,
        apostrophe_repairs=tuple(apostrophe_repairs),
        politeness_class=politeness_class,
        query_style=query_style,
        intent_modifier=intent_modifier,
        idiom_events=tuple(idiom_events),
        vocatives_stripped=_dialect_result.vocatives_stripped,
        abbreviations_expanded=_dialect_result.abbreviations_expanded,
        soft_abbreviations_tagged=_dialect_result.soft_abbreviations_tagged,
        slurs_stripped=_dialect_result.slurs_stripped,
        postposition_stack_matches=tuple(postposition_stack_matches),
        postposition_stack_unknowns=tuple(postposition_stack_unknowns),
        consonant_alternation_repairs=tuple(consonant_alternation_repairs),
        consonant_alternation_events=tuple(consonant_alternation_events),
    )
    _record_nlp_input_repair_metrics(result, len(tokens), confusables_folded, ascii_restored)
    return result
