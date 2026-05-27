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
import time
import uuid
from pathlib import Path

# Ensure xops/ is on sys.path for sibling import.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _common import REPO_ROOT, compose_run, dispatch, info, ok  # noqa: E402


def _run_phase8_opsctl_demo(
    bus: object,
    *,
    max_ack_latency_ms: int | None = None,
    topic_prefix: str = "",
) -> None:
    """Phase 8 §8.9 — ops.denylist-clear round-trip + dry-run walk.

    Extends ``make swarm.demo`` to prove two things using the same
    ``InMemoryBus`` instance that the Phase 4 loop used:

    1. ``--dry-run`` path: builds the envelope, validates the schema,
       prints the expected ack set, but publishes **nothing**.
     2. Live round-trip: publishes ``maint.event.v1{kind=denylist_clear}``
         through the bus, a stub ``sec.rate.v1`` consumer emits the
         ``maint.ack.v1``, and the expected ack-set is observed.
    """
    import uuid
    from datetime import datetime, timezone

    # REPO_ROOT on sys.path so opsctl modules can resolve ``ai.*`` imports.
    repo_str = str(REPO_ROOT)
    if repo_str not in sys.path:
        sys.path.insert(0, repo_str)

    from swarm.agents.maint._ack_routing import expected_ack_set  # noqa: E402
    from swarm.agents.topics import MAINT_ACK, MAINT_EVENT  # noqa: E402

    def _topic(name: str) -> str:
        if not topic_prefix:
            return name
        return f"{topic_prefix}.{name}"

    maint_event_topic = _topic(str(MAINT_EVENT))
    maint_ack_topic = _topic(str(MAINT_ACK))

    from swarm.sdk.bus import InMemoryBus  # noqa: E402
    from swarm.sdk.types import Envelope, Message  # noqa: E402
    from opsctl.subcommands.denylist_clear import run as _dc_run  # noqa: E402

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
        envelope=Envelope(topic=maint_event_topic, producer="ops_console"),
        payload={
            "kind": "denylist_clear",
            "target": "203.0.113.1",
            "request_id": rid,
            "client_id": "demo-op",
            "produced_at": now_iso,
        },
    )

    stub_group = "sec.rate.v1.demo"
    if topic_prefix:
        stub_group = f"{stub_group}.{topic_prefix}"
    bus.ensure_group(maint_event_topic, stub_group)  # type: ignore[attr-defined]

    started_mono = time.monotonic()
    bus.publish(live_msg)  # type: ignore[attr-defined]

    # sec.rate.v1 stub: reads denylist_clear, emits maint.ack.v1 ack.
    deliveries = bus.read(  # type: ignore[attr-defined]
        maint_event_topic, stub_group, "sec.rate.v1.stub", count=16, block_ms=0
    )
    for d in deliveries:
        p = d.message.payload
        if p.get("kind") == "denylist_clear" and str(p.get("request_id")) == rid:
            ack_now = datetime.now(timezone.utc).isoformat(timespec="seconds")
            bus.publish(Message(  # type: ignore[attr-defined]
                envelope=Envelope(topic=maint_ack_topic, producer="sec.rate.v1"),
                payload={
                    "request_id": rid,
                    "accepted": True,
                    "accepted_by": "sec.rate.v1",
                    "reason": "demo_denylist_clear",
                    "processed_at": ack_now,
                    "attempt": 1,
                },
            ))
        bus.ack(maint_event_topic, stub_group, d.handle)  # type: ignore[attr-defined]

    # opsctl side: drain the ack via the standard consumer-group pattern.
    ack_group = f"opsctl.ack.{rid}"
    bus.ensure_group(maint_ack_topic, ack_group)  # type: ignore[attr-defined]
    ack_deliveries = bus.read(  # type: ignore[attr-defined]
        maint_ack_topic, ack_group, "demo.opsctl", count=16, block_ms=0
    )
    received: set[str] = set()
    for d in ack_deliveries:
        p = d.message.payload
        if str(p.get("request_id")) == rid:
            ab = p.get("accepted_by")
            if isinstance(ab, str):
                received.add(ab)
        bus.ack(maint_ack_topic, ack_group, d.handle)  # type: ignore[attr-defined]

    expected = expected_ack_set("denylist_clear")
    if received != expected:
        raise AssertionError(
            f"ack mismatch: got {received!r}, expected {expected!r}"
        )

    if max_ack_latency_ms is not None:
        ack_latency_ms = (time.monotonic() - started_mono) * 1000.0
        if ack_latency_ms >= float(max_ack_latency_ms):
            raise AssertionError(
                "ack latency exceeded live-demo budget: "
                f"{ack_latency_ms:.2f}ms >= {max_ack_latency_ms}ms"
            )
        ok(
            "ops.denylist-clear round-trip: "
            f"acks={sorted(received)}, latency_ms={ack_latency_ms:.2f}"
        )
        return

    ok(f"ops.denylist-clear round-trip: acks={sorted(received)}")


