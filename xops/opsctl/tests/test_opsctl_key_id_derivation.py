from __future__ import annotations

import ast
import base64
import hashlib
from pathlib import Path

import pytest

from ai.common.config import Config
from xops.maint.key_id import DOMAIN_SEPARATOR, derive
from xops.opsctl._op_signature import bootstrap_key, key_id_from_bytes

REPO_ROOT = Path(__file__).resolve().parents[3]
CANONICAL_DERIVE_FILE = REPO_ROOT / "xops" / "maint" / "key_id.py"
KEY_ID_CONSUMERS = (
    REPO_ROOT / "xops" / "opsctl" / "_op_signature.py",
    REPO_ROOT / "ai" / "swarm" / "agents" / "maint" / "_op_signature.py",
)


def test_derive_operator_key_id_matches_formula() -> None:
    raw = bytes(range(32))
    email = "operator@example.com"
    key_b64 = base64.b64encode(raw).decode("ascii")
    expected = hashlib.sha256(
        f"{DOMAIN_SEPARATOR}|{email}|{key_b64}".encode("utf-8")
    ).hexdigest()[:16]
    assert derive(email, raw) == expected


def test_derive_operator_key_id_matches_documented_test_vector() -> None:
    """Phase 8.16.14 proof: fixed (email, key) pair yields stable key_id."""
    raw = bytes(range(32))
    email = "operator@example.com"
    assert derive(email, raw) == "bad138e1fe92d1dd"


def test_derive_operator_key_id_changes_with_email() -> None:
    raw = b"k" * 32
    assert derive("alice@example.com", raw) != derive(
        "bob@example.com", raw
    )


def test_key_id_from_bytes_prefers_canonical_when_email_provided() -> None:
    raw = b"x" * 32
    email = "operator@example.com"
    assert key_id_from_bytes(raw, operator_email=email) == derive(email, raw)


def test_key_id_from_bytes_rejects_missing_operator_email() -> None:
    with pytest.raises(ValueError):
        key_id_from_bytes(b"x" * 32, operator_email="")


def test_bootstrap_key_writes_0600_and_prints_operators_json_line(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    key_path = tmp_path / "opsctl_key"
    cfg = Config(opsctl_key_path=str(key_path))

    kid = bootstrap_key(cfg, operator_email="Operator@Example.COM")
    out = capsys.readouterr().out

    assert key_path.exists()
    assert key_path.stat().st_mode & 0o777 == 0o600
    assert f'"{kid}": {{"email": "operator@example.com", "added_at": "' in out
    assert '"revoked_at": null}' in out
    assert 'revocation_reason' not in out


def test_bootstrap_key_rejects_existing_insecure_mode(tmp_path: Path) -> None:
    key_path = tmp_path / "opsctl_key"
    key_path.write_bytes(b"x" * 32)
    key_path.chmod(0o644)
    cfg = Config(opsctl_key_path=str(key_path))

    with pytest.raises(PermissionError):
        bootstrap_key(cfg, operator_email="operator@example.com")


def test_key_id_derivation_boundary_single_source_ast_scan() -> None:
    """Phase 8 §8.16.14: key_id derivation must stay single-sourced."""
    derive_tree = ast.parse(CANONICAL_DERIVE_FILE.read_text(encoding="utf-8"))
    derive_funcs = [
        node for node in derive_tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "derive"
    ]
    assert len(derive_funcs) == 1, "xops/maint/key_id.py must define exactly one derive()"

    wrapper_offenders: list[str] = []
    for path in KEY_ID_CONSUMERS:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        key_id_wrappers = [
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "key_id_from_bytes"
        ]
        if len(key_id_wrappers) != 1:
            wrapper_offenders.append(
                f"{path.relative_to(REPO_ROOT)}: expected exactly one key_id_from_bytes wrapper"
            )
            continue

        body = [
            stmt
            for stmt in key_id_wrappers[0].body
            if not (
                isinstance(stmt, ast.Expr)
                and isinstance(stmt.value, ast.Constant)
                and isinstance(stmt.value.value, str)
            )
        ]
        if len(body) != 1 or not isinstance(body[0], ast.Return):
            wrapper_offenders.append(
                f"{path.relative_to(REPO_ROOT)}: wrapper must be a single return"
            )
            continue

        call = body[0].value
        if not isinstance(call, ast.Call):
            wrapper_offenders.append(
                f"{path.relative_to(REPO_ROOT)}: wrapper must return a function call"
            )
            continue

        if not isinstance(call.func, ast.Name) or call.func.id != "derive":
            wrapper_offenders.append(
                f"{path.relative_to(REPO_ROOT)}: wrapper must call derive(...)"
            )

    assert wrapper_offenders == [], (
        "key_id derivation wrappers drifted from single-source derive(): "
        f"{wrapper_offenders}"
    )
