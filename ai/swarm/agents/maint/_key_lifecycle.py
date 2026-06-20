"""Phase 8 §8.15.4 — HMAC key lifecycle helpers (revocation, rotation, cache,
kill-switch, rate-limiting).

This module is imported by :mod:`._op_signature` and provides the
stateful / protocol components that keep the operator registry fresh
at runtime without repeated disk reads on every envelope.

Thread-safety: all public state classes are designed for a single-
threaded event loop.  Thread-safe atomic swaps are done via a simple
``threading.Lock`` where required, keeping the dependency surface
stdlib-only.
"""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from ai.common.config import Config

_REPO_ROOT = Path(__file__).resolve().parents[5]

# ──────────────────────────────────────────────────────────────────────────────
# Kill-switch helpers (§8.15.4 bullet 5)
# ──────────────────────────────────────────────────────────────────────────────

def _resolve_kill_switch_path(cfg: Config) -> Path:
    p = getattr(cfg, "opsctl_kill_switch_path", "").strip()
    return Path(p).expanduser() if p else _REPO_ROOT / "infra" / "maint" / "opsctl_kill_switch"


def check_kill_switch(cfg: Config) -> bool:
    """Return True if the emergency kill-switch is currently active.

    The kill-switch is active when:
      1. The file ``cfg.opsctl_kill_switch_path`` exists, AND
      2. Its mtime is within ``cfg.opsctl_kill_switch_max_age_h`` hours.

    This is a per-call ``stat()`` — deliberately NOT cached — so that
    the operator can activate / deactivate by touching / removing the
    file with sub-second effect latency.
    """
    path = _resolve_kill_switch_path(cfg)
    try:
        mtime = path.stat().st_mtime
    except FileNotFoundError:
        return False
    max_age_h = getattr(cfg, "opsctl_kill_switch_max_age_h", 24)
    age_s = time.time() - mtime
    return age_s < max_age_h * 3600


# ──────────────────────────────────────────────────────────────────────────────
# Operators cache (§8.15.4 bullet 4 — cache coherency)
# ──────────────────────────────────────────────────────────────────────────────

