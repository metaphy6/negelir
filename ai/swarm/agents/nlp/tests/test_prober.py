from __future__ import annotations

import json
from pathlib import Path

from common.config import cfg
from swarm.agents.nlp import NlpProberAgent
from swarm.agents.topics import NLP_ALERT_V1, NLP_PROBER_V1, QA_REQUEST_V1
from swarm.sdk.types import Message


def _make_corpus_file(tmp_path: Path) -> Path:
    path = tmp_path / "prober_corpus.jsonl"
    entry = {
        "request_payload": {
            "request_id": "prober-001",
            "sanitized_text": "Galatasaray bugün kazanır mı?",
            "locale": "tr-TR",
            "sec_verdict": "pass",
            "emitted_at": "2026-06-06T00:00:00Z",
        },
        "expected_intent_id": "predict.match_outcome",
        "expected_top_1_entity_id": "team:galatasaray",
        "expected_refusal_reason_code": None,
        "expected_post_render_template_sha": "sha256:000",
        "expected_outbound_checksum": "sha256:111",
    }
    path.write_text(json.dumps(entry) + "\n", encoding="utf-8")
    return path


def test_nlp_prober_emits_probe_request_and_heartbeat(tmp_path: Path) -> None:
    corpus_path = _make_corpus_file(tmp_path)
    agent = NlpProberAgent(corpus_path=str(corpus_path), clock=lambda: 0.0)

    outputs = agent.on_heartbeat()

    assert len(outputs) == 2
    topics = {msg.envelope.topic for msg in outputs}
    assert topics == {QA_REQUEST_V1, NLP_PROBER_V1}

    request_msg = next(msg for msg in outputs if msg.envelope.topic == QA_REQUEST_V1)
    assert request_msg.payload["request_metadata"]["synthetic_prober"] is True
    assert request_msg.payload["request_metadata"]["humanizer_disabled"] is True
    assert request_msg.payload["locale"] == "tr-TR"
    assert request_msg.payload["request_id"] == "prober-001"


def test_nlp_prober_always_disables_humanizer_even_when_cfg_false(tmp_path: Path) -> None:
    corpus_path = _make_corpus_file(tmp_path)
    from common.config import cfg

    monkey_cfg_humanize = cfg.nlp_prober_humanizer_disabled
    cfg.nlp_prober_humanizer_disabled = False
    try:
        agent = NlpProberAgent(corpus_path=str(corpus_path), clock=lambda: 0.0)
        outputs = agent.on_heartbeat()
        request_msg = next(msg for msg in outputs if msg.envelope.topic == QA_REQUEST_V1)
        assert request_msg.payload["request_metadata"]["synthetic_prober"] is True
        assert request_msg.payload["request_metadata"]["humanizer_disabled"] is True
    finally:
        cfg.nlp_prober_humanizer_disabled = monkey_cfg_humanize


def test_nlp_prober_emits_alert_on_post_render_template_sha_drift(tmp_path: Path) -> None:
    corpus_path = _make_corpus_file(tmp_path)
    agent = NlpProberAgent(corpus_path=str(corpus_path), clock=lambda: 0.0)
    agent.on_heartbeat()

    answer = Message.new(
        topic="qa.answer.v1",
        payload={
            "request_id": "prober-001",
            "intent_id": "predict.match_outcome",
            "top_1_entity_id": "team:galatasaray",
            "post_render_template_sha": "sha256:999",
            "outbound_checksum": "sha256:111",
            "request_metadata": {"synthetic_prober": True},
        },
        producer="nlp.answer.v1",
    )
    alerts = list(agent.handle(answer))

    assert len(alerts) == 1
    alert = alerts[0]
    assert alert.envelope.topic == NLP_ALERT_V1
    assert alert.payload["kind"] == "prober_drift_detected"
    assert alert.payload["drift_field"] == "post_render_template_sha"


def test_nlp_prober_records_telemetry_outcome_on_probe_success(monkeypatch, tmp_path: Path) -> None:
    corpus_path = _make_corpus_file(tmp_path)
    agent = NlpProberAgent(corpus_path=str(corpus_path), clock=lambda: 0.0)
    agent.on_heartbeat()

    recorded: list[tuple[str, str, bool]] = []

    class StubSink:
        def record_nlp_prober_outcome(self, request_id: str, intent: str, success: bool, latency_seconds: float | None = None) -> None:
            recorded.append((request_id, intent, success))

    monkeypatch.setattr("common.telemetry.get_sink", lambda: StubSink())

    answer = Message.new(
        topic="qa.answer.v1",
        payload={
            "request_id": "prober-001",
            "intent_id": "predict.match_outcome",
            "top_1_entity_id": "team:galatasaray",
            "post_render_template_sha": "sha256:000",
            "outbound_checksum": "sha256:111",
            "request_metadata": {"synthetic_prober": True},
        },
        producer="nlp.answer.v1",
    )
    assert list(agent.handle(answer)) == []
    assert recorded == [("prober-001", "predict.match_outcome", True)]


