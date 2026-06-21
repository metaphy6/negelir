"""Phase 8 §8.11 — bus circuit-breaker time-window and spool-cap tests.

The §8.11 bullet adds:
* Three consecutive failures must occur **within 30s** (fail_window_s)
  for the breaker to open.  A failure outside the window resets the
  streak counter.
* The spool cap is cfg.maint_agent_spool_max_entries (default 512),
  NOT the legacy maint_bus_spool_max_entries.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable
from uuid import uuid4

import pytest

from swarm.agents.maint._bus_circuit_breaker import (
    _STATE_CLOSED,
    _STATE_DEGRADED,
    BusCircuitBreaker,
)
from swarm.agents.topics import MAINT_EVENT
from swarm.sdk.types import Message

# ── Helpers ──────────────────────────────────────────────────────────

def _make_msg(kind: str = "scale_decision") -> Message:
    return Message.new(
        topic=MAINT_EVENT,
        payload={"kind": kind, "request_id": str(uuid4())},
        producer="maint.scaler.v1",
    )


class _FakeClock:
    """Controllable monotonic clock (seconds)."""

    def __init__(self, start: float = 0.0) -> None:
        self.t = start

    def __call__(self) -> float:
        return self.t

    def advance(self, delta: float) -> None:
        self.t += delta


def _ms_counter() -> Callable[[], int]:
    counter = [1_000_000]

    def _next() -> int:
        counter[0] += 1
        return counter[0]

    return _next


def _make_breaker(
    tmp_path: Path,
    publish_fn: Callable[[Message], None],
    fail_threshold: int = 3,
    fail_window_s: float = 30.0,
    clock_s: Callable[[], float] | None = None,
) -> BusCircuitBreaker:
    spool_dir = tmp_path / "maint.scaler.v1"
    clk: Callable[[], float] = clock_s if clock_s is not None else _FakeClock()
    return BusCircuitBreaker(
        agent_name="maint.scaler.v1",
        publish_fn=publish_fn,
        spool_dir=spool_dir,
        clock_ms=_ms_counter(),
        clock_s=clk,
        new_id=lambda: str(uuid4()),
        fail_threshold=fail_threshold,
        fail_window_s=fail_window_s,
    )


# ── Time-window tests ─────────────────────────────────────────────────

class TestFailureWindow:
    def test_three_failures_within_window_open_breaker(self, tmp_path: Path) -> None:
        """3 failures within fail_window_s → bus_degraded."""
        clock = _FakeClock(start=1000.0)

        def _fail(m: Message) -> None:
            raise RuntimeError("bus down")

        breaker = _make_breaker(tmp_path, _fail, fail_threshold=3,
                                fail_window_s=30.0, clock_s=clock)
        clock.advance(0.0)
        breaker.publish(_make_msg())   # fail 1 at t=1000
        clock.advance(5.0)
        breaker.publish(_make_msg())   # fail 2 at t=1005
        clock.advance(5.0)
        breaker.publish(_make_msg())   # fail 3 at t=1010 (all within 30s)
        assert breaker.state == _STATE_DEGRADED

    def test_failure_outside_window_resets_streak(self, tmp_path: Path) -> None:
        """A failure > fail_window_s after previous resets the streak.

        Pattern: fail, fail, wait > 30s, fail — breaker must stay closed
        because the third failure starts a fresh streak of 1.
        """
        clock = _FakeClock(start=0.0)

        def _fail(m: Message) -> None:
            raise RuntimeError("bus down")

        breaker = _make_breaker(tmp_path, _fail, fail_threshold=3,
                                fail_window_s=30.0, clock_s=clock)

        breaker.publish(_make_msg())    # fail 1 at t=0  → streak=1
        clock.advance(5.0)
        breaker.publish(_make_msg())    # fail 2 at t=5  → streak=2
        clock.advance(35.0)             # jump past the window
        breaker.publish(_make_msg())    # fail 3 at t=40 → resets, streak=1
        assert breaker.state == _STATE_CLOSED

    def test_gap_then_three_more_failures_open_breaker(self, tmp_path: Path) -> None:
        """After a reset, 3 more rapid failures must open the breaker."""
        clock = _FakeClock(start=0.0)

        def _fail(m: Message) -> None:
            raise RuntimeError("bus down")

        breaker = _make_breaker(tmp_path, _fail, fail_threshold=3,
                                fail_window_s=30.0, clock_s=clock)

        breaker.publish(_make_msg())    # fail 1 at t=0  → streak=1
        clock.advance(5.0)
        breaker.publish(_make_msg())    # fail 2 at t=5  → streak=2
        clock.advance(40.0)             # past the window

        breaker.publish(_make_msg())    # fail 1 (reset) at t=45 → streak=1
        clock.advance(2.0)
        breaker.publish(_make_msg())    # fail 2 at t=47 → streak=2
        clock.advance(2.0)
        breaker.publish(_make_msg())    # fail 3 at t=49 → streak=3 → open
        assert breaker.state == _STATE_DEGRADED

    def test_success_clears_failure_timestamp(self, tmp_path: Path) -> None:
        """A success between failures clears the streak and the timer."""
        clock = _FakeClock(start=0.0)
        calls = [0]

        def _sometimes_fail(m: Message) -> None:
            calls[0] += 1
            if calls[0] == 3:
                return   # 3rd call succeeds
            raise RuntimeError("bus down")

        breaker = _make_breaker(tmp_path, _sometimes_fail, fail_threshold=3,
                                fail_window_s=30.0, clock_s=clock)

        breaker.publish(_make_msg())    # fail 1
        clock.advance(5.0)
        breaker.publish(_make_msg())    # fail 2
        clock.advance(5.0)
        breaker.publish(_make_msg())    # success — clears streak + timer
        assert breaker.state == _STATE_CLOSED
        assert breaker._consecutive_failures == 0
        assert breaker._last_failure_ts is None


# ── Spool cap uses maint_agent_spool_max_entries (default 512) ────────

class TestSpoolCapKey:
    def test_spool_respects_agent_spool_max_entries(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The breaker must refuse new spool writes when
        cfg.maint_agent_spool_max_entries is reached."""
        from common.config import cfg

        monkeypatch.setattr(cfg, "maint_agent_spool_max_entries", 2, raising=True)

        def _fail(m: Message) -> None:
            raise RuntimeError("bus down")

        breaker = _make_breaker(tmp_path, _fail, fail_threshold=3)
        spool_dir = tmp_path / "maint.scaler.v1"

        # Open the breaker.
        for _ in range(3):
            breaker.publish(_make_msg())
        assert breaker.state == _STATE_DEGRADED

        # Spool 2 entries — cap reached.
        breaker.publish(_make_msg(kind="entry1"))
        breaker.publish(_make_msg(kind="entry2"))
        count_at_cap = len(list(spool_dir.glob("*.envelope.json")))

        # 3rd entry must be refused (cap exceeded).
        breaker.publish(_make_msg(kind="entry3"))
        count_after = len(list(spool_dir.glob("*.envelope.json")))
        assert count_after == count_at_cap, (
            "Spool grew beyond maint_agent_spool_max_entries cap"
        )

    def test_spool_cap_default_is_512(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """cfg.maint_agent_spool_max_entries default must be 512 per §8.11."""
        from common import config as _config_mod

        monkeypatch.delenv("NEGELIR_MAINT_AGENT_SPOOL_MAX_ENTRIES", raising=False)
        fresh_cfg = _config_mod.Config()
        assert fresh_cfg.maint_agent_spool_max_entries == 512, (
            f"Expected default 512, got {fresh_cfg.maint_agent_spool_max_entries}"
        )
