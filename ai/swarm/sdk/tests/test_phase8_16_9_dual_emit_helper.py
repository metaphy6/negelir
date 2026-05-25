"""Phase 8.16.9 producer-side routing helper tests."""
from __future__ import annotations

import pytest

from swarm.agents.maint import KNOWN_MAINT_EVENT_KINDS
from swarm.agents.payloads import SecAlert
from swarm.agents.payloads import KNOWN_SEC_ALERT_KINDS
from swarm.sdk import _dual_emit_helper as dual_emit_helper
from swarm.sdk._dual_emit_helper import (
    MAINT_EVENT_TOPIC,
    SEC_ALERT_TOPIC,
    derive_event_correlation_id,
    route_topics_for_kind,
)
from swarm.sdk.payloads import MaintEvent


@pytest.mark.parametrize(
    "kind,severity,target,expected",
    [
        ("backup_completed", "info", "maint.backup.v1", (MAINT_EVENT_TOPIC,)),
        (
            "backup_verify_failed",
            "critical",
            "maint.backup.v1",
            (MAINT_EVENT_TOPIC, SEC_ALERT_TOPIC),
        ),
        ("opsctl_signature_invalid", "critical", "ops_console", (SEC_ALERT_TOPIC,)),
    ],
)
def test_route_topics_for_kind_returns_expected_pair(
    kind: str,
    severity: str,
    target: str,
    expected: tuple[str, ...],
) -> None:
    assert route_topics_for_kind(kind=kind, severity=severity, target=target) == expected


def test_maint_event_publish_topics_uses_shared_helper() -> None:
    assert MaintEvent.publish_topics(
        kind="backup_verify_failed",
        severity="critical",
        target="maint.backup.v1",
    ) == (MAINT_EVENT_TOPIC, SEC_ALERT_TOPIC)


def test_sec_alert_publish_topics_uses_shared_helper() -> None:
    assert SecAlert.publish_topics(
        kind="opsctl_signature_invalid",
        severity="critical",
        target="ops_console",
    ) == (SEC_ALERT_TOPIC,)


def test_missing_routing_row_fails_fast() -> None:
    with pytest.raises(ValueError, match="routing row missing"):
        route_topics_for_kind(kind="unknown_new_kind", severity="warn", target="any")


def test_dual_emit_routing_rows_are_known_kinds_and_non_empty() -> None:
    known_kinds = set(KNOWN_MAINT_EVENT_KINDS) | set(KNOWN_SEC_ALERT_KINDS)
    rows = dual_emit_helper._KIND_TOPIC_TABLE

    assert rows, "dual emit routing table must not be empty"
    for kind, topics in rows.items():
        assert kind in known_kinds, f"routing kind {kind!r} must be in known kind sets"
        assert topics, f"routing kind {kind!r} must map to at least one topic"


def test_route_topics_covers_all_known_kinds() -> None:
    for kind in sorted(KNOWN_MAINT_EVENT_KINDS):
        topics = route_topics_for_kind(
            kind=kind,
            severity="info",
            target="maint.backup.v1",
        )
        assert topics, f"known maint kind {kind!r} must route to at least one topic"
        assert MAINT_EVENT_TOPIC in topics, (
            f"known maint kind {kind!r} must route to maint.event.v1"
        )

    for kind in sorted(KNOWN_SEC_ALERT_KINDS):
        topics = route_topics_for_kind(
            kind=kind,
            severity="warn",
            target="maint.backup.v1",
        )
        assert topics, f"known sec kind {kind!r} must route to at least one topic"
        assert SEC_ALERT_TOPIC in topics, (
            f"known sec kind {kind!r} must route to sec.alert.v1"
        )


def test_dual_emission_correlation_uses_same_topics_across_factories() -> None:
    expected = (MAINT_EVENT_TOPIC, SEC_ALERT_TOPIC)

    assert route_topics_for_kind(
        kind="backup_verify_failed",
        severity="critical",
        target="maint.backup.v1",
    ) == expected
    assert MaintEvent.publish_topics(
        kind="backup_verify_failed",
        severity="critical",
        target="maint.backup.v1",
    ) == expected
    assert SecAlert.publish_topics(
        kind="backup_verify_failed",
        severity="critical",
        target="maint.backup.v1",
    ) == expected


def test_backup_verify_failed_dual_emit_uses_same_event_correlation_id() -> None:
    produced_at = "2026-05-22T00:00:00Z"

    maint_payload = MaintEvent.backup_verify_failed(
        produced_at=produced_at,
        target="maint.backup.v1",
        reason="verify failed",
    )
    sec_payload = SecAlert(
        alert_id="a-1",
        kind="backup_verify_failed",
        severity="critical",
        source="maint.backup.v1",
        reason="verify failed",
        produced_at=produced_at,
    ).as_dict()

    expected = derive_event_correlation_id(
        kind="backup_verify_failed",
        target="maint.backup.v1",
        produced_at=produced_at,
    )
    assert maint_payload["event_correlation_id"] == expected
    assert sec_payload["event_correlation_id"] == expected
