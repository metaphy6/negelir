"""SDK-level ``maint.event.v1`` consumer / producer payloads.

Phase 8 §8.15.2 — Consumer-side tolerance + producer-side factory.

``MaintEvent``
--------------
Dual role:

1. **Producer factory** — ``MaintEvent.<kind>(**fields)`` class-methods
   check ``kind_schema_version`` of the loaded per-kind sub-schema against
   the in-code constant in :mod:`swarm.sdk.kind_schema_version`; a mismatch
   (partial schema upgrade) raises ``SystemExit(1)`` at boot via
   :func:`~swarm.sdk.kind_schema_version.validate_boot`.

2. **Consumer deserialiser** — ``MaintEvent.from_dict(payload)`` returns a
   :class:`MaintEventPayload` with all *known* envelope fields populated and
   any *unknown* fields (introduced by a higher ``kind_schema_version``)
   preserved verbatim on the ``_extra`` dict.  Consumers that need a field
   they have not seen before must opt-in by bumping the version they declare
   in :data:`~swarm.sdk.kind_schema_version.KIND_SCHEMA_VERSIONS`; they must
   never rely on silent "field exists but I'll ignore it" discovery.

Deprecation logging
-------------------
When ``from_dict`` (or a factory method) constructs a payload whose kind is
annotated ``"deprecated": true`` in the on-disk sub-schema, it emits a
one-shot ``DeprecationWarning`` via the standard :mod:`warnings` module (one
warning per ``(kind, process)`` pair using the ``default`` filter).
"""
from __future__ import annotations

import logging
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ai.swarm.sdk import kind_schema_version as _ksv
from ai.swarm.sdk._dual_emit_helper import (
    MAINT_EVENT_TOPIC,
    SEC_ALERT_TOPIC,
    derive_event_correlation_id,
    route_topics_for_kind,
)

logger = logging.getLogger(__name__)


def dual_emit_correlation_id(*, kind: str, target: str | None, produced_at: str) -> str:
    """Canonical single source for maint/sec dual-emit correlation IDs.

    Returns the 16-character lowercase hex join key shared by a ``maint.event.v1``
    and a ``sec.alert.v1`` emitted for the same underlying event.

    This is the **only** sanctioned derivation site.  An AST scan in
    ``ai/swarm/tests/test_phase8_16_16_correlation_id.py`` rejects any
    code outside this module that builds ``event_correlation_id`` by hand
    (sha256 slicing, f-strings, etc.).

    Delegates to :func:`swarm.sdk._dual_emit_helper.derive_event_correlation_id`.
    """
    return derive_event_correlation_id(kind=kind, target=target, produced_at=produced_at)


# ── Known envelope-level fields ─────────────────────────────────────────
# These are the fields present on the *envelope* layer of maint.event.v1
# that every kind may carry.  Kind-specific fields land in ``_extra``.
_ENVELOPE_FIELDS: frozenset[str] = frozenset(
    {
        "kind",
        "kind_schema_version",
        "produced_at",
        "target",
        "request_id",
        "fire_window_id",
        "agent_id",
        "dry_run",
    }
)


