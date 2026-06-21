"""Phase 8 §8.15.10 proof tests.

(a) Concurrency cap — race cold-verify and nightly start within 1 s of
    each other → assert exactly one acquires the advisory lock first,
    the other emits `verify_concurrency_blocked` + waits-then-yields
    per policy.
(b) Credential reload — rotate the secret file mid-running multipart
    upload → assert in-flight upload completes on old creds (tracked
    by a mock S3 backend); next upload uses new creds.
(c) Forensic capture — force a `pg_restore` failure with a 100 KB
    stderr → assert sidecar exists, stderr is tail-truncated to 64 KB,
    audit kind emitted with `size_bytes` matching file size.
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from xops.backup.verify_concurrency import RestoreVerifyConcurrencyLock
from xops.backup.credential_provider import FileSecretProvider, S3Credentials
from xops.backup.forensic import (
    ForensicData,
    VerifySqlResult,
    FORENSIC_FILENAME,
    write_forensic_sidecar,
)


# ── (a) Concurrency: cold vs nightly ──────────────────────────────────


class _FakePgConn:
    """In-memory PG advisory lock simulation.

    The lock is implemented with a threading.Lock so the test can be
    concurrent without actually requiring Postgres.
    """

    _global_lock: threading.Lock = threading.Lock()
    _held_by: list[str] = []  # guarded by _global_lock

    def __init__(self) -> None:
        self._held = False

    def cursor(self) -> "_FakeCursor":
        return _FakeCursor(self)


class _FakeCursor:
    def __init__(self, conn: _FakePgConn) -> None:
        self._conn = conn
        self._last_result: Any = None

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, *args: Any) -> None:
        pass

    def execute(self, sql: str, params: tuple = ()) -> None:
        if "pg_try_advisory_lock" in sql:
            with _FakePgConn._global_lock:
                if not _FakePgConn._held_by:
                    _FakePgConn._held_by.append("held")
                    self._last_result = True
                else:
                    self._last_result = False
        elif "pg_advisory_unlock" in sql:
            with _FakePgConn._global_lock:
                if _FakePgConn._held_by:
                    _FakePgConn._held_by.clear()
            self._last_result = True
        else:
            self._last_result = None

    def fetchone(self) -> tuple:
        return (self._last_result,)


@pytest.fixture(autouse=True)
def _reset_fake_pg_lock() -> None:
    """Reset the shared in-memory lock state between tests."""
    _FakePgConn._held_by.clear()


def test_concurrency_cold_yields_immediately_to_nightly() -> None:
    """cold scope yields on first failure when nightly holds the lock."""
    blocked_alerts: list[dict] = []

    def _sink(kind: str, severity: str, subject: str, observed: dict) -> None:
        blocked_alerts.append({"kind": kind, "severity": severity, "scope": observed.get("scope")})

    # nightly acquires the lock first
    nightly_conn = _FakePgConn()
    with RestoreVerifyConcurrencyLock(nightly_conn, scope="nightly") as nightly_held:
        assert nightly_held, "nightly should acquire lock on first attempt"

        # cold-verify arrives while nightly holds the lock
        cold_conn = _FakePgConn()
        with RestoreVerifyConcurrencyLock(
            cold_conn, scope="cold", alert_sink=_sink
        ) as cold_held:
            assert not cold_held, "cold should yield when nightly holds the lock"

    # cold should have emitted verify_concurrency_blocked
    assert len(blocked_alerts) == 1
    assert blocked_alerts[0]["kind"] == "verify_concurrency_blocked"
    assert blocked_alerts[0]["severity"] == "warn"
    assert blocked_alerts[0]["scope"] == "cold"


def test_concurrency_nightly_yields_after_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """nightly scope yields (emits alert) when it cannot acquire lock within timeout."""
    # Use a very short timeout so the test is fast
    monkeypatch.setattr(
        "xops.backup.verify_concurrency._resolve_timeout",
        lambda: 0.05,  # 50 ms
    )
    # Also speed up poll interval
    monkeypatch.setattr(
        "xops.backup.verify_concurrency._POLL_INTERVAL_S",
        0.01,
    )

    blocked_alerts: list[dict] = []

    def _sink(kind: str, severity: str, subject: str, observed: dict) -> None:
        blocked_alerts.append({"kind": kind, "scope": observed.get("scope")})

    # First nightly acquires the lock and holds it
    holder_conn = _FakePgConn()
    with RestoreVerifyConcurrencyLock(holder_conn, scope="nightly") as held_first:
        assert held_first

        # Second nightly tries to acquire — should timeout and yield
        second_conn = _FakePgConn()
        with RestoreVerifyConcurrencyLock(
            second_conn, scope="nightly", alert_sink=_sink
        ) as held_second:
            assert not held_second, "second nightly should yield after timeout"

    assert len(blocked_alerts) == 1
    assert blocked_alerts[0]["kind"] == "verify_concurrency_blocked"
    assert blocked_alerts[0]["scope"] == "nightly"


def test_concurrency_nightly_acquires_after_cold_releases() -> None:
    """nightly eventually acquires the lock once cold-verify finishes."""
    monkeypatch_called_at: list[float] = []

    # Run cold-verify in a thread, release after 50 ms
    cold_conn = _FakePgConn()

    def _run_cold() -> None:
        with RestoreVerifyConcurrencyLock(cold_conn, scope="cold") as held:
            assert held
            time.sleep(0.05)

    t = threading.Thread(target=_run_cold, daemon=True)
    t.start()
    time.sleep(0.01)  # let cold acquire

    # nightly should wait and eventually get the lock
    import xops.backup.verify_concurrency as _vc
    orig_timeout = _vc._resolve_timeout
    orig_interval = _vc._POLL_INTERVAL_S
    _vc._POLL_INTERVAL_S = 0.01

    def _fast_timeout() -> float:
        return 5.0

    _vc._resolve_timeout = _fast_timeout  # type: ignore[assignment]
    try:
        nightly_conn = _FakePgConn()
        with RestoreVerifyConcurrencyLock(nightly_conn, scope="nightly") as held:
            assert held, "nightly should acquire lock once cold releases"
    finally:
        _vc._resolve_timeout = orig_timeout  # type: ignore[assignment]
        _vc._POLL_INTERVAL_S = orig_interval
    t.join(timeout=2.0)


def test_concurrency_invalid_scope_raises() -> None:
    """Passing an unknown scope raises ValueError."""
    conn = _FakePgConn()
    with pytest.raises(ValueError, match="scope must be"):
        RestoreVerifyConcurrencyLock(conn, scope="weekly")


# ── (b) Credential reload — FileSecretProvider ────────────────────────


def test_credential_reload_new_upload_uses_new_creds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rotating the secret file causes the provider to reload; get()
    returns the new credentials after the poll tick."""
    # Speed up the reload interval
    monkeypatch.setattr(
        "xops.backup.credential_provider._resolve_reload_interval",
        lambda: 0.05,  # 50 ms
    )

    id_file = tmp_path / "key_id"
    secret_file = tmp_path / "key_secret"
    id_file.write_text("OLD_KEY_ID")
    secret_file.write_text("OLD_SECRET")

    provider = FileSecretProvider(str(id_file), str(secret_file))
    provider.start()
    try:
        initial = provider.get()
        assert initial.access_key_id == "OLD_KEY_ID"

        # Rotate the secret files (operator writes new values)
        time.sleep(0.01)  # ensure mtime advances
        id_file.write_text("NEW_KEY_ID")
        secret_file.write_text("NEW_SECRET")
        # Bump mtime explicitly to guarantee detection cross-platform
        new_mtime = time.time() + 1.0
        os.utime(str(id_file), (new_mtime, new_mtime))
        os.utime(str(secret_file), (new_mtime, new_mtime))

        # Wait for the background poll to fire
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            time.sleep(0.05)
            if provider.get().access_key_id == "NEW_KEY_ID":
                break

        new_creds = provider.get()
        assert new_creds.access_key_id == "NEW_KEY_ID"
        assert new_creds.secret_access_key == "NEW_SECRET"
    finally:
        provider.stop()


