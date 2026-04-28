"""Tests for Phase 4.2 categorizer."""
from __future__ import annotations

import base64

from swarm.agents.categorizer import CategorizerAgent, RulesClassifier
from swarm.agents.payloads import ScrapeClassified, ScrapeRaw
from swarm.agents.topics import PROOF_FLAG, SCRAPE_CLASSIFIED
from swarm.sdk.types import Message


def _raw_msg(target: str, body: bytes, content_type: str = "text/html") -> Message:
    raw = ScrapeRaw(
        source="mackolik",
        target=target,
        bytes_sha256="0" * 64,
        http_status=200,
        content_type=content_type,
        bytes_b64=base64.b64encode(body).decode("ascii"),
    )
    return Message.new("scrape.raw", raw.as_dict(), producer="test")


def test_rules_classifier_identifies_lineup_from_url() -> None:
    cls = RulesClassifier()
    raw = ScrapeRaw(
        source="mackolik",
        target="/lineup/match-123",
        bytes_sha256="0" * 64,
        http_status=200,
    )
    label, conf = cls.classify(raw, "")
    assert label == "lineup"
    assert conf >= 0.7


def test_categorizer_emits_scrape_classified_above_threshold() -> None:
    agent = CategorizerAgent()
    out = list(agent.handle(_raw_msg("/fixtures/2024", b"<html>fikstur</html>")))
    assert len(out) == 1
    assert out[0].envelope.topic == SCRAPE_CLASSIFIED
    classified = ScrapeClassified.from_dict(out[0].payload)
    assert classified.label == "fixture_list"
    assert classified.classifier_id == "rules.v1"


def test_categorizer_flags_low_confidence_as_proof_flag() -> None:
    agent = CategorizerAgent()
    out = list(agent.handle(_raw_msg("/", b"unrelated boilerplate")))
    assert len(out) == 1
    assert out[0].envelope.topic == PROOF_FLAG
    assert out[0].payload["kind"] == "low_confidence_classification"


def test_categorizer_handles_openfootball_json() -> None:
    body = b'{"name":"TR","matches":[{"team1":"GS","team2":"FB"}]}'
    msg = _raw_msg("/datasets/tr.json", body, content_type="application/json")
    agent = CategorizerAgent()
    out = list(agent.handle(msg))
    assert out
    assert ScrapeClassified.from_dict(out[0].payload).label == "fixture_list"


def test_categorizer_set_model_swaps_classifier() -> None:
    class _Always:
        classifier_id = "always-odds.v1"

        def classify(self, raw, body):
            return "odds", 0.99

    agent = CategorizerAgent()
    agent.set_model(_Always())
    out = list(agent.handle(_raw_msg("/", b"")))
    classified = ScrapeClassified.from_dict(out[0].payload)
    assert classified.classifier_id == "always-odds.v1"
    assert classified.label == "odds"