@dataclass
class MaintEventPayload:
    """Generic deserialized ``maint.event.v1`` payload.

    Consumers that only need the routing fields (``kind``, ``target``,
    ``request_id``) use this class directly.  Consumers that need
    kind-specific fields access them through ``payload._extra["<field>"]``
    or, for forward-compat, through ``payload.get("<field>")``.

    Invariant: ``kind`` and ``produced_at`` are always present (the
    from_dict constructor raises :class:`ValueError` if either is absent).
    ``kind_schema_version`` defaults to 1 when absent (graceful degradation
    for payloads produced by older agents that pre-date §8.15.2).
    """

    kind: str
    produced_at: str
    kind_schema_version: int = 1
    target: str | None = None
    request_id: str | None = None
    fire_window_id: str | None = None
    agent_id: str | None = None
    dry_run: bool | None = None
    # Unknown / kind-specific fields preserved here verbatim.
    _extra: dict[str, Any] = field(default_factory=dict, compare=False)

    def get(self, key: str, default: Any = None) -> Any:
        """Return an envelope field or an extra field by name.

        Envelope fields take precedence; unknown fields are looked up in
        ``_extra``.  Returns ``default`` if the key is absent in both.
        """
        try:
            val = getattr(self, key)
            if val is not None:
                return val
        except AttributeError:
            pass
        return self._extra.get(key, default)

    def as_dict(self) -> dict[str, Any]:
        """Return a plain ``dict`` merging envelope fields and extras."""
        out: dict[str, Any] = {
            "kind": self.kind,
            "produced_at": self.produced_at,
            "kind_schema_version": self.kind_schema_version,
        }
        for attr in ("target", "request_id", "fire_window_id", "agent_id", "dry_run"):
            val = getattr(self, attr)
            if val is not None:
                out[attr] = val
        out.update(self._extra)
        return out


def _warn_deprecated_once(kind: str) -> None:
    sup = _ksv.superseded_by(kind)
    until = _ksv.deprecation_window_until(kind)
    msg = (
        f"maint.event.v1 kind={kind!r} is deprecated"
        + (f"; superseded by {sup!r}" if sup else "")
        + (f"; deprecation window until {until}" if until else "")
        + ". Consumers should migrate to the replacement kind."
    )
    warnings.warn(msg, DeprecationWarning, stacklevel=3)


