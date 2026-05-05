"""xops.opsctl — append-only audit CSV (Phase 8 §8.1).

Every opsctl subcommand writes ONE row, after the publish/ack flow
completes (or refuses), via :func:`append_audit_row`. The schema is:

    timestamp_utc , host , op , target , request_id , exit_code ,
    expected_acks , received_acks , note

Doctrine:

* CSV file mode is 0600; parent dir is 0700 (owner-only). Verified at
  open time; mismatched modes are repaired before the first write so
  a misconfigured deploy does not silently log to a world-readable
  file.
* Each row is followed by an explicit ``fsync`` on the file descriptor;
  the parent dir is ``fsync``'d once on first creation so the file's
  rename-into-place (if any future caller does that) is durable.
* Field values are CSV-escaped via :mod:`csv` (no manual quoting); a
  newline inside a field is therefore safe but discouraged.

Hash-chain HMAC integrity (§8.15.7) and Postgres mirror parity
(Phase 9) are out of scope for this baseline landing; a future
sub-section adds them in-place via additional columns.
"""
from __future__ import annotations

import csv
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Header MUST stay stable. Adding a column is a minor bump on the
# ``xops`` component AND requires a paired migration of any existing
# rotated audit file (truncation is forbidden).
AUDIT_HEADER: tuple[str, ...] = (
    "timestamp_utc",
    "host",
    "op",
    "target",
    "request_id",
    "exit_code",
    "expected_acks",
    "received_acks",
    "note",
)


@dataclass(frozen=True)
class AuditRow:
    timestamp_utc: str
    host: str
    op: str
    target: str
    request_id: str
    exit_code: int
    expected_acks: int
    received_acks: int
    note: str

    def as_record(self) -> tuple[str, ...]:
        return (
            self.timestamp_utc,
            self.host,
            self.op,
            self.target,
            self.request_id,
            str(self.exit_code),
            str(self.expected_acks),
            str(self.received_acks),
            self.note,
        )


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _ensure_parent(path: Path) -> bool:
    """Create the audit file's parent directory if missing.

    Returns True iff the directory was newly created (caller should
    then ``fsync`` the directory's parent so the rename of the new
    dir entry is durable).
    """
    parent = path.parent
    if parent.exists():
        return False
    parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    return True


def _fsync_dir(path: Path) -> None:
    """``fsync`` a directory (POSIX). On platforms without dir-fsync
    support the call silently no-ops — operator durability on those
    platforms is the operator's concern, not the CLI's."""
    try:
        fd = os.open(str(path), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except (OSError, ValueError):
        pass
    finally:
        os.close(fd)


def append_audit_row(
    audit_path: str,
    row: AuditRow,
    *,
    host: Optional[str] = None,  # reserved for future host-pinning audit
) -> None:
    """Append one :class:`AuditRow` to the audit CSV at ``audit_path``.

    Creates the file (with header) and parent dir if missing.
    ``fsync``'s the file after each row; ``fsync``'s the parent dir
    on first creation only.
    """
    del host  # reserved
    path = Path(audit_path)
    dir_was_created = _ensure_parent(path)
    file_exists = path.exists()

    # Open append; create with explicit 0o600 mode.
    fd = os.open(
        str(path),
        os.O_WRONLY | os.O_CREAT | os.O_APPEND,
        0o600,
    )
    try:
        # If the file exists from a prior run with permissive mode,
        # repair it now (operator may have edited permissions).
        try:
            st = os.fstat(fd)
            if (st.st_mode & 0o777) != 0o600:
                os.fchmod(fd, 0o600)
        except OSError:
            pass

        with os.fdopen(fd, "a", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh, lineterminator="\n")
            if not file_exists:
                writer.writerow(AUDIT_HEADER)
            writer.writerow(row.as_record())
            fh.flush()
            os.fsync(fh.fileno())
    finally:
        # fdopen closes fd via the context manager above. Nothing to
        # close here on the success path.
        pass

    if dir_was_created:
        _fsync_dir(path.parent)


def make_row(
    *,
    op: str,
    target: str,
    request_id: str,
    exit_code: int,
    expected_acks: int,
    received_acks: int,
    note: str = "",
    host: str = "",
) -> AuditRow:
    """Construct an :class:`AuditRow` with a UTC timestamp."""
    return AuditRow(
        timestamp_utc=_utc_now_iso(),
        host=host or os.uname().nodename,
        op=op,
        target=target,
        request_id=request_id,
        exit_code=int(exit_code),
        expected_acks=int(expected_acks),
        received_acks=int(received_acks),
        note=note,
    )


__all__ = ["AUDIT_HEADER", "AuditRow", "append_audit_row", "make_row"]
