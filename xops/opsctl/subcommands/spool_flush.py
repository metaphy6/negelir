"""``ops.spool-flush`` — Phase 8 §8.1 spool drain.

When the bus is unreachable, :func:`xops.opsctl._publish.publish_event`
spools the envelope to ``cfg.opsctl_spool_dir_resolved`` as
``{ms}-{request_id}.envelope.json`` (mode 0600). This subcommand
walks that dir in append order (sorted by filename — the millisecond
prefix gives a stable total order across same-millisecond races) and
re-publishes each entry.

Idempotency contract (binding, ROADMAP §8.1):

* Each spool entry carries the ORIGINAL ``request_id``. Replaying
  a previously-acked envelope is benign — consumer-side dedup
  (``ai/swarm/agents/maint/_dedup`` per the §8.0 wire contract)
  drops it.
* A successful publish + ack drain removes the spool file. A
  ``BUS_DOWN_SPOOLED`` outcome (still no bus) leaves it for the
  next flush attempt — but since ``_spool_envelope`` would write
  a *new* file we manually skip the re-spool here by passing the
  original message through and only unlinking on success.
* Concurrent flush is refused via a directory-level
  :func:`fcntl.flock` (exit
  :attr:`xops.opsctl._exit_codes.ExitCode.SPOOL_FLUSH_ALREADY_RUNNING`).

Per-tick budget: stops after ``--max-entries`` successful publishes
or the first non-OK / non-NO_CONSUMER outcome (operator inspects
the audit row to decide retry / escalation). ``--max-entries=0``
means "drain until empty or first hard failure".
"""
from __future__ import annotations

import argparse
import contextlib
import errno
import fcntl
import json
import os
import sys
from pathlib import Path
from typing import Any, Iterator, Optional

from ai.common.config import Config
from ai.swarm.sdk.types import Envelope, Message, Topic

from .._audit import append_audit_row, make_row
from .._exit_codes import ExitCode
from .._publish import publish_event

NAME = "spool-flush"
LOCK_FILENAME = ".flush.lock"


def add_parser(subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]") -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help="Replay bus-down spool entries through the live bus.",
        description=(
            "Drains cfg.opsctl_spool_dir_resolved in filename order. "
            "Successful publishes (OK or NO_CONSUMER_FOR_KIND) remove "
            "the spool file; HARD_TIMEOUT/PARTIAL leave it for retry. "
            "Concurrent flushes refused via dir-level flock."
        ),
    )
    parser.add_argument(
        "--max-entries",
        type=int,
        default=0,
        help="Stop after N successful publishes (0 = drain until empty or hard failure).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List spool entries that would be replayed; do NOT publish.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit a single JSON object on stdout (deterministic).",
    )
    parser.set_defaults(func=run)
    return parser


@contextlib.contextmanager
def _flush_lock(spool_dir: Path) -> Iterator[bool]:
    """Acquire a non-blocking exclusive lock on the spool dir.

    Yields ``True`` on acquire, ``False`` on contention. Unlinks
    the lockfile on release.
    """
    spool_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
    lock_path = spool_dir / LOCK_FILENAME
    fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno in (errno.EWOULDBLOCK, errno.EAGAIN):
                yield False
                return
            raise
        try:
            yield True
        finally:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
            try:
                os.unlink(str(lock_path))
            except FileNotFoundError:
                pass
            except OSError:
                pass
    finally:
        try:
            os.close(fd)
        except OSError:
            pass


def _load_spool_message(path: Path) -> Optional[Message]:
    """Read a spool file and reconstruct the original :class:`Message`.

    Returns ``None`` if the file is malformed; the caller logs and
    quarantines the entry by renaming with a ``.malformed`` suffix.
    """
    try:
        body = path.read_bytes()
    except OSError:
        return None
    try:
        data = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return None
    env = data.get("envelope")
    payload = data.get("payload")
    if not isinstance(env, dict) or not isinstance(payload, dict):
        return None
    try:
        envelope = Envelope.from_dict(env)
    except (TypeError, ValueError):
        return None
    return Message(envelope=envelope, payload=payload)


def _spool_entries(spool_dir: Path) -> list[Path]:
    if not spool_dir.exists():
        return []
    # Sort by filename — millisecond prefix gives append order.
    return sorted(spool_dir.glob("*.envelope.json"))


