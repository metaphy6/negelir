"""Phase 5.4 — predictor-side reactor tests.

Cover:

  * ``LivePredictorReactor`` — plane→market mapping, deterministic
    request_id, idempotency on freshness-event re-delivery.
  * ``TrainerReactor`` — qualifying-event filter, accuracy-floor gate,
    debounce window per ``(predictor_id, league_id)``.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from swarm.agents.payloads import (
    FreshnessEvent,
    ModelTrained,
    PredictRequest,
)
from swarm.agents.reactor import LivePredictorReactor, TrainerReactor
from swarm.agents.topics import (
    FRESHNESS_EVENTS,
    MODEL_TRAINED,
    PREDICT_REQUEST,
)
from swarm.sdk.types import Message


def _freshness(
    *,
    plane: str = "live",
    change_kind: str = "updated",
    event_id: str = "ev-1",
    record_id: int = 42,
    diff: dict | None = None,
    emitted_at: str | None = None,
) -> Message:
    if emitted_at is None:
        emitted_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    payload = FreshnessEvent(
        event_id=event_id,
        record_id=record_id,
        source="mackolik",
        stable_id=f"match:{record_id}",
        record_type="match",
        plane=plane,
        change_kind=change_kind,
        diff=diff or {"league_id": "TR1"},
        emitted_at=emitted_at,
    )
    return Message.new(
        FRESHNESS_EVENTS,
        payload.as_dict(),
        producer="storage",
        trace_id="trace-Q",
    )


# ── LivePredictorReactor ────────────────────────────────────────


def test_live_plane_maps_to_1x2_and_ah():
    r = LivePredictorReactor()
    out = list(r.handle(_freshness(plane="live")))
    markets = sorted(m.payload["market"] for m in out)
    assert markets == ["1x2", "ah"]
    for m in out:
        assert m.envelope.topic == PREDICT_REQUEST
        assert m.envelope.trace_id == "trace-Q"


def test_market_plane_maps_to_ah_ou_btts():
    r = LivePredictorReactor()
    out = list(r.handle(_freshness(plane="market")))
    markets = sorted(m.payload["market"] for m in out)
    assert markets == ["ah", "btts", "ou_2_5"]


def test_other_planes_emit_nothing():
    r = LivePredictorReactor()
    for plane in ("schedule", "editorial", "reference"):
        assert list(r.handle(_freshness(plane=plane))) == []


def test_live_request_id_is_deterministic():
    """Same freshness event → same request_id (so consensus's
    deterministic prediction_id is stable end-to-end)."""
    r = LivePredictorReactor(clock_iso=lambda: "2025-01-01T00:00:00+00:00")
    a = sorted(m.payload["request_id"] for m in r.handle(_freshness()))
    r2 = LivePredictorReactor(clock_iso=lambda: "2025-01-01T00:00:00+00:00")
    b = sorted(m.payload["request_id"] for m in r2.handle(_freshness()))
    assert a == b
    assert a == ["r-ev-1-1x2", "r-ev-1-ah"]


def test_live_redelivery_is_idempotent():
    """Phase 4.7 ledger guard prevents double emission of requests."""
    r = LivePredictorReactor()
    msg = _freshness()
    first = list(r.handle(msg))
    second = list(r.handle(msg))  # same event_id → ledger short-circuits
    assert len(first) == 2
    assert second == []


# ── TrainerReactor ─────────────────────────────────────────────


def test_trainer_filters_non_qualifying_events():
    """Only created/updated should fire a retrain — not invalidated."""
    r = TrainerReactor(
        predictor_ids=("pred.elo.v1",),
        accuracy_lookup=lambda *_: 0.99,
        clock=lambda: 0.0,
    )
    assert list(r.handle(_freshness(change_kind="invalidated"))) == []


def test_trainer_emits_model_trained_for_each_predictor():
    r = TrainerReactor(
        predictor_ids=("pred.elo.v1", "pred.dixon_coles.v1"),
        accuracy_lookup=lambda *_: 0.99,
        clock=lambda: 0.0,
        version_clock=lambda: "v-test",
    )
    out = list(r.handle(_freshness(change_kind="updated")))
    assert len(out) == 2
    for m in out:
        assert m.envelope.topic == MODEL_TRAINED
        ev = ModelTrained.from_dict(m.payload)
        assert ev.predictor_id in ("pred.elo.v1", "pred.dixon_coles.v1")
        assert ev.profile_id == "TR1"  # league_id from diff
        assert ev.model_version == "v-test"


def test_trainer_blocks_when_accuracy_below_floor():
    r = TrainerReactor(
        predictor_ids=("pred.elo.v1",),
        accuracy_floor=0.80,
        accuracy_lookup=lambda *_: 0.50,  # below floor
        clock=lambda: 0.0,
    )
    out = list(r.handle(_freshness()))
    assert out == []


def test_trainer_debounces_per_predictor_league_slice():
    """Within ``debounce_sec``, a second qualifying event for the
    same (predictor_id, league_id) must NOT re-emit."""
    t = [0.0]
    r = TrainerReactor(
        predictor_ids=("pred.elo.v1",),
        debounce_sec=60,
        accuracy_lookup=lambda *_: 0.99,
        clock=lambda: t[0],
    )
    first = list(r.handle(_freshness(event_id="ev-A")))
    assert len(first) == 1
    t[0] = 30.0  # within debounce window
    second = list(r.handle(_freshness(event_id="ev-B")))
    assert second == []
    t[0] = 120.0  # past the window
    third = list(r.handle(_freshness(event_id="ev-C")))
    assert len(third) == 1


def test_trainer_redelivery_is_idempotent():
    """Same event_id → ledger short-circuits before debounce check."""
    r = TrainerReactor(
        predictor_ids=("pred.elo.v1",),
        accuracy_lookup=lambda *_: 0.99,
        clock=lambda: 0.0,
    )
    msg = _freshness(event_id="ev-X")
    first = list(r.handle(msg))
    second = list(r.handle(msg))
    assert len(first) == 1
    assert second == []
