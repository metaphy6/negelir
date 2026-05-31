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

class AmbiguousHit(NamedTuple):
    """Signals that a token matched an alias declared ambiguous in entities_negative.

    alias:
        The normalized trigger token that fired the negative rule.
    candidates:
        Canonical IDs from the ``ambiguous_between`` list in the YAML entry.
        The caller should surface these to the user via a 'Did you mean?' flow
        and emit ``nlp.event.v1{kind=slot_resolution_failed, candidates=[...]}``.  
        Never silently pick one. (§10.5 Ambiguity policy)
    """

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
    """

    spans: list[EntitySpan]
    ambiguous: list[AmbiguousHit]
    pii_dropped: list[EntitySpan] = []  # type: ignore[assignment]


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
    """

    def __init__(
        self,
        store: LexiconStore,
        kind_priority: list[str] | None = None,
        crf: CrfExtractor | None = None,
    ) -> None:
        self._store = store
        self._kind_priority = kind_priority if kind_priority is not None else list(DEFAULT_KIND_PRIORITY)
        self._crf = crf if crf is not None else CrfExtractor()

    def extract(self, tokens: Sequence[str]) -> ExtractionResult:
        """Extract entities from *tokens*.

        Parameters
        ----------
        tokens:
            Already-normalized token list (§10.1 pipeline output).

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
        negative_rules = _load_negative_rules(self._store)

        # 2. Gazetteer pass (collects ambiguous hits via out_ambiguous)
        ambiguous: list[AmbiguousHit] = []
        gazetteer_spans = gazetteer_pass(
            token_list, alias_index, negative_rules, self._kind_priority,
            out_ambiguous=ambiguous,
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
        return ExtractionResult(
            spans=_resolve_conflicts(gazetteer_spans, crf_spans),
            ambiguous=ambiguous,
            pii_dropped=pii_dropped,
        )