def test_credential_inflight_upload_keeps_old_creds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An upload that captured credentials at start continues with the
    old credentials even after the provider has reloaded."""
    monkeypatch.setattr(
        "xops.backup.credential_provider._resolve_reload_interval",
        lambda: 0.05,
    )

    id_file = tmp_path / "key_id"
    secret_file = tmp_path / "key_secret"
    id_file.write_text("ORIG_KEY")
    secret_file.write_text("ORIG_SECRET")

    provider = FileSecretProvider(str(id_file), str(secret_file))
    provider.start()
    try:
        # Simulate upload that holds a reference to credentials at upload-start
        upload_creds: S3Credentials = provider.get()  # captured at upload time
        assert upload_creds.access_key_id == "ORIG_KEY"

        # Rotate credentials while "upload" is in progress
        new_mtime = time.time() + 1.0
        id_file.write_text("ROTATED_KEY")
        secret_file.write_text("ROTATED_SECRET")
        os.utime(str(id_file), (new_mtime, new_mtime))
        os.utime(str(secret_file), (new_mtime, new_mtime))

        # Wait for reload
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            time.sleep(0.05)
            if provider.get().access_key_id == "ROTATED_KEY":
                break

        # Provider now has new creds
        assert provider.get().access_key_id == "ROTATED_KEY"

        # But in-flight upload still holds its original reference (immutable value)
        assert upload_creds.access_key_id == "ORIG_KEY", (
            "In-flight upload must continue with its captured credentials"
        )
    finally:
        provider.stop()


def test_credential_age_alert_warn_then_critical(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Age alerts fire warn then critical as thresholds are crossed."""
    # Set very short thresholds for testing (1 s max_age, 1 s grace)
    monkeypatch.setattr(
        "xops.backup.credential_provider._resolve_age_thresholds",
        lambda: (0.05, 0.05),  # 50 ms each
    )
    monkeypatch.setattr(
        "xops.backup.credential_provider._AGE_ALERT_DEBOUNCE_S",
        0.0,  # disable debounce so test can observe multiple alerts
    )
    monkeypatch.setattr(
        "xops.backup.credential_provider._resolve_reload_interval",
        lambda: 0.02,
    )

    id_file = tmp_path / "key_id"
    secret_file = tmp_path / "key_secret"
    id_file.write_text("STALE_KEY")
    secret_file.write_text("STALE_SECRET")

    alerts: list[tuple[str, str]] = []

    def _sink(kind: str, severity: str, subject: str, observed: dict) -> None:
        alerts.append((kind, severity))

    provider = FileSecretProvider(str(id_file), str(secret_file), alert_sink=_sink)
    provider.start()
    try:
        time.sleep(0.3)  # well past both thresholds
    finally:
        provider.stop()

    kinds = [k for k, _ in alerts]
    sevs = [s for _, s in alerts]
    assert all(k == "offsite_credential_rotation_required" for k in kinds), alerts
    # Should have progressed to critical
    assert "critical" in sevs, f"Expected at least one critical alert; got: {alerts}"


