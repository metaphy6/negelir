"""Phase 8 §8.1 — spool-flush drain semantics."""
from __future__ import annotations

import argparse
import io
import json
import os
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

from ai.common.config import Config
from ai.swarm.sdk.bus import InMemoryBus
from ai.swarm.sdk.types import Envelope, Message, Topic

from xops.opsctl._exit_codes import ExitCode
from xops.opsctl._publish import MAINT_ACK_TOPIC, MAINT_EVENT_TOPIC, build_envelope, publish_event
from xops.opsctl.subcommands import spool_flush


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


class TestSpoolFlushEmpty(unittest.TestCase):
    def test_empty_spool_returns_ok(self) -> None:
        with TemporaryDirectory() as tmp, _Env(tmp):
            args = argparse.Namespace(json=True, dry_run=False, max_entries=0)
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = spool_flush.run(args, bus=InMemoryBus())
            self.assertEqual(rc, int(ExitCode.OK))


class TestSpoolFlushDrainCycle(unittest.TestCase):
    def test_full_cycle_spool_then_flush_removes_file(self) -> None:
        with TemporaryDirectory() as tmp, _Env(tmp):
            cfg = Config()

            # Phase 1: bus down → spool an envelope.
            msg = build_envelope(
                kind="denylist_clear", target="203.0.113.0/24",
                client_id="opsctl-test",
            )
            result = publish_event(None, msg)
            self.assertEqual(result.exit_code, ExitCode.BUS_DOWN_SPOOLED)
            spool = Path(cfg.opsctl_spool_dir_resolved)
            entries = sorted(spool.glob("*.envelope.json"))
            self.assertEqual(len(entries), 1)
            spooled_rid = msg.payload["request_id"]

            # Phase 2: bus up + ack-poster ready → flush the spool.
            bus = InMemoryBus()
            import threading
            import time as _time

            done = threading.Event()

            def _ack_when_seen() -> None:
                bus.ensure_group(MAINT_EVENT_TOPIC, "obs")
                deadline = _time.monotonic() + 2.0
                while _time.monotonic() < deadline:
                    deliveries = bus.read(
                        MAINT_EVENT_TOPIC, "obs", "c", count=4, block_ms=50,
                    )
                    for d in deliveries:
                        rid = str(d.message.payload.get("request_id", ""))
                        ack = Message(
                            envelope=Envelope(
                                topic=Topic(str(MAINT_ACK_TOPIC)),
                                producer="sec.rate.v1",
                            ),
                            payload={
                                "request_id": rid,
                                "accepted": True,
                                "accepted_by": "sec.rate.v1",
                                "processed_at": "2025-01-01T00:00:00+00:00",
                                "attempt": 0,
                            },
                        )
                        bus.publish(ack)
                        bus.ack(MAINT_EVENT_TOPIC, "obs", d.handle)
                        done.set()
                        return
                    _time.sleep(0.01)

            t = threading.Thread(target=_ack_when_seen, daemon=True)
            t.start()

            args = argparse.Namespace(json=True, dry_run=False, max_entries=0)
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = spool_flush.run(args, bus=bus)
            t.join(timeout=1.0)

            self.assertEqual(rc, int(ExitCode.OK))
            out = json.loads(buf.getvalue().strip().splitlines()[-1])
            self.assertEqual(out["succeeded"], 1)
            # Spool file must be unlinked on success.
            remaining = sorted(spool.glob("*.envelope.json"))
            self.assertEqual(remaining, [])
            # Audit row mentions the spool replay.
            audit = Path(cfg.opsctl_audit_path_resolved)
            self.assertTrue(audit.exists())
            content = audit.read_text(encoding="utf-8")
            self.assertIn("spool-flush", content)
            self.assertIn(spooled_rid, content)


class TestSpoolFlushMalformedQuarantine(unittest.TestCase):
    def test_malformed_entry_quarantined(self) -> None:
        with TemporaryDirectory() as tmp, _Env(tmp):
            cfg = Config()
            spool = Path(cfg.opsctl_spool_dir_resolved)
            spool.mkdir(parents=True, mode=0o700, exist_ok=True)
            bad = spool / "0000-broken.envelope.json"
            bad.write_text("{not valid json", encoding="utf-8")
            args = argparse.Namespace(json=True, dry_run=False, max_entries=0)
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = spool_flush.run(args, bus=InMemoryBus())
            # Malformed entries do not block subsequent ones, but the
            # last_exit reflects the failure.
            self.assertNotEqual(rc, int(ExitCode.OK))
            self.assertFalse(bad.exists())
            self.assertTrue((spool / "0000-broken.envelope.json.malformed").exists())


if __name__ == "__main__":
    unittest.main()
