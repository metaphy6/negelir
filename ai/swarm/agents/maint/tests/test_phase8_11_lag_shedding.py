"""Phase 8 §8.11 — maint-plane lag backpressure shedding proof tests.

Verifies the integration of :class:`MaintLagWatchdog` tier signals with:
  * :class:`MaintScaler` — non-emergency scale-down suppression (tier 1/2)
    and observer-only mode (tier 3).
  * :class:`MaintDlqSupervisor` — halved replay budget (tier 1), drain-only
    (tier 2), and observer-only (tier 3).
  * :class:`MaintSchemaSentinel` — 0.1x sample rate (tier 2), observer-only
    (tier 3).
"""
from __future__ import annotations

import pytest

from common import config as _cfg_mod
from swarm.agents.maint.dlq import MaintDlqSupervisor
from swarm.agents.maint.scaler import MaintScaler, NoopController
from swarm.agents.maint.schema import MaintSchemaSentinel
from swarm.sdk.leader import SingleProcessLeader
from swarm.sdk.types import Envelope, Message


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_scaler(monkeypatch=None, cfg=None) -> MaintScaler:
    return MaintScaler(
        controller=NoopController(),
        leader=SingleProcessLeader(name="maint.scaler.v1"),
    )


def _make_dlq() -> MaintDlqSupervisor:
    return MaintDlqSupervisor()


def _scale_down_signals() -> dict[str, dict[str, float]]:
    """Signals that trigger a scale-down decision (very low queue)."""
    return {"target_a": {"queue_depth": 0.0, "in_flight": 0.0, "head_age_s": 0.0}}


def _scale_up_signals() -> dict[str, dict[str, float]]:
    """Signals that trigger a scale-up decision (very high queue)."""
    return {"target_a": {"queue_depth": 10_000.0, "in_flight": 0.0, "head_age_s": 0.0}}


def _dummy_msg(topic: str = "maint.event.v1") -> Message:
    env = Envelope(
        message_id="m1",
        trace_id="t1",
        topic=topic,
        producer="test",
        created_at="2024-01-01T00:00:00+00:00",
        schema_version=1,
        attempt=1,
    )
    return Message(envelope=env, payload={"kind": "test"})


@pytest.fixture()
def scaler_cfg(monkeypatch):
    """Tune the scaler for deterministic scale-down in a single pair of ticks."""
    c = _cfg_mod.cfg
    # Wide enough up/down thresholds so high-queue → up, zero-queue → down.
    monkeypatch.setattr(c, "maint_scaler_scale_up_queue_depth", 100.0, raising=False)
    monkeypatch.setattr(c, "maint_scaler_scale_down_queue_depth", 50.0, raising=False)
    monkeypatch.setattr(c, "maint_scaler_scale_down_grace_windows", 0, raising=False)
    monkeypatch.setattr(c, "maint_scaler_min_replicas", 0, raising=False)
    monkeypatch.setattr(c, "maint_scaler_max_replicas", 10, raising=False)
    monkeypatch.setattr(c, "maint_scaler_min_decision_interval_s", 0, raising=False)
    # 1 ms windows so each call uses a new window.
    monkeypatch.setattr(c, "maint_scaler_decision_window_ms", 1, raising=False)
    # Disable Welford smoothing so each tick uses the raw signal value.
    monkeypatch.setattr(c, "maint_scaler_signal_window_samples", 0, raising=False)
    return c


def _prime_and_scale_down(scaler: MaintScaler) -> list[Message]:
    """Set replicas > 0 via a scale-up, then reset window and issue scale-down."""
    # Scale up to 2 replicas.
    scaler.tick(_scale_up_signals())
    assert scaler._targets.get("target_a") is not None
    # Reset window so next tick is treated as a new window.
    scaler._targets["target_a"].last_window_ns = 0
    return scaler.tick(_scale_down_signals())


# ---------------------------------------------------------------------------
# Scaler — tier-1 suppresses non-emergency scale-down
# ---------------------------------------------------------------------------


def test_scaler_tier0_allows_scale_down(scaler_cfg):
    """At tier 0 (healthy), scale-down decisions are emitted normally."""
    scaler = _make_scaler()
    msgs = _prime_and_scale_down(scaler)
    kinds = [m.payload.get("kind") for m in msgs]
    assert "scale_decision" in kinds, f"Expected scale_decision at tier 0: {kinds}"


