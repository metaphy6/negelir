"""Phase 8 §8.14.3 — age binary supply-chain pin proof tests.

Covers all three proof points from the ROADMAP §8.14.3 bullet:

(a) Run agent boot with ``age`` of a different version → assert
    :class:`~swarm.agents.maint.backup.AgeVersionError` is raised with
    ``fail_safe_age_version_mismatch`` in the message, and that the
    agent did NOT write to the spool or tick a cron.

(b) Run ``make verify.age-pin`` against a tampered provenance file
    (wrong sha) → assert exit non-zero with ``provenance_drift`` in
    output.

(c) Run ``ops.restore`` on a host with no ``age`` installed → assert
    ``age_binary_not_found`` in stderr output and a non-zero exit.
"""
from __future__ import annotations

import hashlib
import io
import os
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Bullet (a): agent boot with wrong age version
# ---------------------------------------------------------------------------

from ai.swarm.agents.maint.backup import (
    AgeVersionError,
    InMemoryPrunerStorage,
    InMemoryQuarantineStore,
    MaintBackupAgent,
    NoopAgeVersionChecker,
    NoopDumpExecutor,
    NoopVerifier,
    StaticDiskGauge,
)


def _build_agent(age_checker: NoopAgeVersionChecker) -> MaintBackupAgent:
    """Construct a :class:`MaintBackupAgent` with all non-age guards bypassed."""
    return MaintBackupAgent(
        dump=NoopDumpExecutor(),
        verifier=NoopVerifier(),
        pruner=InMemoryPrunerStorage(),
        quarantine=InMemoryQuarantineStore(),
        disk=StaticDiskGauge(free_bytes=64 * 1024 ** 3),
        enforce_permissions=False,
        age_version_checker=age_checker,
    )


def test_refuse_wrong_age_version() -> None:
    """§8.14.3 (a-1): age 9.9.9 != pin 1.2.0 raises AgeVersionError
    containing fail_safe_age_version_mismatch."""
    checker = NoopAgeVersionChecker(version="9.9.9")
    with pytest.raises(AgeVersionError) as exc_info:
        _build_agent(checker)
    msg = str(exc_info.value)
    assert "fail_safe_age_version_mismatch" in msg, msg
    assert "9.9.9" in msg, msg
    assert "1.2.0" in msg, msg


def test_refuse_wrong_age_version_no_spool_writes() -> None:
    """§8.14.3 (a-2): the agent raises before making any dump or prune
    calls — dump_toc and pruner.counts are both empty."""
    dump = NoopDumpExecutor()
    pruner = InMemoryPrunerStorage()
    checker = NoopAgeVersionChecker(version="0.0.1")
    with pytest.raises(AgeVersionError):
        MaintBackupAgent(
            dump=dump,
            verifier=NoopVerifier(),
            pruner=pruner,
            quarantine=InMemoryQuarantineStore(),
            disk=StaticDiskGauge(free_bytes=64 * 1024 ** 3),
            enforce_permissions=False,
            age_version_checker=checker,
        )
    # No dump or prune calls were made.
    assert dump.dump_toc == [], f"Unexpected dump_toc: {dump.dump_toc!r}"
    assert pruner.counts == {}, f"Unexpected pruner counts: {pruner.counts!r}"


def test_matching_age_version_starts_ok() -> None:
    """§8.14.3 (a-3): version matching pin starts the agent normally."""
    checker = NoopAgeVersionChecker(version="1.2.0")
    agent = _build_agent(checker)
    assert agent is not None


def test_error_message_includes_installed_and_expected() -> None:
    """§8.14.3 (a-4): AgeVersionError message carries both installed and
    expected versions so the operator knows exactly what to fix."""
    checker = NoopAgeVersionChecker(version="2.0.0")
    with pytest.raises(AgeVersionError) as exc_info:
        _build_agent(checker)
    msg = str(exc_info.value)
    assert "2.0.0" in msg, f"installed version missing: {msg!r}"
    assert "1.2.0" in msg, f"expected version missing: {msg!r}"


# ---------------------------------------------------------------------------
# Bullet (b): verify.age-pin against tampered provenance file
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[5]  # ai/swarm/agents/maint/tests/ → root
_BACKUP_PIN_PY = _REPO_ROOT / "xops" / "makefile" / "backup_pin.py"


def _write_provenance(directory: Path, sha256: str, version: str = "1.2.0") -> Path:
    """Write a minimal provenance INI to ``directory``."""
    content = textwrap.dedent(f"""
        [{version}]
        version = {version}
        sha256 = {sha256}
        source_url = https://github.com/FiloSottile/age/releases/download/v{version}/age-v{version}-linux-amd64.tar.gz
        sigstore_cert_identity_if_any =
        recorded_at = 2026-01-01T00:00:00+00:00
    """).lstrip()
    path = directory / "age_binary_provenance.txt"
    path.write_text(content)
    return path


def _fake_tarball(directory: Path) -> Path:
    """Create a tiny fake tarball file for SHA-256 checking."""
    path = directory / "age-v1.2.0-linux-amd64.tar.gz"
    path.write_bytes(b"fake tarball content for testing")
    return path


