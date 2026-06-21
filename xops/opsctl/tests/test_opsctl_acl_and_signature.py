"""Phase 8 §8.14.4 proof tests: Redis ACL gate + signed-envelope verifier + authz.

Four scenarios:

  (a) Wrong Redis user → FAIL_SAFE_WRONG_REDIS_USER.
  (b) Tampered envelope → signature_invalid.
  (c) Unauthorized key for destructive kind → op_not_authorized.
  (d) infra/redis/acl.conf restricts negelir_opsctl correctly.
"""
from __future__ import annotations

import hashlib
import json
import secrets
from pathlib import Path

import pytest

from common.config import Config
from swarm.agents.maint._op_signature import (
    check_authz,
    key_id_from_bytes,
    load_authz,
    verify_envelope_signature,
)
from swarm.sdk.bus import InMemoryBus
from xops.opsctl._exit_codes import ExitCode
from xops.opsctl._op_signature import inject_signature
from xops.opsctl._redis_acl import assert_opsctl_redis_user

# --------------------------------------------------------------------------
# (a) Wrong Redis ACL user → FAIL_SAFE_WRONG_REDIS_USER
# --------------------------------------------------------------------------

def test_wrong_redis_user_triggers_exit_code() -> None:
    """InMemoryBus with a non-opsctl username must produce FAIL_SAFE_WRONG_REDIS_USER."""
    bus = InMemoryBus(mock_redis_username="some_other_user")
    cfg = Config(
        opsctl_redis_expected_user="negelir_opsctl",
        opsctl_require_signature=False,
    )
    result = assert_opsctl_redis_user(bus, cfg)
    assert result == int(ExitCode.FAIL_SAFE_WRONG_REDIS_USER), (
        f"expected {ExitCode.FAIL_SAFE_WRONG_REDIS_USER!r}, got {result!r}"
    )


def test_correct_redis_user_passes() -> None:
    """InMemoryBus with the correct username returns None (gate passed)."""
    bus = InMemoryBus(mock_redis_username="negelir_opsctl")
    cfg = Config(
        opsctl_redis_expected_user="negelir_opsctl",
        opsctl_require_signature=False,
    )
    result = assert_opsctl_redis_user(bus, cfg)
    assert result is None


# --------------------------------------------------------------------------
# (b) Tampered payload → op_signature_invalid
# --------------------------------------------------------------------------

def test_tampered_payload_fails_verification(tmp_path: Path) -> None:
    """After injecting a valid signature, tampering the target field must fail verify."""
    # Write raw key to a temp file.
    key_file = tmp_path / "opsctl_key"
    raw_key = secrets.token_bytes(32)
    key_file.write_bytes(raw_key)
    key_file.chmod(0o600)

    # Derive the key_id the inject/verify functions would use.
    operator_email = "test@example.com"
    kid = key_id_from_bytes(raw_key, operator_email=operator_email)

    # Register the key_id in a temp operators.json so verify can look it up.
    operators_file = tmp_path / "opsctl_operators.json"
    operators_file.write_text(
        json.dumps({
            "operators": {
                kid: {
                    "email": operator_email,
                    "added_at": "2025-01-01T00:00:00Z",
                    "revoked_at": None,
                }
            }
        }, ensure_ascii=False)
    )

    cfg = Config(
        opsctl_require_signature=True,
        opsctl_key_path=str(key_file),
        opsctl_operators_file=str(operators_file),
        opsctl_key_max_age_days=9999,
    )

    payload: dict = {
        "request_id": "req-test-1",
        "kind": "liveness",
        "target": "all",
        "produced_at": "2025-01-01T00:00:00Z",
        "client_id": operator_email,
    }
    inject_signature(payload, cfg)
    assert "op_signature" in payload, "inject_signature must add op_signature"

    # Tamper one field after signing.
    payload["target"] = "TAMPERED"

    ok, reason = verify_envelope_signature(payload, cfg)
    assert not ok
    assert reason == "op_signature_invalid", f"got {reason!r}"


# --------------------------------------------------------------------------
# (c) Unauthorized key for destructive kind → op_not_authorized
# --------------------------------------------------------------------------

def test_authz_blocks_destructive_kind_without_explicit_key_id(tmp_path: Path) -> None:
    """restore kind with no key_ids authorized must return (False, op_not_authorized)."""
    authz_file = tmp_path / "opsctl_authz.yaml"
    authz_file.write_text(
        "defaults: \"*\"\n"
        "overrides:\n"
        "  restore: []\n"
    )
    cfg = Config(
        opsctl_authz_file=str(authz_file),
        opsctl_require_signature=True,
    )
    key_id = "abcd1234abcd1234"
    ok, reason = check_authz(key_id, "restore", cfg)
    assert not ok
    assert reason == "op_not_authorized", f"got {reason!r}"


def test_authz_allows_non_destructive_kind(tmp_path: Path) -> None:
    """liveness kind (uses defaults=*) must return (True, \"\")."""
    authz_file = tmp_path / "opsctl_authz.yaml"
    authz_file.write_text(
        "defaults: \"*\"\n"
        "overrides:\n"
        "  restore: []\n"
    )
    cfg = Config(
        opsctl_authz_file=str(authz_file),
        opsctl_require_signature=True,
    )
    key_id = "abcd1234abcd1234"
    ok, reason = check_authz(key_id, "liveness", cfg)
    assert ok, f"expected ok, got reason={reason!r}"


# --------------------------------------------------------------------------
# (d) infra/redis/acl.conf is correctly restricted
# --------------------------------------------------------------------------

def test_redis_acl_conf_restricts_negelir_opsctl() -> None:
    """infra/redis/acl.conf must define negelir_opsctl without +set or +evalsha."""
    # test file is at xops/opsctl/tests/; parents[3] is repo root.
    repo_root = Path(__file__).resolve().parents[3]
    acl_path = repo_root / "infra" / "redis" / "acl.conf"
    assert acl_path.exists(), f"Missing {acl_path}"
    acl_text = acl_path.read_text()

    # Find the negelir_opsctl user line.
    opsctl_lines = [l for l in acl_text.splitlines()
                   if "negelir_opsctl" in l and not l.startswith("#")]
    assert opsctl_lines, "negelir_opsctl not defined in acl.conf"
    opsctl_line = opsctl_lines[0]

    # Must not grant full write permissions.
    forbidden = ["+set", "+del", "+evalsha", "+@all", "+@write"]
    for tok in forbidden:
        assert tok not in opsctl_line, (
            f"negelir_opsctl ACL line must not contain {tok!r}; got: {opsctl_line!r}"
        )

    # Must have stream-level capabilities.
    required = ["+xadd", "+xread"]
    for tok in required:
        assert tok in opsctl_line, (
            f"negelir_opsctl ACL line missing {tok!r}; got: {opsctl_line!r}"
        )
