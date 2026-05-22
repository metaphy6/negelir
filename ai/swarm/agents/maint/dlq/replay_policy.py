"""Phase 8.16.7 — layered DLQ replay policy."""

from __future__ import annotations

from common.config import cfg as _cfg


DENY_PREFIXES: tuple[str, ...] = (
    "maint.",
    "sec.",
    "auth.",
    "payment.",
    "patcher.",
)

DENY_SUFFIXES: tuple[str, ...] = (
    ".dlq.dlq",
)

LEGACY_EXACT_DENY_TOPICS: frozenset[str] = frozenset({
    "maint.dlq.v1.dlq",
    "maint.event.v1.dlq",
    "maint.ack.v1.dlq",
    "sec.alert.v1.dlq",
    "sec.quarantine.v1.dlq",
    "qa.request.v1.dlq",
})


def current_allow_overrides() -> tuple[str, ...]:
    return tuple(_cfg.maint_dlq_replay_allow_overrides)


def replay_policy_snapshot(
    *, allow_overrides: tuple[str, ...] | list[str] | None = None
) -> dict[str, list[str]]:
    overrides = tuple(allow_overrides) if allow_overrides is not None else current_allow_overrides()
    return {
        "deny_prefixes": list(DENY_PREFIXES),
        "deny_suffixes": list(DENY_SUFFIXES),
        "allow_overrides": list(overrides),
    }


def deny_reason(
    topic: str,
    *,
    allow_overrides: tuple[str, ...] | list[str] | None = None,
) -> str | None:
    normalized = str(topic or "").strip()
    if not normalized:
        return "invalid_topic"
    if any(normalized.endswith(suffix) for suffix in DENY_SUFFIXES):
        return "deny_suffix"
    if normalized in LEGACY_EXACT_DENY_TOPICS:
        return "recursion_deny"
    overrides = tuple(allow_overrides) if allow_overrides is not None else current_allow_overrides()
    if normalized in overrides:
        return None
    if any(normalized.startswith(prefix) for prefix in DENY_PREFIXES):
        return "recursion_deny"
    return None


def is_replayable(
    topic: str,
    *,
    allow_overrides: tuple[str, ...] | list[str] | None = None,
) -> bool:
    return deny_reason(topic, allow_overrides=allow_overrides) is None


def build_policy_loaded_payload(
    *,
    produced_at: str,
    target: str = "maint.dlq.v1",
    allow_overrides: tuple[str, ...] | list[str] | None = None,
) -> dict[str, object]:
    snapshot = replay_policy_snapshot(allow_overrides=allow_overrides)
    return {
        "kind": "dlq_replay_policy_loaded",
        "kind_schema_version": 1,
        "target": target,
        "produced_at": produced_at,
        **snapshot,
    }


__all__ = [
    "DENY_PREFIXES",
    "DENY_SUFFIXES",
    "LEGACY_EXACT_DENY_TOPICS",
    "build_policy_loaded_payload",
    "current_allow_overrides",
    "deny_reason",
    "is_replayable",
    "replay_policy_snapshot",
]
