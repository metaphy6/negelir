"""Phase 8 §8.14.4 proof tests — consumer-side signature/authz gate.

Tests (b) and (c) from the §8.14.4 DoD, exercised at the agent
``handle()`` dispatch level (not just the bare verify functions):

* **(b-consumer)** Tampered envelope → every maint agent's ``handle()``
  returns an ack with ``accepted=False, reason="op_signature_invalid"``
  **and** emits ``sec.alert.v1{kind=opsctl_signature_invalid,
  severity=critical}``.

* **(c-consumer)** Valid signature from a key not authorized for the
  requested kind → every maint agent's ``handle()`` returns
  ``accepted=False, reason="op_not_authorized"`` and emits
  ``sec.alert.v1{kind=opsctl_unauthorized, severity=critical}``.

All five consumers are covered: backup, dlq, scaler, sec, schema.
"""
from __future__ import annotations

import json
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import pytest

from common.config import Config, cfg as _global_cfg
from swarm.agents.maint._op_signature import key_id_from_bytes
from swarm.agents.maint.backup import (
    InMemoryPrunerStorage,
    InMemoryQuarantineStore,
    MaintBackupAgent,
    NoopDumpExecutor,
    NoopPgSecretAgeChecker,
    NoopVerifier,
    StaticDiskGauge,
)
from swarm.agents.maint.dlq import MaintDlqSupervisor
from swarm.agents.maint.scaler import MaintScaler, NoopController
from swarm.agents.maint.schema import MaintSchemaSentinel
from swarm.agents.maint.sec import InMemoryDecimator, InMemoryPatternStore, MaintSecAgent
from swarm.sdk.leader import SingleProcessLeader
from swarm.sdk.types import Envelope, Message
from swarm.agents.topics import MAINT_ACK, MAINT_EVENT, SEC_ALERT
from xops.opsctl._op_signature import inject_signature


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _write_key_and_ops(
    tmp_path: Path,
) -> tuple[Path, Path, str, bytes]:
    """Write a fresh 32-byte key and a matching operators.json.

    Returns ``(key_file, ops_file, kid, raw_key)``.
    """
    raw_key = secrets.token_bytes(32)
    key_file = tmp_path / "opsctl_key"
    key_file.write_bytes(raw_key)
    key_file.chmod(0o600)

    kid = key_id_from_bytes(raw_key)
    ops_file = tmp_path / "opsctl_operators.json"
    ops_file.write_text(
        json.dumps({
            "operators": {
                kid: {
                    "email": "operator@test.example",
                    "added_at": _utc_iso(),  # use now() so age check never fires
                    "revoked_at": None,
                }
            }
        }, ensure_ascii=False)
    )
    return key_file, ops_file, kid, raw_key


def _wrap(payload: dict, topic: str = MAINT_EVENT) -> Message:
    env = Envelope(
        message_id=secrets.token_hex(8),
        trace_id=secrets.token_hex(8),
        topic=topic,
        producer="ops_console",
        created_at=_utc_iso(),
        schema_version=1,
        attempt=1,
    )
    return Message(envelope=env, payload=payload)


def _make_backup() -> MaintBackupAgent:
    leader = SingleProcessLeader(name="maint.backup.v1")
    return MaintBackupAgent(
        leader=leader,
        quarantine=InMemoryQuarantineStore(),
        pruner=InMemoryPrunerStorage(),
        dump=NoopDumpExecutor(),
        verifier=NoopVerifier(),
        disk=StaticDiskGauge(free_bytes=10 * 1024 * 1024 * 1024),
        pg_secret_age_checker=NoopPgSecretAgeChecker(),
        enforce_permissions=False,
    )


def _make_dlq() -> MaintDlqSupervisor:
    return MaintDlqSupervisor(
        leader=SingleProcessLeader(name="maint.dlq.v1"),
    )


def _make_scaler() -> MaintScaler:
    return MaintScaler(
        controller=NoopController(),
        leader=SingleProcessLeader(name="maint.scaler.v1"),
    )


