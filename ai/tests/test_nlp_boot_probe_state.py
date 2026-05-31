"""Phase 10 §10.21.9 bug floor: liveness and readiness must diverge at boot."""

import json
import pathlib
import threading
import time
from typing import Iterable

from swarm.agents.nlp import NlpBootProbeState
from swarm.sdk import AgentRegistry, AgentRunner, InMemoryBus, Message
from nlp.render import build_environment, warm_closed_intent_templates


def test_nlp_liveness_true_while_readiness_false_during_boot() -> None:
    """A live process can still be unready during NLP cold-start work."""
    state = NlpBootProbeState()

    assert state.liveness() is True
    assert state.readiness() is False


def test_nlp_startup_probe_flips_true_at_stage_1() -> None:
    """Startup probe turns green once lexicons are loaded (stage 1)."""
    state = NlpBootProbeState()

    assert state.startup_readiness() is False

    state.mark_stage(1, elapsed_ms=100)

    assert state.startup_readiness() is True


def test_nlp_mark_ready_keeps_liveness_and_flips_readiness() -> None:
    """Readiness flips only when boot work is explicitly marked complete."""
    state = NlpBootProbeState()

    state.mark_ready()

    assert state.liveness() is True
    assert state.readiness() is True


def test_nlp_readiness_503_semantics_until_stage_6_and_cold_start_event() -> None:
    """Stage 6 is the only ready state; every stage move emits cold_start_stage."""
    state = NlpBootProbeState(clock_iso=lambda: "2026-05-31T00:00:00+00:00")

    for stage in range(6):
        event = state.mark_stage(stage, elapsed_ms=100 + stage)
        assert event.envelope.topic == "nlp.event.v1"
        assert event.payload["kind"] == "cold_start_stage"
        assert event.payload["stage"] == stage
        assert event.payload["elapsed_ms"] == 100 + stage
        assert state.readiness() is False

    final_event = state.mark_stage(6, elapsed_ms=777)
    assert final_event.payload["kind"] == "cold_start_stage"
    assert final_event.payload["stage"] == 6
    assert state.readiness() is True


def test_nlp_readiness_503_until_stage_6() -> None:
    """Named proof from §10.21.9: readiness stays false until stage 6."""
    test_nlp_readiness_503_semantics_until_stage_6_and_cold_start_event()


def test_nlp_probe_contract_stage_thresholds() -> None:
    """Phase 10 §10.21.11: startup/readiness/liveness use distinct thresholds."""
    state = NlpBootProbeState()

    # Stage 0: process is alive, but not startup-ready and not traffic-ready.
    assert state.liveness() is True
    assert state.startup_readiness() is False
    assert state.readiness() is False

    state.mark_stage(1, elapsed_ms=100)

    # Stage 1: startup probe is green; readiness still waits for full boot.
    assert state.liveness() is True
    assert state.startup_readiness() is True
    assert state.readiness() is False

    state.mark_stage(6, elapsed_ms=700)

    # Stage 6: readiness finally flips true.
    assert state.liveness() is True
    assert state.startup_readiness() is True
    assert state.readiness() is True


def test_nlp_boot_stage_regression_rejected() -> None:
    """Boot stages are monotonic; regression attempts are rejected."""
    state = NlpBootProbeState()
    state.mark_stage(3, elapsed_ms=10)

    try:
        state.mark_stage(2, elapsed_ms=11)
    except ValueError as exc:
        assert "regression" in str(exc)
    else:
        raise AssertionError("Expected ValueError on stage regression")


def test_nlp_per_stage_budget_enforced() -> None:
    """Per-stage cap breach emits timeout alert and never flips readiness."""
    clock = {"now": 0.0}

    def monotonic() -> float:
        return clock["now"]

    state = NlpBootProbeState(
        monotonic=monotonic,
        boot_budget_s=30.0,
        boot_liveness_grace_s=0.05,
        stage_caps_s={1: 0.05},
    )

    alert = state.mark_stage(1, elapsed_ms=60)
    assert alert.envelope.topic == "nlp.alert.v1"
    assert alert.payload["kind"] == "nlp_cold_start_timeout"
    assert alert.payload["severity"] == "critical"
    assert alert.payload["reason"] == "stage_cap_breached"
    assert state.readiness() is False
    assert state.liveness() is True

    clock["now"] = 0.2
    assert state.liveness() is False


def test_nlp_cold_start_alert_carries_last_stage() -> None:
    """Timeout alert includes the last successfully completed stage."""
    clock = {"now": 0.0}

    def monotonic() -> float:
        return clock["now"]

    state = NlpBootProbeState(
        monotonic=monotonic,
        boot_budget_s=1.0,
        boot_liveness_grace_s=60.0,
        stage_caps_s={1: 10.0, 2: 10.0},
    )

    clock["now"] = 0.2
    event = state.mark_stage(1, elapsed_ms=20)
    assert event.payload["kind"] == "cold_start_stage"

    clock["now"] = 1.5
    alert = state.mark_stage(2, elapsed_ms=20)
    assert alert.envelope.topic == "nlp.alert.v1"
    assert alert.payload["kind"] == "nlp_cold_start_timeout"
    assert alert.payload["details"]["last_stage"] == 1
    assert alert.payload["details"]["last_stage_name"] == "lexicons_loaded"


def test_nlp_jinja_warm_renders_every_intent_template() -> None:
    """Warm stage must render every closed-enum template without undefined slots."""
    from common.config import cfg

    enum_path = pathlib.Path("ai/swarm/sdk/schemas/_intent_enum.json")
    intents = json.loads(enum_path.read_text(encoding="utf-8"))["enum"]

    bcc_dir = pathlib.Path("data/cache/jinja_bcc")
    bcc_dir.mkdir(parents=True, exist_ok=True)
    before = sorted(bcc_dir.glob("__nlp_*.cache"))

    env = build_environment()
    warmed = warm_closed_intent_templates(env=env)

    assert len(warmed) == len(intents)
    assert warmed == [f"{intent}.tr.j2" for intent in sorted(intents)]

    after = sorted(bcc_dir.glob("__nlp_*.cache"))
    assert len(after) >= len(before)
    assert bcc_dir == pathlib.Path(cfg.nlp_jinja_bcc_dir)


def test_nlp_graceful_shutdown_drains_inflight_no_loss() -> None:
    """Runner stop drains in-flight NLP work before shutdown completes."""

    started = threading.Event()

    class _SlowNlpAgent:
        name = "nlp.intent.v1"
        subscribes = ["qa.request.v1"]
        publishes = ["qa.answer.v1"]

        def handle(self, msg: Message) -> Iterable[Message]:
            started.set()
            time.sleep(0.05)
            yield Message.new(
                "qa.answer.v1",
                {"request_id": msg.payload.get("request_id"), "kind": "ok"},
                producer=self.name,
            )

    bus = InMemoryBus()
    runner = AgentRunner(
        agent=_SlowNlpAgent(),
        bus=bus,
        registry=AgentRegistry(),
        shutdown_grace_s=1.0,
        tick_sec=0.01,
    )
    bus.publish(Message.new("qa.request.v1", {"request_id": "req-1"}, producer="test"))

    thread = threading.Thread(target=runner.run, daemon=True)
    thread.start()

    assert started.wait(timeout=1.0)
    runner.stop()
    thread.join(timeout=2.0)

    assert not thread.is_alive()
    out = bus.drain_topic("qa.answer.v1")
    assert len(out) == 1
    assert out[0].payload["request_id"] == "req-1"
    assert bus.pending_count("qa.request.v1", "swarm:nlp.intent.v1") == 0