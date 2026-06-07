from __future__ import annotations

from __future__ import annotations

import json
from pathlib import Path

import pytest

from swarm.agents.nlp import NlpDispatcherAgent
from swarm.agents.topics import MAINT_EVENT, QA_INTENT_V1
from swarm.sdk.types import Message


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, object] = {}
        self.expiry: dict[str, float] = {}

    def incr(self, key: str) -> int:
        self.store[key] = int(self.store.get(key, 0)) + 1
        return int(self.store[key])

    def decr(self, key: str) -> int:
        self.store[key] = int(self.store.get(key, 0)) - 1
        return int(self.store[key])

    def expire(self, key: str, seconds: int) -> bool:
        self.expiry[key] = seconds
        return True

    def set(self, key: str, value: object, ex: int | None = None) -> None:
        self.store[key] = value
        if ex is not None:
            self.expiry[key] = ex

    def getdel(self, key: str) -> object | None:
        return self.store.pop(key, None)


def test_capture_if_armed_executes_work_once_and_writes_capture_file(tmp_path: Path) -> None:
    redis_client = FakeRedis()
    capture = NlpDispatcherAgent(
        clock_iso=lambda: "2026-06-06T00:00:00Z",
        new_id=lambda: "test-corr-id",
        redis_client=redis_client,
        base_data_dir=tmp_path,
    )._flame_capture

    invocation_count = 0

    def work() -> list[Message]:
        nonlocal invocation_count
        invocation_count += 1
        return []

    capture.arm(
        request_id="request-1",
        qa_correlation_id="",
        ttl_h=24,
        operator_id_h="op-1",
        reason="test arm",
    )

    result = capture.capture_if_armed(
        request_id="request-1",
        qa_correlation_id="",
        work=work,
    )

    assert invocation_count == 1
    assert len(result) == 1
    assert result[0].envelope.topic == MAINT_EVENT
    assert result[0].payload.get("kind") == "nlp_flame_captured"
    capture_path = tmp_path / "nlp" / "flame_captures" / "request-1.flame.json"
    assert capture_path.exists()
    capture_payload = json.loads(capture_path.read_text(encoding="utf-8"))
    assert isinstance(capture_payload.get("stages"), list)
    assert capture_payload["stages"][0]["stage_name"] == "10.31.8_request_entry"


def test_nlp_flame_capture_armed_count_gauge_is_updated_and_request_id_round_trips(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis_client = FakeRedis()
    capture = NlpDispatcherAgent(
        clock_iso=lambda: "2026-06-06T00:00:00Z",
        new_id=lambda: "test-corr-id",
        redis_client=redis_client,
        base_data_dir=tmp_path,
    )._flame_capture

    class FakeGauge:
        def __init__(self) -> None:
            self.value = 0

        def inc(self) -> None:
            self.value += 1

        def dec(self) -> None:
            self.value -= 1

    fake_gauge = FakeGauge()
    monkeypatch.setattr(
        "swarm.agents.nlp._flame_capture.NLP_FLAME_CAPTURE_ARMED_COUNT",
        fake_gauge,
    )

    capture.arm(
        request_id="request-1",
        qa_correlation_id="",
        ttl_h=24,
        operator_id_h="op-1",
        reason="test arm",
    )
    assert fake_gauge.value == 1

    result = capture.capture_if_armed(
        request_id="request-1",
        qa_correlation_id="",
        work=lambda: [],
    )

    assert fake_gauge.value == 0
    assert any(
        output.envelope.topic == MAINT_EVENT
        and output.payload.get("kind") == "nlp_flame_captured"
        and output.payload.get("request_id") == "request-1"
        for output in result
    )
    capture_path = tmp_path / "nlp" / "flame_captures" / "request-1.flame.json"
    assert capture_path.exists()
    capture_payload = json.loads(capture_path.read_text(encoding="utf-8"))
    assert isinstance(capture_payload.get("stages"), list)


def test_nlp_dispatcher_round_trip_flame_capture(tmp_path: Path) -> None:
    redis_client = FakeRedis()
    agent = NlpDispatcherAgent(
        clock_iso=lambda: "2026-06-06T00:00:00Z",
        new_id=lambda: "test-corr-id",
        redis_client=redis_client,
        base_data_dir=tmp_path,
    )

    arm_msg = Message.new(
        topic=MAINT_EVENT,
        payload={
            "kind": "nlp_flame_armed",
            "kind_schema_version": 1,
            "target": "nlp.flame_capture",
            "operator_id_h": "op-1",
            "request_id": "request-1",
            "qa_correlation_id": "",
            "ttl_h": 24,
            "reason": "investigate slow request",
            "produced_at": "2026-06-06T00:00:00Z",
        },
        producer="opsctl",
    )
    assert list(agent.handle(arm_msg)) == []

    intent_msg = Message.new(
        topic=QA_INTENT_V1,
        payload={
            "request_id": "request-1",
            "qa_correlation_id": "qa-1",
            "intent": "meta.help",
            "normalized_text": "Yardım",
            "entities": [],
            "query_style": "natural",
        },
        producer="test",
    )

    outputs = list(agent.handle(intent_msg))
    assert any(
        output.envelope.topic == MAINT_EVENT
        and output.payload.get("kind") == "nlp_flame_captured"
        for output in outputs
    )
    capture_path = tmp_path / "nlp" / "flame_captures" / "request-1.flame.json"
    assert capture_path.exists()
    capture_payload = json.loads(capture_path.read_text(encoding="utf-8"))
    assert isinstance(capture_payload.get("stages"), list)
    assert any(stage["stage_name"].startswith("10.31.8_") for stage in capture_payload["stages"])
    assert any(stage["stage_name"] == "10.8_answer_render" for stage in capture_payload["stages"])
