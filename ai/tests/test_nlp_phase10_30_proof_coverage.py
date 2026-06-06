"""Phase 10 §10.30 proof coverage for new NLP event/alert kinds."""
from __future__ import annotations

import swarm.sdk.schemas as bus_schemas


def test_phase10_30_nlp_event_kinds_are_registered() -> None:
    expected_event_kinds = {
        "sarcasm_cue_no_context",
        "pro_drop_resolved",
        "tr_output_grammar_violation",
        "lexicon_catalog_alias_resolved",
        "healthz_realism_probe_failed",
        "lexicon_canary_disagreement",
        "intent_decision_breakdown",
        "idiom_expansion",
        "idiom_ambiguous",
        "asr_punctuation_word_stripped",
        "repeated_query_threshold_crossed",
        "historical_venue_mentioned",
        "anaphora_antecedent_evicted",
        "obfuscated_slur_negated",
    }
    actual_event_kinds = set(bus_schemas.known_kinds("nlp.event.v1"))
    missing = expected_event_kinds - actual_event_kinds
    assert not missing, f"§10.30 event kinds missing from nlp.event.v1 schema: {missing}"


def test_phase10_30_nlp_alert_kinds_are_documented() -> None:
    expected_alert_kinds = {
        "sarcasm_cue_rate_drift",
        "tr_output_grammar_fallback_used",
        "tr_output_grammar_validator_killswitch_engaged",
        "negation_scope_distribution_drift",
        "refusal_reason_rate_spike",
        "lexicon_catalog_alias_conflict",
        "outbound_checksum_mismatch",
        "lexicon_canary_disagreement_above_threshold",
        "wh_prior_drift",
        "politeness_distribution_drift",
        "cache_subject_key_collision",
    }
    schema = bus_schemas.load("nlp.alert.v1")
    description = schema["properties"]["kind"]["description"]
    missing = sorted(kind for kind in expected_alert_kinds if kind not in description)
    assert not missing, f"§10.30 alert kinds missing from nlp.alert.v1 schema docs: {missing}"
