"""Phase 8 §8.0 — `maint.event.v1` kind → expected-consumer-set routing.

This module is the **single source of truth** for which agent ids
must publish a `maint.ack.v1` for each `maint.event.v1{kind=...}`.
The §8.1 ops console reads this map at publish-time to compute the
expected ack set; the wait-for-acks loop then matches incoming
`maint.ack.v1.accepted_by` values against it.

Boundary discipline (binding, per ROADMAP §0):

* Every kind here MUST have a matching per-kind sub-schema at
  ``ai/swarm/sdk/schemas/maint.event.v1/<kind>.json``. Orphans on
  either side fail CI (test in
  ``ai/swarm/agents/maint/tests/test_phase8_kind_routing.py``).

* An empty consumer set is **not** legal at the ops console layer:
  publishing a `maint.event.v1{kind=...}` with no registered
  consumer that accepts it exits the ops console with code 5
  (``no_consumer_for_kind``) BEFORE hitting the bus. This guard
  prevents fire-and-forget envelopes that nobody owns.

  However, during pre-Phase-8.x rollout some kinds are emitted by
  Phase 6/7 producers with no Phase 8 consumer yet (e.g. the
  trainer.v1 agent for ``retrain_request`` / ``retrain_approve``
  has not landed in v1; until Phase 5.x trainer-as-agent ships,
  these kinds route to the empty set). Those kinds are listed in
  ``KINDS_PENDING_CONSUMER_LANDING`` so the boundary test asserts
  intent (not all empty-routes are bugs) and the ops console
  surfaces a clear ``no_consumer_for_kind: pending Phase X`` error
  instead of a generic one.

Adding a new kind is a three-edit change in the same diff:

  1. Add the kind here with its consumer-set frozenset.
  2. Add the sub-schema file.
  3. Add per-kind shape proof tests in
     ``test_phase8_maint_event_kind_shapes.py``.
"""
from __future__ import annotations

from typing import Final, Mapping

# ── Kind → consumer-set map (binding wire authority) ────────────────────
#
# Keys MUST match the per-kind sub-schema filenames under
# ``ai/swarm/sdk/schemas/maint.event.v1/<kind>.json``.
# Values are frozensets of registered agent ids (from
# ``ai.swarm.agents.bootstrap.build_agents()``); the publisher waits
# for one ack per id.