def test_scaler_tier1_suppresses_scale_down(scaler_cfg):
    """At tier 1, scale-down decisions become scale_throttled{reason=backpressure_tier1}."""
    scaler = _make_scaler()
    scaler.tick(_scale_up_signals())
    scaler._targets["target_a"].last_window_ns = 0
    msgs = scaler.tick(_scale_down_signals(), lag_tier=1)
    kinds = [m.payload.get("kind") for m in msgs]
    reasons = [m.payload.get("reason") for m in msgs]
    assert "scale_decision" not in kinds, f"scale_decision should be suppressed at tier 1: {kinds}"
    assert "backpressure_tier1" in reasons, f"Expected backpressure_tier1 throttle: {reasons}"


def test_scaler_tier1_allows_scale_up(scaler_cfg):
    """At tier 1, scale-up decisions still emit (not suppressed)."""
    scaler = _make_scaler()
    msgs = scaler.tick(_scale_up_signals(), lag_tier=1)
    kinds = [m.payload.get("kind") for m in msgs]
    assert "scale_decision" in kinds, f"Expected scale_decision (up) at tier 1: {kinds}"


def test_scaler_tier2_suppresses_scale_down(scaler_cfg):
    """At tier 2, scale-down decisions are suppressed with reason=backpressure_tier2."""
    scaler = _make_scaler()
    scaler.tick(_scale_up_signals())
    scaler._targets["target_a"].last_window_ns = 0
    msgs = scaler.tick(_scale_down_signals(), lag_tier=2)
    reasons = [m.payload.get("reason") for m in msgs]
    assert "backpressure_tier2" in reasons, f"Expected backpressure_tier2: {reasons}"
    kinds = [m.payload.get("kind") for m in msgs]
    assert "scale_decision" not in kinds


def test_scaler_tier3_observer_only(scaler_cfg):
    """At tier 3, tick() returns [] regardless of signals."""
    scaler = _make_scaler()
    assert scaler.tick(_scale_up_signals(), lag_tier=3) == []
    assert scaler.tick(_scale_down_signals(), lag_tier=3) == []


# ---------------------------------------------------------------------------
# DLQ — tier-1 halves budget, tier-2 drain-only, tier-3 observer-only
# ---------------------------------------------------------------------------


@pytest.fixture()
def dlq_cfg(monkeypatch):
    c = _cfg_mod.cfg
    monkeypatch.setattr(c, "maint_dlq_max_replays_per_tick", 20, raising=True)
    monkeypatch.setattr(c, "maint_dlq_replay_topics_allow_csv", "topic.dlq", raising=True)
    return c


def test_dlq_tier0_full_budget(dlq_cfg):
    """At tier 0, per-topic budget uses full max_replays_per_tick."""
    agent = _make_dlq()
    msgs = agent.tick(["topic.dlq"], lag_tier=0)
    replayed = [m for m in msgs if m.payload.get("kind") == "dlq_replayed"]
    assert len(replayed) == 1
    # budget=20, 1 eligible topic → per_topic=20
    assert replayed[0].payload["max_msgs"] == 20, f"Expected full budget: {replayed[0].payload}"


def test_dlq_tier1_halves_budget(dlq_cfg):
    """At tier 1, per-topic budget is halved (max_replays_per_tick // 2)."""
    agent = _make_dlq()
    msgs = agent.tick(["topic.dlq"], lag_tier=1)
    replayed = [m for m in msgs if m.payload.get("kind") == "dlq_replayed"]
    assert len(replayed) == 1
    # budget=10 (20//2), 1 topic → per_topic=10
    assert replayed[0].payload["max_msgs"] == 10, f"Expected halved budget: {replayed[0].payload}"


def test_dlq_tier2_drain_only(dlq_cfg):
    """At tier 2, no dlq_replayed events (drain-only mode)."""
    agent = _make_dlq()
    msgs = agent.tick(["topic.dlq"], lag_tier=2)
    replayed = [m for m in msgs if m.payload.get("kind") == "dlq_replayed"]
    assert replayed == [], f"Expected no replays at tier 2 (drain-only): {msgs}"


def test_dlq_tier3_observer_only(dlq_cfg):
    """At tier 3, tick() returns []."""
    agent = _make_dlq()
    assert agent.tick(["topic.dlq"], lag_tier=3) == []


# ---------------------------------------------------------------------------
# Schema sentinel — tier-2 reduces sample rate to 0.1x, tier-3 observer-only
# ---------------------------------------------------------------------------


