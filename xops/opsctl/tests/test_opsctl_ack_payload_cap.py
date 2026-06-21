"""Phase 8 §8.9 — maint.ack.v1 payload-cap integration proof tests.

Covers the end-to-end scenario described in the §8.9 DoD bullet:
  "Consumer returns a 64KB ``details`` blob; assert publisher truncates
  to ``cfg.maint_ack_payload_max_bytes``, fires
  ``kind=maint_ack_oversize`` (debounced per ``accepted_by``), and the
  truncated ack still satisfies the operator wait-for-acks loop."

Implementation under test: :func:`ai.swarm.sdk.maint_ack.build_capped_maint_ack`
(emit-time cap helper used by every maint-agent consumer when building
their ``maint.ack.v1`` reply) + :func:`xops.opsctl._publish.publish_event`
(operator wait-for-acks loop).

The test uses a ``_SpyBus`` (InMemoryBus subclass) to record all
published messages so we can assert the ``sec.alert.v1`` alert without
touching bus internals.
"""
from __future__ import annotations

import os
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from common.config import Config
from swarm.agents.topics import MAINT_ACK, SEC_ALERT
from swarm.sdk.bus import InMemoryBus
from swarm.sdk.maint_ack import build_capped_maint_ack
from swarm.sdk.types import Envelope, Message, Topic
from xops.opsctl._exit_codes import ExitCode
from xops.opsctl._publish import MAINT_ACK_TOPIC, build_envelope, publish_event

# ── Helpers ──────────────────────────────────────────────────────────────────

class _SpyBus(InMemoryBus):
    """InMemoryBus that records every published message for assertions."""

    def __init__(self) -> None:
        super().__init__()
        self.published: list[Message] = []

    def publish(self, msg: Message) -> None:  # type: ignore[override]
        self.published.append(msg)
        super().publish(msg)


class _Env:
    """Context manager for patching env vars and reloading Config."""

    def __init__(self, **patches: str) -> None:
        self._patches = patches
        self._old: dict[str, str | None] = {}

    def __enter__(self) -> "_Env":
        for k, v in self._patches.items():
            self._old[k] = os.environ.get(k)
            os.environ[k] = v
        return self

    def __exit__(self, *exc: object) -> None:
        for k, prev in self._old.items():
            if prev is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = prev


