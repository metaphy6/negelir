"""Phase 8 §8.2 — Auto-scaler observability metrics.

Pins the binding contract:

* Counter ``maint_scaler_decisions_total{agent,reason,outcome}`` with
  ``outcome ∈ {applied, throttled, error}`` is registered and
  increments on every emitted ``scale_decision`` / ``scale_throttled``.
* Gauge ``maint_scaler_desired_replicas{agent}`` reflects the latest
  decision per agent.
* Gauge ``maint_scaler_vram_budget_mb{host}`` is set when device
  probes arrive and updated on every budget check.
* Histogram ``maint_scaler_runtime_call_seconds{controller,outcome}``
  observes once per ``RuntimeController.apply`` call; bucket
  boundaries come from ``cfg.maint_scaler_runtime_histogram_buckets``.
* Adversarial cardinality guard (Rule 7): a decision recorded with a
  ``reason`` outside the closed taxonomy is normalised to ``"unknown"``
  so a malformed code path cannot blow up Prometheus label cardinality.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

import pytest

from swarm.agents.maint.scaler import (
    DECISION_REASONS,
    THROTTLE_REASONS,
    MaintScaler,
    NoopController,
    _LabelCounter,
    _LabelGauge,
    _LabelHistogram,
    _parse_runtime_histogram_buckets,
)
from swarm.agents.topics import MAINT_EVENT
from swarm.sdk.types import Envelope, Message


# ── helpers ──────────────────────────────────────────────────────────


def _wrap(payload: dict) -> Message:
    env = Envelope(
        message_id="m-obs-1",
        trace_id="t-obs-1",
        topic=MAINT_EVENT,
        producer="ops_console",
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        schema_version=1,
        attempt=1,
    )
    return Message(envelope=env, payload=payload)


class _SlowController:
    """Test stub whose ``apply`` sleeps for a controllable interval
    so the runtime histogram has a non-zero observation to land in
    a known bucket."""

    name = "slow"

    def __init__(self, latency_s: float = 0.012, accept: bool = True) -> None:
        self.latency_s = latency_s
        self.accept = accept
        self.calls: list[tuple[str, int]] = []

    def apply(self, target: str, replicas: int) -> bool:
        self.calls.append((target, replicas))
        time.sleep(self.latency_s)
        return self.accept


# ── 1. registration ─────────────────────────────────────────────────


def test_metrics_registered_with_correct_label_sets() -> None:
    """Every metric must be registered under the binding name + label
    set declared in §8.2 — guards against silent renames."""
    agent = MaintScaler()
    assert agent._m_decisions.name == "maint_scaler_decisions_total"
    assert agent._m_decisions.label_names == ("agent", "reason", "outcome")
    assert agent._m_desired.name == "maint_scaler_desired_replicas"
    assert agent._m_desired.label_names == ("agent",)
    assert agent._m_vram_budget.name == "maint_scaler_vram_budget_mb"
    assert agent._m_vram_budget.label_names == ("host",)
    assert agent._m_runtime.name == "maint_scaler_runtime_call_seconds"
    assert agent._m_runtime.label_names == ("controller", "outcome")
    # Histogram buckets come from cfg → must be a non-empty
    # monotonic-ascending tuple of floats.
    assert agent._m_runtime.buckets, "histogram buckets must be non-empty"
    assert list(agent._m_runtime.buckets) == sorted(
        set(agent._m_runtime.buckets)
    )


def test_buckets_pulled_from_cfg(monkeypatch) -> None:
    """Operator-set bucket CSV must propagate to the histogram."""
    from common.config import cfg
    monkeypatch.setattr(
        cfg,
        "maint_scaler_runtime_histogram_buckets",
        "0.001,0.5,2.5",
        raising=False,
    )
    agent = MaintScaler()
    assert agent._m_runtime.buckets == (0.001, 0.5, 2.5)


# ── 2. counter outcomes (applied vs throttled) ──────────────────────


def test_counter_increments_on_applied_decision(monkeypatch) -> None:
    """A successful scale_decision lands an increment under
    ``outcome=applied`` for the classified reason."""
    from common.config import cfg
    monkeypatch.setattr(cfg, "maint_scaler_scale_up_queue_depth", 1, raising=False)
    monkeypatch.setattr(
        cfg, "maint_scaler_signal_window_samples", 0, raising=False
    )
    monkeypatch.setattr(
        cfg, "maint_scaler_target_load_per_replica", 0, raising=False
    )
    agent = MaintScaler(controller=NoopController())
    agent.tick({
        "predictor.elo": {
            "queue_depth": 99, "in_flight": 0, "head_age_s": 0,
        },
    })
    # Exactly one applied decision with reason from DECISION_REASONS.
    applied_keys = [
        labels for labels, _ in agent._m_decisions.series()
        if labels[2] == "applied"
    ]
    assert applied_keys, "expected at least one applied decision"
    for labels in applied_keys:
        assert labels[0] == "maint.scaler.v1"
        assert labels[1] in DECISION_REASONS
    snap = agent.metrics_snapshot()
    assert any(
        k.startswith("maint_scaler_decisions_total")
        and "outcome=applied" in k
        for k in snap
    )


def test_counter_increments_on_throttled_decision(monkeypatch) -> None:
    """A scale_throttled (e.g. min_replicas_floor on an idle queue)
    lands an increment under ``outcome=throttled``."""
    from common.config import cfg
    # Push the agent into a clean down-scale path: zero queue depth +
    # min_replicas already at 1 → "min_replicas_floor" throttle once
    # the grace gate has been satisfied.
    monkeypatch.setattr(cfg, "maint_scaler_scale_down_queue_depth", 100, raising=False)
    monkeypatch.setattr(cfg, "maint_scaler_min_replicas", 1, raising=False)
    monkeypatch.setattr(
        cfg, "maint_scaler_scale_down_grace_windows", 0, raising=False
    )
    monkeypatch.setattr(
        cfg, "maint_scaler_signal_window_samples", 0, raising=False
    )
    monkeypatch.setattr(
        cfg, "maint_scaler_target_load_per_replica", 0, raising=False
    )
    agent = MaintScaler(controller=NoopController())
    # Pre-register the target at min_replicas so the very first low
    # signal trips ``min_replicas_floor`` instead of ``scale_down_grace``.
    agent._evict_and_get("predictor.elo").last_replicas = 1
    agent.tick({
        "predictor.elo": {
            "queue_depth": 0, "in_flight": 0, "head_age_s": 0,
        },
    })
    throttled_keys = [
        labels for labels, _ in agent._m_decisions.series()
        if labels[2] == "throttled"
    ]
    assert throttled_keys, "expected at least one throttled decision"
    for labels in throttled_keys:
        assert labels[0] == "maint.scaler.v1"
        assert labels[1] in THROTTLE_REASONS


# ── 3. desired-replicas gauge ───────────────────────────────────────


def test_desired_replicas_gauge_reflects_latest_decision(monkeypatch) -> None:
    """``maint_scaler_desired_replicas{agent}`` must equal the last
    emitted ``next`` value for the agent."""
    from common.config import cfg
    monkeypatch.setattr(cfg, "maint_scaler_scale_up_queue_depth", 1, raising=False)
    monkeypatch.setattr(
        cfg, "maint_scaler_signal_window_samples", 0, raising=False
    )
    monkeypatch.setattr(
        cfg, "maint_scaler_target_load_per_replica", 0, raising=False
    )
    agent = MaintScaler(controller=NoopController())
    out = agent.tick({
        "predictor.elo": {
            "queue_depth": 99, "in_flight": 0, "head_age_s": 0,
        },
    })
    # Find the actual next value the agent published.
    next_val: int | None = None
    for m in out:
        if m.payload.get("kind") == "scale_decision":
            next_val = int(m.payload["next"])
            break
    assert next_val is not None, "expected a scale_decision"
    assert agent._m_desired.value(("predictor.elo",)) == float(next_val)


# ── 4. VRAM budget gauge ────────────────────────────────────────────


def test_vram_budget_gauge_set_on_device_probe(monkeypatch) -> None:
    """``maint_scaler_vram_budget_mb{host}`` is set the moment a probe
    arrives — operator dashboards must reflect the budget without
    waiting for the next decision tick."""
    from common.config import cfg
    monkeypatch.setattr(cfg, "maint_scaler_vram_headroom_mb", 1024, raising=False)
    agent = MaintScaler()
    # Default host = target.
    agent.update_device_probe(
        "predictor.elo",
        vram_total_mb=8192,
        vram_used_mb=1000,
        vram_per_replica_mb=2000,
    )
    assert agent._m_vram_budget.value(("predictor.elo",)) == 8192 - 1024
    # Explicit host label overrides the default.
    agent.update_device_probe(
        "predictor.elo",
        vram_total_mb=16384,
        vram_used_mb=1000,
        vram_per_replica_mb=2000,
        host="gpu-host-2",
    )
    assert agent._m_vram_budget.value(("gpu-host-2",)) == 16384 - 1024


def test_vram_budget_gauge_refreshed_by_check(monkeypatch) -> None:
    """``_check_vram_budget`` must refresh the gauge so a headroom
    cfg change between probes is visible immediately."""
    from common.config import cfg
    monkeypatch.setattr(cfg, "maint_scaler_vram_headroom_mb", 1024, raising=False)
    agent = MaintScaler()
    agent.update_device_probe(
        "predictor.elo",
        vram_total_mb=8192,
        vram_used_mb=100,
        vram_per_replica_mb=100,
    )
    monkeypatch.setattr(cfg, "maint_scaler_vram_headroom_mb", 2048, raising=False)
    # Direct call so we don't depend on the tick path.
    # _check_vram_budget returns (reason, unknown_footprint_seen) since §8.16.8.
    throttle_reason, _unknown = agent._check_vram_budget("predictor.elo", 2)
    assert throttle_reason is None
    assert agent._m_vram_budget.value(("predictor.elo",)) == 8192 - 2048


# ── 5. runtime histogram ────────────────────────────────────────────


def test_runtime_histogram_observes_per_apply(monkeypatch) -> None:
    """Every ``RuntimeController.apply`` call must land exactly one
    observation in the histogram, labelled by the controller name and
    the success/error outcome."""
    from common.config import cfg
    monkeypatch.setattr(cfg, "maint_scaler_scale_up_queue_depth", 1, raising=False)
    monkeypatch.setattr(
        cfg, "maint_scaler_signal_window_samples", 0, raising=False
    )
    monkeypatch.setattr(
        cfg, "maint_scaler_target_load_per_replica", 0, raising=False
    )
    ctl = _SlowController(latency_s=0.012, accept=True)
    agent = MaintScaler(controller=ctl)
    agent.tick({
        "predictor.elo": {
            "queue_depth": 99, "in_flight": 0, "head_age_s": 0,
        },
    })
    # Exactly one runtime call → exactly one observation under
    # (controller=slow, outcome=success).
    assert ctl.calls, "controller should have been invoked"
    assert agent._m_runtime.total(("slow", "success")) == 1
    assert agent._m_runtime.sum(("slow", "success")) >= 0.012
    # Bucket monotonicity: counts are non-decreasing across buckets.
    counts = agent._m_runtime.bucket_counts(("slow", "success"))
    assert list(counts) == sorted(counts)
    # And the observation lands in at least one bucket whose bound
    # exceeds the controller latency.
    assert counts[-1] >= 1


def test_runtime_histogram_records_error_outcome(monkeypatch) -> None:
    """A controller that returns False must produce an ``outcome=error``
    histogram observation (so dashboards can split success from failure
    latency)."""
    from common.config import cfg
    monkeypatch.setattr(cfg, "maint_scaler_scale_up_queue_depth", 1, raising=False)
    monkeypatch.setattr(
        cfg, "maint_scaler_signal_window_samples", 0, raising=False
    )
    monkeypatch.setattr(
        cfg, "maint_scaler_target_load_per_replica", 0, raising=False
    )
    ctl = _SlowController(latency_s=0.001, accept=False)
    agent = MaintScaler(controller=ctl)
    agent.tick({
        "predictor.elo": {
            "queue_depth": 99, "in_flight": 0, "head_age_s": 0,
        },
    })
    assert agent._m_runtime.total(("slow", "error")) == 1
    assert agent._m_runtime.total(("slow", "success")) == 0


# ── 6. adversarial cardinality guard (Rule 7) ───────────────────────


def test_unknown_reason_normalised_to_unknown_label() -> None:
    """A decision recorded with a reason that is NOT in the closed
    taxonomy must NOT register a fresh Prometheus series — it is
    normalised to ``reason="unknown"`` instead. Defends against
    label-cardinality explosions if a future code path adds a
    typo'd reason without updating the taxonomy."""
    agent = MaintScaler()
    bogus_reason = "definitely_not_a_real_reason_xyz123"
    assert bogus_reason not in DECISION_REASONS
    assert bogus_reason not in THROTTLE_REASONS
    before = {labels for labels, _ in agent._m_decisions.series()}
    agent._record_decision_metric(bogus_reason, "applied")
    after = {labels for labels, _ in agent._m_decisions.series()}
    new_series = after - before
    assert len(new_series) == 1
    new_labels = next(iter(new_series))
    # The bogus reason must NOT appear as a label value; "unknown"
    # is the bounded fallback.
    assert new_labels == ("maint.scaler.v1", "unknown", "applied")
    assert agent._m_decisions.value(new_labels) == 1
    # Re-recording with a DIFFERENT bogus reason still maps to the
    # same "unknown" series — cardinality stays bounded at 1.
    agent._record_decision_metric("yet_another_bad_reason", "applied")
    assert agent._m_decisions.value(new_labels) == 2


