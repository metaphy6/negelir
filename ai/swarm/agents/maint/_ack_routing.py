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
    # Phase 8 §8.5 C2 — operator lifts a poison-pattern freeze.
    "dlq_unfreeze":      frozenset({"maint.dlq.v1"}),
    # Phase 8 §8.8 — operator forces decimation sweep now.
    "denylist_decimate_now": frozenset({"maint.sec.v1"}),
    # Phase 8 §8.10 — broadcast pause/resume for the maintenance plane.
    # Expanded dynamically when target='all'; for fixed targets (single
    # agent id), the consumer set is just that agent.
    "maint_pause":       frozenset({"maint.scaler.v1", "maint.dlq.v1", "maint.schema.v1", "maint.sec.v1"}),
    "maint_resume":      frozenset({"maint.scaler.v1", "maint.dlq.v1", "maint.schema.v1", "maint.sec.v1"}),
    # ── Notification-only kinds (Phase 8.2 + 8.5) ────────────────────
    # These are emitted BY maint reactors as side-effect telemetry.
    # They carry NO ``request_id`` (or carry one but expect no acks)
    # and are addressed to operators / dashboards over the bus, not
    # to a peer agent. Empty consumer set is intentional — see
    # ``KINDS_NOTIFICATION_ONLY`` below.
    "scale_decision":              frozenset(),
    "scale_throttled":             frozenset(),
    "manual_scale_pin_expired":    frozenset(),
    # Phase 8 §8.16.1 — emitted once per process lifetime per
    # unconfigured target by maint.scaler.v1 when default-policy
    # fallback applies (operator forgot to widen
    # maint_scaler_max_replicas_overrides_csv after registering a
    # new agent). Notification-only — the operator-visible signal
    # is the paired sec.alert.v1{kind=maint_scaler_unconfigured_agent}.
    "maint_scaler_default_applied": frozenset(),
    "dlq_replayed":                frozenset(),
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
    "pii_erased":                  frozenset(),
}

# Kinds whose consumer set is empty BY DESIGN at this point in the
# Phase 8 rollout. Each entry MUST cite the phase that brings the
# consumer online; the boundary test re-asserts the citation pattern.
KINDS_PENDING_CONSUMER_LANDING: Final[Mapping[str, str]] = {
    "retrain_request":  "Phase 5.x (trainer-as-agent) + Phase 8.2 (scaler warm-up)",
    "retrain_approve":  "Phase 5.x (trainer-as-agent)",
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
    "dlq_replayed",
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
    "pii_erased",
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
