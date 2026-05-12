"""File-locked phase claims for parallel-safe orchestration.

The orchestrator stores per-phase locks under
`<repo>/.orchestrator/locks/<safe-id>.lock`. Mutual exclusion is provided
by atomic `os.open(..., O_CREAT | O_EXCL)`, which is portable across POSIX
and Windows and — crucially — survives across short-lived CLI invocations
(unlike `fcntl.flock`, which releases on fd close).

Lock files contain a small JSON header (claimer uuid, claim time, host, pid)
so that operators can inspect or `--force` release a stale claim left by a
crashed agent. There is no automatic timeout — the human operator (the only
one allowed to land git commits per AGENTS.md Rule 9) is the safety net.
"""

from __future__ import annotations

import json
import os
import socket
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional

from .roadmap import REPO_ROOT

LOCK_DIR = REPO_ROOT / ".orchestrator" / "locks"


@dataclass
class LockHeader:
    phase_id: str
    claimer_id: str
    claimed_at: float
    host: str
    pid: int

    def to_json(self) -> str:
        return json.dumps(
            {
                "phase_id": self.phase_id,
                "claimer_id": self.claimer_id,
                "claimed_at": self.claimed_at,
                "host": self.host,
                "pid": self.pid,
            },
            indent=2,
            sort_keys=True,
        )

    @classmethod
    def from_path(cls, path: Path) -> Optional["LockHeader"]:
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8") or "{}")
        except (json.JSONDecodeError, OSError):
            return None
        try:
            return cls(
                phase_id=data["phase_id"],
                claimer_id=data["claimer_id"],
                claimed_at=float(data["claimed_at"]),
                host=str(data["host"]),
                pid=int(data["pid"]),
            )
        except (KeyError, TypeError, ValueError):
            return None


class LockBusy(Exception):
    """Raised when a phase is already claimed by another orchestrator run."""


class LockMissing(Exception):
    """Raised when releasing a lock that doesn't exist."""


def _safe_id(phase_id: str) -> str:
    # Phase ids are dotted; replace dots with underscores for filename safety.
    return phase_id.replace(".", "_")


def lock_path(phase_id: str) -> Path:
    LOCK_DIR.mkdir(parents=True, exist_ok=True)
    return LOCK_DIR / f"phase_{_safe_id(phase_id)}.lock"


def try_claim(phase_id: str, claimer_id: Optional[str] = None) -> LockHeader:
    """Attempt to claim a phase. Raise LockBusy if already held."""
    path = lock_path(phase_id)
    cid = claimer_id or f"orchestrator-{uuid.uuid4().hex[:12]}"
    header = LockHeader(
        phase_id=phase_id,
        claimer_id=cid,
        claimed_at=time.time(),
        host=socket.gethostname(),
        pid=os.getpid(),
    )
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        existing = LockHeader.from_path(path)
        raise LockBusy(
            f"phase {phase_id} is already claimed"
            f"{' by ' + existing.claimer_id if existing else ''}"
        ) from None
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(header.to_json())
        fh.flush()
        os.fsync(fh.fileno())
    return header


def release(phase_id: str, *, force: bool = False) -> bool:
    """Release a phase lock. Returns True if a lock file was removed."""
    path = lock_path(phase_id)
    try:
        path.unlink()
        return True
    except FileNotFoundError:
        if force:
            return False
        raise LockMissing(f"no lock for phase {phase_id}") from None


def inspect(phase_id: str) -> Optional[LockHeader]:
    """Return the header for an existing lock, or None if free."""
    return LockHeader.from_path(lock_path(phase_id))


def list_held() -> list[LockHeader]:
    LOCK_DIR.mkdir(parents=True, exist_ok=True)
    out: list[LockHeader] = []
    for p in sorted(LOCK_DIR.glob("phase_*.lock")):
        h = LockHeader.from_path(p)
        if h:
            out.append(h)
    return out


@contextmanager
def claim(phase_id: str, claimer_id: Optional[str] = None) -> Iterator[LockHeader]:
    header = try_claim(phase_id, claimer_id=claimer_id)
    try:
        yield header
    finally:
        try:
            release(phase_id)
        except LockMissing:
            pass


__all__ = [
    "LockBusy",
    "LockMissing",
    "LockHeader",
    "LOCK_DIR",
    "lock_path",
    "try_claim",
    "release",
    "inspect",
    "list_held",
    "claim",
]
