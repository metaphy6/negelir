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
import time
from pathlib import Path
from typing import Any, Iterator, Optional

from common.config import Config
from swarm.sdk.spool_aging import prune_aged_spool_entries, quarantine_retired_spool_entries
from swarm.sdk.types import Envelope, Message, Topic

from .._audit import append_audit_row, make_row
from .._exit_codes import ExitCode
from .._publish import publish_event

NAME = "spool-flush"
LOCK_FILENAME = ".flush.lock"


def _maybe_reap_flush_lock(lock_path: Path, stale_timeout_s: float) -> None:
    """Delete the flush lockfile if it exists, is older than *stale_timeout_s*,
    and has no live ``flock`` holder (§8.14.10 stale-flush-lock reaper).

    Best-effort: never raises.
    """
    try:
        st = lock_path.stat()
    except FileNotFoundError:
        return
    except OSError:
        return
    age = time.time() - st.st_mtime
    if age < stale_timeout_s:
        return
    # Probe for a live holder via a non-blocking exclusive flock on a
    # fresh fd.  If we get the lock, no one is holding it — unlink.
    try:
        fd = os.open(str(lock_path), os.O_RDONLY)
    except OSError:
        return
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return  # Held by a live process — not stale; leave alone.
        try:
            os.unlink(str(lock_path))
        except (FileNotFoundError, OSError):
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
        default=None,
        help=(
            "Stop after N successful publishes "
            "(0 = unlimited; default: cfg.opsctl_spool_flush_max_per_run)."
        ),
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
    parser.add_argument(
        "--force-retired",
        action="store_true",
        help=(
            "Re-publish envelopes quarantined in the .retired/ subdir. "
            "The operator accepts that consumers will apply §0 forward-compat "
            "(unknown-kind envelopes may be silently dropped by consumers). "
            "Successfully re-published entries are removed from .retired/."
        ),
    )
    parser.set_defaults(func=run)
    return parser


