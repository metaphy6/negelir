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
import shutil
import sys
import tempfile
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


def _build_phase10_demo_predict_approved_message() -> object:
    """Return a schema-v3 predict.approved.v1 message without citation signature.

    This intentionally exercises §10.21.8 warn-mode handling where missing
    citation_signature emits an alert but rendering still proceeds.
    """
    from swarm.agents.topics import PREDICT_APPROVED  # noqa: E402
    from swarm.sdk.types import Message  # noqa: E402

    return Message.new(
        topic=PREDICT_APPROVED,
        payload={
            "schema_version": 3,
            "prediction_id": "demo-phase10-p1",
            "summary_correlation_id": "demo-phase10-summary-1",
            "summary_expected_count": 1,
            "qa_request_id": "demo-phase10-req-1",
            "qa_correlation_id": "demo-phase10-summary-1",
            "match_id": "tr1:galatasaray-fenerbahce",
            "market": "1x2",
            "approved_at": "2026-05-31T10:00:00+00:00",
            "approved_by": ["proof.sanity.v1"],
            "verdict_count": 1,
            "quorum": 1,
            "calibration_version": 1,
            "final": {
                "prediction_id": "demo-phase10-p1",
                "match_id": "tr1:galatasaray-fenerbahce",
                "market": "1x2",
                "distribution": {"1": 0.52, "X": 0.27, "2": 0.21},
                "weights": {},
                "contributing_models": ["model-demo-1"],
                "calibration_version": 1,
                "swarm_confidence": 0.85,
                "degraded": False,
                "degraded_reason": "",
                "produced_at": "2026-05-31T10:00:00+00:00",
                "league_id": "tr-superlig",
                "profile_id": None,
            },
            # citation_signature intentionally omitted for warn-mode exercise.
        },
        producer="swarm.demo.nlp",
    )


