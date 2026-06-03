"""Phase 10 §10.22.5 — Colloquial / dialect / abbreviation expansion.

Three sub-steps, applied in order during token-stream normalization:

**Step 8b-i: Dialect normalization** (spoken Turkish → standard Turkish)
  Applies phonological rules loaded from
  ``ai/nlp/lang_tr/dialect.tr.yaml``.  Rules are prioritised:

  1. Multi-token compound rules (negation_q_compound, birsey_compound,
     ne_yapiyor_compound, …) — applied on the token list level.
  2. Single-token phonological rules (gerund_r_drop, future_contracted,
     …) — applied per-token.
  3. Seed-lookup fallback — exact-match against ``seed_entries`` for
     forms that do not fit a clean rule.

  **Anti-literalism principle (§10 NLP contract §2.1).** The YAML is
  the *seed corpus + audit trail*.  The code implements *rules*:

  * **Gerund r-drop rule:** any token whose suffix matches the regex
    ``([a-zçğışöüâîû])(yo)$`` has a missing final ``r`` — append it.
    Generalises to all verbs ending in -uyo, -uyo, -iyo, -ıyo, -öyo,
    -üyo without consulting a closed stem list.

  * **Future contraction rule:** any token ending in back-vowel + ``caz``
    or front-vowel + ``cez`` (with optional preceding vowel assimilation)
    is a contracted ``-acağız`` / ``-eceğiz`` suffix.  Expands by
    restoring the ``ğı`` syllable.

  * **Compound rules:** exact pattern on the joined or single-token level
    for negation (dimi), bişey, napıyo.

**Step 8b-ii: Vocative / filler stripping**
  Tokens in ``ai/nlp/lang_tr/vocative_filler.tr.yaml`` are dropped
  pre-classifier.  Tokens flagged ``strip_only_if_not_sole_token``
  are kept when they are the only token in the query.

**Step 8b-iii: Abbreviation expansion** (hard abbreviations only at this step)
  Hard-class abbreviations from ``ai/nlp/lang_tr/abbreviations.tr.yaml``
  are expanded unconditionally.  Soft-class abbreviations are tagged
  but not expanded here; the §10.5 conflict resolver handles them with
  co-token context.

**Single-source contract.** All token strings are loaded from YAML.
No literal team names, vocative words, or colloquial forms appear in
this module (enforced by AST guard in
``test_nlp_dialect_and_entity_dialect_tables_are_disjoint``).

**Idempotency.** Applying ``apply_dialect_normalize`` twice on output
that is already canonical returns the same sequence.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

from nlp.offensive import strip_offensive_slurs

DIALECT_SCHEMA_VERSION: int = 1
ABBREVIATION_SCHEMA_VERSION: int = 1
VOCATIVE_SCHEMA_VERSION: int = 1

_DEFAULT_DIALECT_PATH: Path = (
    Path(__file__).parent / "lang_tr" / "dialect.tr.yaml"
)
_DEFAULT_ABBREV_PATH: Path = (
    Path(__file__).parent / "lang_tr" / "abbreviations.tr.yaml"
)
_DEFAULT_VOCATIVE_PATH: Path = (
    Path(__file__).parent / "lang_tr" / "vocative_filler.tr.yaml"
)
_DEFAULT_ASR_VOCATIVE_PATH: Path = (
    Path(__file__).parent / "lang_tr" / "asr" / "fillers.tr.yaml"
)


class DialectSchemaError(ValueError):
    """Raised when a loaded YAML carries an unexpected schema_version."""


# ---------------------------------------------------------------------------
# YAML loaders
# ---------------------------------------------------------------------------

def _load_yaml(path: Path, schema_key: str, expected_version: int) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    version = int(raw.get("_meta", {}).get("schema_version", 0))
    if version != expected_version:
        raise DialectSchemaError(
            f"{path.name}: expected schema_version={expected_version}, "
            f"got {version}"
        )
    return raw


def load_dialect_rules(
    path: Path = _DEFAULT_DIALECT_PATH,
) -> dict:
    return _load_yaml(path, "dialect", DIALECT_SCHEMA_VERSION)


def load_abbreviations(
    path: Path = _DEFAULT_ABBREV_PATH,
) -> dict:
    return _load_yaml(path, "abbreviations", ABBREVIATION_SCHEMA_VERSION)


def load_vocative_fillers(
    path: Path = _DEFAULT_VOCATIVE_PATH,
) -> dict:
    return _load_yaml(path, "vocative", VOCATIVE_SCHEMA_VERSION)


def load_asr_fillers(
    path: Path = _DEFAULT_ASR_VOCATIVE_PATH,
) -> dict:
    return _load_yaml(path, "vocative", VOCATIVE_SCHEMA_VERSION)


# ---------------------------------------------------------------------------
# Internal: build compiled rule objects from the YAML
# ---------------------------------------------------------------------------

@dataclass
class _MultiRule:
    """Matches a token-list pattern and replaces with output_tokens."""
    rule_id: str
    output_tokens: list[str]
    # One of: single_token_to_multi pattern or two-token pattern.
    single_pattern: Optional[re.Pattern] = None
    two_patterns: Optional[tuple[re.Pattern, re.Pattern]] = None


@dataclass
class _SingleRule:
    """Matches a single token and replaces it (possibly 1→N tokens)."""
    rule_id: str
    pattern: re.Pattern
    replacement: Optional[str]          # None for seed-lookup rules
    output_tokens_override: Optional[list[str]] = None  # for 1→N


@dataclass
class _SeedEntry:
    """Exact-match fallback entry."""
    spoken: str
    canonical: list[str]


@dataclass
class _AbbrevEntry:
    """Compiled abbreviation entry."""
    abbreviation: str
    expansion_id: str
    hard: bool
    requires_co_tokens: frozenset
    aliases: frozenset


# ---------------------------------------------------------------------------
# Internal regex — phonological rules
# (These regexes encode the phonological principles; the YAML witnesses
# are audit fixtures, not the rule itself.)
# ---------------------------------------------------------------------------

# Gerund r-drop: token ends in Turkish-vowel + "yo" (no trailing r).
# Turkish vowels: a e ı i o ö u ü (and their uppercase + circumflex forms
# folded to lowercase before this step).
# The "(yo)$" anchor ensures we only fire when "yo" is truly terminal.
_GERUND_R_DROP_RE = re.compile(
    r"([a-zçğışöüâîûæ])(yo)$",
    re.UNICODE,
)

# Future contracted — back vowel + caz at end: -acaz, -ıcaz → -acağız
# Constraint: the character before "caz" must be a back Turkish vowel
# (a, ı, o, u) OR the literal syllables a/ı before "caz".
_FUTURE_BACK_RE = re.compile(
    r"^([a-zçğışöüâîû]+?)(a|ı)(caz)$",
    re.UNICODE,
)
# Future contracted — front vowel + cez/caz at end: -ecez, -icez, -icaz → -eceğiz
_FUTURE_FRONT_RE = re.compile(
    r"^([a-zçğışöüâîû]+?)(e|i)(cez|caz)$",
    re.UNICODE,
)


def _build_multi_rules(rules_data: list[dict]) -> list[_MultiRule]:
    """Compile multi-token rules from YAML into ``_MultiRule`` objects."""
    compiled: list[_MultiRule] = []
    for rule in rules_data:
        scope = rule.get("scope", "single_token")
        rid = rule["id"]
        if scope == "multi_token":
            pat_single = re.compile(rule["pattern_single"], re.UNICODE)
            pat_two = (
                re.compile(rule["pattern_two"][0], re.UNICODE),
                re.compile(rule["pattern_two"][1], re.UNICODE),
            )
            compiled.append(
                _MultiRule(
                    rule_id=rid,
                    output_tokens=rule["output_tokens"],
                    single_pattern=pat_single,
                    two_patterns=pat_two,
                )
            )
        elif scope == "single_token_to_multi":
            pat = re.compile(rule["pattern"], re.UNICODE | re.IGNORECASE)
            compiled.append(
                _MultiRule(
                    rule_id=rid,
                    output_tokens=rule["output_tokens"],
                    single_pattern=pat,
                )
            )
    return compiled


def _build_seed_map(seed_entries: list[dict]) -> dict[str, list[str]]:
    """Build {spoken → canonical_tokens} from seed_entries."""
    return {
        entry["spoken"]: (
            entry["canonical"]
            if isinstance(entry["canonical"], list)
            else [entry["canonical"]]
        )
        for entry in seed_entries
    }


def _build_abbrev_index(
    abbreviations: list[dict],
) -> tuple[dict[str, _AbbrevEntry], dict[str, _AbbrevEntry]]:
    """Return (hard_map, soft_map) keyed by lowercased abbreviation + aliases."""
    hard: dict[str, _AbbrevEntry] = {}
    soft: dict[str, _AbbrevEntry] = {}
    for entry in abbreviations:
        abbr = entry["abbreviation"]
        is_hard = entry["ambiguity_class"] == "hard"
        compiled = _AbbrevEntry(
            abbreviation=abbr,
            expansion_id=entry["expansion_canonical_id"],
            hard=is_hard,
            requires_co_tokens=frozenset(entry.get("requires_co_token", [])),
            aliases=frozenset(entry.get("aliases", [])),
        )
        target = hard if is_hard else soft
        target[abbr] = compiled
        for alias in entry.get("aliases", []):
            target[alias.replace(".", "").replace(" ", "")] = compiled
    return hard, soft


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DialectResult:
    """Result of the dialect / abbreviation / vocative normalization step.

    Attributes
    ----------
    tokens:
        Token sequence after all three sub-steps.
    dialect_repairs:
        Set of (original_token, rule_id) pairs where a token was
        rewritten by a dialect rule.
    vocatives_stripped:
        Tuple of tokens that were removed in the vocative-strip sub-step.
    abbreviations_expanded:
        Set of (abbrev_token, expansion_id) pairs where a hard abbreviation
        was expanded.
    soft_abbreviations_tagged:
        Set of (abbrev_token, expansion_id, frozenset(requires_co_token))
        for soft abbreviations that were tagged but not yet expanded.
    """
    tokens: tuple[str, ...]
    dialect_repairs: frozenset = field(default_factory=frozenset)
    vocatives_stripped: tuple[str, ...] = field(default_factory=tuple)
    slurs_stripped: tuple[str, ...] = field(default_factory=tuple)
    abbreviations_expanded: frozenset = field(default_factory=frozenset)
    soft_abbreviations_tagged: frozenset = field(default_factory=frozenset)


# ---------------------------------------------------------------------------
# Core normalization steps
# ---------------------------------------------------------------------------

def _apply_multi_rules(
    tokens: list[str],
    multi_rules: list[_MultiRule],
    repairs: list[tuple[str, str]],
) -> list[str]:
    """Apply multi-token compound rules (negation_q_compound etc.)."""
    out: list[str] = []
    i = 0
    while i < len(tokens):
        matched = False
        tok = tokens[i]

        for rule in multi_rules:
            # Case 1: two-token pattern
            if rule.two_patterns and i + 1 < len(tokens):
                nxt = tokens[i + 1]
                p0, p1 = rule.two_patterns
                if p0.match(tok) and p1.match(nxt):
                    repairs.append((tok + " " + nxt, rule.rule_id))
                    out.extend(rule.output_tokens)
                    i += 2
                    matched = True
                    break
            # Case 2: single-token pattern (possibly expanding to multi)
            if rule.single_pattern and rule.single_pattern.match(tok):
                repairs.append((tok, rule.rule_id))
                out.extend(rule.output_tokens)
                i += 1
                matched = True
                break

        if not matched:
            out.append(tok)
            i += 1

    return out


def _apply_single_token_rules(
    tokens: list[str],
    repairs: list[tuple[str, str]],
    seed_map: dict[str, list[str]],
) -> list[str]:
    """Apply phonological rules and seed-lookup per token.

    Rules applied in priority order:
    1. Gerund r-drop (gerund_r_drop)
    2. Future contraction back-vowel (future_contracted)
    3. Future contraction front-vowel (future_contracted)
    4. Seed lookup
    """
    out: list[str] = []
    for tok in tokens:
        # Rule 1: Gerund r-drop — Vyo → Vyor
        m = _GERUND_R_DROP_RE.search(tok)
        if m:
            repaired = tok + "r"
            repairs.append((tok, "gerund_r_drop"))
            out.append(repaired)
            continue

        # Rule 2: Future contraction — back vowel + caz → acağız
        m = _FUTURE_BACK_RE.match(tok)
        if m:
            stem = m.group(1)
            repaired = stem + "acağız"
            repairs.append((tok, "future_contracted"))
            out.append(repaired)
            continue

        # Rule 3: Future contraction — front vowel + cez/caz → eceğiz
        m = _FUTURE_FRONT_RE.match(tok)
        if m:
            stem = m.group(1)
            repaired = stem + "eceğiz"
            repairs.append((tok, "future_contracted"))
            out.append(repaired)
            continue

        # Rule 4: Seed lookup fallback
        if tok in seed_map:
            canonical_tokens = seed_map[tok]
            if canonical_tokens != [tok]:  # skip no-op seed entries
                repairs.append((tok, "seed_lookup"))
                out.extend(canonical_tokens)
                continue

        # No rule matched — pass through
        out.append(tok)

    return out


def _strip_vocatives(
    tokens: list[str],
    vocative_set: frozenset[str],
    sole_token_safe_set: frozenset[str],
    max_strip: int | None = None,
) -> tuple[list[str], list[str]]:
    """Remove vocative/filler tokens; return (kept_tokens, stripped_tokens)."""
    if not tokens:
        return tokens, []
    stripped: list[str] = []
    kept: list[str] = []
    for tok in tokens:
        if tok in vocative_set:
            stripped.append(tok)
        elif tok in sole_token_safe_set:
            # strip_only_if_not_sole_token: keep if it would be the only token
            # We defer this check until after the pass so we know the full kept list.
            stripped.append(tok)  # tentatively strip
        else:
            kept.append(tok)

    if max_strip is not None and len(stripped) > max_strip:
        # Over-cap on ASR filler stripping; preserve the raw token stream
        # rather than risk abusive repeated filler tokens being removed.
        return tokens, []

    # Restore strip_only_if_not_sole_token tokens if kept list would be empty.
    if not kept:
        for tok in stripped:
            if tok in sole_token_safe_set:
                kept.append(tok)
                stripped.remove(tok)

    return kept, stripped


def _expand_abbreviations(
    tokens: list[str],
    hard_map: dict[str, "_AbbrevEntry"],
    soft_map: dict[str, "_AbbrevEntry"],
    expanded_set: list[tuple[str, str]],
    soft_tagged: list[tuple[str, str, frozenset]],
) -> list[str]:
    """Expand hard abbreviations; tag soft ones for downstream resolver."""
    out: list[str] = []
    all_tokens_lower = set(tokens)

    for tok in tokens:
        if tok in hard_map:
            entry = hard_map[tok]
            expanded_set.append((tok, entry.expansion_id))
            out.append(entry.expansion_id)
        elif tok in soft_map:
            entry = soft_map[tok]
            # Check if any required co-token is present in the query
            co_match = entry.requires_co_tokens & all_tokens_lower
            if co_match:
                expanded_set.append((tok, entry.expansion_id))
                out.append(entry.expansion_id)
            else:
                soft_tagged.append((tok, entry.expansion_id, entry.requires_co_tokens))
                out.append(tok)  # keep unexpanded; resolver handles it
        else:
            out.append(tok)

    return out


# ---------------------------------------------------------------------------
# Module-level lazy-loaded shared state
# ---------------------------------------------------------------------------

class _DialectNormalizer:
    """Compiled, reusable normalizer state loaded from YAML once."""

    def __init__(
        self,
        dialect_path: Path = _DEFAULT_DIALECT_PATH,
        abbrev_path: Path = _DEFAULT_ABBREV_PATH,
        vocative_path: Path = _DEFAULT_VOCATIVE_PATH,
        asr_filler_path: Path | None = None,
    ) -> None:
        dialect_data = load_dialect_rules(dialect_path)
        abbrev_data = load_abbreviations(abbrev_path)
        vocative_data = load_vocative_fillers(vocative_path)
        asr_vocative_data: dict[str, list[dict[str, str]]] = {}
        if asr_filler_path is not None:
            asr_vocative_data = load_asr_fillers(asr_filler_path)

        phon_rules: list[dict] = dialect_data.get("phonological_rules", [])
        seed_entries: list[dict] = dialect_data.get("seed_entries", [])

        self._multi_rules: list[_MultiRule] = _build_multi_rules(phon_rules)
        self._seed_map: dict[str, list[str]] = _build_seed_map(seed_entries)

        abbreviations: list[dict] = abbrev_data.get("abbreviations", [])
        self._hard_map, self._soft_map = _build_abbrev_index(abbreviations)

        # Build vocative set
        all_vocative: list[dict] = (
            vocative_data.get("vocative", [])
            + vocative_data.get("fillers", [])
            + asr_vocative_data.get("vocative", [])
            + asr_vocative_data.get("fillers", [])
        )
        sole_token_safe: set[str] = set()
        all_voc: set[str] = set()
        for entry in all_vocative:
            tok = entry["token"]
            all_voc.add(tok)
            if entry.get("strip_only_if_not_sole_token"):
                sole_token_safe.add(tok)
        self._vocative_set: frozenset[str] = frozenset(
            all_voc - sole_token_safe
        )
        self._sole_token_safe_set: frozenset[str] = frozenset(sole_token_safe)

    def normalize(self, tokens: list[str], *, asr_filler_strip_max: int | None = None) -> DialectResult:
        """Apply all three sub-steps and return :class:`DialectResult`."""
        repairs: list[tuple[str, str]] = []
        expanded: list[tuple[str, str]] = []
        soft_tagged: list[tuple[str, str, frozenset]] = []

        # Sub-step i: multi-token compound rules
        out = _apply_multi_rules(list(tokens), self._multi_rules, repairs)

        # Sub-step i (continued): single-token phonological + seed
        out = _apply_single_token_rules(out, repairs, self._seed_map)

        # Sub-step ii: vocative/filler stripping
        out, stripped = _strip_vocatives(
            out,
            self._vocative_set,
            self._sole_token_safe_set,
            max_strip=asr_filler_strip_max,
        )

        # Sub-step ii.b: offensive slur stripping (§10.22.9)
        out, slurs_stripped = strip_offensive_slurs(out)

        # Sub-step iii: abbreviation expansion
        out = _expand_abbreviations(
            out, self._hard_map, self._soft_map, expanded, soft_tagged
        )

        return DialectResult(
            tokens=tuple(out),
            dialect_repairs=frozenset(repairs),
            vocatives_stripped=tuple(stripped),
            abbreviations_expanded=frozenset(expanded),
            soft_abbreviations_tagged=frozenset(
                (a, b, c) for a, b, c in soft_tagged
            ),
            slurs_stripped=tuple(slurs_stripped),
        )


# Module-level singleton (lazy-initialized on first use).
_shared: Optional[_DialectNormalizer] = None
_shared_asr: Optional[_DialectNormalizer] = None


def _get_shared() -> _DialectNormalizer:
    global _shared
    if _shared is None:
        _shared = _DialectNormalizer()
    return _shared


def _get_shared_asr() -> _DialectNormalizer:
    global _shared_asr
    if _shared_asr is None:
        _shared_asr = _DialectNormalizer(asr_filler_path=_DEFAULT_ASR_VOCATIVE_PATH)
    return _shared_asr


def apply_dialect_normalize(
    tokens: list[str],
    *,
    _normalizer: Optional[_DialectNormalizer] = None,
    use_asr_fillers: bool = False,
    asr_filler_strip_max: int | None = None,
) -> DialectResult:
    """Apply dialect normalization (step 8b) to a token list.

    Parameters
    ----------
    tokens:
        Token list produced by step 8a (particle_normalize).
    _normalizer:
        Injectable normalizer for testing.  Defaults to the
        module-level singleton loaded from the standard YAML paths.

    Returns
    -------
    DialectResult
        Normalized token sequence plus repair metadata.
    """
    if _normalizer is not None:
        normalizer = _normalizer
    elif use_asr_fillers:
        normalizer = _get_shared_asr()
    else:
        normalizer = _get_shared()
    return normalizer.normalize(tokens)


# ---------------------------------------------------------------------------
# Composite-abbreviation separator detection (§10.22.5 / §10.6 dispatcher)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MatchSeparatorHit:
    """Returned by :func:`detect_match_separator` when a composite match is found.

    Attributes
    ----------
    team_a_id:
        Canonical entity ID of the first team (left of separator).
    team_b_id:
        Canonical entity ID of the second team (right of separator).
    separator_token:
        The exact separator token that triggered the hit.
    position:
        Index of the separator token in the input list.
    """
    team_a_id: str
    team_b_id: str
    separator_token: str
    position: int


def detect_match_separator(
    tokens: list[str],
    entity_ids: "Optional[set[str]]" = None,
    separator_pattern: str = r"^(-|\u2013|\u2014|vs\.?|x|\u00d7|/)$",
) -> Optional[MatchSeparatorHit]:
    """Detect composite-match patterns in a token list (§10.22.5 / §10.6).

    After abbreviation expansion, scans the token list for patterns of
    the form::

        <team_entity_id>  <separator>  <team_entity_id>

    where the separator token matches ``separator_pattern``.

    The *entity_ids* set is the domain of known team canonical IDs.
    When ``None``, any token is treated as a potential entity.  In
    production this will be populated from the lexicon gazetteer.

    Parameters
    ----------
    tokens:
        Fully-normalized token list (post step 8b).
    entity_ids:
        Optional set of known team entity IDs.  Used to restrict hits to
        tokens that are actually known teams.  ``None`` = permissive (used
        in tests that don't need a full gazetteer).
    separator_pattern:
        Regex pattern for the separator token.
        Default: ``cfg.nlp_match_separator_pattern``.

    Returns
    -------
    :class:`MatchSeparatorHit` or ``None``
        The first composite-match hit found (left-to-right scan), or
        ``None`` if no composite pattern is present.

    Notes
    -----
    Only the first hit is returned.  Multiple separator patterns in a
    single query are resolved by the dispatcher via downstream slot
    logic (§10.6).
    """
    _sep_re = re.compile(separator_pattern, re.UNICODE)

    def _is_team(tok: str) -> bool:
        if entity_ids is None:
            return bool(tok)  # permissive: any non-empty token
        return tok in entity_ids

    for i, tok in enumerate(tokens):
        if _sep_re.match(tok):
            # separator at position i: check left and right
            if i > 0 and i + 1 < len(tokens):
                left = tokens[i - 1]
                right = tokens[i + 1]
                if _is_team(left) and _is_team(right):
                    return MatchSeparatorHit(
                        team_a_id=left,
                        team_b_id=right,
                        separator_token=tok,
                        position=i,
                    )
    return None