def test_verify_age_pin_tampered_provenance_exits_nonzero() -> None:
    """§8.14.3 (b): tampered provenance (wrong sha) → exit non-zero with
    provenance_drift in output."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        fake_tar = _fake_tarball(tmp_dir)
        real_sha = hashlib.sha256(fake_tar.read_bytes()).hexdigest()
        # Flip the last hex digit so the SHA is wrong.
        wrong_sha = real_sha[:-1] + ("1" if real_sha[-1] != "1" else "0")
        prov_file = _write_provenance(tmp_dir, sha256=wrong_sha)

        env = {
            **os.environ,
            "AGE_PIN_LOCAL_TARBALL": str(fake_tar),
            "_NEGELIR_PROVENANCE_OVERRIDE": str(prov_file),
        }
        result = subprocess.run(
            [sys.executable, str(_BACKUP_PIN_PY), "verify-age-pin"],
            capture_output=True,
            text=True,
            env=env,
        )

    assert result.returncode != 0, (
        f"Expected non-zero exit for tampered provenance; got 0.\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
    combined = result.stdout + result.stderr
    assert "provenance_drift" in combined, (
        f"Expected 'provenance_drift' in output; got:\n{combined!r}"
    )


def test_verify_age_pin_correct_sha_exits_zero() -> None:
    """§8.14.3 (b-complement): correct sha exits 0."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        fake_tar = _fake_tarball(tmp_dir)
        correct_sha = hashlib.sha256(fake_tar.read_bytes()).hexdigest()
        prov_file = _write_provenance(tmp_dir, sha256=correct_sha)

        env = {
            **os.environ,
            "AGE_PIN_LOCAL_TARBALL": str(fake_tar),
            "_NEGELIR_PROVENANCE_OVERRIDE": str(prov_file),
        }
        result = subprocess.run(
            [sys.executable, str(_BACKUP_PIN_PY), "verify-age-pin"],
            capture_output=True,
            text=True,
            env=env,
        )

    assert result.returncode == 0, (
        f"Expected 0 exit for matching SHA; got {result.returncode}.\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )


# ---------------------------------------------------------------------------
# Bullet (c): ops.restore with no age installed
# ---------------------------------------------------------------------------

_RESTORE_MODULE = "xops.opsctl.subcommands.restore"


def _make_restore_args() -> "argparse.Namespace":  # type: ignore[name-defined]
    import argparse
    return argparse.Namespace(
        target="2026-01-01",
        from_offsite=False,
        destination_conn="",
        confirm_overwrite_live=False,
        reason="dr-test",
        client_id="test-client",
        json=False,
        dry_run=True,
        confirm="",
    )


def _force_prod_profile() -> tuple[object, str]:
    """Temporarily switch cfg.profile to prod; returns (cfg, original_profile)."""
    from common.config import cfg as _cfg
    original = str(_cfg.profile)
    object.__setattr__(_cfg, "profile", "prod")
    return _cfg, original


def test_restore_no_age_binary_exits_nonzero() -> None:
    """§8.14.3 (c-1): ops.restore with no age binary exits non-zero with
    age_binary_not_found in stderr."""
    from xops.opsctl.subcommands.restore import run as restore_run

    stderr_capture = io.StringIO()
    _cfg, original_profile = _force_prod_profile()
    try:
        with (
            patch(f"{_RESTORE_MODULE}.subprocess.run", side_effect=FileNotFoundError("age")),
            patch("sys.stderr", stderr_capture),
        ):
            rc = restore_run(_make_restore_args(), bus=None)
    finally:
        object.__setattr__(_cfg, "profile", original_profile)

    assert rc != 0, f"Expected non-zero exit; got {rc}"
    stderr_out = stderr_capture.getvalue()
    assert "age_binary_not_found" in stderr_out, (
        f"Expected 'age_binary_not_found' in stderr; got:\n{stderr_out!r}"
    )


def test_restore_no_age_binary_includes_runbook_link() -> None:
    """§8.14.3 (c-2): stderr includes the runbook link (FiloSottile/age)."""
    from xops.opsctl.subcommands.restore import run as restore_run

    stderr_capture = io.StringIO()
    _cfg, original_profile = _force_prod_profile()
    try:
        with (
            patch(f"{_RESTORE_MODULE}.subprocess.run", side_effect=FileNotFoundError("age")),
            patch("sys.stderr", stderr_capture),
        ):
            restore_run(_make_restore_args(), bus=None)
    finally:
        object.__setattr__(_cfg, "profile", original_profile)

    stderr_out = stderr_capture.getvalue()
    assert "FiloSottile/age" in stderr_out, (
        f"Expected runbook link in stderr; got:\n{stderr_out!r}"
    )


def test_restore_wrong_age_version_non_mock_exits_nonzero() -> None:
    """§8.14.3 (c-3): ops.restore with wrong age version on prod profile
    exits non-zero with fail_safe_age_version_mismatch_local."""
    from common.config import cfg as _cfg
    from xops.opsctl.subcommands.restore import run as restore_run

    mock_completed = type("CP", (), {
        "stdout": "age v9.9.9\n",
        "stderr": "",
        "returncode": 0,
    })()

    stderr_capture = io.StringIO()
    original_profile = str(_cfg.profile)
    original_pin = str(_cfg.maint_backup_age_binary_version)
    try:
        object.__setattr__(_cfg, "profile", "prod")
        object.__setattr__(_cfg, "maint_backup_age_binary_version", "1.2.0")

        with (
            patch(f"{_RESTORE_MODULE}.subprocess.run", return_value=mock_completed),
            patch("sys.stderr", stderr_capture),
        ):
            rc = restore_run(_make_restore_args(), bus=None)
    finally:
        object.__setattr__(_cfg, "profile", original_profile)
        object.__setattr__(_cfg, "maint_backup_age_binary_version", original_pin)

    assert rc != 0, f"Expected non-zero exit; got {rc}"
    stderr_out = stderr_capture.getvalue()
    assert "fail_safe_age_version_mismatch_local" in stderr_out, (
        f"Expected fail_safe_age_version_mismatch_local in stderr;\n{stderr_out!r}"
    )