def _run_phase10_nlp_demo_extensions() -> None:
    """Run §10.21.14 extra demo paths for make swarm.demo.nlp.

    Exercises:
    1) confusables-fold path with Cyrillic a,
    2) lexicon swap fail-revert on one corrupted file,
    3) citation-signature warn-mode missing-key,
    4) cold-start stage events in strict order.
    """
    ai_path = str(REPO_ROOT / "ai")
    if ai_path in sys.path:
        sys.path.remove(ai_path)
    sys.path.insert(0, ai_path)
    os.environ.setdefault("PYTHONPATH", ai_path)

    # `xops/makefile/nlp.py` can shadow the top-level `nlp` package when the
    # makefile directory is on sys.path during unit tests.
    nlp_mod = sys.modules.get("nlp")
    nlp_file = str(getattr(nlp_mod, "__file__", "")) if nlp_mod is not None else ""
    if nlp_file.endswith("xops/makefile/nlp.py"):
        del sys.modules["nlp"]

    from common.config import cfg  # noqa: E402
    from nlp.lexicon_loader import LexiconStore  # noqa: E402
    from nlp.normalize import normalize_input  # noqa: E402
    from swarm.agents.nlp import NlpAnswerAgent, NlpBootProbeState  # noqa: E402
    from swarm.agents.topics import NLP_ALERT_V1, NLP_EVENT_V1, QA_ANSWER_V1  # noqa: E402

    # (a) Confusables-fold path: Cyrillic "а" in team name.
    confusables = normalize_input("Gal\u0430tasaray maçı")
    normalized_joined = " ".join(confusables.tokens)
    if "confusables_fold" not in confusables.steps_run:
        raise AssertionError("phase10 demo: confusables_fold step did not execute")
    if "galatasaray" not in normalized_joined:
        raise AssertionError(
            "phase10 demo: Cyrillic confusables input did not fold to galatasaray"
        )
    ok("swarm.demo.nlp: confusables-fold path exercised")

    # (b) Lexicon swap fail-revert: corrupt one file and assert rollback.
    class _Clock:
        def __init__(self) -> None:
            self.value = 0.0

        def now(self) -> float:
            return self.value

    lexicon_src = REPO_ROOT / "ai" / "nlp" / "lexicon"
    with tempfile.TemporaryDirectory(prefix="swarm-demo-nlp-") as tmpdir:
        lexicon_tmp = Path(tmpdir)
        for src_file in sorted(lexicon_src.glob("*.tr.yaml")):
            if src_file.name.startswith("_"):
                continue
            shutil.copy2(src_file, lexicon_tmp / src_file.name)

        clock = _Clock()
        prev_atomicity_env = os.getenv("NEGELIR_NLP_LEXICON_SWAP_ATOMICITY")
        os.environ["NEGELIR_NLP_LEXICON_SWAP_ATOMICITY"] = "per_file"
        try:
            store = LexiconStore(
                lexicon_tmp,
                reload_s=1,
                max_rss_mb=0,
                clock_mono=clock.now,
            )
            first_alerts = store.maybe_reload()
            if first_alerts:
                raise AssertionError(f"phase10 demo: initial lexicon load alerted: {first_alerts!r}")

            players_path = lexicon_tmp / "players.tr.yaml"
            # Corrupt one file with invalid YAML to force a failed reload cycle.
            players_path.write_text("entries: [", encoding="utf-8")

            # Force poll interval window to pass without sleeping.
            clock.value = 2.0
            alerts = store.maybe_reload()
            if not any(a.get("kind") == "lexicon_unreadable" for a in alerts):
                raise AssertionError(
                    "phase10 demo: expected lexicon_unreadable alert on corrupt lexicon"
                )

            rolled_back = store.get("players.tr.yaml")
            if rolled_back is None:
                raise AssertionError("phase10 demo: players.tr.yaml missing after rollback")
            rolled_back_entries = rolled_back[1]
            if not rolled_back_entries:
                raise AssertionError("phase10 demo: rollback snapshot unexpectedly empty")
        finally:
            if prev_atomicity_env is None:
                os.environ.pop("NEGELIR_NLP_LEXICON_SWAP_ATOMICITY", None)
            else:
                os.environ["NEGELIR_NLP_LEXICON_SWAP_ATOMICITY"] = prev_atomicity_env
    ok("swarm.demo.nlp: lexicon swap fail-revert exercised")

    # (c) Citation signature warn-mode with missing key/signature.
    prev_mode = str(getattr(cfg, "nlp_predict_citation_hmac_required", "warn"))
    try:
        cfg.nlp_predict_citation_hmac_required = "warn"
        answer_agent = NlpAnswerAgent(clock_iso=lambda: "2026-05-31T10:00:00+00:00")
        outputs = list(answer_agent.handle(_build_phase10_demo_predict_approved_message()))
    finally:
        cfg.nlp_predict_citation_hmac_required = prev_mode

    has_answer = any(m.envelope.topic == QA_ANSWER_V1 for m in outputs)
    has_warn_alert = any(
        m.envelope.topic == NLP_ALERT_V1
        and m.payload.get("kind") == "nlp_citation_signature_verify_failed"
        and m.payload.get("severity") == "warn"
        for m in outputs
    )
    if not has_answer or not has_warn_alert:
        raise AssertionError(
            "phase10 demo: citation warn-mode missing-key path did not emit answer+warn alert"
        )
    ok("swarm.demo.nlp: citation-signature warn-mode missing-key exercised")

    # (f) §10.23 tenant fairness, canary/shadow, partial summary, screen-reader,
    # and safe-mode recovery paths.
    from nlp.intake_fair_queue import NlpIntakeFairQueue  # noqa: E402
    from nlp.intent import IntentClassifier  # noqa: E402
    from nlp.render import build_environment, render as nlp_render  # noqa: E402
    from nlp.lexicon_loader import LexiconStore  # noqa: E402
    from swarm.agents.nlp import _SummaryAgg, NlpAnswerAgent  # noqa: E402

    fairness = NlpIntakeFairQueue[int](
        fairness_key="tenant_id",
        per_tenant_inflight_max=1,
        max_tracked_keys=100,
        tenant_abuse_qps_threshold=10.0,
        tenant_abuse_window_s=10,
        clock=lambda: 0.0,
    )
    for idx, tenant_id in enumerate(
        ["tenant-alpha", "tenant-alpha", "tenant-alpha", "tenant-beta", "tenant-gamma"],
        1,
    ):
        fairness.enqueue(idx, {"tenant_id": tenant_id})
    first_three: list[str] = []
    for _ in range(3):
        dispatch = fairness.dequeue()
        if dispatch is None:
            raise AssertionError("phase10 demo: fairness queue returned no dispatch")
        first_three.append(dispatch.key)
        fairness.complete(dispatch.key)
    if first_three != ["tenant-alpha", "tenant-beta", "tenant-gamma"]:
        raise AssertionError(
            f"phase10 demo: fairness queue did not isolate noisy tenant; got {first_three!r}"
        )
    ok("swarm.demo.nlp: tenant-fairness isolation under load exercised")

    class _StubIntentModel:
        def __init__(self, model_version: str, intent: str, confidence: float) -> None:
            self.model_version = model_version
            self._intent = intent
            self._confidence = confidence

        def predict_intent(self, text: str) -> tuple[str, float]:
            return self._intent, self._confidence

    prev_canary_pod = getattr(cfg, "nlp_canary_pod", False)
    prev_canary_pct = getattr(cfg, "nlp_intent_model_canary_pct", 0)
    prev_canary_bucket = getattr(cfg, "nlp_canary_account_bucket_size", 1000)
    prev_shadow_mode = getattr(cfg, "nlp_intent_shadow_mode", "off")
    prev_shadow_rate = getattr(cfg, "nlp_shadow_sample_rate", 0.01)
    try:
        cfg.nlp_canary_pod = True
        cfg.nlp_intent_model_canary_pct = 100
        cfg.nlp_canary_account_bucket_size = 1000
        cfg.nlp_intent_shadow_mode = "on"
        cfg.nlp_shadow_sample_rate = 1.0
        if not IntentClassifier.should_route_to_canary("acct-123", cfg):
            raise AssertionError(
                "phase10 demo: canary routing did not select the expected account"
            )
        baseline = _StubIntentModel("baseline-v1", "predict.1x2", 0.82)
        canary = _StubIntentModel("canary-v2", "predict.2.5", 0.32)
        shadow_payload = IntentClassifier.shadow_payload_for_request(
            "Galatasaray maç",
            baseline,
            canary,
            cfg,
            request_id="demo-shadow-1",
        )
        if shadow_payload is None:
            raise AssertionError("phase10 demo: shadow-mode did not produce payload")
        if shadow_payload["agreement"] is not False:
            raise AssertionError(
                "phase10 demo: shadow-mode disagreement was not recorded as expected"
            )
        ok(
            "swarm.demo.nlp: canary routing + shadow-mode disagreement recording exercised"
        )
    finally:
        cfg.nlp_canary_pod = prev_canary_pod
        cfg.nlp_intent_model_canary_pct = prev_canary_pct
        cfg.nlp_canary_account_bucket_size = prev_canary_bucket
        cfg.nlp_intent_shadow_mode = prev_shadow_mode
        cfg.nlp_shadow_sample_rate = prev_shadow_rate

    agent = NlpAnswerAgent(
        clock_iso=lambda: "2026-05-31T10:00:00+00:00",
        monotonic=lambda: 0.0,
    )
    agg = _SummaryAgg(
        expected=5,
        qa_request_id="demo-req-2",
        qa_correlation_id="demo-summary-2",
        deadline=0.0,
    )
    for index in range(3):
        agg.predictions.append(
            {
                "prediction_id": f"demo-p{index}",
                "qa_request_id": "demo-req-2",
                "qa_correlation_id": "demo-summary-2",
                "summary_correlation_id": "demo-summary-2",
                "calibration_version": 1,
                "final": {
                    "prediction_id": f"demo-p{index}",
                    "contributing_models": ["model-demo"],
                    "produced_at": "2026-05-31T10:00:00+00:00",
                    "degraded": False,
                    "degraded_reason": None,
                },
            }
        )
    summary_answer = agent._build_summary_answer(agg, "demo-summary-2", received=3)
    if summary_answer.payload["kind"] != "summary":
        raise AssertionError("phase10 demo: summary partial-render did not produce a summary answer")
    if not summary_answer.payload["degraded"]:
        raise AssertionError("phase10 demo: partial summary answer should be degraded")
    if "3/5 maç" not in summary_answer.payload["answer_text"]:
        raise AssertionError(
            "phase10 demo: partial summary answer text did not include missing fixtures count"
        )
    ok("swarm.demo.nlp: summary fan-out partial-render path exercised")

    with tempfile.TemporaryDirectory(prefix="swarm-demo-nlp-screen-reader-") as sample_tmp:
        sample_dir = Path(sample_tmp)
        sample_dir.mkdir(parents=True, exist_ok=True)
        sample_template = sample_dir / "screen_reader_emoji.tr.j2"
        sample_template.write_text(
            "Tahmin % 67 ✓ ⚽ 🏟️ ▶\n",
            encoding="utf-8",
        )
        env = build_environment(template_dir=sample_dir)
        text1 = nlp_render(
            "screen_reader_emoji.tr.j2",
            {},
            env=env,
            answer_format="screen_reader",
        )
        text2 = nlp_render(
            "screen_reader_emoji.tr.j2",
            {},
            env=env,
            answer_format="screen_reader",
        )
        if text1.encode("utf-8") != text2.encode("utf-8"):
            raise AssertionError("phase10 demo: screen_reader output is not byte-stable")
        if any(ch in text1 for ch in ["✓", "⚽", "🏟️", "▶"]):
            raise AssertionError("phase10 demo: screen_reader output contained decorative emoji")
    ok("swarm.demo.nlp: answer_format=screen_reader byte-stable rendering exercised")

    with tempfile.TemporaryDirectory(prefix="swarm-demo-nlp-safe-mode-") as safe_tmp:
        primary_dir = Path(safe_tmp) / "lexicon"
        safe_mode_dir = primary_dir.parent / "lexicon_safe_mode"
        primary_dir.mkdir(parents=True, exist_ok=True)
        safe_mode_dir.mkdir(parents=True, exist_ok=True)
        safe_yaml = """_meta:\n  schema_version: 1\n  lexicon_version: 1.0.0\n  generated_at_utc: '2026-06-02T00:00:00Z'\n  generator: test\nentries:\n- canonical_id: galatasaray\n  names:\n  - Galatasaray\n  aliases:\n  - Galatasaray\n"""
        primary_valid_yaml = """_meta:\n  schema_version: 1\n  lexicon_version: 1.0.0\n  generated_at_utc: '2026-06-02T00:00:00Z'\n  generator: test\nentries:\n- canonical_id: fenerbahce\n  names:\n  - Fenerbahçe\n  aliases:\n  - Fenerbahce\n"""
        (safe_mode_dir / "teams.tr.yaml").write_text(safe_yaml, encoding="utf-8")
        primary_file = primary_dir / "teams.tr.yaml"
        primary_file.write_text("entries: [", encoding="utf-8")
        class _Clock:
            def __init__(self) -> None:
                self.value = 0.0

            def now(self) -> float:
                return self.value

        prev_lex_dir = getattr(cfg, "nlp_lexicon_dir", "ai/nlp/lexicon")
        prev_safe_enabled = getattr(cfg, "nlp_safe_mode_fallback_enabled", True)
        cfg.nlp_lexicon_dir = str(primary_dir)
        cfg.nlp_safe_mode_fallback_enabled = True
        clock = _Clock()
        try:
            safe_store = LexiconStore.from_cfg(
                cfg, reload_s=1, max_rss_mb=0, clock_mono=clock.now
            )
            alerts = safe_store.maybe_reload()
            if not safe_store.safe_mode_active:
                raise AssertionError("phase10 demo: safe-mode did not activate on corrupted primary lexicon")
            if not any(a.get("kind") == "nlp_safe_mode_active" for a in alerts):
                raise AssertionError("phase10 demo: safe-mode activation alert missing")
            primary_file.write_text(primary_valid_yaml, encoding="utf-8")
            clock.value = 2.0
            exit_alerts = safe_store.maybe_reload()
            if safe_store.safe_mode_active:
                raise AssertionError("phase10 demo: safe-mode did not exit after primary lexicon recovery")
            if not any(a.get("kind") == "nlp_safe_mode_exited" for a in exit_alerts):
                raise AssertionError("phase10 demo: safe-mode exit alert missing")
        finally:
            cfg.nlp_lexicon_dir = prev_lex_dir
            cfg.nlp_safe_mode_fallback_enabled = prev_safe_enabled
    ok("swarm.demo.nlp: safe-mode engage/exit via injected lexicon corruption exercised")

    # (e) §10.22 Turkish robustness paths.
    from nlp.entity import EntityExtractor  # noqa: E402
    from nlp.lexicon_loader import LexiconStore  # noqa: E402
    from nlp.normalize import normalize_input  # noqa: E402
    from swarm.agents.nlp import NlpIntentAgent  # noqa: E402
    from swarm.agents.topics import NLP_EVENT_V1, QA_REQUEST_V1  # noqa: E402
    from swarm.sdk import RequestIdDeduper  # noqa: E402
    from swarm.sdk.types import Message  # noqa: E402

    normalized = normalize_input("Galatasaray maci")
    if normalized.tokens != ("galatasaray", "maci"):
        raise AssertionError(
            f"phase10 demo: ASCII-only Turkish input failed: {normalized.tokens!r}"
        )
    ok("swarm.demo.nlp: ASCII-only Turkish input path exercised")

    normalized = normalize_input("Galatasaraya maç")
    if not normalized.apostrophe_repairs:
        raise AssertionError(
            "phase10 demo: dropped-apostrophe path did not produce apostrophe repairs"
        )
    if "galatasaray'a" not in normalized.tokens:
        raise AssertionError(
            f"phase10 demo: dropped-apostrophe token not repaired: {normalized.tokens!r}"
        )
    ok("swarm.demo.nlp: dropped-apostrophe path exercised")

    normalized = normalize_input("Galatasaray maçmı")
    if "maçmı" not in normalized.particle_repairs:
        raise AssertionError(
            f"phase10 demo: attached question particle path did not repair: {normalized.particle_repairs!r}"
        )
    ok("swarm.demo.nlp: attached-question-particle path exercised")

    normalized = normalize_input("Galatasaray geliyo maç")
    if ("geliyo", "gerund_r_drop") not in normalized.dialect_repairs:
        raise AssertionError(
            f"phase10 demo: dialect normalization failed: {normalized.dialect_repairs!r}"
        )
    ok("swarm.demo.nlp: dialect normalization path exercised")

    normalized = normalize_input("mci maç")
    if ("mci", "manchester_city") not in normalized.abbreviations_expanded:
        raise AssertionError(
            f"phase10 demo: abbreviation expansion failed: {normalized.abbreviations_expanded!r}"
        )
    ok("swarm.demo.nlp: abbreviation expansion path exercised")

    with tempfile.TemporaryDirectory(prefix="swarm-demo-nlp-lexicon-") as tmpdir:
        lexicon_tmp = Path(tmpdir)
        lexicon_tmp.mkdir(parents=True, exist_ok=True)
        lexicon_tmp.joinpath("teams.tr.yaml").write_text(
            """_meta:
  schema_version: 1
  lexicon_version: 1.0.0
  generated_at_utc: '2026-06-02T00:00:00Z'
  generator: test
entries:
- canonical_id: manchester_city
  names:
  - Manchester City
  aliases:
  - Man City
- canonical_id: bayern_munich
  names:
  - Bayern Münih
  aliases:
  - Bayern Munich
""",
            encoding="utf-8",
        )
        store = LexiconStore(lexicon_tmp)
        store.maybe_reload()
        extractor = EntityExtractor(store=store)

        normalized = normalize_input("Manchester City formdaymış")
        result = extractor.extract(normalized.tokens, raw_tokens=normalized.tokens)
        if "manchester_city" not in [span.canonical_id for span in result.spans]:
            raise AssertionError(
                f"phase10 demo: code-switch team did not resolve: {[span.canonical_id for span in result.spans]!r}"
            )
        ok("swarm.demo.nlp: code-switch entity resolution path exercised")

        normalized = normalize_input("Bayern Münih maç")
        result = extractor.extract(normalized.tokens, raw_tokens=normalized.tokens)
        if "bayern_munich" not in [span.canonical_id for span in result.spans]:
            raise AssertionError(
                f"phase10 demo: foreign transliteration path did not resolve: {[span.canonical_id for span in result.spans]!r}"
            )
        ok("swarm.demo.nlp: foreign-transliteration path exercised")

    normalized = normalize_input("Galatasaray 23 Ekim maç")
    if "23" not in normalized.tokens or "ekim" not in normalized.tokens or "maç" not in normalized.tokens:
        raise AssertionError(
            f"phase10 demo: date+match-pair path tokenization failed: {normalized.tokens!r}"
        )
    ok("swarm.demo.nlp: date+match-pair path exercised")

    intent_agent = NlpIntentAgent(
        monotonic=lambda: 0.0,
        deduper=RequestIdDeduper(window_s=10.0, max_keys=1000, clock=lambda: 0.0),
    )
    intent_msg = Message.new(
        topic=QA_REQUEST_V1,
        payload={
            "request_id": "demo-req-1",
            "locale": "tr",
            "sanitized_text": "gs maçı tahmin",
            "sec_verdict": "pass",
            "emitted_at": "2026-05-31T10:00:00+00:00",
        },
        producer="demo",
    )
    intent_out = list(intent_agent.handle(intent_msg))
    if not any(
        m.envelope.topic == NLP_EVENT_V1
        and m.payload.get("kind") == "locale_fallback_used"
        and m.payload.get("requested") == "tr"
        and m.payload.get("resolved") == "tr-TR"
        for m in intent_out
    ):
        raise AssertionError("phase10 demo: locale fallback path did not emit locale_fallback_used")
    ok("swarm.demo.nlp: locale-fallback path exercised")

    normalized = normalize_input("Galatasaray oç maç")
    if "oç" not in normalized.slurs_stripped or "maç" not in normalized.tokens:
        raise AssertionError(
            f"phase10 demo: offensive-with-real-intent path did not strip slur while preserving intent: {normalized.slurs_stripped!r}, {normalized.tokens!r}"
        )
    ok("swarm.demo.nlp: offensive-with-real-intent path exercised")

    # (d) Cold-start staging order check: every stage event observed in order.
    probe = NlpBootProbeState(
        clock_iso=lambda: "2026-05-31T10:00:00+00:00",
        monotonic=lambda: 0.0,
        boot_budget_s=30.0,
        boot_liveness_grace_s=60.0,
    )
    observed: list[int] = []
    for stage in range(1, 7):
        msg = probe.mark_stage(stage, elapsed_ms=100)
        if msg.envelope.topic != NLP_EVENT_V1:
            raise AssertionError("phase10 demo: cold-start emitted alert instead of stage event")
        if msg.payload.get("kind") != "cold_start_stage":
            raise AssertionError("phase10 demo: unexpected cold-start event kind")
        observed.append(int(msg.payload.get("stage", -1)))

    if observed != [1, 2, 3, 4, 5, 6]:
        raise AssertionError(f"phase10 demo: cold-start stage order mismatch: {observed!r}")
    if not probe.readiness():
        raise AssertionError("phase10 demo: readiness did not become true at stage 6")
    ok("swarm.demo.nlp: cold-start staging order exercised")


