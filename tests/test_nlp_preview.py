"""Phase 10 §10.27.5 — operator preview metadata and shadow-row filtering."""
from __future__ import annotations

from ai.swarm.agents.nlp import _make_qa_answer_payload
from ai.swarm.agents.nlp.shadow_writer import NlpShadowWriter
from ai.swarm.agents.topics import QA_INTENT_V1
from ai.swarm.sdk.types import Message


def test_nlp_shadow_writer_drops_preview_rows() -> None:
    msg = Message.new(
        topic=QA_INTENT_V1,
        payload={
            "request_id": "req-preview-001",
            "request_metadata": {"preview": True},
        },
        producer="test",
    )

    out = NlpShadowWriter().handle(msg)

    assert out == []


def test_qa_answer_payload_preserves_preview_request_metadata() -> None:
    payload = _make_qa_answer_payload(
        request_id="req-preview-002",
        qa_correlation_id="corr-preview-002",
        intent="meta.help",
        kind="meta.help",
        answer_text="Bu bir önizleme yanıtıdır.",
        request_metadata={"preview": True},
        emitted_at_utc="2026-06-05T12:00:00Z",
    )

    assert payload["request_metadata"] == {"preview": True}


def test_qa_answer_payload_preserves_synthetic_prober_request_metadata() -> None:
    payload = _make_qa_answer_payload(
        request_id="req-prober-001",
        qa_correlation_id="corr-prober-001",
        intent="predict.match_outcome",
        kind="prediction",
        answer_text="Bu bir prober cevabıdır.",
        request_metadata={"synthetic_prober": True},
        emitted_at_utc="2026-06-05T12:00:00Z",
    )

    assert payload["request_metadata"] == {"synthetic_prober": True}
