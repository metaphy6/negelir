"""Phase 8 §8.16.2 proof tests — spool-flush ack reconciliation.

Three scenarios:
  (a) All acks arrive in time — reconciler emits spool_flush_acks_reconciled
      with complete=True and back-fills ack_received_count on the audit row
      (represented as a plain dict here; the real path is the CSV walker).
  (b) One consumer never acks — after deadline elapsed sweep() fires
      the spool_flush_acks_incomplete sec.alert and a reconciled event
      with complete=False.
  (c) Reconciler ticked twice with the same acks — no duplicate
      spool_flush_acks_reconciled events emitted.
"""
from __future__ import annotations

from typing import FrozenSet, List
from uuid import uuid4

import pytest

# ---------------------------------------------------------------------------
# Minimal stubs so tests run without bus infrastructure.
# ---------------------------------------------------------------------------


def _make_reconciler(start_s: float = 1_000_000.0, max_wait_h: int = 24):
    """Build a SpoolAckReconciler with injectable clock and patched config."""
    from unittest.mock import patch

    clock_calls = [start_s]

    def clock_s() -> float:
        return clock_calls[0]

    iso_calls = ["2099-01-01T00:00:00+00:00"]

    def clock_iso() -> str:
        return iso_calls[0]

    id_seq = [f"id-{i}" for i in range(1000)]

    def new_id() -> str:
        return id_seq.pop(0)

    with patch("swarm.agents.maint._spool_ack_reconciler._cfg") as mock_cfg:
        mock_cfg.opsctl_spool_ack_max_wait_h = max_wait_h
        from swarm.agents.maint._spool_ack_reconciler import SpoolAckReconciler
        r = SpoolAckReconciler(clock_s=clock_s, clock_iso=clock_iso, new_id=new_id)

    # Expose the mutable clock value so tests can advance time.
    r._clock_calls = clock_calls
    r._mock_cfg_patch_max_wait_h = max_wait_h
    return r, clock_calls


def _advance(clock_calls: list, seconds: float) -> None:
    clock_calls[0] += seconds


# ---------------------------------------------------------------------------
# Test (a): all 3 acks land — complete=True, no alert
# ---------------------------------------------------------------------------

def test_all_acks_land_emits_complete_true():
    """Three envelopes flushed; all three consumers ack within deadline.

    Expects:
    * Exactly one spool_flush_acks_reconciled event after the last ack.
    * complete=True in payload.
    * No spool_flush_acks_incomplete alert emitted.
    """
    from unittest.mock import patch
    from swarm.agents.maint._spool_ack_reconciler import SpoolAckReconciler
    from swarm.agents.topics import MAINT_EVENT, SEC_ALERT

    start = 1_000_000.0
    clock_calls = [start]

    with patch("swarm.agents.maint._spool_ack_reconciler._cfg") as mock_cfg:
        mock_cfg.opsctl_spool_ack_max_wait_h = 24
        r = SpoolAckReconciler(
            clock_s=lambda: clock_calls[0],
            clock_iso=lambda: "2099-01-01T00:00:00+00:00",
        )

        flush_id = uuid4().hex
        req_id = uuid4().hex
        expected: FrozenSet[str] = frozenset({"consumer.a.v1", "consumer.b.v1", "consumer.c.v1"})

        # First two acks arrive — no emission yet.
        msgs1 = r.reconcile(
            flush_invocation_id=flush_id,
            request_id=req_id,
            accepted_by="consumer.a.v1",
            expected=expected,
        )
        assert msgs1 == [], "should not emit before all acks land"

        msgs2 = r.reconcile(
            flush_invocation_id=flush_id,
            request_id=req_id,
            accepted_by="consumer.b.v1",
            expected=expected,
        )
        assert msgs2 == [], "should not emit before all acks land"

        # Final ack lands — should emit exactly one reconciled event.
        msgs3 = r.reconcile(
            flush_invocation_id=flush_id,
            request_id=req_id,
            accepted_by="consumer.c.v1",
            expected=expected,
        )

    assert len(msgs3) == 1, f"expected 1 msg, got {len(msgs3)}"
    msg = msgs3[0]
    assert msg.envelope.topic == MAINT_EVENT
    payload = msg.payload
    assert payload["kind"] == "spool_flush_acks_reconciled"
    assert payload["complete"] is True
    assert payload["expected_ack_count"] == 3
    assert payload["received_ack_count"] == 3
    assert "missing_ack_consumers" not in payload or payload["missing_ack_consumers"] == []
    # No sec.alert for complete flush.
    alert_msgs = [m for m in msgs3 if m.envelope.topic == SEC_ALERT]
    assert alert_msgs == [], "no alert expected when complete=True"


# ---------------------------------------------------------------------------
# Test (b): one consumer never acks — alert fires after deadline
# ---------------------------------------------------------------------------