def _run_phase10_nlp_demo_full_extensions() -> None:
    """Run §10.24 extra demo paths for make swarm.demo.nlp.full."""
    ai_path = str(REPO_ROOT / "ai")
    if ai_path in sys.path:
        sys.path.remove(ai_path)
    sys.path.insert(0, ai_path)
    os.environ.setdefault("PYTHONPATH", ai_path)

    # `xops/makefile/nlp.py` can shadow the top-level `nlp` package when the
    # makefile directory is on sys.path during unit tests.
    nlp_mod = sys.modules.get("nlp")
    nlp_file = str(getattr(nlp_mod, "__file__", "")) if nlp_mod is not None else ""
    if nlp_file.endswith("xops/makefile/nlp.py"):
        del sys.modules["nlp"]

    from common.config import cfg  # noqa: E402
    from nlp.normalize import normalize_input  # noqa: E402
    from swarm.agents.nlp import NlpIntentAgent  # noqa: E402
    from swarm.agents.topics import NLP_EVENT_V1, QA_ANSWER_V1, QA_REQUEST_V1  # noqa: E402
    from swarm.sdk.types import Message  # noqa: E402

    normalized = normalize_input("Galatasaraya maç")
    if not normalized.apostrophe_repairs:
        raise AssertionError("phase10 demo.full: harmony-violation recovery path did not produce apostrophe repairs")
    ok("swarm.demo.nlp.full: harmony-violation recovery path exercised")

    normalized = normalize_input("maçkkkk")
    if normalized.tokens != ("maçkk",):
        raise AssertionError(
            f"phase10 demo.full: repeated-character collapse path failed: {normalized.tokens!r}"
        )
    ok("swarm.demo.nlp.full: repeated-character collapse path exercised")

    normalized = normalize_input("g00l")
    if normalized.tokens != ("gool",):
        raise AssertionError(
            f"phase10 demo.full: digit-letter fold path failed: {normalized.tokens!r}"
        )
    ok("swarm.demo.nlp.full: digit-letter fold path exercised")

    normalized = normalize_input("i\u0307stanbul maç")
    if "istanbul" not in normalized.tokens:
        raise AssertionError(
            f"phase10 demo.full: decomposed dotted-I NFC path failed: {normalized.tokens!r}"
        )
    ok("swarm.demo.nlp.full: decomposed-İ NFC composition path exercised")

    normalized = normalize_input(
        "Galatasaray maç var mı bugün? Beşiktaş maç nerede? Bu fark ne kadar?",
        input_source="voice",
    )
    if len(normalized.subqueries) < 2:
        raise AssertionError(
            "phase10 demo.full: run-on multi-question split path did not produce multiple subqueries"
        )
    ok("swarm.demo.nlp.full: run-on multi-question split path exercised")

    normalized = normalize_input("Maç bugün değil mi?")
    if "değil" not in normalized.tokens or "mi" not in normalized.tokens:
        raise AssertionError(
            f"phase10 demo.full: negation framing path failed: {normalized.tokens!r}"
        )
    ok("swarm.demo.nlp.full: negation framing path exercised")

    normalized = normalize_input("MKE Ankaragücü maç")
    if "ankaragüc'ü" not in normalized.tokens:
        raise AssertionError(
            f"phase10 demo.full: MKE Ankaragücü affix-tolerant match path failed: {normalized.tokens!r}"
        )
    ok("swarm.demo.nlp.full: MKE Ankaragücü affix-tolerant match path exercised")

    normalized = normalize_input("Kara Kartal maç")
    if "kara" not in normalized.tokens or "kartal" not in normalized.tokens:
        raise AssertionError(
            f"phase10 demo.full: Kara Kartal nickname backtrack path failed: {normalized.tokens!r}"
        )
    ok("swarm.demo.nlp.full: Kara Kartal nickname backtrack path exercised")

    normalized = normalize_input("Hocam Trabzonspor maçı ne zaman?")
    if "trabzonspor" not in normalized.tokens:
        raise AssertionError(
            f"phase10 demo.full: hoca-honorific role narrowing path failed: {normalized.tokens!r}"
        )
    if "hocam" in normalized.tokens:
        raise AssertionError(
            f"phase10 demo.full: hoca-honorific role narrowing path failed to strip the honorific: {normalized.tokens!r}"
        )
    ok("swarm.demo.nlp.full: hoca-honorific role narrowing path exercised")

    normalized = normalize_input("Galatasaray 🔴🏟️")
    if not any(event.get("kind") == "emoji_hint_extracted" for event in normalized.normalization_events):
        raise AssertionError("phase10 demo.full: color-emoji hint path did not emit emoji_hint_extracted")
    ok("swarm.demo.nlp.full: color-emoji hint path exercised")

    normalized = normalize_input("#Galatasaray maç @fenerbahce")
    event_kinds = {event.get("kind") for event in normalized.normalization_events}
    if "hashtag_dropped" not in event_kinds or "mention_resolved" not in event_kinds:
        raise AssertionError(
            f"phase10 demo.full: hashtag/mention hygiene path failed: {event_kinds!r}"
        )
    ok("swarm.demo.nlp.full: hashtag/mention hygiene path exercised")

    normalized = normalize_input("3.5 maç sonucu")
    if "3.5" not in normalized.tokens:
        raise AssertionError(
            f"phase10 demo.full: decimal-vs-score disambiguation path failed: {normalized.tokens!r}"
        )
    ok("swarm.demo.nlp.full: decimal-vs-score disambiguation path exercised")

    agent = NlpIntentAgent()
    request = Message.new(
        topic=QA_REQUEST_V1,
        payload={
            "request_id": "demo-empty-001",
            "locale": "tr-TR",
            "sanitized_text": "",
            "sec_verdict": "pass",
            "emitted_at": "2026-06-05T00:00:00+00:00",
        },
        producer="swarm.demo.nlp.full",
    )
    output = list(agent.handle(request))
    answer = [m for m in output if m.envelope.topic == QA_ANSWER_V1]
    events = [m for m in output if m.envelope.topic == NLP_EVENT_V1]
    if len(answer) != 1 or len(events) != 1:
        raise AssertionError(
            f"phase10 demo.full: empty-input canned help path failed: answers={len(answer)} events={len(events)}"
        )
    if answer[0].payload.get("intent") != "meta.help":
        raise AssertionError("phase10 demo.full: empty-input canned help did not produce meta.help answer")
    if events[0].payload.get("kind") != "empty_input_floor_response":
        raise AssertionError("phase10 demo.full: empty-input canned help did not emit empty_input_floor_response event")
    ok("swarm.demo.nlp.full: empty-input canned help path exercised")


