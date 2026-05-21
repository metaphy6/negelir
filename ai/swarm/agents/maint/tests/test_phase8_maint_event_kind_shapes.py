"""Phase 8 §8.9 — maint.event.v1 per-kind shape proof tests.

Three assertions (per ROADMAP §8.9 DoD):

1. Typed factory validates: scaler._notify produces payloads that
   pass schemas.validate_kind for the given kind.

2. Unknown kind in redelivery -> maint_unknown_kind alert (not silent).

3. Debounce: same unknown kind twice -> one alert only.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from swarm.agents.maint.scaler import MaintScaler
from swarm.agents.topics import MAINT_EVENT
from swarm.sdk import schemas
from swarm.sdk.types import Envelope, Message


def _scaler() -> MaintScaler:
    return MaintScaler()


def _wrap(payload: dict) -> Message:
    env = Envelope(
        message_id="m-test",
        trace_id="t-test",
        topic=MAINT_EVENT,
        producer="ops_console",
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        schema_version=1,
        attempt=1,
    )
    return Message(envelope=env, payload=payload)


# 1. Typed factory validates

@pytest.mark.parametrize("kind,target,extra", [
    (
        "scale_decision",
        "pred.elo.v1",
        {
            "replicas": 2,
            "source": "auto",
            "controller": "noop",
            "controller_accepted": True,
            "decision_window_id": "ab12cd34:1735689600000",
        },
    ),
    (
        "scale_throttled",
        "pred.elo.v1",
        {
            "would_be": 4,
            "reason": "max_changes_per_window",
            "decision_window_id": "ab12cd34:1735689600000",
        },
    ),
    (
        "manual_scale_pin_expired",
        "pred.elo.v1",
        {"reason": "ttl"},
    ),
])
def test_scaler_notify_payload_validates_per_kind_schema(
    kind: str, target: str, extra: dict
) -> None:
    scaler = _scaler()
    msg = scaler._notify(kind, target=target, extra=extra)
    errors = schemas.validate_kind(MAINT_EVENT, msg.payload)
    assert errors == [], (
    )


# 2. Unknown kind in redelivery -> maint_unknown_kind alert

def test_unknown_kind_redelivery_emits_maint_unknown_kind() -> None:
    scaler = _scaler()
    msg = _wrap({"kind": "some_future_kind_v999", "target": "x"})
    out = list(scaler.handle(msg))
    assert len(out) == 1, (
        f"expected exactly 1 maint_unknown_kind message; got {out}"
    )
    payload = out[0].payload
    assert payload["kind"] == "maint_unknown_kind"
    assert payload["unknown_kind"] == "some_future_kind_v999"
    assert payload["source"] == "maint.scaler.v1"


def test_unknown_kind_redelivery_payload_validates_per_kind_schema() -> None:
    scaler = _scaler()
    msg = _wrap({"kind": "future_unknown_kind_xyz"})
    out = list(scaler.handle(msg))
    assert out, "expected maint_unknown_kind notification"
    errors = schemas.validate_kind(MAINT_EVENT, out[0].payload)
    assert errors == [], (
        f"maint_unknown_kind payload failed schema validation: {errors}"
    )


def test_known_kinds_not_treated_as_unknown() -> None:
    from swarm.agents.maint import KNOWN_MAINT_EVENT_KINDS
    scaler = _scaler()
    for kind in sorted(KNOWN_MAINT_EVENT_KINDS)[:5]:
        out = list(scaler.handle(_wrap({"kind": kind, "target": "x"})))
        for m in out:
            assert m.payload.get("kind") != "maint_unknown_kind", (
            )


# 3. Debounce

def test_unknown_kind_alert_debounced_within_process() -> None:
    scaler = _scaler()
    msg1 = _wrap({"kind": "future_kind_debounce_test"})
    msg2 = _wrap({"kind": "future_kind_debounce_test"})
    out1 = list(scaler.handle(msg1))
    out2 = list(scaler.handle(msg2))
    assert len(out1) == 1, "first delivery must produce one alert"
    assert len(out2) == 0, "second delivery must be silently dropped (debounced)"


def test_two_distinct_unknown_kinds_each_produce_one_alert() -> None:
    scaler = _scaler()
    out_a = list(scaler.handle(_wrap({"kind": "future_alpha"})))
    out_b = list(scaler.handle(_wrap({"kind": "future_beta"})))
    assert len(out_a) == 1
    assert len(out_b) == 1
    assert out_a[0].payload["unknown_kind"] == "future_alpha"
    assert out_b[0].payload["unknown_kind"] == "future_beta"
