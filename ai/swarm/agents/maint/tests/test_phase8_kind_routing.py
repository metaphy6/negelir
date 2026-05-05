"""Phase 8 §8.0 — wire-contract tests for `maint.event.v1{kind=...}` and
`maint.ack.v1`.

What this asserts (boundary discipline):

1. Every kind in ``swarm.agents.maint._ack_routing.KNOWN_MAINT_EVENT_KINDS``
   has a matching ``ai/swarm/sdk/schemas/maint.event.v1/<kind>.json``
   sub-schema, and every sub-schema file has a matching routing entry
   (orphans on either side fail loudly — no silent drift).
2. Every kind whose consumer set is empty is listed in
   ``KINDS_PENDING_CONSUMER_LANDING`` with a citation. This forces a
   conscious decision rather than "oops I forgot the consumer".
3. ``schemas.validate_kind("maint.event.v1", payload)`` accepts a
   well-formed payload for each kind and rejects (a) missing
   discriminator, (b) unknown kind, (c) wrong ``kind`` const, (d)
   missing required fields, (e) unknown extra fields.
4. ``MaintAck`` round-trips through ``schemas.validate("maint.ack.v1",
   ack.as_dict())`` cleanly and rejects malformed inputs at the
   dataclass layer.
5. The ``MAINT_ACK`` topic constant exists and is exported.
"""
from __future__ import annotations

import pytest

from ai.swarm.agents.maint import (
    KINDS_PENDING_CONSUMER_LANDING,
    KNOWN_MAINT_EVENT_KINDS,
    expected_ack_set,
    is_pending_consumer_landing,
)
from ai.swarm.agents.payloads import MaintAck
from ai.swarm.agents.topics import MAINT_ACK, MAINT_EVENT
from ai.swarm.sdk import schemas


# ── Routing ↔ sub-schema symmetry ───────────────────────────────────────


def test_routing_table_matches_sub_schema_directory() -> None:
    """Every kind in the routing table has a sub-schema file, and vice
    versa. Orphans on either side fail CI."""
    schema_kinds = set(schemas.known_kinds(MAINT_EVENT))
    routing_kinds = set(KNOWN_MAINT_EVENT_KINDS)
    missing_in_schema = routing_kinds - schema_kinds
    missing_in_routing = schema_kinds - routing_kinds
    assert not missing_in_schema, (
        f"kinds in _ack_routing without a sub-schema: {sorted(missing_in_schema)}"
    )
    assert not missing_in_routing, (
        f"sub-schema files without a routing entry: {sorted(missing_in_routing)}"
    )


def test_maint_event_is_kind_discriminated() -> None:
    assert MAINT_EVENT in schemas.kind_discriminated_topics()


def test_empty_consumer_sets_are_listed_pending() -> None:
    """Empty consumer-set kinds MUST be listed in
    KINDS_PENDING_CONSUMER_LANDING with a citation. This catches the
    "forgot to wire the consumer" footgun: the only legitimate way to
    have an empty set is to declare the consumer is not yet built."""
    for kind in KNOWN_MAINT_EVENT_KINDS:
        if not expected_ack_set(kind):
            assert is_pending_consumer_landing(kind), (
                f"kind={kind!r} routes to empty consumer set but is NOT "
                "listed in KINDS_PENDING_CONSUMER_LANDING — either wire "
                "a consumer or add a citation explaining why it is "
                "intentionally empty"
            )
            citation = KINDS_PENDING_CONSUMER_LANDING[kind]
            assert "Phase" in citation, (
                f"kind={kind!r} pending citation must reference a Phase "
                f"(got {citation!r})"
            )


def test_pending_kinds_are_known() -> None:
    """KINDS_PENDING_CONSUMER_LANDING entries must reference real kinds."""
    for kind in KINDS_PENDING_CONSUMER_LANDING:
        assert kind in KNOWN_MAINT_EVENT_KINDS, (
            f"KINDS_PENDING_CONSUMER_LANDING references unknown kind={kind!r}"
        )


def test_consumer_set_values_are_frozenset() -> None:
    """Routing values must be immutable to prevent accidental mutation
    by consumer-side code that gets a reference."""
    for kind in KNOWN_MAINT_EVENT_KINDS:
        consumers = expected_ack_set(kind)
        assert isinstance(consumers, frozenset), (
            f"kind={kind!r} consumer set is {type(consumers).__name__}, "
            "expected frozenset"
        )


def test_expected_ack_set_raises_on_unknown_kind() -> None:
    with pytest.raises(KeyError):
        expected_ack_set("does_not_exist")


# ── Per-kind sub-schema validation ──────────────────────────────────────


_GOOD_PAYLOADS: dict[str, dict[str, object]] = {
    "retrain_request": {
        "kind": "retrain_request",
        "target": "pred.elo.v1",
        "reason": "brier_floor",
        "request_id": "req-001",
    },
    "retrain_approve": {
        "kind": "retrain_approve",
        "target": "pred.elo.v1",
        "request_id": "req-002",
        "client_id": "ops@host",
        "produced_at": "2025-01-01T00:00:00Z",
    },
    "denylist_clear": {
        "kind": "denylist_clear",
        "target": "ip:9.9.9.9",
        "request_id": "req-003",
        "client_id": "ops@host",
        "produced_at": "2025-01-01T00:00:00Z",
    },
    "baseline_reset": {
        "kind": "baseline_reset",
        "target": "mackolik",
        "request_id": "req-004",
        "client_id": "ops@host",
        "produced_at": "2025-01-01T00:00:00Z",
    },
    "quarantine_erase": {
        "kind": "quarantine_erase",
        "target": "user-42",
        "request_id": "req-005",
        "client_id": "ops@host",
        "produced_at": "2025-01-01T00:00:00Z",
    },
    "quarantine_clear": {
        "kind": "quarantine_clear",
        "target": "qid-7",
        "request_id": "req-006",
        "client_id": "ops@host",
        "produced_at": "2025-01-01T00:00:00Z",
    },
}


