"""Phase 8.16.9 producer-side maint/sec topic routing helper.

The helper is intentionally tiny and strict: producers ask this module for
the topic route and fail fast if a kind has no routing row.
"""
from __future__ import annotations

from hashlib import sha256
from typing import Final

MAINT_EVENT_TOPIC: Final[str] = "maint.event.v1"
SEC_ALERT_TOPIC: Final[str] = "sec.alert.v1"

# Static routing table (kind -> topic tuple).
# A missing row is treated as a boundary error.
_KIND_TOPIC_TABLE: Final[dict[str, tuple[str, ...]]] = {
    "backup_completed": (MAINT_EVENT_TOPIC,),
    "backup_verify_failed": (MAINT_EVENT_TOPIC, SEC_ALERT_TOPIC),
    "opsctl_signature_invalid": (SEC_ALERT_TOPIC,),
}


def derive_event_correlation_id(*, kind: str, target: str | None, produced_at: str) -> str:
    """Derive a stable short correlation id shared by maint/sec dual emits."""
    token = f"{kind}|{target or ''}|{produced_at}"
    return sha256(token.encode("utf-8")).hexdigest()[:16]


def _known_kind_membership(kind: str) -> tuple[bool, bool]:
    """Return ``(is_known_maint_kind, is_known_sec_kind)`` for ``kind``."""
    from ai.swarm.agents.maint import KNOWN_MAINT_EVENT_KINDS
    from ai.swarm.agents.payloads import KNOWN_SEC_ALERT_KINDS

    return kind in KNOWN_MAINT_EVENT_KINDS, kind in KNOWN_SEC_ALERT_KINDS


def route_topics_for_kind(
    *,
    kind: str,
    severity: str,
    target: str | None,
) -> tuple[str, ...]:
    """Return publish topics for a ``(kind, severity, target)`` tuple.

    ``severity`` and ``target`` are accepted for future rule expansion and to
    keep the call shape uniform across both producer factories.
    """
    del severity, target
    if not kind:
        raise ValueError("dual-emit routing requires non-empty kind")

    topics = _KIND_TOPIC_TABLE.get(kind)
    if topics is not None:
        return topics

    in_maint, in_sec = _known_kind_membership(kind)
    if in_maint and in_sec:
        return (MAINT_EVENT_TOPIC, SEC_ALERT_TOPIC)
    if in_maint:
        return (MAINT_EVENT_TOPIC,)
    if in_sec:
        return (SEC_ALERT_TOPIC,)

    raise ValueError(
        f"dual-emit routing row missing for kind={kind!r}; add a row to _KIND_TOPIC_TABLE"
    )


__all__ = [
    "MAINT_EVENT_TOPIC",
    "SEC_ALERT_TOPIC",
    "derive_event_correlation_id",
    "route_topics_for_kind",
]
