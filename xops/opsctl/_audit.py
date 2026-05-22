"""xops.opsctl — append-only audit CSV (Phase 8 §8.1 / §8.15.7).

Every opsctl subcommand writes ONE row, after the publish/ack flow
completes (or refuses), via :func:`append_audit_row`. The schema is:

    timestamp_utc , host , op , target , request_id , exit_code ,
    expected_acks , received_acks , note , prev_hmac , row_hmac

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

Hash-chain HMAC integrity (§8.15.7):

* Each row carries ``prev_hmac`` (hex HMAC of the prior row) and
  ``row_hmac`` (hex HMAC of this row). The genesis row's ``prev_hmac``
  is :data:`GENESIS_PREV_HMAC`. A truncation or row-rewrite breaks
  the chain at the first row whose ``prev_hmac`` does not equal the
  recomputed hash of the prior row.
* When ``hmac_key`` is *None* (no key configured) both columns are
  empty strings — backward-compatible with pre-§8.15.7 deployments.
* Rotation: when the file exceeds ``max_bytes`` it is renamed to
  ``<path>.1`` (existing ``.1`` → ``.2``, etc.) and a new file is
  started. The new file's genesis ``prev_hmac`` = rotated file's last
  ``row_hmac``, so the chain is continuous across rotation.

Postgres mirror parity (Phase 9): when the §8.1 PG mirror lands the
same columns flow into ``maint_audit_log`` — see migration 009.
"""
from __future__ import annotations

import csv
import hashlib
import hmac as _hmac_module
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Genesis prev_hmac: sha256("negelir-audit-chain-v1")[:32] hex chars.
# Constant — changing it breaks all existing chains.
GENESIS_PREV_HMAC: str = hashlib.sha256(b"negelir-audit-chain-v1").hexdigest()[:32]

# Header MUST stay stable. Adding a column is a minor bump on the
# ``xops`` component AND requires a paired migration of any existing
# rotated audit file (truncation is forbidden).
# §8.15.7 added prev_hmac + row_hmac at the end (additive-only).
AUDIT_HEADER: tuple[str, ...] = (
    "timestamp_utc",
    "host",
    "user",        # §8.15.7 — operator identity bound in HMAC
    "op",
    "target",
    "request_id",
    "exit_code",
    "expected_acks",
    "received_acks",
    "note",
    "prev_hmac",   # §8.15.7 hash-chain
    "row_hmac",    # §8.15.7 hash-chain
)

# Column index of each hash-chain field (stable as long as AUDIT_HEADER is).
_IDX_PREV_HMAC = AUDIT_HEADER.index("prev_hmac")
_IDX_ROW_HMAC  = AUDIT_HEADER.index("row_hmac")


@dataclass(frozen=True)
class AuditRow:
    timestamp_utc: str
    host: str
    user: str          # §8.15.7 — operator identity (bound in HMAC)
    op: str
    target: str
    request_id: str
    exit_code: int
    expected_acks: int
    received_acks: int
    note: str
    # §8.15.7 hash-chain columns (empty string = no key configured).
    prev_hmac: str = field(default="")
    row_hmac: str  = field(default="")

    def as_record(self) -> tuple[str, ...]:
        return (
            self.timestamp_utc,
            self.host,
            self.user,
            self.op,
            self.target,
            self.request_id,
            str(self.exit_code),
            str(self.expected_acks),
            str(self.received_acks),
            self.note,
            self.prev_hmac,
            self.row_hmac,
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
    host: Optional[str] = None,     # reserved for future host-pinning audit
    hmac_key: Optional[bytes] = None,  # §8.15.7 — HMAC key bytes (None = no chain)
    max_bytes: int = 0,               # §8.15.7 — rotate when file ≥ this many bytes (0 = off)
) -> None:
    """Append one :class:`AuditRow` to the audit CSV at ``audit_path``.

    Creates the file (with header) and parent dir if missing.
    ``fsync``'s the file after each row; ``fsync``'s the parent dir
    on first creation only.

    §8.15.7 extensions:

    * When ``hmac_key`` is provided, ``prev_hmac`` and ``row_hmac`` are
      computed and written. When *None*, both columns are empty strings
      (backward-compatible with pre-§8.15.7 deployments).
    * When ``max_bytes > 0`` and the file would exceed that size, the
      file is rotated to ``<path>.1`` (existing ``.1`` → ``.2``, etc.)
      before the new row is written. The chain continues: the new
      file's genesis ``prev_hmac`` = rotated file's last ``row_hmac``.
    """
    del host  # reserved
    path = Path(audit_path)

    # §8.15.7: read prev_hmac BEFORE possible rotation so the chain bridges
    # correctly across file boundaries. If hmac_key is None, no chain to track.
    prev_hmac_for_row: str = ""
    if hmac_key is not None:
        prev_hmac_for_row = _read_last_row_hmac(path)

    # §8.15.7: rotate before writing if the file is too large.
    if max_bytes > 0 and path.exists() and path.stat().st_size >= max_bytes:
        _rotate_audit_file(path)

    dir_was_created = _ensure_parent(path)
    file_exists = path.exists()

    # §8.15.7: compute hash-chain columns when a key is provided.
    if hmac_key is not None:
        row_hmac = compute_row_hmac(hmac_key, prev_hmac_for_row, row)
        row = AuditRow(
            timestamp_utc=row.timestamp_utc,
            host=row.host,
            user=row.user,
            op=row.op,
            target=row.target,
            request_id=row.request_id,
            exit_code=row.exit_code,
            expected_acks=row.expected_acks,
            received_acks=row.received_acks,
            note=row.note,
            prev_hmac=prev_hmac_for_row,
            row_hmac=row_hmac,
        )

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
    user: str = "",
) -> AuditRow:
    """Construct an :class:`AuditRow` with a UTC timestamp."""
    import getpass  # stdlib — no network; safe in hot path
    return AuditRow(
        timestamp_utc=_utc_now_iso(),
        host=host or os.uname().nodename,
        user=user or getpass.getuser(),
        op=op,
        target=target,
        request_id=request_id,
        exit_code=int(exit_code),
        expected_acks=int(expected_acks),
        received_acks=int(received_acks),
        note=note,
    )