def _make_sec() -> MaintSecAgent:
    return MaintSecAgent(
        pattern_store=InMemoryPatternStore(),
        decimator=InMemoryDecimator(),
        leader=SingleProcessLeader(name="maint.sec.v1"),
    )


def _make_schema() -> MaintSchemaSentinel:
    return MaintSchemaSentinel(
        leader=SingleProcessLeader(name="maint.schema.v1"),
    )


_AGENT_FACTORIES: list[tuple[str, Callable]] = [
    ("backup", _make_backup),
    ("dlq", _make_dlq),
    ("scaler", _make_scaler),
    ("sec", _make_sec),
    ("schema", _make_schema),
]


def _assert_gate_failure(
    results: list,
    expected_reason: str,
    expected_alert_kind: str,
    agent_label: str,
) -> None:
    """Assert the two-message gate failure contract: ack + sec.alert.v1."""
    assert len(results) == 2, (
        f"{agent_label}: expected exactly 2 messages (ack + alert), "
        f"got {len(results)}: {[r.payload for r in results]}"
    )
    ack, alert = results
    # ── ack checks ────────────────────────────────────────────────
    assert ack.envelope.topic == MAINT_ACK, (
        f"{agent_label}: first message must be on {MAINT_ACK!r}, "
        f"got {ack.envelope.topic!r}"
    )
    assert ack.payload.get("accepted") is False, (
        f"{agent_label}: ack.accepted must be False, got {ack.payload!r}"
    )
    assert ack.payload.get("reason") == expected_reason, (
        f"{agent_label}: ack.reason must be {expected_reason!r}, "
        f"got {ack.payload.get('reason')!r}"
    )
    # ── alert checks ──────────────────────────────────────────────
    assert alert.envelope.topic == SEC_ALERT, (
        f"{agent_label}: second message must be on {SEC_ALERT!r}, "
        f"got {alert.envelope.topic!r}"
    )
    assert alert.payload.get("kind") == expected_alert_kind, (
        f"{agent_label}: alert.kind must be {expected_alert_kind!r}, "
        f"got {alert.payload.get('kind')!r}"
    )
    assert alert.payload.get("severity") == "critical", (
        f"{agent_label}: alert.severity must be 'critical', "
        f"got {alert.payload.get('severity')!r}"
    )


# ─── (b-consumer) Tampered envelope ──────────────────────────────────────────


