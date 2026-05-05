"""Phase 8 §8.1 — re-entrancy lock unit tests."""
from __future__ import annotations

import errno
import fcntl
import os
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from xops.opsctl._lock import _lock_filename, reentrancy_lock


class TestLockFilename(unittest.TestCase):
    def test_deterministic_and_filesystem_safe(self) -> None:
        a = _lock_filename("host-1", "denylist_clear", "203.0.113.0/24")
        b = _lock_filename("host-1", "denylist_clear", "203.0.113.0/24")
        self.assertEqual(a, b, "filename must be deterministic")
        self.assertNotIn("/", a, "filename must not contain path separators")
        # Different target → different name.
        c = _lock_filename("host-1", "denylist_clear", "198.51.100.0/24")
        self.assertNotEqual(a, c)

    def test_safe_kind_prefix_strips_separators(self) -> None:
        # Defensive: even if a future kind contains "/", we still get
        # a flat filename.
        out = _lock_filename("host", "weird/kind:1", "x")
        self.assertNotIn("/", out)
        self.assertNotIn(":", out)


class TestLockAcquireAndContention(unittest.TestCase):
    def test_acquire_yields_acquired_true(self) -> None:
        with TemporaryDirectory() as tmp:
            with reentrancy_lock(
                lock_dir=tmp, host="h", kind="denylist_clear",
                target="x", ack_timeout_ms=5000, stale_factor=2,
            ) as out:
                self.assertTrue(out.acquired)
                self.assertEqual(out.note, "acquired")
                self.assertTrue(Path(out.path).exists())

    def test_contended_acquire_yields_false(self) -> None:
        # Hold the lock from a separate fd, then attempt to acquire
        # via the helper. The helper must NOT block; it must yield
        # acquired=False.
        with TemporaryDirectory() as tmp:
            parent = Path(tmp)
            parent.mkdir(parents=True, mode=0o700, exist_ok=True)
            from xops.opsctl._lock import _lock_filename
            name = _lock_filename("h", "denylist_clear", "x")
            target_path = parent / name
            fd = os.open(str(target_path), os.O_RDWR | os.O_CREAT, 0o600)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                with reentrancy_lock(
                    lock_dir=tmp, host="h", kind="denylist_clear",
                    target="x", ack_timeout_ms=5000, stale_factor=2,
                ) as out:
                    self.assertFalse(out.acquired)
                    self.assertIn("contended", out.note)
            finally:
                try:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                except OSError:
                    pass
                os.close(fd)

    def test_release_unlinks_file(self) -> None:
        with TemporaryDirectory() as tmp:
            with reentrancy_lock(
                lock_dir=tmp, host="h", kind="denylist_clear",
                target="x", ack_timeout_ms=5000, stale_factor=2,
            ) as out:
                self.assertTrue(Path(out.path).exists())
            # Outside the with-block the lockfile is unlinked.
            self.assertFalse(Path(out.path).exists())


class TestLockStaleReap(unittest.TestCase):
    def test_stale_lockfile_is_reaped(self) -> None:
        # Create a lockfile with no live holder and an old mtime.
        # The next acquire must succeed.
        with TemporaryDirectory() as tmp:
            parent = Path(tmp)
            parent.mkdir(parents=True, mode=0o700, exist_ok=True)
            name = _lock_filename("h", "denylist_clear", "x")
            stale = parent / name
            stale.write_bytes(b"")
            os.chmod(stale, 0o600)
            # Push mtime far into the past.
            ancient = time.time() - 10_000
            os.utime(str(stale), (ancient, ancient))
            self.assertTrue(stale.exists())

            with reentrancy_lock(
                lock_dir=tmp, host="h", kind="denylist_clear",
                target="x", ack_timeout_ms=100, stale_factor=2,
            ) as out:
                self.assertTrue(out.acquired)


if __name__ == "__main__":
    unittest.main()