_ACK_ROUTING_TABLE: Final[Mapping[str, frozenset[str]]] = {
    # Phase 6.3 drift → trainer (action of record) + scaler (warm-up).
    # Trainer-as-agent does not land until Phase 5.x patch (per ROADMAP
    # §8.16 chart compatibility block); scaler lands in §8.2. Until
    # then, this set is intentionally empty and listed in
    # KINDS_PENDING_CONSUMER_LANDING.
    "retrain_request":   frozenset(),
    # Operator override — same set as retrain_request (trainer is the
    # action-of-record).
    "retrain_approve":   frozenset(),
    # Phase 7 §7.3 — sec.rate.v1 owns the denylist key surface.
    "denylist_clear":    frozenset({"sec.rate.v1"}),
    # Phase 7 §7.2 — sec.scrape.v1 owns source fingerprints.
    "baseline_reset":    frozenset({"sec.scrape.v1"}),
    # Phase 7 §7.1 / Phase 8 §8.3 — maint.backup.v1 is the consumer of
    # right-to-erasure requests in v1 (the storage.v1 surface lives in
    # the Phase R1 datasource bootstrap and is NOT yet wired). The
    # backup agent owns quarantine_samples lifecycle (TTL pruning AND
    # operator-driven erasure) so it is the natural single consumer.
    "quarantine_erase":  frozenset({"maint.backup.v1"}),
    # Phase 8 §8.7 — FP feedback loop. Consumed by maint.sec.v1.
    "quarantine_clear":  frozenset({"maint.sec.v1"}),
    # Phase 8 §8.2 — operator pins replica count on a scalable agent.
    "manual_scale_pin":  frozenset({"maint.scaler.v1"}),
    # Phase 8 §8.5 — operator-driven DLQ replay request.
    "dlq_replay":        frozenset({"maint.dlq.v1"}),
    # Phase 8 §8.15.9 — operator explicitly drops a DLQ entry without
    # replaying it. Supervisor acks AND emits dlq_dropped{reason=operator_drop}
    # with forensic fields for the audit channel.
    "dlq_drop_request":  frozenset({"maint.dlq.v1"}),
    # Phase 8 §8.5 C2 — operator lifts a poison-pattern freeze.
    "dlq_unfreeze":      frozenset({"maint.dlq.v1"}),
    # Phase 8 §8.8 — operator forces decimation sweep now.
    "denylist_decimate_now": frozenset({"maint.sec.v1"}),
    # Phase 8 §8.10 — broadcast pause/resume for the maintenance plane.
    # Expanded dynamically when target='all'; for fixed targets (single
    # agent id), the consumer set is just that agent.
    "maint_pause":       frozenset({"maint.scaler.v1", "maint.dlq.v1", "maint.schema.v1", "maint.sec.v1"}),
    "maint_resume":      frozenset({"maint.scaler.v1", "maint.dlq.v1", "maint.schema.v1", "maint.sec.v1"}),
    # Phase 8 §8.3 — operator-driven backup lifecycle. `backup_now`
    # and `backup_rotate_key` consumers still land later in §8.3;
    # `restore` is wired to maint.backup.v1 (operator-driven restore
    # runbook — `ops.restore`). Until the deferred two land their
    # consumer sets stay empty and KINDS_PENDING_CONSUMER_LANDING
    # below cites the upcoming phase.
    "backup_now":        frozenset(),
    "backup_rotate_key": frozenset(),
    "restore":           frozenset({"maint.backup.v1"}),
    # Phase 8 §8.7 — operator-driven pattern_allowlist lifecycle.
    # Consumer is maint.sec.v1 (FP feedback loop), which lands in
    # §8.7; until then the consumer set is empty.
    "allowlist_extend":  frozenset(),
    "allowlist_approve": frozenset(),
    "allowlist_show":    frozenset(),
    # Phase 8 §8.16.10 — operator-triggered legacy-row migration and
    # allowlist HMAC key rotation surfaces.
    "allowlist_rehash":  frozenset(),
    "allowlist_rotate_key": frozenset(),
    # Phase 10 §10.27 — NLP operator kill-pattern arm/disarm.
    "nlp_kill_pattern_armed": frozenset({"nlp.answer.v1"}),
    "nlp_kill_pattern_disarmed": frozenset({"nlp.answer.v1"}),
    # ── Notification-only kinds (Phase 8.2 + 8.5) ────────────────────
    # These are emitted BY maint reactors as side-effect telemetry.
    # They carry NO ``request_id`` (or carry one but expect no acks)
    # and are addressed to operators / dashboards over the bus, not
    # to a peer agent. Empty consumer set is intentional — see
    # ``KINDS_NOTIFICATION_ONLY`` below.
    "scale_decision":              frozenset(),
    "scale_throttled":             frozenset(),
    # Phase 8 §8.15.1 — emitted once at agent boot (resolved clock source)
    # and on each detected container-suspend event.  Notification-only;
    # no ack expected.  Action field disambiguates boot vs. suspend_detected.
    "maint_clock_source_changed":  frozenset(),
    # Phase 8 §8.14.8 — soft warm-up advisory emitted by maint.scaler.v1
    # on retrain_request; replaces scale_decision{source=retrain_request_warmup}.
    # The trainer MAY consume to pre-warm capacity; no ack expected.
    "trainer_warmup_hint":         frozenset(),
    "manual_scale_pin_expired":    frozenset(),
    # Phase 8 §8.16.1 — emitted once per process lifetime per
    # unconfigured target by maint.scaler.v1 when default-policy
    # fallback applies (operator forgot to widen
    # maint_scaler_max_replicas_overrides_csv after registering a
    # new agent). Notification-only — the operator-visible signal
    # is the paired sec.alert.v1{kind=maint_scaler_unconfigured_agent}.
    "maint_scaler_default_applied": frozenset(),
    "dlq_replayed":                frozenset(),
    "dlq_replay_policy_loaded":    frozenset(),
    "dlq_escalated":               frozenset(),
    "dlq_topic_disabled_drained":  frozenset(),
    "dlq_dropped":                 frozenset(),
    # Phase 8 §8.5 C2 — poison-pattern detection notifications.
    "dlq_consumer_broken":         frozenset(),
    "dlq_topic_unfrozen":          frozenset(),
    # ── Notification-only kinds (Phase 8.3 backup agent) ─────────────
    # Emitted by maint.backup.v1; carry a fire_window_id, expect no
    # acks. `pii_erased` carries the originating quarantine_erase
    # request_id but is itself notification-only — the operator who
    # waited for the quarantine_erase ack already got their answer.
    "backup_started":              frozenset(),
    "backup_completed":            frozenset(),
    "backup_verify_orphan_swept":  frozenset(),
    "prune_started":               frozenset(),
    "prune_completed":             frozenset(),
    "prune_skipped":               frozenset(),
    "quarantine_pruned":           frozenset(),
    "pattern_allowlist_expired":   frozenset(),
    "pii_erased":                  frozenset(),
    # ROADMAP §8.3 weekly cold-verify (silent storage rot detector).
    "backup_cold_verify_completed": frozenset(),
    "backup_cold_verify_failed":    frozenset(),
    # ROADMAP §8.3 operator-driven restore runbook (`ops.restore`).
    # Notification-only — the operator already received their
    # `maint.ack.v1` for the originating `restore` envelope.
    "backup_restore_started":       frozenset(),
    "backup_restore_completed":     frozenset(),
    # ── §8.9 / §8.3 additions (second-pass completeness) ─────────────
    # Phase 8.3 backup watchdog + key rotation + offsite.
    "backup_age_alert":             frozenset(),
    "backup_key_rotated":           frozenset(),
    "backup_offsite_uploaded":      frozenset(),
    "backup_offsite_failed":        frozenset(),
    "backup_verify_failed":         frozenset(),
    "backup_verify_key_rotated":    frozenset(),
    # Phase 8.8 sec.denylist decimate result + cap-cleared confirmation.
    "denylist_decimate":            frozenset(),
    "denylist_cap_cleared":         frozenset(),
    # Phase 8.10 pause/resume acknowledgements emitted by maint agents
    # after successfully processing the `maint_pause`/`maint_resume` cmd.
    "maint_paused":                 frozenset(),
    "maint_resumed":                frozenset(),
    # Phase 8.11 maint-plane lag watchdog tier transitions.
    "maint_plane_throttled":        frozenset(),
    "maint_plane_recovered":        frozenset(),
    # Phase 8.16 D2 dead-mans-switch notification (dual-published on both
    # sec.alert.v1 and maint.event.v1 for audit trail purposes).
    "maint_silence_alert":          frozenset(),
    # Forward-compat: unknown kinds in redelivered envelopes after a
    # downgrade drop here with a debounced audit notification.
    "maint_unknown_kind":           frozenset(),
    # Phase 8.7 pattern-allowlist lifecycle notifications from maint.sec.v1.
    "pattern_allowlist_pending":    frozenset(),
    "pattern_allowlist_added":      frozenset(),
    "pattern_allowlist_promoted":   frozenset(),
    # Phase 8 §8.16.10 — sec.input.v1 emits once-per-legacy-row
    # compatibility hits to prompt operator rehash flow.
    "pattern_allowlist_legacy_hit": frozenset(),
    # Phase 8.6 schema-sentinel / source-watcher drift notification.
    "schema_drift_detected":        frozenset(),
    # ── Phase 8 §8.13.1 model-artifact backup discipline ─────────────
    # Notification-only kinds emitted by the model-lineage / cold-mirror
    # subsystem.  None require acks — they are telemetry for operators
    # and dashboards.
    "backup_model_uploaded":             frozenset(),
    "backup_model_offsite_failed":       frozenset(),
    "backup_model_cold_verify_completed": frozenset(),
    "backup_model_cold_verify_failed":   frozenset(),
    "backup_model_lineage_legacy":       frozenset(),
    # Emitted when a live artifact under data/models/ is missing its
    # lineage sidecar or the sidecar's predictor_id/version does not
    # match the enclosing directory structure (lineage drift).
    "backup_model_lineage_drift":        frozenset(),
    # ── Phase 8 §8.13.3 spool entry aging ────────────────────────────
    # Notification-only audit event emitted by spool-flush helpers when
    # a spool entry is pruned because its age exceeds
    # cfg.maint_spool_entry_max_age_h. Carries target, request_id,
    # age_h, and the original kind of the aged-out envelope.
    "spool_entry_aged_out":              frozenset(),    # Phase 8 §8.13.3 retired-kind / schema-outdated quarantine ──────────────
    # Notification-only event emitted when a spool entry is moved to .retired/
    # because its kind is no longer in KNOWN_MAINT_EVENT_KINDS or its
    # schema_version is below cfg.swarm_min_supported_schema_version.
    "spool_entry_retired_kind":          frozenset(),
    # ── Phase 8 §8.13.7 cross-section additions ───────────────────────────────
    # Emitted during restore when the dump's manifest is in legacy format
    # (missing migration metadata from before Phase 8.13.4 revision).
    # Fall-back: skip forward-migrate, run verify.sql against the dump's
    # schema only. Notification-only (paired with severity=info restore log).
    "backup_legacy_manifest":            frozenset(),
    # Emitted when the backup-role PG password age exceeds the hard cap
    # (cfg.maint_backup_pg_secret_max_age_days). The agent refuses to start
    # until the password is rotated. Companion maint.event.v1 to the
    # sec.alert.v1{kind=backup_pg_secret_expired} that fires concurrently.
    "backup_pg_secret_expired":          frozenset(),
    # Emitted for the audit trail when an operator acknowledges a DR-key
    # compromise and revokes the compromised recipient. Carries scope, the
    # compromised recipient fingerprint, and the action taken.
    "backup_key_compromise_acknowledged": frozenset(),
    # Phase 8 §8.14.2 per-file dump checksum manifest: emitted during
    # restore-verify when the dump tarball contains no inner manifest
    # (legacy dump pre-§8.14.2). Verify proceeds with outer-checksum-only
    # detection. Notification-only (paired with severity=info restore log).
    "backup_legacy_no_file_manifest":    frozenset(),
    # Phase 8 §8.14.10 spool-flush partial-drain audit event: emitted when
    # ops.spool-flush exhausts cfg.opsctl_spool_flush_max_per_run without
    # emptying the spool directory. Notification-only; no ack expected.
    "spool_flush_partial":               frozenset(),
    # Phase 8 §8.15.4 — HMAC key lifecycle audit events.
    # Emitted by ops.revoke-key / ops.rotate-key through the
    # destructive-token gate.  Notification-only (operators observe via
    # dashboards; the originating opsctl envelope carries the ack).
    "opsctl_key_revoked":                frozenset(),
    "opsctl_key_rotated":                frozenset(),
    # Phase 8 §8.15.7 — opsctl_audit.csv hash-chain hourly verification.
    # Emitted by maint.backup.v1 once per verification cron tick.
    # Notification-only — no consumer ack expected.
    "audit_chain_verify":                frozenset(),
    # Phase 8 §8.15.10 Fix C — restore-verify forensic capture.
    # Emitted by maint.backup.v1 when a failed restore-verify writes
    # the verify_forensic.json sidecar to <date>.failed/.
    # Carries target (date string), size_bytes (file size on disk).
    # Notification-only — no consumer ack expected.
    "verify_forensic_captured":          frozenset(),
    # Phase 8 §8.16.2 — emitted by SpoolAckReconciler (inside
    # maint.dlq.v1) once all expected acks land or the
    # cfg.opsctl_spool_ack_max_wait_h deadline elapses.
    # Notification-only — dashboards/operators consume via bus;
    # no peer-agent ack expected.
    "spool_flush_acks_reconciled":       frozenset(),
    # Phase 8 §8.16.5 — multipart upload-id TTL.
    # Emitted by MultipartResumeManager when the persisted upload_id is
    # confirmed stale (either via ListParts NoSuchUpload or mtime > max_age_h).
    # Agent restarts the upload from scratch. Notification-only.
    "backup_offsite_upload_id_expired":  frozenset(),
}

