"""Phase 7 §7.4 — Open-enum registry and helpers.

Closed JSON Schema enums break older consumers when a new value lands;
Negelir's wire contract uses an *open enum* pattern (per ROADMAP §7.4):

    {"kind": {"type": "string",
              "pattern": "^[a-z][a-z0-9_]{0,63}$",
              "x-enum-open": true}}

Producers MUST emit only known values; consumers MUST tolerate unknown
values and route by a sibling discriminator (e.g. `severity`). The
JSON Schema validator only enforces `pattern` (the `x-enum-open` marker
is non-standard and is silently ignored — that is by design). The
test pair below is what actually keeps producers honest:

  (a) ``test_open_enum_producers_emit_only_known_kinds`` — AST scan over
      production source, every emission-site literal must be in the
      registered known-set. Catches typos at landing time; the wire
      validator will not.

  (b) ``test_open_enum_consumers_accept_unknown_kind`` — round-trips a
      payload with a synthetic future kind through ``validate(...)``
      and asserts no rejection.

This module is the **registry**. Open enums register here once; the
two contract tests parametrize over the registry so adding a new
open enum (e.g. Phase 8 will add ``MaintEventKind`` once the
producer set expands per §7.5) requires only a one-line append, not a
new test file.

The Phase 7 producer-side AST scan currently lives in
``ai/swarm/agents/tests/test_phase7_open_enum.py`` (it predates this
helper). When Phase 8 introduces the second open enum, that test
will be rewritten to consume ``OPEN_ENUM_REGISTRY`` directly so the
two enums share a single parametrized contract test.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import FrozenSet

# Producer-side shape: kebab-snake, ASCII lower, length 1..64. This is
# the ONLY structural constraint the wire validator enforces (see
# `_validate_kind_pattern` callers in this package). Cardinality is
# bounded by length cap; log-injection is bounded by ASCII-alnum-only.
KIND_PATTERN: str = r"^[a-z][a-z0-9_]{0,63}$"
KIND_RE = re.compile(KIND_PATTERN)


@dataclass(frozen=True)
class OpenEnum:
    """One registered open-enum field.

    Attributes:
        topic: Wire schema id (e.g. "sec.alert.v1") — joins the
            JSON Schema this enum lives in.
        field: Dotted path inside the payload (e.g. "kind"). For
            nested fields, dots separate (e.g. "metadata.kind").
        known: Frozenset of producer-allowed values. Producers must
            only emit these literals; consumers must tolerate any
            string matching ``KIND_PATTERN``.
        owner_module: Dotted Python module that owns the frozen-set
            definition. The contract test re-imports the set from
            here at run-time so a mid-flight rename of the set does
            not silently leak past the gate.
    """

    topic: str
    field: str
    known: FrozenSet[str]
    owner_module: str


# ── Phase 7 registry ─────────────────────────────────────────────────
# Append here when a new open enum lands. The contract tests will
# pick it up automatically.
from ai.swarm.agents.payloads import KNOWN_SEC_ALERT_KINDS as _SEC_ALERT_KINDS
from ai.swarm.agents.maint._ack_routing import KNOWN_MAINT_EVENT_KINDS as _MAINT_EVENT_KINDS

OPEN_ENUM_REGISTRY: tuple[OpenEnum, ...] = (
    OpenEnum(
        topic="sec.alert.v1",
        field="kind",
        known=_SEC_ALERT_KINDS,
        owner_module="swarm.agents.payloads:KNOWN_SEC_ALERT_KINDS",
    ),
    # Phase 8 §8.9: maint.event.v1.kind open-enum. The known-kinds
    # set is KNOWN_MAINT_EVENT_KINDS (= frozenset(_ACK_ROUTING_TABLE))
    # so adding a new maint kind is a single-file change in _ack_routing.py.
    OpenEnum(
        topic="maint.event.v1",
        field="kind",
        known=_MAINT_EVENT_KINDS,
        owner_module="swarm.agents.maint._ack_routing:KNOWN_MAINT_EVENT_KINDS",
    ),
)


__all__ = ["KIND_PATTERN", "KIND_RE", "OpenEnum", "OPEN_ENUM_REGISTRY"]
