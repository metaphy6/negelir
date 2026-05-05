"""Phase 8 §8.x — self-maintenance reactors (`swarm.agents.maint.*`).

This package holds the Phase 8 maint plane reactors plus the central
``_ack_routing.py`` map (kind → expected-consumer-set). Per ROADMAP
§8 placement note, the transitional path is ``ai/swarm/agents/maint/``
until the R2 ``git mv`` to ``swarm/reactors/maint/``.

Phase 8.0 ships the contract scaffolding only (no reactors yet):
* ``_ack_routing.py`` — kind → consumer-set map.
* Per-kind sub-schemas under ``ai/swarm/sdk/schemas/maint.event.v1/``.
* ``maint.ack.v1.json`` schema (new topic; §3.5 wire-authority grows
  by exactly one row at the §8.1 ops console landing).

Subsequent §8.x slices add one reactor each.
"""
from __future__ import annotations

from ._ack_routing import (
    KINDS_NOTIFICATION_ONLY,
    KINDS_PENDING_CONSUMER_LANDING,
    KNOWN_MAINT_EVENT_KINDS,
    expected_ack_set,
    is_notification_only,
    is_pending_consumer_landing,
)

__all__ = [
    "KNOWN_MAINT_EVENT_KINDS",
    "KINDS_PENDING_CONSUMER_LANDING",
    "KINDS_NOTIFICATION_ONLY",
    "expected_ack_set",
    "is_pending_consumer_landing",
    "is_notification_only",
]