# Kinds whose consumer set is empty BY DESIGN at this point in the
# Phase 8 rollout. Each entry MUST cite the phase that brings the
# consumer online; the boundary test re-asserts the citation pattern.
KINDS_PENDING_CONSUMER_LANDING: Final[Mapping[str, str]] = {
    "retrain_request":  "Phase 5.x (trainer-as-agent) + Phase 8.2 (scaler warm-up)",
    "retrain_approve":  "Phase 5.x (trainer-as-agent)",
    "backup_now":        "Phase 8.3 (maint.backup.v1)",
    "backup_rotate_key": "Phase 8.3 (maint.backup.v1)",
    "allowlist_extend":  "Phase 8.7 (maint.sec.v1 allowlist surface)",
    "allowlist_approve": "Phase 8.7 (maint.sec.v1 allowlist surface)",
    "allowlist_show":    "Phase 8.7 (maint.sec.v1 allowlist surface)",
    "allowlist_rehash":  "Phase 8.16.10 (maint.sec.v1 rehash consumer)",
    "allowlist_rotate_key": "Phase 8.16.10 (maint.sec.v1 rotation consumer)",
    # Phase 8 §8.14.8 — trainer_warmup_hint has an optional consumer
    # (the trainer pre-warm logic) that lands with Phase 5.x trainer-as-agent.
    "trainer_warmup_hint": "Phase 5.x (trainer-as-agent) pre-warm consumer",
}

