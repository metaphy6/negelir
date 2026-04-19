#!/usr/bin/env python3
"""
git_helper.py — auto-commit driver for `make git` and `make git.dry`.

⚠️  AI ASSISTANTS MUST NOT INVOKE THIS SCRIPT.
    `make git` pushes to the remote with the operator's credentials.
    Authorship and intent must be the human's. See AGENTS.md
    §operationalSafety / §5 for the full rationale.

What it does
------------
1. Reads the tracker rows added to docs/tracking/phases.csv since HEAD.
2. Builds a Conventional Commits message from those rows:
       <type>(<scope>): <subject>
       <body>
   - type   : inferred from each row's status + action verb in the note
              (feat / fix / refactor / docs / test / chore / perf / style …).
   - scope  : "phase-N" or "phase-N.M" (joined for multi-row commits).
   - subject: <= 72 chars, taken from the most significant row's note.
   - body   : full notes + divergence lines (only when more than one row,
              or when the subject had to be truncated).
3. `commit`  → stages everything, commits, pushes.
   `dry`     → prints the message and the staged file list, makes no changes.

Cross-platform: Python 3.8+ stdlib only; no shell-isms.
"""

from __future__ import annotations

import csv
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]
TRACKER_REL = Path("docs/tracking/phases.csv")
TRACKER_ABS = REPO_ROOT / TRACKER_REL
SUBJECT_LIMIT = 72

# ── Conventional-Commit inference ─────────────────────────────

# Rules are *ordered*; first match wins per row. Word-boundary regex on the note.
TYPE_RULES: List[Tuple[str, re.Pattern]] = [
    ("fix",      re.compile(r"\b(fix|fixes|fixed|bug|broken|crash|oom|leak|hotfix|patch|repair|recover|restore)\b", re.I)),
    ("test",     re.compile(r"\b(test|tests|pytest|coverage|fixture|adversarial|chaos)\b", re.I)),
    ("docs",     re.compile(r"\b(doc|docs|readme|roadmap|comment|comments|changelog|markdown|guide)\b", re.I)),
    ("perf",     re.compile(r"\b(perf|performance|optimi[sz]e|speed[- ]?up|throughput|latency)\b", re.I)),
    ("refactor", re.compile(r"\b(refactor|rewrite|reorgani[sz]e|reframe|reframing|audit|cleanup|stale|rename|consolidate|extract|migrate|reshape|reword)\b", re.I)),
    ("feat",     re.compile(r"\b(add|adds|added|introduce|implement|implements|implemented|new|create|created|extend|extends|support|supports|wire|wired)\b", re.I)),
    ("build",    re.compile(r"\b(docker|compose|makefile|build|dockerfile|requirements|dependency|deps)\b", re.I)),
    ("ci",       re.compile(r"\b(ci|github actions|workflow|pipeline\b(?!.*pipeline))\b", re.I)),
    ("style",    re.compile(r"\b(style|format|lint|whitespace)\b", re.I)),
]
# Severity for picking primary row in multi-row commits (highest wins).
TYPE_PRIORITY = {
    "fix": 90, "feat": 80, "perf": 70, "refactor": 60, "test": 50,
    "build": 40, "ci": 35, "docs": 30, "style": 20, "chore": 10,
}
# Status fallback when the note has no obvious verb.
STATUS_TO_TYPE = {
    "completed": "feat",
    "in-progress": "chore",
    "adapted": "refactor",
    "diverged": "refactor",
    "blocked": "chore",
    "cancelled": "revert",
}


def _classify(row: Dict[str, str]) -> str:
    """
    Pick a Conventional Commits type for one tracker row.

    Strategy: count how many distinct keywords from each rule fire in the
    note. The type with the most hits wins; ties are broken by TYPE_PRIORITY
    *inverted* (lower priority wins on ties so a `refactor` with the same
    score as `fix` is preferred — most tracker notes are refactors that
    happen to mention the word "fix" in passing). Falls back to the
    status→type map when nothing matches.
    """
    note = (row.get("notes") or "").strip()
    if not note:
        return STATUS_TO_TYPE.get(row.get("status", ""), "chore")

    scores: Dict[str, int] = {}
    for ctype, pat in TYPE_RULES:
        hits = len(pat.findall(note))
        if hits:
            scores[ctype] = hits

    if not scores:
        return STATUS_TO_TYPE.get(row.get("status", ""), "chore")

    # Highest hit count wins; on ties, lower TYPE_PRIORITY wins
    # (so "refactor" beats "fix" when both score 1).
    best = max(scores.items(), key=lambda kv: (kv[1], -TYPE_PRIORITY.get(kv[0], 0)))
    return best[0]