class MaintEvent:
    """Factory and consumer class for ``maint.event.v1`` payloads.

    Usage
    -----
    Producer::

        payload = MaintEvent.scale_decision(
            target="pred.elo.v1",
            produced_at="2026-05-22T00:00:00Z",
            replicas=2,
            ...
        )

    Consumer::

        evt = MaintEvent.from_dict(raw_payload)
        print(evt.kind, evt.target, evt._extra.get("replicas"))

    Boot validation (call once per process on startup)::

        MaintEvent.validate_boot()
    """

    # ------------------------------------------------------------------
    # Boot validation
    # ------------------------------------------------------------------

    @staticmethod
    def validate_boot() -> None:
        """Validate all in-code version constants against on-disk schemas.

        Calls :func:`~swarm.sdk.kind_schema_version.validate_boot`.
        Raises ``SystemExit(1)`` (via :exc:`KindSchemaDriftError`) on any
        mismatch.
        """
        _ksv.validate_boot()

    # ------------------------------------------------------------------
    # Consumer deserializer
    # ------------------------------------------------------------------

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> MaintEventPayload:
        """Deserialize a raw ``maint.event.v1`` dict into a
        :class:`MaintEventPayload`.

        Known envelope fields are populated on the dataclass; unknown
        fields (introduced by a newer ``kind_schema_version`` or by future
        additive changes) are preserved verbatim on ``_extra``.

        :param payload: raw dict from the bus.
        :raises ValueError: if ``kind`` or ``produced_at`` are absent.
        """
        if "kind" not in payload:
            raise ValueError("maint.event.v1 payload missing required key 'kind'")
        if "produced_at" not in payload:
            raise ValueError("maint.event.v1 payload missing required key 'produced_at'")

        kind: str = str(payload["kind"])
        produced_at: str = str(payload["produced_at"])
        kind_schema_version: int = int(payload.get("kind_schema_version", 1))

        # Warn once if the kind is deprecated.
        if _ksv.is_deprecated(kind):
            _warn_deprecated_once(kind)

        # Envelope fields.
        target: str | None = payload.get("target")
        request_id: str | None = payload.get("request_id")
        fire_window_id: str | None = payload.get("fire_window_id")
        agent_id: str | None = payload.get("agent_id")
        dry_run: bool | None = payload.get("dry_run")

        # Extra: everything not in the known envelope set.
        extra: dict[str, Any] = {
            k: v for k, v in payload.items() if k not in _ENVELOPE_FIELDS
        }

        return MaintEventPayload(
            kind=kind,
            produced_at=produced_at,
            kind_schema_version=kind_schema_version,
            target=target,
            request_id=request_id,
            fire_window_id=fire_window_id,
            agent_id=agent_id,
            dry_run=dry_run,
            _extra=extra,
        )

    # ------------------------------------------------------------------
    # Producer factory helpers — checked against KIND_SCHEMA_VERSIONS
    # ------------------------------------------------------------------

    @staticmethod
    def publish_topics(*, kind: str, severity: str, target: str | None) -> tuple[str, ...]:
        """Return the canonical publish-topic tuple for the given event shape."""
        return route_topics_for_kind(kind=kind, severity=severity, target=target)

    @classmethod
    def _make(cls, kind: str, **fields: Any) -> dict[str, Any]:
        """Internal helper: build a raw dict for ``kind``, injecting
        ``kind_schema_version`` from the in-code constants table.

        If a ``details`` kwarg is present, its serialised JSON size is
        checked against ``cfg.maint_audit_per_kind_details_max_bytes``
        (§8.15.5 per-kind soft fence).  Over-budget details are replaced
        with the sentinel dict and the original is written to
        ``data/maint/audit_oversize/<row_id>.json``.

        ``row_id`` defaults to ``fields.get("request_id", kind)`` when not
        supplied — sufficient for uniqueness in normal operation; tests may
        supply an explicit ``_audit_row_id`` kwarg (stripped before the dict
        is returned) to control the sidecar filename.

        Logs a one-shot warning if the kind is deprecated.
        """
        code_version = _ksv.KIND_SCHEMA_VERSIONS.get(kind)
        if code_version is None:
            raise ValueError(
                f"maint.event.v1 kind={kind!r} has no entry in "
                f"KIND_SCHEMA_VERSIONS; register it before emitting."
            )
        if _ksv.is_deprecated(kind):
            _warn_deprecated_once(kind)

        # Strip the internal testing kwarg (never reaches the wire).
        audit_row_id: str = str(fields.pop("_audit_row_id", "") or fields.get("request_id", kind) or kind)

        # §8.15.5 per-kind soft fence: cap the ``details`` kwarg.
        if "details" in fields and isinstance(fields["details"], dict):
            from ai.common.config import cfg as _cfg  # lazy import — avoids boot-time cycle
            from ai.swarm.sdk.maint_audit import truncate_oversize as _truncate
            kind_budgets = _cfg.maint_audit_per_kind_details_max_bytes_parsed
            cap = kind_budgets.get(kind, kind_budgets.get("default", 2048))
            oversize_dir = Path(_cfg.data_dir) / "maint" / "audit_oversize"
            fields["details"] = _truncate(
                fields["details"],
                kind=kind,
                row_id=audit_row_id,
                oversize_dir=oversize_dir,
                cap_bytes=cap,
            )

        try:
            topics = route_topics_for_kind(
                kind=kind,
                severity=str(fields.get("severity", "")),
                target=(str(fields.get("target")) if fields.get("target") is not None else None),
            )
        except ValueError:
            topics = ()
        if (
            MAINT_EVENT_TOPIC in topics
            and SEC_ALERT_TOPIC in topics
            and "event_correlation_id" not in fields
        ):
            fields["event_correlation_id"] = dual_emit_correlation_id(
                kind=kind,
                target=(str(fields.get("target")) if fields.get("target") is not None else None),
                produced_at=str(fields.get("produced_at", "")),
            )

        return {"kind": kind, "kind_schema_version": code_version, **fields}

    @classmethod
    def scale_decision(cls, **fields: Any) -> dict[str, Any]:
        return cls._make("scale_decision", **fields)

    @classmethod
    def scale_throttled(cls, **fields: Any) -> dict[str, Any]:
        return cls._make("scale_throttled", **fields)

    @classmethod
    def maint_plane_throttled(cls, **fields: Any) -> dict[str, Any]:
        return cls._make("maint_plane_throttled", **fields)

    @classmethod
    def maint_plane_recovered(cls, **fields: Any) -> dict[str, Any]:
        return cls._make("maint_plane_recovered", **fields)

    @classmethod
    def dlq_escalated(cls, **fields: Any) -> dict[str, Any]:
        return cls._make("dlq_escalated", **fields)

    @classmethod
    def dlq_replay_policy_loaded(cls, **fields: Any) -> dict[str, Any]:
        return cls._make("dlq_replay_policy_loaded", **fields)

    @classmethod
    def dlq_dropped(cls, **fields: Any) -> dict[str, Any]:
        return cls._make("dlq_dropped", **fields)

    @classmethod
    def schema_drift_detected(cls, **fields: Any) -> dict[str, Any]:
        return cls._make("schema_drift_detected", **fields)

    @classmethod
    def maint_clock_source_changed(cls, **fields: Any) -> dict[str, Any]:
        return cls._make("maint_clock_source_changed", **fields)

    @classmethod
    def backup_started(cls, **fields: Any) -> dict[str, Any]:
        return cls._make("backup_started", **fields)

    @classmethod
    def backup_completed(cls, **fields: Any) -> dict[str, Any]:
        return cls._make("backup_completed", **fields)

    @classmethod
    def retrain_request(cls, **fields: Any) -> dict[str, Any]:
        return cls._make("retrain_request", **fields)

    @classmethod
    def baseline_reset(cls, **fields: Any) -> dict[str, Any]:
        return cls._make("baseline_reset", **fields)

    @classmethod
    def spool_entry_aged_out(cls, **fields: Any) -> dict[str, Any]:
        return cls._make("spool_entry_aged_out", **fields)

    @classmethod
    def spool_entry_retired_kind(cls, **fields: Any) -> dict[str, Any]:
        return cls._make("spool_entry_retired_kind", **fields)

    @classmethod
    def spool_flush_partial(cls, **fields: Any) -> dict[str, Any]:
        return cls._make("spool_flush_partial", **fields)

    @classmethod
    def maint_paused(cls, **fields: Any) -> dict[str, Any]:
        return cls._make("maint_paused", **fields)

    @classmethod
    def maint_resumed(cls, **fields: Any) -> dict[str, Any]:
        return cls._make("maint_resumed", **fields)

    @classmethod
    def maint_unknown_kind(cls, **fields: Any) -> dict[str, Any]:
        return cls._make("maint_unknown_kind", **fields)

    @classmethod
    def pattern_allowlist_promoted(cls, **fields: Any) -> dict[str, Any]:
        return cls._make("pattern_allowlist_promoted", **fields)

    @classmethod
    def pattern_allowlist_pending(cls, **fields: Any) -> dict[str, Any]:
        return cls._make("pattern_allowlist_pending", **fields)

    @classmethod
    def pattern_allowlist_added(cls, **fields: Any) -> dict[str, Any]:
        return cls._make("pattern_allowlist_added", **fields)

    @classmethod
    def pattern_allowlist_expired(cls, **fields: Any) -> dict[str, Any]:
        return cls._make("pattern_allowlist_expired", **fields)

    @classmethod
    def pii_erased(cls, **fields: Any) -> dict[str, Any]:
        return cls._make("pii_erased", **fields)

    @classmethod
    def prune_started(cls, **fields: Any) -> dict[str, Any]:
        return cls._make("prune_started", **fields)

    @classmethod
    def prune_completed(cls, **fields: Any) -> dict[str, Any]:
        return cls._make("prune_completed", **fields)

    @classmethod
    def prune_skipped(cls, **fields: Any) -> dict[str, Any]:
        return cls._make("prune_skipped", **fields)

    @classmethod
    def quarantine_pruned(cls, **fields: Any) -> dict[str, Any]:
        return cls._make("quarantine_pruned", **fields)

    @classmethod
    def backup_offsite_uploaded(cls, **fields: Any) -> dict[str, Any]:
        return cls._make("backup_offsite_uploaded", **fields)

    @classmethod
    def backup_verify_orphan_swept(cls, **fields: Any) -> dict[str, Any]:
        return cls._make("backup_verify_orphan_swept", **fields)

    @classmethod
    def backup_model_uploaded(cls, **fields: Any) -> dict[str, Any]:
        return cls._make("backup_model_uploaded", **fields)

    @classmethod
    def backup_key_compromise_acknowledged(cls, **fields: Any) -> dict[str, Any]:
        return cls._make("backup_key_compromise_acknowledged", **fields)

    @classmethod
    def backup_key_rotated(cls, **fields: Any) -> dict[str, Any]:
        return cls._make("backup_key_rotated", **fields)

    @classmethod
    def denylist_cap_cleared(cls, **fields: Any) -> dict[str, Any]:
        return cls._make("denylist_cap_cleared", **fields)

    @classmethod
    def maint_silence_alert(cls, **fields: Any) -> dict[str, Any]:
        return cls._make("maint_silence_alert", **fields)

    @classmethod
    def manual_scale_pin(cls, **fields: Any) -> dict[str, Any]:
        return cls._make("manual_scale_pin", **fields)

    @classmethod
    def manual_scale_pin_expired(cls, **fields: Any) -> dict[str, Any]:
        return cls._make("manual_scale_pin_expired", **fields)

    @classmethod
    def trainer_warmup_hint(cls, **fields: Any) -> dict[str, Any]:
        return cls._make("trainer_warmup_hint", **fields)

    @classmethod
    def retrain_approve(cls, **fields: Any) -> dict[str, Any]:
        return cls._make("retrain_approve", **fields)

    @classmethod
    def maint_scaler_default_applied(cls, **fields: Any) -> dict[str, Any]:
        return cls._make("maint_scaler_default_applied", **fields)

    @classmethod
    def restore(cls, **fields: Any) -> dict[str, Any]:
        return cls._make("restore", **fields)

    @classmethod
    def allowlist_approve(cls, **fields: Any) -> dict[str, Any]:
        return cls._make("allowlist_approve", **fields)

    @classmethod
    def allowlist_extend(cls, **fields: Any) -> dict[str, Any]:
        return cls._make("allowlist_extend", **fields)

    @classmethod
    def allowlist_show(cls, **fields: Any) -> dict[str, Any]:
        return cls._make("allowlist_show", **fields)

    @classmethod
    def backup_now(cls, **fields: Any) -> dict[str, Any]:
        return cls._make("backup_now", **fields)

    @classmethod
    def backup_rotate_key(cls, **fields: Any) -> dict[str, Any]:
        return cls._make("backup_rotate_key", **fields)

    @classmethod
    def denylist_clear(cls, **fields: Any) -> dict[str, Any]:
        return cls._make("denylist_clear", **fields)

    @classmethod
    def denylist_decimate_now(cls, **fields: Any) -> dict[str, Any]:
        return cls._make("denylist_decimate_now", **fields)

    @classmethod
    def denylist_decimate(cls, **fields: Any) -> dict[str, Any]:
        return cls._make("denylist_decimate", **fields)

    @classmethod
    def dlq_consumer_broken(cls, **fields: Any) -> dict[str, Any]:
        return cls._make("dlq_consumer_broken", **fields)

    @classmethod
    def dlq_replay(cls, **fields: Any) -> dict[str, Any]:
        return cls._make("dlq_replay", **fields)

    @classmethod
    def dlq_replayed(cls, **fields: Any) -> dict[str, Any]:
        return cls._make("dlq_replayed", **fields)

    @classmethod
    def dlq_topic_disabled_drained(cls, **fields: Any) -> dict[str, Any]:
        return cls._make("dlq_topic_disabled_drained", **fields)

    @classmethod
    def dlq_topic_unfrozen(cls, **fields: Any) -> dict[str, Any]:
        return cls._make("dlq_topic_unfrozen", **fields)

    @classmethod
    def dlq_unfreeze(cls, **fields: Any) -> dict[str, Any]:
        return cls._make("dlq_unfreeze", **fields)

    @classmethod
    def maint_pause(cls, **fields: Any) -> dict[str, Any]:
        return cls._make("maint_pause", **fields)

    @classmethod
    def maint_resume(cls, **fields: Any) -> dict[str, Any]:
        return cls._make("maint_resume", **fields)

    @classmethod
    def quarantine_clear(cls, **fields: Any) -> dict[str, Any]:
        return cls._make("quarantine_clear", **fields)

    @classmethod
    def quarantine_erase(cls, **fields: Any) -> dict[str, Any]:
        return cls._make("quarantine_erase", **fields)

    @classmethod
    def backup_age_alert(cls, **fields: Any) -> dict[str, Any]:
        return cls._make("backup_age_alert", **fields)

    @classmethod
    def backup_cold_verify_completed(cls, **fields: Any) -> dict[str, Any]:
        return cls._make("backup_cold_verify_completed", **fields)

    @classmethod
    def backup_cold_verify_failed(cls, **fields: Any) -> dict[str, Any]:
        return cls._make("backup_cold_verify_failed", **fields)

    @classmethod
    def backup_legacy_manifest(cls, **fields: Any) -> dict[str, Any]:
        return cls._make("backup_legacy_manifest", **fields)

    @classmethod
    def backup_legacy_no_file_manifest(cls, **fields: Any) -> dict[str, Any]:
        return cls._make("backup_legacy_no_file_manifest", **fields)

    @classmethod
    def backup_model_cold_verify_completed(cls, **fields: Any) -> dict[str, Any]:
        return cls._make("backup_model_cold_verify_completed", **fields)

    @classmethod
    def backup_model_cold_verify_failed(cls, **fields: Any) -> dict[str, Any]:
        return cls._make("backup_model_cold_verify_failed", **fields)

    @classmethod
    def backup_model_lineage_drift(cls, **fields: Any) -> dict[str, Any]:
        return cls._make("backup_model_lineage_drift", **fields)

    @classmethod
    def backup_model_offsite_failed(cls, **fields: Any) -> dict[str, Any]:
        return cls._make("backup_model_offsite_failed", **fields)

    @classmethod
    def backup_offsite_failed(cls, **fields: Any) -> dict[str, Any]:
        return cls._make("backup_offsite_failed", **fields)

    @classmethod
    def backup_pg_secret_expired(cls, **fields: Any) -> dict[str, Any]:
        return cls._make("backup_pg_secret_expired", **fields)

    @classmethod
    def backup_restore_completed(cls, **fields: Any) -> dict[str, Any]:
        return cls._make("backup_restore_completed", **fields)

    @classmethod
    def backup_restore_started(cls, **fields: Any) -> dict[str, Any]:
        return cls._make("backup_restore_started", **fields)

    @classmethod
    def backup_started(cls, **fields: Any) -> dict[str, Any]:  # type: ignore[override]
        return cls._make("backup_started", **fields)

    @classmethod
    def backup_verify_failed(cls, **fields: Any) -> dict[str, Any]:
        return cls._make("backup_verify_failed", **fields)

    @classmethod
    def backup_verify_key_rotated(cls, **fields: Any) -> dict[str, Any]:
        return cls._make("backup_verify_key_rotated", **fields)

    @classmethod
    def backup_model_uploaded(cls, **fields: Any) -> dict[str, Any]:  # type: ignore[override]
        return cls._make("backup_model_uploaded", **fields)
