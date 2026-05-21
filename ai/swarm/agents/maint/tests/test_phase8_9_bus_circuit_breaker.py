"""Phase 8 §8.9 proof-tests — per-agent bus circuit-breaker.

Verifies the binding spec from ROADMAP §8.9 DoD:

* 3 consecutive bus failures flip the agent to ``bus_degraded``.
* Subsequent (non-critical) emits land in
  ``data/maint/agent_spool/maint.scaler.v1/``.
* Restoring the bus: spool drains in arrival order on the next tick.
* Critical-severity alert during outage either succeeds or triggers
  ``maint_self_isolated`` — never silently spooled.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Callable
from uuid import uuid4

import pytest

from ai.swarm.agents.maint._bus_circuit_breaker import (
    BusCircuitBreaker,
    _STATE_CLOSED,
    _STATE_DEGRADED,
)
from ai.swarm.sdk.types import Envelope, Message
from ai.swarm.agents.topics import MAINT_EVENT, SEC_ALERT


# ── Helpers ──────────────────────────────────────────────────────────

def _make_msg(kind: str = "scale_decision", severity: str | None = None) -> Message:
    payload: dict = {"kind": kind, "request_id": uuid4().hex}
    if severity is not None:
        payload["severity"] = severity
    return Message.new(
        topic=MAINT_EVENT,
        payload=payload,
        producer="maint.scaler.v1",
    )


def _make_critical_msg() -> Message:
    return _make_msg(kind="backup_failed", severity="critical")


def _ms_counter() -> Callable[[], int]:
    """Monotonic ms clock — returns distinct values each call."""
    counter = [int(time.time() * 1000)]

    def _next() -> int:
        counter[0] += 1
        return counter[0]

    return _next


def _make_breaker(
    tmp_path: Path,
    publish_fn: Callable[[Message], None],
    fail_threshold: int = 3,
) -> BusCircuitBreaker:
    spool_dir = tmp_path / "maint.scaler.v1"
    return BusCircuitBreaker(
        agent_name="maint.scaler.v1",
        publish_fn=publish_fn,
        spool_dir=spool_dir,
        clock_ms=_ms_counter(),
        new_id=lambda: uuid4().hex,
        fail_threshold=fail_threshold,
    )


# ── Tests ─────────────────────────────────────────────────────────────


class TestCircuitBreakerStateTransition:
    def test_initial_state_is_closed(self, tmp_path: Path) -> None:
        breaker = _make_breaker(tmp_path, publish_fn=lambda m: None)
        assert breaker.state == _STATE_CLOSED

    def test_two_failures_do_not_open(self, tmp_path: Path) -> None:
        calls = [0]

        def _fail(m: Message) -> None:
            calls[0] += 1
            raise RuntimeError("bus down")

        breaker = _make_breaker(tmp_path, _fail, fail_threshold=3)
        breaker.publish(_make_msg())
        breaker.publish(_make_msg())
        # Still closed after 2 failures.
        assert breaker.state == _STATE_CLOSED

    def test_three_consecutive_failures_open_breaker(self, tmp_path: Path) -> None:
        def _fail(m: Message) -> None:
            raise RuntimeError("bus down")

        breaker = _make_breaker(tmp_path, _fail, fail_threshold=3)
        for _ in range(3):
            breaker.publish(_make_msg())
        assert breaker.state == _STATE_DEGRADED

    def test_success_resets_failure_counter(self, tmp_path: Path) -> None:
        calls = [0]

        def _sometimes_fail(m: Message) -> None:
            calls[0] += 1
            # Fail twice then succeed.
            if calls[0] <= 2:
                raise RuntimeError("bus down")

        breaker = _make_breaker(tmp_path, _sometimes_fail, fail_threshold=3)
        breaker.publish(_make_msg())  # fail 1
        breaker.publish(_make_msg())  # fail 2
        breaker.publish(_make_msg())  # success — resets counter
        assert breaker.state == _STATE_CLOSED


class TestSpoolBehavior:
    def test_non_critical_emits_land_in_spool_dir(self, tmp_path: Path) -> None:
        def _fail(m: Message) -> None:
            raise RuntimeError("bus down")

        breaker = _make_breaker(tmp_path, _fail, fail_threshold=3)
        spool_dir = tmp_path / "maint.scaler.v1"

        # Open the breaker.
        for _ in range(3):
            breaker.publish(_make_msg())

        assert breaker.state == _STATE_DEGRADED
        # 4th emit (including the 3rd which also hit degraded path).
        breaker.publish(_make_msg())

        spool_files = list(spool_dir.glob("*.envelope.json"))
        assert len(spool_files) >= 1

    def test_spool_file_mode_0600(self, tmp_path: Path) -> None:
        def _fail(m: Message) -> None:
            raise RuntimeError("bus down")

        breaker = _make_breaker(tmp_path, _fail, fail_threshold=3)
        spool_dir = tmp_path / "maint.scaler.v1"

        for _ in range(4):
            breaker.publish(_make_msg())

        for f in spool_dir.glob("*.envelope.json"):
            mode = oct(os.stat(f).st_mode & 0o777)
            assert mode == oct(0o600), f"expected 0600, got {mode} for {f}"

    def test_spool_entries_are_valid_json(self, tmp_path: Path) -> None:
        def _fail(m: Message) -> None:
            raise RuntimeError("bus down")

        breaker = _make_breaker(tmp_path, _fail, fail_threshold=3)
        spool_dir = tmp_path / "maint.scaler.v1"

        for _ in range(4):
            breaker.publish(_make_msg())

        for f in sorted(spool_dir.glob("*.envelope.json")):
            data = json.loads(f.read_bytes())
            assert "envelope" in data
            assert "payload" in data

    def test_spool_filenames_ordered_by_ms_prefix(self, tmp_path: Path) -> None:
        """Spool filenames must sort in arrival order (ms-prefix guarantee)."""

        def _fail(m: Message) -> None:
            raise RuntimeError("bus down")

        breaker = _make_breaker(tmp_path, _fail, fail_threshold=3)
        spool_dir = tmp_path / "maint.scaler.v1"

        # Open the breaker first with 3 probe failures (any kind).
        for _ in range(3):
            breaker.publish(_make_msg(kind="probe"))
        assert breaker.state == _STATE_DEGRADED

        # Now spool 3 messages with distinct kinds.
        kinds = ["scale_decision", "scale_throttled", "manual_pin_expired"]
        for k in kinds:
            breaker.publish(_make_msg(kind=k))

        # The last 3 spool entries (after any probe entries) must be in order.
        entries = sorted(spool_dir.glob("*.envelope.json"))
        tail_entries = entries[-3:]
        for path, kind in zip(tail_entries, kinds):
            data = json.loads(path.read_bytes())
            assert data["payload"]["kind"] == kind, (
                f"filename {path.name} should map to kind={kind}"
            )


class TestSpoolDrain:
    def test_spool_drains_on_bus_recovery(self, tmp_path: Path) -> None:
        fail_flag = [True]
        received: list[Message] = []

        def _toggle(m: Message) -> None:
            if fail_flag[0]:
                raise RuntimeError("bus down")
            received.append(m)

        breaker = _make_breaker(tmp_path, _toggle, fail_threshold=3)
        spool_dir = tmp_path / "maint.scaler.v1"

        # Open breaker + spool 2 messages.
        for _ in range(3):
            breaker.publish(_make_msg())
        breaker.publish(_make_msg(kind="a"))
        breaker.publish(_make_msg(kind="b"))
        assert breaker.state == _STATE_DEGRADED

        # Restore bus.
        fail_flag[0] = False
        drained = breaker.tick()

        assert breaker.state == _STATE_CLOSED
        # At least "a" and "b" were drained.
        drained_kinds = [m.payload.get("kind") for m in drained]
        assert "a" in drained_kinds
        assert "b" in drained_kinds

    def test_spool_drains_in_arrival_order(self, tmp_path: Path) -> None:
        fail_flag = [True]
        received_kinds: list[str] = []

        def _toggle(m: Message) -> None:
            if fail_flag[0]:
                raise RuntimeError("bus down")
            received_kinds.append(m.payload.get("kind", ""))

        breaker = _make_breaker(tmp_path, _toggle, fail_threshold=3)

        # Open breaker.
        for _ in range(3):
            breaker.publish(_make_msg())

        # Spool 5 messages with distinct kinds.
        ordered = ["k1", "k2", "k3", "k4", "k5"]
        for k in ordered:
            breaker.publish(_make_msg(kind=k))

        # Restore and drain.
        fail_flag[0] = False
        breaker.tick()

        # The drained kinds must appear in the same order we spooled them.
        spooled_drained = [k for k in received_kinds if k in ordered]
        assert spooled_drained == ordered, (
            f"Expected {ordered}, got {spooled_drained}"
        )

    def test_spool_files_unlinked_after_successful_drain(self, tmp_path: Path) -> None:
        fail_flag = [True]

        def _toggle(m: Message) -> None:
            if fail_flag[0]:
                raise RuntimeError("bus down")

        breaker = _make_breaker(tmp_path, _toggle, fail_threshold=3)
        spool_dir = tmp_path / "maint.scaler.v1"

        for _ in range(4):
            breaker.publish(_make_msg())

        pre_drain = list(spool_dir.glob("*.envelope.json"))
        assert len(pre_drain) > 0

        fail_flag[0] = False
        breaker.tick()

        remaining = list(spool_dir.glob("*.envelope.json"))
        assert remaining == [], f"Expected empty spool, found {remaining}"

    def test_tick_noop_when_closed(self, tmp_path: Path) -> None:
        breaker = _make_breaker(tmp_path, publish_fn=lambda m: None)
        result = breaker.tick()
        assert result == []


class TestCriticalAlertHandling:
    def test_critical_alert_succeeds_when_bus_up(self, tmp_path: Path) -> None:
        """In bus_degraded state: if the direct publish of a critical alert
        succeeds, no extra messages are returned."""
        fail_flag = [True]
        received: list[Message] = []

        def _publish(m: Message) -> None:
            if fail_flag[0]:
                # Normal emits fail; critical gets special path — allow it.
                if not (m.payload or {}).get("severity") == "critical":
                    raise RuntimeError("bus down")
            received.append(m)

        breaker = _make_breaker(tmp_path, _publish, fail_threshold=3)
        # Open breaker.
        for _ in range(3):
            breaker.publish(_make_msg())
        assert breaker.state == _STATE_DEGRADED

        # Critical alert — bus accepts it.
        fail_flag[0] = False  # bus back up for critical
        extra = breaker.publish(_make_critical_msg())
        assert extra == []
        critical_received = [m for m in received if (m.payload or {}).get("severity") == "critical"]
        assert len(critical_received) == 1

    def test_critical_alert_triggers_maint_self_isolated_on_failure(
        self, tmp_path: Path
    ) -> None:
        """When bus is down AND critical alert fails, maint_self_isolated is
        returned — the critical message is never silently spooled."""
        spool_dir = tmp_path / "maint.scaler.v1"

        def _always_fail(m: Message) -> None:
            raise RuntimeError("bus down")

        breaker = _make_breaker(tmp_path, _always_fail, fail_threshold=3)
        # Open breaker.
        for _ in range(3):
            breaker.publish(_make_msg())
        assert breaker.state == _STATE_DEGRADED

        # Critical alert — also fails.
        extra = breaker.publish(_make_critical_msg())
        assert len(extra) == 1
        payload = extra[0].payload or {}
        assert payload.get("kind") == "maint_self_isolated"
        assert payload.get("severity") == "critical"

        # Original critical message must NOT be in the spool.
        spool_files = list(spool_dir.glob("*.envelope.json"))
        for f in spool_files:
            data = json.loads(f.read_bytes())
            assert data["payload"].get("kind") != "backup_failed", (
                "Critical message must not be silently spooled"
            )

    def test_self_isolated_flag_set_on_critical_failure(self, tmp_path: Path) -> None:
        def _always_fail(m: Message) -> None:
            raise RuntimeError("bus down")

        breaker = _make_breaker(tmp_path, _always_fail, fail_threshold=3)
        for _ in range(3):
            breaker.publish(_make_msg())

        assert not breaker.self_isolated
        breaker.publish(_make_critical_msg())
        assert breaker.self_isolated

    def test_self_isolated_cleared_on_recovery(self, tmp_path: Path) -> None:
        fail_flag = [True]

        def _toggle(m: Message) -> None:
            if fail_flag[0]:
                raise RuntimeError("bus down")

        breaker = _make_breaker(tmp_path, _toggle, fail_threshold=3)
        for _ in range(3):
            breaker.publish(_make_msg())
        breaker.publish(_make_critical_msg())
        assert breaker.self_isolated

        fail_flag[0] = False
        breaker.tick()
        assert not breaker.self_isolated
