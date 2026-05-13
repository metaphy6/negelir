"""Phase 8 §8.3 — Append-only fire-window audit ledger (CSV).

The :class:`swarm.agents.maint.backup.MaintBackupAgent` writes one
row per cron fire to ``cfg.maint_backup_dir/audit.csv`` so two
properties hold across agent restarts:

* **Idempotency on `(job_id, backup_date_utc)`.** On boot, the
  agent reads the most recent successful row for *today (UTC)* and
  re-seeds its in-memory ``_last_completed_wall`` /
  ``_last_verified_wall`` timestamps so a restart-mid-day does NOT
  re-fire the dump.
* **Skew forensics.** Both ``wall_clock_utc`` AND
  ``monotonic_ns_at_fire`` are persisted on every fire so an
  operator can correlate a backwards / forwards wall-clock step
  against monotonic time after the fact (the in-memory
  detection in the agent only catches *adjacent* fires).

CSV-not-JSON because the bullet's binding language is "first row
of the day" and CSV is line-grep-able from a sidecar shell. The
file is opened with ``newline=""`` per :mod:`csv` doctrine and
flushed + ``fsync``'d on every append so a SIGKILL between fires
never tears a row.

This module is stdlib-only — Rule 1 forbids new deps for tooling
this small.
"""
from __future__ import annotations

import csv
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

# Header is part of the wire contract — adding a column requires a
# swarm minor bump (consumers may depend on stable column ordering)
# and a migration row that backfills the new column on legacy lines.
_HEADER: tuple[str, ...] = (
    "wall_clock_utc",
    "monotonic_ns_at_fire",
    "fire_window_id",
    "outcome",
    "verified",
    "catch_up",
)


@dataclass(frozen=True)
class AuditRow:
    """One persisted fire-window row. Field names mirror :data:`_HEADER`."""

    wall_clock_utc: str
    monotonic_ns_at_fire: int
    fire_window_id: str
    outcome: str
    verified: bool
    catch_up: bool


def append_row(audit_path: Path, row: AuditRow) -> None:
    """Append ``row`` to ``audit_path`` atomically (best-effort).

    Creates the file with its header if missing. ``fsync`` is
    invoked after the write so a power loss between fires cannot
    leave a torn line that breaks :func:`last_completed_today`.
    """

    audit_path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not audit_path.exists()
    # 0o600 file perms — §8.3 binding contract. The umask the agent
    # sets at boot already yields 0o600, but be explicit so this
    # helper is correct on its own.
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
    fd = os.open(audit_path, flags, 0o600)
    try:
        with os.fdopen(fd, "a", newline="") as fh:
            writer = csv.writer(fh)
            if new_file:
                writer.writerow(_HEADER)
            writer.writerow([
                row.wall_clock_utc,
                str(int(row.monotonic_ns_at_fire)),
                row.fire_window_id,
                row.outcome,
                "1" if row.verified else "0",
                "1" if row.catch_up else "0",
            ])
            fh.flush()
            os.fsync(fh.fileno())
    except OSError:
        # Persistence is best-effort — the in-memory state machine
        # remains the source of truth for the running agent. The
        # boot-time replay only loses a single fire-window in this
        # case, which is the same as a fresh install.
        return


def _read_rows(audit_path: Path) -> Iterable[dict[str, str]]:
    """Yield rows from ``audit_path`` in append order. Empty/missing
    files yield nothing; malformed rows are skipped (defence in
    depth — a half-written line must not wedge boot)."""

    if not audit_path.exists():
        return
    try:
        with audit_path.open("r", newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                if not row:
                    continue
                yield row
    except OSError:
        return


def last_completed_today(
    audit_path: Path, *, today: datetime
) -> datetime | None:
    """Return the wall-clock timestamp of the most recent ``ok`` /
    ``dry_run`` row dated ``today`` (UTC), or ``None`` if no such
    row exists.

    Used at agent boot to seed ``_last_completed_wall`` so a
    restart-mid-day does NOT re-fire today's dump (binding
    idempotency on ``(job_id, backup_date_utc)`` per §8.3).

    Backwards / forwards-skew rows (``outcome=skew_skipped``),
    disk-pressure rows, and verify-failure rows DO NOT satisfy
    today's idempotency — the next cron tick still owes a real
    backup.
    """

    if today.tzinfo is None:
        today = today.replace(tzinfo=timezone.utc)
    today_date = today.astimezone(timezone.utc).date().isoformat()
    last: datetime | None = None
    for row in _read_rows(audit_path):
        outcome = row.get("outcome", "")
        if outcome not in ("ok", "dry_run"):
            continue
        ts_str = row.get("wall_clock_utc", "")
        if not ts_str.startswith(today_date):
            continue
        try:
            ts = datetime.fromisoformat(ts_str)
        except ValueError:
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if last is None or ts > last:
            last = ts
    return last


def last_verified_today(
    audit_path: Path, *, today: datetime
) -> datetime | None:
    """Return the wall-clock timestamp of the most recent ``ok``
    (``verified=1``) row dated ``today`` (UTC), or ``None``.

    Drives the watchdog seed: only a verified completion satisfies
    the backup-age gauge.
    """

    if today.tzinfo is None:
        today = today.replace(tzinfo=timezone.utc)
    today_date = today.astimezone(timezone.utc).date().isoformat()
    last: datetime | None = None
    for row in _read_rows(audit_path):
        if row.get("outcome", "") != "ok":
            continue
        if row.get("verified", "0") != "1":
            continue
        ts_str = row.get("wall_clock_utc", "")
        if not ts_str.startswith(today_date):
            continue
        try:
            ts = datetime.fromisoformat(ts_str)
        except ValueError:
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if last is None or ts > last:
            last = ts
    return last


__all__ = [
    "AuditRow",
    "append_row",
    "last_completed_today",
    "last_verified_today",
]