@pytest.mark.parametrize("label,factory", _AGENT_FACTORIES)
def test_consumer_tampered_sig_yields_ack_and_critical_alert(
    label: str,
    factory: Callable,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tampered payload after signing → ack op_signature_invalid + critical alert
    for every maint agent's handle() dispatch.
    """
    key_file, ops_file, kid, raw_key = _write_key_and_ops(tmp_path)

    # Patch global cfg so gate_op_envelope uses the temp key material.
    monkeypatch.setattr(_global_cfg, "opsctl_require_signature", True)
    monkeypatch.setattr(_global_cfg, "opsctl_key_path", str(key_file))
    monkeypatch.setattr(_global_cfg, "opsctl_operators_file", str(ops_file))

    # Build a signing cfg (same key material).
    sign_cfg = Config(
        opsctl_require_signature=True,
        opsctl_key_path=str(key_file),
        opsctl_operators_file=str(ops_file),
    )

    payload: dict = {
        "request_id": f"req-tamper-{label}",
        "kind": "maint_pause",
        "target": "all",
        "produced_at": _utc_iso(),
    }
    inject_signature(payload, sign_cfg)
    assert "op_signature" in payload, "inject_signature must add op_signature"

    # Tamper a field after signing.
    payload["target"] = "TAMPERED"

    msg = _wrap(payload)
    agent = factory()
    results = list(agent.handle(msg))

    _assert_gate_failure(
        results,
        expected_reason="op_signature_invalid",
        expected_alert_kind="opsctl_signature_invalid",
        agent_label=label,
    )


# ─── (c-consumer) Unauthorized key for kind ──────────────────────────────────


@pytest.mark.parametrize("label,factory", _AGENT_FACTORIES)
def test_consumer_unauthorized_key_yields_ack_and_critical_alert(
    label: str,
    factory: Callable,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Valid signature but key not in authz allow-list for the kind →
    ack op_not_authorized + critical alert for every maint agent.
    """
    key_file, ops_file, kid, raw_key = _write_key_and_ops(tmp_path)

    # Authz: maint_pause is restricted to an explicit (empty) list,
    # so our test key_id is NOT authorized for it.
    authz_file = tmp_path / "opsctl_authz.yaml"
    authz_file.write_text(
        "defaults: \"*\"\n"
        "overrides:\n"
        f"  maint_pause: []\n"  # nobody allowed
    )

    monkeypatch.setattr(_global_cfg, "opsctl_require_signature", True)
    monkeypatch.setattr(_global_cfg, "opsctl_key_path", str(key_file))
    monkeypatch.setattr(_global_cfg, "opsctl_operators_file", str(ops_file))
    monkeypatch.setattr(_global_cfg, "opsctl_authz_file", str(authz_file))

    sign_cfg = Config(
        opsctl_require_signature=True,
        opsctl_key_path=str(key_file),
        opsctl_operators_file=str(ops_file),
        opsctl_authz_file=str(authz_file),
    )

    payload: dict = {
        "request_id": f"req-unauth-{label}",
        "kind": "maint_pause",
        "target": "all",
        "produced_at": _utc_iso(),
    }
    inject_signature(payload, sign_cfg)
    assert "op_signature" in payload

    msg = _wrap(payload)
    agent = factory()
    results = list(agent.handle(msg))

    _assert_gate_failure(
        results,
        expected_reason="op_not_authorized",
        expected_alert_kind="opsctl_unauthorized",
        agent_label=label,
    )


# ─── Happy-path: signature disabled → gate is bypassed ───────────────────────


def test_consumer_signature_not_required_passes_all_agents(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When cfg.opsctl_require_signature=False the gate is fully bypassed;
    the envelope (without a signature field) must NOT yield an
    op_signature_invalid ack for any of the five agents.
    """
    from common.config import cfg as _global_cfg  # local re-import to match scope

    monkeypatch.setattr(_global_cfg, "opsctl_require_signature", False)

    payload: dict = {
        "request_id": "req-nosig-happy",
        "kind": "maint_status",
        "target": "all",
        "produced_at": _utc_iso(),
        # no op_signature field at all
    }
    msg = _wrap(payload)

    for label, factory in _AGENT_FACTORIES:
        agent = factory()
        results = list(agent.handle(msg))
        # Gate must NOT fire (no ack with reason=op_signature_invalid)
        for r in results:
            assert not (
                r.payload.get("reason") == "op_signature_invalid"
            ), (
                f"{label}: gate fired (op_signature_invalid) "
                "even though opsctl_require_signature=False"
            )


# ─── Adversarial: partially-signed envelope (op_key_id present, sig absent) ──


@pytest.mark.parametrize("label,factory", _AGENT_FACTORIES)
def test_consumer_partial_sig_fields_rejected(
    label: str,
    factory: Callable,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Envelope with op_key_id but no op_signature → gate rejects as
    op_signature_invalid (not silently accepted as a producer signal).
    Validates that the gate triggers on partial opsctl field sets.
    """
    key_file, ops_file, kid, raw_key = _write_key_and_ops(tmp_path)

    monkeypatch.setattr(_global_cfg, "opsctl_require_signature", True)
    monkeypatch.setattr(_global_cfg, "opsctl_key_path", str(key_file))
    monkeypatch.setattr(_global_cfg, "opsctl_operators_file", str(ops_file))

    payload: dict = {
        "request_id": f"req-partial-sig-{label}",
        "kind": "maint_pause",
        "target": "all",
        "produced_at": _utc_iso(),
        "op_key_id": kid,
        # intentionally NO op_signature — partial opsctl fields
    }

    msg = _wrap(payload)
    agent = factory()
    results = list(agent.handle(msg))

    _assert_gate_failure(
        results,
        expected_reason="op_signature_missing",
        expected_alert_kind="opsctl_signature_invalid",
        agent_label=label,
    )