# Kinds that are intentionally consumer-less because they are
# notification-only (emitted by §8.x reactors for operators /
# dashboards to observe). Distinct from KINDS_PENDING_CONSUMER_LANDING
# — these will NEVER grow a consumer; the empty set is the contract.
KINDS_NOTIFICATION_ONLY: Final[frozenset[str]] = frozenset({
    "scale_decision",
    "scale_throttled",
    "manual_scale_pin_expired",
    "maint_scaler_default_applied",
    # Phase 10 §10.27 — NLP operator kill-pattern arm/disarm are notification-only.
    "nlp_kill_pattern_armed",
    "nlp_kill_pattern_disarmed",
    # Phase 8 §8.15.1 — clock-source boot validation + suspend detection.
    "maint_clock_source_changed",
    "dlq_replayed",
    "dlq_replay_policy_loaded",
    "dlq_escalated",
    "dlq_topic_disabled_drained",
    "dlq_dropped",
    "dlq_consumer_broken",
    "dlq_topic_unfrozen",
    # Phase 8.3 backup agent.
    "backup_started",
    "backup_completed",
    "backup_verify_orphan_swept",
    "prune_started",
    "prune_completed",
    "prune_skipped",
    "quarantine_pruned",
    "pattern_allowlist_expired",
    "pattern_allowlist_legacy_hit",
    "pii_erased",
    # ROADMAP §8.3 weekly cold-verify (silent storage rot detector).
    "backup_cold_verify_completed",
    "backup_cold_verify_failed",
    # ROADMAP §8.3 operator-driven restore runbook (`ops.restore`).
    "backup_restore_started",
    "backup_restore_completed",
    # §8.9 second-pass additions (see _ACK_ROUTING_TABLE).
    "backup_age_alert",
    "backup_key_rotated",
    "backup_offsite_uploaded",
    "backup_offsite_failed",
    "backup_verify_failed",
    "backup_verify_key_rotated",
    "denylist_decimate",
    "denylist_cap_cleared",
    "maint_paused",
    "maint_resumed",
    "maint_plane_throttled",
    "maint_plane_recovered",
    "maint_silence_alert",
    "maint_unknown_kind",
    "pattern_allowlist_pending",
    "pattern_allowlist_added",
    "pattern_allowlist_promoted",
    "schema_drift_detected",
    # Phase 8 §8.13.1 model-artifact backup discipline.
    "backup_model_uploaded",
    "backup_model_offsite_failed",
    "backup_model_cold_verify_completed",
    "backup_model_cold_verify_failed",
    "backup_model_lineage_legacy",
    "backup_model_lineage_drift",
    # Phase 8 §8.13.3 spool entry aging + retired-kind quarantine.
    "spool_entry_aged_out",
    "spool_entry_retired_kind",
    # Phase 8 §8.13.7 cross-section additions.
    "backup_legacy_manifest",
    "backup_pg_secret_expired",
    "backup_key_compromise_acknowledged",
    # Phase 8 §8.14.2 per-file dump checksum manifest (legacy path).
    "backup_legacy_no_file_manifest",
    # Phase 8 §8.14.10 spool-flush partial-drain audit notification.
    # No consumer expected — notification-only event for operators/dashboards.
    "spool_flush_partial",
    # Phase 8 §8.15.4 — HMAC key lifecycle audit events.
    "opsctl_key_revoked",
    "opsctl_key_rotated",
    # Phase 8 §8.15.7 — opsctl_audit.csv hash-chain hourly verify cron.
    "audit_chain_verify",
    # Phase 8 §8.15.10 Fix C — restore-verify forensic sidecar capture.
    "verify_forensic_captured",
    # Phase 8 §8.16.2 — spool-flush ack reconciliation summary.
    # No consumer expected — the reconciler emits this as a notification
    # once all acks have landed (or deadline has elapsed). Notification-only.
    "spool_flush_acks_reconciled",
    # Phase 8 §8.16.5 — multipart upload-id TTL audit notification.
    "backup_offsite_upload_id_expired",
})

