"""Phase 10 §10.5 — Hybrid entity extraction pipeline.

Implements:
  1. Gazetteer pass — longest-non-overlapping match against the lexicons (§10.2).
     Each hit carries (span_start, span_end, kind, canonical_id, confidence=1.0,
     lexicon_version).  Span indices are token-level (0-based inclusive start,
     exclusive end).
  2. CRF pass — small linear-chain CRF over BIO tags for
     {date, time, weekday, ordinal, money_amount, score}.  Vendored via
     python-crfsuite (pycrfsuite); degrades gracefully when the model file is
     absent or the package is not installed.
  3. Conflict resolution:
     (a) Gazetteer overrides CRF on token overlap.
     (b) Within gazetteer, longest-match wins.
     (c) Ties broken by entities_negative.tr.yaml rules then by
         cfg.nlp_entity_kind_priority ordered list.

Usage::

    from nlp.entity import EntityExtractor, EntitySpan
    from nlp.lexicon_loader import LexiconStore
    from pathlib import Path

    store = LexiconStore(Path("ai/nlp/lexicon/"))
    store.maybe_reload()
    extractor = EntityExtractor(store=store, kind_priority=["team", "player", ...])
    tokens = ["galatasaray", "maç", "tahmini"]
    spans = extractor.extract(tokens)
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, NamedTuple, Sequence

# CRF is optional (gracefully absent when pycrfsuite not installed or model missing)
try:
    import pycrfsuite  # type: ignore[import]
    _CRFSUITE_AVAILABLE = True
except ImportError:
    _CRFSUITE_AVAILABLE = False

from nlp.lexicon_loader import AliasHit, LexiconStore
from common.text.turkish import lowercase_tr
from common.security.patterns import detect_pii

# ── Public constants ───────────────────────────────────────────────────────

# Entity kinds produced exclusively by the gazetteer
GAZETTEER_KINDS: frozenset[str] = frozenset(
    {"team", "player", "league", "competition", "market"}
)

# Entity kinds produced exclusively by the CRF
CRF_KINDS: frozenset[str] = frozenset(
    {"date", "time", "weekday", "ordinal", "money_amount", "score"}
)

# Default kind-priority ordering for tie-breaking (§10.5 conflict resolution)
DEFAULT_KIND_PRIORITY: list[str] = [
    "team",
    "player",
    "league",
    "competition",
    "market",
    "date",
    "time",
    "weekday",
    "ordinal",
    "money_amount",
    "score",
]

_ASCII_PASS_PRIMARY_KINDS: frozenset[str] = frozenset({"team", "player", "league"})

_TR_ASCII_FOLD_TABLE: dict[int, str] = str.maketrans({
    "ç": "c",
    "ğ": "g",
    "ı": "i",
    "ö": "o",
    "ş": "s",
    "ü": "u",
    "â": "a",
    "î": "i",
    "û": "u",
})

# Lexicon files that feed the gazetteer (order does NOT matter for correctness)
_GAZETTEER_FILES: tuple[str, ...] = (
    "teams.tr.yaml",
    "players.tr.yaml",
    "leagues.tr.yaml",
    "competitions.tr.yaml",
    "markets.tr.yaml",
)

_NEGATIVE_FILE: str = "entities_negative.tr.yaml"


# ── Public types ───────────────────────────────────────────────────────────

class PhoneticAliasMatch(NamedTuple):
    """Records a resolved phonetic alias from the curated allow-list.

    alias:
        The exact phonetic form matched from ``ai/nlp/lang_tr/phonetic_aliases.tr.yaml``.
    canonical_id:
        The resolved canonical entity ID.
    kind:
        Entity kind inferred from the current lexicon snapshot.
    confused_with:
        Alternative canonical IDs that the phonetic form is commonly confused with.
    """

    alias: str
    canonical_id: str
    kind: str
    confused_with: tuple[str, ...]


class AmbiguousHit(NamedTuple):
    """Represents an alias suppressed by a negative rule with ambiguous candidates."""

    alias: str
    candidates: tuple[str, ...]


class ExtractionResult(NamedTuple):
    """Return type of :meth:`EntityExtractor.extract`.

    spans:
        Non-overlapping entity spans sorted by ``span_start``.
    ambiguous:
        Ambiguous alias hits encountered during the gazetteer pass.  Non-empty
        only when an alias is suppressed by a negative rule that carries an
        ``ambiguous_between`` declaration.  The caller is responsible for
        emitting ``nlp.event.v1{kind=slot_resolution_failed}`` and routing the
        answer to the 'Did you mean?' template.  The entity extractor itself is
        side-effect-free — it never silently picks a canonical. (§10.5)
    pii_dropped:
        CRF spans whose joined token text matched a PII pattern (phone number,
        email address, or credit-card number).  These spans are **excluded**
        from ``spans`` and must NOT be published in ``qa.intent.v1``.
        The caller must emit ``nlp.alert.v1{kind=pii_detected_in_input,
        severity=warn}`` for each entry (operator visibility; user-facing
        answer is unaffected). (§10.5 PII guard at extraction)
    phonetic_alias_matches:
        Phonetic alias matches from ``ai/nlp/lang_tr/phonetic_aliases.tr.yaml``.
        These are curated resolutions; the caller may emit corresponding
        ``nlp.event.v1`` events with ``confused_with`` metadata.
    """

    spans: list[EntitySpan]
    ambiguous: list[AmbiguousHit]
    pii_dropped: list[EntitySpan] = []
    phonetic_alias_matches: tuple[PhoneticAliasMatch, ...] = ()


class EntitySpan(NamedTuple):
    """One extracted entity span.

    span_start:
        0-based inclusive token index (into the token list passed to
        :meth:`EntityExtractor.extract`).
    span_end:
        Exclusive token index (``tokens[span_start:span_end]`` is the span).
    kind:
        Entity kind — one of ``GAZETTEER_KINDS | CRF_KINDS``.
    canonical_id:
        Canonical entity identifier (empty string for CRF-produced spans
        that have no canonical_id, e.g. date expressions).
    confidence:
        1.0 for gazetteer hits; model confidence for CRF spans.
    lexicon_version:
        SemVer of the lexicon file that produced this span (empty string for
        CRF spans).
    source:
        ``"gazetteer"`` or ``"crf"``.
    """

    span_start: int
    span_end: int
    kind: str
    canonical_id: str
    confidence: float
    lexicon_version: str
    source: str


# ── Negative-rule index ────────────────────────────────────────────────────

@dataclass(frozen=True)
class _NegativeRule:
    """Parsed entry from entities_negative.tr.yaml."""

    token: str             # normalized; trigger alias
    requires_cotoken: str  # normalized; must be present for a hit to survive
    # Canonical IDs that this alias is ambiguous between (may be empty).
    # When non-empty and the rule fires, the alias is an AmbiguousHit.
    ambiguous_between: tuple[str, ...] = ()


def _load_negative_rules(store: LexiconStore) -> list[_NegativeRule]:
    """Extract negative disambiguation rules from the store (if loaded)."""
    result = store.get(_NEGATIVE_FILE)
    if result is None:
        return []
    _meta, entries = result
    rules: list[_NegativeRule] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        token = entry.get("token")
        cotoken = entry.get("requires_cotoken")
        if token and cotoken and isinstance(token, str) and isinstance(cotoken, str):
            raw_ambig = entry.get("ambiguous_between")
            ambig: tuple[str, ...] = ()
            if isinstance(raw_ambig, list):
                ambig = tuple(
                    str(c) for c in raw_ambig if isinstance(c, str) and c.strip()
                )
            rules.append(
                _NegativeRule(
                    token=lowercase_tr(token.strip()),
                    requires_cotoken=lowercase_tr(cotoken.strip()),
                    ambiguous_between=ambig,
                )
            )
    return rules


# ── Gazetteer pass ─────────────────────────────────────────────────────────

def _build_combined_alias_index(
    store: LexiconStore,
) -> dict[str, AliasHit]:
    """Merge alias indices from all gazetteer lexicon files into one dict.

    Normalizes all alias keys via lowercase_tr so matching against normalized
    input is consistent (§10.1 pipeline already lowercases tokens).

    In case of collision the first file in ``_GAZETTEER_FILES`` wins (order is
    ``teams → players → leagues → competitions → markets``).
    """
    combined: dict[str, AliasHit] = {}
    for fname in reversed(_GAZETTEER_FILES):  # reversed so first file wins on conflict
        idx = store.get_alias_index(fname)
        if idx is None:
            continue
        for alias, hit in sorted(idx.items()):
            key = lowercase_tr(alias.strip())
            if key:
                combined[key] = hit
    return combined


_PHONETIC_ALIASES_PATH = Path(__file__).resolve().parent / "lang_tr" / "phonetic_aliases.tr.yaml"


@dataclass(frozen=True)
class PhoneticAlias:
    phonetic_form: str
    canonical_id: str
    requires_co_token: bool
    confused_with: tuple[str, ...]
    table_version: str


def _load_phonetic_aliases(path: Path | None = None) -> tuple[PhoneticAlias, ...]:
    """Load the curated phonetic alias allow-list for §10.22.10."""
    path = path or _PHONETIC_ALIASES_PATH
    if not path.exists():
        return ()

    try:
        import yaml

        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, ImportError, yaml.YAMLError):
        return ()
    if not isinstance(data, dict):
        return ()

    meta = data.get("_meta")
    if not isinstance(meta, dict):
        return ()
    if meta.get("schema_version") != 1:
        return ()

    table_version = str(meta.get("table_version", "1.0.0")).strip() or "1.0.0"
    aliases: list[PhoneticAlias] = []
    for item in data.get("aliases", []) if isinstance(data.get("aliases", []), list) else []:
        if not isinstance(item, dict):
            continue
        phonetic_form = item.get("phonetic_form")
        canonical_id = item.get("canonical_id")
        if not isinstance(phonetic_form, str) or not phonetic_form.strip():
            continue
        if not isinstance(canonical_id, str) or not canonical_id.strip():
            continue
        requires_co_token = bool(item.get("requires_co_token", False))
        confused_with = tuple(
            str(v).strip()
            for v in item.get("confused_with", [])
            if isinstance(v, str) and v.strip()
        )
        aliases.append(
            PhoneticAlias(
                phonetic_form=phonetic_form.strip(),
                canonical_id=canonical_id.strip(),
                requires_co_token=requires_co_token,
                confused_with=confused_with,
                table_version=table_version,
            )
        )
    return tuple(aliases)


def _canonical_kind_map(store: LexiconStore) -> dict[str, str]:
    """Return a canonical_id → kind map from the current lexicon snapshot."""
    kind_map: dict[str, str] = {}
    for fname in _GAZETTEER_FILES:
        idx = store.get_alias_index(fname)
        if idx is None:
            continue
        for hit in idx.values():
            if hit.canonical_id and hit.kind in GAZETTEER_KINDS:
                kind_map.setdefault(hit.canonical_id, hit.kind)
    return kind_map


def _inject_phonetic_aliases(
    alias_index: dict[str, AliasHit],
    store: LexiconStore,
    phonetic_aliases: tuple[PhoneticAlias, ...],
) -> dict[str, PhoneticAlias]:
    """Merge curated phonetic aliases into the gazetteer alias index."""
    canonical_kind = _canonical_kind_map(store)
    matches: dict[str, PhoneticAlias] = {}
    for alias in phonetic_aliases:
        kind = canonical_kind.get(alias.canonical_id)
        if kind is None:
            continue
        normalized = " ".join(lowercase_tr(alias.phonetic_form).split())
        if not normalized:
            continue
        if alias.requires_co_token and " " not in normalized:
            continue
        alias_index[normalized] = AliasHit(
            canonical_id=alias.canonical_id,
            kind=kind,
            lexicon_version=alias.table_version,
        )
        matches[normalized] = alias
        folded = _ascii_fold_tr(normalized)
        if folded != normalized:
            matches[folded] = alias
    return matches


def _ascii_fold_tr(text: str) -> str:
    """Fold Turkish diacritics to ASCII for §10.22.1 ASCII-first matching."""
    return lowercase_tr(text).translate(_TR_ASCII_FOLD_TABLE)


def _build_ascii_alias_index(alias_index: dict[str, AliasHit]) -> dict[str, AliasHit]:
    """Build a folded alias index where each alias key is Turkish-ASCII folded."""
    folded: dict[str, AliasHit] = {}
    for alias, hit in alias_index.items():
        key = _ascii_fold_tr(alias)
        if not key:
            continue
        folded.setdefault(key, hit)
    return folded


def _has_ascii_primary_hit(spans: Sequence[EntitySpan]) -> bool:
    """Return True when ASCII pass produced a high-confidence primary hit."""
    for span in spans:
        if span.kind in _ASCII_PASS_PRIMARY_KINDS and span.confidence >= 1.0:
            return True
    return False


def _merge_two_pass_gazetteer(
    ascii_spans: list[EntitySpan],
    restored_spans: list[EntitySpan],
    *,
    kind_priority: list[str],
    restored_margin: float,
) -> list[EntitySpan]:
    """Merge ASCII/restored gazetteer spans with §10.22.1 conflict policy."""
    if not ascii_spans:
        return list(restored_spans)
    if not restored_spans:
        return list(ascii_spans)

    combined: list[tuple[str, EntitySpan]] = [("ascii", s) for s in ascii_spans]
    combined.extend(("restored", s) for s in restored_spans)

    def _priority(kind: str) -> int:
        try:
            return kind_priority.index(kind)
        except ValueError:
            return len(kind_priority)

    def _sort_key(item: tuple[str, EntitySpan]) -> tuple[int, float, int, int, int]:
        source, span = item
        length = span.span_end - span.span_start
        source_rank = 0 if source == "ascii" else 1
        return (-length, -span.confidence, _priority(span.kind), source_rank, span.span_start)

    selected: list[tuple[str, EntitySpan]] = []
    for source, span in sorted(combined, key=_sort_key):
        same_slot_idx: int | None = None
        overlaps = False
        for idx, (_, chosen) in enumerate(selected):
            if chosen.span_start == span.span_start and chosen.span_end == span.span_end:
                same_slot_idx = idx
            if not (span.span_end <= chosen.span_start or span.span_start >= chosen.span_end):
                overlaps = True
                break

        if same_slot_idx is not None:
            chosen_source, chosen_span = selected[same_slot_idx]
            if (
                source == "restored"
                and chosen_source == "ascii"
                and chosen_span.canonical_id != span.canonical_id
                and span.confidence >= chosen_span.confidence + restored_margin
            ):
                selected[same_slot_idx] = (source, span)
            continue

        if overlaps:
            continue
        selected.append((source, span))

    return [span for _, span in sorted(selected, key=lambda item: item[1].span_start)]


def _fold_negative_rules_to_ascii(rules: Sequence[_NegativeRule]) -> list[_NegativeRule]:
    """Fold negative-rule trigger/co-token strings for the ASCII pass."""
    folded: list[_NegativeRule] = []
    for rule in rules:
        folded.append(
            _NegativeRule(
                token=_ascii_fold_tr(rule.token),
                requires_cotoken=_ascii_fold_tr(rule.requires_cotoken),
                ambiguous_between=rule.ambiguous_between,
            )
        )
    return folded


def _dedupe_ambiguous_hits(hits: Sequence[AmbiguousHit]) -> list[AmbiguousHit]:
    """Return stable-order unique AmbiguousHit entries by (alias, candidates)."""
    seen: set[tuple[str, tuple[str, ...]]] = set()
    out: list[AmbiguousHit] = []
    for hit in hits:
        key = (hit.alias, hit.candidates)
        if key in seen:
            continue
        seen.add(key)
        out.append(hit)
    return out


def gazetteer_pass(
    tokens: Sequence[str],
    alias_index: dict[str, AliasHit],
    negative_rules: list[_NegativeRule],
    kind_priority: list[str],
    *,
    out_ambiguous: "list[AmbiguousHit] | None" = None,
) -> list[EntitySpan]:
    """Perform the gazetteer pass on *tokens*.

    Algorithm
    ---------
    1. For every possible token window (i..j), check if the space-joined
       lowercased sequence matches an alias.
    2. Collect all candidate spans.
    3. Sort by span length descending (longest-match preference).
    4. Greedy non-overlapping selection with tie-breaking by kind_priority.
    5. Apply negative rules: suppress a span if its matched alias token is
       in the negative list AND the required co-token is absent from the
       full token list.

    Parameters
    ----------
    tokens:
        Already-normalized token list (§10.1 pipeline output).
    alias_index:
        Combined alias index from :func:`_build_combined_alias_index`.
    negative_rules:
        Parsed negative disambiguation rules.
    kind_priority:
        Ordered list of kinds for tie-breaking; kinds not in the list sort last.

    Returns
    -------
    list[EntitySpan]
        Non-overlapping spans sorted by span_start.
    """
    n = len(tokens)
    if n == 0:
        return []

    # Normalize tokens (already normalized but ensure lowercase_tr applied)
    norm_tokens: list[str] = [lowercase_tr(t) for t in tokens]

    # Build a set of normalized tokens for co-token lookup (negative rules)
    token_set: frozenset[str] = frozenset(norm_tokens)

    # Collect all candidate hits: (start, end, hit)
    candidates: list[tuple[int, int, AliasHit]] = []
    for i in range(n):
        for j in range(i + 1, n + 1):
            window = " ".join(norm_tokens[i:j])
            hit = alias_index.get(window)
            if hit is not None and hit.kind in GAZETTEER_KINDS:
                candidates.append((i, j, hit))

    # Apply negative rules before conflict resolution
    # Build negative lookups: trigger_token → required_cotoken / ambiguous_between
    neg_cotoken_map: dict[str, str] = {
        r.token: r.requires_cotoken for r in negative_rules
    }
    neg_ambiguous_map: dict[str, tuple[str, ...]] = {
        r.token: r.ambiguous_between
        for r in negative_rules
        if r.ambiguous_between
    }

    filtered: list[tuple[int, int, AliasHit]] = []
    for i, j, hit in candidates:
        suppressed = False
        for tok in norm_tokens[i:j]:
            cotoken_required = neg_cotoken_map.get(tok)
            if cotoken_required is not None and cotoken_required not in token_set:
                suppressed = True
                # §10.5 Ambiguity policy: surface candidates when declared
                if out_ambiguous is not None:
                    ambig = neg_ambiguous_map.get(tok)
                    if ambig:
                        out_ambiguous.append(AmbiguousHit(alias=tok, candidates=ambig))
                break
        if not suppressed:
            filtered.append((i, j, hit))
    candidates = filtered

    if not candidates:
        return []

    # Kind priority lookup (kind → index; lower index = higher priority)
    priority_map: dict[str, int] = {k: idx for idx, k in enumerate(kind_priority)}
    _max_priority = len(kind_priority)

    def _kind_rank(kind: str) -> int:
        return priority_map.get(kind, _max_priority)

    # Sort: longest span first, then highest-priority kind, then smallest start
    candidates.sort(
        key=lambda c: (-(c[1] - c[0]), _kind_rank(c[2].kind), c[0])
    )

    # Greedy non-overlapping selection
    occupied: set[int] = set()
    selected: list[EntitySpan] = []

    for start, end, hit in candidates:
        span_tokens = set(range(start, end))
        if span_tokens & occupied:
            continue
        occupied.update(span_tokens)
        selected.append(
            EntitySpan(
                span_start=start,
                span_end=end,
                kind=hit.kind,
                canonical_id=hit.canonical_id,
                confidence=1.0,
                lexicon_version=hit.lexicon_version,
                source="gazetteer",
            )
        )

    selected.sort(key=lambda s: s.span_start)
    return selected


# ── CRF pass ───────────────────────────────────────────────────────────────

def _token_features(tokens: list[str], i: int) -> list[str]:
    """Simple feature set for position *i* in *tokens* (BIO tagger).

    Designed for lightweight Turkish NER (date / time / ordinal / score /
    money_amount / weekday).  No external feature libraries required.
    """
    tok = tokens[i]
    feats: list[str] = [
        f"tok={tok}",
        f"tok.lower={lowercase_tr(tok)}",
        f"len={len(tok)}",
        f"is_digit={tok.isdigit()}",
        f"has_digit={any(c.isdigit() for c in tok)}",
        f"is_upper={tok.isupper()}",
    ]
    # Prefix / suffix features (bounded to avoid high cardinality)
    if len(tok) >= 2:
        feats.append(f"pref2={lowercase_tr(tok[:2])}")
        feats.append(f"suf2={lowercase_tr(tok[-2:])}")
    if len(tok) >= 3:
        feats.append(f"pref3={lowercase_tr(tok[:3])}")
        feats.append(f"suf3={lowercase_tr(tok[-3:])}")

    # Context window (±1 token)
    if i > 0:
        prev = tokens[i - 1]
        feats.append(f"prev={lowercase_tr(prev)}")
    else:
        feats.append("BOS")

    if i < len(tokens) - 1:
        nxt = tokens[i + 1]
        feats.append(f"next={lowercase_tr(nxt)}")
    else:
        feats.append("EOS")

    return feats


def _bio_to_spans(tokens: list[str], labels: list[str]) -> list[EntitySpan]:
    """Convert BIO tag sequence to ``EntitySpan`` objects.

    Labels follow the ``B-<kind>`` / ``I-<kind>`` / ``O`` convention.
    Confidence is set to 1.0 (CRF marginal probability decoding deferred to
    future work; the tagger yields hard labels in this implementation).
    """
    spans: list[EntitySpan] = []
    i = 0
    while i < len(labels):
        label = labels[i]
        if label.startswith("B-"):
            kind = label[2:]
            j = i + 1
            while j < len(labels) and labels[j] == f"I-{kind}":
                j += 1
            spans.append(
                EntitySpan(
                    span_start=i,
                    span_end=j,
                    kind=kind,
                    canonical_id="",
                    confidence=1.0,
                    lexicon_version="",
                    source="crf",
                )
            )
            i = j
        else:
            i += 1
    return spans


class CrfExtractor:
    """Thin wrapper around a loaded pycrfsuite tagger.

    Degrades gracefully when:
      * pycrfsuite is not installed.
      * The model file path is absent or empty.
      * The model file does not exist.
      * SHA256 mismatch (refuses to use a tampered model).

    In all degradation cases :meth:`extract` returns an empty list — the
    gazetteer-only path is the fallback, which is preferable to a crash.
    """

    def __init__(
        self,
        model_path: str = "",
        model_sha256: str = "",
        model_max_size_mb: int = 5,
    ) -> None:
        self._model_path = model_path
        self._expected_sha256 = model_sha256.lower().strip()
        self._model_max_size_mb = max(1, model_max_size_mb)
        self._tagger: Any = None  # pycrfsuite.Tagger | None
        self._load_error: str = ""
        self._available = False
        self._try_load()

    def _try_load(self) -> None:
        """Attempt to load the CRF model; set self._available accordingly."""
        if not _CRFSUITE_AVAILABLE:
            self._load_error = "pycrfsuite not installed"
            return
        if not self._model_path:
            self._load_error = "nlp_entity_crf_model_path not set"
            return
        p = Path(self._model_path)
        if not p.exists():
            self._load_error = f"CRF model not found: {p}"
            return
        size_mb = p.stat().st_size / (1024 * 1024)
        if size_mb > self._model_max_size_mb:
            self._load_error = (
                f"CRF model {p} size={size_mb:.1f} MB exceeds cap "
                f"{self._model_max_size_mb} MB"
            )
            return
        if self._expected_sha256:
            actual = hashlib.sha256(p.read_bytes()).hexdigest()
            if actual != self._expected_sha256:
                self._load_error = (
                    f"CRF model SHA256 mismatch: got {actual}, "
                    f"expected {self._expected_sha256}"
                )
                return
        try:
            tagger = pycrfsuite.Tagger()  # type: ignore[union-attr]
            tagger.open(str(p))
            self._tagger = tagger
            self._available = True
        except Exception as exc:  # noqa: BLE001
            self._load_error = f"pycrfsuite.Tagger.open failed: {exc}"

    @property
    def available(self) -> bool:
        """True if the CRF model is loaded and ready."""
        return self._available

    @property
    def load_error(self) -> str:
        """Human-readable reason why the model is unavailable (empty if ok)."""
        return self._load_error

    def extract(self, tokens: list[str]) -> list[EntitySpan]:
        """Tag *tokens* and return BIO-decoded spans.

        Returns an empty list when the model is unavailable.
        """
        if not self._available or self._tagger is None:
            return []
        features = [_token_features(tokens, i) for i in range(len(tokens))]
        try:
            labels: list[str] = self._tagger.tag(features)
        except Exception:  # noqa: BLE001
            return []
        return _bio_to_spans(tokens, labels)


# ── Conflict resolution ────────────────────────────────────────────────────

def _resolve_conflicts(
    gazetteer_spans: list[EntitySpan],
    crf_spans: list[EntitySpan],
) -> list[EntitySpan]:
    """Merge gazetteer and CRF spans, applying §10.5 conflict resolution rules.

    Rules (binding):
      (a) Gazetteer overrides CRF on any token overlap.
      (b) Within gazetteer, longest-match already won (done in gazetteer_pass).
      (c) CRF spans that do not overlap with any gazetteer span are kept.

    Returns a flat, sorted, non-overlapping list of EntitySpan.
    """
    # Build occupied-token set from gazetteer spans
    gazetteer_occupied: set[int] = set()
    for s in gazetteer_spans:
        gazetteer_occupied.update(range(s.span_start, s.span_end))

    surviving_crf = [
        s for s in crf_spans
        if not (set(range(s.span_start, s.span_end)) & gazetteer_occupied)
    ]

    merged = gazetteer_spans + surviving_crf
    merged.sort(key=lambda s: s.span_start)
    return merged


# ── Public extractor ───────────────────────────────────────────────────────

class EntityExtractor:
    """Hybrid entity extractor (§10.5 Hybrid pipeline).

    Combines the gazetteer pass and the CRF pass, then applies conflict
    resolution.

    Parameters
    ----------
    store:
        A loaded :class:`~nlp.lexicon_loader.LexiconStore`.  The caller is
        responsible for calling ``store.maybe_reload()`` before invoking
        :meth:`extract`.
    kind_priority:
        Ordered list of entity kinds for tie-breaking.  Defaults to
        ``DEFAULT_KIND_PRIORITY``.
    crf:
        Optional :class:`CrfExtractor`.  When omitted, a no-op extractor
        (CRF unavailable) is used — gazetteer-only mode.
    phonetic_aliases_path:
        Optional path to a curated phonetic alias allow-list YAML file.
        Defaults to ``ai/nlp/lang_tr/phonetic_aliases.tr.yaml``.
    """

    def __init__(
        self,
        store: LexiconStore,
        kind_priority: list[str] | None = None,
        crf: CrfExtractor | None = None,
        ascii_vs_restored_margin: float = 0.2,
        phonetic_aliases_path: Path | None = None,
    ) -> None:
        self._store = store
        self._kind_priority = kind_priority if kind_priority is not None else list(DEFAULT_KIND_PRIORITY)
        self._crf = crf if crf is not None else CrfExtractor()
        self._ascii_vs_restored_margin = ascii_vs_restored_margin
        self._phonetic_aliases_path = phonetic_aliases_path
        self._phonetic_aliases = _load_phonetic_aliases(phonetic_aliases_path)

    def extract(
        self,
        tokens: Sequence[str],
        *,
        raw_tokens: Sequence[str] | None = None,
    ) -> ExtractionResult:
        """Extract entities from *tokens*.

        Parameters
        ----------
        tokens:
            Already-normalized token list (§10.1 pipeline output).
        raw_tokens:
            Optional pre-restoration token list for §10.22.1 ASCII-first
            gazetteer pass. When omitted, falls back to *tokens*.

        Returns
        -------
        ExtractionResult
            ``.spans``: non-overlapping entity spans sorted by ``span_start``.
            ``.ambiguous``: ambiguous alias hits that need 'Did you mean?'
            routing by the caller (§10.5 Ambiguity policy).  Empty list when
            no ambiguity was detected.
        """
        token_list = list(tokens)

        # 1. Build gazetteer alias index + negative rules from current store snapshot
        alias_index = _build_combined_alias_index(self._store)
        phonetic_alias_map: dict[str, PhoneticAlias] = {}
        if self._phonetic_aliases:
            phonetic_alias_map = _inject_phonetic_aliases(
                alias_index, self._store, self._phonetic_aliases
            )
        ascii_alias_index = _build_ascii_alias_index(alias_index)
        negative_rules = _load_negative_rules(self._store)
        ascii_negative_rules = _fold_negative_rules_to_ascii(negative_rules)

        # 2. Gazetteer two-pass policy (§10.22.1): ASCII-first, restored fallback.
        raw_token_list = list(raw_tokens) if raw_tokens is not None else token_list
        ascii_tokens = [_ascii_fold_tr(t) for t in raw_token_list]
        ambiguous: list[AmbiguousHit] = []
        ascii_spans = gazetteer_pass(
            ascii_tokens, ascii_alias_index, ascii_negative_rules, self._kind_priority,
            out_ambiguous=ambiguous,
        )
        if _has_ascii_primary_hit(ascii_spans):
            gazetteer_spans = ascii_spans
        else:
            restored_spans = gazetteer_pass(
                token_list, alias_index, negative_rules, self._kind_priority,
                out_ambiguous=ambiguous,
            )
            gazetteer_spans = _merge_two_pass_gazetteer(
                ascii_spans,
                restored_spans,
                kind_priority=self._kind_priority,
                restored_margin=self._ascii_vs_restored_margin,
            )

        # 3. CRF pass — then filter out any span whose text matches a PII
        #    pattern (§10.5 PII guard at extraction).  Dropped spans are
        #    returned in pii_dropped so the caller can emit the alert.
        crf_spans_raw = self._crf.extract(token_list)
        crf_spans: list[EntitySpan] = []
        pii_dropped: list[EntitySpan] = []
        for span in crf_spans_raw:
            span_text = " ".join(token_list[span.span_start:span.span_end])
            if detect_pii(span_text) is not None:
                pii_dropped.append(span)
            else:
                crf_spans.append(span)

        # 4. Conflict resolution
        phonetic_matches: list[PhoneticAliasMatch] = []
        for span in gazetteer_spans:
            window = " ".join(lowercase_tr(t) for t in token_list[span.span_start:span.span_end]).strip()
            alias_match = phonetic_alias_map.get(window)
            if alias_match is None:
                ascii_window = " ".join(_ascii_fold_tr(t) for t in token_list[span.span_start:span.span_end]).strip()
                alias_match = phonetic_alias_map.get(ascii_window)
            if alias_match is not None:
                phonetic_matches.append(
                    PhoneticAliasMatch(
                        alias=alias_match.phonetic_form,
                        canonical_id=alias_match.canonical_id,
                        kind=span.kind,
                        confused_with=alias_match.confused_with,
                    )
                )

        return ExtractionResult(
            spans=_resolve_conflicts(gazetteer_spans, crf_spans),
            ambiguous=_dedupe_ambiguous_hits(ambiguous),
            pii_dropped=pii_dropped,
            phonetic_alias_matches=tuple(phonetic_matches),
        )