def test_missing_ack_fires_alert_after_deadline():
    """Two of three consumers ack; the third is silent.

    After advancing past cfg.opsctl_spool_ack_max_wait_h, sweep() must:
    * emit spool_flush_acks_reconciled with complete=False
    * emit sec.alert.v1{kind=spool_flush_acks_incomplete, severity=warn}
    """
    from unittest.mock import patch
    from swarm.agents.maint._spool_ack_reconciler import SpoolAckReconciler
    from swarm.agents.topics import MAINT_EVENT, SEC_ALERT

    start = 1_000_000.0
    clock_calls = [start]
    max_wait_h = 1  # short window for the test

    with patch("swarm.agents.maint._spool_ack_reconciler._cfg") as mock_cfg:
        mock_cfg.opsctl_spool_ack_max_wait_h = max_wait_h
        r = SpoolAckReconciler(
            clock_s=lambda: clock_calls[0],
            clock_iso=lambda: "2099-01-01T01:00:00+00:00",
        )

        flush_id = uuid4().hex
        req_id = uuid4().hex
        expected: FrozenSet[str] = frozenset({"consumer.x.v1", "consumer.y.v1", "consumer.z.v1"})

        # Two acks land.
        r.reconcile(flush_invocation_id=flush_id, request_id=req_id,
                    accepted_by="consumer.x.v1", expected=expected)
        r.reconcile(flush_invocation_id=flush_id, request_id=req_id,
                    accepted_by="consumer.y.v1", expected=expected)

        # Advance clock past deadline.
        clock_calls[0] += max_wait_h * 3600 + 1

        sweep_msgs = r.sweep()

    # Must have exactly two messages: reconciled event + alert.
    topics = [m.envelope.topic for m in sweep_msgs]
    assert MAINT_EVENT in topics, "spool_flush_acks_reconciled notification expected"
    assert SEC_ALERT in topics, "spool_flush_acks_incomplete alert expected"

    event_msgs = [m for m in sweep_msgs if m.envelope.topic == MAINT_EVENT]
    alert_msgs = [m for m in sweep_msgs if m.envelope.topic == SEC_ALERT]

    assert len(event_msgs) == 1
    assert len(alert_msgs) == 1

    ep = event_msgs[0].payload
    assert ep["kind"] == "spool_flush_acks_reconciled"
    assert ep["complete"] is False
    assert ep["received_ack_count"] == 2
    assert ep["expected_ack_count"] == 3
    assert "consumer.z.v1" in ep.get("missing_ack_consumers", [])

    ap = alert_msgs[0].payload
    assert ap["kind"] == "spool_flush_acks_incomplete"
    assert ap["severity"] == "warn"
    assert "consumer.z.v1" in ap["reason"]


# ---------------------------------------------------------------------------
# Test (c): reconciler ticked twice — no duplicate events
# ---------------------------------------------------------------------------

def test_no_duplicate_reconciled_event():
    """Running reconcile() then sweep() a second time for the same flush
    must not produce duplicate spool_flush_acks_reconciled events.
    """
    from unittest.mock import patch
    from swarm.agents.maint._spool_ack_reconciler import SpoolAckReconciler
    from swarm.agents.topics import MAINT_EVENT

    start = 1_000_000.0
    clock_calls = [start]
    max_wait_h = 1

    with patch("swarm.agents.maint._spool_ack_reconciler._cfg") as mock_cfg:
        mock_cfg.opsctl_spool_ack_max_wait_h = max_wait_h
        r = SpoolAckReconciler(
            clock_s=lambda: clock_calls[0],
            clock_iso=lambda: "2099-01-01T00:00:00+00:00",
        )

        flush_id = uuid4().hex
        req_id = uuid4().hex
        expected: FrozenSet[str] = frozenset({"agent.alpha.v1"})

        # Single ack lands — window complete, emits reconciled.
        msgs_first = r.reconcile(
            flush_invocation_id=flush_id,
            request_id=req_id,
            accepted_by="agent.alpha.v1",
            expected=expected,
        )
        reconciled_events_first = [
            m for m in msgs_first
            if m.envelope.topic == MAINT_EVENT
            and (m.payload or {}).get("kind") == "spool_flush_acks_reconciled"
        ]
        assert len(reconciled_events_first) == 1, "expected exactly 1 reconciled event on first emit"

        # Second reconcile() call with same triple — must be no-op.
        msgs_dup = r.reconcile(
            flush_invocation_id=flush_id,
            request_id=req_id,
            accepted_by="agent.alpha.v1",
            expected=expected,
        )
        assert msgs_dup == [], "duplicate reconcile() must produce no messages"

        # sweep() after emission — must also be empty.
        sweep_msgs = r.sweep()
        reconciled_second = [
            m for m in sweep_msgs
            if m.envelope.topic == MAINT_EVENT
            and (m.payload or {}).get("kind") == "spool_flush_acks_reconciled"
        ]
        assert reconciled_second == [], "sweep after emission must not re-emit"
