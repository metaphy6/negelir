from __future__ import annotations

import ai.swarm.sdk.schemas as bus_schemas


def test_phase10_23_nlp_event_and_alert_kinds_are_registered() -> None:
    """Verify Phase 10 §10.23 event and alert kinds are present in the wire schemas."""
    expected_event_kinds = {
        "fairness_key_evicted",
        "cache_signature_dropped",
        "safe_mode_engaged",
        "safe_mode_exited",
        "canary_shadow_disagreement",
    }
    actual_event_kinds = set(bus_schemas.known_kinds("nlp.event.v1"))
    missing_event_kinds = expected_event_kinds - actual_event_kinds
    assert not missing_event_kinds, (
        f"§10.23 event kinds missing from nlp.event.v1 schema: {missing_event_kinds}"
    )

    expected_alert_kinds = {
        "nlp_tenant_intake_abuse",
        "nlp_canary_rolled_back",
        "nlp_weekly_eval_regression",
        "nlp_humanizer_pod_budget_exceeded",
        "nlp_l1_cache_signature_invalid",
        "nlp_safe_mode_active",
        "canary_promotion_blocked",
    }
    alert_schema = bus_schemas.load("nlp.alert.v1")
    alert_description = alert_schema["properties"]["kind"]["description"]
    missing_alert_kinds = sorted(
        kind for kind in expected_alert_kinds if kind not in alert_description
    )
    assert not missing_alert_kinds, (
        f"§10.23 alert kinds missing from nlp.alert.v1 schema docs: {missing_alert_kinds}"
    )
