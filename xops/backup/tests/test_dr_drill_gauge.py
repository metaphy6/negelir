"""Phase 8 §8.12 — DR-drill cadence gauge tests."""
from __future__ import annotations

import csv
import datetime as _dt
from pathlib import Path

import pytest

from xops.backup.dr_drill_gauge import (
    ALERT_DAYS,
    DrDrillAgeReport,
    compute_dr_drill_age,
)

_HEADER = (
    "drill_date_utc,outcome,restored_from_offsite,"
    "target_conn_hash,drill_duration_s,operator,notes"
)


def _write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "drill_date_utc",
                "outcome",
                "restored_from_offsite",
                "target_conn_hash",
                "drill_duration_s",
                "operator",
                "notes",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)


# ── missing / empty file ──────────────────────────────────────────────


def test_missing_csv_returns_unknown(tmp_path: Path) -> None:
    rep = compute_dr_drill_age(tmp_path / "absent.csv")
    assert rep.severity == "unknown"
    assert rep.age_days is None
    assert rep.last_drill_date_utc is None
    assert "not found" in rep.reason


def test_header_only_csv_returns_crit(tmp_path: Path) -> None:
    p = tmp_path / "dr_drills.csv"
    _write_csv(p, [])
    rep = compute_dr_drill_age(p)
    assert rep.severity == "crit"
    assert rep.last_drill_date_utc is None
    assert "no successful" in rep.reason


# ── outcome filtering ─────────────────────────────────────────────────


def test_only_failed_rows_returns_crit(tmp_path: Path) -> None:
    p = tmp_path / "dr_drills.csv"
    _write_csv(
        p,
        [
            {
                "drill_date_utc": "2026-01-01T00:00:00Z",
                "outcome": "failed",
                "restored_from_offsite": "1",
                "target_conn_hash": "abc",
                "drill_duration_s": "100",
                "operator": "ops",
                "notes": "",
            }
        ],
    )
    rep = compute_dr_drill_age(p)
    assert rep.severity == "crit"
    assert rep.last_drill_date_utc is None


def test_ok_row_used_for_freshness(tmp_path: Path) -> None:
    p = tmp_path / "dr_drills.csv"
    drill_dt = _dt.datetime(2026, 2, 1, 10, 0, 0, tzinfo=_dt.timezone.utc)
    _write_csv(
        p,
        [
            {
                "drill_date_utc": drill_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "outcome": "ok",
                "restored_from_offsite": "1",
                "target_conn_hash": "abc123",
                "drill_duration_s": "1800",
                "operator": "ops",
                "notes": "all clear",
            }
        ],
    )
    now = _dt.datetime(2026, 3, 1, 10, 0, 0, tzinfo=_dt.timezone.utc)
    rep = compute_dr_drill_age(p, now_utc=now)
    assert rep.severity == "ok"
    assert rep.last_drill_date_utc == drill_dt
    assert rep.age_days == pytest.approx(28.0, abs=0.01)


# ── alert threshold ───────────────────────────────────────────────────


def test_crit_when_age_exceeds_alert_days(tmp_path: Path) -> None:
    p = tmp_path / "dr_drills.csv"
    drill_dt = _dt.datetime(2026, 1, 1, 0, 0, 0, tzinfo=_dt.timezone.utc)
    _write_csv(
        p,
        [
            {
                "drill_date_utc": drill_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "outcome": "ok",
                "restored_from_offsite": "1",
                "target_conn_hash": "xyz",
                "drill_duration_s": "900",
                "operator": "ops",
                "notes": "",
            }
        ],
    )
    # 101 days later → over the 100-day default threshold
    now = drill_dt + _dt.timedelta(days=101)
    rep = compute_dr_drill_age(p, now_utc=now)
    assert rep.severity == "crit"
    assert rep.age_days is not None and rep.age_days >= ALERT_DAYS
    assert "alert=" in rep.reason


