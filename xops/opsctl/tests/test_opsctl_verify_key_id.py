"""Tests for ``ops.verify-key-id`` (Phase 8 §8.16.14 self-verification)."""
from __future__ import annotations

import json
import os
import subprocess
import stat
from pathlib import Path
from typing import Any, Dict

import pytest

from common.config import Config
from xops.maint.key_id import derive_operator_key_id
from xops.opsctl._exit_codes import ExitCode
from xops.opsctl.subcommands import verify_key_id

REPO_ROOT = Path(__file__).resolve().parents[3]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_key_file(tmp_path: Path, key_bytes: bytes) -> Path:
    """Write key bytes to a 0600 file and return the path."""
    p = tmp_path / "opsctl_key"
    fd = os.open(str(p), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, key_bytes)
    finally:
        os.close(fd)
    return p


def _registry(operators: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "_comment": "test registry",
        "_schema": "key_id -> {email, added_at, revoked_at}",
        "key_id_derivation": "sha256(...)[:16]",
        "operators": operators,
    }


def _write_registry(tmp_path: Path, operators: Dict[str, Any]) -> Path:
    p = tmp_path / "opsctl_operators.json"
    p.write_text(json.dumps(_registry(operators)), encoding="utf-8")
    return p


def _args(email: str, operators_json: Path):
    import argparse
    ns = argparse.Namespace(
        operator_email=email,
        operators_json=str(operators_json),
    )
    return ns


# ---------------------------------------------------------------------------
# Happy path: key_id matches registry
# ---------------------------------------------------------------------------

def test_verify_key_id_ok(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    key_bytes = bytes(range(32))
    email = "operator@example.com"
    kid = derive_operator_key_id(email, key_bytes)

    key_path = _make_key_file(tmp_path, key_bytes)
    registry_path = _write_registry(tmp_path, {
        kid: {"email": email, "added_at": "2026-01-01T00:00:00Z", "revoked_at": None},
    })

    cfg = Config(opsctl_key_path=str(key_path))
    ns = _args(email, registry_path)

    # Patch cfg construction inside run()
    import unittest.mock as mock
    with mock.patch("ai.common.config.Config", return_value=cfg):
        code = verify_key_id.run(ns)

    assert code == int(ExitCode.OK)
    out = capsys.readouterr().out
    assert kid in out
    assert "OK" in out


# ---------------------------------------------------------------------------
# Drift: key_id not in registry
# ---------------------------------------------------------------------------

def test_verify_key_id_drift_not_in_registry(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    key_bytes = b"\x00" * 32
    email = "operator@example.com"

    key_path = _make_key_file(tmp_path, key_bytes)
    # registry is empty — key_id will not be found
    registry_path = _write_registry(tmp_path, {})

    cfg = Config(opsctl_key_path=str(key_path))
    ns = _args(email, registry_path)

    import unittest.mock as mock
    with mock.patch("ai.common.config.Config", return_value=cfg):
        code = verify_key_id.run(ns)

    assert code == int(ExitCode.KEY_ID_DRIFT)
    err_out = capsys.readouterr().err
    assert "key_id_drift" in err_out
    assert "Runbook" in err_out


# ---------------------------------------------------------------------------
# Drift: tampered registry (key_id present but wrong email)
# ---------------------------------------------------------------------------

def test_verify_key_id_drift_wrong_email_in_registry(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    key_bytes = b"\xff" * 32
    email = "alice@example.com"
    kid = derive_operator_key_id(email, key_bytes)

    key_path = _make_key_file(tmp_path, key_bytes)
    # Registry maps same key_id to a different email (tampered)
    registry_path = _write_registry(tmp_path, {
        kid: {"email": "eve@example.com", "added_at": "2026-01-01T00:00:00Z", "revoked_at": None},
    })

    cfg = Config(opsctl_key_path=str(key_path))
    ns = _args(email, registry_path)

    import unittest.mock as mock
    with mock.patch("ai.common.config.Config", return_value=cfg):
        code = verify_key_id.run(ns)

    assert code == int(ExitCode.KEY_ID_DRIFT)
    err_out = capsys.readouterr().err
    assert "key_id_drift" in err_out


# ---------------------------------------------------------------------------
# Drift: key is revoked
# ---------------------------------------------------------------------------

def test_verify_key_id_drift_revoked(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    key_bytes = b"\xab" * 32
    email = "revoked@example.com"
    kid = derive_operator_key_id(email, key_bytes)

    key_path = _make_key_file(tmp_path, key_bytes)
    registry_path = _write_registry(tmp_path, {
        kid: {
            "email": email,
            "added_at": "2026-01-01T00:00:00Z",
            "revoked_at": "2026-03-01T00:00:00Z",
        },
    })

    cfg = Config(opsctl_key_path=str(key_path))
    ns = _args(email, registry_path)

    import unittest.mock as mock
    with mock.patch("ai.common.config.Config", return_value=cfg):
        code = verify_key_id.run(ns)

    assert code == int(ExitCode.KEY_ID_DRIFT)


# ---------------------------------------------------------------------------
# Missing key file
# ---------------------------------------------------------------------------

def test_verify_key_id_missing_key_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    email = "nobody@example.com"
    registry_path = _write_registry(tmp_path, {})

    cfg = Config(opsctl_key_path=str(tmp_path / "nonexistent_key"))
    ns = _args(email, registry_path)

    import unittest.mock as mock
    with mock.patch("ai.common.config.Config", return_value=cfg):
        code = verify_key_id.run(ns)

    assert code == int(ExitCode.GENERIC_FAILURE)
    err_out = capsys.readouterr().err
    assert "make ops.bootstrap-key" in err_out


# ---------------------------------------------------------------------------
# Subcommand CLI integration: NAME and add_parser
# ---------------------------------------------------------------------------

def test_verify_key_id_name() -> None:
    assert verify_key_id.NAME == "verify-key-id"


def test_verify_key_id_add_parser_registers_func() -> None:
    import argparse
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="cmd")
    verify_key_id.add_parser(subparsers)
    ns = parser.parse_args(["verify-key-id", "--operator-email", "x@y.com"])
    assert ns.func is verify_key_id.run


# ---------------------------------------------------------------------------
# Exit code sanity
# ---------------------------------------------------------------------------

def test_key_id_drift_exit_code_value() -> None:
    assert int(ExitCode.KEY_ID_DRIFT) == 13


def test_make_ops_verify_key_id_drift_on_tampered_operators_json(tmp_path: Path) -> None:
    """Phase 8.16.14 proof: make target exits key_id_drift on tampered registry."""
    key_bytes = bytes(range(32))
    email = "operator@example.com"
    kid = derive_operator_key_id(email, key_bytes)

    key_path = _make_key_file(tmp_path, key_bytes)
    # Tamper by mapping the computed key_id to a different operator email.
    registry_path = _write_registry(tmp_path, {
        kid: {
            "email": "attacker@example.com",
            "added_at": "2026-01-01T00:00:00Z",
            "revoked_at": None,
        },
    })

    env = os.environ.copy()
    env["OPERATOR"] = email
    env["OPERATORS_JSON"] = str(registry_path)
    env["NEGELIR_OPSCTL_KEY_PATH"] = str(key_path)

    proc = subprocess.run(
        ["make", "ops.verify-key-id"],
        cwd=str(REPO_ROOT),
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert proc.returncode != 0
    assert "key_id_drift" in proc.stderr
    assert f"Error {int(ExitCode.KEY_ID_DRIFT)}" in proc.stderr
