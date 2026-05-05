"""xops.opsctl — re-entrancy lock (Phase 8 §8.1).

A per-(host, kind, target) advisory lockfile under
``cfg.opsctl_lock_dir_resolved`` prevents two concurrent operator
shells from publishing the same logical command. The lock is taken
with :func:`fcntl.flock` (LOCK_EX | LOCK_NB) so the kernel cleans
it up automatically when the holding process exits — even on hard
SIGKILL.

Doctrine (binding, ROADMAP §8.1):

* The lock guards **logical** concurrency, not bus single-publication.
  A second operator who passes the lock will still publish; the
  consumer's idempotency ledger handles dedup.
* Stale lockfiles (no live holder, mtime older than
  ``opsctl_ack_timeout_ms × opsctl_lock_stale_factor``) are
  deleted on the next acquire so a crashed CLI does not block the
  same tuple forever. ``flock`` always wins over the mtime probe —
  if the kernel still holds the lock, we never delete.
* The lock filename uses a sha256 of ``host|kind|target`` so
  filesystem-restricted characters in ``target`` (``/``, spaces,
  IPv6 colons) cannot break the lock path.

Use :func:`reentrancy_lock` as a context manager; it yields a
``LockOutcome`` so callers can distinguish "acquired" from
"contended" without raising.
"""
from __future__ import annotations

import contextlib
import errno
import fcntl
import hashlib
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional

# A tiny in-memory marker so a single process re-entering the same
# (kind, target) tuple within one CLI invocation cleanly deadlocks
# itself in tests rather than silently sharing the kernel-level
# flock (which is per-process, not per-fd-without-OFD).
_LOCK_NAME_MIN_LEN = 8


@dataclass(frozen=True)
class LockOutcome:
    """Result of attempting to acquire the re-entrancy lock."""

    acquired: bool
    path: str
    note: str = ""


def _lock_filename(host: str, kind: str, target: str) -> str:
    """Return a deterministic filename for the (host, kind, target)
    tuple. Uses sha256 to keep the path filesystem-safe regardless of
    target characters."""
    h = hashlib.sha256(f"{host}|{kind}|{target}".encode("utf-8")).hexdigest()
    # Prefix with kind for operator legibility on `ls`; suffix with
    # the hash for uniqueness.
    safe_kind = "".join(c if c.isalnum() or c in "._-" else "_" for c in kind)
    return f"{safe_kind}.{h[:32]}.lock"


def _maybe_reap_stale(path: Path, max_age_s: float) -> None:
    """If the lockfile exists, has no live ``flock`` holder, and is
    older than ``max_age_s``, remove it.

    The reap is best-effort: if any step racey-fails we leave the
    file alone — the next acquire will retry. Never raises.
    """
    try:
        st = path.stat()
    except FileNotFoundError:
        return
    except OSError:
        return
    age = time.time() - st.st_mtime
    if age < max_age_s:
        return
    # Probe for a live holder via a non-blocking exclusive flock on a
    # fresh fd. If we get the lock, no one is holding it; we then
    # release and unlink. Otherwise, leave alone (live holder is
    # legitimately doing work and will refresh mtime on next op).
    try:
        fd = os.open(str(path), os.O_RDONLY)
    except OSError:
        return
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            # Held by someone else — not stale; leave alone.
            return
        # We got the probe lock; the file is stale. Unlink while still
        # holding the kernel lock (defensive ordering on most POSIX
        # filesystems).
        try:
            os.unlink(str(path))
        except FileNotFoundError:
            pass
        except OSError:
            pass
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass
    finally:
        try:
            os.close(fd)
        except OSError:
            pass


@contextlib.contextmanager
def reentrancy_lock(
    *,
    lock_dir: str,
    host: str,
    kind: str,
    target: str,
    ack_timeout_ms: int,
    stale_factor: int,
) -> Iterator[LockOutcome]:
    """Yield a :class:`LockOutcome` for the (host, kind, target) tuple.

    On contended acquire (another shell holds the kernel lock), yields
    ``acquired=False`` with a human-readable note. The caller decides
    whether to refuse, defer, or proceed — typically refuse.

    The lockfile is created with mode 0600; the parent dir is created
    with mode 0700 if missing.
    """
    parent = Path(lock_dir)
    parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    name = _lock_filename(host, kind, target)
    if len(name) < _LOCK_NAME_MIN_LEN:  # defensive; sha hex makes this unreachable
        raise ValueError(f"lockfile name {name!r} unexpectedly short")
    path = parent / name
    max_age_s = (ack_timeout_ms / 1000.0) * float(max(1, stale_factor))
    _maybe_reap_stale(path, max_age_s)

    fd = os.open(str(path), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno in (errno.EWOULDBLOCK, errno.EAGAIN):
                yield LockOutcome(
                    acquired=False,
                    path=str(path),
                    note="contended: another opsctl holds the (host,kind,target) lock",
                )
                return
            raise
        # Refresh mtime so the stale-reap heuristic stays meaningful
        # under long-held locks (e.g. ack-timeout near upper budget).
        try:
            os.utime(str(path), None)
        except OSError:
            pass
        try:
            yield LockOutcome(acquired=True, path=str(path), note="acquired")
        finally:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
            # Unlink before close so concurrent acquires after our
            # close see a fresh file rather than racing with the dead
            # inode. Best-effort.
            try:
                os.unlink(str(path))
            except FileNotFoundError:
                pass
            except OSError:
                pass
    finally:
        try:
            os.close(fd)
        except OSError:
            pass


__all__ = ["LockOutcome", "reentrancy_lock"]
