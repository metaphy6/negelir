"""Tests for Phase 4.1 scraper agent base + concrete sources."""
from __future__ import annotations

import base64

import pytest

from swarm.agents.payloads import ScrapeRaw, ScrapeRequest
from swarm.agents.scraper import (
    MackolikScraperAgent,
    NesineScraperAgent,
    OpenFootballScraperAgent,
    TffScraperAgent,
)
from swarm.agents.topics import PROOF_FLAG, SCRAPE_RAW
from swarm.sdk.types import Message


class _FakeResp:
    def __init__(self, status: int, body: bytes, content_type: str = "text/html") -> None:
        self.status_code = status
        self.content = body
        self.headers = {"Content-Type": content_type}


class _FakeClient:
    def __init__(self, responses: list[_FakeResp]) -> None:
        self._responses = list(responses)
        self.calls: list[str] = []

    def get(self, url: str, *, timeout: int) -> _FakeResp:
        self.calls.append(url)
        return self._responses.pop(0)


def _req_msg(source: str, target: str = "/fixtures") -> Message:
    return Message.new(
        topic="scrape.request",
        payload=ScrapeRequest(source=source, target=target).as_dict(),
        producer="test",
    )


def test_scraper_emits_scrape_raw_on_2xx() -> None:
    client = _FakeClient([_FakeResp(200, b"hello world")])
    agent = MackolikScraperAgent(client=client, clock=lambda: 1e9)
    out = list(agent.handle(_req_msg("mackolik")))

    assert len(out) == 1
    assert out[0].envelope.topic == SCRAPE_RAW
    raw = ScrapeRaw.from_dict(out[0].payload)
    assert raw.source == "mackolik"
    assert raw.http_status == 200
    assert base64.b64decode(raw.bytes_b64) == b"hello world"
    assert len(raw.bytes_sha256) == 64
    assert client.calls[0].startswith("https://mackolik.local/fixtures")


def test_scraper_ignores_other_sources() -> None:
    client = _FakeClient([])  # should not be called
    agent = MackolikScraperAgent(client=client, clock=lambda: 1e9)
    out = list(agent.handle(_req_msg("nesine")))
    assert out == []
    assert client.calls == []


def test_scraper_404_emits_proof_flag() -> None:
    client = _FakeClient([_FakeResp(404, b"")])
    agent = MackolikScraperAgent(client=client, clock=lambda: 1e9)
    out = list(agent.handle(_req_msg("mackolik")))

    assert len(out) == 1
    assert out[0].envelope.topic == PROOF_FLAG
    assert out[0].payload["http_status"] == 404
    assert out[0].payload["kind"] == "upstream_missing"


def test_scraper_5xx_raises_for_runner_to_retry() -> None:
    client = _FakeClient([_FakeResp(503, b"down")])
    agent = MackolikScraperAgent(client=client, clock=lambda: 1e9)
    with pytest.raises(RuntimeError, match="503"):
        list(agent.handle(_req_msg("mackolik")))


def test_resolve_url_passthrough_for_absolute_targets() -> None:
    client = _FakeClient([_FakeResp(200, b"x")])
    agent = NesineScraperAgent(client=client, clock=lambda: 1e9)
    out = list(
        agent.handle(_req_msg("nesine", target="https://nesine.local/abs"))
    )
    assert out
    assert client.calls == ["https://nesine.local/abs"]


def test_all_concrete_scrapers_have_unique_names() -> None:
    names = {
        cls(client=_FakeClient([]), clock=lambda: 1e9).name
        for cls in (
            MackolikScraperAgent,
            NesineScraperAgent,
            TffScraperAgent,
            OpenFootballScraperAgent,
        )
    }
    assert names == {
        "scraper.mackolik.v1",
        "scraper.nesine.v1",
        "scraper.tff.v1",
        "scraper.openfootball.v1",
    }


def test_scraper_malformed_payload_returns_no_messages() -> None:
    client = _FakeClient([])
    agent = MackolikScraperAgent(client=client, clock=lambda: 1e9)
    bad = Message.new(topic="scrape.request", payload={"oops": True}, producer="test")
    assert list(agent.handle(bad)) == []
    assert client.calls == []