def test_nlp_prober_ignores_matching_synthetic_answer(tmp_path: Path) -> None:
    corpus_path = _make_corpus_file(tmp_path)
    agent = NlpProberAgent(corpus_path=str(corpus_path), clock=lambda: 0.0)
    agent.on_heartbeat()

    answer = Message.new(
        topic="qa.answer.v1",
        payload={
            "request_id": "prober-001",
            "intent_id": "predict.match_outcome",
            "top_1_entity_id": "team:galatasaray",
            "post_render_template_sha": "sha256:000",
            "outbound_checksum": "sha256:111",
            "request_metadata": {"synthetic_prober": True},
        },
        producer="nlp.answer.v1",
    )
    alerts = list(agent.handle(answer))

    assert alerts == []


def test_nlp_prober_emits_alert_on_answer_drift(tmp_path: Path) -> None:
    corpus_path = _make_corpus_file(tmp_path)
    agent = NlpProberAgent(corpus_path=str(corpus_path), clock=lambda: 0.0)
    agent.on_heartbeat()

    answer = Message.new(
        topic="qa.answer.v1",
        payload={
            "request_id": "prober-001",
            "intent_id": "predict.match_outcome",
            "top_1_entity_id": "team:galatasaray",
            "post_render_template_sha": "sha256:000",
            "outbound_checksum": "sha256:999",
            "request_metadata": {"synthetic_prober": True},
        },
        producer="nlp.answer.v1",
    )
    alerts = list(agent.handle(answer))

    assert len(alerts) == 1
    alert = alerts[0]
    assert alert.envelope.topic == NLP_ALERT_V1
    assert alert.payload["kind"] == "prober_drift_detected"
    assert alert.payload["drift_field"] == "outbound_checksum"


def test_nlp_prober_emits_alert_on_intent_id_drift(tmp_path: Path) -> None:
    corpus_path = _make_corpus_file(tmp_path)
    agent = NlpProberAgent(corpus_path=str(corpus_path), clock=lambda: 0.0)
    agent.on_heartbeat()

    answer = Message.new(
        topic="qa.answer.v1",
        payload={
            "request_id": "prober-001",
            "intent_id": "data.fixture_lookup",
            "top_1_entity_id": "team:galatasaray",
            "post_render_template_sha": "sha256:000",
            "outbound_checksum": "sha256:111",
            "request_metadata": {"synthetic_prober": True},
        },
        producer="nlp.answer.v1",
    )
    alerts = list(agent.handle(answer))

    assert len(alerts) == 1
    alert = alerts[0]
    assert alert.envelope.topic == NLP_ALERT_V1
    assert alert.payload["kind"] == "prober_drift_detected"
    assert alert.payload["drift_field"] == "intent_id"


def test_nlp_prober_catches_mid_flight_drift_after_previous_match(tmp_path: Path) -> None:
    corpus_path = _make_corpus_file(tmp_path)

    now = [0.0]

    def clock() -> float:
        return now[0]

    agent = NlpProberAgent(corpus_path=str(corpus_path), clock=clock)

    outputs = agent.on_heartbeat()
    assert any(msg.envelope.topic == QA_REQUEST_V1 for msg in outputs)

    answer = Message.new(
        topic="qa.answer.v1",
        payload={
            "request_id": "prober-001",
            "intent_id": "predict.match_outcome",
            "top_1_entity_id": "team:galatasaray",
            "post_render_template_sha": "sha256:000",
            "outbound_checksum": "sha256:111",
            "request_metadata": {"synthetic_prober": True},
        },
        producer="nlp.answer.v1",
    )
    assert list(agent.handle(answer)) == []

    now[0] += cfg.nlp_prober_interval_s + 1
    outputs = agent.on_heartbeat()
    assert any(msg.envelope.topic == QA_REQUEST_V1 for msg in outputs)

    drift_answer = Message.new(
        topic="qa.answer.v1",
        payload={
            "request_id": "prober-001",
            "intent_id": "predict.match_outcome",
            "top_1_entity_id": "team:galatasaray",
            "post_render_template_sha": "sha256:000",
            "outbound_checksum": "sha256:999",
            "request_metadata": {"synthetic_prober": True},
        },
        producer="nlp.answer.v1",
    )

    alerts = list(agent.handle(drift_answer))
    assert len(alerts) == 1
    alert = alerts[0]
    assert alert.envelope.topic == NLP_ALERT_V1
    assert alert.payload["kind"] == "prober_drift_detected"
    assert alert.payload["drift_field"] == "outbound_checksum"


def test_nlp_prober_ignores_non_synthetic_answers(tmp_path: Path) -> None:
    corpus_path = _make_corpus_file(tmp_path)
    agent = NlpProberAgent(corpus_path=str(corpus_path), clock=lambda: 0.0)
    agent.on_heartbeat()

    answer = Message.new(
        topic="qa.answer.v1",
        payload={
            "request_id": "prober-001",
            "intent_id": "predict.match_outcome",
            "top_1_entity_id": "team:galatasaray",
            "post_render_template_sha": "sha256:000",
            "outbound_checksum": "sha256:111",
        },
        producer="nlp.answer.v1",
    )
    alerts = list(agent.handle(answer))

    assert alerts == []
