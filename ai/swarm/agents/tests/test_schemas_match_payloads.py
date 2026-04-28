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


from swarm.sdk.schemas import validate


_CASES: list[tuple[str, dict]] = [
    ("scrape.request", _example_scrape_request()),
    ("scrape.raw", _example_scrape_raw()),
    ("scrape.classified", _example_scrape_classified()),
    ("match.normalized", _example_normalized()),
    ("match.stored", _example_match_stored()),
    ("freshness.events.v1", _example_freshness()),
]


@pytest.mark.parametrize("topic,payload", _CASES, ids=[t for t, _ in _CASES])
def test_dataclass_payload_satisfies_schema(topic: str, payload: dict) -> None:
    errors = validate(topic, payload)
    assert not errors, f"{topic}: schema drift detected:\n  " + "\n  ".join(errors)