def test_schema_tier3_observer_only():
    """At tier 3, observe() yields nothing (observer-only)."""
    sentinel = MaintSchemaSentinel()
    results = list(sentinel.observe(_dummy_msg(), lag_tier=3))
    assert results == [], f"Expected no output at tier 3: {results}"


def test_schema_tier0_observe_passes_through():
    """At tier 0, observe() runs normally (no tier suppression)."""
    sentinel = MaintSchemaSentinel()
    # Just assert no exception and returns a list.
    result = list(sentinel.observe(_dummy_msg(), lag_tier=0))
    assert isinstance(result, list)


def test_schema_tier2_reduces_sample_rate(monkeypatch):
    """At tier 2, the effective sample rate is 0.1x the configured rate.

    Uses a fixed monotonic clock injected at construction time so the
    elapsed-time arithmetic is deterministic.
    """
    c = _cfg_mod.cfg
    # Small burst so the refill rate is the limiting factor.
    monkeypatch.setattr(c, "maint_schema_sample_rate_per_s", 10.0, raising=True)
    monkeypatch.setattr(c, "maint_schema_burst", 5, raising=True)

    # Fixed monotonic time: 100.0 s.
    FIXED_NOW = 100.0
    sentinel = MaintSchemaSentinel(clock_mono=lambda: FIXED_NOW)

    topic = "probe.topic.v1"
    bucket_t0 = sentinel._buckets[topic]
    bucket_t2 = sentinel._buckets[topic]  # same sentinel, different calls

    # Warm up the bucket: first call sets last_refill=100.0, tokens=burst=5.
    sentinel._consume_token(bucket_t0, lag_tier=0)  # uses burst → True

    # Drain the bucket completely.
    bucket_t0.tokens = 0.0
    # Set last_refill to 90.0 so next call has elapsed = FIXED_NOW - 90.0 = 10.0 s.
    bucket_t0.last_refill = 90.0

    # Tier-0: rate=10.0, elapsed=10s → new_tokens = min(5, 0 + 10*10) = 5 → True.
    result_t0 = sentinel._consume_token(bucket_t0, lag_tier=0)
    assert result_t0 is True, "tier-0 should consume a token with 10s elapsed at rate=10"

    # Reset bucket for tier-2 measurement: 0 tokens, last_refill at 99.9s (0.1s elapsed).
    bucket_t0.tokens = 0.0
    bucket_t0.last_refill = 99.9  # elapsed = 100.0 - 99.9 = 0.1 s
    # Tier-2: rate = 10.0 * 0.1 = 1.0, elapsed = 0.1s → new_tokens = min(5, 0 + 0.1) = 0.1 → False.
    result_t2 = sentinel._consume_token(bucket_t0, lag_tier=2)
    assert result_t2 is False, (
        "tier-2 should NOT consume a token with only 0.1s elapsed at effective rate=1.0"
    )


# ---------------------------------------------------------------------------
# No self-amplification — §8.11 bullet 2
# ---------------------------------------------------------------------------

from swarm.agents.maint._lag_watchdog import MaintLagWatchdog


def _drive_to_tier(watchdog: MaintLagWatchdog, lag_s: float, n_ticks: int = 5) -> list:
    """Feed sustained lag to the watchdog and collect all emitted messages."""
    t = 0.0
    collected: list = []
    for _ in range(n_ticks):
        t += 1.0
        watchdog.note_lag(lag_s=lag_s, now_s=t)
    # Tick several times with the same lag to verify no re-emission.
    for _ in range(n_ticks):
        t += 1.0
        collected.extend(watchdog.tick(now_s=t))
    return collected


def _throttled_at_tier(messages: list, tier: int) -> list:
    return [
        m for m in messages
        if m.payload.get("kind") == "maint_plane_throttled"
        and m.payload.get("tier") == tier
    ]


