"""Phase 8.16.7 proof tests — layered DLQ replay policy."""

from __future__ import annotations

from pathlib import Path

from common.config import cfg
from swarm.agents.maint.dlq import MaintDlqSupervisor
from swarm.agents.maint.dlq.replay_policy import (
    DENY_PREFIXES,
    DENY_SUFFIXES,
    build_policy_loaded_payload,
    is_replayable,
)
from xops.maint.verify_dlq_replay_policy import verify_policy


def _docs_stub(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "# Security Exceptions",
                "",
                "## DLQ Replay Policy Overrides",
                "",
                "| topic | reason | responsible_agent | phase12_stub | sign_off |",
                "| --- | --- | --- | --- | --- |",
            ]
        ),
        encoding="utf-8",
    )


def test_auth_login_dlq_is_denied_by_prefix() -> None:
    assert "auth." in DENY_PREFIXES
    assert is_replayable("auth.login.v1.dlq") is False


def test_verify_dlq_replay_policy_fails_without_docs_row(
    monkeypatch, tmp_path: Path
) -> None:
    docs_path = tmp_path / "security_exceptions.md"
    _docs_stub(docs_path)
    monkeypatch.setattr(
        cfg,
        "_maint_dlq_replay_allow_overrides_raw",
        "auth.login.v1.dlq",
        raising=False,
    )
    result = verify_policy(docs_path)
    assert result.ok is False
    assert result.undocumented == ("auth.login.v1.dlq",)


def test_double_dlq_suffix_is_always_denied_even_with_override() -> None:
    assert ".dlq.dlq" in DENY_SUFFIXES
    assert (
        is_replayable(
            "auth.login.v1.dlq.dlq",
            allow_overrides=("auth.login.v1.dlq.dlq",),
        )
        is False
    )


def test_boot_policy_event_reports_active_policy(monkeypatch) -> None:
    monkeypatch.setattr(
        cfg,
        "_maint_dlq_replay_allow_overrides_raw",
        "auth.login.v1.dlq",
        raising=False,
    )
    payload = build_policy_loaded_payload(
        produced_at="2025-01-01T00:00:00Z",
        allow_overrides=("auth.login.v1.dlq",),
    )
    assert payload["kind"] == "dlq_replay_policy_loaded"
    assert payload["deny_prefixes"] == list(DENY_PREFIXES)
    assert payload["deny_suffixes"] == list(DENY_SUFFIXES)
    assert payload["allow_overrides"] == ["auth.login.v1.dlq"]

    supervisor = MaintDlqSupervisor()
    boot_messages = supervisor.boot_replay_policy_messages()
    assert any(
        message.payload.get("kind") == "dlq_replay_policy_loaded"
        for message in boot_messages
    )
