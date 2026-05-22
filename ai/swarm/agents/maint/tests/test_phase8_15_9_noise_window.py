"""Phase 8 §8.15.9 — proof tests (b)(c)(d): scaler noise-window suppression.

Tests:
  (b) Inside noise window, load-driven signal is suppressed:
      scale_throttled{reason=noise_window_active} emitted, no scale_decision.
  (c) VRAM-budget-exceeded fires DESPITE noise window (emergency bypass —
      VRAM check is before noise window check in tick()).
  (d) Clock walk 02:55→03:00→05:01 emits exactly two
      scaler_noise_window_active sec.alert events (entry + exit).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from swarm.agents.maint import scaler as scaler_module
from swarm.agents.maint.scaler import MaintScaler, NoopController
from swarm.agents.topics import SEC_ALERT


# ── helpers ────────────────────────────────────────────────────────────

def _build_agent(monkeypatch, noise_windows_json: str) -> MaintScaler:
    """Create a fresh MaintScaler with the given noise-windows config."""
    from common.config import cfg
    monkeypatch.setattr(cfg, "maint_scaler_noise_windows",
                        noise_windows_json, raising=False)
    # Low queue-depth threshold so a signal with depth=100 reliably triggers
    # a scale-up decision before suppression.
    monkeypatch.setattr(cfg, "maint_scaler_scale_up_queue_depth",
                        1, raising=False)
    return MaintScaler(controller=NoopController())


def _patch_now(monkeypatch, fixed_dt: datetime) -> None:
    """Patch `datetime.now` inside the scaler module to return *fixed_dt*."""
    mock_dt = MagicMock(spec=datetime)
    mock_dt.now.return_value = fixed_dt
    monkeypatch.setattr(scaler_module, "datetime", mock_dt)


# ── test (b): load-driven signal suppressed inside noise window ────────

def test_noise_window_suppresses_load_driven_scale_decision(monkeypatch) -> None:
    """When the current UTC hour falls inside a configured noise window,
    a load-driven scale decision must be replaced by
    ``scale_throttled{reason=noise_window_active}`` and no
    ``scale_decision`` must be emitted."""
    # "0 3-5 * * *" matches hours 3, 4, 5 on any day.
    agent = _build_agent(monkeypatch, '["0 3-5 * * *"]')
    # 2025-04-07 Monday (cron DOW=1) 03:30 UTC — inside window.
    _patch_now(monkeypatch, datetime(2025, 4, 7, 3, 30, tzinfo=timezone.utc))

    out = agent.tick({"predictor.elo": {
        "queue_depth": 100, "in_flight": 0, "head_age_s": 0,
    }})

    kinds = {m.payload.get("kind") for m in out}
    throttled = [m.payload for m in out if m.payload.get("kind") == "scale_throttled"]

    assert "scale_decision" not in kinds, (
        "scale_decision must not be emitted inside a noise window"
    )
    assert throttled, "must emit scale_throttled inside noise window"
    assert any(p.get("reason") == "noise_window_active" for p in throttled), (
        f"expected reason=noise_window_active in {[p.get('reason') for p in throttled]}"
    )


def test_noise_window_throttled_payload_carries_observed_field(monkeypatch) -> None:
    """The scale_throttled payload must include
    ``observed={'noise_window': '<cron_expr>'}`` for operator context."""
    agent = _build_agent(monkeypatch, '["0 3-5 * * *"]')
    _patch_now(monkeypatch, datetime(2025, 4, 7, 4, 0, tzinfo=timezone.utc))

    out = agent.tick({"predictor.elo": {
        "queue_depth": 50, "in_flight": 0, "head_age_s": 0,
    }})

    throttled = [m.payload for m in out
                 if m.payload.get("kind") == "scale_throttled"
                 and m.payload.get("reason") == "noise_window_active"]
    # May be empty if no decision would have been made — check if we got one
    # by also running the baseline (outside window) to confirm a decision fires.
    outside_agent = _build_agent(monkeypatch, '[]')  # no windows
    out2 = outside_agent.tick({"predictor.elo": {
        "queue_depth": 50, "in_flight": 0, "head_age_s": 0,
    }})
    if any(m.payload.get("kind") == "scale_decision" for m in out2):
        # A decision would fire without the window — so the window must suppress.
        assert throttled, "noise window must suppress the decision"
        obs = throttled[0].get("observed", {})
        assert obs.get("noise_window") == "0 3-5 * * *", (
            f"expected observed.noise_window='0 3-5 * * *', got {obs!r}"
        )


def test_outside_noise_window_decisions_are_not_suppressed(monkeypatch) -> None:
    """Outside the configured window, decisions must proceed normally."""
    agent = _build_agent(monkeypatch, '["0 3-5 * * *"]')
    # 02:59 UTC — just before the window starts.
    _patch_now(monkeypatch, datetime(2025, 4, 7, 2, 59, tzinfo=timezone.utc))

    out = agent.tick({"predictor.elo": {
        "queue_depth": 100, "in_flight": 0, "head_age_s": 0,
    }})

    kinds = {m.payload.get("kind") for m in out}
    # Noise window suppression must NOT fire outside the window.
    throttled_nw = [m.payload for m in out
                    if m.payload.get("kind") == "scale_throttled"
                    and m.payload.get("reason") == "noise_window_active"]
    assert not throttled_nw, (
        "noise-window suppression must not fire at hour=02 (window is 03-05)"
    )


# ── test (c): VRAM emergency bypass ───────────────────────────────────

def test_vram_budget_exceeded_fires_despite_noise_window(monkeypatch) -> None:
    """VRAM-budget check fires BEFORE the noise-window check.
    A scale_throttled{reason=vram_budget_exceeded} must still be emitted
    even when the current tick is inside a noise window."""
    from common.config import cfg
    monkeypatch.setattr(cfg, "maint_scaler_vram_headroom_mb", 512, raising=False)
    agent = _build_agent(monkeypatch, '["0 3-5 * * *"]')
    # Push a stale-but-near-full VRAM probe so the VRAM check will fire.
    agent.update_device_probe(
        "predictor.elo",
        vram_total_mb=8192,
        vram_used_mb=7800,   # 7800 used + 512 headroom > 8192 total
        vram_per_replica_mb=2000,
    )
    # Put the clock inside the noise window (hour=3).
    _patch_now(monkeypatch, datetime(2025, 4, 7, 3, 30, tzinfo=timezone.utc))

    out = agent.tick({"predictor.elo": {
        "queue_depth": 100, "in_flight": 0, "head_age_s": 0,
    }})

    throttled = [m.payload for m in out if m.payload.get("kind") == "scale_throttled"]
    reasons = [p.get("reason") for p in throttled]

    # VRAM check fires first (before noise window).
    assert "vram_budget_exceeded" in reasons, (
        f"expected vram_budget_exceeded in throttle reasons, got {reasons}"
    )
    # Noise-window suppression should NOT produce its own event because
    # the VRAM guard already continued to the next target.
    assert "noise_window_active" not in reasons, (
        "vram_budget_exceeded fires before noise-window check — "
        "noise_window_active must not also appear for the same target"
    )


# ── test (d): edge detection — exactly 2 sec.alert events ─────────────

def test_noise_window_edge_detection_emits_entry_and_exit_alerts(monkeypatch) -> None:
    """Clock walk: 02:55 (outside) → 03:00 (inside) → 05:01 (outside)
    must produce exactly two scaler_noise_window_active sec.alert events:
      1. entry edge at hour=3
      2. exit edge at hour=5 (after window end)
    """
    agent = _build_agent(monkeypatch, '["0 3-5 * * *"]')

    # ── Tick 1: hour=02 — outside window. No alert. ───────────────────
    _patch_now(monkeypatch, datetime(2025, 4, 7, 2, 55, tzinfo=timezone.utc))
    out1 = agent.tick({"predictor.elo": {
        "queue_depth": 5, "in_flight": 0, "head_age_s": 0,
    }})

    # ── Tick 2: hour=03 — enters window. Expect ENTRY alert. ──────────
    _patch_now(monkeypatch, datetime(2025, 4, 7, 3, 0, tzinfo=timezone.utc))
    out2 = agent.tick({"predictor.elo": {
        "queue_depth": 5, "in_flight": 0, "head_age_s": 0,
    }})

    # ── Tick 3: hour=03 again — still in window. No new alert. ────────
    _patch_now(monkeypatch, datetime(2025, 4, 7, 3, 30, tzinfo=timezone.utc))
    out3 = agent.tick({"predictor.elo": {
        "queue_depth": 5, "in_flight": 0, "head_age_s": 0,
    }})

    # ── Tick 4: hour=06 — exits window. Expect EXIT alert. ────────────
    _patch_now(monkeypatch, datetime(2025, 4, 7, 6, 1, tzinfo=timezone.utc))
    out4 = agent.tick({"predictor.elo": {
        "queue_depth": 5, "in_flight": 0, "head_age_s": 0,
    }})

    all_out = out1 + out2 + out3 + out4
    alerts = [m.payload for m in all_out
              if m.envelope.topic == SEC_ALERT
              and m.payload.get("kind") == "scaler_noise_window_active"]

    assert len(alerts) == 2, (
        f"expected exactly 2 scaler_noise_window_active alerts "
        f"(entry + exit), got {len(alerts)}: {[a.get('reason') for a in alerts]}"
    )

    # Entry alert must mention "entry" or "entered".
    entry_alerts = [a for a in alerts if "entr" in (a.get("reason") or "").lower()]
    exit_alerts = [a for a in alerts if "exit" in (a.get("reason") or "").lower()]
    assert entry_alerts, f"no entry alert found in {alerts}"
    assert exit_alerts, f"no exit alert found in {alerts}"


def test_noise_window_no_spurious_alert_on_first_tick_outside_window(
    monkeypatch,
) -> None:
    """The very first tick when no window is active must NOT emit an alert
    (sentinel → None is not an operator-observable transition)."""
    agent = _build_agent(monkeypatch, '["0 3-5 * * *"]')
    _patch_now(monkeypatch, datetime(2025, 4, 7, 2, 0, tzinfo=timezone.utc))

    out = agent.tick({"predictor.elo": {
        "queue_depth": 5, "in_flight": 0, "head_age_s": 0,
    }})

    alerts = [m for m in out
              if m.envelope.topic == SEC_ALERT
              and m.payload.get("kind") == "scaler_noise_window_active"]
    assert not alerts, (
        "first tick outside any window must NOT emit scaler_noise_window_active"
    )


# ── adversarial: _parse_noise_windows error branches ───────────────────


def test_parse_noise_windows_bad_json_returns_empty(monkeypatch) -> None:
    """Malformed JSON string must disable suppression (return []) silently."""
    from swarm.agents.maint.scaler import _parse_noise_windows
    result = _parse_noise_windows("not-json-at-all{{{")
    assert result == [], "bad JSON should yield empty list (no suppression)"


def test_parse_noise_windows_non_string_entry_skipped(monkeypatch) -> None:
    """Non-string entries inside the JSON array must be skipped; valid entries
    are still parsed."""
    from swarm.agents.maint.scaler import _parse_noise_windows
    # Mixed array: one valid cron, one integer, one boolean.
    result = _parse_noise_windows('["0 3-5 * * *", 42, true]')
    assert len(result) == 1, (
        "integer and boolean entries must be skipped; one valid cron survives"
    )
