"""Phase 19 §19.8 — Promotion pre-flight outputs machine-readable report."""
import pytest
import json


def test_promotion_preflight_outputs_machine_readable_report():
    """Promotion pre-flight generates a machine-readable YAML/JSON report."""
    from xops.leagues.promotion_ceremony import PromotionCeremony
    
    ceremony = PromotionCeremony()
    report = ceremony.generate_preflight_report("br_serie_a", tier_to="T2", output_format="json")
    
    # Must be valid JSON
    data = json.loads(report)
    assert "ready" in data
    assert "gates" in data
    assert isinstance(data["ready"], bool)


def test_preflight_report_lists_all_gates():
    """Preflight report includes every gate with status."""
    from xops.leagues.promotion_ceremony import PromotionCeremony
    
    ceremony = PromotionCeremony()
    report = ceremony.generate_preflight_report("br_serie_a", tier_to="T2", output_format="json")
    
    data = json.loads(report)
    gates = data["gates"]
    
    required_gates = [
        "calibration_status",
        "nlp_recall",
        "data_completeness",
        "source_availability",
    ]
    for gate in required_gates:
        assert any(gate in g["name"] for g in gates), f"Missing gate: {gate}"


def test_preflight_report_includes_timestamp():
    """Preflight report includes generation timestamp."""
    from xops.leagues.promotion_ceremony import PromotionCeremony
    
    ceremony = PromotionCeremony()
    report = ceremony.generate_preflight_report("br_serie_a", tier_to="T2")
    
    data = json.loads(report)
    assert "generated_at" in data
