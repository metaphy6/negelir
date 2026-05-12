"""ROADMAP.md parser → phase tree.

Pure stdlib. Parses `docs/planning/ROADMAP.md` into a hierarchical tree of
PhaseNode objects keyed by dotted ids (e.g. `5`, `5.3`, `9.17.11`).

Heading grammar (binding):

    ## 🧹 Phase N — Title          → top-level phase id "N"
    ### N.M Title                  → sub-phase id "N.M"
    #### N.M.P Title               → sub-sub-phase id "N.M.P"
    ##### N.M.P.Q Title (rare)     → tolerated, deeper levels collapse to id

Special phase ids `R1`..`R9` (Pivot v3 renumbering) are also recognised
when the heading reads `## 🧹 Phase R<digit> — Title`.

Checkboxes belonging to a phase are every `- [ ]` / `- [x]` / `- [~]` line
between this heading and the next heading at the same or shallower depth.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]
ROADMAP_PATH = REPO_ROOT / "docs" / "planning" / "ROADMAP.md"

# Phase id grammar accepts both numeric (5, 5.3, 9.17.11) and pivot ids (R1..R9).
# Tolerate any leading emoji / non-word glyphs between the hashes and "Phase".
_PHASE_HEAD_RE = re.compile(
    r"^(?P<hashes>#{2,6})\s+"
    r"(?:[^\w\n]+\s+)?Phase\s+(?P<id>R?\d+(?:\.\d+){0,4})"
    r"(?:\s+[—–\-:]\s*(?P<title>.+?))?\s*$"
)
_SUB_HEAD_RE = re.compile(
    r"^(?P<hashes>#{3,6})\s+"
    r"(?P<id>\d+(?:\.\d+){1,4})"
    r"(?:\s+[—–\-:]?\s*(?P<title>.+?))?\s*$"
)
_CHECKBOX_RE = re.compile(r"^\s*-\s*\[(?P<state>[ xX~])\]\s+(?P<text>.+?)\s*$")


@dataclass
class Checkbox:
    line: int  # 1-based source line
    state: str  # " ", "x", "~"
    text: str


@dataclass
class PhaseNode:
    phase_id: str
    title: str
    depth: int  # heading depth (## = 2, ### = 3, …)
    line_start: int  # 1-based, line of the heading
    line_end: int = 0  # exclusive; filled when the next sibling/parent appears
    parent_id: Optional[str] = None
    children: List[str] = field(default_factory=list)
    checkboxes: List[Checkbox] = field(default_factory=list)

    @property
    def is_root_phase(self) -> bool:
        return "." not in self.phase_id

    @property
    def total_boxes(self) -> int:
        return len(self.checkboxes)

    @property
    def open_boxes(self) -> int:
        return sum(1 for c in self.checkboxes if c.state == " ")

    @property
    def done_boxes(self) -> int:
        return sum(1 for c in self.checkboxes if c.state.lower() == "x")

    @property
    def deferred_boxes(self) -> int:
        return sum(1 for c in self.checkboxes if c.state == "~")

    @property
    def is_complete(self) -> bool:
        return self.total_boxes > 0 and self.open_boxes == 0


@dataclass
class RoadmapTree:
    nodes: Dict[str, PhaseNode]
    order: List[str]  # ids in source order

    def get(self, phase_id: str) -> Optional[PhaseNode]:
        return self.nodes.get(phase_id)

    def descendants(self, phase_id: str) -> List[str]:
        out: List[str] = []
        node = self.nodes.get(phase_id)
        if not node:
            return out
        stack = list(node.children)
        while stack:
            cid = stack.pop(0)
            out.append(cid)
            stack[:0] = self.nodes[cid].children
        return out

    def slice_text(self, phase_id: str, source: str) -> str:
        """Return the verbatim ROADMAP slice for `phase_id` (heading + body)."""
        node = self.nodes.get(phase_id)
        if not node:
            return ""
        lines = source.splitlines(keepends=True)
        start = node.line_start - 1
        end = node.line_end - 1 if node.line_end else len(lines)
        return "".join(lines[start:end])


def _heading_match(line: str) -> Optional[Tuple[int, str, str]]:
    """Return (depth, phase_id, title) if `line` is a recognised heading, else None."""
    # Phase N / Phase R<n> with explicit "Phase" word
    m = _PHASE_HEAD_RE.match(line)
    if m:
        return (
            len(m.group("hashes")),
            m.group("id"),
            (m.group("title") or "").strip(),
        )
    # Bare numeric N.M.P heading (### / #### / …) — never a top-level "## Phase"
    m = _SUB_HEAD_RE.match(line)
    if m and len(m.group("hashes")) >= 3:
        return (
            len(m.group("hashes")),
            m.group("id"),
            (m.group("title") or "").strip(),
        )
    return None


def parse_roadmap(path: Optional[Path] = None) -> Tuple[RoadmapTree, str]:
    """Parse ROADMAP.md into a tree. Returns (tree, raw source)."""
    src_path = Path(path) if path else ROADMAP_PATH
    text = src_path.read_text(encoding="utf-8")
    lines = text.splitlines()

    nodes: Dict[str, PhaseNode] = {}
    order: List[str] = []
    # Stack of (depth, phase_id) for parent-resolution; deeper depth on top.
    stack: List[Tuple[int, str]] = []
    current_id: Optional[str] = None

    for idx, raw in enumerate(lines, start=1):
        head = _heading_match(raw)
        if head:
            depth, phase_id, title = head
            # Close any open node whose end is before this heading.
            while stack and stack[-1][0] >= depth:
                done_depth, done_id = stack.pop()
                done_node = nodes.get(done_id)
                if done_node and not done_node.line_end:
                    done_node.line_end = idx
            parent_id: Optional[str] = stack[-1][1] if stack else None
            # Skip duplicate ids — keep first occurrence (defensive).
            if phase_id in nodes:
                current_id = phase_id
                continue
            node = PhaseNode(
                phase_id=phase_id,
                title=title,
                depth=depth,
                line_start=idx,
                parent_id=parent_id,
            )
            nodes[phase_id] = node
            order.append(phase_id)
            if parent_id and parent_id in nodes:
                nodes[parent_id].children.append(phase_id)
            stack.append((depth, phase_id))
            current_id = phase_id
            continue

        if current_id is None:
            continue

        cb = _CHECKBOX_RE.match(raw)
        if cb:
            nodes[current_id].checkboxes.append(
                Checkbox(line=idx, state=cb.group("state"), text=cb.group("text"))
            )

    # Close any still-open nodes at EOF.
    eof = len(lines) + 1
    for _, pid in stack:
        if not nodes[pid].line_end:
            nodes[pid].line_end = eof
    for node in nodes.values():
        if not node.line_end:
            node.line_end = eof

    return RoadmapTree(nodes=nodes, order=order), text


def iter_phases(tree: RoadmapTree, *, leaves_only: bool = False) -> Iterable[PhaseNode]:
    for pid in tree.order:
        node = tree.nodes[pid]
        if leaves_only and node.children:
            continue
        yield node
