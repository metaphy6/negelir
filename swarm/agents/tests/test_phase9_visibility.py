"""Phase 9 §9.13 DoD bullet 5 — swarmctl topics visibility + wire-authority.

Proves two invariants that satisfy the DoD requirement
"`swarmctl topics` shows `api.request.v1`, `api.response.v1`,
`predict.cancel.v1` with the correct producers":

1. **Schema-layer visibility** — all three Phase 9 gateway topics are
   registered in ``ai/swarm/sdk/schemas/`` (i.e. ``known_topics()``
   returns them).  This is the proxy for "swarmctl topics would show
   them on a live system": ``swarmctl topics`` enumerates Redis stream
   keys via SCAN, so a topic appears once the gateway has published its
   first message; the JSON Schema registration is the pre-publish
   declaration that ties the stream name to the wire contract.

2. **Wire-authority producer pins** — both the Phase 9 ``API_TOPIC_V1``
   constant and the new ``PREDICT_CANCEL_V1_ALLOWED_PRODUCERS`` constant
   in ``ai/swarm/sdk/wire_contracts.py`` pin ``api.gateway.v1`` as the
   sole permitted producer.  This matches the Go-side static map in
   ``server/cmd/swarmctl/main.go`` (``wireAuthorityProducers``), which
   is the data source for the PRODUCER column that swarmctl topics now
   prints.

The Go-side companion test is in
``server/cmd/swarmctl/main_test.go::TestWireAuthorityPhase9Topics``.
"""
from __future__ import annotations

import pytest

from swarm.agents.topics import API_REQUEST_V1, API_RESPONSE_V1, PREDICT_CANCEL_V1
from swarm.sdk.wire_contracts import (
    API_TOPIC_V1_ALLOWED_PRODUCERS,
    PREDICT_CANCEL_V1_ALLOWED_PRODUCERS,
)


# ── 1. Schema-layer visibility ────────────────────────────────────────────


_PHASE9_GATEWAY_TOPICS = frozenset({
    str(API_REQUEST_V1),
    str(API_RESPONSE_V1),
    str(PREDICT_CANCEL_V1),
})


def test_phase9_gateway_topics_in_schema_layer() -> None:
    """Every Phase 9 gateway topic has a registered JSON schema.

    ``swarmctl topics`` enumerates stream keys via Redis SCAN.  The
    JSON schema registration is the *static* declaration that a topic
    exists; the stream itself is created lazily on first ``XADD``.
    After this test passes, the Go swarmctl ``cmdTopics`` function will
    merge wire-authority topics into its output even before the gateway
    has published — which is how ``swarmctl topics`` can always show
    the three topics with their PRODUCER column.
    """
    from swarm.sdk.schemas import known_topics  # local import for resilience

    known = frozenset(known_topics())
    missing = _PHASE9_GATEWAY_TOPICS - known
    assert not missing, (
        "Phase 9 gateway topics missing from SDK schema layer "
        f"(ai/swarm/sdk/schemas/): {sorted(missing)}. "
        "Each topic requires a <topic>.json schema file for "
        "swarmctl to enumerate it and for live-emission validators "
        "to accept publications."
    )


@pytest.mark.parametrize("topic_name", sorted(_PHASE9_GATEWAY_TOPICS))
def test_phase9_gateway_topic_schema_loadable(topic_name: str) -> None:
    """Each Phase 9 gateway topic schema loads without error."""
    from swarm.sdk.schemas import load  # local import for resilience

    schema = load(topic_name)
    assert schema.get("title") == topic_name, (
        f"Schema for {topic_name!r} has unexpected title "
        f"{schema.get('title')!r}; expected {topic_name!r}."
    )


# ── 2. Wire-authority producer pins ──────────────────────────────────────


def test_api_topic_v1_allowed_producers_pin() -> None:
    """``API_TOPIC_V1_ALLOWED_PRODUCERS`` is exactly ``{api.gateway.v1}``.

    Mirrors ``test_api_topic_v1_allowed_producers_constant`` in
    ``test_boundary_discipline.py`` — the single-source constant lives
    in ``wire_contracts.py`` and BOTH tests import it, so they stay
    in sync automatically.  This test lives here so the Phase 9
    visibility suite is self-contained.
    """
    assert API_TOPIC_V1_ALLOWED_PRODUCERS == frozenset({"api.gateway.v1"}), (
        "API_TOPIC_V1_ALLOWED_PRODUCERS must be exactly "
        "{'api.gateway.v1'} (Phase 9 §9.0 wire-authority). "
        f"Actual: {sorted(API_TOPIC_V1_ALLOWED_PRODUCERS)}"
    )


def test_predict_cancel_v1_allowed_producers_pin() -> None:
    """``PREDICT_CANCEL_V1_ALLOWED_PRODUCERS`` is exactly ``{api.gateway.v1}``.

    ``predict.cancel.v1`` is a Phase 9 §9.5 addition.  The schema
    description already states "Producer set bounded to api.gateway.v1";
    this test locks the Python wire-authority constant to match.
    The Go-side equivalent is ``wireAuthorityProducers["predict.cancel.v1"]``
    in ``server/cmd/swarmctl/main.go``, verified by
    ``TestWireAuthorityPhase9Topics``.
    """
    assert PREDICT_CANCEL_V1_ALLOWED_PRODUCERS == frozenset({"api.gateway.v1"}), (
        "PREDICT_CANCEL_V1_ALLOWED_PRODUCERS must be exactly "
        "{'api.gateway.v1'} (Phase 9 §9.5 wire-authority). "
        f"Actual: {sorted(PREDICT_CANCEL_V1_ALLOWED_PRODUCERS)}"
    )


def test_all_phase9_gateway_topics_have_same_producer() -> None:
    """All three Phase 9 gateway topics share a single allowed producer.

    This is a convenience check that catches copy-paste errors — if
    one topic's constant is accidentally set to a different producer,
    this test surfaces it alongside the per-topic pins above.
    """
    assert (
        API_TOPIC_V1_ALLOWED_PRODUCERS
        == PREDICT_CANCEL_V1_ALLOWED_PRODUCERS
        == frozenset({"api.gateway.v1"})
    ), (
        "All three Phase 9 gateway topics must have the same sole "
        "producer: api.gateway.v1. Check API_TOPIC_V1_ALLOWED_PRODUCERS "
        "and PREDICT_CANCEL_V1_ALLOWED_PRODUCERS in wire_contracts.py."
    )


# ── 3. No swarm agent publishes any gateway topic ─────────────────────────


def _registry_agents() -> tuple[object, ...]:
    """Canonical agent set from ``bootstrap.build_agents()``."""
    from swarm.bootstrap import build_agents  # local import

    return tuple(build_agents())


@pytest.mark.parametrize("topic", sorted(_PHASE9_GATEWAY_TOPICS))
def test_no_swarm_agent_publishes_gateway_topic(topic: str) -> None:
    """No in-process swarm agent may publish any Phase 9 gateway topic.

    The sole producer for all three topics is ``api.gateway.v1`` (the
    Go gateway process).  This enumerative registry scan catches any
    future agent class that accidentally wires a gateway audit topic
    into its publish set.
    """
    from swarm.sdk.types import Topic  # local import

    topic_obj = Topic(topic)
    offenders: list[str] = []
    for agent in _registry_agents():
        if topic_obj in tuple(getattr(agent, "publishes", ())):
            offenders.append(getattr(agent, "name", agent.__class__.__name__))
    assert offenders == [], (
        f"{topic} may only be published by api.gateway.v1 (Go). "
        "No Python swarm agent may publish here. "
        f"In-registry violators: {offenders}."
    )
