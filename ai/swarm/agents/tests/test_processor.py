"""Tests for Phase 4.3 processor agents."""
from __future__ import annotations

import base64
import json

import pytest

from swarm.agents.payloads import NormalizedRecord, ScrapeClassified, ScrapeRaw
from swarm.agents.processor import (
    EXTRACTOR_VERSION,
    FixtureProcessorAgent,
    LineupProcessorAgent,
    MatchDetailProcessorAgent,
    OddsProcessorAgent,
)
from swarm.agents.topics import MATCH_NORMALIZED, PROOF_FLAG
from swarm.sdk.types import Message


def _classified_msg(label: str, body: bytes, *, content_type: str = "text/html") -> Message:
    raw = ScrapeRaw(
        source="openfootball",
        target=f"/{label}",
        bytes_sha256="0" * 64,
        http_status=200,
        content_type=content_type,
        bytes_b64=base64.b64encode(body).decode("ascii"),
    )
    payload = ScrapeClassified(raw=raw, label=label, confidence=0.9, classifier_id="rules.v1")
    return Message.new("scrape.classified", payload.as_dict(), producer="test")


def test_fixture_processor_handles_openfootball_json() -> None:
    data = {"name": "TR", "matches": [
        {"date": "2024-08-10", "team1": "Galatasaray", "team2": "Fenerbahçe"},
        {"date": "2024-08-11", "team1": "Beşiktaş", "team2": "Trabzonspor"},
    ]}
    msg = _classified_msg(
        "fixture_list", json.dumps(data).encode("utf-8"),
        content_type="application/json",
    )
    out = list(FixtureProcessorAgent().handle(msg))
    assert len(out) == 2
    for m in out:
        assert m.envelope.topic == MATCH_NORMALIZED
        rec = NormalizedRecord.from_dict(m.payload)
        assert rec.record_type == "fixture"
        assert rec.plane == "schedule"
        assert rec.extractor_version == EXTRACTOR_VERSION
        assert rec.payload["home_team"]
        assert rec.payload["away_team"]


def test_processor_ignores_other_labels() -> None:
    msg = _classified_msg("odds", b"")
    assert list(FixtureProcessorAgent().handle(msg)) == []


def test_processor_flags_empty_parse() -> None:
    msg = _classified_msg("fixture_list", b"<html>nothing</html>")
    out = list(FixtureProcessorAgent().handle(msg))
    assert len(out) == 1
    assert out[0].envelope.topic == PROOF_FLAG
    assert out[0].payload["kind"] == "empty_parse"


def test_match_detail_processor_extracts_score() -> None:
    body = b"Galatasaray 3 - 2 Fenerbahce"
    out = list(MatchDetailProcessorAgent().handle(_classified_msg("match_detail", body)))
    assert len(out) == 1
    rec = NormalizedRecord.from_dict(out[0].payload)
    assert rec.record_type == "match_detail"
    assert rec.plane == "live"
    assert rec.payload["home_score"] == 3
    assert rec.payload["away_score"] == 2


def test_lineup_processor_requires_eleven_players() -> None:
    short_body = b"\n".join(f"{i}. Player".encode() for i in range(1, 6))
    out = list(LineupProcessorAgent().handle(_classified_msg("lineup", short_body)))
    assert len(out) == 1 and out[0].envelope.topic == PROOF_FLAG  # too short

    full_body = b"\n".join(
        f"{i}. Oyuncu Adı".encode("utf-8") for i in range(1, 12)
    )
    out2 = list(LineupProcessorAgent().handle(_classified_msg("lineup", full_body)))
    assert len(out2) == 1
    rec = NormalizedRecord.from_dict(out2[0].payload)
    assert rec.record_type == "lineup"
    assert len(rec.payload["players"]) == 11


def test_odds_processor_extracts_1x2() -> None:
    body = b"GS-FB 1.85 3.40 4.20"
    out = list(OddsProcessorAgent().handle(_classified_msg("odds", body)))
    assert len(out) == 1
    rec = NormalizedRecord.from_dict(out[0].payload)
    assert rec.record_type == "odds"
    assert rec.plane == "market"
    assert rec.payload == {"1": 1.85, "X": 3.40, "2": 4.20}


def test_normalized_record_validates_plane() -> None:
    with pytest.raises(ValueError):
        NormalizedRecord(
            record_type="fixture",
            plane="bogus",
            source="x",
            source_match_id="1",
            stable_id="abc",
            extractor_version="v1",
            payload={},
        )
