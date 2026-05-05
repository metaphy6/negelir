"""Phase 8 §8.15.1 + §8.10 — clock + leader Protocol unit tests."""
from __future__ import annotations

import time

import pytest

from swarm.sdk.clock import (
    CLOCK_SOURCE_AUTO,
    CLOCK_SOURCE_MONOTONIC,
    resolve_clock,
    window_anchor_ns,
)
from swarm.sdk.leader import SingleProcessLeader


def test_resolve_clock_auto_returns_callable() -> None:
    source, fn = resolve_clock(CLOCK_SOURCE_AUTO)
    assert source in ("boottime", "monotonic")
    a, b = fn(), fn()
    assert isinstance(a, int) and isinstance(b, int)
    assert b >= a


def test_resolve_clock_monotonic_pinned() -> None:
    source, fn = resolve_clock(CLOCK_SOURCE_MONOTONIC)
    assert source == "monotonic"
    assert fn() > 0


def test_resolve_clock_unknown_raises() -> None:
    with pytest.raises(ValueError):
        resolve_clock("wallclock")


def test_window_anchor_quantizes_monotonically() -> None:
    win_ms = 1000
    a = window_anchor_ns(win_ms, now_ns=5_500_000_000)
    b = window_anchor_ns(win_ms, now_ns=5_999_999_999)
    c = window_anchor_ns(win_ms, now_ns=6_000_000_000)
    assert a == b
    assert c > a
    assert c - a == 1_000_000_000


def test_window_anchor_zero_window_rejected() -> None:
    with pytest.raises(ValueError):
        window_anchor_ns(0)


def test_single_process_leader_default_is_leader() -> None:
    leader = SingleProcessLeader(name="maint.scaler.v1")
    assert leader.is_leader() is True
    assert leader.name == "maint.scaler.v1"


def test_single_process_leader_shed_then_reacquire() -> None:
    leader = SingleProcessLeader(name="maint.dlq.v1")
    leader.shed()
    assert leader.is_leader() is False
    leader.reacquire()
    assert leader.is_leader() is True
