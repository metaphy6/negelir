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
"""
from __future__ import annotations

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


__all__ = [
    "CLOCK_SOURCE_AUTO",
    "CLOCK_SOURCE_BOOTTIME",
    "CLOCK_SOURCE_MONOTONIC",
    "resolve_clock",
    "window_anchor_ns",
]
