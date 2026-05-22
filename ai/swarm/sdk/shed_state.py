"""Phase 8 §8.15.8 — shed-tier persistence for leader handover.

Provides :class:`ShedStateStore` which :class:`~swarm.agents.maint
._lag_watchdog.MaintLagWatchdog` uses to persist its active shedding
tier so a new leader (or a restarted process) can inherit the tier
without re-amplifying a plane-wide incident.

Compose mode (``cfg.maint_runtime != "k8s"``): state lives in
``data/maint/lease/<agent>.shed_state.json`` (mode 0600; written
atomically via a sibling-temp + os.replace).

K8s mode (Phase 14 placeholder): will map to
``coordination.k8s.io/v1.Lease`` annotations::

    negelir.io/maint-shed-tier
    negelir.io/maint-shed-since-utc
    negelir.io/maint-shed-reason
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class ShedStateRecord:
    """Persisted shed-tier snapshot written by the outgoing leader."""

    tier: int
    since_utc: str
    reason: str
    pod_instance_id: str


class ShedStateStore:
    """Atomic read/write store for the active shedding tier.

    Parameters
    ----------
    path:
        Absolute path to the shed-state JSON file.
        Parent directories are created on first write.
        Pass an explicit :class:`pathlib.Path` in tests to keep writes
        off the live filesystem.
    """

    def __init__(self, path: Path) -> None:
        self._path = Path(path)

    # ── Public interface ────────────────────────────────────────────────

    def write(self, tier: int, reason: str, pod_instance_id: str) -> None:
        """Persist *tier* atomically (sibling-temp + os.replace).

        Mode 0600 (owner read/write only) is requested on POSIX; best-
        effort on platforms that do not support it.
        """
        self._path.parent.mkdir(parents=True, exist_ok=True)
        record: dict = {
            "tier": tier,
            "since_utc": _utc_iso(),
            "reason": reason,
            "pod_instance_id": pod_instance_id,
            "_schema": 1,
        }
        tmp = self._path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(record, separators=(",", ":")), encoding="utf-8")
        os.replace(tmp, self._path)
        try:
            self._path.chmod(0o600)
        except OSError:
            pass  # best-effort; test sandboxes may not support chmod

    def read(self) -> Optional[ShedStateRecord]:
        """Return the stored record, or *None* if absent or corrupt."""
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError):
            return None
        try:
            return ShedStateRecord(
                tier=int(data["tier"]),
                since_utc=str(data["since_utc"]),
                reason=str(data["reason"]),
                pod_instance_id=str(data["pod_instance_id"]),
            )
        except (KeyError, TypeError):
            return None

    def clear(self) -> None:
        """Remove the stored state file (idempotent)."""
        try:
            self._path.unlink()
        except FileNotFoundError:
            pass

    @property
    def path(self) -> Path:
        """Absolute path to the backing file."""
        return self._path


def default_shed_state_path(agent_name: str) -> Path:
    """Return the canonical compose-mode path for *agent_name*.

    Example::

        default_shed_state_path("maint.scaler.v1")
        # → Path("data/maint/lease/maint.scaler.v1.shed_state.json")
    """
    return Path("data/maint/lease") / f"{agent_name}.shed_state.json"


__all__ = [
    "ShedStateRecord",
    "ShedStateStore",
    "default_shed_state_path",
]
