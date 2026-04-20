"""Rule-based change classifier for source_watcher diffs.

Phase 2.8 deliberately starts deterministic: a small ruleset turns
``FieldDiff`` records into one of three severities. The (optional)
LLM summarizer in Phase 8 will only ever *narrate* what the rules
already decided — it never overrides them.

Severity rules (refined 2026-04-20 after the deep-review stress test;
see docs/testing/phase2-source-watcher-stress.md):

- HTML probe paths (``*._status``, ``*._sha256``, ``*._raw_len``) get
  dedicated treatment so the watcher can see what the byte-level diff
  hides:
    * status flipping into 4xx/5xx is always SCHEMA_BREAKING
    * sha256 changing while raw_len is unchanged is SCHEMA_BREAKING
      (the canonical "DOM rewrite at identical byte count" / soft block)
    * raw_len drop ≥ 80% with a 200 status is SCHEMA_BREAKING
      (Cloudflare-style challenge replacing real content)
    * tiny raw_len delta (< 1%) is COSMETIC
- ``type_changed`` where ``str(old) == str(new)`` is SEMANTIC
  (e.g. ``1 → "1"`` — a coercion most scrapers absorb).
- ``removed`` of a list element (path ends with ``[N]``) is SEMANTIC,
  not SCHEMA_BREAKING. Real upstream lists routinely shrink (season
  pruning) without the schema actually breaking.
- ``removed`` of a dict key remains SCHEMA_BREAKING.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from .differ import FieldDiff

COSMETIC = "cosmetic"
SEMANTIC = "semantic"
SCHEMA_BREAKING = "schema_breaking"


@dataclass(frozen=True)
class ClassifiedDiff:
    diff: FieldDiff
    severity: str
    reason: str


# ── path inspection helpers ─────────────────────────────────────


def _last_segment(path: str) -> str:
    """Return the rightmost dotted/bracketed segment of a diff path."""
    return path.rsplit(".", 1)[-1]


def _is_list_element(path: str) -> bool:
    """True when the diff target is a list index, e.g. ``$.matches[3]``."""
    seg = _last_segment(path)
    return seg.endswith("]") and "[" in seg


def _classify_html_probe(d: FieldDiff) -> Optional[ClassifiedDiff]:
    """Special-case the synthetic HTML probe fields.

    ``watch.run`` records HTML seeds as ``{_raw_len, _suffix, _sha256, _status}``
    rather than parsing the DOM. The rules below let those probe fields
    communicate severity faithfully.
    """
    seg = _last_segment(d.path)
    if seg == "_status":
        new_status = d.new if isinstance(d.new, int) else None
        if new_status is not None and not (200 <= new_status < 300):
            return ClassifiedDiff(d, SCHEMA_BREAKING,
                                  f"upstream status {new_status} at {d.path}")
        return None
    if seg == "_sha256":
        # Severity decided by the cross-diff pass (see classify()).
        return None
    if seg == "_raw_len":
        try:
            old = float(d.old)
            new = float(d.new)
        except (TypeError, ValueError):
            return None
        if old <= 0:
            return None
        ratio = abs(new - old) / old
        if ratio < 0.01:
            return ClassifiedDiff(d, COSMETIC,
                                  f"tiny raw_len delta ({ratio:.4f}) at {d.path}")
        if new < old * 0.2:
            return ClassifiedDiff(d, SCHEMA_BREAKING,
                                  f"raw_len collapsed (old={int(old)}, new={int(new)}) at {d.path}")
        return None
    return None


def _classify_one(d: FieldDiff) -> ClassifiedDiff:
    probe = _classify_html_probe(d)
    if probe is not None:
        return probe

    if d.kind == "type_changed":
        if d.old is not None and d.new is not None and str(d.old) == str(d.new):
            return ClassifiedDiff(d, SEMANTIC,
                                  f"lossless type coercion at {d.path}")
        if d.old is None or d.new is None:
            return ClassifiedDiff(d, SEMANTIC,
                                  f"nullability change at {d.path}")
        return ClassifiedDiff(d, SCHEMA_BREAKING,
                              f"type_changed at {d.path}")

    if d.kind == "removed":
        if _is_list_element(d.path):
            return ClassifiedDiff(d, SEMANTIC,
                                  f"list element removed at {d.path}")
        return ClassifiedDiff(d, SCHEMA_BREAKING,
                              f"removed at {d.path}")

    if d.kind == "added":
        return ClassifiedDiff(d, SEMANTIC, f"new field at {d.path}")

    if isinstance(d.old, str) and isinstance(d.new, str):
        if d.old.strip() == d.new.strip():
            return ClassifiedDiff(d, COSMETIC, f"whitespace at {d.path}")
    return ClassifiedDiff(d, SEMANTIC, f"value changed at {d.path}")


def classify(diffs: List[FieldDiff]) -> List[ClassifiedDiff]:
    out = [_classify_one(d) for d in diffs]

    # ── cross-diff escalation #1: bulk list-element removals.
    # >5 removed siblings from the same parent list = mass truncation
    # (S12) and is real data loss, not benign pruning.
    parent_removes: dict[str, int] = {}
    for c in out:
        if c.severity == SEMANTIC and c.diff.kind == "removed" and _is_list_element(c.diff.path):
            parent = c.diff.path.rsplit("[", 1)[0]
            parent_removes[parent] = parent_removes.get(parent, 0) + 1
    bulk_parents = {p for p, n in parent_removes.items() if n > 5}

    # ── cross-diff escalation #2: sha256 changed while raw_len did NOT.
    # Indicates content swap at identical byte count (DOM rewrite, soft
    # block, A/B test serving same-size HTML). Mark every such ``_sha256``
    # diff as SCHEMA_BREAKING.
    raw_len_diffs = {
        d.diff.path.rsplit(".", 1)[0]: d
        for d in out
        if _last_segment(d.diff.path) == "_raw_len"
    }

    out2: List[ClassifiedDiff] = []
    for c in out:
        # Bulk list truncation → SCHEMA_BREAKING.
        if c.diff.kind == "removed" and _is_list_element(c.diff.path):
            parent = c.diff.path.rsplit("[", 1)[0]
            if parent in bulk_parents:
                out2.append(ClassifiedDiff(
                    c.diff, SCHEMA_BREAKING,
                    f"bulk list truncation at {parent} ({parent_removes[parent]} elements removed)",
                ))
                continue

        # _sha256 handling — only escalate genuine value changes, not
        # the first-time appearance of the field (e.g. after a watcher
        # upgrade adds new probe fields to the envelope).
        if _last_segment(c.diff.path) == "_sha256" and c.diff.kind == "changed":
            sibling_parent = c.diff.path.rsplit(".", 1)[0]
            sibling_raw = raw_len_diffs.get(sibling_parent)
            if sibling_raw is None:
                # raw_len unchanged → content swap at same byte count.
                out2.append(ClassifiedDiff(
                    c.diff, SCHEMA_BREAKING,
                    f"sha256 changed with no raw_len change at {c.diff.path}"
                    f" — content swap at identical byte count",
                ))
                continue
            # raw_len did change → inherit cosmetic-vs-not from raw_len.
            out2.append(ClassifiedDiff(
                c.diff, sibling_raw.severity,
                f"sha256 followed raw_len severity ({sibling_raw.severity}) at {c.diff.path}",
            ))
            continue

        out2.append(c)
    return out2


def worst_severity(classified: List[ClassifiedDiff]) -> str:
    """Return the highest severity present (cosmetic < semantic < breaking)."""
    rank = {COSMETIC: 0, SEMANTIC: 1, SCHEMA_BREAKING: 2}
    if not classified:
        return COSMETIC
    return max(classified, key=lambda c: rank[c.severity]).severity