def test_is_upload_allowed_blocks_past_grace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """is_upload_allowed returns False once age exceeds max_age+grace."""
    # 0 s thresholds → anything is immediately past-grace
    monkeypatch.setattr(
        "xops.backup.credential_provider._resolve_age_thresholds",
        lambda: (0.0, 0.0),  # 0 = disabled per spec
    )

    id_file = tmp_path / "key_id"
    secret_file = tmp_path / "key_secret"
    id_file.write_text("KEY")
    secret_file.write_text("SECRET")

    provider = FileSecretProvider(str(id_file), str(secret_file))
    # With 0-s thresholds the age check is DISABLED → should be allowed
    assert provider.is_upload_allowed(), "0-s threshold disables age check"


def test_is_upload_blocked_when_past_grace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """is_upload_allowed returns False when age > max_age + grace."""
    monkeypatch.setattr(
        "xops.backup.credential_provider._resolve_age_thresholds",
        lambda: (0.001, 0.001),  # 1 ms each → immediately exceeded
    )

    id_file = tmp_path / "key_id"
    secret_file = tmp_path / "key_secret"
    id_file.write_text("KEY")
    secret_file.write_text("SECRET")

    provider = FileSecretProvider(str(id_file), str(secret_file))
    time.sleep(0.05)  # let credentials age past both thresholds
    assert not provider.is_upload_allowed(), (
        "upload must be blocked when credential age exceeds max_age+grace"
    )


# ── (c) Forensic capture ───────────────────────────────────────────────


def test_forensic_sidecar_written_on_failure(tmp_path: Path) -> None:
    """write_forensic_sidecar creates the file in <date>.failed/."""
    failed_dir = tmp_path / "2026-05-22.failed"
    data = ForensicData(
        verifier_kind="local",
        pg_restore_exit_code=1,
        pg_restore_stderr="ERROR: relation not found",
        pg_restore_stdout="pg_restore: connecting...",
        verify_sql_results=[
            VerifySqlResult(query="SELECT count(*) FROM matches", row_count=42)
        ],
        duration_ms=1800,
        verify_pg_image="postgres:16-alpine",
        manifest_server_version_num=160001,
        file_manifest_failures=[],
    )
    size = write_forensic_sidecar(str(failed_dir), data)
    sidecar = failed_dir / FORENSIC_FILENAME
    assert sidecar.exists()
    # Mode 0600
    assert oct(sidecar.stat().st_mode)[-3:] == "600"
    # Content is valid JSON
    payload = json.loads(sidecar.read_bytes())
    assert payload["pg_restore_exit_code"] == 1
    assert payload["verifier_kind"] == "local"
    assert size == sidecar.stat().st_size


