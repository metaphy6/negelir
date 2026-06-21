"""Phase 10 §10.28 proof coverage for new NLP event/alert kinds."""
from __future__ import annotations

import ai.swarm.sdk.schemas as bus_schemas


def test_phase10_28_nlp_event_kinds_are_registered() -> None:
    expected_event_kinds = {
        "consonant_softening_repaired",
        "vowel_drop_repaired",
        "assimilation_folded",
        "compound_word_split",
        "loanword_variant_resolved",
        "fragment_detected",
        "preamble_strip_capped",
        "softg_restored",
        "meta_question_routed_query",
        "meta_question_routed_request",
        "meta_question_routed_info",
        "lexicon_rebuild_deferred_for_rss",
    }
    actual_event_kinds = set(bus_schemas.known_kinds("nlp.event.v1"))
    missing = expected_event_kinds - actual_event_kinds
    assert not missing, f"§10.28 event kinds missing from nlp.event.v1 schema: {missing}"


def test_phase10_28_nlp_alert_kinds_are_documented() -> None:
    expected_alert_kinds = {
        "nlp_pii_in_input_tc_kimlik",
        "nlp_pii_in_input_iban",
        "nlp_pii_in_input_phone",
        "nlp_pii_in_input_plate",
        "nlp_pii_in_input_vkn",
        "nlp_shout_rate_anomaly_per_subject",
        "lexicon_rebuild_queue_overflow",
        "nlp_request_budget_exhausted",
        "nlp_classifier_extractor_skew_high",
    }
    schema = bus_schemas.load("nlp.alert.v1")
    description = schema["properties"]["kind"]["description"]
    missing = sorted(kind for kind in expected_alert_kinds if kind not in description)
    assert not missing, f"§10.28 alert kinds missing from nlp.alert.v1 schema docs: {missing}"
