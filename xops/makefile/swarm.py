#!/usr/bin/env python3
"""`make swarm.demo` — Phase 4.8 DoD dispatcher.

Runs the full scrape→categorize→process→store loop end-to-end against
``InMemoryBus`` so the swarm is exercised without requiring Redis.
Useful as a developer smoke test and as a reference for the
multi-agent wiring.

The ``--league`` flag is forwarded to the seed scrape request as
``metadata.league_id``; downstream agents use it for routing only,
not for filtering. With no flag, the demo defaults to TR Süper Lig.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Ensure xops/ is on sys.path for sibling import.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _common import REPO_ROOT, dispatch, info, ok  # noqa: E402


def _run_demo(league: str) -> int:
    # Make the ai/ package importable like the test suite does.
    ai_path = str(REPO_ROOT / "ai")
    if ai_path not in sys.path:
        sys.path.insert(0, ai_path)
    os.environ.setdefault("PYTHONPATH", ai_path)

    from swarm.agents.cache import (  # noqa: E402
        CacheAgent,
        InMemoryCacheBackend,
    )
    from swarm.agents.categorizer import CategorizerAgent  # noqa: E402
    from swarm.agents.payloads import ScrapeRequest  # noqa: E402
    from swarm.agents.processor import FixtureProcessorAgent  # noqa: E402
    from swarm.agents.reactor import FeatureStoreReactor  # noqa: E402
    from swarm.agents.scraper import OpenFootballScraperAgent  # noqa: E402
    from swarm.agents.storage import (  # noqa: E402
        InMemoryRecordStore,
        StorageAgent,
    )
    from swarm.agents.telemetry import TelemetryAgent  # noqa: E402
    from swarm.agents.topics import SCRAPE_REQUEST  # noqa: E402
    from swarm.sdk.bus import InMemoryBus  # noqa: E402
    from swarm.sdk.registry import AgentRegistry  # noqa: E402
    from swarm.sdk.runner import AgentRunner  # noqa: E402
    from swarm.sdk.types import Message  # noqa: E402

    body = json.dumps({
        "name": f"Demo league {league}",
        "matches": [
            {"date": "2025-08-10", "team1": "Galatasaray", "team2": "Fenerbahçe"},
            {"date": "2025-08-11", "team1": "Beşiktaş", "team2": "Trabzonspor"},
            {"date": "2025-08-12", "team1": "Adana Demirspor", "team2": "Antalyaspor"},
        ],
    }).encode("utf-8")

    class _Resp:
        status_code = 200
        content = body
        headers = {"Content-Type": "application/json"}

    class _Client:
        def get(self, url, *, timeout):  # noqa: ARG002
            return _Resp()

    bus = InMemoryBus()
    cache = InMemoryCacheBackend()
    store = InMemoryRecordStore()

    agents = [
        OpenFootballScraperAgent(client=_Client(), clock=lambda: 1e9),
        CategorizerAgent(),
        FixtureProcessorAgent(),
        StorageAgent(store=store),
        CacheAgent(backend=cache),
        FeatureStoreReactor(),
        TelemetryAgent(),
    ]

    runners = []
    for ag in agents:
        r = AgentRunner(
            agent=ag,
            bus=bus,
            registry=AgentRegistry(),
            max_in_flight=8,
            retry_budget=3,
            tick_sec=0.001,
        )
        r.register()
        runners.append(r)

    info(f"swarm.demo: seeding scrape.request for league={league}")
    bus.publish(
        Message.new(
            SCRAPE_REQUEST,
            ScrapeRequest(
                source="openfootball",
                target="/datasets/tr.1.json",
                league_id=league,
            ).as_dict(),
            producer="swarm.demo",
        )
    )

    try:
        for _ in range(64):
            progress = False
            for r in runners:
                if r.step():
                    progress = True
            if not progress:
                break
        ok(f"stored {len(store.all_rows())} normalized records")
        ok(f"cache populated with {len(cache)} keys")
        feature_reactor = next(
            r.agent for r in runners if r.agent.name == "reactor.feature_store"
        )
        ok(
            f"feature-store reactor flagged "
            f"{len(feature_reactor.dirty_record_ids)} dirty record(s)"  # type: ignore[attr-defined]
        )
        telemetry = next(
            r.agent for r in runners if r.agent.name == "telemetry.v1"
        )
        info("telemetry counters:")
        for line in telemetry.counters.render_prometheus().splitlines():  # type: ignore[attr-defined]
            if line.startswith("negelir_"):
                print(f"  {line}")
        return 0
    finally:
        for r in runners:
            r.deregister()


def cmd_demo(argv):
    parser = argparse.ArgumentParser(prog="swarm.py demo")
    parser.add_argument("--league", default="tr_super_lig")
    args = parser.parse_args(argv)
    return _run_demo(args.league)


COMMANDS = {"demo": cmd_demo}


def main(argv=None):
    return dispatch(
        argv if argv is not None else sys.argv[1:],
        COMMANDS,
        script_name="swarm.py",
    )


if __name__ == "__main__":
    raise SystemExit(main())
