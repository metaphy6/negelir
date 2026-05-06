"""Phase 8 §8.3 — backup-age gauge (operator-visible freshness signal).

Pure-function module. Computes hours since the most-recent
*successfully completed* backup directory in
``cfg.maint_backup_dir`` and exposes it as a
:class:`BackupAgeReport`. The §8.3 backup agent (or any operator
dashboard scraper) maps this into a Prometheus gauge.

A backup directory counts as "successful" iff:

* its name parses as ``YYYYMMDDTHHMMSSZ`` (ISO-8601 UTC, the
  fire-window-id format the agent emits);
* it contains both ``manifest.json`` AND ``negelir.checksum.txt``
  (i.e. the encrypt + checksum step finished, see
  :mod:`xops.backup.executors`);
* its ``manifest.json`` parses and reports ``status="ok"``.

A directory missing any of those is treated as in-flight or
failed and ignored for freshness scoring.

Hard-coded thresholds (§8.3 contract):

* ``WARN_HOURS = 30`` — a daily nightly job should produce a
  fresh dump every 24h; 6h slack absorbs cron skew + verify time.
* ``CRIT_HOURS = 54`` — two nightly cycles missed; the operator
  should be paged.
"""
from __future__ import annotations

import datetime as _dt
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

WARN_HOURS: float = 30.0
CRIT_HOURS: float = 54.0
_WINDOW_FMT: str = "%Y%m%dT%H%M%SZ"


@dataclass(frozen=True)
class BackupAgeReport:
    """Snapshot of backup freshness suitable for telemetry export."""

    last_success_window_id: Optional[str]
    last_success_at_utc: Optional[_dt.datetime]
    age_hours: Optional[float]
    severity: str  # "ok" | "warn" | "crit" | "unknown"
    reason: str

    def to_dict(self) -> dict[str, object]:
        return {
            "last_success_window_id": self.last_success_window_id,
            "last_success_at_utc": (
                self.last_success_at_utc.isoformat()
                if self.last_success_at_utc is not None
                else None
            ),
            "age_hours": self.age_hours,
            "severity": self.severity,
            "reason": self.reason,
        }


def _parse_window_id(name: str) -> Optional[_dt.datetime]:
    try:
        ts = _dt.datetime.strptime(name, _WINDOW_FMT)
    except ValueError:
        return None
    return ts.replace(tzinfo=_dt.timezone.utc)


def _is_complete(d: Path) -> bool:
    if not (d / "manifest.json").is_file():
        return False
    if not (d / "negelir.checksum.txt").is_file():
        return False
    try:
        with (d / "manifest.json").open("r", encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return False
    return isinstance(doc, dict) and doc.get("status") == "ok"


def compute_backup_age(
    backup_dir: str | Path,
    *,
    now_utc: Optional[_dt.datetime] = None,
    warn_hours: float = WARN_HOURS,
    crit_hours: float = CRIT_HOURS,
) -> BackupAgeReport:
    """Scan ``backup_dir`` for the freshest successful dump.

    The function is total — it never raises for missing dirs or
    parse errors. It returns a ``severity="unknown"`` report so
    callers can decide whether absent-state counts as a page.
    """
    now = now_utc or _dt.datetime.now(_dt.timezone.utc)
    root = Path(backup_dir)
    if not root.is_dir():
        return BackupAgeReport(
            last_success_window_id=None,
            last_success_at_utc=None,
            age_hours=None,
            severity="unknown",
            reason=f"backup_dir does not exist: {root}",
        )

    candidates: list[tuple[_dt.datetime, str]] = []
    for child in root.iterdir():
        if not child.is_dir():
            continue
        ts = _parse_window_id(child.name)
        if ts is None:
            continue
        if not _is_complete(child):
            continue
        candidates.append((ts, child.name))

    if not candidates:
        return BackupAgeReport(
            last_success_window_id=None,
            last_success_at_utc=None,
            age_hours=None,
            severity="crit",
            reason="no successful dump directory found",
        )

    candidates.sort(reverse=True)
    last_ts, last_id = candidates[0]
    age_h = max(0.0, (now - last_ts).total_seconds() / 3600.0)
    if age_h >= crit_hours:
        sev, reason = "crit", f"age_hours={age_h:.1f} >= crit={crit_hours}"
    elif age_h >= warn_hours:
        sev, reason = "warn", f"age_hours={age_h:.1f} >= warn={warn_hours}"
    else:
        sev, reason = "ok", f"age_hours={age_h:.1f} < warn={warn_hours}"
    return BackupAgeReport(
        last_success_window_id=last_id,
        last_success_at_utc=last_ts,
        age_hours=age_h,
        severity=sev,
        reason=reason,
    )
