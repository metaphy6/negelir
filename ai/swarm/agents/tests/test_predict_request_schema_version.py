"""Phase 8 §8.16.12 — predict.request schema-version compatibility.

The additive `qa_correlation_id` field must not break legacy payloads.
Legacy producers omit `kind_schema_version` entirely (treated as v1);
current producers emit v2.
"""
from __future__ import annotations

from swarm.agents.payloads import PredictRequest
from swarm.sdk.schemas import validate


def test_predict_request_current_payload_emits_kind_schema_version_2() -> None:
    payload = PredictRequest(
        request_id="req-1",
        match_id="match-1",
        market="1x2",
        qa_correlation_id="qa-1",
    ).as_dict()

    assert payload["kind_schema_version"] == 2
    assert validate("predict.request", payload) == []


def test_predict_request_legacy_payload_without_version_still_validates() -> None:
    legacy_payload = {
        "request_id": "req-legacy",
        "match_id": "match-1",
        "market": "1x2",
    }

    assert validate("predict.request", legacy_payload) == []
    req = PredictRequest.from_dict(legacy_payload)
    assert req.kind_schema_version == 1
    assert req.qa_correlation_id is None


def test_predict_request_explicit_legacy_version_remains_accepted() -> None:
    legacy_payload = {
        "request_id": "req-legacy-v1",
        "match_id": "match-1",
        "market": "1x2",
        "kind_schema_version": 1,
    }

    assert validate("predict.request", legacy_payload) == []
    assert PredictRequest.from_dict(legacy_payload).kind_schema_version == 1