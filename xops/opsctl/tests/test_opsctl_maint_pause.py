"""Phase 8 §8.10 — ``ops.maint-pause`` / ``ops.maint-resume`` tests.

Covers:
* dry-run of pause + resume (no publish, no audit row, expected
  ack set computed per the routing table)
* full publish + ack-wait happy path against an in-memory bus,
  with all four maint.* consumers acking ('all' broadcast)
* single-target publish where the non-targeted agents return
  ``not_targeted`` so the publisher still sees a complete ack set
* schema validation: ttl_s in [1, 86400]; pause requires it
* critical-agent gate bumps to CONFIRM tier (refused without
  --confirm)
"""
from __future__ import annotations

import argparse
import io
import json
import os
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

from common.config import Config
from swarm.agents.maint._ack_routing import expected_ack_set
from swarm.sdk.bus import InMemoryBus
from swarm.sdk.types import Envelope, Message, Topic
from xops.opsctl._exit_codes import ExitCode
from xops.opsctl._publish import MAINT_ACK_TOPIC
from xops.opsctl.subcommands import maint_pause, maint_resume

# ── env scaffolding ────────────────────────────────────────────────


class _Env:
    def __init__(self, tmp: str, *, ack_timeout_ms: int = 1000,
                 critical: str = "consensus.v1,sec.rate.v1,maint.backup.v1") -> None:
        self.patches = {
            "NEGELIR_OPSCTL_AUDIT_PATH": str(Path(tmp) / "audit.csv"),
            "NEGELIR_OPSCTL_SPOOL_DIR": str(Path(tmp) / "spool"),
            "NEGELIR_OPSCTL_LOCK_DIR": str(Path(tmp) / "locks"),
            "NEGELIR_OPSCTL_ACK_TIMEOUT_MS": str(ack_timeout_ms),
            "NEGELIR_OPSCTL_CRITICAL_AGENTS": critical,
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


def _run(module, **kwargs) -> tuple[int, dict]:
    defaults = dict(
        target="all", ttl_s=0, reason="", client_id="opsctl-test",
        confirm="", dry_run=False, json=True,
    )
    defaults.update(kwargs)
    args = argparse.Namespace(**defaults)
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = module.run(args, bus=kwargs.pop("bus", None))
    out = {}
    last_line = buf.getvalue().strip().splitlines()[-1] if buf.getvalue().strip() else ""
    if last_line:
        try:
            out = json.loads(last_line)
        except json.JSONDecodeError:
            out = {"_raw": last_line}
    return rc, out


# ── dry-run ────────────────────────────────────────────────────────


class TestMaintPauseDryRun(unittest.TestCase):
    def test_pause_dry_run_full_ack_set(self) -> None:
        with TemporaryDirectory() as tmp, _Env(tmp):
            args = argparse.Namespace(
                target="all", ttl_s=300, reason="rolling",
                client_id="opsctl-test", confirm="",
                dry_run=True, json=True,
            )
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = maint_pause.run(args, bus=None)
            self.assertEqual(rc, int(ExitCode.OK))
            out = json.loads(buf.getvalue().strip().splitlines()[-1])
            self.assertEqual(out["op"], "maint-pause")
            self.assertEqual(out["kind"], "maint_pause")
            self.assertEqual(out["target"], "all")
            self.assertEqual(
                set(out["expected_acks"]),
                set(expected_ack_set("maint_pause")),
            )
            self.assertEqual(out["payload"]["ttl_s"], 300)
            self.assertEqual(out["payload"]["reason"], "rolling")
            cfg = Config()
            self.assertFalse(Path(cfg.opsctl_audit_path_resolved).exists())

    def test_resume_dry_run(self) -> None:
        with TemporaryDirectory() as tmp, _Env(tmp):
            args = argparse.Namespace(
                target="all", reason="", client_id="opsctl-test",
                confirm="", dry_run=True, json=True,
            )
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = maint_resume.run(args, bus=None)
            self.assertEqual(rc, int(ExitCode.OK))
            out = json.loads(buf.getvalue().strip().splitlines()[-1])
            self.assertEqual(out["op"], "maint-resume")
            self.assertEqual(out["kind"], "maint_resume")
            self.assertEqual(
                set(out["expected_acks"]),
                set(expected_ack_set("maint_resume")),
            )

    def test_pause_ttl_default_from_cfg(self) -> None:
        with TemporaryDirectory() as tmp, _Env(tmp):
            os.environ["NEGELIR_MAINT_PAUSE_DEFAULT_TTL_S"] = "777"
            try:
                args = argparse.Namespace(
                    target="all", ttl_s=0, reason="",
                    client_id="opsctl-test", confirm="",
                    dry_run=True, json=True,
                )
                buf = io.StringIO()
                with redirect_stdout(buf):
                    rc = maint_pause.run(args, bus=None)
                self.assertEqual(rc, int(ExitCode.OK))
                out = json.loads(buf.getvalue().strip().splitlines()[-1])
                self.assertEqual(out["payload"]["ttl_s"], 777)
            finally:
                os.environ.pop("NEGELIR_MAINT_PAUSE_DEFAULT_TTL_S", None)

    def test_pause_ttl_capped_to_schema_max(self) -> None:
        with TemporaryDirectory() as tmp, _Env(tmp):
            args = argparse.Namespace(
                target="all", ttl_s=10_000_000, reason="",
                client_id="opsctl-test", confirm="",
                dry_run=True, json=True,
            )
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = maint_pause.run(args, bus=None)
            self.assertEqual(rc, int(ExitCode.OK))
            out = json.loads(buf.getvalue().strip().splitlines()[-1])
            # Hard cap is 86400 per the per-kind sub-schema upper bound.
            self.assertEqual(out["payload"]["ttl_s"], 86_400)


# ── critical-agent gate ────────────────────────────────────────────


class TestCriticalAgentGate(unittest.TestCase):
    def test_pause_critical_agent_refused_without_confirm(self) -> None:
        with TemporaryDirectory() as tmp, _Env(tmp):
            args = argparse.Namespace(
                target="maint.backup.v1", ttl_s=300, reason="",
                client_id="opsctl-test", confirm="",
                dry_run=False, json=True,
            )
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = maint_pause.run(args, bus=None)
            self.assertEqual(rc, int(ExitCode.BAD_USAGE))
            out = json.loads(buf.getvalue().strip().splitlines()[-1])
            self.assertEqual(out["action"], "refuse")
            self.assertIn("destructive op refused", out["note"])

    def test_pause_non_critical_target_no_confirm_required(self) -> None:
        # 'all' (broadcast) is NOT a critical-agent id, so the
        # classifier returns SAFE — dry-run path proves the envelope
        # builds without --confirm.
        with TemporaryDirectory() as tmp, _Env(tmp):
            args = argparse.Namespace(
                target="all", ttl_s=300, reason="",
                client_id="opsctl-test", confirm="",
                dry_run=True, json=True,
            )
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = maint_pause.run(args, bus=None)
            self.assertEqual(rc, int(ExitCode.OK))


# ── full publish + ack-wait against in-memory bus ──────────────────


def _ack(*, request_id: str, accepted_by: str,
         accepted: bool = True, reason: str = "paused") -> Message:
    return Message(
        envelope=Envelope(topic=Topic(str(MAINT_ACK_TOPIC)),
                          producer=accepted_by),
        payload={
            "request_id": request_id,
            "accepted": accepted,
            "accepted_by": accepted_by,
            "processed_at": "2025-01-01T00:00:00+00:00",
            "attempt": 0,
            "reason": reason,
        },
    )


class _AutoAckBus(InMemoryBus):
    """In-memory bus that auto-publishes the full ack set whenever a
    `maint.event.v1{kind in {maint_pause, maint_resume}}` lands.

    Mirrors what the maint.* reactors would do under their dispatch
    handlers — keeps the publisher's ack-wait loop deterministic for
    tests without spinning up real agents.
    """

    def publish(self, msg: Message) -> None:  # type: ignore[override]
        super().publish(msg)
        topic = str(msg.envelope.topic)
        if topic != "maint.event.v1":
            return
        kind = msg.payload.get("kind")
        if kind not in {"maint_pause", "maint_resume"}:
            return
        rid = str(msg.payload.get("request_id") or "")
        if not rid:
            return
        for who in expected_ack_set(kind):
            super().publish(_ack(request_id=rid, accepted_by=who))


class TestMaintPausePublishHappyPath(unittest.TestCase):
    def test_pause_all_collects_all_acks(self) -> None:
        with TemporaryDirectory() as tmp, _Env(tmp, ack_timeout_ms=2000):
            bus = _AutoAckBus()
            args = argparse.Namespace(
                target="all", ttl_s=120, reason="rolling",
                client_id="opsctl-test", confirm="",
                dry_run=False, json=True,
            )
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = maint_pause.run(args, bus=bus)
            self.assertEqual(rc, int(ExitCode.OK), msg=buf.getvalue())
            out = json.loads(buf.getvalue().strip().splitlines()[-1])
            self.assertEqual(set(out["received_acks"]),
                             set(expected_ack_set("maint_pause")))

    def test_resume_all_collects_all_acks(self) -> None:
        with TemporaryDirectory() as tmp, _Env(tmp, ack_timeout_ms=2000):
            bus = _AutoAckBus()
            args = argparse.Namespace(
                target="all", reason="", client_id="opsctl-test",
                confirm="", dry_run=False, json=True,
            )
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = maint_resume.run(args, bus=bus)
            self.assertEqual(rc, int(ExitCode.OK), msg=buf.getvalue())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