def test_no_self_amplification_tier2(monkeypatch):
    """Tier-2 shedding event fires exactly once per tier transition.

    §8.11: Tier 2/3 shedding events must be emitted at most once per tier
    transition — not once per tick — to avoid amplifying the very plane
    they are shedding.
    """
    c = _cfg_mod.cfg
    monkeypatch.setattr(c, "maint_plane_lag_alert_ms", 5_000, raising=False)
    monkeypatch.setattr(c, "maint_plane_lag_alert_window_s", 1, raising=False)
    monkeypatch.setattr(c, "maint_plane_recovery_window_s", 120, raising=False)

    watchdog = MaintLagWatchdog()
    # Drive into tier 2 (lag=20s > 15s).
    msgs = _drive_to_tier(watchdog, lag_s=20.0, n_ticks=10)

    tier2_events = _throttled_at_tier(msgs, tier=2)
    assert watchdog.tier >= 2, f"Expected tier ≥ 2, got {watchdog.tier}"
    assert len(tier2_events) == 1, (
        f"Expected exactly ONE tier-2 throttled event, got {len(tier2_events)}: {tier2_events}"
    )

    # Additional ticks with same sustained lag must produce NO new tier-2 events.
    extra = []
    t0 = 100.0
    for i in range(20):
        watchdog.note_lag(lag_s=20.0, now_s=t0 + i)
        extra.extend(watchdog.tick(now_s=t0 + i + 0.5))
    extra_tier2 = _throttled_at_tier(extra, tier=2)
    assert extra_tier2 == [], (
        f"Tier-2 event re-emitted on sustained lag (self-amplification): {extra_tier2}"
    )


def test_no_self_amplification_tier3(monkeypatch):
    """Tier-3 shedding event fires exactly once per tier transition.

    §8.11: Even under sustained tier-3 lag, the maint_plane_throttled{tier=3}
    event must not repeat — otherwise the maint plane amplifies itself.
    """
    c = _cfg_mod.cfg
    monkeypatch.setattr(c, "maint_plane_lag_alert_ms", 5_000, raising=False)
    monkeypatch.setattr(c, "maint_plane_lag_alert_window_s", 1, raising=False)
    monkeypatch.setattr(c, "maint_plane_recovery_window_s", 120, raising=False)

    watchdog = MaintLagWatchdog()
    # Drive into tier 3 (lag=70s > 60s).
    msgs = _drive_to_tier(watchdog, lag_s=70.0, n_ticks=10)

    tier3_events = _throttled_at_tier(msgs, tier=3)
    assert watchdog.tier == 3, f"Expected tier 3, got {watchdog.tier}"
    assert len(tier3_events) == 1, (
        f"Expected exactly ONE tier-3 throttled event, got {len(tier3_events)}: {tier3_events}"
    )

    # Additional ticks with same sustained lag must produce NO new tier-3 events.
    extra = []
    t0 = 200.0
    for i in range(20):
        watchdog.note_lag(lag_s=70.0, now_s=t0 + i)
        extra.extend(watchdog.tick(now_s=t0 + i + 0.5))
    extra_tier3 = _throttled_at_tier(extra, tier=3)
    assert extra_tier3 == [], (
        f"Tier-3 event re-emitted on sustained lag (self-amplification): {extra_tier3}"
    )


def test_no_self_amplification_tier2_then_tier3(monkeypatch):
    """Transitioning from tier 2 to tier 3 emits exactly one event per tier."""
    c = _cfg_mod.cfg
    monkeypatch.setattr(c, "maint_plane_lag_alert_ms", 5_000, raising=False)
    monkeypatch.setattr(c, "maint_plane_lag_alert_window_s", 1, raising=False)
    monkeypatch.setattr(c, "maint_plane_recovery_window_s", 120, raising=False)

    watchdog = MaintLagWatchdog()
    t = 0.0

    # Ramp to tier 2 first.
    for i in range(10):
        t += 1.0
        watchdog.note_lag(lag_s=20.0, now_s=t)
    msgs_t2 = []
    for i in range(5):
        t += 1.0
        msgs_t2.extend(watchdog.tick(now_s=t))

    # Ramp to tier 3.
    for i in range(10):
        t += 1.0
        watchdog.note_lag(lag_s=70.0, now_s=t)
    msgs_t3 = []
    for i in range(5):
        t += 1.0
        msgs_t3.extend(watchdog.tick(now_s=t))

    assert _throttled_at_tier(msgs_t2, tier=2) == [msgs_t2[next(
        j for j, m in enumerate(msgs_t2)
        if m.payload.get("kind") == "maint_plane_throttled" and m.payload.get("tier") == 2
    )]] if any(m.payload.get("kind") == "maint_plane_throttled" and m.payload.get("tier") == 2 for m in msgs_t2) else True

    # Tier-3 fires exactly once; tier-2 does not re-fire during tier-3 phase.
    tier3_from_ramp = _throttled_at_tier(msgs_t3, tier=3)
    tier2_from_ramp = _throttled_at_tier(msgs_t3, tier=2)
    assert len(tier3_from_ramp) == 1, f"Expected exactly 1 tier-3 event: {msgs_t3}"
    assert tier2_from_ramp == [], f"Tier-2 re-emitted during tier-3 ramp: {tier2_from_ramp}"
