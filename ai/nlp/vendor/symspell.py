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
from typing import NamedTuple, Optional

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
    edit_distance: int
    """True Levenshtein edit distance between *term* and the query token."""


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

    def lookup(self, token: str) -> Optional[_Candidate]:
        """Return the closest indexed term for *token*, or ``None``.

        Per-token edit budget (§10.3 doctrine):
          * ``len(token) ≤ 2`` → 0 (no fuzzy; exact-only)
          * ``len(token) 3-4`` → 1
          * ``len(token) ≥ 5`` → ``self._max_edit_distance``

        When two candidates share the same edit distance, the one with the
        shorter original term is preferred.  Exact matches short-circuit.
        """
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
            dist = _edit_distance(token, orig_term)
            if dist > budget:
                continue
            if best is None or dist < best.edit_distance or (
                dist == best.edit_distance and len(orig_term) < len(best.term)
            ):
                best = _Candidate(orig_term, hit, dist)

        return best

    # ------------------------------------------------------------------
    # Per-query budget enforcement  (§10.3 Per-query budget)
    # ------------------------------------------------------------------

    def lookup_tokens(
        self,
        tokens: list[str],
        max_lookups: int,
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
        fuzzy_done: int = 0
        budget_exhausted: bool = False

        for token in tokens:
            if budget_exhausted:
                results.append(None)
                continue
            candidate = self.lookup(token)
            if candidate is not None and candidate.edit_distance > 0:
                fuzzy_done += 1
                if fuzzy_done > max_lookups:
                    # This correction would exceed the budget; discard it.
                    budget_exhausted = True
                    results.append(None)
                    continue
            results.append(candidate)

        return results, budget_exhausted
