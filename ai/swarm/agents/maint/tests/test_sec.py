"""Phase 8 §8.7 + §8.8 — `maint.sec.v1` smoke tests."""
from __future__ import annotations

from datetime import datetime, timezone

from common.config import cfg as _cfg

from swarm.agents.maint.sec import (
    InMemoryDecimator,
    InMemoryPatternStore,
    MaintSecAgent,
)
from swarm.agents.topics import MAINT_ACK, MAINT_EVENT, SEC_ALERT
from swarm.sdk.types import Envelope, Message


def _wrap(payload: dict) -> Message:
    env = Envelope(
        message_id="m1",
        trace_id="t1",
        topic=MAINT_EVENT,
        producer="ops_console",
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        schema_version=1,
        attempt=1,
    )
    return Message(envelope=env, payload=payload)


def test_subscribes_publishes() -> None:
    a = MaintSecAgent()
    assert a.name == "maint.sec.v1"
    assert MAINT_EVENT in a.subscribes
    assert MAINT_ACK in a.publishes


def test_quarantine_clear_promotes_pattern() -> None:
    store = InMemoryPatternStore()
    agent = MaintSecAgent(pattern_store=store)
    out = list(agent.handle(_wrap({
        "kind": "quarantine_clear",
        "request_id": "req-001",
        "client_id": "ops",
        "target": "qid:abc123",
        "produced_at": "2024-01-01T00:00:00+00:00",
        "reason": "false positive",
        "details": {"pattern": "/* SAFE_QUERY */"},
    })))
    kinds = [m.payload.get("kind") for m in out]
    assert "pattern_allowlist_pending" in kinds
    assert "pattern_allowlist_added" in kinds
    assert any(m.envelope.topic == MAINT_ACK for m in out)


def test_quarantine_clear_dedup() -> None:
    agent = MaintSecAgent()
    msg = _wrap({
        "kind": "quarantine_clear",
        "request_id": "req-002",
        "client_id": "ops",
        "target": "qid:abc",
        "produced_at": "2024-01-01T00:00:00+00:00",
        "reason": "fp",
        "details": {"pattern": "p1"},
    })
    list(agent.handle(msg))
    out2 = list(agent.handle(msg))
    # On dedup we ack but emit no further notifications.
    kinds = [m.payload.get("kind") for m in out2 if m.envelope.topic == MAINT_EVENT]
    assert kinds == []


def test_quarantine_clear_no_pattern_acks_noop() -> None:
    agent = MaintSecAgent()
    out = list(agent.handle(_wrap({
        "kind": "quarantine_clear",
        "request_id": "req-003",
        "client_id": "ops",
        "target": "qid:x",
        "produced_at": "2024-01-01T00:00:00+00:00",
        "reason": "fp",
    })))
    acks = [m for m in out if m.envelope.topic == MAINT_ACK]
    assert acks and acks[0].payload["accepted"] is True


def test_denylist_decimate_emits_summary() -> None:
    decimator = InMemoryDecimator(entries={f"k{i}": float(i) for i in range(50)})
    agent = MaintSecAgent(decimator=decimator)
    out = list(agent.handle(_wrap({
        "kind": "denylist_decimate_now",
        "request_id": "req-004",
        "client_id": "ops",
        "target": "all",
        "produced_at": "2024-01-01T00:00:00+00:00",
        "reason": "manual",
    })))
    kinds = [m.payload.get("kind") for m in out if m.envelope.topic == MAINT_EVENT]
    assert "denylist_decimate" in kinds


def test_unrelated_kind_ignored() -> None:
    agent = MaintSecAgent()
    out = list(agent.handle(_wrap({"kind": "scale_decision"})))
    assert out == []


# ── Phase 8 §8.8 hysteresis + decile-boundary + alert path ──────────
def _alert_msg(payload: dict) -> Message:
    env = Envelope(
        message_id="ma1",
        trace_id="ta1",
        topic=SEC_ALERT,
        producer="sec.rate.v1",
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        schema_version=1,
        attempt=1,
    )
    return Message(envelope=env, payload=payload)


def test_subscribes_to_sec_alert_for_growth_anomaly() -> None:
    a = MaintSecAgent()
    assert SEC_ALERT in a.subscribes


