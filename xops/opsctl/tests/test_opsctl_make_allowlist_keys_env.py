"""Phase 8 S8.16.10 - make-level env contract for allowlist key ops."""
from __future__ import annotations

from typing import List

from xops.makefile import opsctl as make_opsctl


def _clear_env(monkeypatch) -> None:
    for key in (
        "TARGET",
        "BATCH_SIZE",
        "NO_REHASH",
        "REASON",
        "CLIENT_ID",
        "CONFIRM",
        "DRY_RUN",
        "JSON",
    ):
        monkeypatch.delenv(key, raising=False)


def test_make_bootstrap_allowlist_key(monkeypatch) -> None:
    captured: List[str] = []

    def _fake_run(args: List[str]) -> int:
        captured[:] = list(args)
        return 0

    monkeypatch.setattr(make_opsctl, "_run_opsctl", _fake_run)
    rc = make_opsctl.cmd_bootstrap_allowlist_key([])
    assert rc == 0
    assert captured == ["bootstrap-allowlist-key"]


def test_make_allowlist_rehash_env_mapping(monkeypatch) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("TARGET", "all")
    monkeypatch.setenv("BATCH_SIZE", "200")
    monkeypatch.setenv("REASON", "ops-migration")
    monkeypatch.setenv("DRY_RUN", "1")
    monkeypatch.setenv("JSON", "1")

    captured: List[str] = []

    def _fake_run(args: List[str]) -> int:
        captured[:] = list(args)
        return 0

    monkeypatch.setattr(make_opsctl, "_run_opsctl", _fake_run)
    rc = make_opsctl.cmd_allowlist_rehash([])
    assert rc == 0
    assert captured == [
        "allowlist-rehash",
        "--target",
        "all",
        "--batch-size",
        "200",
        "--reason",
        "ops-migration",
        "--dry-run",
        "--json",
    ]


def test_make_rotate_allowlist_key_env_mapping(monkeypatch) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("TARGET", "allowlist_hmac")
    monkeypatch.setenv("NO_REHASH", "1")
    monkeypatch.setenv("REASON", "break-glass")
    monkeypatch.setenv("CLIENT_ID", "opsctl-test")
    monkeypatch.setenv("DRY_RUN", "1")

    captured: List[str] = []

    def _fake_run(args: List[str]) -> int:
        captured[:] = list(args)
        return 0

    monkeypatch.setattr(make_opsctl, "_run_opsctl", _fake_run)
    rc = make_opsctl.cmd_rotate_allowlist_key([])
    assert rc == 0
    assert captured == [
        "rotate-allowlist-key",
        "--target",
        "allowlist_hmac",
        "--no-rehash",
        "--client-id",
        "opsctl-test",
        "--reason",
        "break-glass",
        "--dry-run",
    ]
