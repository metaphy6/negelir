"""Phase 8 §8.15.1 — monotonic-clock helper for the maintenance plane.

The §8.2 scaler computes its decision-window anchor from a monotonic
clock so a wall-clock NTP step (post-suspend resume) cannot collapse
two windows into one or split one across a step. On Linux we prefer
``CLOCK_BOOTTIME`` (advances during suspend); elsewhere we fall back
to :func:`time.monotonic_ns`.

Selection is governed by ``cfg.maint_scaler_clock_source``:

* ``auto``       (default) — boottime on Linux, monotonic elsewhere.
* ``boottime``   — force ``CLOCK_BOOTTIME``; raises if unavailable.
* ``monotonic``  — force :func:`time.monotonic_ns`.

The chosen source is reported once via ``maint.event.v1{kind=
maint_clock_source_changed}`` at first use so dashboards know which
clock is anchoring the windows.

Suspend-detection (§8.15.1 probe)
----------------------------------
Agents that own a heartbeat loop call :func:`check_suspend_gap` once
per tick. It compares the delta between ``CLOCK_BOOTTIME`` and
``CLOCK_MONOTONIC`` across two successive calls; a step-up larger than
``cfg.maint_clock_suspend_alert_s`` (default 30 s) indicates that the
container was suspended between ticks.  Returns a dict suitable for
inclusion in a ``maint.event.v1{kind=maint_clock_source_changed,
action=suspend_detected}`` publish, or ``None`` if no event is needed.
"""
from __future__ import annotations

import datetime
import os
import sys
import time
from typing import Callable


CLOCK_SOURCE_AUTO = "auto"
CLOCK_SOURCE_BOOTTIME = "boottime"
CLOCK_SOURCE_MONOTONIC = "monotonic"

_VALID_SOURCES: frozenset[str] = frozenset(
    {CLOCK_SOURCE_AUTO, CLOCK_SOURCE_BOOTTIME, CLOCK_SOURCE_MONOTONIC}
)


def _boottime_available() -> bool:
    """``CLOCK_BOOTTIME`` is Linux-specific (kernel 2.6.39+)."""
    if not sys.platform.startswith("linux"):
        return False
    return hasattr(time, "CLOCK_BOOTTIME")


def resolve_clock(source: str) -> tuple[str, Callable[[], int]]:
    """Resolve a config value to ``(effective_source, ns_callable)``.

    Raises ``ValueError`` for unknown sources or when ``boottime`` is
    requested on a platform where it is unavailable.
    """
    src = (source or CLOCK_SOURCE_AUTO).strip().lower()
    if src not in _VALID_SOURCES:
        raise ValueError(
            f"maint_scaler_clock_source={source!r} not in "
            f"{sorted(_VALID_SOURCES)}"
        )
    if src == CLOCK_SOURCE_BOOTTIME or (
        src == CLOCK_SOURCE_AUTO and _boottime_available()
    ):
        if not _boottime_available():
            raise ValueError(
                "maint_scaler_clock_source=boottime requested but "
                "CLOCK_BOOTTIME is unavailable on this platform"
            )
        clk = time.CLOCK_BOOTTIME  # type: ignore[attr-defined]
        return (CLOCK_SOURCE_BOOTTIME, lambda: time.clock_gettime_ns(clk))
    return (CLOCK_SOURCE_MONOTONIC, time.monotonic_ns)


