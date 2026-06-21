"""Deterministic structural differ for HTML / JSON snapshots.

Pure functions, no I/O. Easy to unit-test against tiny fixtures.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Tuple


@dataclass(frozen=True)
class FieldDiff:
    """A single delta between an old and a new captured payload."""
    path: str          # dotted path, e.g. "matches[0].home_score"
    kind: str          # "added" | "removed" | "changed" | "type_changed"
    old: Any = None
    new: Any = None


def diff_json(old: Any, new: Any, *, path: str = "$") -> List[FieldDiff]:
    """Recursive structural diff between two JSON-compatible values."""
    if type(old) is not type(new):
        return [FieldDiff(path=path, kind="type_changed", old=old, new=new)]
    if isinstance(old, dict):
        out: List[FieldDiff] = []
        for key in sorted(set(old) | set(new)):
            sub = f"{path}.{key}"
            if key not in old:
                out.append(FieldDiff(path=sub, kind="added", new=new[key]))
            elif key not in new:
                out.append(FieldDiff(path=sub, kind="removed", old=old[key]))
            else:
                out.extend(diff_json(old[key], new[key], path=sub))
        return out
    if isinstance(old, list):
        out = []
        for idx in range(max(len(old), len(new))):
            sub = f"{path}[{idx}]"
            if idx >= len(old):
                out.append(FieldDiff(path=sub, kind="added", new=new[idx]))
            elif idx >= len(new):
                out.append(FieldDiff(path=sub, kind="removed", old=old[idx]))
            else:
                out.extend(diff_json(old[idx], new[idx], path=sub))
        return out
    if old != new:
        return [FieldDiff(path=path, kind="changed", old=old, new=new)]
    return []


def summarize(diffs: List[FieldDiff]) -> Dict[str, int]:
    counts: Dict[str, int] = {"added": 0, "removed": 0, "changed": 0, "type_changed": 0}
    for d in diffs:
        counts[d.kind] += 1
    return counts
