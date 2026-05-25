"""CI resume cursor — persist orchestrator progress across GitHub Actions runs.

Why this exists
---------------

The interactive `make orchestrate.*` loop assumes a single human
attendant who restarts work after a crash. In CI we need the
**workflow** to survive interruption — most commonly a Copilot /
upstream LLM rate-limit (429) mid-phase. Burning Actions minutes by
sleeping in-job is wasteful, so the runtime instead:

1. Writes a cursor to `.orchestrator/resume/<run-id>.json` describing
   what's left to do (filter, model, branch, last-completed phase,
   not-before timestamp).
2. Commits + pushes that cursor to the work branch via the gitops
   layer (CI-only carve-out, see AGENTS.md Rule 9 CI exception).
3. Exits cleanly. A separate cron-driven scheduler workflow scans
   the cursor directory on the default branch every 15 minutes and
   re-dispatches the main workflow when `not_before <= now`.

This module owns the cursor file format. It is **read by both**
`orchestrate-roadmap.yml` (to seed the next run) and
`orchestrate-resume.yml` (to decide when to re-dispatch). Both
workflows are pure orchestration — actual cursor manipulation happens
here in Python.

Public API (intentionally tiny):

    save_cursor(...)        — write a new cursor for the current run
    load_cursor(path)       — parse one cursor file
    list_pending(now)       — list cursor files whose not_before <= now
    drop_cursor(path)       — delete a cursor (called after re-dispatch)

The orchestrator package stays git-free per its own README; the
gitops glue lives in `xops/ci/` and is responsible for committing
the cursor file. This module is purely a serializer + cursor
inspector.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable, List, Optional

from .roadmap import REPO_ROOT

RESUME_DIR = REPO_ROOT / ".orchestrator" / "resume"
CURSOR_SCHEMA_VERSION = 1
MAX_RETRIES = 8                    # refuse infinite-loop cursors
SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass
class ResumeCursor:
    """All state needed to resume a paused orchestrator run.

    Fields are intentionally narrow:

    - ``include`` / ``exclude``: the original filter tokens the human
      picked. The next run re-resolves them against the *current*
      ROADMAP, so already-completed phases are auto-skipped.
    - ``model``: the model id the human picked (e.g.
      ``claude-sonnet-4-5``). Carried through so the resumed run
      doesn't silently switch models on the operator.
    - ``branch``: the per-run work branch (e.g.
      ``agent/phase-8-12345``). The scheduler workflow re-dispatches
      against this branch so the next run sees the partial diff.
    - ``last_completed_phase`` / ``next_phase``: best-effort hints.
      Authoritative state lives in ROADMAP checkboxes + phases.csv;
      these fields are debug breadcrumbs, not contracts.
    - ``not_before``: epoch seconds. The scheduler workflow refuses
      to re-dispatch before this. Source = ``retry-after`` header
      from the rate-limit response (or a default backoff).
    - ``reason``: human-readable description ("copilot 429:
      30 min retry-after"). Surfaced in scheduler logs + tracker.
    - ``retry_count``: refuses to re-arm past ``MAX_RETRIES``.
    """

    schema_version: int = CURSOR_SCHEMA_VERSION
    run_id: str = ""                     # GH Actions run id (string)
    workflow_id: str = ""                # source workflow file basename
    include: List[str] = field(default_factory=list)
    exclude: List[str] = field(default_factory=list)
    model: str = ""
    branch: str = ""
    last_completed_phase: str = ""
    next_phase: str = ""
    not_before: float = 0.0
    reason: str = ""
    retry_count: int = 0
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict) -> "ResumeCursor":
        if raw.get("schema_version") != CURSOR_SCHEMA_VERSION:
            raise ValueError(
                f"resume cursor schema_version mismatch: "
                f"expected {CURSOR_SCHEMA_VERSION}, got {raw.get('schema_version')!r}"
            )
        kwargs = {k: raw[k] for k in raw if k in cls.__annotations__}
        return cls(**kwargs)


# ── filesystem helpers ────────────────────────────────────────


def _safe_name(token: str) -> str:
    return SAFE_NAME_RE.sub("-", token).strip("-") or "unknown"


def cursor_path(run_id: str) -> Path:
    """Deterministic path so a re-run of the same job can find its own cursor."""
    return RESUME_DIR / f"{_safe_name(run_id)}.json"


def save_cursor(cursor: ResumeCursor) -> Path:
    """Atomically write a cursor. The CI git-glue is responsible for
    staging + committing the resulting file to the work branch."""
    if cursor.retry_count > MAX_RETRIES:
        raise RuntimeError(
            f"resume cursor for run {cursor.run_id!r} exceeded MAX_RETRIES "
            f"({MAX_RETRIES}); refusing to arm another retry — escalate to human"
        )
    if not cursor.run_id:
        raise ValueError("cursor.run_id is required")
    RESUME_DIR.mkdir(parents=True, exist_ok=True)
    path = cursor_path(cursor.run_id)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(cursor.to_dict(), indent=2, sort_keys=True) + "\n",
                   encoding="utf-8")
    os.replace(tmp, path)
    return path


def load_cursor(path: Path) -> ResumeCursor:
    return ResumeCursor.from_dict(json.loads(path.read_text(encoding="utf-8")))


def list_cursors() -> List[Path]:
    if not RESUME_DIR.exists():
        return []
    return sorted(p for p in RESUME_DIR.glob("*.json") if p.is_file())


def list_pending(now: Optional[float] = None) -> List[ResumeCursor]:
    """Return cursors whose ``not_before`` has elapsed, oldest first.

    Used by `orchestrate-resume.yml` to decide which paused runs are
    ready to wake up. Malformed cursors are skipped (logged by caller).
    """
    cutoff = now if now is not None else time.time()
    ready: List[ResumeCursor] = []
    for path in list_cursors():
        try:
            c = load_cursor(path)
        except (ValueError, json.JSONDecodeError):
            continue
        if c.not_before <= cutoff:
            ready.append(c)
    ready.sort(key=lambda c: c.not_before)
    return ready


def drop_cursor(path: Path) -> None:
    """Remove a cursor after the scheduler re-dispatches its run.

    Refuses to follow symlinks (CI safety) and silently no-ops if the
    file is already gone.
    """
    try:
        if path.is_symlink():
            raise RuntimeError(f"refusing to delete symlink: {path}")
        path.unlink()
    except FileNotFoundError:
        pass


# ── rate-limit detection ──────────────────────────────────────


# Conservative defaults. Real values come from the upstream response
# headers when present; these only fire if nothing more specific is
# available.
DEFAULT_BACKOFF_SECONDS = 30 * 60         # 30 minutes
MAX_BACKOFF_SECONDS = 6 * 60 * 60         # 6 hours (matches GH Actions job cap)


def compute_not_before(
    retry_after_header: Optional[str],
    *,
    now: Optional[float] = None,
    retry_count: int = 0,
) -> float:
    """Derive a ``not_before`` epoch from an HTTP ``Retry-After`` value.

    Accepts either a seconds-as-int form (`"1800"`) or an RFC 7231
    HTTP-date form (`"Sun, 06 Nov 1994 08:49:37 GMT"`). On parse failure
    we fall back to an exponential backoff capped at
    ``MAX_BACKOFF_SECONDS``. We never return a value beyond that cap;
    the safety net is `MAX_RETRIES` in ``save_cursor``.
    """
    base = now if now is not None else time.time()

    # 1) Integer-seconds form.
    if retry_after_header and retry_after_header.strip().isdigit():
        delta = min(int(retry_after_header.strip()), MAX_BACKOFF_SECONDS)
        return base + max(delta, 60)        # never < 1 minute

    # 2) HTTP-date form.
    if retry_after_header:
        try:
            from email.utils import parsedate_to_datetime
            when = parsedate_to_datetime(retry_after_header).timestamp()
            if when - base > MAX_BACKOFF_SECONDS:
                return base + MAX_BACKOFF_SECONDS
            return max(when, base + 60)
        except (TypeError, ValueError):
            pass

    # 3) Exponential backoff fallback.
    delta = min(DEFAULT_BACKOFF_SECONDS * (2 ** retry_count), MAX_BACKOFF_SECONDS)
    return base + delta


__all__ = [
    "ResumeCursor",
    "CURSOR_SCHEMA_VERSION",
    "MAX_RETRIES",
    "RESUME_DIR",
    "cursor_path",
    "save_cursor",
    "load_cursor",
    "list_cursors",
    "list_pending",
    "drop_cursor",
    "compute_not_before",
]