def test_unknown_outcome_dropped_silently() -> None:
    """An ``outcome`` outside the closed enum must be dropped (not
    registered as a new series)."""
    agent = MaintScaler()
    before = {labels for labels, _ in agent._m_decisions.series()}
    agent._record_decision_metric("manual_pin", "totally_made_up_outcome")
    after = {labels for labels, _ in agent._m_decisions.series()}
    assert before == after


# ── 7. parser smoke ────────────────────────────────────────────────


def test_runtime_bucket_parser_drops_bad_tokens_and_sorts() -> None:
    """The runtime-only parser must be defence-in-depth even though
    cfg already validates: malformed entries dropped, non-positive
    dropped, output sorted + de-duplicated."""
    out = _parse_runtime_histogram_buckets(
        "5.0, 0.01, NaN-token,  0.01, -1, 2.5,"
    )
    assert out == (0.01, 2.5, 5.0)


# ── 8. metric primitive arity safety ───────────────────────────────


def test_metric_primitives_drop_mismatched_arity() -> None:
    """Counter/Gauge/Histogram must silently drop observations whose
    label tuple length differs from the registered arity — the
    fallback behaviour the cardinality guard relies on."""
    c = _LabelCounter("c", ("a", "b"))
    c.inc(("only_one",))
    c.inc(("a", "b", "c"))
    assert list(c.series()) == []
    g = _LabelGauge("g", ("a",))
    g.set(("x", "y"), 1.0)
    assert list(g.series()) == []
    h = _LabelHistogram("h", ("a",), (1.0, 2.0))
    h.observe(("x", "y"), 0.5)
    assert h.total(("x", "y")) == 0