# Stable, alphabetised view of all known kinds (test imports this).
KNOWN_MAINT_EVENT_KINDS: Final[frozenset[str]] = frozenset(_ACK_ROUTING_TABLE)


def expected_ack_set(kind: str) -> frozenset[str]:
    """Return the expected `maint.ack.v1.accepted_by` set for a kind.

    Raises ``KeyError`` if the kind is unknown. Callers (the §8.1
    ops console publisher) MUST surface unknown-kind as exit code 6
    (``unknown_kind``), distinct from exit code 5
    (``no_consumer_for_kind``) which is the empty-set case.
    """
    return _ACK_ROUTING_TABLE[kind]


def is_pending_consumer_landing(kind: str) -> bool:
    """Return True iff the kind is known but its consumer set is empty
    by design (a not-yet-landed downstream agent)."""
    return kind in KINDS_PENDING_CONSUMER_LANDING


def is_notification_only(kind: str) -> bool:
    """Return True iff the kind is a notification-only event (no
    consumer set will ever be wired). Distinct from
    :func:`is_pending_consumer_landing`."""
    return kind in KINDS_NOTIFICATION_ONLY


__all__ = [
    "KNOWN_MAINT_EVENT_KINDS",
    "KINDS_PENDING_CONSUMER_LANDING",
    "KINDS_NOTIFICATION_ONLY",
    "expected_ack_set",
    "is_pending_consumer_landing",
    "is_notification_only",
]