def _redis_demo_cleanup(bus: object, *, topic_prefix: str) -> None:
    """Delete all live-demo Redis keys for the given prefix and assert clean."""
    client = getattr(bus, "_client", None)
    if client is None:
        return

    pattern = f"{topic_prefix}*"
    cursor = 0
    keys: list[bytes | str] = []
    while True:
        cursor, batch = client.scan(cursor=cursor, match=pattern, count=100)
        if batch:
            keys.extend(batch)
        if cursor == 0:
            break

    if keys:
        client.delete(*keys)

    _cursor = 0
    leftovers: list[bytes | str] = []
    while True:
        _cursor, batch = client.scan(cursor=_cursor, match=pattern, count=100)
        if batch:
            leftovers.extend(batch)
        if _cursor == 0:
            break
    if leftovers:
        raise AssertionError(
            f"live demo cleanup left prefixed Redis keys: {leftovers!r}"
        )
    ok(f"swarm.demo.live cleanup: no leftover Redis keys for prefix={topic_prefix}")


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


def _run_api_smoke_test(base_url: str, *, budget_ms: int = 1500) -> None:
    """Phase 9 §9.13 — API end-to-end smoke test (skip-if-no-API).

    Sequence: probe /v1/healthz → POST /v1/auth/register → POST /v1/auth/login
    → POST /v1/qa.  The total wall-clock from before register through the
    /v1/qa response must be < budget_ms.

    Auth handlers return 501 in Phase 9.2 stub mode (full bcrypt/JWT wired
    later).  Register may also return 403 (self-registration disabled) or 409
    (duplicate).  These are all treated as expected-stub responses so the demo
    is not blocked by incomplete auth implementation.

    /v1/qa does not require a JWT — the handler accepts any valid JSON body with
    a non-empty "q" field and returns 202 Accepted with a qa_correlation_id.
    """
    import urllib.error
    import urllib.request

    # ── 1. Probe healthz — skip if API is not up ──────────────────────────
    healthz_url = f"{base_url}/v1/healthz"
    try:
        req = urllib.request.Request(healthz_url, method="GET")
        with urllib.request.urlopen(req, timeout=1.0) as resp:
            if resp.status not in (200, 503):
                warn(
                    f"swarm.demo.live API: unexpected healthz status "
                    f"{resp.status} at {base_url} — skip API steps"
                )
                return
        info(f"swarm.demo.live API: healthz OK at {base_url}")
    except Exception as exc:
        warn(
            f"swarm.demo.live API: not reachable at {base_url} "
            f"({type(exc).__name__}: {exc}) — skip API steps"
        )
        return

    # ── 2. Start wall-clock ───────────────────────────────────────────────
    t0 = time.monotonic()

    # ── 3. Register (stub-tolerant) ───────────────────────────────────────
    email = "test-api-demo@negelir.local"
    password = "Demo-Smoke-Test-Phase9!"
    reg_status: int | None = None
    try:
        reg_body = json.dumps({"email": email, "password": password}).encode("utf-8")
        reg_req = urllib.request.Request(
            f"{base_url}/v1/auth/register",
            data=reg_body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(reg_req, timeout=1.0) as resp:
            reg_status = resp.status
    except urllib.error.HTTPError as exc:
        reg_status = exc.code
    except Exception as exc:
        warn(f"swarm.demo.live API: register request error ({exc})")
    # 201 = created, 403 = self-reg disabled, 409 = duplicate, 501 = stub
    if reg_status in (200, 201, 403, 409, 501):
        ok(f"swarm.demo.live API: POST /v1/auth/register status={reg_status} (stub/disabled tolerated)")
    elif reg_status is not None:
        raise AssertionError(
            f"POST /v1/auth/register returned unexpected status {reg_status}"
        )

    # ── 4. Login (stub-tolerant) ──────────────────────────────────────────
    login_status: int | None = None
    try:
        login_body = json.dumps({"email": email, "password": password}).encode("utf-8")
        login_req = urllib.request.Request(
            f"{base_url}/v1/auth/login",
            data=login_body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(login_req, timeout=1.0) as resp:
            login_status = resp.status
    except urllib.error.HTTPError as exc:
        login_status = exc.code
    except Exception as exc:
        warn(f"swarm.demo.live API: login request error ({exc})")
    # 200 = full JWT issued, 501 = stub (Phase 9.2 not complete)
    if login_status in (200, 201, 501):
        ok(f"swarm.demo.live API: POST /v1/auth/login status={login_status} (stub tolerated)")
    elif login_status is not None:
        raise AssertionError(
            f"POST /v1/auth/login returned unexpected status {login_status}"
        )

    # ── 5. POST /v1/qa — this must succeed ───────────────────────────────
    qa_payload = json.dumps(
        {"q": "Beşiktaş vs Galatasaray'da kim kazanır?", "locale": "tr"},
        ensure_ascii=False,
    ).encode("utf-8")
    qa_status: int = 0
    try:
        qa_req = urllib.request.Request(
            f"{base_url}/v1/qa",
            data=qa_payload,
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        with urllib.request.urlopen(qa_req, timeout=2.0) as resp:
            qa_status = resp.status
    except urllib.error.HTTPError as exc:
        qa_status = exc.code
    except Exception as exc:
        raise AssertionError(f"POST /v1/qa request failed: {exc}") from exc

    # ── 6. Assert latency budget ──────────────────────────────────────────
    wall_ms = (time.monotonic() - t0) * 1000.0

    if qa_status not in (200, 202):
        raise AssertionError(
            f"POST /v1/qa returned {qa_status}, want 200 or 202"
        )
    if wall_ms >= float(budget_ms):
        raise AssertionError(
            f"end-to-end wall-clock {wall_ms:.2f}ms >= budget {budget_ms}ms"
        )
    ok(
        f"swarm.demo.live API: POST /v1/qa status={qa_status} "
        f"wall_ms={wall_ms:.2f} < {budget_ms}ms  ✓"
    )


def cmd_demo_live(argv):
    parser = argparse.ArgumentParser(prog="swarm.py demo-live")
    parser.parse_args(argv)

    ai_path = str(REPO_ROOT / "ai")
    if ai_path not in sys.path:
        sys.path.insert(0, ai_path)
    os.environ.setdefault("PYTHONPATH", ai_path)

    from common.config import cfg  # noqa: E402
    from swarm.sdk.bus import RedisStreamsBus  # noqa: E402

    info("swarm.demo.live: ensuring demo-profile Redis is up")
    compose_run("--profile", "demo", "up", "-d", "redis")

    # Skip-if-no-Redis: attempt a quick ping before constructing RedisStreamsBus.
    # A 1-second connection timeout avoids a long hang when docker isn't running.
    try:
        import socket as _socket
        _sock = _socket.create_connection(
            (cfg.redis_host, cfg.redis_port), timeout=1.0
        )
        _sock.close()
    except OSError as _exc:
        warn(
            f"swarm.demo.live: Redis not reachable at "
            f"{cfg.redis_host}:{cfg.redis_port} ({_exc}) — SKIP"
        )
        return 0

    bus = RedisStreamsBus(
        host=cfg.redis_host,
        port=cfg.redis_port,
        socket_timeout=float(cfg.redis_socket_timeout),
        dlq_max_len=cfg.swarm_dlq_max_len,
    )
    topic_prefix = f"swarm.demo.live.{uuid.uuid4().hex[:10]}"
    info(
        "swarm.demo.live: ops console round-trip over Redis Streams "
        f"(budget={cfg.opsctl_ack_timeout_ms_live_demo}ms)"
    )

    try:
        _run_phase8_opsctl_demo(
            bus,
            max_ack_latency_ms=cfg.opsctl_ack_timeout_ms_live_demo,
            topic_prefix=topic_prefix,
        )
    finally:
        _redis_demo_cleanup(bus, topic_prefix=topic_prefix)

    # ── Phase 9 §9.13 extension: API end-to-end smoke test ───────────────
    info(
        f"swarm.demo.live: Phase 9 §9.13 API smoke test "
        f"(base={cfg.api_demo_base_url}, budget=1500ms)"
    )
    _run_api_smoke_test(cfg.api_demo_base_url, budget_ms=1500)

    return 0


COMMANDS = {
    "demo": cmd_demo,
    "demo-live": cmd_demo_live,
}


def main(argv=None):
    return dispatch(
        argv if argv is not None else sys.argv[1:],
        COMMANDS,
        script_name="swarm.py",
    )


if __name__ == "__main__":
    raise SystemExit(main())
