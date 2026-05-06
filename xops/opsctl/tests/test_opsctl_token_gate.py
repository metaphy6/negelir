"""Phase 8 §8.1 — quarantine-erase typed-token gate."""
from __future__ import annotations

import argparse
import io
import os
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

from ai.common.config import Config
from ai.swarm.sdk.bus import InMemoryBus
from ai.swarm.sdk.types import Envelope, Message, Topic

from xops.opsctl._exit_codes import ExitCode
from xops.opsctl._publish import MAINT_ACK_TOPIC
from xops.opsctl._token import derive_confirm_token
from xops.opsctl.subcommands import quarantine_erase


class _Env:
    def __init__(self, tmp: str) -> None:
        self.patches = {
            "NEGELIR_OPSCTL_AUDIT_PATH": str(Path(tmp) / "audit.csv"),
            "NEGELIR_OPSCTL_SPOOL_DIR": str(Path(tmp) / "spool"),
            "NEGELIR_OPSCTL_LOCK_DIR": str(Path(tmp) / "locks"),
            "NEGELIR_OPSCTL_ACK_TIMEOUT_MS": "1000",
        }
        self.old: dict[str, str | None] = {}

    def __enter__(self) -> "_Env":
        for k, v in self.patches.items():
            self.old[k] = os.environ.get(k)
            os.environ[k] = v
        return self

    def __exit__(self, *exc) -> None:
        for k, prev in self.old.items():
            if prev is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = prev


class TestQuarantineEraseTokenGate(unittest.TestCase):
    def test_missing_confirm_refused_with_audit(self) -> None:
        with TemporaryDirectory() as tmp, _Env(tmp):
            args = argparse.Namespace(
                target="sample-1", client_id="opsctl-test",
                confirm="", dry_run=False, json=True,
            )
            stderr = io.StringIO()
            with redirect_stdout(io.StringIO()), redirect_stderr(stderr):
                rc = quarantine_erase.run(args, bus=InMemoryBus())
            self.assertEqual(rc, int(ExitCode.BAD_USAGE))
            cfg = Config()
            audit = Path(cfg.opsctl_audit_path_resolved)
            self.assertTrue(audit.exists(), "audit row must be appended on refuse")
            content = audit.read_text(encoding="utf-8")
            self.assertIn("quarantine-erase", content)
            # Operator-friendly stderr names the expected token.
            expected = derive_confirm_token(
                subcommand="quarantine-erase", target="sample-1",
            )
            self.assertIn(expected, stderr.getvalue())

    def test_correct_confirm_accepted_publishes(self) -> None:
        with TemporaryDirectory() as tmp, _Env(tmp):
            bus = InMemoryBus()
            expected_token = derive_confirm_token(
                subcommand="quarantine-erase", target="sample-2",
            )
            args = argparse.Namespace(
                target="sample-2", client_id="opsctl-test",
                confirm=expected_token, dry_run=False, json=True,
            )

            # Pre-stage an ack from storage.v1 so the publish completes.
            # publish_event derives a fresh request_id; we listen to the
            # bus to learn the rid, then publish the ack. Easier path:
            # spawn a thread that watches MAINT_EVENT and answers.
            import threading
            from xops.opsctl._publish import MAINT_EVENT_TOPIC

            answered = threading.Event()

            def _ack_when_event_seen() -> None:
                bus.ensure_group(MAINT_EVENT_TOPIC, "test.observer")
                # Poll briefly for the published event.
                import time as _time
                deadline = _time.monotonic() + 2.0
                while _time.monotonic() < deadline:
                    deliveries = bus.read(
                        MAINT_EVENT_TOPIC, "test.observer", "obs", count=4, block_ms=50,
                    )
                    for d in deliveries:
                        rid = str(d.message.payload.get("request_id", ""))
                        ack = Message(
                            envelope=Envelope(
                                topic=Topic(str(MAINT_ACK_TOPIC)),
                                producer="maint.backup.v1",
                            ),
                            payload={
                                "request_id": rid,
                                "accepted": True,
                                "accepted_by": "maint.backup.v1",
                                "processed_at": "2025-01-01T00:00:00+00:00",
                                "attempt": 0,
                            },
                        )
                        bus.publish(ack)
                        bus.ack(MAINT_EVENT_TOPIC, "test.observer", d.handle)
                        answered.set()
                        return
                    _time.sleep(0.01)

            t = threading.Thread(target=_ack_when_event_seen, daemon=True)
            t.start()

            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = quarantine_erase.run(args, bus=bus)
            self.assertEqual(rc, int(ExitCode.OK), msg=buf.getvalue())
            t.join(timeout=1.0)
            self.assertTrue(answered.is_set(), "test observer should have seen the event")


if __name__ == "__main__":
    unittest.main()
