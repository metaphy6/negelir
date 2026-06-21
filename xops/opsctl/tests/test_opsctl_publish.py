"""Phase 8 §8.1 — publish + ack-wait flow against an InMemoryBus."""
from __future__ import annotations

import os
import threading
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from common.config import Config
from swarm.sdk.bus import InMemoryBus
from swarm.sdk.types import Envelope, Message, Topic
from xops.opsctl._exit_codes import ExitCode
from xops.opsctl._publish import (
    MAINT_ACK_TOPIC,
    OPS_CONSOLE_PRODUCER,
    build_envelope,
    publish_event,
)


def _ack_message(*, request_id: str, accepted_by: str) -> Message:
    return Message(
        envelope=Envelope(topic=Topic(str(MAINT_ACK_TOPIC)), producer=accepted_by),
        payload={
            "request_id": request_id,
            "accepted": True,
            "accepted_by": accepted_by,
            "processed_at": "2025-01-01T00:00:00+00:00",
            "attempt": 0,
        },
    )


class _OpsctlEnvOverrides:
    """Context manager that pins per-test env (audit + spool dirs +
    a short ack timeout) and reloads the global Config so the
    publisher sees the patched values."""

    def __init__(self, tmpdir: str, ack_timeout_ms: int) -> None:
        self._patches = {
            "NEGELIR_OPSCTL_AUDIT_PATH": str(Path(tmpdir) / "audit.csv"),
            "NEGELIR_OPSCTL_SPOOL_DIR": str(Path(tmpdir) / "spool"),
            "NEGELIR_OPSCTL_ACK_TIMEOUT_MS": str(ack_timeout_ms),
        }
        self._old: dict[str, str | None] = {}

    def __enter__(self) -> "_OpsctlEnvOverrides":
        for k, v in self._patches.items():
            self._old[k] = os.environ.get(k)
            os.environ[k] = v
        return self

    def __exit__(self, *exc) -> None:
        for k, prev in self._old.items():
            if prev is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = prev


class TestPublishHappyPath(unittest.TestCase):
    def test_all_acks_received(self) -> None:
        with TemporaryDirectory() as tmp, _OpsctlEnvOverrides(tmp, ack_timeout_ms=1000):
            bus = InMemoryBus()
            msg = build_envelope(
                kind="denylist_clear",
                target="203.0.113.0/24",
                client_id="opsctl-test",
            )
            request_id = msg.payload["request_id"]

            # Pre-stage the ack so publish_event finds it on first read.
            bus.publish(_ack_message(request_id=request_id, accepted_by="sec.rate.v1"))

            result = publish_event(bus, msg)
            self.assertEqual(result.exit_code, ExitCode.OK, msg=result.note)
            self.assertEqual(result.expected_acks, frozenset({"sec.rate.v1"}))
            self.assertEqual(result.received_acks, frozenset({"sec.rate.v1"}))


class TestPublishHardTimeout(unittest.TestCase):
    def test_no_acks_within_budget(self) -> None:
        with TemporaryDirectory() as tmp, _OpsctlEnvOverrides(tmp, ack_timeout_ms=80):
            bus = InMemoryBus()
            msg = build_envelope(
                kind="denylist_clear",
                target="198.51.100.0/24",
                client_id="opsctl-test",
            )
            t0 = time.monotonic()
            result = publish_event(bus, msg)
            elapsed_ms = (time.monotonic() - t0) * 1000.0
            self.assertEqual(result.exit_code, ExitCode.HARD_TIMEOUT)
            self.assertLess(elapsed_ms, 1500.0, msg="hard-timeout did not bound wait")


class TestPublishUnknownAndNoConsumer(unittest.TestCase):
    def test_unknown_kind(self) -> None:
        with TemporaryDirectory() as tmp, _OpsctlEnvOverrides(tmp, ack_timeout_ms=100):
            bus = InMemoryBus()
            # Hand-build an envelope with a kind not in the routing table.
            msg = Message(
                envelope=Envelope(
                    topic=Topic("maint.event.v1"), producer=OPS_CONSOLE_PRODUCER
                ),
                payload={
                    "kind": "not_a_real_kind",
                    "target": "x",
                    "request_id": "rid",
                    "client_id": "opsctl-test",
                    "produced_at": "2025-01-01T00:00:00+00:00",
                },
            )
            result = publish_event(bus, msg)
            self.assertEqual(result.exit_code, ExitCode.UNKNOWN_KIND)

    def test_no_consumer_for_kind(self) -> None:
        # retrain_request is registered but has empty consumer set
        # (KINDS_PENDING_CONSUMER_LANDING — Phase 5.x trainer agent).
        with TemporaryDirectory() as tmp, _OpsctlEnvOverrides(tmp, ack_timeout_ms=100):
            bus = InMemoryBus()
            msg = build_envelope(
                kind="retrain_request",
                target="model-x",
                client_id="opsctl-test",
                extra_payload={"reason": "brier_floor"},
            )
            result = publish_event(bus, msg)
            self.assertEqual(result.exit_code, ExitCode.NO_CONSUMER_FOR_KIND)


class TestPublishBusDownSpools(unittest.TestCase):
    def test_bus_none_spools_envelope(self) -> None:
        with TemporaryDirectory() as tmp, _OpsctlEnvOverrides(tmp, ack_timeout_ms=100):
            cfg = Config()
            msg = build_envelope(
                kind="denylist_clear",
                target="203.0.113.99",
                client_id="opsctl-test",
            )
            result = publish_event(None, msg)
            self.assertEqual(result.exit_code, ExitCode.BUS_DOWN_SPOOLED)
            files = list(Path(cfg.opsctl_spool_dir_resolved).glob("*.envelope.json"))
            self.assertEqual(len(files), 1, msg="exactly one spool entry expected")
            # File mode owner-only (0600).
            mode = files[0].stat().st_mode & 0o777
            self.assertEqual(mode, 0o600)


if __name__ == "__main__":
    unittest.main()
