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


def _run_phase8_opsctl_demo(bus: object) -> None:
    """Phase 8 §8.9 — ops.denylist-clear round-trip + dry-run walk.

    Extends ``make swarm.demo`` to prove two things using the same
    ``InMemoryBus`` instance that the Phase 4 loop used:

    1. ``--dry-run`` path: builds the envelope, validates the schema,
       prints the expected ack set, but publishes **nothing**.
    2. Live round-trip: publishes ``maint.event.v1{kind=denylist_clear}``
       through the bus, a stub ``sec.rate.v1`` consumer emits the
       ``maint.ack.v1``, and ack latency is asserted
       ``< cfg.opsctl_ack_timeout_ms``.
    """
    import time
    import uuid
    from datetime import datetime, timezone

    # REPO_ROOT on sys.path so opsctl modules can resolve ``ai.*`` imports.
    repo_str = str(REPO_ROOT)
    if repo_str not in sys.path:
        sys.path.insert(0, repo_str)

    from swarm.agents.maint._ack_routing import expected_ack_set  # noqa: E402
    from swarm.agents.topics import MAINT_ACK, MAINT_EVENT  # noqa: E402
    from swarm.sdk.bus import InMemoryBus  # noqa: E402
    from swarm.sdk.types import Envelope, Message  # noqa: E402
    from opsctl.subcommands.denylist_clear import run as _dc_run  # noqa: E402
    from ai.common.config import Config  # noqa: E402

    cfg = Config()

    # ── 1. dry-run: zero bus publications ─────────────────────────────
    dry_bus = InMemoryBus()
    dry_args = argparse.Namespace(
        target="203.0.113.1",
        client_id="demo-op",
        dry_run=True,
        json=False,
        confirm="",
    )
    rc = _dc_run(dry_args, bus=dry_bus)
    msgs_published = sum(len(s) for s in dry_bus._streams.values())
    if rc != 0:
        raise AssertionError(f"ops.denylist-clear --dry-run exited {rc}")
    if msgs_published != 0:
        raise AssertionError(
            f"dry-run published {msgs_published} unexpected messages"
        )
    ok("ops.denylist-clear --dry-run: no bus publish (correct)")

    # ── 2. live round-trip through the shared bus ──────────────────────
    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rid = uuid.uuid4().hex
    live_msg = Message(
        envelope=Envelope(topic=MAINT_EVENT, producer="ops_console"),
        payload={
            "kind": "denylist_clear",
            "target": "203.0.113.1",
            "request_id": rid,
            "client_id": "demo-op",
            "produced_at": now_iso,
        },
    )

    stub_group = "sec.rate.v1.demo"
    bus.ensure_group(MAINT_EVENT, stub_group)  # type: ignore[attr-defined]

    t0 = time.monotonic()
    bus.publish(live_msg)  # type: ignore[attr-defined]

    # sec.rate.v1 stub: reads denylist_clear, emits maint.ack.v1 ack.
    deliveries = bus.read(  # type: ignore[attr-defined]
        MAINT_EVENT, stub_group, "sec.rate.v1.stub", count=16, block_ms=0
    )
    for d in deliveries:
        p = d.message.payload
        if p.get("kind") == "denylist_clear" and str(p.get("request_id")) == rid:
            ack_now = datetime.now(timezone.utc).isoformat(timespec="seconds")
            bus.publish(Message(  # type: ignore[attr-defined]
                envelope=Envelope(topic=MAINT_ACK, producer="sec.rate.v1"),
                payload={
                    "request_id": rid,
                    "accepted": True,
                    "accepted_by": "sec.rate.v1",
                    "reason": "demo_denylist_clear",
                    "processed_at": ack_now,
                    "attempt": 1,
                },
            ))
        bus.ack(MAINT_EVENT, stub_group, d.handle)  # type: ignore[attr-defined]

    # opsctl side: drain the ack via the standard consumer-group pattern.
    ack_group = f"opsctl.ack.{rid}"
    bus.ensure_group(MAINT_ACK, ack_group)  # type: ignore[attr-defined]
    ack_deliveries = bus.read(  # type: ignore[attr-defined]
        MAINT_ACK, ack_group, "demo.opsctl", count=16, block_ms=0
    )
    received: set[str] = set()
    for d in ack_deliveries:
        p = d.message.payload
        if str(p.get("request_id")) == rid:
            ab = p.get("accepted_by")
            if isinstance(ab, str):
                received.add(ab)
        bus.ack(MAINT_ACK, ack_group, d.handle)  # type: ignore[attr-defined]

    latency_ms = (time.monotonic() - t0) * 1000.0
    expected = expected_ack_set("denylist_clear")
    if received != expected:
        raise AssertionError(
            f"ack mismatch: got {received!r}, expected {expected!r}"
        )
    budget = cfg.opsctl_ack_timeout_ms
    if latency_ms >= budget:
        raise AssertionError(
            f"ack latency {latency_ms:.1f}ms >= budget {budget}ms"
        )
    ok(
        f"ops.denylist-clear round-trip: ack in {latency_ms:.1f}ms "
        f"(budget={budget}ms, acks={sorted(received)})"
    )


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
        # ── Phase 8 extension: ops.denylist-clear round-trip + dry-run ─
        info("swarm.demo (Phase 8): ops console round-trip")
        _run_phase8_opsctl_demo(bus)
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
