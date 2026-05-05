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
    # Phase 7 §7.1 / Phase 8 §8.3 — storage.v1 owns quarantine_samples.
    "quarantine_erase":  frozenset({"storage.v1"}),
    # Phase 8 §8.7 — FP feedback loop. The maint.sec.v1 reactor lands
    # in §8.7; until then it routes to empty (boundary test asserts
    # intent via KINDS_PENDING_CONSUMER_LANDING).
    "quarantine_clear":  frozenset(),
}

# Kinds whose consumer set is empty BY DESIGN at this point in the
# Phase 8 rollout. Each entry MUST cite the phase that brings the
# consumer online; the boundary test re-asserts the citation pattern.
KINDS_PENDING_CONSUMER_LANDING: Final[Mapping[str, str]] = {
    "retrain_request":  "Phase 5.x (trainer-as-agent) + Phase 8.2 (scaler warm-up)",
    "retrain_approve":  "Phase 5.x (trainer-as-agent)",
    "quarantine_clear": "Phase 8.7 (maint.sec.v1 FP feedback loop)",
}

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


__all__ = [
    "KNOWN_MAINT_EVENT_KINDS",
    "KINDS_PENDING_CONSUMER_LANDING",
    "expected_ack_set",
    "is_pending_consumer_landing",
]
