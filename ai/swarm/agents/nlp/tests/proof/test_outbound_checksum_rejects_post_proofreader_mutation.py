from __future__ import annotations

from common.config import cfg
from pytest import MonkeyPatch

from swarm.agents.nlp import (
    _make_qa_answer_payload,
    verify_qa_answer_envelope_signature,
)


def _minimal_citation() -> dict[str, object]:
    return {
        "kind": "prediction",
        "prediction_id": "pred-001",
        "produced_at_utc": "2026-05-26T10:00:00Z",
        "model_versions": ["predictor@1.2.3"],
        "calibration_version": "1.0.0",
    }


def _minimal_v3_answer() -> dict[str, object]:
    return _make_qa_answer_payload(
        request_id="req-001",
        qa_correlation_id="qa-001",
        intent="predict.match_outcome",
        kind="direct",
        answer_text="Galatasaray yarın kazanacak.",
        citations=[_minimal_citation()],
        schema_version=3,
    )


def test_outbound_checksum_rejects_post_proofreader_mutation(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(cfg, "profile", "mock")

    payload = _minimal_v3_answer()
    assert verify_qa_answer_envelope_signature(payload)

    mutated = dict(payload)
    mutated_parts = [dict(part) for part in mutated.get("parts", []) if isinstance(part, dict)]
    if mutated_parts:
        mutated_parts[0]["body"] = mutated_parts[0]["body"].replace("Galatasaray", "GalataSaray")
        mutated["parts"] = mutated_parts
    mutated["answer_text"] = mutated["answer_text"].replace("Galatasaray", "GalataSaray")

    assert not verify_qa_answer_envelope_signature(mutated)
