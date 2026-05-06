"""Phase 8 §8.1 batch-A2 — opsctl ``scale-pin``, ``scale-unpin``, ``spool-show``.

Covers:
* ``ops.scale-pin``: routes to ``scale.run`` with replicas/ttl_s; classifier
  flags inherit from the underlying ``ops.scale`` (confirm tier on
  ``replicas_zero``).
* ``ops.scale-unpin``: SAFE; produces a ``manual_scale_pin`` with
  ``replicas=-1`` (cancellation).
* ``ops.spool-show``: SAFE read-only listing; works on empty spool dirs;
  reads ``--json`` output deterministically.

Plus Phase 8 §8.16.2 — ``opsctl-spool-reconcile`` audit scanner.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from xops.opsctl._exit_codes import ExitCode
from xops.opsctl import spool_reconciler
from xops.opsctl.subcommands import scale_pin, scale_unpin, spool_show


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


def _run(module, **fields) -> tuple[int, dict, str]:
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


class TestScalePin(unittest.TestCase):
    def test_dry_run_safe_growth(self) -> None:
        with TemporaryDirectory() as tmp, _Env(tmp):
            rc, out, _ = _run(
                scale_pin,
                target="predictor.elo.v1",
                replicas=6,
                ttl_s=900,
                current=2,
                reason="capacity",
                client_id="opsctl-test",
                confirm="",
                dry_run=True,
                json=True,
            )
            self.assertEqual(rc, int(ExitCode.OK))
            self.assertEqual(out["kind"], "manual_scale_pin")
            self.assertEqual(out["payload"]["replicas"], 6)
            self.assertEqual(out["payload"]["ttl_s"], 900)

    def test_replicas_zero_requires_confirm(self) -> None:
        with TemporaryDirectory() as tmp, _Env(tmp):
            rc, out, _ = _run(
                scale_pin,
                target="predictor.elo.v1",
                replicas=0,
                ttl_s=300,
                current=4,
                reason="drain",
                client_id="opsctl-test",
                confirm="",
                dry_run=True,
                json=True,
            )
            # Dry-run still returns OK; the classifier flags must be
            # surfaced in the dry-run summary.
            self.assertEqual(rc, int(ExitCode.OK))
            # Dry-run summary surfaces the expected confirm token whenever
            # the classifier raised the destructive-tier gate.
            self.assertTrue(out.get("expected_confirm_token"))


class TestScaleUnpin(unittest.TestCase):
    def test_unpin_emits_minus_one(self) -> None:
        with TemporaryDirectory() as tmp, _Env(tmp):
            rc, out, _ = _run(
                scale_unpin,
                target="predictor.elo.v1",
                reason="resume autonomous scaler",
                client_id="opsctl-test",
                confirm="",
                dry_run=True,
                json=True,
            )
            self.assertEqual(rc, int(ExitCode.OK))
            self.assertEqual(out["kind"], "manual_scale_pin")
            self.assertEqual(out["payload"]["replicas"], -1)


class TestSpoolShow(unittest.TestCase):
    def test_empty_spool_dir(self) -> None:
        with TemporaryDirectory() as tmp, _Env(tmp):
            rc, out, raw = _run(
                spool_show, limit=10, json=True,
            )
            self.assertEqual(rc, int(ExitCode.OK))
            self.assertEqual(out["count"], 0)
            self.assertEqual(out["entries"], [])

    def test_lists_envelopes(self) -> None:
        with TemporaryDirectory() as tmp, _Env(tmp):
            spool = Path(tmp) / "spool"
            spool.mkdir(parents=True, exist_ok=True)
            doc = {
                "envelope": {"topic": "maint.event.v1", "producer": "opsctl"},
                "payload": {
                    "kind": "denylist_clear",
                    "target": "subj-1",
                    "produced_at": "2025-01-01T00:00:00+00:00",
                    "request_id": "req-abc",
                },
            }
            (spool / "00000-test.envelope.json").write_text(json.dumps(doc))
            rc, out, _ = _run(spool_show, limit=10, json=True)
            self.assertEqual(rc, int(ExitCode.OK))
            self.assertEqual(out["count"], 1)
            row = out["entries"][0]
            self.assertEqual(row["kind"], "denylist_clear")
            self.assertEqual(row["target"], "subj-1")
            self.assertEqual(row["request_id"], "req-abc")


# ── §8.16.2 spool-flush ack reconciler ───────────────────────────


def _write_audit(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    header = [
        "timestamp_utc", "host", "op", "target", "request_id",
        "exit_code", "expected_acks", "received_acks", "note",
    ]
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=header)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in header})


class TestSpoolReconciler(unittest.TestCase):
    def test_no_audit_returns_zero_rows(self) -> None:
        with TemporaryDirectory() as tmp:
            rows = spool_reconciler.scan(
                Path(tmp) / "missing.csv", horizon_s=3600,
            )
            self.assertEqual(rows, [])

    def test_complete_rows_are_ignored(self) -> None:
        with TemporaryDirectory() as tmp:
            audit = Path(tmp) / "audit.csv"
            now = datetime.now(timezone.utc)
            old_ts = (now - timedelta(hours=48)).isoformat(timespec="seconds")
            _write_audit(audit, [
                # Old but COMPLETE — should be ignored.
                {
                    "timestamp_utc": old_ts, "host": "h", "op": "spool-flush",
                    "target": "t1", "request_id": "r1", "exit_code": "0",
                    "expected_acks": "2", "received_acks": "2", "note": "replay: ok",
                },
            ])
            rows = spool_reconciler.scan(audit, horizon_s=3600)
            self.assertEqual(rows, [])

    def test_recent_incomplete_below_horizon_ignored(self) -> None:
        with TemporaryDirectory() as tmp:
            audit = Path(tmp) / "audit.csv"
            now = datetime.now(timezone.utc)
            recent_ts = (now - timedelta(seconds=10)).isoformat(timespec="seconds")
            _write_audit(audit, [
                {
                    "timestamp_utc": recent_ts, "host": "h", "op": "spool-flush",
                    "target": "t2", "request_id": "r2", "exit_code": "0",
                    "expected_acks": "3", "received_acks": "1", "note": "replay: partial",
                },
            ])
            rows = spool_reconciler.scan(audit, horizon_s=3600)
            self.assertEqual(rows, [])

    def test_stale_incomplete_surfaces(self) -> None:
        with TemporaryDirectory() as tmp:
            audit = Path(tmp) / "audit.csv"
            now = datetime.now(timezone.utc)
            old_ts = (now - timedelta(hours=48)).isoformat(timespec="seconds")
            _write_audit(audit, [
                {
                    "timestamp_utc": old_ts, "host": "h", "op": "spool-flush",
                    "target": "t3", "request_id": "r3", "exit_code": "0",
                    "expected_acks": "5", "received_acks": "2", "note": "replay: partial",
                },
                # Non-spool-flush rows must not appear.
                {
                    "timestamp_utc": old_ts, "host": "h", "op": "scale",
                    "target": "x", "request_id": "rx", "exit_code": "0",
                    "expected_acks": "1", "received_acks": "0", "note": "n/a",
                },
            ])
            rows = spool_reconciler.scan(audit, horizon_s=3600, now=now)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].request_id, "r3")
            self.assertEqual(rows[0].expected_acks, 5)
            self.assertEqual(rows[0].received_acks, 2)
            self.assertGreaterEqual(rows[0].age_s, 48 * 3600 - 5)

    def test_main_exits_9_when_incomplete(self) -> None:
        with TemporaryDirectory() as tmp:
            audit = Path(tmp) / "audit.csv"
            now = datetime.now(timezone.utc)
            old_ts = (now - timedelta(hours=48)).isoformat(timespec="seconds")
            _write_audit(audit, [{
                "timestamp_utc": old_ts, "host": "h", "op": "spool-flush",
                "target": "t4", "request_id": "r4", "exit_code": "0",
                "expected_acks": "2", "received_acks": "0", "note": "replay: timeout",
            }])
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = spool_reconciler.main([
                    "--audit-path", str(audit), "--horizon-h", "1", "--json",
                ])
            self.assertEqual(rc, spool_reconciler.EXIT_INCOMPLETE)
            doc = json.loads(buf.getvalue().splitlines()[-1])
            self.assertEqual(doc["incomplete_count"], 1)
            self.assertEqual(doc["rows"][0]["request_id"], "r4")

    def test_main_exits_0_when_clean(self) -> None:
        with TemporaryDirectory() as tmp:
            audit = Path(tmp) / "audit.csv"
            _write_audit(audit, [])  # header only
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = spool_reconciler.main([
                    "--audit-path", str(audit), "--horizon-h", "1", "--json",
                ])
            self.assertEqual(rc, spool_reconciler.EXIT_OK)


class TestRegistryWiring(unittest.TestCase):
    def test_new_subcommands_registered(self) -> None:
        from xops.opsctl import subcommands
        names = {m.NAME for m in subcommands.SUBCOMMANDS}
        for required in ("scale-pin", "scale-unpin", "spool-show"):
            self.assertIn(required, names)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
