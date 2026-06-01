#!/usr/bin/env python3
"""roadmap_split — extract a long ROADMAP phase into a modular folder.

Pattern lifted from Phase 10 (`docs/design/phase10/sections/` + thin ROADMAP
stub). Given a phase number, this:

1. Locates the `## ... Phase <N> — ...` header in
   `docs/planning/ROADMAP.md` and the matching closing `---` (or the
   start of `## ... Phase <N+1>`).
2. Splits the body on `### <N>.<M>` sub-section headers.
3. Writes one file per sub-section under
   `docs/design/phase<N>/sections/NN-<slug>.md` (verbatim body).
4. Writes a `docs/design/phase<N>/README.md` index.
5. Replaces the original phase body in ROADMAP.md with a slim stub
   carrying only the per-section pointer table + a phase-rollup `[ ]`.

Conventions (binding for the agent, per AGENTS.md §3.4 + §6.1):

- Byte-for-byte preservation of every `[ ]` / `[x]` / `[~]` checkbox.
- No content edits — only relocation.
- Stub layout mirrors the live Phase 10 stub in ROADMAP.md.
- Idempotent: re-running on an already-split phase refuses with a
  clear error (no clobber).

Usage:
    python3 xops/makefile/roadmap_split.py extract --phase 8
    python3 xops/makefile/roadmap_split.py extract --phase 9 --dry-run

Make wrapper: see `make roadmap.split PHASE=8`.

This script is stdlib-only and cross-platform per AGENTS.md §5.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
ROADMAP = REPO_ROOT / "docs" / "planning" / "ROADMAP.md"
DESIGN_ROOT = REPO_ROOT / "docs" / "design"

# Matches lines like "## 🛡️ Phase 7 — Defense Agents (…)".
PHASE_HEADER_RE = re.compile(r"^## .*?Phase (\d+)\b.*$", re.MULTILINE)
# Matches "### 8.1 Ops console (`ops_console` …)" — captures id + title.
SUB_HEADER_RE = re.compile(r"^### (\d+)\.(\d+)\s+(.*)$")


@dataclass(frozen=True)
class PhaseSpan:
    phase: int
    header_line_idx: int          # 0-based line index of the `## Phase N …`
    body_start_line_idx: int      # first content line after the header
    end_line_idx: int             # exclusive — first line *not* in this phase
    header_line: str              # the original header text (for the stub)


@dataclass(frozen=True)
class SubSection:
    phase: int
    sub: int
    title: str                    # everything after "### N.M "
    header_line_idx: int          # 0-based in ROADMAP
    body_lines: List[str]         # includes the header line itself


# ---------------------------------------------------------------------------
# parse


def _find_phase(lines: List[str], phase: int) -> PhaseSpan:
    headers = [
        (i, m) for i, line in enumerate(lines)
        for m in [PHASE_HEADER_RE.match(line)] if m
    ]
    if not headers:
        sys.exit("ROADMAP.md: no '## Phase N …' headers found")

    target_idx: Optional[int] = None
    next_idx: Optional[int] = None
    for pos, (line_idx, m) in enumerate(headers):
        if int(m.group(1)) == phase:
            target_idx = line_idx
            if pos + 1 < len(headers):
                next_idx = headers[pos + 1][0]
            break

    if target_idx is None:
        sys.exit(f"ROADMAP.md: Phase {phase} not found")

    # End = line of next phase header (exclusive), or EOF. Trim trailing `---`
    # blank lines so the stub we re-emit lands cleanly.
    end = next_idx if next_idx is not None else len(lines)
    return PhaseSpan(
        phase=phase,
        header_line_idx=target_idx,
        body_start_line_idx=target_idx + 1,
        end_line_idx=end,
        header_line=lines[target_idx],
    )


def _split_subsections(span: PhaseSpan, lines: List[str]) -> List[SubSection]:
    subs: List[SubSection] = []
    current: Optional[SubSection] = None
    buf: List[str] = []

    def flush(c: Optional[SubSection], body: List[str]) -> None:
        if c is None:
            return
        subs.append(SubSection(
            phase=c.phase, sub=c.sub, title=c.title,
            header_line_idx=c.header_line_idx,
            body_lines=body,
        ))

    for i in range(span.body_start_line_idx, span.end_line_idx):
        line = lines[i]
        m = SUB_HEADER_RE.match(line)
        if m and int(m.group(1)) == span.phase:
            flush(current, buf)
            current = SubSection(
                phase=int(m.group(1)),
                sub=int(m.group(2)),
                title=m.group(3).strip(),
                header_line_idx=i,
                body_lines=[],
            )
            buf = [line]
        else:
            if current is None:
                # Preamble before the first ### — kept for the stub `goal/depends`.
                continue
            buf.append(line)

    flush(current, buf)
    return subs


def _preamble(span: PhaseSpan, subs: List[SubSection], lines: List[str]) -> str:
    """Lines between the phase header and the first sub-section header.

    The Phase 10 stub keeps the Goal/Depends/Anchor block in ROADMAP. We
    re-use that preamble verbatim.
    """
    if not subs:
        end = span.end_line_idx
    else:
        end = subs[0].header_line_idx
    return "".join(lines[span.body_start_line_idx:end]).rstrip() + "\n"


# ---------------------------------------------------------------------------
# emit


_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


def _slug(title: str) -> str:
    # Keep content inside backticks (so "`FeedReader` (R3.4)" → "feedreader"),
    # but drop the backtick chars and any parenthetical clauses.
    base = title.replace("`", " ")
    base = re.sub(r"\([^)]*\)", "", base)
    base = base.lower().strip()
    base = _SLUG_STRIP.sub("-", base).strip("-")
    return base[:80] or "section"


def _section_filename(sub: SubSection) -> str:
    return f"{sub.sub:02d}-{_slug(sub.title)}.md"


def _write_section_files(
    phase: int,
    subs: List[SubSection],
    folder: Path,
    *,
    dry_run: bool,
) -> List[Path]:
    sections_dir = folder / "sections"
    written: List[Path] = []
    if not dry_run:
        sections_dir.mkdir(parents=True, exist_ok=True)
    for sub in subs:
        fname = _section_filename(sub)
        path = sections_dir / fname
        if path.exists() and not dry_run:
            sys.exit(f"refusing to overwrite existing file: {path}")
        # Section file: include a small front-note + the original sub-section.
        body = (
            f"# Phase {phase}.{sub.sub} — {sub.title}\n"
            f"\n"
            f"> Extracted from `docs/planning/ROADMAP.md` §{phase}.{sub.sub}\n"
            f"> as part of the phase-split modularization (mirrors the Phase 10\n"
            f"> pattern at `docs/design/phase10/sections/`). The `[ ]`/`[x]` state\n"
            f"> below is **binding**; the ROADMAP carries only the rollup.\n"
            f"\n"
            + "".join(sub.body_lines).rstrip() + "\n"
        )
        if dry_run:
            print(f"[dry-run] would write {path.relative_to(REPO_ROOT)} ({len(body)} bytes)")
        else:
            path.write_text(body, encoding="utf-8")
        written.append(path)
    return written


def _write_readme(
    span: PhaseSpan,
    subs: List[SubSection],
    folder: Path,
    *,
    dry_run: bool,
) -> Path:
    phase = span.phase
    # Pull the phase title (everything after "— ") from the header.
    title_after_dash = span.header_line.split("—", 1)[-1].strip().rstrip()
    if not title_after_dash:
        title_after_dash = f"Phase {phase}"

    rows = "\n".join(
        f"| §{phase}.{s.sub} | [`sections/{_section_filename(s)}`](sections/{_section_filename(s)}) | {s.title} |"
        for s in subs
    )
    readme = (
        f"# `docs/design/phase{phase}/` — Phase {phase} detail\n"
        f"\n"
        f"> **Why this folder exists.** Phase {phase} ({title_after_dash}) grew\n"
        f"> past ROADMAP's review threshold and was carved out into one file\n"
        f"> per sub-section, mirroring the Phase 10 pattern at\n"
        f"> [`../phase10/sections/`](../phase10/sections/). Content here is **binding**\n"
        f"> — the ROADMAP §{phase} stub is now a pointer that delegates to this\n"
        f"> folder.\n"
        f">\n"
        f"> **Editing rules.**\n"
        f"> 1. Every `[ ]` / `[x]` checkbox flip lives in **this** folder, in\n"
        f">    the per-section file that owns the item. The ROADMAP §{phase}\n"
        f">    stub carries only the phase-rollup checkbox.\n"
        f"> 2. Any non-trivial edit triggers `make version.bump COMPONENT=docs\n"
        f">    LEVEL=minor NOTE=\"...\"` in the same commit (per AGENTS.md §6.1).\n"
        f"> 3. Cross-phase references are authoritative against\n"
        f">    [`../../planning/ROADMAP.md`](../../planning/ROADMAP.md) and the\n"
        f">    matching `docs/design/*.md` anchors. Fix this folder if a claim\n"
        f">    drifts — never silently re-plan a sister phase.\n"
        f"> 4. No rename of these files without explicit human request (URL\n"
        f">    stability); no deletion of a binding `[ ]` item; no weakening\n"
        f">    of a Definition-of-Done gate.\n"
        f"\n"
        f"## Layout\n"
        f"\n"
        f"| Source | File | Theme |\n"
        f"|---|---|---|\n"
        f"{rows}\n"
        f"\n"
        f"## Reading order\n"
        f"\n"
        f"1. The ROADMAP §{phase} stub (`docs/planning/ROADMAP.md`) — goal,\n"
        f"   dependencies, and rollup checkbox.\n"
        f"2. The earliest section file relevant to the area you're modifying.\n"
        f"   Later sub-sections often assume earlier ones are in force; if a\n"
        f"   later file's `Depends on` clause names another sub-section,\n"
        f"   re-read it first.\n"
        f"3. The Definition-of-Done sub-section (the one whose title contains\n"
        f"   *Definition of Done* or matching `DoD` rollup) — this is the\n"
        f"   gate that flips the rollup checkbox in ROADMAP.\n"
    )
    path = folder / "README.md"
    if path.exists() and not dry_run:
        sys.exit(f"refusing to overwrite existing file: {path}")
    if dry_run:
        print(f"[dry-run] would write {path.relative_to(REPO_ROOT)} ({len(readme)} bytes)")
    else:
        folder.mkdir(parents=True, exist_ok=True)
        path.write_text(readme, encoding="utf-8")
    return path


def _build_stub(
    span: PhaseSpan,
    subs: List[SubSection],
    preamble: str,
    folder_name: str,
) -> str:
    phase = span.phase
    rows = "\n".join(
        f"| §{phase}.{s.sub} | [`{_section_filename(s)}`](../design/{folder_name}/sections/{_section_filename(s)}) | {s.title} |"
        for s in subs
    )
    stub = (
        f"{span.header_line.rstrip()}\n"
        f"\n"
        f"{preamble.rstrip()}\n"
        f"\n"
        f"**Detail folder:** [`design/{folder_name}/`](../design/{folder_name}/README.md) — **binding** per-section checkboxes live there.\n"
        f"\n"
        f"> **Why this is a stub.** Phase {phase} grew past ROADMAP's review\n"
        f"> threshold and was carved out into per-sub-section files under\n"
        f"> [`docs/design/{folder_name}/sections/`](../design/{folder_name}/sections/),\n"
        f"> mirroring the Phase 10 pattern. Every `[ ]` checkbox state lives\n"
        f"> in those files; this stub carries only the phase-rollup checkbox\n"
        f"> (last bullet below).\n"
        f"\n"
        f"### {phase}.* Per-section binding files\n"
        f"\n"
        f"| Source | File | Theme |\n"
        f"|---|---|---|\n"
        f"{rows}\n"
        f"\n"
        f"### {phase}.DoD Phase rollup\n"
        f"\n"
        f"- [ ] Every binding `[ ]` in §{phase}.* (across all per-section files\n"
        f"      in [`docs/design/{folder_name}/sections/`](../design/{folder_name}/sections/))\n"
        f"      is `[x]`. Tracker row + `make version.bump COMPONENT=docs`\n"
        f"      recorded for every meaningful per-section edit (per AGENTS.md\n"
        f"      §3 + §6.1).\n"
        f"\n"
        f"---\n"
        f"\n"
    )
    return stub


def _replace_phase_in_roadmap(
    span: PhaseSpan,
    stub: str,
    lines: List[str],
) -> str:
    new = lines[:span.header_line_idx] + [stub] + lines[span.end_line_idx:]
    return "".join(new)


# ---------------------------------------------------------------------------
# commands


def cmd_extract(argv: argparse.Namespace) -> int:
    phase = argv.phase
    folder_name = f"phase{phase}"
    folder = DESIGN_ROOT / folder_name

    text = ROADMAP.read_text(encoding="utf-8")
    # splitlines(keepends=True) preserves trailing newlines per line so we can
    # round-trip the file with zero whitespace drift.
    lines = text.splitlines(keepends=True)

    span = _find_phase(lines, phase)
    subs = _split_subsections(span, lines)
    if not subs:
        sys.exit(f"Phase {phase}: no '### {phase}.M' sub-sections found — nothing to split")

    if folder.exists() and not argv.force:
        sys.exit(
            f"refusing to split: {folder.relative_to(REPO_ROOT)} already exists. "
            "Pass --force to clobber (dangerous — review the diff)."
        )

    preamble = _preamble(span, subs, lines)
    sec_paths = _write_section_files(phase, subs, folder, dry_run=argv.dry_run)
    readme_path = _write_readme(span, subs, folder, dry_run=argv.dry_run)
    stub = _build_stub(span, subs, preamble, folder_name)

    if argv.dry_run:
        print(f"[dry-run] would replace ROADMAP §{phase} body (lines "
              f"{span.header_line_idx + 1}..{span.end_line_idx}) with "
              f"{len(stub)} bytes")
        print(f"[dry-run] {len(subs)} sub-section(s) detected")
        return 0

    new_roadmap = _replace_phase_in_roadmap(span, stub, lines)
    ROADMAP.write_text(new_roadmap, encoding="utf-8")
    print(
        f"split Phase {phase}: {len(sec_paths)} section file(s) + "
        f"README at {folder.relative_to(REPO_ROOT)}; "
        f"ROADMAP §{phase} replaced by {len(stub.splitlines())}-line stub"
    )
    return 0


def cmd_help(_: argparse.Namespace) -> int:
    print(__doc__)
    return 0


COMMANDS = {
    "extract": cmd_extract,
    "help": cmd_help,
}


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="roadmap_split")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_extract = sub.add_parser("extract", help="extract one phase into design folder + stub")
    p_extract.add_argument("--phase", type=int, required=True)
    p_extract.add_argument("--dry-run", action="store_true",
                           help="report what would change; touch nothing")
    p_extract.add_argument("--force", action="store_true",
                           help="overwrite docs/design/phase<N>/ if it already exists")
    p_extract.set_defaults(func=cmd_extract)

    p_help = sub.add_parser("help", help="show docstring")
    p_help.set_defaults(func=cmd_help)

    ns = parser.parse_args(argv)
    return ns.func(ns)


if __name__ == "__main__":
    sys.exit(main())