def test_decimate_hysteresis_blocks_back_to_back_calls() -> None:
    """§8.8 binding: at most one decimate per
    cfg.maint_sec_decimate_min_interval_s globally. Second call within
    the window acks accepted=true, reason='hysteresis_throttled' and
    emits 'denylist_decimate_throttled' (no actual eviction)."""
    decimator = InMemoryDecimator(
        entries={f"k{i}": float(i) for i in range(50)}
    )
    clock = {"ms": 1_700_000_000_000}
    agent = MaintSecAgent(decimator=decimator, clock_ms=lambda: clock["ms"])
    cap = int(_cfg.sec_denylist_max_entries)
    # Force a real eviction on the first call by sizing entries
    # above cap (the InMemoryDecimator no-ops when len <= cap; we
    # override cap via a smaller decimator population check by
    # raising entries count beyond cap — for the in-memory shim
    # cap=sec_denylist_max_entries default 250000; the test
    # populates only 50 entries so the first call is itself a
    # no-op. Instead, use a tiny decimator wrapper that always
    # reports an eviction so we exercise the gate transition.
    class _AlwaysEvictsDecimator:
        def __init__(self) -> None:
            self.calls = 0

        def cardinality(self) -> int:
            return 100

        def decimate(self, *, now_ms: int, cap: int) -> dict:
            self.calls += 1
            return {
                "evicted_count": 5,
                "decile_size": 5,
                "new_zcard": 95,
                "cap_cleared": False,
            }

    drv = _AlwaysEvictsDecimator()
    agent = MaintSecAgent(decimator=drv, clock_ms=lambda: clock["ms"])

    # First call: real decimate.
    out1 = list(agent.handle(_wrap({
        "kind": "denylist_decimate_now",
        "request_id": "req-h1",
        "target": "all",
    })))
    ack1 = [m for m in out1 if m.envelope.topic == MAINT_ACK][0]
    assert ack1.payload["accepted"] is True
    assert ack1.payload["reason"] == "decimated"
    assert drv.calls == 1

    # Second call inside the window: throttled, no second decimate.
    clock["ms"] += 1000  # 1s elapsed; default window is 300s
    out2 = list(agent.handle(_wrap({
        "kind": "denylist_decimate_now",
        "request_id": "req-h2",
        "target": "all",
    })))
    ack2 = [m for m in out2 if m.envelope.topic == MAINT_ACK][0]
    assert ack2.payload["accepted"] is True
    assert ack2.payload["reason"] == "hysteresis_throttled"
    assert "cooldown_ms" in (ack2.payload.get("details") or {})
    kinds2 = [m.payload.get("kind") for m in out2
              if m.envelope.topic == MAINT_EVENT]
    assert "denylist_decimate_throttled" in kinds2
    assert "denylist_decimate" not in kinds2
    assert drv.calls == 1  # no second eviction

    # After the window expires, decimate runs again.
    clock["ms"] += int(_cfg.maint_sec_decimate_min_interval_s) * 1000 + 1
    out3 = list(agent.handle(_wrap({
        "kind": "denylist_decimate_now",
        "request_id": "req-h3",
        "target": "all",
    })))
    ack3 = [m for m in out3 if m.envelope.topic == MAINT_ACK][0]
    assert ack3.payload["reason"] == "decimated"
    assert drv.calls == 2


def test_decimate_noop_does_not_arm_hysteresis() -> None:
    """A decimate call that evicts 0 entries (ZCARD <= cap) leaves
    the hysteresis gate open so the *next* alert during real
    pressure is not silently swallowed."""
    decimator = InMemoryDecimator(entries={"k0": 0.0})  # 1 entry, cap is huge
    clock = {"ms": 1_700_000_000_000}
    agent = MaintSecAgent(decimator=decimator, clock_ms=lambda: clock["ms"])
    list(agent.handle(_wrap({
        "kind": "denylist_decimate_now",
        "request_id": "req-n1",
        "target": "all",
    })))
    assert agent._last_decimate_ms == 0  # noqa: SLF001 — boundary


def test_decimate_decile_boundary_zcard_below_ten() -> None:
    """ZCARD<10 ⇒ decile_size=1 (still meaningful). ROADMAP §8.8."""
    decimator = InMemoryDecimator(entries={f"k{i}": float(i) for i in range(5)})
    # Force the cap below cardinality so the shim actually runs.
    res = decimator.decimate(now_ms=0, cap=2)
    assert res["decile_size"] == 1
    assert res["evicted_count"] == 1


def test_decimate_decile_boundary_zcard_zero_is_noop() -> None:
    """ZCARD==0 ⇒ no-op, evicted_count=0, decile_size=0,
    cap_cleared=False. ROADMAP §8.8 ('alert was spurious; agent
    records and debounces')."""
    decimator = InMemoryDecimator(entries={})
    res = decimator.decimate(now_ms=0, cap=10)
    assert res == {
        "evicted_count": 0,
        "decile_size": 0,
        "new_zcard": 0,
        "cap_cleared": False,
    }


