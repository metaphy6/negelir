"""Phase 4.8 — End-to-end pipeline DoD test.

Exercises the full Phase 4 chain on the in-memory bus:

    scrape.request → scraper.openfootball.v1 → scrape.raw
                  → categorizer.v1            → scrape.classified
                  → processor.fixture.v1      → match.normalized
                  → storage.v1                → match.stored + freshness.events.v1
                  → cache.v1 (records cache)  + reactor.feature_store

Wires every Phase 4 agent through ``AgentRunner`` against
``InMemoryBus`` so the message flow uses the production retry / DLQ /
ack path. The test asserts that one synthetic openfootball JSON
fixture rolls all the way through to a populated cache + dirty-feature
set.
"""
from __future__ import annotations

import base64
import json

from swarm.agents.cache import (
    CacheAgent,
    InMemoryCacheBackend,
    make_record_key,
)
from swarm.agents.categorizer import CategorizerAgent
from swarm.agents.payloads import ScrapeRaw, ScrapeRequest
from swarm.agents.processor import FixtureProcessorAgent
from swarm.agents.reactor import FeatureStoreReactor
from swarm.agents.scraper import OpenFootballScraperAgent
from swarm.agents.storage import InMemoryRecordStore, StorageAgent
from swarm.agents.telemetry import TelemetryAgent
from swarm.agents.topics import (
    MATCH_NORMALIZED,
    MATCH_STORED,
    SCRAPE_CLASSIFIED,
    SCRAPE_RAW,
    SCRAPE_REQUEST,
)
from swarm.sdk.bus import InMemoryBus
from swarm.sdk.registry import AgentRegistry
from swarm.sdk.runner import AgentRunner
from swarm.sdk.types import Message


_OPENFOOTBALL_BODY = json.dumps({
    "name": "TR Süper Lig 2024-25",
    "matches": [
        {"date": "2024-08-10", "team1": "Galatasaray", "team2": "Fenerbahçe"},
        {"date": "2024-08-11", "team1": "Beşiktaş", "team2": "Trabzonspor"},
    ],
}).encode("utf-8")


class _FakeResp:
    status_code = 200
    content = _OPENFOOTBALL_BODY
    headers = {"Content-Type": "application/json"}


class _FakeClient:
    def get(self, url, *, timeout):  # noqa: ARG002
        return _FakeResp()


def _make_runner(bus, agent):
    runner = AgentRunner(
        agent=agent,
        bus=bus,
        registry=AgentRegistry(),
        max_in_flight=8,
        retry_budget=3,
        tick_sec=0.001,
    )
    runner.register()
    return runner


def _drain(runners, *, max_steps: int = 64) -> None:
    """Round-robin step every runner until none of them does work."""
    for _ in range(max_steps):
        progress = False
        for r in runners:
            if r.step():
                progress = True
        if not progress:
            return
    raise AssertionError(
        "swarm pipeline did not quiesce within max_steps; possible loop"
    )


def test_phase4_swarm_demo_end_to_end() -> None:
    bus = InMemoryBus()
    cache = InMemoryCacheBackend()
    store = InMemoryRecordStore()

    runners = [
        _make_runner(
            bus,
            OpenFootballScraperAgent(client=_FakeClient(), clock=lambda: 1e9),
        ),
        _make_runner(bus, CategorizerAgent()),
        _make_runner(bus, FixtureProcessorAgent()),
        _make_runner(bus, StorageAgent(store=store)),
        _make_runner(bus, CacheAgent(backend=cache)),
        _make_runner(bus, FeatureStoreReactor()),
        _make_runner(bus, TelemetryAgent()),
    ]

    try:
        # Inject the seed scrape.request.
        bus.publish(
            Message.new(
                SCRAPE_REQUEST,
                ScrapeRequest(
                    source="openfootball",
                    target="/datasets/tr.1.json",
                ).as_dict(),
                producer="test",
            )
        )

        _drain(runners)

        # ── Storage assertions ──
        rows = store.all_rows()
        assert len(rows) == 2, f"expected 2 fixtures, got {rows}"

        # ── Cache assertions ──
        assert len(cache) == 2

        # Cache key shape is record:<source>:<stable_id>:<record_type>
        # We don't know the stable_id without re-deriving; just sanity check.
        any_key = next(iter(cache._data.keys()))  # pyright: ignore[reportPrivateUsage]
        assert any_key.startswith("record:openfootball:")
        assert any_key.endswith(":fixture")

        # ── Reactor assertion ──
        feature_reactor = next(
            r.agent for r in runners if r.agent.name == "reactor.feature_store"
        )
        assert len(feature_reactor.dirty_record_ids) == 2  # type: ignore[attr-defined]

        # ── Telemetry assertion ──
        telemetry = next(
            r.agent for r in runners if r.agent.name == "telemetry.v1"
        )
        text = telemetry.counters.render_prometheus()  # type: ignore[attr-defined]
        # Every Phase 4 control topic should have a counter.
        for topic in (
            SCRAPE_REQUEST, SCRAPE_RAW, SCRAPE_CLASSIFIED,
            MATCH_NORMALIZED, MATCH_STORED,
        ):
            assert f'topic="{topic}"' in text, f"missing counter for {topic}"

        # ── No DLQ leakage ──
        for topic in (SCRAPE_REQUEST, SCRAPE_RAW, SCRAPE_CLASSIFIED,
                      MATCH_NORMALIZED, MATCH_STORED):
            dlq_msgs = bus.drain_topic(f"{topic}.dlq")
            assert dlq_msgs == [], f"unexpected DLQ items on {topic}: {dlq_msgs}"

        # ── Wire-contract assertion (Phase 4 fourth-pass audit) ──
        # Every message that touched the bus must satisfy its registered
        # JSON schema. Catches drift between payloads.py and schemas/*.json
        # at the live emission point, not just on hand-crafted fixtures.
        from swarm.sdk.schemas import known_topics, validate
        registered = set(known_topics())
        for topic in bus.topics():
            topic_str = str(topic)
            if topic_str not in registered:
                continue  # e.g. echo.* / future topics without schemas
            for msg in bus.drain_topic(topic_str):
                errors = validate(topic_str, msg.payload)
                assert not errors, (
                    f"emitted {topic_str} payload violates schema:\n  "
                    + "\n  ".join(errors)
                )

    finally:
        for r in runners:
            r.deregister()


def test_phase4_pipeline_is_idempotent_on_replay() -> None:
    """Re-injecting the same scrape.request must not duplicate rows."""
    bus = InMemoryBus()
    store = InMemoryRecordStore()

    runners = [
        _make_runner(
            bus,
            OpenFootballScraperAgent(client=_FakeClient(), clock=lambda: 1e9),
        ),
        _make_runner(bus, CategorizerAgent()),
        _make_runner(bus, FixtureProcessorAgent()),
        _make_runner(bus, StorageAgent(store=store)),
    ]
    try:
        for _ in range(3):
            bus.publish(
                Message.new(
                    SCRAPE_REQUEST,
                    ScrapeRequest(
                        source="openfootball",
                        target="/datasets/tr.1.json",
                    ).as_dict(),
                    producer="test",
                )
            )
            _drain(runners)

        # 2 fixtures, regardless of how many requests we replayed.
        assert len(store.all_rows()) == 2
    finally:
        for r in runners:
            r.deregister()
