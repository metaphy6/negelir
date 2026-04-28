"""Cross-phase regression: payload dataclasses must not drift from the
JSON Schemas that document the bus wire contract (ROADMAP §3.5).

Phase 4 surfaced the wire dataclasses in `ai/swarm/agents/payloads.py`;
Phase 3 mandates one JSON Schema per topic in
`ai/swarm/sdk/schemas/<topic>.json`. The third-pass audit found six
silent drifts (renamed keys, wrong scalar types, missing required
fields). This test exists to keep them honest.
"""
from __future__ import annotations

import pytest

from swarm.agents.payloads import (
    FreshnessEvent,
    MatchStored,
    NormalizedRecord,
    ScrapeClassified,
    ScrapeRaw,
    ScrapeRequest,
)
from swarm.sdk.schemas import load


def _example_scrape_request() -> dict:
    return ScrapeRequest(
        source="mackolik",
        target="/fixtures",
        league_id="tr_super_lig",
        competition_id=None,
        requested_at="2026-04-28T12:00:00+00:00",
        metadata={"priority": 1},
    ).as_dict()


def _example_scrape_raw() -> dict:
    return ScrapeRaw(
        source="mackolik",
        target="/fixtures",
        bytes_sha256="0" * 64,
        http_status=200,
        content_type="text/html",
        bytes_b64="",
        bytes_ref="",
        league_id="tr_super_lig",
        competition_id=None,
        fetched_at="2026-04-28T12:00:00+00:00",
    ).as_dict()


def _example_scrape_classified() -> dict:
    return ScrapeClassified(
        raw=ScrapeRaw.from_dict(_example_scrape_raw()),
        label="fixture_list",
        confidence=0.9,
        classifier_id="rules.v1",
    ).as_dict()


def _example_normalized() -> dict:
    return NormalizedRecord(
        record_type="fixture",
        plane="schedule",
        source="mackolik",
        source_match_id="m1",
        stable_id="abcdef0123456789",
        extractor_version="phase4.v1",
        payload={"home_team": "GS", "away_team": "FB"},
        captured_at="2026-04-28T12:00:00+00:00",
    ).as_dict()


def _example_match_stored() -> dict:
    return MatchStored(
        record_id=1,
        record_type="fixture",
        plane="schedule",
        source="mackolik",
        stable_id="abcdef0123456789",
        change_kind="created",
        stored_at="2026-04-28T12:00:00+00:00",
    ).as_dict()


def _example_freshness() -> dict:
    return FreshnessEvent(
        event_id="abc123" * 6,
        record_id=1,
        source="mackolik",
        stable_id="abcdef0123456789",
        record_type="fixture",
        plane="schedule",
        change_kind="updated",
        diff={"score": [None, "1-0"]},
        emitted_at="2026-04-28T12:00:00+00:00",
    ).as_dict()


_CASES: list[tuple[str, dict]] = [
    ("scrape.request", _example_scrape_request()),
    ("scrape.raw", _example_scrape_raw()),
    ("scrape.classified", _example_scrape_classified()),
    ("match.normalized", _example_normalized()),
    ("match.stored", _example_match_stored()),
    ("freshness.events.v1", _example_freshness()),
]


_PYTHON_TYPE_MAP: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
    "object": (dict,),
    "array": (list, tuple),
    "null": (type(None),),
}


def _accepts(spec: dict, value) -> bool:
    """Loose JSON-Schema type check sufficient to catch wire drift."""
    types = spec.get("type")
    if types is None:
        return True
    if isinstance(types, str):
        types = [types]
    if value is None:
        return "null" in types
    for t in types:
        if isinstance(value, _PYTHON_TYPE_MAP.get(t, ())):
            # Reject `bool` matching `integer` (Python quirk).
            if t == "integer" and isinstance(value, bool):
                continue
            return True
    return False


@pytest.mark.parametrize("topic,payload", _CASES, ids=[t for t, _ in _CASES])
def test_dataclass_payload_satisfies_schema(topic: str, payload: dict) -> None:
    schema = load(topic)
    required: list[str] = list(schema.get("required", []))
    properties: dict = dict(schema.get("properties", {}))
    additional = schema.get("additionalProperties", True)

    missing = [k for k in required if k not in payload]
    assert not missing, (
        f"{topic}: payload missing schema-required keys: {missing}"
    )

    if additional is False:
        unknown = [k for k in payload if k not in properties]
        assert not unknown, (
            f"{topic}: payload has keys not declared in schema "
            f"(additionalProperties=false): {unknown}"
        )

    for key, value in payload.items():
        if key not in properties:
            continue
        spec = properties[key]
        # Skip $ref-only properties (validated transitively elsewhere).
        if "$ref" in spec and "type" not in spec:
            continue
        assert _accepts(spec, value), (
            f"{topic}.{key}: value {value!r} does not satisfy schema "
            f"type={spec.get('type')!r}"
        )
        enum = spec.get("enum")
        if enum is not None and value is not None:
            assert value in enum, (
                f"{topic}.{key}: value {value!r} not in declared enum {enum}"
            )