def test_sec_alert_growth_anomaly_triggers_decimate() -> None:
    """Sec.alert.v1{kind=denylist_growth_anomaly, severity=critical}
    must drive an automatic decimate on the maint.sec agent."""

    class _AlwaysEvictsDecimator:
        def __init__(self) -> None:
            self.calls = 0

        def cardinality(self) -> int:
            return 100

        def decimate(self, *, now_ms: int, cap: int) -> dict:
            self.calls += 1
            return {"evicted_count": 5, "decile_size": 5,
                    "new_zcard": 95, "cap_cleared": False}

    drv = _AlwaysEvictsDecimator()
    clock = {"ms": 1_700_000_000_000}
    agent = MaintSecAgent(decimator=drv, clock_ms=lambda: clock["ms"])
    out = list(agent.handle(_alert_msg({
        "alert_id": "a1",
        "kind": "denylist_growth_anomaly",
        "severity": "critical",
        "source": "sec.rate.v1",
        "subject": "10.0.0.0/24",
        "reason": "rejected_capped",
        "produced_at": "2024-01-01T00:00:00+00:00",
    })))
    assert drv.calls == 1
    notif_kinds = [m.payload.get("kind") for m in out
                   if m.envelope.topic == MAINT_EVENT]
    assert "denylist_decimate" in notif_kinds
    # No ack on the alert path (no request_id from sec.rate.v1).
    assert all(m.envelope.topic != MAINT_ACK for m in out)


def test_sec_alert_dedup_by_alert_id() -> None:
    """Same alert_id arriving twice (bus redelivery) decimates
    once."""
    class _CountingDecimator:
        def __init__(self) -> None:
            self.calls = 0

        def cardinality(self) -> int:
            return 100

        def decimate(self, *, now_ms: int, cap: int) -> dict:
            self.calls += 1
            return {"evicted_count": 1, "decile_size": 1,
                    "new_zcard": 99, "cap_cleared": False}

    drv = _CountingDecimator()
    agent = MaintSecAgent(decimator=drv,
                          clock_ms=lambda: 1_700_000_000_000)
    msg = _alert_msg({
        "alert_id": "dup-1",
        "kind": "denylist_growth_anomaly",
        "severity": "critical",
        "source": "sec.rate.v1",
        "subject": "1.2.3.4",
        "reason": "rejected_capped",
        "produced_at": "2024-01-01T00:00:00+00:00",
    })
    list(agent.handle(msg))
    list(agent.handle(msg))
    assert drv.calls == 1


def test_sec_alert_non_critical_is_ignored() -> None:
    """Severity=warn growth-anomaly does NOT trigger automatic
    decimate (the policy is critical-only per ROADMAP §8.8)."""
    class _CountingDecimator:
        def __init__(self) -> None:
            self.calls = 0

        def cardinality(self) -> int:
            return 100

        def decimate(self, *, now_ms: int, cap: int) -> dict:
            self.calls += 1
            return {"evicted_count": 1, "decile_size": 1,
                    "new_zcard": 99, "cap_cleared": False}

    drv = _CountingDecimator()
    agent = MaintSecAgent(decimator=drv,
                          clock_ms=lambda: 1_700_000_000_000)
    list(agent.handle(_alert_msg({
        "alert_id": "warn-1",
        "kind": "denylist_growth_anomaly",
        "severity": "warn",
        "source": "sec.rate.v1",
        "subject": "1.2.3.4",
        "reason": "rejected_capped",
        "produced_at": "2024-01-01T00:00:00+00:00",
    })))
    assert drv.calls == 0


# ── §8.9 idempotency/hysteresis: parallel triggers collapse to one call ──

def test_decimate_hysteresis_parallel_operator_then_alert() -> None:
    """ROADMAP §8.9 idempotency: operator trigger fires first, then a
    sec.alert.v1 arrives within min_interval_s — both share the same
    _last_decimate_ms gate so the alert path is throttled.  Total
    decimator.decimate() calls == 1."""

    class _CountingDecimator:
        def __init__(self) -> None:
            self.calls = 0

        def cardinality(self) -> int:
            return 100

        def decimate(self, *, now_ms: int, cap: int) -> dict:
            self.calls += 1
            return {"evicted_count": 5, "decile_size": 5,
                    "new_zcard": 95, "cap_cleared": False}

    clock = {"ms": 1_700_000_000_000}
    drv = _CountingDecimator()
    agent = MaintSecAgent(decimator=drv, clock_ms=lambda: clock["ms"])

    # Trigger 1: operator command → real eviction, gate armed.
    out_op = list(agent.handle(_wrap({
        "kind": "denylist_decimate_now",
        "request_id": "req-par-op",
        "target": "all",
    })))
    ack_op = [m for m in out_op if m.envelope.topic == MAINT_ACK][0]
    assert ack_op.payload["reason"] == "decimated"
    assert drv.calls == 1

    # Trigger 2: alert fires inside the window (1 s elapsed).
    clock["ms"] += 1000
    out_alert = list(agent.handle(_alert_msg({
        "alert_id": "a-par-1",
        "kind": "denylist_growth_anomaly",
        "severity": "critical",
        "source": "sec.rate.v1",
        "subject": "10.0.0.0/24",
        "reason": "rejected_capped",
        "produced_at": "2024-01-01T00:00:00+00:00",
    })))
    # Alert path must be throttled — no second decimate.
    notif_kinds = [m.payload.get("kind") for m in out_alert
                   if m.envelope.topic == MAINT_EVENT]
    assert "denylist_decimate_throttled" in notif_kinds
    assert "denylist_decimate" not in notif_kinds
    assert drv.calls == 1  # still one call total