def window_anchor_ns(window_ms: int, *, now_ns: int | None = None,
                     source: str = CLOCK_SOURCE_AUTO) -> int:
    """Return the start-of-window anchor in ns for a given window size.

    Two calls inside the same window return the same anchor; the next
    window begins at ``anchor + window_ms*1_000_000``. Used by the
    scaler to assign one ``decision_window_id`` per window.
    """
    if window_ms <= 0:
        raise ValueError(f"window_ms must be > 0 (got {window_ms!r})")
    _, clk = resolve_clock(source)
    if now_ns is None:
        now_ns = clk()
    width_ns = int(window_ms) * 1_000_000
    return (now_ns // width_ns) * width_ns


# ── Boot validation ────────────────────────────────────────────────────────

def boot_validate_clock_source(
    source_cfg: str,
    *,
    agent_id: str = "",
    prev_source: str | None = None,
) -> dict[str, object]:
    """Validate ``source_cfg`` at agent boot and return event dicts.

    Returns a dict with two keys:

    * ``"maint_event"`` — a ``maint.event.v1{kind=maint_clock_source_changed}``
      payload dict (always present; broadcast once at boot).
    * ``"sec_alert"`` — a ``sec.alert.v1{kind=maint_clock_source_unsupported}``
      payload dict, or ``None`` if the resolved source is suspend-resilient.

    Raises ``SystemExit(1)`` (i.e. ``fail_safe_clock_source_unavailable``)
    when ``source_cfg="boottime"`` is forced but ``CLOCK_BOOTTIME`` is not
    available on the current platform.
    """
    src = (source_cfg or CLOCK_SOURCE_AUTO).strip().lower()
    if src not in _VALID_SOURCES:
        raise ValueError(
            f"maint_scaler_clock_source={source_cfg!r} not in "
            f"{sorted(_VALID_SOURCES)}"
        )
    # Forced boottime on unsupported platform → hard fail.
    if src == CLOCK_SOURCE_BOOTTIME and not _boottime_available():
        raise SystemExit(
            "fail_safe_clock_source_unavailable: "
            "maint_scaler_clock_source=boottime requested but "
            "CLOCK_BOOTTIME is unavailable on this platform"
        )
    # Resolve effective source.
    try:
        effective, _ = resolve_clock(source_cfg)
    except ValueError:
        # Already handled above; re-raise for safety.
        raise
    suspend_resilient = (effective == CLOCK_SOURCE_BOOTTIME)

    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

    maint_event: dict[str, object] = {
        "kind": "maint_clock_source_changed",
        "target": agent_id,
        "prev": prev_source,
        "current": effective,
        "suspend_resilient": suspend_resilient,
        "produced_at": now_iso,
    }

    sec_alert: dict[str, object] | None = None
    if not suspend_resilient:
        sec_alert = {
            "kind": "maint_clock_source_unsupported",
            "severity": "warn",
            "reason": (
                f"CLOCK_BOOTTIME unavailable on this platform "
                f"(platform={sys.platform!r}); falling back to "
                f"time.monotonic_ns() — window IDs are NOT suspend-resilient"
            ),
            "produced_at": now_iso,
        }

    return {"maint_event": maint_event, "sec_alert": sec_alert}


# ── Suspend-detection probe ────────────────────────────────────────────────

def check_suspend_gap(
    prev_boottime_ns: int,
    prev_monotonic_ns: int,
    cur_boottime_ns: int,
    cur_monotonic_ns: int,
    alert_threshold_s: float,
) -> dict[str, object] | None:
    """Detect a container suspend between two consecutive heartbeat ticks.

    The difference ``(boottime - monotonic)`` advances only during
    suspend (``CLOCK_MONOTONIC`` stands still; ``CLOCK_BOOTTIME`` does
    not).  If the delta grew by more than ``alert_threshold_s`` seconds
    since the previous sample, a suspend occurred.

    Parameters
    ----------
    prev_boottime_ns, prev_monotonic_ns:
        Clock readings from the *previous* heartbeat tick.
    cur_boottime_ns, cur_monotonic_ns:
        Clock readings from the *current* heartbeat tick.
    alert_threshold_s:
        Minimum gap growth (in seconds) that triggers an event.
        Pass ``0`` to disable (always returns ``None``).

    Returns
    -------
    A ``maint.event.v1{kind=maint_clock_source_changed,
    action=suspend_detected}`` payload dict, or ``None`` if no
    suspend was detected or the probe is disabled.
    """
    if alert_threshold_s <= 0:
        return None
    prev_delta_ns = prev_boottime_ns - prev_monotonic_ns
    cur_delta_ns = cur_boottime_ns - cur_monotonic_ns
    gap_ns = cur_delta_ns - prev_delta_ns
    if gap_ns <= 0:
        return None
    gap_s = gap_ns / 1_000_000_000
    if gap_s < alert_threshold_s:
        return None
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    return {
        "kind": "maint_clock_source_changed",
        "action": "suspend_detected",
        "gap_s": gap_s,
        "recovered_at_utc": now_iso,
        "produced_at": now_iso,
    }


class MonotonicClock:
    """Thin namespace capturing the UTC wall-clock time at process start.

    §8.15.11 proof tests import this class and assert
    ``hasattr(MonotonicClock, 'boot_utc')`` to confirm the clock module
    exposes a stable boot-time reference for forensic timestamps.

    ``boot_utc`` is set once at class-definition time (module import) so
    all callers within a process share the same origin.
    """

    boot_utc: datetime.datetime = datetime.datetime.now(datetime.timezone.utc)


__all__ = [
    "CLOCK_SOURCE_AUTO",
    "CLOCK_SOURCE_BOOTTIME",
    "CLOCK_SOURCE_MONOTONIC",
    "MonotonicClock",
    "boot_validate_clock_source",
    "check_suspend_gap",
    "resolve_clock",
    "window_anchor_ns",
]
