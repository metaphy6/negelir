"""Phase-id include / exclude filter.

A phase id `a.b.c` matches a filter token `t` iff:
  - `t == a.b.c` (exact), OR
  - `a.b.c` starts with `t.` (t is an ancestor).

So `--include 5,8.13` selects phase 5 plus every descendant of 8.13;
`--exclude 9.17.11` removes that single phase (and its descendants).

Resolution order:
  1. Start with all phases (or `--include` set if non-empty).
  2. Subtract anything matching `--exclude`.
  3. Optionally restrict to leaves (no children) — used when emitting work.
"""

from __future__ import annotations

from typing import Iterable, List, Sequence, Set

from .roadmap import RoadmapTree


def _matches(phase_id: str, token: str) -> bool:
    if phase_id == token:
        return True
    return phase_id.startswith(token + ".")


def _expand(tree: RoadmapTree, tokens: Sequence[str]) -> Set[str]:
    """Resolve raw filter tokens to the full set of phase ids they cover."""
    selected: Set[str] = set()
    for tok in tokens:
        tok = tok.strip()
        if not tok:
            continue
        if tok not in tree.nodes:
            # Token may still be a valid prefix — accept only if at least one match.
            matched = [pid for pid in tree.order if _matches(pid, tok)]
            if not matched:
                raise ValueError(f"unknown phase filter token: {tok!r}")
            selected.update(matched)
            continue
        selected.add(tok)
        selected.update(tree.descendants(tok))
    return selected


def select_phase_ids(
    tree: RoadmapTree,
    *,
    include: Sequence[str] = (),
    exclude: Sequence[str] = (),
    leaves_only: bool = True,
    skip_complete: bool = True,
) -> List[str]:
    """Return the ordered list of phase ids to dispatch."""
    universe: Set[str]
    if include:
        universe = _expand(tree, include)
    else:
        universe = set(tree.order)

    if exclude:
        universe -= _expand(tree, exclude)

    selected = [pid for pid in tree.order if pid in universe]
    if leaves_only:
        selected = [pid for pid in selected if not tree.nodes[pid].children]
    if skip_complete:
        selected = [
            pid for pid in selected
            if (tree.nodes[pid].total_boxes == 0 or not tree.nodes[pid].is_complete)
        ]
    return selected


def parse_filter(raw: str) -> List[str]:
    """Split a comma-separated CLI filter into tokens."""
    if not raw:
        return []
    return [t for t in (s.strip() for s in raw.split(",")) if t]


__all__ = ["select_phase_ids", "parse_filter"]
