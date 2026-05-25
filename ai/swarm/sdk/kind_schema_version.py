"""Per-kind sub-schema version constants and boot-time validation.

Phase 8 §8.15.2 — Producer-side validation.

Every ``maint.event.v1`` kind that ships a per-kind sub-schema under
``ai/swarm/sdk/schemas/maint.event.v1/<kind>.json`` carries its own
``kind_schema_version`` integer in the schema AND an in-code constant
here.  At boot, :func:`validate_boot` cross-checks the two sources; a
mismatch (e.g. schema file edited but factory not updated) triggers an
``SystemExit(1)`` with a ``fail_safe_kind_schema_drift`` log.

Additive change discipline (§8.15.2):
  * Adding an **optional** field to an existing kind: bump ``KIND_SCHEMA_VERSIONS[kind]``
    here AND bump ``kind_schema_version`` in the on-disk ``<kind>.json`` in the
    same diff.
  * Adding a **breaking** change: ship ``<kind>.v2.json`` + new ``kind_v2`` value;
    keep the old entry unchanged.

The producer constants table is the authoritative "current" view; the
on-disk schema is the wire contract.  Both must always agree.
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_SCHEMA_DIR = Path(__file__).parent / "schemas" / "maint.event.v1"

# ── In-code constants (single source of truth for producers) ─────────────
# Add a new entry when a new kind is registered.  Bump the version when an
# optional field is added.  Never lower a version.
KIND_SCHEMA_VERSIONS: dict[str, int] = {
    "allowlist_approve": 1,
    "allowlist_extend": 1,
    "allowlist_rehash": 1,
    "allowlist_rotate_key": 1,
    "allowlist_show": 1,
    "audit_chain_verify": 1,
    "backup_age_alert": 1,
    "backup_cold_verify_completed": 1,
    "backup_cold_verify_failed": 1,
    "backup_completed": 1,
    "backup_key_compromise_acknowledged": 1,
    "backup_key_rotated": 1,
    "backup_legacy_manifest": 1,
    "backup_legacy_no_file_manifest": 1,
    "backup_model_cold_verify_completed": 1,
    "backup_model_cold_verify_failed": 1,
    "backup_model_lineage_drift": 1,
    "backup_model_lineage_legacy": 1,
    "backup_model_offsite_failed": 1,
    "backup_model_uploaded": 1,
    "backup_now": 1,
    "backup_offsite_failed": 1,
    "backup_offsite_uploaded": 1,
    "backup_pg_secret_expired": 1,
    "backup_restore_completed": 1,
    "backup_restore_started": 1,
    "backup_rotate_key": 1,
    "backup_started": 1,
    "backup_verify_failed": 1,
    "backup_verify_key_rotated": 1,
    "backup_verify_orphan_swept": 1,
    "baseline_reset": 1,
    "denylist_cap_cleared": 1,
    "denylist_clear": 1,
    "denylist_decimate": 1,
    "denylist_decimate_now": 1,
    "dlq_consumer_broken": 1,
    "dlq_drop_request": 1,
    "dlq_dropped": 1,
    "dlq_escalated": 1,
    "dlq_replay": 1,
    "dlq_replay_policy_loaded": 1,
    "dlq_replayed": 1,
    "dlq_topic_disabled_drained": 1,
    "dlq_topic_unfrozen": 1,
    "dlq_unfreeze": 1,
    "maint_clock_source_changed": 1,
    "maint_pause": 1,
    "maint_paused": 1,
    "maint_plane_recovered": 1,
    "maint_plane_throttled": 1,
    "maint_resume": 1,
    "maint_resumed": 1,
    "maint_scaler_default_applied": 1,
    "maint_silence_alert": 1,
    "maint_unknown_kind": 1,
    "manual_scale_pin": 1,
    "manual_scale_pin_expired": 1,
    "pattern_allowlist_added": 1,
    "pattern_allowlist_expired": 1,
    "pattern_allowlist_legacy_hit": 1,
    "pattern_allowlist_pending": 1,
    "pattern_allowlist_promoted": 1,
    "pii_erased": 1,
    "prune_completed": 1,
    "prune_skipped": 1,
    "prune_started": 1,
    "quarantine_clear": 1,
    "quarantine_erase": 1,
    "quarantine_pruned": 1,
    "restore": 1,
    "retrain_approve": 1,
    "retrain_request": 1,
    "scale_decision": 1,
    "scale_throttled": 1,
    "schema_drift_detected": 1,
    "spool_entry_aged_out": 1,
    "spool_entry_retired_kind": 1,
    "spool_flush_partial": 1,
    "trainer_warmup_hint": 1,
    # Phase 8 §8.15.4 — HMAC key lifecycle audit events.
    "opsctl_key_revoked": 1,
    "opsctl_key_rotated": 1,
    # Phase 8 §8.15.10 — restore-verify forensic sidecar capture.
    "verify_forensic_captured": 1,
    # Phase 8 §8.16.2 — spool-flush ack reconciliation summary.
    "spool_flush_acks_reconciled": 1,
    # Phase 8 §8.16.5 — multipart upload-id TTL audit event.
    "backup_offsite_upload_id_expired": 1,
}


class KindSchemaDriftError(SystemExit):
    """Raised (with exit-code 1) when the in-code version constant for a
    kind does not match the on-disk sub-schema's ``kind_schema_version``."""


