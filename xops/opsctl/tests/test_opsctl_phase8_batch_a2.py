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

from swarm.sdk.bus import InMemoryBus
from swarm.sdk.types import Message
from xops.opsctl import spool_reconciler
from xops.opsctl._exit_codes import ExitCode
from xops.opsctl.subcommands import dlq_replay, dlq_show, scale_pin, scale_unpin, spool_show


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


def _publish_predict_request_dlq(
    bus: InMemoryBus,
    request_id: str,
    *,
    qa_correlation_id: str | None,
    match_id: str,
    market: str,
    producer: str = "predictor.elo.v1",
) -> None:
    payload = {
        "request_id": request_id,
        "match_id": match_id,
        "market": market,
    }
    if qa_correlation_id is not None:
        payload["metadata"] = {"qa_correlation_id": qa_correlation_id}
    bus.publish(Message.new(
        "predict.request.dlq",
        {
            "original_topic": "predict.request",
            "reason": "retry_budget_exhausted",
            "attempts": 2,
            "payload": payload,
        },
        producer=producer,
    ))


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


class TestDlqShow(unittest.TestCase):
    def test_filters_entries_by_qa_correlation_id(self) -> None:
        bus = InMemoryBus()
        qa_id = "qa-corr-123"
        for request_id in ("req-1", "req-2", "req-3"):
            _publish_predict_request_dlq(
                bus,
                request_id,
                qa_correlation_id=qa_id,
                match_id="m-1",
                market="1x2",
            )
        _publish_predict_request_dlq(
            bus,
            "req-other",
            qa_correlation_id="qa-other",
            match_id="m-2",
            market="ah",
            producer="predictor.xgb.v1",
        )
        _publish_predict_request_dlq(
            bus,
            "req-legacy",
            qa_correlation_id=None,
            match_id="m-3",
            market="btts",
        )

        args = argparse.Namespace(
            topic="predict.request.dlq",
            limit=100,
            qa_correlation_id=qa_id,
            json=True,
        )
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = dlq_show.run(args, bus=bus)

        self.assertEqual(rc, int(ExitCode.OK))
        doc = json.loads(buf.getvalue().strip())
        self.assertEqual(doc["op"], "dlq-show")
        self.assertEqual(doc["topic"], "predict.request.dlq")
        self.assertEqual(doc["qa_correlation_id"], qa_id)
        self.assertEqual(doc["count"], 3)
        self.assertEqual(
            sorted(row["request_id"] for row in doc["entries"]),
            ["req-1", "req-2", "req-3"],
        )

    def test_proof_qa_fanout_show_returns_exact_three_predict_dlqs(self) -> None:
        bus = InMemoryBus()
        qa_id = "qa-fanout-msg-001"
        expected_request_ids = ["pred-req-1", "pred-req-2", "pred-req-3"]
        for offset, request_id in enumerate(expected_request_ids, start=1):
            _publish_predict_request_dlq(
                bus,
                request_id,
                qa_correlation_id=qa_id,
                match_id=f"match-{offset}",
                market="1x2",
            )
        _publish_predict_request_dlq(
            bus,
            "pred-req-other",
            qa_correlation_id="qa-other-msg",
            match_id="match-other",
            market="ah",
        )
        _publish_predict_request_dlq(
            bus,
            "pred-req-legacy",
            qa_correlation_id=None,
            match_id="match-legacy",
            market="btts",
        )

        args = argparse.Namespace(
            topic="predict.request.dlq",
            limit=100,
            qa_correlation_id=qa_id,
            json=True,
        )
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = dlq_show.run(args, bus=bus)

        self.assertEqual(rc, int(ExitCode.OK))
        doc = json.loads(buf.getvalue().strip())
        self.assertEqual(doc["count"], 3)
        self.assertEqual(
            sorted(row["request_id"] for row in doc["entries"]),
            expected_request_ids,
        )
        self.assertTrue(all(row["qa_correlation_id"] == qa_id for row in doc["entries"]))

    def test_ignores_non_string_qa_correlation_values_to_avoid_pii_bridging(self) -> None:
        bus = InMemoryBus()
        bus.publish(Message.new(
            "predict.request.dlq",
            {
                "original_topic": "predict.request",
                "reason": "retry_budget_exhausted",
                "attempts": 2,
                "payload": {
                    "request_id": "req-malformed",
                    "match_id": "m-1",
                    "market": "1x2",
                    "qa_correlation_id": {"question": "Ali'nin kuponu ne oldu?"},
                    "metadata": {
                        "qa_correlation_id": ["Ayse", "555-0100"],
                    },
                    "sanitized_text": "Ali'nin kuponu ne oldu?",
                },
            },
            producer="predictor.elo.v1",
        ))

        args = argparse.Namespace(
            topic="predict.request.dlq",
            limit=100,
            qa_correlation_id="Ali'nin kuponu ne oldu?",
            json=True,
        )
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = dlq_show.run(args, bus=bus)

        self.assertEqual(rc, int(ExitCode.OK))
        doc = json.loads(buf.getvalue().strip())
        self.assertEqual(doc["count"], 0)
        self.assertEqual(doc["entries"], [])

    def test_bad_usage_when_topic_is_not_a_dlq(self) -> None:
        rc, out, raw = _run(
            dlq_show,
            topic="predict.request",
            limit=10,
            qa_correlation_id="",
            json=True,
        )
        self.assertEqual(rc, int(ExitCode.BAD_USAGE))
        self.assertEqual(out, {})
        self.assertEqual(raw, "")

    def test_proof_legacy_entries_stay_in_no_correlation_bucket(self) -> None:
        bus = InMemoryBus()
        _publish_predict_request_dlq(
            bus,
            "legacy-1",
            qa_correlation_id=None,
            match_id="legacy-match-1",
            market="1x2",
        )
        _publish_predict_request_dlq(
            bus,
            "legacy-2",
            qa_correlation_id=None,
            match_id="legacy-match-2",
            market="ah",
        )
        _publish_predict_request_dlq(
            bus,
            "corr-1",
            qa_correlation_id="qa-corr-keep",
            match_id="corr-match-1",
            market="btts",
        )

        json_args = argparse.Namespace(
            topic="predict.request.dlq",
            limit=100,
            qa_correlation_id="",
            json=True,
        )
        json_buf = io.StringIO()
        with redirect_stdout(json_buf):
            rc = dlq_show.run(json_args, bus=bus)

        self.assertEqual(rc, int(ExitCode.OK))
        doc = json.loads(json_buf.getvalue().strip())
        legacy_rows = [row for row in doc["entries"] if not row["qa_correlation_id"]]
        self.assertEqual(
            sorted(row["request_id"] for row in legacy_rows),
            ["legacy-1", "legacy-2"],
        )

        plain_args = argparse.Namespace(
            topic="predict.request.dlq",
            limit=100,
            qa_correlation_id="",
            json=False,
        )
        plain_buf = io.StringIO()
        with redirect_stdout(plain_buf):
            rc = dlq_show.run(plain_args, bus=bus)

        self.assertEqual(rc, int(ExitCode.OK))
        plain = plain_buf.getvalue()
        self.assertIn("request_id=legacy-1", plain)
        self.assertIn("request_id=legacy-2", plain)
        self.assertIn("qa_correlation_id=-", plain)


