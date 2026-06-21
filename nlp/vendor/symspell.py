"""Phase 10 §10.3 — SymSpell-style fuzzy lookup for typo correction.

Vendored in-tree (zero external runtime dependencies).  Implements the
subset of the SymSpell algorithm required by §10.3:

  * Delete-neighbour index built from all indexed terms (aliases from the
    team / player / league / competition lexicons).
  * Per-token edit budget enforced at lookup:
      - len ≤ 2  → 0 (no fuzzy: must hit the abbreviation table exactly)
      - len 3-4  → 1
      - len ≥ 5  → ``max_edit_distance`` (from ``cfg.nlp_typo_max_edit_distance``,
                    default 2; must be 1 or 2)
  * Ties broken by shorter original term (Occam's razor).

Reference: Garbe, Wolf (2012). "SymSpell: 1 million times faster spelling
correction & fuzzy string search through Symmetric Delete spelling correction
algorithm." Version 6.7.

Usage::

    from nlp.vendor.symspell import SymSpellIndex, _Candidate
    from nlp.lexicon_loader import AliasHit

    idx = SymSpellIndex(max_edit_distance=2)
    idx.add_term("galatasaray", AliasHit("gs-001", "team", "1.0.0"))
    idx.add_term("fenerbahce", AliasHit("fb-001", "team", "1.0.0"))

    result = idx.lookup("gaalatasaray")  # edit-distance 1 (one extra 'a')
    assert result is not None
    assert result.term == "galatasaray"
    assert result.edit_distance == 1
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import NamedTuple, Optional

import yaml

from nlp.lexicon_loader import AliasHit

# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


class _Candidate(NamedTuple):
    """Fuzzy-match result returned by :meth:`SymSpellIndex.lookup`."""

    term: str
    """The indexed term that best matches the query token."""
    hit: AliasHit
    """The ``AliasHit`` (canonical_id, kind, lexicon_version) for *term*."""
    edit_distance: float
    """Edit distance between *term* and the query token.

    For ordinary lookups this is true Levenshtein distance. Layout-aware
    lookups may return weighted distances using keyboard confusable costs.
    """


# ---------------------------------------------------------------------------
# Edit-distance helpers
# ---------------------------------------------------------------------------


def _collect_deletes(
    word: str,
    current_dist: int,
    max_dist: int,
    out: set[str],
) -> None:
    """Recursively collect all single-char deletions up to *max_dist*."""
    if current_dist >= max_dist or not word:
        return
    for i in range(len(word)):
        deleted = word[:i] + word[i + 1 :]
        out.add(deleted)
        _collect_deletes(deleted, current_dist + 1, max_dist, out)


def _delete_variants(word: str, max_dist: int) -> set[str]:
    """Return all strings formed by deleting up to *max_dist* characters."""
    variants: set[str] = set()
    _collect_deletes(word, 0, max_dist, variants)
    return variants


_LAYOUT_CONFUSABLES_PATH = Path(__file__).resolve().parents[1] / "lang_tr" / "ime" / "keyboard_confusables.tr.yaml"
_LAYOUT_CONFUSABLES: dict[str, dict[tuple[str, str], float]] | None = None


def _edit_distance(a: str, b: str) -> int:
    """Wagner-Fischer full edit distance (insert / delete / substitute = 1 each)."""
    if a == b:
        return 0
    m, n = len(a), len(b)
    if m == 0:
        return n
    if n == 0:
        return m
    prev = list(range(n + 1))
    for i in range(1, m + 1):
        curr = [i] + [0] * n
        for j in range(1, n + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            curr[j] = min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + cost)
        prev = curr
    return prev[n]


def _normalize_layout_name(layout: str | None) -> str | None:
    if layout is None:
        return None
    layout = layout.strip().lower()
    if layout == "unknown":
        return None
    if layout not in {"q", "f", "swipe"}:
        raise ValueError(
            f"SymSpellIndex.lookup: unsupported layout {layout!r}; must be one of q, f, swipe, unknown, or None"
        )
    return layout


def _load_layout_confusables() -> dict[str, dict[tuple[str, str], float]]:
    global _LAYOUT_CONFUSABLES
    if _LAYOUT_CONFUSABLES is None:
        raw = yaml.safe_load(_LAYOUT_CONFUSABLES_PATH.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise ValueError("keyboard_confusables.tr.yaml must be a mapping")
        parsed: dict[str, dict[tuple[str, str], float]] = {}
        for key, value in raw.items():
            if key == "q_layout":
                layout = "q"
            elif key == "f_layout":
                layout = "f"
            elif key == "swipe_vowel":
                layout = "swipe"
            else:
                raise ValueError(
                    f"keyboard_confusables.tr.yaml contains unexpected section {key!r}"
                )
            if not isinstance(value, dict):
                raise ValueError(f"{key} section must be a mapping")
            table: dict[tuple[str, str], float] = {}
            for source_char, neighbours in value.items():
                if not isinstance(neighbours, dict):
                    raise ValueError(f"{key}.{source_char} must be a mapping")
                for neighbour_char, cost in neighbours.items():
                    if not isinstance(cost, (int, float)):
                        raise ValueError(
                            f"{key}.{source_char}.{neighbour_char} cost must be numeric"
                        )
                    table[(source_char, neighbour_char)] = float(cost)
            parsed[layout] = table
        _LAYOUT_CONFUSABLES = parsed
    return _LAYOUT_CONFUSABLES


def _layout_cost_multiplier(a: str, b: str, layout: str | None) -> float:
    if layout is None:
        return 1.0
    table = _load_layout_confusables().get(layout, {})
    return table.get((a, b), 1.0)


def _weighted_edit_distance(a: str, b: str, layout: str | None = None) -> float:
    """Weighted edit distance using layout-specific substitution costs."""
    if a == b:
        return 0.0
    m, n = len(a), len(b)
    if m == 0:
        return float(n)
    if n == 0:
        return float(m)
    prev = [float(x) for x in range(n + 1)]
    for i in range(1, m + 1):
        curr = [float(i)] + [0.0] * n
        for j in range(1, n + 1):
            if a[i - 1] == b[j - 1]:
                cost = 0.0
            else:
                cost = _layout_cost_multiplier(a[i - 1], b[j - 1], layout)
            curr[j] = min(prev[j] + 1.0, curr[j - 1] + 1.0, prev[j - 1] + cost)
        prev = curr
    return prev[n]


# ---------------------------------------------------------------------------
# SymSpellIndex
# ---------------------------------------------------------------------------


class SymSpellIndex:
    """Delete-neighbour index for typo correction over a set of known terms.

    Build once from the union of team / player / league / competition aliases
    (after §10.1 normalisation); look up single tokens at query time.

    Parameters
    ----------
    max_edit_distance:
        Global cap on edit distance for tokens of length ≥ 5.
        Must be 1 or 2 (larger values cause an exponential blowup in the
        delete-variant table and are out of scope for the §10.3 contract).
        Default 2, mirroring ``cfg.nlp_typo_max_edit_distance``.
    """

    def __init__(self, max_edit_distance: int = 2) -> None:
        if max_edit_distance not in (1, 2):
            raise ValueError(
                f"SymSpellIndex: max_edit_distance must be 1 or 2, "
                f"got {max_edit_distance!r}."
            )
        self._max_edit_distance = max_edit_distance
        # delete-variant → list of (original_term, AliasHit)
        self._index: dict[str, list[tuple[str, AliasHit]]] = defaultdict(list)
        # exact term → AliasHit  (fast path; avoids delete-variant lookup)
        self._exact: dict[str, AliasHit] = {}

    # ------------------------------------------------------------------
    # Building the index
    # ------------------------------------------------------------------

    def add_term(self, term: str, hit: AliasHit) -> None:
        """Index *term* mapped to *hit*.

        Safe to call multiple times for the same *term*; the last write wins
        for the exact-match table.  Call once per alias when loading lexicons.
        """
        self._exact[term] = hit
        for variant in _delete_variants(term, self._max_edit_distance):
            # Avoid duplicates within the same term's variants
            entry = (term, hit)
            bucket = self._index[variant]
            # Only append if this (term, hit) pair is not already present
            if not any(t == term for t, _ in bucket):
                bucket.append(entry)

    @property
    def term_count(self) -> int:
        """Number of unique terms indexed (exact entries)."""
        return len(self._exact)

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    def lookup(self, token: str, layout: str | None = None) -> Optional[_Candidate]:
        """Return the closest indexed term for *token*, or ``None``.

        Per-token edit budget (§10.3 doctrine):
          * ``len(token) ≤ 2`` → 0 (no fuzzy; exact-only)
          * ``len(token) 3-4`` → 1
          * ``len(token) ≥ 5`` → ``self._max_edit_distance``

        When two candidates share the same edit distance, the one with the
        shorter original term is preferred.  Exact matches short-circuit.
        Layout-aware lookups use a keyboard confusable cost matrix when
        *layout* is set; default lookup behaviour is unchanged.
        """
        layout = _normalize_layout_name(layout)

        # Fast path: exact match
        if token in self._exact:
            return _Candidate(token, self._exact[token], 0)

        # Per-token edit budget
        tlen = len(token)
        if tlen <= 2:
            budget = 0
        elif tlen <= 4:
            budget = 1
        else:
            budget = self._max_edit_distance

        if budget == 0:
            return None  # Short tokens: exact only (abbreviation table, not fuzzy)

        # Gather candidate original terms reachable via delete variants
        candidates: dict[str, AliasHit] = {}

        # Case A: delete a char from the query → look up the shorter string in
        # the variant table (covers substitutions that cancel via common prefix)
        # AND in the exact table (covers query-has-extra-insertion vs. term).
        for variant in _delete_variants(token, budget):
            for orig_term, hit in self._index.get(variant, ()):
                if orig_term not in candidates:
                    candidates[orig_term] = hit
            # A delete-variant of the query may be an exact dictionary term.
            # e.g. query="gss", variant="gs", "gs" in _exact → insert in query.
            if variant in self._exact and variant not in candidates:
                candidates[variant] = self._exact[variant]

        # Case B: the token itself is a delete-variant of a dictionary term
        # (term has an insertion relative to the query = deletion from term).
        for orig_term, hit in self._index.get(token, ()):
            if orig_term not in candidates:
                candidates[orig_term] = hit

        if not candidates:
            return None

        # Score via true edit distance; filter to budget
        best: Optional[_Candidate] = None
        for orig_term, hit in sorted(candidates.items()):
            dist = _weighted_edit_distance(token, orig_term, layout=layout)
            if dist > float(budget):
                continue
            if best is None or dist < best.edit_distance or (
                dist == best.edit_distance and len(orig_term) < len(best.term)
            ):
                best = _Candidate(orig_term, hit, int(dist) if dist.is_integer() else dist)

        return best

    # ------------------------------------------------------------------
    # Per-query budget enforcement  (§10.3 Per-query budget)
    # ------------------------------------------------------------------

    def lookup_tokens(
        self,
        tokens: list[str],
        max_lookups: int,
        layout: str | None = None,
    ) -> "tuple[list[Optional[_Candidate]], bool]":
        """Correct a list of *tokens*, capping total fuzzy lookups at *max_lookups*.

        A "fuzzy lookup" is any :meth:`lookup` call whose result has
        ``edit_distance > 0``.  Once *max_lookups* such corrections have been
        consumed, every subsequent token whose lookup would also be fuzzy
        short-circuits to ``None`` (pass-through) and ``budget_exhausted`` is
        set to ``True`` for the remainder of the token list.

        The caller should emit ``nlp.event.v1{kind=did_you_mean_offered}``
        when ``budget_exhausted`` is ``True`` and offer a "Did you mean?"
        reformulation rather than silently applying partial corrections.

        Parameters
        ----------
        tokens:
            Ordered list of normalised tokens from §10.1 step 7.
        max_lookups:
            Maximum number of fuzzy corrections allowed; must be ≥ 1.
            Pass ``cfg.nlp_typo_max_lookups_per_query`` from the call site.
        layout:
            Optional keyboard layout hint. ``q``, ``f``, and ``swipe`` use
            layout-aware typo costs and count as 0.5 fuzzy budget each.

        Returns
        -------
        results:
            Per-token list of :class:`_Candidate` or ``None``.  ``None``
            means no correction (either exact match in index, no in-budget
            match, or budget exhausted for this position).
        budget_exhausted:
            ``True`` when the fuzzy-lookup count reached *max_lookups* before
            all tokens were processed, signalling that the caller must offer
            "Did you mean?" rather than continuing to guess.
        """
        results: list[Optional[_Candidate]] = []
        fuzzy_done: float = 0.0
        budget_exhausted: bool = False
        layout = _normalize_layout_name(layout)
        layout_cost = 0.5 if layout in {"q", "f", "swipe"} else 1.0

        for token in tokens:
            if budget_exhausted:
                results.append(None)
                continue
            candidate = self.lookup(token, layout=layout)
            if candidate is not None and candidate.edit_distance > 0:
                fuzzy_done += layout_cost
                if fuzzy_done > max_lookups:
                    # This correction would exceed the budget; discard it.
                    budget_exhausted = True
                    results.append(None)
                    continue
            results.append(candidate)

        return results, budget_exhausted
