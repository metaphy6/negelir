"""ci_full_roadmap — cursor management for the full-project CI loop.

The full-roadmap loop is an event-driven chain where:
  1. ``orchestrate-full-roadmap.yml`` dispatches the implementer for
     phase[0] and persists the rest of the phases in a cursor.
  2. When the phase PR is merged, ``orchestrate-pr-review.yml`` reads
     the cursor, pops the next phase, and re-dispatches the workflow.
  3. Steps 1–2 repeat until ``phases_remaining`` is empty (project done).

At most ONE cursor is active at a time (the loop is serial). The cursor
lives at ``.orchestrator/full-roadmap/<session_id>.json`` on the default
branch so it survives workflow runs.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
CURSOR_DIR = REPO_ROOT / ".orchestrator" / "full-roadmap"


# ── Cursor dataclass ──────────────────────────────────────────────────────────

@dataclass
class FullRoadmapCursor:
    session_id: str
    phases_remaining: List[str]
    phases_completed: List[str] = field(default_factory=list)
    exclude: str = ""
    model: str = "claude-sonnet-4-5"
    max_phases: int = 100
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    last_phase_dispatched: str = ""
    last_phase_dispatched_at: str = ""
    triggered_by_run_id: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "FullRoadmapCursor":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# ── Path helpers ──────────────────────────────────────────────────────────────

def cursor_path(session_id: str) -> Path:
    return CURSOR_DIR / f"{session_id}.json"


def list_cursors() -> List[Path]:
    if not CURSOR_DIR.exists():
        return []
    return sorted(CURSOR_DIR.glob("*.json"))


def find_active_cursor() -> Optional[FullRoadmapCursor]:
    """Return the single active cursor (first *.json found), or None."""
    paths = list_cursors()
    if not paths:
        return None
    return load_cursor(paths[0])


# ── CRUD ──────────────────────────────────────────────────────────────────────

def save_cursor(cursor: FullRoadmapCursor) -> Path:
    CURSOR_DIR.mkdir(parents=True, exist_ok=True)
    path = cursor_path(cursor.session_id)
    path.write_text(json.dumps(cursor.to_dict(), indent=2, sort_keys=True))
    return path


def load_cursor(path: Path) -> FullRoadmapCursor:
    data = json.loads(path.read_text())
    return FullRoadmapCursor.from_dict(data)


def drop_cursor(path: Path) -> None:
    """Delete a cursor file. Idempotent — no error if already gone."""
    try:
        path.unlink()
    except FileNotFoundError:
        pass


# ── Lifecycle helpers ─────────────────────────────────────────────────────────

def new_cursor(
    phases: List[str],
    *,
    exclude: str = "",
    model: str = "claude-sonnet-4-5",
    max_phases: int = 100,
    triggered_by_run_id: str = "",
    session_id: Optional[str] = None,
) -> FullRoadmapCursor:
    """Create a brand-new cursor. Caps ``phases`` to ``max_phases``."""
    session = session_id or str(uuid.uuid4())[:8]
    return FullRoadmapCursor(
        session_id=session,
        phases_remaining=phases[:max_phases],
        phases_completed=[],
        exclude=exclude,
        model=model,
        max_phases=max_phases,
        triggered_by_run_id=triggered_by_run_id,
    )


def advance_cursor(cursor: FullRoadmapCursor, dispatched_phase: str) -> None:
    """Record that ``dispatched_phase`` has been dispatched (moved to in-flight).

    The phase stays in ``phases_remaining`` until ``complete_phase`` is called
    after the PR merges. This function just stamps the dispatch metadata.
    """
    cursor.last_phase_dispatched = dispatched_phase
    cursor.last_phase_dispatched_at = datetime.now(timezone.utc).isoformat()


def complete_phase(cursor: FullRoadmapCursor, phase_id: str) -> Optional[str]:
    """Mark ``phase_id`` done. Returns the NEXT phase id (or None if done).

    Removes ``phase_id`` from ``phases_remaining``, appends to
    ``phases_completed``. If the phase was not in ``phases_remaining``, the
    call is idempotent (it may have already been handled by a retried run).
    """
    if phase_id in cursor.phases_remaining:
        cursor.phases_remaining.remove(phase_id)
    if phase_id not in cursor.phases_completed:
        cursor.phases_completed.append(phase_id)
    return cursor.phases_remaining[0] if cursor.phases_remaining else None
