"""Cross-component wire-contract allow-lists.

The Phase 6 §6.4 boundary test originally asserted that
``maint.event.v1`` had ``producers == {drift.v1}``. Phase 7 §7.3
expands the producer set to include ``ops_console`` (the Phase 8
maint surface) so operators can clear denylists, reset upstream
baselines, etc. via the same envelope. The contract change belongs
to whichever phase first needs the second producer — that's Phase 7
via the §7.3 consumer hook on ``sec.rate.v1``.

This module is the single source of truth for that allow-list (and
any future cross-component allow-list of the same shape). The
boundary tests import the constant; the producers do NOT — producer
identity is enforced by AST scan over Python source + the agent
``publishes`` declaration, not at runtime (matches the open-enum
producer-side discipline pattern).

Doctrine: append-only. Adding a producer is a minor bump on the
``swarm`` component; never silently widen the set. Removing a
producer requires a migration plan because some consumer is almost
certainly depending on the producer's emissions.
"""
from __future__ import annotations

from typing import FrozenSet


# `maint.event.v1` producers (ROADMAP §7.3 cross-phase note).
#
# Members:
#   * ``drift.v1`` — Phase 6.3, kind=retrain_request when a rolling
#     Brier / log-loss / KS-test trips.
#   * ``ops_console`` — Phase 8 maint surface. Operators send
#     ``kind=denylist_clear`` (Phase 7.3 consumer: ``sec.rate.v1``)
#     and ``kind=baseline_reset`` (Phase 7.2 consumer:
#     ``sec.scrape.v1``). The ``ops_console`` name is the
#     `producer` field on the envelope; there is no Python agent
#     class with this name (humans publish via a CLI).
#
# Future additions land here with a tracker row + minor bump. The
# boundary test in ``test_boundary_discipline.py`` asserts producers
# in production code are a subset of this set.
MAINT_EVENT_V1_ALLOWED_PRODUCERS: FrozenSet[str] = frozenset({
    "drift.v1",
    "ops_console",
    # Phase 8 self-maintenance reactors. Each emits notifications on
    # `maint.event.v1` (the bus's "maintenance happened" channel):
    #   * ``maint.scaler.v1``  — scale_decision / scale_throttled /
    #                            manual_scale_pin_expired
    #   * ``maint.dlq.v1``      — dlq_replayed (and dlq_replay_throttled)
    #   * ``maint.schema.v1``   — schema_drift_detected
    #   * ``maint.sec.v1``      — pattern_allowlist_pending /
    #                             pattern_allowlist_added /
    #                             pattern_allowlist_expired /
    #                             denylist_decimate / denylist_cap_cleared
    #   * ``source.watcher.v1`` — schema_drift_detected (source-side)
    "maint.scaler.v1",
    "maint.dlq.v1",
    "maint.schema.v1",
    "maint.sec.v1",
    "source.watcher.v1",
})


# `sec.config.v1` producers (ROADMAP §7.1 cross-pod fan-out).
#
# Members:
#   * ``sec.input.v1`` — emits when its mtime poller detects a
#     local change, so sibling replicas re-read the file
#     immediately rather than waiting for their own poll tick.
#   * ``sec.scrape.v1`` — same pattern for the (future) scrape-side
#     allowlist; reserved so the agent can join the producer set
#     without a separate doctrine rev.
#   * ``ops_console`` — Phase 8 maint surface. Operators publish
#     when they edit the YAML out-of-band (e.g. via a sealed
#     ConfigMap rotation); the announcement triggers immediate
#     reload across all sec.input.v1 / gateway replicas.
#
# Doctrine: append-only. Adding a producer is a minor bump on
# `swarm`. Consumers tolerate unknown producers (the sha256 is the
# contract); the allow-list is the AST-scan boundary test.
SEC_CONFIG_V1_ALLOWED_PRODUCERS: FrozenSet[str] = frozenset({
    "sec.input.v1",
    "sec.scrape.v1",
    "ops_console",
})


__all__ = [
    "MAINT_EVENT_V1_ALLOWED_PRODUCERS",
    "SEC_CONFIG_V1_ALLOWED_PRODUCERS",
]
