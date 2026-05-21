"""Phase 8 §8.12 — DR-drill cadence gauge.

Reads ``data/backups/dr_drills.csv`` (the append-only record of
quarterly disaster-recovery drills) and emits a
:class:`DrDrillAgeReport` indicating how many days have passed
since the last successful drill.

A *successful* drill is a row with ``outcome == "ok"`` in the CSV.
The module is intentionally total — missing file, empty file, or
parse errors all return a deterministic report rather than
raising, so the watchdog can always decide whether to page.

Alert threshold (default):

* ``ALERT_DAYS = 100`` — one quarter is ~91 d; 100 d gives a
  ~9-day grace before the cadence-overdue alert fires.

CSV columns (authoritative schema matches
``docs/guides/dr_drill_runbook.md``):

    drill_date_utc,outcome,restored_from_offsite,target_conn_hash,
    drill_duration_s,operator,notes

``drill_date_utc`` must be ISO-8601 (``YYYY-MM-DD`` or full UTC
datetime).  ``outcome`` must be ``"ok"`` to count as a successful
drill; any other value (``"failed"``, ``"aborted"`` …) is recorded
but ignored for freshness scoring.
"""
from __future__ import annotations

import csv
import datetime as _dt
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

ALERT_DAYS: float = 100.0

_DATE_FORMATS: tuple[str, ...] = (
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d",
)


@dataclass(frozen=True)
class DrDrillAgeReport:
    """Snapshot of DR-drill cadence suitable for telemetry export."""

    last_drill_date_utc: Optional[_dt.datetime]
    age_days: Optional[float]
    severity: str  # "ok" | "crit" | "unknown"
    reason: str

    def to_dict(self) -> dict[str, object]:
        return {
            "last_drill_date_utc": (
                self.last_drill_date_utc.isoformat()
                if self.last_drill_date_utc is not None
                else None
            ),
            "age_days": self.age_days,
            "severity": self.severity,
            "reason": self.reason,
        }


def _parse_drill_date(raw: str) -> Optional[_dt.datetime]:
    raw = raw.strip()
    for fmt in _DATE_FORMATS:
        try:
            dt = _dt.datetime.strptime(raw, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=_dt.timezone.utc)
            return dt
        except ValueError:
            continue
    return None


def compute_dr_drill_age(
    drills_csv: str | Path,
    *,
    now_utc: Optional[_dt.datetime] = None,
    alert_days: float = ALERT_DAYS,
) -> DrDrillAgeReport:
    """Read *drills_csv* and return a :class:`DrDrillAgeReport`.

    The function is **total** — it never raises for missing files,
    empty CSVs, or parse errors.  Callers map ``severity="crit"``
    to a page; ``severity="unknown"`` means no data exists yet
    (first-run environment).
    """
    now = now_utc or _dt.datetime.now(_dt.timezone.utc)
    path = Path(drills_csv)

    if not path.is_file():
        return DrDrillAgeReport(
            last_drill_date_utc=None,
            age_days=None,
            severity="unknown",
            reason=f"dr_drills.csv not found: {path}",
        )

    successful: list[_dt.datetime] = []
    try:
        with path.open(newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                outcome = (row.get("outcome") or "").strip().lower()
                if outcome != "ok":
                    continue
                raw_date = row.get("drill_date_utc") or ""
                dt = _parse_drill_date(raw_date)
                if dt is not None:
                    successful.append(dt)
    except (OSError, csv.Error):
        return DrDrillAgeReport(
            last_drill_date_utc=None,
            age_days=None,
            severity="unknown",
            reason=f"dr_drills.csv unreadable: {path}",
        )

    if not successful:
        return DrDrillAgeReport(
            last_drill_date_utc=None,
            age_days=None,
            severity="crit",
            reason="no successful DR drill on record",
        )

    last_drill = max(successful)
    age_d = max(0.0, (now - last_drill).total_seconds() / 86400.0)

    if age_d >= alert_days:
        sev = "crit"
        reason = f"dr_drill_age_days={age_d:.1f} >= alert={alert_days}"
    else:
        sev = "ok"
        reason = f"dr_drill_age_days={age_d:.1f} < alert={alert_days}"

    return DrDrillAgeReport(
        last_drill_date_utc=last_drill,
        age_days=age_d,
        severity=sev,
        reason=reason,
    )
