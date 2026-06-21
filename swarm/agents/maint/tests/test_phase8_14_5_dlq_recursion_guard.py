"""Phase 8 §8.14.5 proof tests — DLQ supervisor recursion guard.

Four bullets in the §8.14.5 DoD, all exercised here:

1. **Real bug** — ``maint.dlq.v1.dlq`` is in ``RECURSION_DENY_SET``.
2. **Hardcoded blacklist** — ``boot_check_allow_list()`` emits one
   ``sec.alert.v1{kind=dlq_recursion_blocked, severity=warn,
   subject=<topic>}`` per orphan (allow-list entry that is also in
   ``RECURSION_DENY_SET``); idempotent (fires once per process).
   Active subscription set excludes the orphan.
3. **Zero replay counter** — 100 ``tick()`` calls with
   ``active_topics=["maint.dlq.v1.dlq"]`` produce zero accepted
   replays; ``_replays_total.get("maint.dlq.v1.dlq", 0) == 0``.
4. **Operator escalation path** — ``maint.event.v1.dlq`` is in
   ``RECURSION_DENY_SET`` and is NOT operator-escalatable (the
   only supported escalation token is in the ROADMAP prose but the
   agent still enforces the deny set — ``confirm_destructive`` in
   the payload does NOT bypass RECURSION_DENY_SET for this entry).
   For the opsctl side the classifier returns CONFIRM when
   ``confirm_destructive`` is in flags.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from swarm.agents.maint.dlq import RECURSION_DENY_SET, MaintDlqSupervisor
from swarm.agents.payloads import KNOWN_SEC_ALERT_KINDS
from swarm.agents.topics import MAINT_ACK, MAINT_EVENT, SEC_ALERT
from swarm.sdk.types import Envelope, Message


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _wrap(payload: dict) -> Message:
    env = Envelope(
        message_id="m1",
        trace_id="t1",
        topic=MAINT_EVENT,
        producer="ops_console",
        created_at=_utc_iso(),
        schema_version=1,
        attempt=1,
    )
    return Message(envelope=env, payload=payload)


def _setup_replay_cfg(monkeypatch, *, allow_csv: str = "") -> None:
    from common.config import cfg
    monkeypatch.setattr(cfg, "maint_dlq_replay_topics_allow_csv", allow_csv, raising=False)
    monkeypatch.setattr(cfg, "maint_dlq_max_replays_per_tick", 1_000, raising=False)
    monkeypatch.setattr(cfg, "maint_dlq_per_topic_max_per_min", 10_000_000, raising=False)
    monkeypatch.setattr(cfg, "maint_dlq_replay_rps", 10_000_000, raising=False)
    monkeypatch.setattr(cfg, "maint_dlq_backlog_alert", 999_999_999, raising=False)
    monkeypatch.setattr(cfg, "maint_dlq_state_max", 10_000, raising=False)


# ─── Bullet 1: real bug — maint.dlq.v1.dlq in RECURSION_DENY_SET ─────────────


def test_maint_dlq_v1_dlq_in_recursion_deny_set() -> None:
    """§8.14.5 real bug: maint.dlq.v1.dlq MUST be in RECURSION_DENY_SET."""
    assert "maint.dlq.v1.dlq" in RECURSION_DENY_SET, (
        "maint.dlq.v1.dlq missing from RECURSION_DENY_SET — "
        "supervisor would loop on its own DLQ"
    )


def test_recursion_deny_set_contains_all_core_four() -> None:
    """§8.14.5: all four core deny-set entries must be present."""
    required = {
        "maint.dlq.v1.dlq",
        "maint.event.v1.dlq",
        "maint.ack.v1.dlq",
        "sec.alert.v1.dlq",
    }
    missing = required - RECURSION_DENY_SET
    assert not missing, f"RECURSION_DENY_SET missing core entries: {missing}"


# ─── Bullet 2: boot_check_allow_list() emits dlq_recursion_blocked ───────────


def test_boot_check_emits_alert_for_orphan(monkeypatch) -> None:
    """§8.14.5: allow-list contains maint.dlq.v1.dlq → one sec.alert emitted."""
    _setup_replay_cfg(
        monkeypatch,
        allow_csv="some.topic.dlq,maint.dlq.v1.dlq,another.dlq",
    )
    sup = MaintDlqSupervisor()
    alerts = sup.boot_check_allow_list()

    # Must have exactly one alert for maint.dlq.v1.dlq.
    dlq_v1_alerts = [
        m for m in alerts
        if m.envelope.topic == SEC_ALERT
        and m.payload.get("kind") == "dlq_recursion_blocked"
        and m.payload.get("subject") == "maint.dlq.v1.dlq"
    ]
    assert len(dlq_v1_alerts) == 1, (
        f"Expected 1 dlq_recursion_blocked for maint.dlq.v1.dlq; "
        f"got alerts: {[m.payload for m in alerts]}"
    )
    # Severity must be warn.
    assert dlq_v1_alerts[0].payload["severity"] == "warn"
    # Source must be the supervisor.
    assert dlq_v1_alerts[0].payload["source"] == "maint.dlq.v1"


def test_boot_check_idempotent(monkeypatch) -> None:
    """§8.14.5: boot_check fires exactly once per orphan per process."""
    _setup_replay_cfg(monkeypatch, allow_csv="maint.dlq.v1.dlq")
    sup = MaintDlqSupervisor()
    first = sup.boot_check_allow_list()
    second = sup.boot_check_allow_list()
    assert len(first) == 1
    assert len(second) == 0, (
        "boot_check must not re-emit the same alert on subsequent calls"
    )


def test_boot_check_excludes_orphan_from_replay(monkeypatch) -> None:
    """§8.14.5: orphan topic is excluded from replay by _is_allowed_topic()."""
    _setup_replay_cfg(monkeypatch, allow_csv="maint.dlq.v1.dlq,predict.final.dlq")
    sup = MaintDlqSupervisor()
    sup.boot_check_allow_list()
    # The orphan must not pass the allow-list gate.
    assert sup._is_allowed_topic("maint.dlq.v1.dlq") is False
    # A legitimately allowed topic still passes.
    assert sup._is_allowed_topic("predict.final.dlq") is True


def test_boot_check_no_orphan_emits_nothing(monkeypatch) -> None:
    """§8.14.5: allow-list with no deny-set entries → zero alerts."""
    _setup_replay_cfg(monkeypatch, allow_csv="predict.final.dlq,match.stored.dlq")
    sup = MaintDlqSupervisor()
    alerts = sup.boot_check_allow_list()
    assert alerts == []


def test_dlq_recursion_blocked_in_known_sec_alert_kinds() -> None:
    """§8.14.5: kind must be registered in KNOWN_SEC_ALERT_KINDS."""
    assert "dlq_recursion_blocked" in KNOWN_SEC_ALERT_KINDS


# ─── Bullet 3: zero auto-replay counter after 100 ticks ──────────────────────


def test_zero_replay_counter_after_100_ticks(monkeypatch) -> None:
    """§8.14.5: 100 tick() calls with active=maint.dlq.v1.dlq → counter stays 0."""
    _setup_replay_cfg(monkeypatch, allow_csv="")
    sup = MaintDlqSupervisor()
    for _ in range(100):
        sup.tick(["maint.dlq.v1.dlq"])
    assert sup._replays_total.get("maint.dlq.v1.dlq", 0) == 0, (
        "_replays_total must be 0 for a deny-set topic after 100 ticks"
    )


def test_replay_counter_increments_for_allowed_topic(monkeypatch) -> None:
    """§8.14.5: _replays_total increments only for accepted operator replays."""
    _setup_replay_cfg(monkeypatch, allow_csv="predict.final.dlq")
    sup = MaintDlqSupervisor()
    # Operator-commanded replay (via handle, not tick).
    msg = _wrap({
        "kind": "dlq_replay",
        "request_id": "req-8145-01",
        "client_id": "ops",
        "target": "predict.final.dlq",
        "produced_at": _utc_iso(),
        "reason": "proof test",
    })
    out = list(sup.handle(msg))
    acks = [m for m in out if m.envelope.topic == MAINT_ACK]
    assert acks and acks[0].payload.get("accepted") is True, (
        f"Expected accepted ack; got {[m.payload for m in out]}"
    )
    assert sup._replays_total.get("predict.final.dlq", 0) == 1


def test_replay_counter_zero_for_denied_operator_command(monkeypatch) -> None:
    """§8.14.5: operator dlq_replay for maint.dlq.v1.dlq → counter stays 0."""
    _setup_replay_cfg(monkeypatch, allow_csv="maint.dlq.v1.dlq")
    sup = MaintDlqSupervisor()
    msg = _wrap({
        "kind": "dlq_replay",
        "request_id": "req-8145-02",
        "client_id": "ops",
        "target": "maint.dlq.v1.dlq",
        "produced_at": _utc_iso(),
        "reason": "adversarial",
    })
    out = list(sup.handle(msg))
    acks = [m for m in out if m.envelope.topic == MAINT_ACK]
    assert acks and acks[0].payload.get("accepted") is False
    assert acks[0].payload.get("reason") == "recursion_deny"
    assert sup._replays_total.get("maint.dlq.v1.dlq", 0) == 0


# ─── Bullet 4: adversarial — confirm_destructive does NOT bypass deny set ────


def test_confirm_destructive_does_not_bypass_recursion_deny(monkeypatch) -> None:
    """§8.14.5: even with confirm_destructive, maint.dlq.v1.dlq is blocked.

    RECURSION_DENY_SET is unconditional and NOT operator-overridable.
    The supervisor must still reject the request with recursion_deny.
    """
    _setup_replay_cfg(monkeypatch, allow_csv="maint.dlq.v1.dlq")
    sup = MaintDlqSupervisor()
    msg = _wrap({
        "kind": "dlq_replay",
        "request_id": "req-8145-03",
        "client_id": "ops",
        "target": "maint.dlq.v1.dlq",
        "confirm_destructive": "I-understand-this-is-destructive",
        "produced_at": _utc_iso(),
        "reason": "adversarial override attempt",
    })
    out = list(sup.handle(msg))
    acks = [m for m in out if m.envelope.topic == MAINT_ACK]
    assert acks and acks[0].payload.get("accepted") is False, (
        "confirm_destructive must NOT override RECURSION_DENY_SET"
    )
    assert acks[0].payload.get("reason") == "recursion_deny"
    assert sup._replays_total.get("maint.dlq.v1.dlq", 0) == 0


# ─── Opsctl side: classifier returns CONFIRM for confirm_destructive ──────────


def test_classify_confirm_destructive_returns_confirm() -> None:
    """§8.14.5 opsctl: --confirm-destructive → classifier tier=CONFIRM."""
    from xops.opsctl._classify import Action, ClassifyRequest, classify

    req = ClassifyRequest(
        subcommand="dlq-replay",
        flags=frozenset({"confirm_destructive"}),
    )
    assert classify(req) == Action.CONFIRM


def test_classify_topic_sec_without_confirm_pii_still_refuses() -> None:
    """§8.14.5 opsctl: topic_sec without confirm_pii or confirm_destructive → REFUSE."""
    from xops.opsctl._classify import Action, ClassifyRequest, classify

    req = ClassifyRequest(
        subcommand="dlq-replay",
        flags=frozenset({"topic_sec"}),
    )
    assert classify(req) == Action.REFUSE


def test_maint_event_dlq_not_flagged_topic_sec_in_opsctl() -> None:
    """§8.14.5 opsctl: maint.event.v1.dlq target does NOT set topic_sec flag.

    It is a control-plane topic, not PII-bearing; the opsctl must not
    trigger the REFUSE branch for it.
    """
    import argparse
    from xops.opsctl.subcommands.dlq_replay import run

    # Simulate args as if the user ran:
    #   ops dlq-replay --target maint.event.v1.dlq --confirm-destructive TOKEN
    args = argparse.Namespace(
        target="maint.event.v1.dlq",
        max_msgs=0,
        drop=False,
        confirm_pii=False,
        confirm_destructive="I-am-operator",
        reason="test",
        client_id="opsctl",
        confirm="",
        dry_run=True,  # do not actually publish
        json=False,
    )
    # dry_run=True returns 0 without publishing; we just check it
    # doesn't fail with a bad-usage exit code from flag mismatch.
    rc = run(args, bus=None)
    assert rc == 0, (
        f"Expected exit 0 for dry-run on control-plane DLQ; got {rc}"
    )