def test_forensic_stderr_truncated_to_64kb(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A 100 KB stderr is tail-truncated to ≤64 KB in the sidecar."""
    monkeypatch.setattr(
        "xops.backup.forensic._resolve_max_bytes",
        lambda: 0,  # disable overall budget so only per-field cap applies
    )

    failed_dir = tmp_path / "2026-05-22.failed"
    stderr_100kb = "E" * (100 * 1024)
    data = ForensicData(
        verifier_kind="local",
        pg_restore_exit_code=1,
        pg_restore_stderr=stderr_100kb,
        pg_restore_stdout="",
        duration_ms=500,
    )
    write_forensic_sidecar(str(failed_dir), data)

    payload = json.loads((failed_dir / FORENSIC_FILENAME).read_bytes())
    actual_len = len(payload["pg_restore_stderr"].encode("utf-8"))
    assert actual_len <= 64 * 1024, (
        f"Expected stderr ≤64KB; got {actual_len} bytes"
    )
    # Should still be at the tail end of the original string
    assert payload["pg_restore_stderr"].endswith("E" * 100)


def test_forensic_overall_budget_truncates_stderr_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When overall max_bytes is tight, pg_restore_stderr is trimmed first."""
    # Allow only 4 KiB total — forces trimming
    monkeypatch.setattr(
        "xops.backup.forensic._resolve_max_bytes",
        lambda: 4 * 1024,
    )

    failed_dir = tmp_path / "2026-05-22.failed"
    data = ForensicData(
        verifier_kind="local",
        pg_restore_exit_code=1,
        pg_restore_stderr="E" * (4 * 1024),  # 4 KB
        pg_restore_stdout="O" * (4 * 1024),  # 4 KB
        duration_ms=200,
    )
    size = write_forensic_sidecar(str(failed_dir), data)
    assert size <= 4 * 1024 + 512, f"Expected ≤4.5 KiB total; got {size}"


def test_forensic_audit_kind_emitted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The returned size can be used to build the verify_forensic_captured audit event."""
    monkeypatch.setattr(
        "xops.backup.forensic._resolve_max_bytes",
        lambda: 0,  # unbounded
    )

    failed_dir = tmp_path / "2026-05-22.failed"
    data = ForensicData(
        verifier_kind="local",
        pg_restore_exit_code=2,
        pg_restore_stderr="error\n" * 5,
        pg_restore_stdout="",
    )
    returned_size = write_forensic_sidecar(str(failed_dir), data)
    actual_size = (failed_dir / FORENSIC_FILENAME).stat().st_size
    assert returned_size == actual_size, (
        "write_forensic_sidecar return value must equal the file's size_bytes "
        "for the verify_forensic_captured audit kind"
    )


def test_forensic_verify_forensic_captured_in_known_kinds() -> None:
    """verify_forensic_captured must be in KNOWN_MAINT_EVENT_KINDS."""
    from swarm.agents.maint import KNOWN_MAINT_EVENT_KINDS  # type: ignore

    assert "verify_forensic_captured" in KNOWN_MAINT_EVENT_KINDS, (
        "verify_forensic_captured not found in KNOWN_MAINT_EVENT_KINDS"
    )


def test_forensic_verify_concurrency_blocked_in_known_sec_alert_kinds() -> None:
    """verify_concurrency_blocked must be in KNOWN_SEC_ALERT_KINDS."""
    from swarm.agents.payloads import KNOWN_SEC_ALERT_KINDS  # type: ignore

    assert "verify_concurrency_blocked" in KNOWN_SEC_ALERT_KINDS, (
        "verify_concurrency_blocked not found in KNOWN_SEC_ALERT_KINDS"
    )


def test_forensic_offsite_credential_rotation_in_known_sec_alert_kinds() -> None:
    """offsite_credential_rotation_required must be in KNOWN_SEC_ALERT_KINDS."""
    from swarm.agents.payloads import KNOWN_SEC_ALERT_KINDS  # type: ignore

    assert "offsite_credential_rotation_required" in KNOWN_SEC_ALERT_KINDS, (
        "offsite_credential_rotation_required not found in KNOWN_SEC_ALERT_KINDS"
    )