class _OpsctlEnv:
    """Pins opsctl-specific env + a short ack timeout for tests."""

    def __init__(self, tmpdir: str, ack_timeout_ms: int = 1000) -> None:
        self._patches = {
            "NEGELIR_OPSCTL_AUDIT_PATH": str(Path(tmpdir) / "audit.csv"),
            "NEGELIR_OPSCTL_SPOOL_DIR": str(Path(tmpdir) / "spool"),
            "NEGELIR_OPSCTL_ACK_TIMEOUT_MS": str(ack_timeout_ms),
        }
        self._old: dict[str, str | None] = {}

    def __enter__(self) -> "_OpsctlEnv":
        for k, v in self._patches.items():
            self._old[k] = os.environ.get(k)
            os.environ[k] = v
        return self

    def __exit__(self, *exc: object) -> None:
        for k, prev in self._old.items():
            if prev is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = prev


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _publish_agent_ack(
    bus: InMemoryBus,
    *,
    request_id: str,
    accepted_by: str,
    details: dict[str, Any],
    oversize_alerted: set[str],
    cfg: Config,
) -> None:
    """Simulate a maint-agent consumer that uses ``build_capped_maint_ack``
    to publish its ``maint.ack.v1`` reply, then fires a debounced
    ``sec.alert.v1{kind=maint_ack_oversize}`` if the payload was over-cap.

    ``oversize_alerted`` is the agent's per-session debounce set; the
    caller owns it so tests can inspect or share it across calls.
    """
    ack, notice = build_capped_maint_ack(
        request_id=request_id,
        accepted=True,
        accepted_by=accepted_by,
        processed_at=_now_iso(),
        details=details,
        cfg=cfg,
    )
    bus.publish(
        Message(
            envelope=Envelope(topic=MAINT_ACK, producer=accepted_by),
            payload=ack.as_dict(),
        )
    )
    if notice is not None and accepted_by not in oversize_alerted:
        oversize_alerted.add(accepted_by)
        bus.publish(
            Message(
                envelope=Envelope(topic=SEC_ALERT, producer=accepted_by),
                payload={
                    "kind": "maint_ack_oversize",
                    "severity": "warn",
                    "accepted_by": accepted_by,
                    "request_id": request_id,
                    "original_details_bytes": notice.original_details_bytes,
                    "capped_payload_bytes": notice.capped_payload_bytes,
                    "cap": notice.cap,
                },
            )
        )


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestTruncatedAckSatisfiesOpsctlLoop(unittest.TestCase):
    """Core DoD requirement: truncated ack still closes the wait loop."""

    def test_64kb_details_loop_returns_ok(self) -> None:
        """Consumer returns 64KB details → published ack is truncated →
        opsctl wait-for-acks loop returns ExitCode.OK."""
        with TemporaryDirectory() as tmp:
            with _OpsctlEnv(tmp), _Env(NEGELIR_MAINT_ACK_PAYLOAD_MAX_BYTES="256"):
                cfg = Config()
                bus = _SpyBus()
                event_msg = build_envelope(
                    kind="denylist_clear",
                    target="203.0.113.0/24",
                    client_id="test-cap",
                )
                request_id = str(event_msg.payload["request_id"])
                oversize_alerted: set[str] = set()

                # Consumer publishes a truncated ack (64KB details → capped).
                _publish_agent_ack(
                    bus,
                    request_id=request_id,
                    accepted_by="sec.rate.v1",
                    details={"blob": "x" * 65536},
                    oversize_alerted=oversize_alerted,
                    cfg=cfg,
                )

                result = publish_event(bus, event_msg)

        self.assertEqual(result.exit_code, ExitCode.OK, msg=result.note)
        self.assertIn("sec.rate.v1", result.received_acks)

    def test_truncated_ack_has_reason_prefix(self) -> None:
        """Ack ``reason`` starts with ``truncated:`` so the operator can
        see the payload was capped when inspecting opsctl output."""
        with _Env(NEGELIR_MAINT_ACK_PAYLOAD_MAX_BYTES="256"):
            cfg = Config()
            ack, notice = build_capped_maint_ack(
                request_id="req-reason",
                accepted=True,
                accepted_by="sec.rate.v1",
                processed_at=_now_iso(),
                details={"blob": "x" * 65536},
                cfg=cfg,
            )
        self.assertIsNotNone(notice)
        self.assertIn("truncated:", ack.reason)
        self.assertIsNone(ack.details)

    def test_truncated_ack_accepted_by_intact(self) -> None:
        """Truncation must not corrupt ``accepted_by`` — it is the loop's
        correlation key and must survive byte-capping unchanged."""
        with _Env(NEGELIR_MAINT_ACK_PAYLOAD_MAX_BYTES="256"):
            cfg = Config()
            ack, _ = build_capped_maint_ack(
                request_id="req-ab",
                accepted=True,
                accepted_by="maint.scaler.v1",
                processed_at=_now_iso(),
                details={"blob": "y" * 65536},
                cfg=cfg,
            )
        self.assertEqual(ack.accepted_by, "maint.scaler.v1")
        self.assertTrue(ack.accepted)