def test_ok_just_under_alert_days(tmp_path: Path) -> None:
    p = tmp_path / "dr_drills.csv"
    drill_dt = _dt.datetime(2026, 1, 1, 0, 0, 0, tzinfo=_dt.timezone.utc)
    _write_csv(
        p,
        [
            {
                "drill_date_utc": drill_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "outcome": "ok",
                "restored_from_offsite": "1",
                "target_conn_hash": "xyz",
                "drill_duration_s": "900",
                "operator": "ops",
                "notes": "",
            }
        ],
    )
    # 99 days later → still under the default 100-day threshold
    now = drill_dt + _dt.timedelta(days=99)
    rep = compute_dr_drill_age(p, now_utc=now)
    assert rep.severity == "ok"
    assert rep.age_days is not None and rep.age_days < ALERT_DAYS


# ── picks latest ok row when multiple rows exist ──────────────────────


def test_picks_latest_ok_row(tmp_path: Path) -> None:
    p = tmp_path / "dr_drills.csv"
    old_dt = _dt.datetime(2026, 1, 1, 0, 0, 0, tzinfo=_dt.timezone.utc)
    new_dt = _dt.datetime(2026, 4, 1, 0, 0, 0, tzinfo=_dt.timezone.utc)
    _write_csv(
        p,
        [
            {
                "drill_date_utc": old_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "outcome": "ok",
                "restored_from_offsite": "1",
                "target_conn_hash": "aaa",
                "drill_duration_s": "1000",
                "operator": "ops1",
                "notes": "",
            },
            {
                "drill_date_utc": new_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "outcome": "ok",
                "restored_from_offsite": "1",
                "target_conn_hash": "bbb",
                "drill_duration_s": "1200",
                "operator": "ops2",
                "notes": "",
            },
        ],
    )
    now = new_dt + _dt.timedelta(days=5)
    rep = compute_dr_drill_age(p, now_utc=now)
    assert rep.last_drill_date_utc == new_dt
    assert rep.age_days == pytest.approx(5.0, abs=0.01)
    assert rep.severity == "ok"


# ── custom alert_days parameter ───────────────────────────────────────


def test_custom_alert_days(tmp_path: Path) -> None:
    p = tmp_path / "dr_drills.csv"
    drill_dt = _dt.datetime(2026, 1, 1, 0, 0, 0, tzinfo=_dt.timezone.utc)
    _write_csv(
        p,
        [
            {
                "drill_date_utc": drill_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "outcome": "ok",
                "restored_from_offsite": "1",
                "target_conn_hash": "abc",
                "drill_duration_s": "600",
                "operator": "ops",
                "notes": "",
            }
        ],
    )
    now = drill_dt + _dt.timedelta(days=20)
    # Custom low threshold of 10 days → crit at 20 days
    rep = compute_dr_drill_age(p, now_utc=now, alert_days=10.0)
    assert rep.severity == "crit"


# ── to_dict serialisation ─────────────────────────────────────────────


def test_to_dict_unknown(tmp_path: Path) -> None:
    rep = compute_dr_drill_age(tmp_path / "gone.csv")
    d = rep.to_dict()
    assert d["severity"] == "unknown"
    assert d["age_days"] is None
    assert d["last_drill_date_utc"] is None


def test_to_dict_ok(tmp_path: Path) -> None:
    p = tmp_path / "dr_drills.csv"
    drill_dt = _dt.datetime(2026, 5, 1, 0, 0, 0, tzinfo=_dt.timezone.utc)
    _write_csv(
        p,
        [
            {
                "drill_date_utc": "2026-05-01",  # date-only format
                "outcome": "ok",
                "restored_from_offsite": "1",
                "target_conn_hash": "def",
                "drill_duration_s": "500",
                "operator": "ops",
                "notes": "",
            }
        ],
    )
    now = drill_dt + _dt.timedelta(days=3)
    rep = compute_dr_drill_age(p, now_utc=now)
    d = rep.to_dict()
    assert d["severity"] == "ok"
    assert isinstance(d["last_drill_date_utc"], str)
    assert isinstance(d["age_days"], float)