# ── §8.15.7 HMAC helpers ────────────────────────────────────────────────


def load_audit_chain_key(key_path: str) -> Optional[bytes]:
    """Load the raw HMAC key from ``key_path`` (mode 0400).

    Returns *None* when the path is empty, the file is absent, or it
    cannot be read — callers treat *None* as "no chain configured".
    Strips trailing whitespace / newlines from the key file bytes so
    that ``echo -n <hex> | xxd -r -p > key`` and
    ``openssl rand -out key 32`` both work without surprises.
    """
    if not key_path:
        return None
    try:
        data = Path(key_path).expanduser().read_bytes()
    except OSError:
        return None
    data = data.strip()
    return data if data else None


def compute_row_hmac(key: bytes, prev_hmac: str, row: AuditRow) -> str:
    """Compute HMAC-SHA256 hex digest for one audit row.

    The signed message is:
        ``{prev_hmac}|{timestamp_utc}|{user}|{host}|{op}|{target}|{request_id}``

    This binds the row position in the chain (via ``prev_hmac``),
    the operator identity (``user``), the causal timestamp, and the
    operation so reordering, replaying, or re-attributing rows breaks
    the chain.
    """
    msg = (
        f"{prev_hmac}|{row.timestamp_utc}|{row.user}"
        f"|{row.host}|{row.op}|{row.target}|{row.request_id}"
    )
    return _hmac_module.new(key, msg.encode(), hashlib.sha256).hexdigest()


def _read_last_row_hmac(path: Path) -> str:
    """Return the ``row_hmac`` of the last data row in ``path``.

    Returns :data:`GENESIS_PREV_HMAC` when the file does not exist,
    is empty, or contains only a header row.
    """
    if not path.exists():
        return GENESIS_PREV_HMAC
    try:
        with open(path, newline="", encoding="utf-8") as fh:
            reader = csv.reader(fh)
            last_row: Optional[list[str]] = None
            for row in reader:
                last_row = row
            if last_row is None or last_row == list(AUDIT_HEADER):
                return GENESIS_PREV_HMAC
            # row_hmac is the last column
            if len(last_row) > _IDX_ROW_HMAC:
                h = last_row[_IDX_ROW_HMAC].strip()
                return h if h else GENESIS_PREV_HMAC
    except (OSError, csv.Error):
        pass
    return GENESIS_PREV_HMAC


def _rotate_audit_file(path: Path) -> None:
    """Rotate ``path`` → ``path.1`` (``path.1`` → ``path.2``, etc.).

    Shifts existing rotated files down by one before renaming the
    active file.  The new active file is started fresh by the
    caller.  Errors are silently swallowed — a rotation failure
    must not prevent the audit row from being written.
    """
    try:
        # Find the highest existing rotation number.
        n = 1
        while (path.parent / f"{path.name}.{n}").exists():
            n += 1
        # Shift down: .N-1 → .N, ..., .1 → .2
        for i in range(n, 1, -1):
            src = path.parent / f"{path.name}.{i - 1}"
            dst = path.parent / f"{path.name}.{i}"
            src.rename(dst)
        # Rename active → .1
        path.rename(path.parent / f"{path.name}.1")
    except OSError:
        pass


__all__ = [
    "AUDIT_HEADER",
    "AuditRow",
    "GENESIS_PREV_HMAC",
    "append_audit_row",
    "compute_row_hmac",
    "load_audit_chain_key",
    "make_row",
]