@contextlib.contextmanager
def _flush_lock(spool_dir: Path, *, stale_timeout_s: float = 10.0) -> Iterator[bool]:
    """Acquire a non-blocking exclusive lock on the spool dir.

    Stale locks (no live holder, mtime older than *stale_timeout_s*) are
    reaped before the acquire attempt so a crashed flush process does not
    permanently block the directory.

    Yields ``True`` on acquire, ``False`` on contention. Unlinks
    the lockfile on release.
    """
    spool_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
    lock_path = spool_dir / LOCK_FILENAME
    _maybe_reap_flush_lock(lock_path, stale_timeout_s)
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
    # §8.14.10: newest-first (mtime descending) — fresh operator intent
    # is more valuable than stale enqueued actions on bus recovery.
    paths = list(spool_dir.glob("*.envelope.json"))
    try:
        return sorted(paths, key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        # Fallback if stat fails mid-iteration (file removed between glob and sort).
        return sorted(paths, reverse=True)


def _read_swarm_version() -> str:
    """Best-effort read of the swarm component version from chart.json."""
    try:
        chart = Path(__file__).resolve().parents[3] / "xops" / "versioning" / "chart.json"
        data = json.loads(chart.read_text())
        return str(data.get("components", {}).get("swarm", {}).get("version", ""))
    except Exception:
        return ""


def run(args: argparse.Namespace, *, bus: Optional[Any] = None) -> int:
    cfg = Config()
    spool_dir = Path(cfg.opsctl_spool_dir_resolved)
    json_output = bool(getattr(args, "json", False))
    dry_run = bool(getattr(args, "dry_run", False))
    # §8.14.10: use cfg.opsctl_spool_flush_max_per_run as the default cap;
    # --max-entries explicitly overrides (0 = unlimited).
    _max_entries_arg = getattr(args, "max_entries", None)
    if _max_entries_arg is None:
        max_entries = int(cfg.opsctl_spool_flush_max_per_run)
    else:
        max_entries = int(_max_entries_arg)
    force_retired = bool(getattr(args, "force_retired", False))
    host = os.uname().nodename
    # §8.14.10: stale flush-lock timeout = 2 × opsctl_ack_timeout_ms.
    stale_timeout_s = 2.0 * cfg.opsctl_ack_timeout_ms / 1000.0

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

    with _flush_lock(spool_dir, stale_timeout_s=stale_timeout_s) as acquired:
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

        # Pre-scan: quarantine malformed entries before the prune/retire
        # steps.  A file named with an epoch-zero ms prefix (e.g. test
        # fixtures) would otherwise be deleted as "aged out" before the
        # malformed-detection loop below has a chance to rename it.
        for _pre_path in list(entries):
            if _load_spool_message(_pre_path) is None:
                _pre_q = _pre_path.with_suffix(_pre_path.suffix + ".malformed")
                try:
                    _pre_path.rename(_pre_q)
                except OSError:
                    pass
                failed += 1
                last_exit = int(ExitCode.GENERIC_FAILURE)
                append_audit_row(
                    cfg.opsctl_audit_path_resolved,
                    make_row(
                        op=NAME, target=_pre_path.name, request_id="-",
                        exit_code=int(ExitCode.GENERIC_FAILURE),
                        expected_acks=0, received_acks=0,
                        note=f"malformed spool entry quarantined as {_pre_q.name}",
                        host=host,
                    ),
                )
        # Refresh after malformed pre-scan so prune/quarantine don't see them.
        entries = _spool_entries(spool_dir)

        # §8.13.3 — prune aged entries before replaying live ones.
        import time as _time
        _prune_result = prune_aged_spool_entries(
            spool_dir=spool_dir,
            max_age_h=int(cfg.maint_spool_entry_max_age_h),
            now_s=_time.time(),
            target="opsctl",
            producer="ops_console",
            spool_label="opsctl",
        )
        if _prune_result.pruned_paths and bus is not None:
            for _msg in _prune_result.maint_events + _prune_result.sec_alerts:
                try:
                    publish_event(bus, _msg)
                except Exception:
                    pass
        # Refresh entry list after pruning.
        entries = _spool_entries(spool_dir)

        # §8.13.3 — quarantine retired-kind / schema-outdated entries.
        from swarm.agents.maint import KNOWN_MAINT_EVENT_KINDS
        _retire_result = quarantine_retired_spool_entries(
            spool_dir=spool_dir,
            known_kinds=KNOWN_MAINT_EVENT_KINDS,
            min_schema_version=int(cfg.swarm_min_supported_schema_version),
            target="opsctl",
            producer="ops_console",
            current_version=_read_swarm_version(),
            spool_label="opsctl",
        )
        if _retire_result.retired_paths and bus is not None:
            for _msg in _retire_result.sec_alerts:
                try:
                    publish_event(bus, _msg)
                except Exception:
                    pass
        # Refresh entry list after quarantine.
        entries = _spool_entries(spool_dir)

        # §8.13.3 --force-retired: re-publish quarantined envelopes.
        if force_retired:
            retired_dir = spool_dir / ".retired"
            for rpath in sorted(retired_dir.glob("*.envelope.json")) if retired_dir.exists() else []:
                message = _load_spool_message(rpath)
                if message is None:
                    continue
                result = publish_event(bus, message)
                if result.exit_code in (ExitCode.OK, ExitCode.NO_CONSUMER_FOR_KIND):
                    try:
                        rpath.unlink()
                    except FileNotFoundError:
                        pass
                    succeeded += 1
                    if max_entries and succeeded >= max_entries:
                        break

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

    # §8.14.10: emit spool_flush_partial audit row when the drain budget
    # was exhausted and unprocessed entries remain.
    _processed = succeeded + failed + skipped
    _remaining = max(0, len(entries) - _processed)
    _hit_budget = max_entries > 0 and succeeded >= max_entries and _remaining > 0
    if _hit_budget:
        append_audit_row(
            cfg.opsctl_audit_path_resolved,
            make_row(
                op="spool-flush-partial",
                target="-",
                request_id="-",
                exit_code=int(ExitCode.OK),
                expected_acks=0,
                received_acks=0,
                note=(
                    f"drain budget exhausted: drained={succeeded} "
                    f"remaining={_remaining}"
                ),
                host=host,
            ),
        )

    summary = {
        "op": NAME,
        "spool_dir": str(spool_dir),
        "succeeded": succeeded,
        "failed": failed,
        "skipped": skipped,
        "exit_code": int(last_exit),
        "note": f"flushed {succeeded}/{len(entries)} spool entries",
    }
    if _hit_budget:
        summary["kind"] = "spool_flush_partial"
        summary["remaining"] = _remaining
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