def cmd_demo(argv):
    parser = argparse.ArgumentParser(prog="swarm.py demo")
    parser.add_argument("--league", default="tr_super_lig")
    args = parser.parse_args(argv)
    return _run_demo(args.league)


def cmd_demo_nlp(argv):
    parser = argparse.ArgumentParser(prog="swarm.py demo-nlp")
    parser.add_argument("--league", default="tr_super_lig")
    args = parser.parse_args(argv)

    started = time.monotonic()
    rc = _run_demo(args.league)
    if rc != 0:
        return rc

    info("swarm.demo.nlp: running Phase 10 §10.21.14 extension checks")
    _run_phase10_nlp_demo_extensions()

    elapsed_s = time.monotonic() - started
    budget_s = 30.0
    if elapsed_s >= budget_s:
        raise AssertionError(
            f"swarm.demo.nlp exceeded budget: {elapsed_s:.2f}s >= {budget_s:.2f}s"
        )
    ok(f"swarm.demo.nlp completed in {elapsed_s:.2f}s (< {budget_s:.2f}s)")
    return 0


def cmd_demo_nlp_full(argv):
    parser = argparse.ArgumentParser(prog="swarm.py demo-nlp-full")
    parser.add_argument("--league", default="tr_super_lig")
    args = parser.parse_args(argv)

    started = time.monotonic()
    rc = _run_demo(args.league)
    if rc != 0:
        return rc

    info("swarm.demo.nlp.full: running Phase 10 §10.21.14 extension checks")
    _run_phase10_nlp_demo_extensions()
    info("swarm.demo.nlp.full: running Phase 10 §10.24 full extension checks")
    _run_phase10_nlp_demo_full_extensions()

    elapsed_s = time.monotonic() - started
    budget_s = 60.0
    if elapsed_s >= budget_s:
        raise AssertionError(
            f"swarm.demo.nlp.full exceeded budget: {elapsed_s:.2f}s >= {budget_s:.2f}s"
        )
    ok(f"swarm.demo.nlp.full completed in {elapsed_s:.2f}s (< {budget_s:.2f}s)")
    return 0


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
    "demo-nlp": cmd_demo_nlp,
    "demo-nlp-full": cmd_demo_nlp_full,
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
