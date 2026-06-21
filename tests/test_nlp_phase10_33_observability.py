"""Phase 10 §10.14 proof coverage: telemetry event bodies must stay PII-clean."""
from __future__ import annotations

import json
from pathlib import Path

from common.security.patterns import PII_PATTERNS
from common.security.tr_pii import redact_tr_pii
from swarm.agents.nlp import NlpIntentAgent
from swarm.agents.topics import QA_REQUEST_V1
from swarm.sdk.types import Message


def _assert_payload_contains_no_pii(payload: object) -> None:
    if isinstance(payload, str):
        for _, pattern in PII_PATTERNS:
            assert pattern.search(payload) is None, (
                f"PII pattern found in telemetry payload string: {payload!r}"
            )
        return
    if isinstance(payload, dict):
        for value in payload.values():
            _assert_payload_contains_no_pii(value)
        return
    if isinstance(payload, list):
        for item in payload:
            _assert_payload_contains_no_pii(item)
        return


def _load_eval_corpus_rows() -> list[object]:
    corpus_path = Path(__file__).resolve().parents[2] / "data" / "nlp" / "eval_corpus" / "2026q2.jsonl"
    text = corpus_path.read_text(encoding="utf-8")
    rows: list[object] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def test_phase10_18_eval_harness_corpus_is_pii_clean() -> None:
    rows = _load_eval_corpus_rows()
    assert len(rows) >= 2, "Expected the eval corpus to contain at least two rows."

    for row in rows:
        if isinstance(row, dict) and row.get("_meta") is not None:
            continue
        _assert_payload_contains_no_pii(row)


def test_phase10_14_telemetry_no_pii_in_event_body() -> None:
    corpus_path = Path(__file__).resolve().parent / "fixtures" / "tr_pii_corpus.json"
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    assert len(corpus) >= 60

    agent = NlpIntentAgent()
    output_messages: list[Message] = []
    repeated = (corpus * ((500 + len(corpus) - 1) // len(corpus)))[:500]

    for index, row in enumerate(repeated):
        redacted_text, _ = redact_tr_pii(str(row["text"]))
        request_id = f"pii-test-{index:04d}"
        msg = Message.new(
            topic=QA_REQUEST_V1,
            payload={
                "schema_version": 1,
                "request_id": request_id,
                "qa_correlation_id": f"qc-{index:04d}",
                "locale": "tr-TR",
                "input_source": "keyboard",
                "sanitized_text": redacted_text,
            },
            producer="test",
        )
        output_messages.extend(agent.handle(msg))

    assert output_messages, "Expected NLP intent agent to emit telemetry-relevant output."
    for message in output_messages:
        _assert_payload_contains_no_pii(message.payload)