def test_decimate_hysteresis_parallel_alert_then_operator() -> None:
    """ROADMAP §8.9 idempotency: alert path fires first, then an
    operator command arrives within min_interval_s — operator path is
    throttled.  Total decimator.decimate() calls == 1."""

    class _CountingDecimator:
        def __init__(self) -> None:
            self.calls = 0

        def cardinality(self) -> int:
            return 100

        def decimate(self, *, now_ms: int, cap: int) -> dict:
            self.calls += 1
            return {"evicted_count": 5, "decile_size": 5,
                    "new_zcard": 95, "cap_cleared": False}

    clock = {"ms": 1_700_000_000_000}
    drv = _CountingDecimator()
    agent = MaintSecAgent(decimator=drv, clock_ms=lambda: clock["ms"])

    # Trigger 1: alert → real eviction, gate armed.
    out_alert = list(agent.handle(_alert_msg({
        "alert_id": "a-par-2",
        "kind": "denylist_growth_anomaly",
        "severity": "critical",
        "source": "sec.rate.v1",
        "subject": "10.0.0.0/24",
        "reason": "rejected_capped",
        "produced_at": "2024-01-01T00:00:00+00:00",
    })))
    notif_kinds_1 = [m.payload.get("kind") for m in out_alert
                     if m.envelope.topic == MAINT_EVENT]
    assert "denylist_decimate" in notif_kinds_1
    assert drv.calls == 1

    # Trigger 2: operator command inside the window (1 s elapsed).
    clock["ms"] += 1000
    out_op = list(agent.handle(_wrap({
        "kind": "denylist_decimate_now",
        "request_id": "req-par-op2",
        "target": "all",
    })))
    ack_op = [m for m in out_op if m.envelope.topic == MAINT_ACK][0]
    assert ack_op.payload["reason"] == "hysteresis_throttled"
    notif_kinds_2 = [m.payload.get("kind") for m in out_op
                     if m.envelope.topic == MAINT_EVENT]
    assert "denylist_decimate_throttled" in notif_kinds_2
    assert "denylist_decimate" not in notif_kinds_2
    assert drv.calls == 1  # still one call total


def test_decimate_hysteresis_two_simultaneous_alerts_collapse() -> None:
    """ROADMAP §8.9 idempotency: two alerts arrive at the same clock_ms
    (truly parallel in a bus-redelivery scenario) — because alert_id
    dedup fires for the second identical alert, or the hysteresis gate
    blocks a second distinct alert_id within the window.  Either way,
    exactly one decimator call is made."""

    class _CountingDecimator:
        def __init__(self) -> None:
            self.calls = 0

        def cardinality(self) -> int:
            return 100

        def decimate(self, *, now_ms: int, cap: int) -> dict:
            self.calls += 1
            return {"evicted_count": 5, "decile_size": 5,
                    "new_zcard": 95, "cap_cleared": False}

    clock = {"ms": 1_700_000_000_000}
    drv = _CountingDecimator()
    agent = MaintSecAgent(decimator=drv, clock_ms=lambda: clock["ms"])

    # Two distinct alert_ids at the same millisecond (parallel arrival).
    for aid in ("a-sim-1", "a-sim-2"):
        list(agent.handle(_alert_msg({
            "alert_id": aid,
            "kind": "denylist_growth_anomaly",
            "severity": "critical",
            "source": "sec.rate.v1",
            "subject": "10.0.0.0/24",
            "reason": "rejected_capped",
            "produced_at": "2024-01-01T00:00:00+00:00",
        })))

    # First alert decimates; second alert is blocked by hysteresis
    # (same clock_ms → elapsed_ms == 0 < window_ms).
    assert drv.calls == 1
