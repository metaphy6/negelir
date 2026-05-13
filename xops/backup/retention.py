"""Phase 8 §8.3 — dump-on-disk retention (GFS-light).

After a successful nightly fire (verify=ok, prune=done), the agent
calls :func:`prune_retained_dumps` to drop dump windows older than
the policy:

* keep every dump from the last ``cfg.maint_backup_retention_days``
  calendar days (default 14);
* additionally keep the most recent ``cfg.maint_backup_retention_weeks``
  Sunday dumps (default 4 — the "weekly" tier of GFS-light).

The function operates **only** on the on-disk artefacts produced by
:class:`xops.backup.executors.LocalPgDumpExecutor`. Encryption-key
material is *never* touched here — key rotation is operator-driven
(``ops.backup-rotate-key`` per §8.3 prose) and old key versions
remain on disk so historical dumps stay decryptable.

Doctrine respected:

* **Single-source config (Rule 1).** Caller passes the resolved
  ``backup_dir`` / ``keep_days`` / ``keep_weeks`` so the
  ``swarm.agents.maint.backup`` module owns the cfg → policy
  binding (and tests can drive the function with synthetic values).
* **No fabricated production data (Rule 3).** Best-effort: a missing
  / unreadable backup dir returns an empty result, NEVER raises into
  the agent's state machine.
* **Quarantine preservation.** Directories with the
  :data:`xops.backup.executors.FAILED_DIR_SUFFIX` suffix
  (``.failed`` / ``.failed.<n>``) are *never* pruned — they are
  forensic evidence; an operator decides their fate.

The pruner is pure-stdlib (no third-party deps) so it stays
container-agnostic and trivially testable.
"""
from __future__ import annotations

import logging
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from xops.backup.executors import FAILED_DIR_SUFFIX


_log = logging.getLogger("xops.backup.retention")


# Per-fire-window directory names produced by ``LocalPgDumpExecutor``
# embed an ISO-8601 timestamp with ``:`` replaced by ``_`` (per
# ``safe_window_name``). Example:
#   "<pod_instance_id>:<iso>" → "<pod_instance_id>_<iso-with-underscores>"
# We detect a 4-2-2 date prefix anywhere inside the name to derive
# the dump's calendar day. The regex deliberately rejects names that
# cannot be parsed — they are skipped (returned in `unparseable`)
# rather than mis-pruned.
_DATE_RE = re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)")


@dataclass(frozen=True)
class RetentionResult:
    """Outcome of a retention sweep.

    Attributes:
        kept: Per-window-dir names retained on disk.
        pruned: Per-window-dir names removed by the sweep.
        unparseable: Per-window-dir names whose date could not be
            derived from the directory name (skipped, never deleted).
        skipped_quarantine: ``.failed`` dirs that were intentionally
            preserved as forensic evidence.
    """

    kept: tuple[str, ...]
    pruned: tuple[str, ...]
    unparseable: tuple[str, ...]
    skipped_quarantine: tuple[str, ...]


def _parse_dump_date(name: str) -> datetime | None:
    """Return the UTC midnight of the dump's calendar day, or
    ``None`` when the name does not embed a parseable date."""
    m = _DATE_RE.search(name)
    if m is None:
        return None
    try:
        return datetime(
            int(m.group(1)), int(m.group(2)), int(m.group(3)),
            tzinfo=timezone.utc,
        )
    except ValueError:
        return None


def _is_quarantined(name: str) -> bool:
    """A name is quarantined if it carries the
    :data:`FAILED_DIR_SUFFIX` (or any disambiguating ``.failed.<n>``
    variant). Match is conservative: substring at end."""
    return name.endswith(FAILED_DIR_SUFFIX) or (
        FAILED_DIR_SUFFIX + "." in name
    )


