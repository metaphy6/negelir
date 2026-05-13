"""Phase 8 §8.3 — make-level `ops.restore` env contract.

Pins the Make wrapper shape required by the restore runbook:

* `DATE=YYYY-MM-DD` is the dump date source of truth.
* `TARGET=<dsn>` is the optional destination override.
* Legacy compatibility remains for old invocations that used
  `TARGET=<date>` and optional `DESTINATION_CONN=<dsn>`.
"""
from __future__ import annotations

from typing import List

from xops.makefile import opsctl as make_opsctl


def _clear_restore_env(monkeypatch) -> None:
    for key in (
        "DATE",
        "TARGET",
        "DESTINATION_CONN",
        "FROM_OFFSITE",
        "CONFIRM_OVERWRITE_LIVE",
        "REASON",
        "CLIENT_ID",
        "CONFIRM",
        "DRY_RUN",
        "JSON",
    ):
        monkeypatch.delenv(key, raising=False)


def test_restore_requires_date(monkeypatch) -> None:
    _clear_restore_env(monkeypatch)
    assert make_opsctl.cmd_restore([]) == 64


def test_restore_maps_date_and_target_destination(monkeypatch) -> None:
    _clear_restore_env(monkeypatch)
    monkeypatch.setenv("DATE", "2026-05-01")
    monkeypatch.setenv("TARGET", "postgresql://dr@host/negelir_restore")
    monkeypatch.setenv("FROM_OFFSITE", "1")
    monkeypatch.setenv("CONFIRM_OVERWRITE_LIVE", "1")
    monkeypatch.setenv("REASON", "dr drill")
    monkeypatch.setenv("DRY_RUN", "1")
    monkeypatch.setenv("JSON", "1")

    captured: List[str] = []

    def _fake_run(args: List[str]) -> int:
        captured[:] = list(args)
        return 0

    monkeypatch.setattr(make_opsctl, "_run_opsctl", _fake_run)

    rc = make_opsctl.cmd_restore([])
    assert rc == 0
    assert captured == [
        "restore",
        "--target",
        "2026-05-01",
        "--from-offsite",
        "--destination-conn",
        "postgresql://dr@host/negelir_restore",
        "--confirm-overwrite-live",
        "--reason",
        "dr drill",
        "--dry-run",
        "--json",
    ]


def test_restore_legacy_target_date_is_still_accepted(monkeypatch) -> None:
    _clear_restore_env(monkeypatch)
    monkeypatch.setenv("TARGET", "2026-05-01")

    captured: List[str] = []

    def _fake_run(args: List[str]) -> int:
        captured[:] = list(args)
        return 0

    monkeypatch.setattr(make_opsctl, "_run_opsctl", _fake_run)

    rc = make_opsctl.cmd_restore([])
    assert rc == 0
    assert captured == ["restore", "--target", "2026-05-01"]


def test_restore_legacy_destination_conn_fallback(monkeypatch) -> None:
    _clear_restore_env(monkeypatch)
    monkeypatch.setenv("DATE", "2026-05-01")
    monkeypatch.setenv("DESTINATION_CONN", "postgresql://legacy@host/db")

    captured: List[str] = []

    def _fake_run(args: List[str]) -> int:
        captured[:] = list(args)
        return 0

    monkeypatch.setattr(make_opsctl, "_run_opsctl", _fake_run)

    rc = make_opsctl.cmd_restore([])
    assert rc == 0
    assert captured == [
        "restore",
        "--target",
        "2026-05-01",
        "--destination-conn",
        "postgresql://legacy@host/db",
    ]