class TestOversizeAlertFired(unittest.TestCase):
    """When build_capped_maint_ack returns a notice, the caller must
    publish ``sec.alert.v1{kind=maint_ack_oversize}``."""

    def test_oversize_notice_publishes_sec_alert(self) -> None:
        """First oversized ack → exactly one ``maint_ack_oversize`` alert."""
        with _Env(NEGELIR_MAINT_ACK_PAYLOAD_MAX_BYTES="256"):
            cfg = Config()
            bus = _SpyBus()
            oversize_alerted: set[str] = set()
            _publish_agent_ack(
                bus,
                request_id="req-alert",
                accepted_by="maint.scaler.v1",
                details={"blob": "a" * 65536},
                oversize_alerted=oversize_alerted,
                cfg=cfg,
            )

        sec_alerts = [
            m for m in bus.published
            if m.envelope.topic == SEC_ALERT
            and m.payload.get("kind") == "maint_ack_oversize"
        ]
        self.assertEqual(len(sec_alerts), 1)
        self.assertEqual(sec_alerts[0].payload["accepted_by"], "maint.scaler.v1")

    def test_maint_ack_oversize_in_known_sec_alert_kinds(self) -> None:
        """``maint_ack_oversize`` must be a registered kind so the
        producer-set boundary test doesn't flag it as unknown."""
        from swarm.agents.payloads import KNOWN_SEC_ALERT_KINDS
        self.assertIn("maint_ack_oversize", KNOWN_SEC_ALERT_KINDS)

    def test_alert_payload_carries_size_diagnostics(self) -> None:
        """Alert payload carries ``original_details_bytes`` and ``cap``
        so operators can size the budget without guessing."""
        with _Env(NEGELIR_MAINT_ACK_PAYLOAD_MAX_BYTES="256"):
            cfg = Config()
            bus = _SpyBus()
            oversize_alerted: set[str] = set()
            _publish_agent_ack(
                bus,
                request_id="req-diag",
                accepted_by="maint.dlq.v1",
                details={"blob": "b" * 65536},
                oversize_alerted=oversize_alerted,
                cfg=cfg,
            )

        alerts = [
            m for m in bus.published
            if m.envelope.topic == SEC_ALERT
            and m.payload.get("kind") == "maint_ack_oversize"
        ]
        self.assertEqual(len(alerts), 1)
        payload = alerts[0].payload
        self.assertIn("original_details_bytes", payload)
        self.assertIn("cap", payload)
        self.assertGreater(payload["original_details_bytes"], 256)
        self.assertEqual(payload["cap"], 256)


class TestOversizeAlertDebounced(unittest.TestCase):
    """Alert is debounced per ``accepted_by`` — second oversize from the
    same consumer does NOT fire a second ``maint_ack_oversize`` event."""

    def test_second_oversize_from_same_accepted_by_no_second_alert(self) -> None:
        with _Env(NEGELIR_MAINT_ACK_PAYLOAD_MAX_BYTES="256"):
            cfg = Config()
            bus = _SpyBus()
            oversize_alerted: set[str] = set()

            # First oversize ack
            _publish_agent_ack(
                bus, request_id="req-db-1", accepted_by="maint.scaler.v1",
                details={"blob": "c" * 65536},
                oversize_alerted=oversize_alerted, cfg=cfg,
            )
            # Second oversize ack from the same accepted_by
            _publish_agent_ack(
                bus, request_id="req-db-2", accepted_by="maint.scaler.v1",
                details={"blob": "d" * 65536},
                oversize_alerted=oversize_alerted, cfg=cfg,
            )

        oversize_alerts = [
            m for m in bus.published
            if m.envelope.topic == SEC_ALERT
            and m.payload.get("kind") == "maint_ack_oversize"
        ]
        # Debounced: only the first fires.
        self.assertEqual(len(oversize_alerts), 1,
                         msg="second oversize from same accepted_by must be suppressed")

    def test_different_accepted_by_each_fires_once(self) -> None:
        """Two different consumers both oversizing → two alerts (one each)."""
        with _Env(NEGELIR_MAINT_ACK_PAYLOAD_MAX_BYTES="256"):
            cfg = Config()
            bus = _SpyBus()
            oversize_alerted: set[str] = set()

            _publish_agent_ack(
                bus, request_id="req-diff-1", accepted_by="maint.scaler.v1",
                details={"blob": "e" * 65536},
                oversize_alerted=oversize_alerted, cfg=cfg,
            )
            _publish_agent_ack(
                bus, request_id="req-diff-2", accepted_by="maint.backup.v1",
                details={"blob": "f" * 65536},
                oversize_alerted=oversize_alerted, cfg=cfg,
            )

        oversize_alerts = [
            m for m in bus.published
            if m.envelope.topic == SEC_ALERT
            and m.payload.get("kind") == "maint_ack_oversize"
        ]
        alert_agents = {a.payload["accepted_by"] for a in oversize_alerts}
        self.assertEqual(len(oversize_alerts), 2)
        self.assertIn("maint.scaler.v1", alert_agents)
        self.assertIn("maint.backup.v1", alert_agents)


if __name__ == "__main__":
    unittest.main()
