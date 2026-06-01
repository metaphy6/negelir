"""Phase 10 §10.22.4 — Token-level particle disambiguation (step 8a).

Detaches attached question particles (mi/mı/mu/mü and personal-suffix
compounds) from tokens when vowel-harmony and stem-validity checks pass.
Annotates tokens that contain attached de/da or ki particles by splitting
them into ``[stem, particle]`` and recording the original token in
``repaired_originals``.

**Single-source contract.** All particle string values are loaded from
``ai/nlp/lang_tr/particles.tr.yaml``.  No literal particle strings appear
in this module (AST guard: ``test_nlp_particle_rules_loaded_from_yaml_only``).

**Anti-literalism (§10 NLP contract).** The normalizer implements *rules*:

* mi/mı/mu/mü — vowel-harmony detection: the variant's 2-char base must
  match ``four_way_harmony[last_stem_vowel]``.  Any token whose suffix
  satisfies harmony and leaves a ≥ min_stem_length plausible stem is split.
  No closed list of known verb stems is consulted.
* de/da — 2-way vowel harmony (front → de, back → da) + min stem length
  + no trailing apostrophe.  Lexicon cross-check deferred to §10.5
  integration.
* ki — structural stem-validity only; relative vs. conjunctive ambiguity
  is resolved downstream by §10.4 + §10.5.

**Idempotency guarantee.** ``apply_particle_normalize`` runs a fixpoint
loop until no further splits occur.  After one call the output token
sequence is fully stabilised: a second call produces the identical result.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml

#: Schema version this loader understands.
PARTICLES_SCHEMA_VERSION: int = 1

#: Default YAML path relative to this source file.
_DEFAULT_YAML_PATH: Path = Path(__file__).parent / "lang_tr" / "particles.tr.yaml"


class ParticleSchemaError(ValueError):
    """Raised when the particles YAML carries an unexpected schema_version."""


# ---------------------------------------------------------------------------
# YAML loader
# ---------------------------------------------------------------------------

def load_rules(path: Path = _DEFAULT_YAML_PATH) -> dict:
    """Load and return the raw particles YAML as a plain ``dict``.

    Raises :exc:`ParticleSchemaError` on schema-version mismatch.
    """
    with open(path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    version = int(raw.get("_meta", {}).get("schema_version", 0))
    if version != PARTICLES_SCHEMA_VERSION:
        raise ParticleSchemaError(
            f"particles.tr.yaml schema_version={version!r}, "
            f"expected {PARTICLES_SCHEMA_VERSION!r}"
        )
    return raw


# ---------------------------------------------------------------------------
# Module-level rule cache (loaded once on first use)
# ---------------------------------------------------------------------------

_RULES_CACHE: Optional[dict] = None


def _get_rules() -> dict:
    """Return the cached particle rules, loading from YAML on first call."""
    global _RULES_CACHE
    if _RULES_CACHE is None:
        _RULES_CACHE = load_rules()
    return _RULES_CACHE


# ---------------------------------------------------------------------------
# Structural helpers — no particle literals here
# ---------------------------------------------------------------------------

def _last_vowel(s: str, vowel_set: frozenset) -> Optional[str]:
    """Return the rightmost vowel character in *s*, or ``None`` if absent."""
    for ch in reversed(s):
        if ch in vowel_set:
            return ch
    return None


def _is_valid_stem(stem: str, min_len: int, vowel_set: frozenset) -> bool:
    """Return ``True`` iff *stem* is a plausible Turkish stem post-detach.

    Three structural checks (no lexicon):

    1. ``len(stem) >= min_len`` — rejects trivially short pseudo-stems.
    2. At least one vowel — rejects pure-consonant sequences.
    3. Does not end in U+0027 (straight apostrophe) — a trailing apostrophe
       indicates a proper-noun suffix already written correctly via
       punct_normalize (e.g. ``"galatasaray'"``); further splitting is wrong.
    """
    if len(stem) < min_len:
        return False
    if stem[-1] == "\u0027":  # straight apostrophe — proper-noun sentinel
        return False
    return any(c in vowel_set for c in stem)


# ---------------------------------------------------------------------------
# Single-pass normalizer (internal)
# ---------------------------------------------------------------------------

def _apply_single_pass(
    tokens: list,
    rules: dict,
) -> tuple:
    """Apply one pass of §10.22.4 particle rules to *tokens*.

    Returns ``(new_tokens, changed)`` where *changed* is ``True`` iff at
    least one token was split.
    """
    vowel_sets = rules["vowel_sets"]
    all_vowels: frozenset = frozenset(vowel_sets["all_vowels"])
    front_vowels: frozenset = frozenset(vowel_sets["front"])

    mi_cfg = rules["mi_variants"]
    mi_harmony: dict = mi_cfg["four_way_harmony"]
    # YAML guarantees longest-first ordering; list() preserves it.
    mi_all: list = list(mi_cfg["all_variants"])
    mi_min_stem: int = int(mi_cfg["min_stem_length"])

    de_da_cfg = rules["de_da"]
    front_p: str = de_da_cfg["front_variant"]
    back_p: str = de_da_cfg["back_variant"]
    de_da_min_stem: int = int(de_da_cfg["min_stem_length"])
    # tuple keeps membership test deterministic
    de_da_particles: tuple = (front_p, back_p)

    ki_cfg = rules["ki"]
    ki_p: str = ki_cfg["particle"]
    ki_min_stem: int = int(ki_cfg["min_stem_length"])

    new_tokens: list = []
    changed = False

    for tok in tokens:
        # ── Rule 1: mi/mı/mu/mü question-particle detach ─────────────────────
        mi_matched = False
        for variant in mi_all:
            vlen = len(variant)
            if len(tok) <= vlen:
                continue
            if not tok.endswith(variant):
                continue
            stem = tok[:-vlen]
            if not _is_valid_stem(stem, mi_min_stem, all_vowels):
                continue
            last_v = _last_vowel(stem, all_vowels)
            if last_v is None:
                continue
            # Compound forms share the 2-char base mi/mı/mu/mü.
            harmony_base = variant[:2]
            if mi_harmony.get(last_v) != harmony_base:
                continue
            new_tokens.append(stem)
            new_tokens.append(variant)
            changed = True
            mi_matched = True
            break
        if mi_matched:
            continue

        # ── Rule 2: de/da detach + annotate ──────────────────────────────────
        de_da_matched = False
        if len(tok) > 2:
            suffix_2 = tok[-2:]
            if suffix_2 in de_da_particles:
                stem = tok[:-2]
                if _is_valid_stem(stem, de_da_min_stem, all_vowels):
                    last_v = _last_vowel(stem, all_vowels)
                    if last_v is not None:
                        # 2-way harmony: front vowel → front_p; back → back_p.
                        expected_p = front_p if last_v in front_vowels else back_p
                        if expected_p == suffix_2:
                            new_tokens.append(stem)
                            new_tokens.append(suffix_2)
                            changed = True
                            de_da_matched = True
        if de_da_matched:
            continue

        # ── Rule 3: ki detach + annotate ─────────────────────────────────────
        ki_len = len(ki_p)
        if len(tok) > ki_len and tok.endswith(ki_p):
            stem = tok[:-ki_len]
            if _is_valid_stem(stem, ki_min_stem, all_vowels):
                new_tokens.append(stem)
                new_tokens.append(ki_p)
                changed = True
                continue

        # ── No rule matched — pass through unchanged ──────────────────────────
        new_tokens.append(tok)

    return new_tokens, changed


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def apply_particle_normalize(
    tokens: list,
    rules: dict,
) -> tuple:
    """Apply §10.22.4 particle normalization to *tokens* until stable (fixpoint).

    Runs ``_apply_single_pass`` repeatedly until no further splits occur.
    This guarantees idempotency: a second call on the output always returns
    the identical list.

    Returns ``(new_tokens, repaired_originals)`` where *repaired_originals*
    is a ``frozenset`` of the original token strings that were split at
    least once (across all passes).
    """
    all_repaired: set = set()
    current = list(tokens)
    for _ in range(len(tokens) + 1):  # upper bound: each pass resolves ≥1 token
        new_tokens, changed = _apply_single_pass(current, rules)
        if not changed:
            break
        # Collect originals that were modified in this pass.
        # A token was split if it appears in `current` but is absent (or split)
        # in `new_tokens`.
        new_set = set(new_tokens)
        for tok in current:
            if tok not in new_set:
                all_repaired.add(tok)
        current = new_tokens
    return current, frozenset(all_repaired)


def normalize_particles(
    tokens: list,
    *,
    _rules: Optional[dict] = None,
) -> tuple:
    """Convenience wrapper: apply particle normalization using the cached YAML.

    Parameters
    ----------
    tokens:
        Input token list (post step-7 tokenization in §10.1).
    _rules:
        Optional rules override for testing.  When ``None``, the
        module-level cached rules are used.

    Returns
    -------
    ``(new_tokens, repaired_originals)``
    """
    rules = _rules if _rules is not None else _get_rules()
    return apply_particle_normalize(tokens, rules)
