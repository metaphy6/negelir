"""Tests for the periodic scheduler — fake clock, fake fetcher, no I/O delay."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import pytest

from ai.swarm.source_watcher import scheduler


@pytest.fixture
def history_root(tmp_path: Path) -> Path:
    return tmp_path / "history"


def test_run_once_first_pass_skips_with_first_snapshot_reason(history_root: Path) -> None:
    fetcher = lambda src: {"v": 1}  # noqa: E731
    ticks = scheduler.run_once(["mackolik"], fetcher=fetcher, snapshot_root=history_root)
    assert len(ticks) == 1
    assert ticks[0].plan is None
    assert ticks[0].skipped_reason == "first_snapshot"


def test_run_once_unchanged_skips(history_root: Path) -> None:
    fetcher = lambda src: {"v": 1}  # noqa: E731
    scheduler.run_once(["nesine"], fetcher=fetcher, snapshot_root=history_root)
    ticks = scheduler.run_once(["nesine"], fetcher=fetcher, snapshot_root=history_root)
    assert ticks[0].skipped_reason == "unchanged"
    assert ticks[0].plan is None


def test_run_once_changed_produces_plan(history_root: Path) -> None:
    state: Dict[str, Any] = {"v": 1}
    fetcher = lambda src: dict(state)  # noqa: E731

    scheduler.run_once(["tff"], fetcher=fetcher, snapshot_root=history_root)
    state["v"] = 2  # mutate; differ should fire
    ticks = scheduler.run_once(["tff"], fetcher=fetcher, snapshot_root=history_root)

    assert ticks[0].plan is not None
    assert ticks[0].plan.source == "tff"
    assert ticks[0].plan.severity == "semantic"


def test_loop_runs_n_iterations_and_uses_fake_sleep(history_root: Path) -> None:
    sleeps: List[float] = []
    counter = {"n": 0}

    def fetcher(_src: str) -> Dict[str, int]:
        counter["n"] += 1
        return {"v": counter["n"]}

    history = scheduler.loop(
        ["x"],
        fetcher=fetcher,
        interval_s=5.0,
        iterations=3,
        sleep=sleeps.append,
        snapshot_root=history_root,
    )
    assert len(history) == 3
    # Three iterations → at most two sleeps between them (last one skipped).
    assert sleeps == [5.0, 5.0]


def test_loop_rejects_zero_interval(history_root: Path) -> None:
    with pytest.raises(ValueError):
        scheduler.loop(
            ["a"],
            fetcher=lambda s: {},
            interval_s=0.0,
            iterations=1,
            sleep=lambda _s: None,
            snapshot_root=history_root,
        )


def test_loop_invokes_on_tick_callback(history_root: Path) -> None:
    received: List[int] = []
    scheduler.loop(
        ["a"],
        fetcher=lambda s: {},
        interval_s=1.0,
        iterations=2,
        sleep=lambda _s: None,
        snapshot_root=history_root,
        on_tick=lambda ticks: received.append(len(ticks)),
    )
    assert received == [1, 1]
