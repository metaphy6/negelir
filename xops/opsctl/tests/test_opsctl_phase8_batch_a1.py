"""Phase 8 §8.1 batch-A1 — opsctl subcommands ``scale``, ``dlq-replay``,
``dlq-unfreeze``, ``denylist-decimate-now``.

Covers, per the slice-A landing checklist:

* ``ops.scale``: classifier flags ``replicas_zero`` (CONFIRM) and
  ``reduction_over_50pct`` (CONFIRM) when the operator passes
  ``--current``; cancellation (replicas=-1) is SAFE.
* ``ops.dlq-replay``: ``--drop`` flips to CONFIRM; PII-prefixed
  topic without ``--confirm-pii`` is REFUSED outright; vanilla
  replay on a non-PII topic is SAFE.
* ``ops.dlq-unfreeze``: SAFE + idempotent; rejects a target that
  does not end in ``.dlq``.
* ``ops.denylist-decimate-now``: SAFE under both ``--target all``
  and a subject prefix.

All assertions go through the dry-run summary so we never touch
Redis or the bus during the unit suite.
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

from xops.opsctl._exit_codes import ExitCode
from xops.opsctl.subcommands import (
    denylist_decimate_now,
    dlq_replay,
    dlq_unfreeze,
    scale,
)


class _Env:
    """Isolate audit/spool/lock dirs so tests do not collide."""

    def __init__(self, tmp: str, *, critical: str = "consensus.v1,sec.rate.v1,maint.backup.v1") -> None:
        self.patches = {
            "NEGELIR_OPSCTL_AUDIT_PATH": str(Path(tmp) / "audit.csv"),
            "NEGELIR_OPSCTL_SPOOL_DIR": str(Path(tmp) / "spool"),
            "NEGELIR_OPSCTL_LOCK_DIR": str(Path(tmp) / "locks"),
            "NEGELIR_OPSCTL_ACK_TIMEOUT_MS": "1000",
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


def _run(module, **fields) -> tuple[int, dict, str]:
    """Invoke a subcommand's run() in dry-run / json mode and parse.

    Returns ``(exit_code, parsed_summary_or_empty, raw_stdout)``.
    """
    args = argparse.Namespace(**fields)
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = module.run(args, bus=None)
    raw = buf.getvalue()
    last = raw.strip().splitlines()[-1] if raw.strip() else ""
    parsed: dict = {}
    if last:
        try:
            parsed = json.loads(last)
        except json.JSONDecodeError:
            parsed = {}
    return rc, parsed, raw


# ── ops.scale ──────────────────────────────────────────────────────


class TestScaleClassifier(unittest.TestCase):
    def test_dry_run_safe_when_growing_with_known_current(self) -> None:
        with TemporaryDirectory() as tmp, _Env(tmp):
            rc, out, _ = _run(
                scale,
                target="predictor.elo.v1",
                replicas=8,
                ttl_s=600,
                current=4,
                reason="capacity",
                client_id="opsctl-test",
                confirm="",
                dry_run=True,
                json=True,
            )
            self.assertEqual(rc, int(ExitCode.OK))
            self.assertEqual(out["op"], "scale")
            self.assertEqual(out["kind"], "manual_scale_pin")
            self.assertEqual(out["payload"]["replicas"], 8)
            self.assertEqual(out["payload"]["ttl_s"], 600)

    def test_replicas_zero_requires_confirm(self) -> None:
        with TemporaryDirectory() as tmp, _Env(tmp):
            # No --confirm: CONFIRM tier rejects with BAD_USAGE.
            rc, _, _ = _run(
                scale,
                target="predictor.elo.v1",
                replicas=0,
                ttl_s=0,
                current=4,
                reason="drain",
                client_id="opsctl-test",
                confirm="",
                dry_run=False,
                json=True,
            )
            self.assertEqual(rc, int(ExitCode.BAD_USAGE))

    def test_over_50pct_reduction_with_explicit_current_requires_confirm(self) -> None:
        with TemporaryDirectory() as tmp, _Env(tmp):
            rc, _, _ = _run(
                scale,
                target="predictor.elo.v1",
                replicas=1,
                ttl_s=0,
                current=10,
                reason="cooling",
                client_id="opsctl-test",
                confirm="",
                dry_run=False,
                json=True,
            )
            self.assertEqual(rc, int(ExitCode.BAD_USAGE))

    def test_cancel_pin_is_safe(self) -> None:
        with TemporaryDirectory() as tmp, _Env(tmp):
            rc, out, _ = _run(
                scale,
                target="predictor.elo.v1",
                replicas=-1,
                ttl_s=0,
                current=-1,
                reason="resume autonomous",
                client_id="opsctl-test",
                confirm="",
                dry_run=True,
                json=True,
            )
            self.assertEqual(rc, int(ExitCode.OK))
            self.assertEqual(out["payload"]["replicas"], -1)


# ── ops.dlq-replay ─────────────────────────────────────────────────


class TestDlqReplayClassifier(unittest.TestCase):
    def test_vanilla_replay_is_safe(self) -> None:
        with TemporaryDirectory() as tmp, _Env(tmp):
            rc, out, _ = _run(
                dlq_replay,
                target="ingest.feed.v1.dlq",
                max_msgs=50,
                drop=False,
                confirm_pii=False,
                reason="drain backlog",
                client_id="opsctl-test",
                confirm="",
                dry_run=True,
                json=True,
            )
            self.assertEqual(rc, int(ExitCode.OK))
            self.assertEqual(out["op"], "dlq-replay")
            self.assertEqual(out["target"], "ingest.feed.v1.dlq")

    def test_drop_requires_confirm(self) -> None:
        with TemporaryDirectory() as tmp, _Env(tmp):
            rc, _, _ = _run(
                dlq_replay,
                target="ingest.feed.v1.dlq",
                max_msgs=10,
                drop=True,
                confirm_pii=False,
                reason="poison purge",
                client_id="opsctl-test",
                confirm="",
                dry_run=False,
                json=True,
            )
            self.assertEqual(rc, int(ExitCode.BAD_USAGE))

    def test_pii_topic_without_confirm_is_refused(self) -> None:
        # REFUSE blocks even in dry-run.
        with TemporaryDirectory() as tmp, _Env(tmp):
            rc, out, _ = _run(
                dlq_replay,
                target="sec.alert.v1.dlq",
                max_msgs=0,
                drop=False,
                confirm_pii=False,
                reason="",
                client_id="opsctl-test",
                confirm="",
                dry_run=True,
                json=True,
            )
            self.assertEqual(rc, int(ExitCode.BAD_USAGE))
            self.assertEqual(out.get("action"), "refuse")

    def test_pii_topic_with_confirm_pii_clears_refuse(self) -> None:
        # confirm_pii flag flips REFUSE → SAFE; dry-run completes.
        with TemporaryDirectory() as tmp, _Env(tmp):
            rc, out, _ = _run(
                dlq_replay,
                target="sec.alert.v1.dlq",
                max_msgs=0,
                drop=False,
                confirm_pii=True,
                reason="audited override",
                client_id="opsctl-test",
                confirm="",
                dry_run=True,
                json=True,
            )
            self.assertEqual(rc, int(ExitCode.OK))
            self.assertEqual(out["target"], "sec.alert.v1.dlq")

    def test_target_must_end_in_dlq(self) -> None:
        with TemporaryDirectory() as tmp, _Env(tmp):
            rc, _, _ = _run(
                dlq_replay,
                target="ingest.feed.v1",
                max_msgs=0,
                drop=False,
                confirm_pii=False,
                reason="",
                client_id="opsctl-test",
                confirm="",
                dry_run=True,
                json=True,
            )
            self.assertEqual(rc, int(ExitCode.BAD_USAGE))


# ── ops.dlq-unfreeze ───────────────────────────────────────────────


class TestDlqUnfreeze(unittest.TestCase):
    def test_safe_dry_run(self) -> None:
        with TemporaryDirectory() as tmp, _Env(tmp):
            rc, out, _ = _run(
                dlq_unfreeze,
                target="ingest.feed.v1.dlq",
                reason="post-incident",
                client_id="opsctl-test",
                confirm="",
                dry_run=True,
                json=True,
            )
            self.assertEqual(rc, int(ExitCode.OK))
            self.assertEqual(out["op"], "dlq-unfreeze")
            self.assertEqual(out["kind"], "dlq_unfreeze")

    def test_target_must_end_in_dlq(self) -> None:
        with TemporaryDirectory() as tmp, _Env(tmp):
            rc, _, _ = _run(
                dlq_unfreeze,
                target="ingest.feed.v1",
                reason="",
                client_id="opsctl-test",
                confirm="",
                dry_run=True,
                json=True,
            )
            self.assertEqual(rc, int(ExitCode.BAD_USAGE))


# ── ops.denylist-decimate-now ──────────────────────────────────────


class TestDenylistDecimateNow(unittest.TestCase):
    def test_default_target_all_is_safe(self) -> None:
        with TemporaryDirectory() as tmp, _Env(tmp):
            rc, out, _ = _run(
                denylist_decimate_now,
                target="all",
                reason="capacity relief",
                client_id="opsctl-test",
                confirm="",
                dry_run=True,
                json=True,
            )
            self.assertEqual(rc, int(ExitCode.OK))
            self.assertEqual(out["op"], "denylist-decimate-now")
            self.assertEqual(out["target"], "all")

    def test_specific_prefix_is_safe(self) -> None:
        with TemporaryDirectory() as tmp, _Env(tmp):
            rc, out, _ = _run(
                denylist_decimate_now,
                target="ip:203.0.113.",
                reason="",
                client_id="opsctl-test",
                confirm="",
                dry_run=True,
                json=True,
            )
            self.assertEqual(rc, int(ExitCode.OK))
            self.assertEqual(out["target"], "ip:203.0.113.")


# ── Registry presence ──────────────────────────────────────────────


class TestRegistryWiring(unittest.TestCase):
    def test_all_four_modules_registered(self) -> None:
        from xops.opsctl import subcommands as reg

        names = {m.NAME for m in reg.SUBCOMMANDS}
        for expected in ("scale", "dlq-replay", "dlq-unfreeze", "denylist-decimate-now"):
            self.assertIn(expected, names)


if __name__ == "__main__":
    unittest.main()