def _read_file_version(kind: str) -> int | None:
    """Return the ``kind_schema_version`` declared in ``<kind>.json``, or
    ``None`` if the file is absent or carries no such field."""
    path = _SCHEMA_DIR / f"{kind}.json"
    if not path.exists():
        return None
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    props = data.get("properties", {})
    ksv = props.get("kind_schema_version")
    if ksv is None:
        return None
    # Prefer the const value (most schemas use ``{"const": N}``); fall back
    # to enum/minimum for forward compatibility.
    if "const" in ksv:
        return int(ksv["const"])
    return None


def validate_boot(topic: str = "maint.event.v1") -> None:
    """Cross-check every ``KIND_SCHEMA_VERSIONS`` constant against the
    corresponding on-disk sub-schema.

    Called once at agent boot (before the main loop).  On any mismatch
    logs a structured ``fail_safe_kind_schema_drift`` record and calls
    ``sys.exit(1)`` — a partial schema upgrade must not silently produce
    malformed events.

    :raises KindSchemaDriftError: (subclass of SystemExit) on first mismatch.
    """
    drifted: list[dict[str, Any]] = []
    for kind, code_version in sorted(KIND_SCHEMA_VERSIONS.items()):
        file_version = _read_file_version(kind)
        if file_version is None:
            # Schema file missing entirely — also a drift.
            drifted.append(
                {
                    "kind": kind,
                    "code_version": code_version,
                    "file_version": None,
                    "error": "schema_file_missing",
                }
            )
        elif file_version != code_version:
            drifted.append(
                {
                    "kind": kind,
                    "code_version": code_version,
                    "file_version": file_version,
                    "error": "version_mismatch",
                }
            )

    if drifted:
        msg = (
            f"fail_safe_kind_schema_drift: {len(drifted)} kind(s) have "
            f"schema version mismatch — fix KIND_SCHEMA_VERSIONS or the "
            f"on-disk sub-schema before restarting. Affected: "
            f"{[d['kind'] for d in drifted]}"
        )
        for entry in drifted:
            logger.critical(
                msg,
                extra={
                    "event": "fail_safe_kind_schema_drift",
                    "topic": topic,
                    **entry,
                },
            )
        # Raise with a single-arg SystemExit so .code == 1 (not a tuple).
        err = KindSchemaDriftError(1)
        err.detail = msg  # type: ignore[attr-defined]
        err.drifted = drifted  # type: ignore[attr-defined]
        raise err


def is_deprecated(kind: str) -> bool:
    """Return True if the on-disk sub-schema for ``kind`` is annotated
    ``"deprecated": true``."""
    path = _SCHEMA_DIR / f"{kind}.json"
    if not path.exists():
        return False
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return bool(data.get("deprecated", False))


def superseded_by(kind: str) -> str | None:
    """Return the ``superseded_by`` value from the on-disk sub-schema, or
    ``None`` if the kind is not deprecated / superseded."""
    path = _SCHEMA_DIR / f"{kind}.json"
    if not path.exists():
        return None
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data.get("superseded_by")


def deprecation_window_until(kind: str) -> str | None:
    """Return the ``deprecation_window_until`` ISO-8601 date string from the
    on-disk sub-schema, or ``None``."""
    path = _SCHEMA_DIR / f"{kind}.json"
    if not path.exists():
        return None
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data.get("deprecation_window_until")
