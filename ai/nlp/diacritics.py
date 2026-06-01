"""Phase 10 §10.3 — Diacritic restoration table loader.

Loads ``ai/nlp/lexicon/_diacritics.tr.yaml`` and provides a ``restore(text)``
callable for step 6 of the §10.1 normalization pipeline.

* No LLM in this path (AGENTS.md Rule 4 + Rule 1).
* Thread-safe: the mapping dict is frozen at construction time.
* Schema-version mismatch raises :exc:`DiacriticsSchemaError` immediately.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import NamedTuple, Optional

import yaml

#: Schema version this loader understands (must match ``_diacritics.tr.yaml``
#: ``_meta.schema_version``).
DIACRITICS_SCHEMA_VERSION: int = 1

#: Default path: ``ai/nlp/lexicon/_diacritics.tr.yaml`` relative to this file.
_DEFAULT_PATH: Path = Path(__file__).parent / "lexicon" / "_diacritics.tr.yaml"

#: Default path: ``ai/nlp/lang_tr/diacritic_risk.tr.yaml`` relative to this file.
_DEFAULT_RISK_PATH: Path = Path(__file__).parent / "lang_tr" / "diacritic_risk.tr.yaml"

# Match sequences of pure ASCII lowercase letters (a-z).
# After step 4 (lowercase_tr) the text is fully lowercase; any character
# outside [a-z] is either punctuation, a digit, or a Turkish diacritic that
# already looks correct — neither needs restoration.
_ASCII_WORD_RE = re.compile(r"([a-z]+)")


def _compute_token_risk(
    ascii_form: str,
    canonical: str,
    risk_weights: dict[str, float],
) -> float:
    """Return cumulative per-character restoration risk for one token.

    Risk keys are encoded as ``"<ascii_char>-><canonical_char>"`` in the
    YAML table (for example ``"i->ı"``).
    """
    total = 0.0
    for ascii_char, canonical_char in zip(ascii_form, canonical):
        if ascii_char == canonical_char:
            continue
        total += float(risk_weights.get(f"{ascii_char}->{canonical_char}", 0.0))
    return total


def _load_risk_weights(path: Path) -> dict[str, float]:
    """Load per-character diacritic risk weights from a YAML file.

    Missing files or malformed payloads intentionally degrade to an empty table
    so restoration keeps legacy behavior instead of failing closed at boot.
    """
    if not path.is_file():
        return {}
    raw_yaml = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw_yaml, dict):
        return {}
    weights_raw = raw_yaml.get("weights", {})
    if not isinstance(weights_raw, dict):
        return {}
    weights: dict[str, float] = {}
    for key, value in weights_raw.items():
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            continue
        if parsed < 0:
            continue
        weights[str(key)] = parsed
    return weights


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


class DiacriticsSchemaError(ValueError):
    """Raised when ``_meta.schema_version`` does not match DIACRITICS_SCHEMA_VERSION."""


class DiacriticsEntry(NamedTuple):
    """A single restoration mapping entry."""

    canonical: str
    """The canonical Turkish form with proper diacritics (e.g. ``fenerbahce``
    is the key; ``fenerbahçe`` is ``canonical``)."""
    frequency: int
    """Corpus frequency of *canonical* (from ``tr_word_freq.txt``).
    Used by the §10.3 ambiguity policy to break ties."""
    is_ambiguous: bool = False
    """``True`` when the top-2 restoration candidates for this ASCII form are
    within ``cfg.nlp_diacritic_tie_break_ratio`` of each other in frequency.
    Ambiguous tokens are **not** restored by :meth:`DiacriticsTable.restore`;
    they are preserved in their original ASCII form and flagged via
    :meth:`DiacriticsTable.restore_with_flags` for the entity resolver to
    disambiguate via context (§10.3 Ambiguity policy)."""


# ---------------------------------------------------------------------------
# DiacriticsTable
# ---------------------------------------------------------------------------


class DiacriticsTable:
    """Immutable diacritics restoration table.

    Loaded from ``ai/nlp/lexicon/_diacritics.tr.yaml``.  The internal mapping
    dict is built once at ``__init__`` time and never mutated; callers may
    hold a reference safely across threads.

    Parameters
    ----------
    data:
        Parsed YAML dict from ``_diacritics.tr.yaml``.
    tie_break_ratio:
        Frequency ratio threshold for the §10.3 ambiguity policy.  When the
        highest-frequency candidate's frequency divided by the second candidate's
        frequency is ≤ this value, the entry is marked as ambiguous
        (``DiacriticsEntry.is_ambiguous=True``) and :meth:`restore` preserves
        the original ASCII token.  Default ``1.5`` (matches
        ``cfg.nlp_diacritic_tie_break_ratio``).  Must be ≥ 1.0.

    Raises
    ------
    DiacriticsSchemaError
        If ``_meta.schema_version`` does not equal ``DIACRITICS_SCHEMA_VERSION``.
    """

    def __init__(
        self,
        data: dict,
        tie_break_ratio: float = 1.5,
        hard_call_min_freq: int = 10000,
        max_risk_per_token: float = 2.5,
        risk_weights: Optional[dict[str, float]] = None,
    ) -> None:
        meta: dict = data.get("_meta", {}) or {}
        sv = meta.get("schema_version")
        if sv != DIACRITICS_SCHEMA_VERSION:
            raise DiacriticsSchemaError(
                f"_diacritics.tr.yaml schema_version={sv!r}; "
                f"expected {DIACRITICS_SCHEMA_VERSION}"
            )
        raw: dict = data.get("mappings", {}) or {}
        safe_risk_weights = risk_weights or {}
        self._map: dict[str, DiacriticsEntry] = {}
        for ascii_form, entry in sorted(raw.items()):
            if not isinstance(entry, dict):
                continue
            candidates_raw = entry.get("candidates")
            if candidates_raw is not None and isinstance(candidates_raw, list):
                # Multi-candidate format: [{canonical, frequency}, ...]
                candidates = sorted(
                    [
                        (str(c.get("canonical", ascii_form)), int(c.get("frequency", 0)))
                        for c in candidates_raw
                        if isinstance(c, dict)
                    ],
                    key=lambda x: -x[1],
                )
                if not candidates:
                    continue
                canonical = candidates[0][0]
                frequency = candidates[0][1]
                # Ambiguity check: top-2 within tie_break_ratio?
                if len(candidates) >= 2:
                    top_freq = candidates[0][1]
                    second_freq = candidates[1][1]
                    if second_freq > 0 and top_freq > 0:
                        is_ambiguous = (top_freq / second_freq) <= tie_break_ratio
                    else:
                        # One or both zeros: unambiguous (clear winner)
                        is_ambiguous = False
                else:
                    is_ambiguous = False
                if is_ambiguous and frequency >= hard_call_min_freq:
                    is_ambiguous = False
            else:
                # Single-canonical format (original schema)
                canonical = str(entry.get("canonical", ascii_form))
                frequency = int(entry.get("frequency", 0))
                is_ambiguous = False
            token_risk = _compute_token_risk(
                ascii_form=str(ascii_form),
                canonical=canonical,
                risk_weights=safe_risk_weights,
            )
            if token_risk > max_risk_per_token:
                is_ambiguous = True
            self._map[str(ascii_form)] = DiacriticsEntry(canonical, frequency, is_ambiguous)
        self._source_sha256: str = str(meta.get("source_sha256", ""))
        self._lexicon_version: str = str(meta.get("lexicon_version", ""))

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def load(
        cls,
        path: Optional[Path] = None,
        tie_break_ratio: float = 1.5,
        hard_call_min_freq: int = 10000,
        max_risk_per_token: float = 2.5,
        risk_path: Optional[Path] = None,
    ) -> "DiacriticsTable":
        """Load the diacritics table from *path*.

        Parameters
        ----------
        path:
            Path to ``_diacritics.tr.yaml``.  Defaults to the built-in
            ``ai/nlp/lexicon/_diacritics.tr.yaml``.
        tie_break_ratio:
            Forwarded to :class:`DiacriticsTable.__init__`.  Defaults to
            ``1.5`` (``cfg.nlp_diacritic_tie_break_ratio``).
        hard_call_min_freq:
            Forwarded to :class:`DiacriticsTable.__init__`.  Defaults to
            ``10000`` (``cfg.nlp_diacritic_hard_call_min_freq``).
        max_risk_per_token:
            Forwarded to :class:`DiacriticsTable.__init__`.  Defaults to
            ``2.5`` (``cfg.nlp_diacritic_max_risk_per_token``).
        risk_path:
            Path to per-character risk table YAML. Defaults to
            ``ai/nlp/lang_tr/diacritic_risk.tr.yaml``.
        """
        target = path if path is not None else _DEFAULT_PATH
        risk_target = risk_path if risk_path is not None else _DEFAULT_RISK_PATH
        raw_yaml = yaml.safe_load(target.read_text(encoding="utf-8"))
        risk_weights = _load_risk_weights(risk_target)
        return cls(
            raw_yaml,
            tie_break_ratio=tie_break_ratio,
            hard_call_min_freq=hard_call_min_freq,
            max_risk_per_token=max_risk_per_token,
            risk_weights=risk_weights,
        )

    # ------------------------------------------------------------------
    # Core API
    # ------------------------------------------------------------------

    def restore(self, text: str) -> str:
        """Replace known ASCIIfied word-tokens in *text* with canonical forms.

        Called as step 6 of the §10.1 pipeline, *before* tokenization (step 7).
        The input is the full normalized string from step 5 (lowercased,
        punctuation-normalized, spaces collapsed).

        Only pure ASCII lowercase sequences (``[a-z]+``) are considered for
        replacement.  Tokens that already contain a Turkish diacritic character
        are passed through unchanged.

        Tokens whose :attr:`DiacriticsEntry.is_ambiguous` flag is ``True``
        are **also** passed through unchanged (§10.3 Ambiguity policy).  Use
        :meth:`restore_with_flags` to obtain the set of preserved-ambiguous
        tokens.

        Parameters
        ----------
        text:
            Lowercased, punct-normalised text (output of §10.1 step 5).

        Returns
        -------
        str
            Text with known unambiguous ASCIIfied word forms swapped for their
            canonical Turkish forms (e.g. ``"fenerbahce mac"`` →
            ``"fenerbahçe maç"``).
        """
        if not self._map:
            return text
        # Split on ASCII-word boundaries, preserving separators.
        # _ASCII_WORD_RE.split() alternates: [sep, word, sep, word, ...]
        parts = _ASCII_WORD_RE.split(text)
        for i, part in enumerate(parts):
            if _ASCII_WORD_RE.fullmatch(part):
                entry = self._map.get(part)
                if entry is not None and not entry.is_ambiguous:
                    parts[i] = entry.canonical
        return "".join(parts)

    def restore_with_flags(self, text: str) -> "tuple[str, frozenset[str]]":
        """Like :meth:`restore` but also returns the set of ambiguous tokens.

        Ambiguous tokens (those with :attr:`DiacriticsEntry.is_ambiguous` set)
        are preserved in their original ASCII form in the returned text, and
        their ASCII forms are collected in the returned frozenset.  The entity
        resolver can use this set to attempt context-based disambiguation (e.g.,
        a co-occurring league name disambiguates ``kor`` → ``kör`` vs ``kor``).

        Parameters
        ----------
        text:
            Lowercased, punct-normalised text (output of §10.1 step 5).

        Returns
        -------
        tuple[str, frozenset[str]]
            ``(restored_text, ambiguous_ascii_forms)`` where
            ``ambiguous_ascii_forms`` is the set of tokens that were preserved
            because of the ambiguity policy.  Empty frozenset when no ambiguous
            tokens were encountered.
        """
        if not self._map:
            return text, frozenset()
        parts = _ASCII_WORD_RE.split(text)
        ambiguous: set[str] = set()
        for i, part in enumerate(parts):
            if _ASCII_WORD_RE.fullmatch(part):
                entry = self._map.get(part)
                if entry is not None:
                    if entry.is_ambiguous:
                        ambiguous.add(part)
                    else:
                        parts[i] = entry.canonical
        return "".join(parts), frozenset(ambiguous)

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def __len__(self) -> int:
        """Number of ASCII-form entries in the table."""
        return len(self._map)

    def __contains__(self, ascii_form: str) -> bool:
        """Return ``True`` if *ascii_form* has a registered restoration."""
        return ascii_form in self._map

    def get(self, ascii_form: str) -> Optional[DiacriticsEntry]:
        """Return the :class:`DiacriticsEntry` for *ascii_form*, or ``None``."""
        return self._map.get(ascii_form)

    @property
    def source_sha256(self) -> str:
        """SHA-256 of the ``tr_word_freq.txt`` file used during generation."""
        return self._source_sha256

    @property
    def lexicon_version(self) -> str:
        """Semantic version of this table (from ``_meta.lexicon_version``)."""
        return self._lexicon_version
