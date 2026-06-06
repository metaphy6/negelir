"""Phase 10 §10.25 proof coverage for NLP event/alert kind registration."""
from __future__ import annotations

import swarm.sdk.schemas as bus_schemas


def test_phase10_25_nlp_event_kinds_are_registered() -> None:
    expected_event_kinds = {
        "conversation_entity_overridden",
        "streaming_client_slow_canceled",
        "active_learning_queue_overflow",
        "compliance_refusal_triggered",
        "nlp_intent_rolled_back",
        "nlp_audit_rerender_executed",
        "disclosure_emitted",
        "disclosure_locale_fallback",
    }
    actual_event_kinds = set(bus_schemas.known_kinds("nlp.event.v1"))
    missing = expected_event_kinds - actual_event_kinds
    assert not missing, f"§10.25 event kinds missing from nlp.event.v1 schema: {missing}"


def test_phase10_25_nlp_alert_kinds_are_documented() -> None:
    expected_alert_kinds = {
        "conversation_context_cleared_after_block",
        "streaming_humanizer_chunk_blocked",
        "nlp_compatibility_quartet_mismatch",
        "lexicon_coverage_below_floor",
        "lexicon_stale",
        "nlp_consensus_smoke_failed",
        "humanizer_subprocess_died",
    }
    schema = bus_schemas.load("nlp.alert.v1")
    description = schema["properties"]["kind"]["description"]
    missing = sorted(kind for kind in expected_alert_kinds if kind not in description)
    assert not missing, f"§10.25 alert kinds missing from nlp.alert.v1 schema docs: {missing}"