class OperatorsCache:
    """Thread-safe, mtime-polling cache for ``opsctl_operators.json``.

    The cache is atomically swapped on each reload so in-flight
    signature verifications complete against the snapshot they started
    with.

    Reload failure (file missing or unreadable) sets ``_fail_safe``
    to True; every subsequent signature check fails with
    ``"operators_unreadable"`` until the next successful reload.

    The cache is intentionally per-process (not Redis-backed at v1).
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._operators: Dict[str, Dict[str, Any]] = {}
        self._prev_operators: Dict[str, Dict[str, Any]] = {}
        self._fail_safe: bool = False
        self._last_reload: float = 0.0
        self._last_mtime: float = -1.0
        self._operators_path: Optional[Path] = None

    def _do_reload(self, path: Path) -> None:
        import json  # noqa: PLC0415
        try:
            new_mtime = path.stat().st_mtime
            if new_mtime == self._last_mtime:
                return  # no change
            data = json.loads(path.read_text(encoding="utf-8"))
            new_operators: Dict[str, Dict[str, Any]] = dict(data.get("operators", {}))
            with self._lock:
                self._prev_operators = self._operators
                self._operators = new_operators
                self._last_mtime = new_mtime
                self._fail_safe = False
        except FileNotFoundError:
            with self._lock:
                self._fail_safe = True
        except Exception:
            with self._lock:
                self._fail_safe = True

    def get_snapshot(
        self,
        cfg: Config,
        operators_path: Path,
    ) -> Tuple[Optional[Dict[str, Dict[str, Any]]], bool]:
        """Return ``(operators_dict, is_fail_safe)``.

        Reloads the file if the poll interval has elapsed.

        Returns ``(None, True)`` when in fail-safe mode (file unreadable).
        """
        reload_s = getattr(cfg, "opsctl_operators_reload_s", 60)
        now = time.monotonic()
        if now - self._last_reload >= reload_s:
            self._do_reload(operators_path)
            self._last_reload = now
        with self._lock:
            if self._fail_safe:
                return None, True
            return dict(self._operators), False

    def force_reload(self, operators_path: Path) -> None:
        """Unconditionally reload the file (used on cache miss)."""
        self._do_reload(operators_path)
        self._last_reload = time.monotonic()

    @property
    def prev_snapshot(self) -> Dict[str, Dict[str, Any]]:
        """Previous cache snapshot (for mismatch-detection logging)."""
        with self._lock:
            return dict(self._prev_operators)

    @property
    def fail_safe(self) -> bool:
        with self._lock:
            return self._fail_safe


# Module-level singleton — shared across all envelope verifications in
# the same process.  Tests can replace it via the test fixture.
_OPERATORS_CACHE = OperatorsCache()


def get_operators_cache() -> OperatorsCache:
    """Return the module-level operators cache singleton."""
    return _OPERATORS_CACHE


def reset_operators_cache() -> None:
    """Replace the module-level cache with a fresh instance (tests only)."""
    global _OPERATORS_CACHE  # noqa: PLW0603
    _OPERATORS_CACHE = OperatorsCache()


# ──────────────────────────────────────────────────────────────────────────────
# Per-key rate-limit token bucket (§8.15.4 bullet 6)
# ──────────────────────────────────────────────────────────────────────────────

class _KeyRateBucket:
    """Token-bucket per ``key_id``, refilled at ``limit_per_min / 60`` per second."""

    def __init__(self, limit_per_min: int) -> None:
        self._limit = limit_per_min
        self._tokens: Dict[str, float] = {}
        self._last_refill: Dict[str, float] = {}

    def consume(self, key_id: str) -> bool:
        """Attempt to consume one token for ``key_id``.

        Returns True if within budget; False if rate-limited.
        A limit of 0 means unlimited.
        """
        if self._limit == 0:
            return True
        now = time.monotonic()
        if key_id not in self._tokens:
            self._tokens[key_id] = float(self._limit)
            self._last_refill[key_id] = now
        else:
            elapsed = now - self._last_refill[key_id]
            refill = elapsed * (self._limit / 60.0)
            self._tokens[key_id] = min(self._limit, self._tokens[key_id] + refill)
            self._last_refill[key_id] = now

        if self._tokens[key_id] >= 1.0:
            self._tokens[key_id] -= 1.0
            return True
        return False


# Module-level rate-bucket singleton.
_RATE_BUCKET: Optional[_KeyRateBucket] = None
_RATE_BUCKET_LIMIT: int = -1


def get_rate_bucket(cfg: Config) -> _KeyRateBucket:
    """Return or recreate the module-level rate bucket (respects cfg changes)."""
    global _RATE_BUCKET, _RATE_BUCKET_LIMIT  # noqa: PLW0603
    limit = getattr(cfg, "opsctl_key_rate_limit_per_min", 30)
    if _RATE_BUCKET is None or _RATE_BUCKET_LIMIT != limit:
        _RATE_BUCKET = _KeyRateBucket(limit)
        _RATE_BUCKET_LIMIT = limit
    return _RATE_BUCKET


def reset_rate_bucket() -> None:
    """Reset module-level rate bucket (tests only)."""
    global _RATE_BUCKET, _RATE_BUCKET_LIMIT  # noqa: PLW0603
    _RATE_BUCKET = None
    _RATE_BUCKET_LIMIT = -1


# ──────────────────────────────────────────────────────────────────────────────
# Rotation-overdue alert debounce (§8.15.4 bullet 3)
# ──────────────────────────────────────────────────────────────────────────────

# key_id → last alert epoch (float seconds, monotonic)
_ROTATION_OVERDUE_DEBOUNCE: Dict[str, float] = {}
_ROTATION_OVERDUE_INTERVAL_S: float = 86400.0  # once per day


def check_rotation_overdue(
    operators: Dict[str, Dict[str, Any]],
    cfg: Config,
) -> list[Dict[str, Any]]:
    """Scan operators for keys past ``cfg.opsctl_key_max_age_days``.

    Returns a list of ``{kind, key_id, age_days, severity}`` dicts for
    each overdue key whose daily debounce has expired.  Callers are
    responsible for emitting the corresponding ``sec.alert.v1`` events.
    """
    import datetime  # noqa: PLC0415
    max_age_days = getattr(cfg, "opsctl_key_max_age_days", 365)
    alerts: list[Dict[str, Any]] = []
    now_mono = time.monotonic()
    now_utc = time.time()

    for key_id, entry in operators.items():
        if entry.get("revoked_at") is not None:
            continue  # already revoked — not our concern
        added_at_str = entry.get("added_at", "")
        if not added_at_str:
            continue
        try:
            added_dt = datetime.datetime.fromisoformat(
                added_at_str.replace("Z", "+00:00")
            )
            age_days = (now_utc - added_dt.timestamp()) / 86400.0
        except (ValueError, OSError):
            continue

        if age_days <= max_age_days:
            continue

        # Debounce: one alert per key per day.
        # float('-inf') sentinel means "never alerted" → always expired.
        last = _ROTATION_OVERDUE_DEBOUNCE.get(key_id, float('-inf'))
        if now_mono - last < _ROTATION_OVERDUE_INTERVAL_S:
            continue

        _ROTATION_OVERDUE_DEBOUNCE[key_id] = now_mono
        alerts.append({
            "kind": "opsctl_key_rotation_overdue",
            "key_id": key_id,
            "age_days": round(age_days, 1),
            "severity": "warn",
        })
    return alerts


# ──────────────────────────────────────────────────────────────────────────────
# Rate-limit debounce (§8.15.4 bullet 6)
# ──────────────────────────────────────────────────────────────────────────────

# key_id → last rate-limit alert epoch (monotonic seconds)
_RATE_LIMIT_DEBOUNCE: Dict[str, float] = {}
_RATE_LIMIT_DEBOUNCE_S: float = 300.0  # 5 minutes per key_id


def is_rate_limit_debounce_expired(key_id: str) -> bool:
    """Return True iff the rate-limit debounce for ``key_id`` has expired."""
    now = time.monotonic()
    last = _RATE_LIMIT_DEBOUNCE.get(key_id, 0.0)
    if now - last >= _RATE_LIMIT_DEBOUNCE_S:
        _RATE_LIMIT_DEBOUNCE[key_id] = now
        return True
    return False


def reset_debounce_state() -> None:
    """Clear all debounce state (tests only)."""
    _ROTATION_OVERDUE_DEBOUNCE.clear()
    _RATE_LIMIT_DEBOUNCE.clear()


__all__ = [
    "check_kill_switch",
    "OperatorsCache",
    "get_operators_cache",
    "reset_operators_cache",
    "get_rate_bucket",
    "reset_rate_bucket",
    "check_rotation_overdue",
    "is_rate_limit_debounce_expired",
    "reset_debounce_state",
]