@pytest.mark.parametrize("kind", sorted(KNOWN_MAINT_EVENT_KINDS))
def test_each_kind_has_a_validating_payload(kind: str) -> None:
    """Each routed kind must be exercisable by a well-formed payload —
    catches sub-schema fields that drift from `_GOOD_PAYLOADS` here."""
    assert kind in _GOOD_PAYLOADS, (
        f"add a representative payload for kind={kind!r} to _GOOD_PAYLOADS"
    )
    errors = schemas.validate_kind(MAINT_EVENT, _GOOD_PAYLOADS[kind])
    assert errors == [], f"kind={kind!r} payload rejected: {errors}"


def test_validate_kind_rejects_missing_discriminator() -> None:
    errors = schemas.validate_kind(MAINT_EVENT, {"target": "x"})
    assert errors and "kind" in errors[0]


def test_validate_kind_rejects_unknown_kind() -> None:
    errors = schemas.validate_kind(
        MAINT_EVENT, {"kind": "does_not_exist", "target": "x"}
    )
    assert errors and "no per-kind sub-schema" in errors[0]


def test_validate_kind_rejects_wrong_const_kind() -> None:
    """A payload that loads the retrain_request sub-schema but carries a
    different `kind` value must fail the const check."""
    bad = dict(_GOOD_PAYLOADS["retrain_request"])
    bad["kind"] = "denylist_clear"  # routes to denylist_clear sub-schema
    errors = schemas.validate_kind(MAINT_EVENT, bad)
    # Goes to denylist_clear sub-schema, which requires client_id +
    # produced_at — those will be flagged. The point is: it does NOT
    # validate against retrain_request just because the other fields
    # match retrain_request's shape.
    assert errors


def test_validate_kind_rejects_missing_required_field() -> None:
    bad = dict(_GOOD_PAYLOADS["denylist_clear"])
    del bad["client_id"]
    errors = schemas.validate_kind(MAINT_EVENT, bad)
    assert any("client_id" in e for e in errors), errors


def test_validate_kind_rejects_unknown_extra_field() -> None:
    bad = dict(_GOOD_PAYLOADS["baseline_reset"])
    bad["secret_backdoor"] = "nope"
    errors = schemas.validate_kind(MAINT_EVENT, bad)
    assert any("secret_backdoor" in e for e in errors), errors


def test_retrain_request_reason_enum_enforced() -> None:
    bad = dict(_GOOD_PAYLOADS["retrain_request"])
    bad["reason"] = "vibes"
    errors = schemas.validate_kind(MAINT_EVENT, bad)
    assert any("enum" in e for e in errors), errors


# ── MaintAck dataclass + schema parity ──────────────────────────────────


def test_maint_ack_topic_exported() -> None:
    assert MAINT_ACK == "maint.ack.v1"
    assert MAINT_ACK in schemas.known_topics()


def test_maint_ack_round_trip_validates() -> None:
    ack = MaintAck(
        request_id="req-001",
        accepted=True,
        accepted_by="sec.rate.v1",
        processed_at="2025-01-01T00:00:00Z",
        attempt=1,
    )
    payload = ack.as_dict()
    errors = schemas.validate(MAINT_ACK, payload)
    assert errors == [], errors
    restored = MaintAck.from_dict(payload)
    assert restored == ack


def test_maint_ack_with_optionals_round_trips() -> None:
    ack = MaintAck(
        request_id="req-002",
        accepted=False,
        accepted_by="storage.v1",
        processed_at="2025-01-01T00:00:00Z",
        attempt=2,
        reason="schema_mismatch",
        details={"missing_key": "client_id"},
    )
    payload = ack.as_dict()
    assert payload["reason"] == "schema_mismatch"
    assert payload["details"] == {"missing_key": "client_id"}
    assert schemas.validate(MAINT_ACK, payload) == []
    assert MaintAck.from_dict(payload) == ack


def test_maint_ack_rejects_blank_request_id() -> None:
    with pytest.raises(ValueError, match="request_id"):
        MaintAck(
            request_id="",
            accepted=True,
            accepted_by="sec.rate.v1",
            processed_at="2025-01-01T00:00:00Z",
        )


def test_maint_ack_rejects_zero_attempt() -> None:
    with pytest.raises(ValueError, match="attempt"):
        MaintAck(
            request_id="req-x",
            accepted=True,
            accepted_by="sec.rate.v1",
            processed_at="2025-01-01T00:00:00Z",
            attempt=0,
        )


def test_maint_ack_omits_unset_optionals_from_wire() -> None:
    """Empty `reason` and None `details` must NOT appear on the wire —
    keeps payloads tight against the cfg.maint_ack_payload_max_bytes
    cap that lands in §8.1."""
    ack = MaintAck(
        request_id="req-001",
        accepted=True,
        accepted_by="sec.rate.v1",
        processed_at="2025-01-01T00:00:00Z",
    )
    payload = ack.as_dict()
    assert "reason" not in payload
    assert "details" not in payload
