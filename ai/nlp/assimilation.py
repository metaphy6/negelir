"""Phase 10 §10.28.2 — consonant assimilation fold and instrumental variant normalization.

This module provides a small lexicon-driven normalization pass that folds
voiceless locative suffixes (te/ta/ten/tan) back to their voiced canonical
counterparts (de/da/den/dan), and normalizes vowel-final instrumental
variants by mapping short -le/-la to canonical -yle/-yla.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, NamedTuple, Optional

import yaml

from common.text.turkish import lowercase_tr

_DEFAULT_ASSIMILATION_PATH: Path = (
    Path(__file__).parent / 'lang_tr' / 'spelling' / 'assimilation_pairs.tr.yaml'
)
_SCHEMA_VERSION = 1
_VOWELS = set('aeıioöuü')


class AssimilationRules(NamedTuple):
    voiced: tuple[str, ...]
    voiceless: tuple[str, ...]
    instrumental_short: tuple[str, ...]
    instrumental_canonical: tuple[str, ...]


class AssimilationSchemaError(ValueError):
    pass


def _load_yaml(path: Path) -> dict[str, Any]:
    with open(path, 'r', encoding='utf-8') as fh:
        raw = yaml.safe_load(fh)
    version = int(raw.get('_meta', {}).get('schema_version', 0))
    if version != _SCHEMA_VERSION:
        raise AssimilationSchemaError(
            f'{path.name}: expected schema_version={_SCHEMA_VERSION}, got {version}'
        )
    return raw


def load_assimilation_pairs(path: Path = _DEFAULT_ASSIMILATION_PATH) -> AssimilationRules:
    raw = _load_yaml(path)
    entry = raw.get('assimilation_pairs', {})
    voiced = tuple(lowercase_tr(x.strip()) for x in entry.get('voiced', []))
    voiceless = tuple(lowercase_tr(x.strip()) for x in entry.get('voiceless', []))
    instrumental_short = tuple(lowercase_tr(x.strip()) for x in entry.get('instrumental_short', []))
    instrumental_canonical = tuple(lowercase_tr(x.strip()) for x in entry.get('instrumental_canonical', []))

    if len(voiced) != len(voiceless):
        raise ValueError('assimilation_pairs.tr.yaml: voiced and voiceless lists must match length')
    if len(instrumental_short) != len(instrumental_canonical):
        raise ValueError('assimilation_pairs.tr.yaml: instrumental_short and instrumental_canonical lists must match length')
    if len(voiced) != 4:
        raise ValueError('assimilation_pairs.tr.yaml: expected 4 voiced/voiceless locative forms')
    if len(instrumental_short) != 2:
        raise ValueError('assimilation_pairs.tr.yaml: expected 2 instrumental variant forms')

    return AssimilationRules(
        voiced=voiced,
        voiceless=voiceless,
        instrumental_short=instrumental_short,
        instrumental_canonical=instrumental_canonical,
    )


def _lookup_term(token: str, lookup: Any) -> Optional[str]:
    if lookup is None:
        return None
    candidate = lookup(token)
    if candidate is None:
        return None
    if isinstance(candidate, str):
        return candidate
    return getattr(candidate, 'term', None)


def _fold_voiceless_locative(token: str, lookup: Any, rules: AssimilationRules) -> tuple[str, dict[str, str] | None]:
    canonical = _lookup_term(token, lookup)
    if canonical == token:
        return token, None

    for voiceless, voiced in zip(rules.voiceless, rules.voiced):
        if token.endswith(voiceless):
            stem = token[:-len(voiceless)]
            if not stem:
                continue
            folded = stem + voiced
            folded_candidate = _lookup_term(folded, lookup)
            if folded_candidate is not None:
                return folded_candidate, {
                    'kind': 'assimilation_folded',
                    'original': token,
                    'repaired': folded_candidate,
                }

    return token, None


def _fold_instrumental(token: str, lookup: Any, rules: AssimilationRules) -> tuple[str, dict[str, str] | None]:
    canonical = _lookup_term(token, lookup)
    if canonical == token:
        return token, None

    for short, canonical_suffix in zip(rules.instrumental_short, rules.instrumental_canonical):
        if token.endswith(short):
            stem = token[:-len(short)]
            if not stem or stem[-1] not in _VOWELS:
                continue
            folded = stem + canonical_suffix
            folded_candidate = _lookup_term(folded, lookup)
            if folded_candidate is not None:
                return folded_candidate, {
                    'kind': 'assimilation_folded',
                    'original': token,
                    'repaired': folded_candidate,
                }

    return token, None


def fold_assimilated_suffixes(tokens: list[str], lookup: Any, rules: AssimilationRules) -> list[str]:
    folded: list[str] = []
    for token in tokens:
        normalized = lowercase_tr(token)
        repaired, _ = _fold_voiceless_locative(normalized, lookup, rules)
        if repaired == normalized:
            repaired, _ = _fold_instrumental(normalized, lookup, rules)
        folded.append(repaired)
    return folded