def _scope(row: Dict[str, str]) -> str:
    phase = (row.get("phase") or "").strip()
    sub = (row.get("subphase") or "").strip()
    if not phase:
        return "tracker"
    return f"phase-{phase}.{sub}" if sub else f"phase-{phase}"


def _subject_from_note(note: str, limit: int = SUBJECT_LIMIT) -> str:
    """First sentence-ish chunk, lowercased start, no trailing period, capped."""
    cleaned = re.sub(r"\s+", " ", note).strip()
    # First sentence boundary: '.', ';', or ' — '
    m = re.search(r"[.;](?:\s|$)|\s—\s", cleaned)
    head = cleaned[: m.start()] if m else cleaned
    if not head:
        head = cleaned
    head = head.rstrip(" .;:—-")
    # Lowercase first letter only if the next word isn't an acronym/proper noun.
    if head and head[0].isupper() and (len(head) < 2 or not head[1].isupper()):
        head = head[0].lower() + head[1:]
    if len(head) <= limit:
        return head
    truncated = head[: limit - 1].rstrip()
    # Don't cut mid-word
    if " " in truncated:
        truncated = truncated.rsplit(" ", 1)[0]
    return truncated + "…"


# ── Subprocess helpers ────────────────────────────────────────

def _run(args: List[str], check: bool = True, capture: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(
        args, cwd=REPO_ROOT, check=check,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
        text=True,
    )


def _git_out(args: List[str]) -> str:
    return _run(["git", *args], capture=True).stdout


def _has_uncommitted_changes() -> bool:
    return bool(_git_out(["status", "--porcelain"]).strip())


# ── Tracker diff ──────────────────────────────────────────────

def _read_csv_text(text: str) -> List[Dict[str, str]]:
    if not text.strip():
        return []
    return list(csv.DictReader(text.splitlines()))


def _phases_at_head() -> List[Dict[str, str]]:
    try:
        text = _git_out(["show", f"HEAD:{TRACKER_REL.as_posix()}"])
    except subprocess.CalledProcessError:
        return []
    return _read_csv_text(text)


def _phases_now() -> List[Dict[str, str]]:
    if not TRACKER_ABS.exists():
        return []
    return _read_csv_text(TRACKER_ABS.read_text(encoding="utf-8"))


def _row_key(r: Dict[str, str]) -> Tuple[str, str, str, str]:
    return (
        r.get("timestamp", ""),
        r.get("phase", ""),
        r.get("subphase", ""),
        r.get("status", ""),
    )


def _new_tracker_rows() -> List[Dict[str, str]]:
    head_keys = {_row_key(r) for r in _phases_at_head()}
    return [r for r in _phases_now() if _row_key(r) not in head_keys]


# ── Message building ──────────────────────────────────────────

def _build_message(rows: List[Dict[str, str]]) -> str:
    if not rows:
        raise ValueError("no rows")

    typed: List[Tuple[str, Dict[str, str]]] = [(_classify(r), r) for r in rows]

    if len(typed) == 1:
        ctype, row = typed[0]
        scope = _scope(row)
        note = (row.get("notes") or "").strip()
        subject_body = _subject_from_note(note)
        header = f"{ctype}({scope}): {subject_body}"
        if len(header) <= SUBJECT_LIMIT and "…" not in subject_body:
            return header
        # Long note: keep header trimmed, full note in body.
        short = _subject_from_note(note, limit=SUBJECT_LIMIT - len(f"{ctype}({scope}): "))
        body_lines = [note]
        div = (row.get("divergence") or "").strip()
        if div:
            body_lines.append(f"divergence: {div}")
        return f"{ctype}({scope}): {short}\n\n" + "\n".join(body_lines)

    # Multi-row: pick primary by highest priority, then earliest timestamp.
    typed_sorted = sorted(
        typed,
        key=lambda tr: (-TYPE_PRIORITY.get(tr[0], 0), tr[1].get("timestamp", "")),
    )
    primary_type, primary_row = typed_sorted[0]
    phases = sorted({_scope(r) for _, r in typed})
    scope = ",".join(phases) if len(phases) <= 3 else "tracker"
    subject = _subject_from_note(primary_row.get("notes", ""))
    # Keep header within limit
    header = f"{primary_type}({scope}): {subject}"
    if len(header) > SUBJECT_LIMIT:
        budget = SUBJECT_LIMIT - len(f"{primary_type}({scope}): ")
        subject = _subject_from_note(primary_row.get("notes", ""), limit=max(budget, 20))
        header = f"{primary_type}({scope}): {subject}"

    body_lines = [f"Tracker rollup ({len(typed)} rows):", ""]
    for ctype, row in typed:
        body_lines.append(
            f"- [{ctype}] {_scope(row)} → {row.get('status', '?')}: "
            f"{(row.get('notes') or '').strip()}"
        )
        div = (row.get("divergence") or "").strip()
        if div:
            body_lines.append(f"  divergence: {div}")
    return header + "\n\n" + "\n".join(body_lines)


# ── Commands ──────────────────────────────────────────────────

def _emoji_no_changes() -> int:
    print("✨ Working tree clean — nothing to commit.")
    return 0


def _emoji_no_tracker_rows() -> int:
    print("❌ Uncommitted changes detected, but no new rows in "
          f"{TRACKER_REL.as_posix()} since HEAD.")
    print("   📝 Record what you did first:")
    print('      make track-add PHASE=N STATUS=in-progress NOTE="…"')
    print("   Then re-run: make git")
    return 2


def _preview(message: str, files: Optional[List[str]] = None) -> None:
    print("✍️  Proposed commit message:")
    print("─" * 64)
    print(message)
    print("─" * 64)
    if files is not None:
        print(f"📦 Files that would be staged ({len(files)}):")
        for f in files[:50]:
            print(f"   • {f}")
        if len(files) > 50:
            print(f"   …and {len(files) - 50} more")


def cmd_dry() -> int:
    rows = _new_tracker_rows()
    if not rows:
        if not _has_uncommitted_changes():
            return _emoji_no_changes()
        return _emoji_no_tracker_rows()
    message = _build_message(rows)
    # Show what `git add -A` would touch (untracked + modified + deleted).
    porcelain = _git_out(["status", "--porcelain"]).splitlines()
    files = [line[3:] for line in porcelain if line.strip()]
    print("🔎 Dry run — no changes will be made.")
    _preview(message, files)
    print("✅ Dry run complete. Run `make git` to actually commit & push.")
    return 0


def cmd_commit() -> int:
    if not _has_uncommitted_changes():
        return _emoji_no_changes()

    rows = _new_tracker_rows()
    if not rows:
        return _emoji_no_tracker_rows()

    message = _build_message(rows)
    print("📦 Staging all changes…")
    _run(["git", "add", "-A"])

    # Re-check after staging — guard against gitignored-only diffs.
    staged = _git_out(["diff", "--cached", "--name-only"]).strip()
    if not staged:
        print("ℹ️  Nothing was actually staged (all changes ignored?).")
        return 0

    _preview(message, staged.splitlines())
    print("📝 Committing…")
    _run(["git", "commit", "-m", message])
    print("🚀 Pushing to remote…")
    try:
        _run(["git", "push"])
    except subprocess.CalledProcessError as exc:
        print("⚠️  Commit succeeded but push failed.")
        if exc.stderr:
            print(exc.stderr.rstrip())
        print("   Resolve the remote (pull/rebase) and run `git push` manually.")
        return 1
    print("✅ Done.")
    return 0


# ── Entrypoint ────────────────────────────────────────────────

USAGE = "usage: git_helper.py {commit|dry}"


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    if len(argv) != 1 or argv[0] not in {"commit", "dry"}:
        print(USAGE, file=sys.stderr)
        return 64
    try:
        return cmd_commit() if argv[0] == "commit" else cmd_dry()
    except subprocess.CalledProcessError as exc:
        print(f"❌ git command failed (exit {exc.returncode}).", file=sys.stderr)
        if exc.stderr:
            print(exc.stderr.rstrip(), file=sys.stderr)
        return exc.returncode or 1


if __name__ == "__main__":
    raise SystemExit(main())