def prune_retained_dumps(
    *,
    backup_dir: str | Path,
    keep_days: int,
    keep_weeks: int,
    now: datetime,
    dry_run: bool = False,
) -> RetentionResult:
    """Drop dump-window dirs older than the retention policy.

    Policy (binding §8.3):

    1. Skip everything that is not a dump-window dir (audit.csv,
       ``.verify_keys/``, key files, anything else).
    2. Quarantined ``.failed`` dirs are always kept.
    3. Dirs whose calendar day is within the last ``keep_days``
       days (inclusive of today UTC) are always kept.
    4. From the remaining (older) dirs, the most recent ``keep_weeks``
       Sunday dumps are kept; the rest are removed.
    5. Dirs whose name has no parseable date are kept (logged as
       unparseable) — never delete what we do not understand.

    The function NEVER raises into the agent's state machine; any
    per-dir ``OSError`` during ``rmtree`` is logged and the dir
    remains in ``pruned`` (best effort) — the next sweep retries.

    ``dry_run=True`` returns the same partition without removing
    anything from disk; the agent uses this when
    ``cfg.maint_backup_dry_run`` is set so its safety-floor
    contract holds for retention too.
    """

    base = Path(backup_dir)
    if not base.is_dir():
        return RetentionResult((), (), (), ())

    keep_days = max(int(keep_days), 1)
    keep_weeks = max(int(keep_weeks), 0)
    today_utc = datetime(
        now.year, now.month, now.day, tzinfo=timezone.utc,
    )
    day_cutoff = today_utc - timedelta(days=keep_days - 1)

    quarantined: list[str] = []
    unparseable: list[str] = []
    fresh: list[str] = []
    aged: list[tuple[datetime, str]] = []

    for entry in sorted(base.iterdir()):
        if not entry.is_dir():
            continue
        name = entry.name
        # Operator-managed sibling dirs we never touch.
        if name.startswith(".") or name in {"audit", "audit.csv"}:
            continue
        if _is_quarantined(name):
            quarantined.append(name)
            continue
        dump_day = _parse_dump_date(name)
        if dump_day is None:
            unparseable.append(name)
            continue
        if dump_day >= day_cutoff:
            fresh.append(name)
            continue
        aged.append((dump_day, name))

    # GFS-light weekly tier: keep the most recent `keep_weeks` Sunday
    # dumps from the aged set. ``weekday() == 6`` is Sunday in the
    # Python stdlib.
    aged.sort(key=lambda pair: pair[0], reverse=True)
    sundays_kept: list[str] = []
    to_prune: list[str] = []
    for day, name in aged:
        if day.weekday() == 6 and len(sundays_kept) < keep_weeks:
            sundays_kept.append(name)
        else:
            to_prune.append(name)

    pruned: list[str] = []
    if not dry_run:
        for name in to_prune:
            target = base / name
            try:
                shutil.rmtree(target)
                pruned.append(name)
            except OSError as exc:  # pragma: no cover — surfaced via log
                _log.warning(
                    "xops.backup.retention: rmtree %s failed: %r",
                    target, exc,
                )
    else:
        # Dry-run: report what would be pruned without touching disk.
        pruned = list(to_prune)

    kept_all = sorted(fresh + sundays_kept + unparseable + quarantined)
    return RetentionResult(
        kept=tuple(kept_all),
        pruned=tuple(pruned),
        unparseable=tuple(unparseable),
        skipped_quarantine=tuple(quarantined),
    )


def oldest_retained_sunday_dump(
    *, backup_dir: str | Path,
) -> tuple[datetime, str] | None:
    """Return ``(dump_day_utc, dir_name)`` of the oldest still-retained
    Sunday dump under ``backup_dir``, or ``None`` when no such dump
    exists.

    "Still-retained" mirrors the read side of :func:`prune_retained_dumps`:
    quarantined ``.failed`` dirs are skipped (forensic evidence, not
    valid restore sources), unparseable names are skipped (we never
    operate on what we cannot date), and only dirs whose calendar day
    is a Sunday (``weekday() == 6``) are considered. The result is the
    oldest such directory by date — the binding contract for §8.3
    weekly cold-verify (catches silent storage rot in the longest-lived
    dump first).

    Best-effort: a missing / unreadable backup dir returns ``None``;
    the caller (``MaintBackupAgent``) treats absence as "nothing to
    cold-verify yet" rather than an error.
    """

    base = Path(backup_dir)
    if not base.is_dir():
        return None
    candidates: list[tuple[datetime, str]] = []
    try:
        entries = list(base.iterdir())
    except OSError:
        return None
    for entry in entries:
        if not entry.is_dir():
            continue
        name = entry.name
        if name.startswith(".") or name in {"audit", "audit.csv"}:
            continue
        if _is_quarantined(name):
            continue
        dump_day = _parse_dump_date(name)
        if dump_day is None:
            continue
        if dump_day.weekday() != 6:  # Sunday only
            continue
        candidates.append((dump_day, name))
    if not candidates:
        return None
    candidates.sort(key=lambda pair: (pair[0], pair[1]))
    return candidates[0]


__all__ = ["RetentionResult", "prune_retained_dumps", "oldest_retained_sunday_dump"]