class TestDlqReplay(unittest.TestCase):
    def test_predict_request_batch_replay_accepts_qa_correlation_id(self) -> None:
        with TemporaryDirectory() as tmp, _Env(tmp):
            rc, out, _ = _run(
                dlq_replay,
                target="predict.request.dlq",
                max_msgs=25,
                qa_correlation_id="qa-corr-123",
                drop=False,
                confirm_pii=False,
                confirm_destructive="",
                reason="replay qa batch",
                client_id="opsctl-test",
                confirm="",
                dry_run=True,
                json=True,
            )
            self.assertEqual(rc, int(ExitCode.OK))
            self.assertEqual(out["payload"]["qa_correlation_id"], "qa-corr-123")

    def test_proof_replay_by_correlation_id_targets_same_original_request_ids(self) -> None:
        bus = InMemoryBus()
        qa_id = "qa-fanout-msg-777"
        expected_request_ids = ["pred-a", "pred-b", "pred-c"]
        for idx, request_id in enumerate(expected_request_ids, start=1):
            _publish_predict_request_dlq(
                bus,
                request_id,
                qa_correlation_id=qa_id,
                match_id=f"match-{idx}",
                market="1x2",
            )
        _publish_predict_request_dlq(
            bus,
            "pred-other",
            qa_correlation_id="qa-other",
            match_id="match-other",
            market="ou_2_5",
        )

        show_args = argparse.Namespace(
            topic="predict.request.dlq",
            limit=100,
            qa_correlation_id=qa_id,
            json=True,
        )
        show_buf = io.StringIO()
        with redirect_stdout(show_buf):
            show_rc = dlq_show.run(show_args, bus=bus)

        self.assertEqual(show_rc, int(ExitCode.OK))
        show_doc = json.loads(show_buf.getvalue().strip())
        self.assertEqual(
            sorted(row["request_id"] for row in show_doc["entries"]),
            expected_request_ids,
        )

        with TemporaryDirectory() as tmp, _Env(tmp):
            rc, out, _ = _run(
                dlq_replay,
                target="predict.request.dlq",
                max_msgs=25,
                qa_correlation_id=qa_id,
                drop=False,
                confirm_pii=False,
                confirm_destructive="",
                reason="replay qa fanout batch",
                client_id="opsctl-test",
                confirm="",
                dry_run=True,
                json=True,
            )

        self.assertEqual(rc, int(ExitCode.OK))
        self.assertEqual(out["payload"]["qa_correlation_id"], qa_id)
        self.assertEqual(show_doc["count"], 3)

    def test_qa_correlation_id_filter_is_restricted_to_predict_request_dlq(self) -> None:
        with TemporaryDirectory() as tmp, _Env(tmp):
            rc, out, raw = _run(
                dlq_replay,
                target="predict.vote.dlq",
                max_msgs=25,
                qa_correlation_id="qa-corr-123",
                drop=False,
                confirm_pii=False,
                confirm_destructive="",
                reason="replay qa batch",
                client_id="opsctl-test",
                confirm="",
                dry_run=True,
                json=True,
            )
            self.assertEqual(rc, int(ExitCode.BAD_USAGE))
            self.assertEqual(out, {})
            self.assertEqual(raw, "")


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
        for required in ("scale-pin", "scale-unpin", "spool-show", "dlq-show"):
            self.assertIn(required, names)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