def run(args: argparse.Namespace, *, bus: Optional[Any] = None) -> int:
    cfg = Config()
    spool_dir = Path(cfg.opsctl_spool_dir_resolved)
    json_output = bool(getattr(args, "json", False))
    dry_run = bool(getattr(args, "dry_run", False))
    max_entries = int(getattr(args, "max_entries", 0) or 0)
    host = os.uname().nodename

    entries = _spool_entries(spool_dir)
    if dry_run:
        summary = {
            "op": NAME,
            "spool_dir": str(spool_dir),
            "entries": [str(p.name) for p in entries],
            "count": len(entries),
            "action": "dry-run",
            "note": "dry-run: no publish, no audit row",
        }
        if json_output:
            sys.stdout.write(json.dumps(summary, sort_keys=True, ensure_ascii=False))
            sys.stdout.write("\n")
        else:
            sys.stdout.write(
                f"opsctl {NAME} DRY-RUN spool_dir={spool_dir} count={len(entries)}\n"
            )
            for p in entries:
                sys.stdout.write(f"  - {p.name}\n")
        return int(ExitCode.OK)

    succeeded = 0
    failed = 0
    skipped = 0
    last_exit = int(ExitCode.OK)

    with _flush_lock(spool_dir) as acquired:
        if not acquired:
            note = "another spool-flush is in progress"
            sys.stderr.write(f"opsctl {NAME}: {note}\n")
            append_audit_row(
                cfg.opsctl_audit_path_resolved,
                make_row(
                    op=NAME, target="-", request_id="-",
                    exit_code=int(ExitCode.SPOOL_FLUSH_ALREADY_RUNNING),
                    expected_acks=0, received_acks=0,
                    note=note, host=host,
                ),
            )
            if json_output:
                sys.stdout.write(json.dumps(
                    {"op": NAME, "exit_code": int(ExitCode.SPOOL_FLUSH_ALREADY_RUNNING),
                     "note": note},
                    sort_keys=True, ensure_ascii=False,
                ))
                sys.stdout.write("\n")
            return int(ExitCode.SPOOL_FLUSH_ALREADY_RUNNING)

        for path in entries:
            message = _load_spool_message(path)
            if message is None:
                # Quarantine the malformed entry so we do not loop on it.
                quarantine = path.with_suffix(path.suffix + ".malformed")
                try:
                    path.rename(quarantine)
                except OSError:
                    pass
                failed += 1
                last_exit = int(ExitCode.GENERIC_FAILURE)
                append_audit_row(
                    cfg.opsctl_audit_path_resolved,
                    make_row(
                        op=NAME, target=path.name, request_id="-",
                        exit_code=int(ExitCode.GENERIC_FAILURE),
                        expected_acks=0, received_acks=0,
                        note=f"malformed spool entry quarantined as {quarantine.name}",
                        host=host,
                    ),
                )
                continue

            result = publish_event(bus, message)
            request_id = result.request_id or str(message.payload.get("request_id", "-"))
            append_audit_row(
                cfg.opsctl_audit_path_resolved,
                make_row(
                    op=NAME,
                    target=str(message.payload.get("target", "-")),
                    request_id=request_id,
                    exit_code=int(result.exit_code),
                    expected_acks=len(result.expected_acks),
                    received_acks=len(result.received_acks),
                    note=f"replay: {result.note}",
                    host=host,
                ),
            )
            ec = result.exit_code
            if ec in (ExitCode.OK, ExitCode.NO_CONSUMER_FOR_KIND):
                # Accepted (or routed but no live consumer to ack —
                # operator's intent is recorded, drop the spool entry).
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
                except OSError:
                    pass
                succeeded += 1
                last_exit = int(ec)
                if max_entries and succeeded >= max_entries:
                    break
            elif ec == ExitCode.BUS_DOWN_SPOOLED:
                # Bus still down. publish_event already wrote a NEW
                # spool file on retry; remove the old one to avoid
                # double-publish on next flush. Stop draining: bus is
                # down, no point in iterating.
                try:
                    path.unlink()
                except OSError:
                    pass
                skipped += 1
                last_exit = int(ec)
                break
            else:
                # HARD_TIMEOUT / PARTIAL_ACK_TIMEOUT / UNKNOWN_KIND /
                # BAD_USAGE / etc. Leave the file for the next flush
                # so the operator can inspect the audit row.
                failed += 1
                last_exit = int(ec)
                break

    summary = {
        "op": NAME,
        "spool_dir": str(spool_dir),
        "succeeded": succeeded,
        "failed": failed,
        "skipped": skipped,
        "exit_code": int(last_exit),
        "note": f"flushed {succeeded}/{len(entries)} spool entries",
    }
    if json_output:
        sys.stdout.write(json.dumps(summary, sort_keys=True, ensure_ascii=False))
        sys.stdout.write("\n")
    else:
        sys.stdout.write(
            f"opsctl {NAME} succeeded={succeeded} failed={failed} skipped={skipped} "
            f"exit={last_exit}\n"
        )
    return int(last_exit)


__all__ = ["NAME", "add_parser", "run"]
