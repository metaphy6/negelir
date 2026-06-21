
"""Phase 10 §10.28.3 — no-space compound splitting for Turkish input.

This module performs a bounded longest-prefix split on a single token when the
original token does not resolve, and when all resulting parts resolve to either
lexicon entries or a small top-frequency word set.
"""
from __future__ import annotations

from typing import Any, Callable, Optional


def _lookup_term(token: str, lookup: Any) -> Optional[str]:
    if lookup is None:
        return None
    candidate = lookup(token)
    if candidate is None:
        return None
    if isinstance(candidate, str):
        return candidate
    if getattr(candidate, 'edit_distance', 0) != 0:
        return None
    return getattr(candidate, 'term', None)


def _recursive_split(
    token: str,
    start: int,
    splits_left: int,
    lookup: Any,
    top_words: set[str],
    budget: int,
) -> tuple[list[str], int] | None:
    if start == len(token):
        return [], budget
    if splits_left <= 0:
        return None

    for end in range(len(token), start, -1):
        piece = token[start:end]
        if not piece:
            continue

        if piece in top_words:
            remaining_budget = budget
        else:
            if budget <= 0:
                continue
            if _lookup_term(piece, lookup) is None:
                continue
            remaining_budget = budget - 1

        if end == len(token):
            return [piece], remaining_budget

        result = _recursive_split(
            token,
            end,
            splits_left - 1,
            lookup,
            top_words,
            remaining_budget,
        )
        if result is not None:
            parts, remaining_budget = result
            return [piece] + parts, remaining_budget

    return None


def split_compound_tokens(
    tokens: list[str],
    lookup: Any,
    top_words: set[str],
    max_splits: int = 4,
    max_lookups: int = 24,
    skip_if_pii: Optional[Callable[[str], bool]] = None,
    event_sink: Optional[Callable[[dict[str, object]], None]] = None,
) -> list[str]:
    if skip_if_pii is None:
        skip_if_pii = lambda token: False

    result: list[str] = []
    applied = False

    for token in tokens:
        if applied or skip_if_pii(token) or _lookup_term(token, lookup) is not None:
            result.append(token)
            continue

        split_result = _recursive_split(token, 0, max_splits, lookup, top_words, max_lookups)
        if split_result is None:
            result.append(token)
            continue

        parts, _ = split_result
        if len(parts) > 1:
            result.extend(parts)
            applied = True
            if event_sink is not None:
                event_sink({
                    "kind": "compound_word_split",
                    "parts_count": len(parts),
                    "applied_strategy": "longest_prefix",
                })
        else:
            result.append(token)

    return result
