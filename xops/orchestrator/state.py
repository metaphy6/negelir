"""Per-phase orchestration state.

State lives next to the locks under `<repo>/.orchestrator/state/<safe-id>.json`
and tracks the multi-pass review pipeline:

    pending → implementing → reviewing → verifying → completed
                                     ↘ failed | escalated

Each transition appends to a `passes[]` log so a future agent (or human)
can reconstruct exactly what every subagent did, when, with which model.
The state file is the single source of truth for orchestrator progress;
`docs/tracking/phases.csv` remains the canonical project tracker (the
orchestrator writes a tracker row when a phase reaches `completed`).
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from .roadmap import REPO_ROOT

STATE_DIR = REPO_ROOT / ".orchestrator" / "state"

# Closed enum — every transition validated.
STATUSES = (
    "pending",
    "implementing",
    "reviewing",
    "verifying",
    "completed",
    "failed",
    "escalated",
    "skipped",
)

ROLES = ("implementer", "reviewer", "verifier")


@dataclass
class PassRecord:
    role: str
    at: float
    outcome: str  # "ok", "needs-changes", "blocked", "escalated"
    model: str = ""
    notes: str = ""
    diff_summary: str = ""


@dataclass
class PhaseState:
    phase_id: str
    title: str
    status: str = "pending"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    passes: List[PassRecord] = field(default_factory=list)
    last_error: str = ""
    tracker_rows_added: int = 0
    version_bumps: List[Dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "phase_id": self.phase_id,
            "title": self.title,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "passes": [asdict(p) for p in self.passes],
            "last_error": self.last_error,
            "tracker_rows_added": self.tracker_rows_added,
            "version_bumps": list(self.version_bumps),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PhaseState":
        return cls(
            phase_id=str(data["phase_id"]),
            title=str(data.get("title", "")),
            status=str(data.get("status", "pending")),
            created_at=float(data.get("created_at", time.time())),
            updated_at=float(data.get("updated_at", time.time())),
            passes=[PassRecord(**p) for p in data.get("passes", [])],
            last_error=str(data.get("last_error", "")),
            tracker_rows_added=int(data.get("tracker_rows_added", 0)),
            version_bumps=list(data.get("version_bumps", [])),
        )


def _safe_id(phase_id: str) -> str:
    return phase_id.replace(".", "_")


def state_path(phase_id: str) -> Path:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    return STATE_DIR / f"phase_{_safe_id(phase_id)}.json"


def load(phase_id: str) -> Optional[PhaseState]:
    path = state_path(phase_id)
    if not path.is_file():
        return None
    try:
        return PhaseState.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, OSError, KeyError, ValueError):
        return None


def save(state: PhaseState) -> None:
    state.updated_at = time.time()
    path = state_path(state.phase_id)
    # Atomic write: tmp + os.replace.
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(state.to_dict(), fh, indent=2, sort_keys=True)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def transition(state: PhaseState, new_status: str) -> None:
    if new_status not in STATUSES:
        raise ValueError(f"unknown status {new_status!r}; expected one of {STATUSES}")
    state.status = new_status


def record_pass(
    state: PhaseState,
    *,
    role: str,
    outcome: str,
    model: str = "",
    notes: str = "",
    diff_summary: str = "",
) -> None:
    if role not in ROLES:
        raise ValueError(f"unknown role {role!r}; expected one of {ROLES}")
    state.passes.append(
        PassRecord(
            role=role,
            at=time.time(),
            outcome=outcome,
            model=model,
            notes=notes,
            diff_summary=diff_summary,
        )
    )


def list_states() -> List[PhaseState]:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    out: List[PhaseState] = []
    for p in sorted(STATE_DIR.glob("phase_*.json")):
        try:
            out.append(PhaseState.from_dict(json.loads(p.read_text(encoding="utf-8"))))
        except (json.JSONDecodeError, OSError, KeyError, ValueError):
            continue
    return out


__all__ = [
    "STATUSES",
    "ROLES",
    "STATE_DIR",
    "PassRecord",
    "PhaseState",
    "state_path",
    "load",
    "save",
    "transition",
    "record_pass",
    "list_states",
]
