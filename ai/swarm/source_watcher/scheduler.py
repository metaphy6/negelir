"""Periodic scheduler for the source_watcher pipeline.

Pure logic + injectable clock + injectable fetcher → fully testable
without sleeping or touching the network.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from . import snapshot_store
from .classifier import classify
from .differ import diff_json
from .planner import UpdatePlan, plan

Fetcher = Callable[[str], Any]      # source key → fetched payload
Clock = Callable[[], float]         # epoch seconds


@dataclass
class Tick:
    source: str
    plan: Optional[UpdatePlan]
    skipped_reason: Optional[str] = None


def run_once(
    sources: List[str],
    *,
    fetcher: Fetcher,
    snapshot_root=snapshot_store.HISTORY_ROOT,
) -> List[Tick]:
    """Fetch each source, snapshot it, diff vs previous, plan."""
    out: List[Tick] = []
    for src in sources:
        payload = fetcher(src)
        prev = snapshot_store.latest(src, root=snapshot_root)
        snap = snapshot_store.store(src, payload, root=snapshot_root)
        if prev is None:
            out.append(Tick(source=src, plan=None, skipped_reason="first_snapshot"))
            continue
        if prev.sha256 == snap.sha256:
            out.append(Tick(source=src, plan=None, skipped_reason="unchanged"))
            continue
        diffs = diff_json(prev.payload, snap.payload)
        classified = classify(diffs)
        out.append(Tick(source=src, plan=plan(src, classified)))
    return out


def loop(
    sources: List[str],
    *,
    fetcher: Fetcher,
    interval_s: float,
    iterations: Optional[int] = None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Clock = time.monotonic,
    snapshot_root=snapshot_store.HISTORY_ROOT,
    on_tick: Optional[Callable[[List[Tick]], None]] = None,
) -> List[List[Tick]]:
    """Run ``run_once`` every ``interval_s`` seconds.

    Pass ``iterations=N`` to bound the loop (used by tests). Production
    callers pass ``iterations=None`` for unbounded runs and rely on
    process lifecycle for shutdown.
    """
    if interval_s <= 0:
        raise ValueError("interval_s must be positive")
    history: List[List[Tick]] = []
    i = 0
    while iterations is None or i < iterations:
        ticks = run_once(sources, fetcher=fetcher, snapshot_root=snapshot_root)
        history.append(ticks)
        if on_tick is not None:
            on_tick(ticks)
        i += 1
        if iterations is not None and i >= iterations:
            break
        sleep(interval_s)
    return history
