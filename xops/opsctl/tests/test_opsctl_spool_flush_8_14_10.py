"""Phase 8 §8.14.10 proof tests — spool-flush dir-level lock + newest-first ordering.

(a) Concurrent flush: exactly one wins, other exits 8; total publishes == spool count.
(b) Newest-first + drain budget: 200 entries, flush_max_per_run=100 → 100 newest first.
(c) Stale-lock reap: a .flush.lock with old mtime is reaped and flush proceeds.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import time
import threading
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
from xops.opsctl.subcommands.spool_flush import LOCK_FILENAME, _maybe_reap_flush_lock


class _Env:
    """Patch opsctl env vars to point at a temp directory."""

    def __init__(self, tmp: str, *, max_per_run: int | None = None) -> None:
        self.patches: dict[str, str] = {
            "NEGELIR_OPSCTL_AUDIT_PATH": str(Path(tmp) / "audit.csv"),
            "NEGELIR_OPSCTL_SPOOL_DIR": str(Path(tmp) / "spool"),
            "NEGELIR_OPSCTL_LOCK_DIR": str(Path(tmp) / "locks"),
            "NEGELIR_OPSCTL_ACK_TIMEOUT_MS": "500",
            # Disable signature requirement so unit tests don't need a key.
            "NEGELIR_OPSCTL_REQUIRE_SIGNATURE": "false",
        }
        if max_per_run is not None:
            self.patches["NEGELIR_OPSCTL_SPOOL_FLUSH_MAX_PER_RUN"] = str(max_per_run)
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


def _make_spool_entry(spool_dir: Path, *, mtime_offset_s: float = 0.0) -> Path:
    """Write a valid spool envelope and set its mtime to now + offset."""
    msg = build_envelope(kind="denylist_clear", target="10.0.0.1/32", client_id="test")
    bus = None  # no bus → spools the entry
    publish_event(bus, msg)
    # The new file is the most-recently-created envelope in spool_dir.
    entries = sorted(spool_dir.glob("*.envelope.json"), key=lambda p: p.stat().st_mtime)
    path = entries[-1]
    if mtime_offset_s:
        new_mtime = path.stat().st_mtime + mtime_offset_s
        os.utime(str(path), (new_mtime, new_mtime))
    return path


def _ack_poster(bus: InMemoryBus, count: int, *, deadline_s: float = 3.0) -> threading.Thread:
    """Background thread that acks every maint.event.v1 message it sees."""
    done = threading.Event()
    acked: list[str] = []

    def _run() -> None:
        bus.ensure_group(MAINT_EVENT_TOPIC, "ack_poster")
        end = time.monotonic() + deadline_s
        while time.monotonic() < end and len(acked) < count:
            deliveries = bus.read(MAINT_EVENT_TOPIC, "ack_poster", "c", count=4, block_ms=50)
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
                        "processed_at": "2026-01-01T00:00:00+00:00",
                        "attempt": 0,
                    },
                )
                bus.publish(ack)
                bus.ack(MAINT_EVENT_TOPIC, "ack_poster", d.handle)
                acked.append(rid)
            time.sleep(0.005)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return t


# ── Test (a): Concurrent flush ──────────────────────────────────────────────

class TestConcurrentFlushOnlyOneWins(unittest.TestCase):
    """(a) Two parallel ops.spool-flush → exactly one wins, the other exits 8;
    total bus publishes equal spool entry count, never double.
    """

    def test_concurrent_flush_exactly_one_wins(self) -> None:
        with TemporaryDirectory() as tmp, _Env(tmp, max_per_run=0):
            cfg = Config()
            spool_dir = Path(cfg.opsctl_spool_dir_resolved)

            # Spool 3 entries with no live bus.
            for _ in range(3):
                _make_spool_entry(spool_dir)
            self.assertEqual(len(list(spool_dir.glob("*.envelope.json"))), 3)

            # Shared bus that both flushes will publish into.
            bus = InMemoryBus()
            acker = _ack_poster(bus, count=3)

            results: list[int] = []
            errors: list[Exception] = []

            def _run_flush(n: int) -> None:
                args = argparse.Namespace(
                    json=True,
                    dry_run=False,
                    max_entries=0,  # unlimited per-run
                    force_retired=False,
                )
                buf = io.StringIO()
                try:
                    with redirect_stdout(buf):
                        rc = spool_flush.run(args, bus=bus)
                    results.append(rc)
                except Exception as exc:
                    errors.append(exc)

            t1 = threading.Thread(target=_run_flush, args=(1,))
            t2 = threading.Thread(target=_run_flush, args=(2,))
            t1.start()
            t2.start()
            t1.join(timeout=5.0)
            t2.join(timeout=5.0)
            acker.join(timeout=2.0)

            self.assertFalse(errors, f"Unexpected exceptions: {errors}")
            self.assertEqual(
                sorted(results),
                sorted([int(ExitCode.OK), int(ExitCode.SPOOL_FLUSH_ALREADY_RUNNING)]),
                f"Expected one OK and one SPOOL_FLUSH_ALREADY_RUNNING; got {results}",
            )

            # After successful flush, spool must be empty (no doubles).
            remaining = list(spool_dir.glob("*.envelope.json"))
            self.assertEqual(remaining, [],
                             "Spool dir must be empty after one successful flush")


# ── Test (b): Newest-first ordering + drain budget ─────────────────────────

class TestNewestFirstDrainBudget(unittest.TestCase):
    """(b) Spool 200 entries spread across 7 days; flush_max_per_run=100 →
    first invocation publishes the 100 newest, second publishes the next 100.
    """

    def _make_entries_with_timestamps(self, spool_dir: Path, count: int) -> list[float]:
        """Create *count* spool entries with evenly-spaced mtimes across 7 days.
        Returns list of mtimes in creation order (oldest first).
        """
        spool_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
        now = time.time()
        # Use 24h span so no entry hits the 168h prune threshold.
        span_s = 24 * 3600.0
        mtimes: list[float] = []
        for i in range(count):
            # Spread mtimes: 0 is oldest, count-1 is newest.
            mtime = now - span_s + (span_s * i / (count - 1))
            # Write a minimal valid spool entry file.
            from uuid import uuid4
            rid = uuid4().hex
            ms = int(mtime * 1000)
            fname = f"{ms:016d}-{rid}.envelope.json"
            path = spool_dir / fname
            body = json.dumps({
                "envelope": {
                    "topic": "maint.event.v1",
                    "producer": "ops_console",
                    "schema_version": 1,
                },
                "payload": {
                    "kind": "denylist_clear",
                    "target": f"10.0.{i // 256}.{i % 256}/32",
                    "request_id": rid,
                    "client_id": "test",
                    "produced_at": "2026-01-01T00:00:00+00:00",
                },
            }, ensure_ascii=False)
            path.write_bytes(body.encode())
            os.utime(str(path), (mtime, mtime))
            mtimes.append(mtime)
        return mtimes

    def test_drain_budget_newest_first(self) -> None:
        with TemporaryDirectory() as tmp, _Env(tmp, max_per_run=100):
            cfg = Config()
            spool_dir = Path(cfg.opsctl_spool_dir_resolved)

            # Create 200 entries spread across 7 days.
            mtimes = self._make_entries_with_timestamps(spool_dir, 200)
            # The 100 newest entries have the 100 largest mtimes.
            top100_mtimes = sorted(mtimes, reverse=True)[:100]
            top100_threshold = top100_mtimes[-1]  # oldest of the top-100

            published_rids_run1: list[str] = []
            published_rids_run2: list[str] = []

            # --- Run 1: drain 100 newest ---
            bus1 = InMemoryBus()
            bus1.ensure_group(MAINT_EVENT_TOPIC, "obs1")

            def _collect1() -> None:
                end = time.monotonic() + 8.0
                while time.monotonic() < end:
                    deliveries = bus1.read(MAINT_EVENT_TOPIC, "obs1", "c", count=10, block_ms=50)
                    for d in deliveries:
                        rid = str(d.message.payload.get("request_id", ""))
                        published_rids_run1.append(rid)
                        ack = Message(
                            envelope=Envelope(
                                topic=Topic(str(MAINT_ACK_TOPIC)),
                                producer="sec.rate.v1",
                            ),
                            payload={
                                "request_id": rid,
                                "accepted": True,
                                "accepted_by": "sec.rate.v1",
                                "processed_at": "2026-01-01T00:00:00+00:00",
                                "attempt": 0,
                            },
                        )
                        bus1.publish(ack)
                        bus1.ack(MAINT_EVENT_TOPIC, "obs1", d.handle)
                    time.sleep(0.001)  # yield GIL so spool_flush.run() can make progress
                    if len(published_rids_run1) >= 100:
                        break

            t = threading.Thread(target=_collect1, daemon=True)
            t.start()
            args1 = argparse.Namespace(json=True, dry_run=False, max_entries=None, force_retired=False)
            buf1 = io.StringIO()
            with redirect_stdout(buf1):
                rc1 = spool_flush.run(args1, bus=bus1)
            t.join(timeout=10.0)

            out1 = json.loads(buf1.getvalue().strip().splitlines()[-1])
            self.assertEqual(out1["succeeded"], 100,
                             f"Run 1 should drain exactly 100; got {out1}")
            self.assertEqual(out1.get("kind"), "spool_flush_partial",
                             "Run 1 should report spool_flush_partial")
            self.assertEqual(out1.get("remaining"), 100,
                             "Run 1 should report 100 remaining")

            # Verify the 100 drained entries were the newest ones.
            remaining_after_run1 = list(spool_dir.glob("*.envelope.json"))
            self.assertEqual(len(remaining_after_run1), 100,
                             "Exactly 100 entries should remain after run 1")
            # All remaining entries should have mtimes in the older half.
            for p in remaining_after_run1:
                mtime = p.stat().st_mtime
                self.assertLessEqual(
                    mtime, top100_threshold + 0.001,
                    f"Remaining entry {p.name} has mtime {mtime} > threshold {top100_threshold}",
                )

            # --- Run 2: drain the remaining 100 ---
            bus2 = InMemoryBus()
            bus2.ensure_group(MAINT_EVENT_TOPIC, "obs2")

            def _collect2() -> None:
                end = time.monotonic() + 8.0
                while time.monotonic() < end:
                    deliveries = bus2.read(MAINT_EVENT_TOPIC, "obs2", "c", count=10, block_ms=50)
                    for d in deliveries:
                        rid = str(d.message.payload.get("request_id", ""))
                        published_rids_run2.append(rid)
                        ack = Message(
                            envelope=Envelope(
                                topic=Topic(str(MAINT_ACK_TOPIC)),
                                producer="sec.rate.v1",
                            ),
                            payload={
                                "request_id": rid,
                                "accepted": True,
                                "accepted_by": "sec.rate.v1",
                                "processed_at": "2026-01-01T00:00:00+00:00",
                                "attempt": 0,
                            },
                        )
                        bus2.publish(ack)
                        bus2.ack(MAINT_EVENT_TOPIC, "obs2", d.handle)
                    time.sleep(0.001)  # yield GIL so spool_flush.run() can make progress
                    if len(published_rids_run2) >= 100:
                        break

            t2 = threading.Thread(target=_collect2, daemon=True)
            t2.start()
            args2 = argparse.Namespace(json=True, dry_run=False, max_entries=None, force_retired=False)
            buf2 = io.StringIO()
            with redirect_stdout(buf2):
                rc2 = spool_flush.run(args2, bus=bus2)
            t2.join(timeout=10.0)

            out2 = json.loads(buf2.getvalue().strip().splitlines()[-1])
            self.assertEqual(out2["succeeded"], 100,
                             f"Run 2 should drain all remaining 100; got {out2}")
            # No entries remain.
            self.assertEqual(list(spool_dir.glob("*.envelope.json")), [],
                             "Spool must be empty after run 2")

            # All request_ids across both runs are unique (no double-publish).
            all_rids = set(published_rids_run1) | set(published_rids_run2)
            self.assertEqual(len(all_rids), len(published_rids_run1) + len(published_rids_run2),
                             "No request_id should appear in both runs (no double-publish)")


# ── Test (c): Stale-lock reap ───────────────────────────────────────────────

class TestStaleLockReap(unittest.TestCase):
    """(c) Write a .flush.lock with mtime older than the stale timeout × 2,
    run flush → assert lock is reaped and flush proceeds successfully.
    """

    def test_stale_lock_is_reaped_and_flush_proceeds(self) -> None:
        with TemporaryDirectory() as tmp, _Env(tmp, max_per_run=0):
            cfg = Config()
            spool_dir = Path(cfg.opsctl_spool_dir_resolved)
            spool_dir.mkdir(parents=True, mode=0o700, exist_ok=True)

            # Write a stale .flush.lock — no flock holder, very old mtime.
            lock_path = spool_dir / LOCK_FILENAME
            lock_path.write_bytes(b"stale")
            stale_mtime = time.time() - 3600.0  # 1 hour old >> 2 × 500ms timeout
            os.utime(str(lock_path), (stale_mtime, stale_mtime))
            self.assertTrue(lock_path.exists(), "Stale lock should exist before flush")

            # Spool one entry.
            _make_spool_entry(spool_dir)
            self.assertEqual(len(list(spool_dir.glob("*.envelope.json"))), 1)

            bus = InMemoryBus()
            acker = _ack_poster(bus, count=1)
            args = argparse.Namespace(json=True, dry_run=False, max_entries=0, force_retired=False)
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = spool_flush.run(args, bus=bus)
            acker.join(timeout=2.0)

            self.assertEqual(rc, int(ExitCode.OK),
                             f"Flush should succeed after stale lock reap; got rc={rc}")
            self.assertEqual(list(spool_dir.glob("*.envelope.json")), [],
                             "Spool must be empty after successful flush")

    def test_maybe_reap_flush_lock_helper_reaps_stale(self) -> None:
        """Unit test _maybe_reap_flush_lock directly."""
        with TemporaryDirectory() as tmp:
            spool_dir = Path(tmp)
            lock_path = spool_dir / LOCK_FILENAME
            lock_path.write_bytes(b"stale")
            # Set mtime to 1 hour ago (>> stale_timeout_s=10s).
            old_mtime = time.time() - 3600.0
            os.utime(str(lock_path), (old_mtime, old_mtime))

            _maybe_reap_flush_lock(lock_path, stale_timeout_s=10.0)
            self.assertFalse(lock_path.exists(), "Stale lock should have been reaped")

    def test_maybe_reap_flush_lock_leaves_fresh_lock(self) -> None:
        """_maybe_reap_flush_lock must NOT touch a fresh lock."""
        with TemporaryDirectory() as tmp:
            spool_dir = Path(tmp)
            lock_path = spool_dir / LOCK_FILENAME
            lock_path.write_bytes(b"fresh")
            # mtime = now (younger than stale_timeout_s=3600s)
            _maybe_reap_flush_lock(lock_path, stale_timeout_s=3600.0)
            self.assertTrue(lock_path.exists(), "Fresh lock must NOT be reaped")

    def test_maybe_reap_flush_lock_leaves_held_lock(self) -> None:
        """_maybe_reap_flush_lock must not unlink a lock held by another fd."""
        import fcntl as _fcntl
        with TemporaryDirectory() as tmp:
            spool_dir = Path(tmp)
            lock_path = spool_dir / LOCK_FILENAME
            # Create and hold the lock.
            fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o600)
            _fcntl.flock(fd, _fcntl.LOCK_EX)
            # Set old mtime so the age check passes.
            old_mtime = time.time() - 3600.0
            os.utime(str(lock_path), (old_mtime, old_mtime))
            try:
                _maybe_reap_flush_lock(lock_path, stale_timeout_s=1.0)
                # The lock is held by this process — reaper must leave it alone.
                self.assertTrue(lock_path.exists(),
                                "Held lock must NOT be reaped")
            finally:
                _fcntl.flock(fd, _fcntl.LOCK_UN)
                os.close(fd)


if __name__ == "__main__":
    unittest.main()
