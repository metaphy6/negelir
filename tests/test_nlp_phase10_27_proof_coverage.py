"""Phase 10 §10.27 proof-coverage for new NLP event/alert kinds and config knobs."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from common.config import cfg
import swarm.sdk.schemas as bus_schemas


def test_phase10_27_nlp_event_kinds_are_registered() -> None:
    expected_event_kinds = {
        "nlp_pii_recovered_for_trace",
        "nlp_complaint_trace_completed",
        "nlp_complaint_trace_drift_detected",
        "nlp_kill_pattern_stale_armed_at_boot",
        "nlp_preview_token_budget_exhausted_per_operator",
    }
    actual_event_kinds = set(bus_schemas.known_kinds("nlp.event.v1"))
    missing = expected_event_kinds - actual_event_kinds
    assert not missing, f"§10.27 event kinds missing from nlp.event.v1 schema: {missing}"


def test_phase10_27_nlp_alert_kinds_are_documented() -> None:
    expected_alert_kinds = {
        "calibration_horizon_mismatch",
        "lexicon_swap_late",
        "lexicon_swap_lag_drained_to_503",
        "nlp_complaint_trace_drift",
        "nlp_kill_pattern_stale_armed_at_boot",
        "nlp_preview_token_budget_exhausted_per_operator",
    }
    schema = bus_schemas.load("nlp.alert.v1")
    description = schema["properties"]["kind"]["description"]
    missing = sorted(kind for kind in expected_alert_kinds if kind not in description)
    assert not missing, f"§10.27 alert kinds missing from nlp.alert.v1 schema docs: {missing}"


def test_phase10_27_maint_event_kind_schema_exists() -> None:
    payload = {
        "kind": "nlp_pii_recovered_for_trace",
        "kind_schema_version": 1,
        "request_id": "req-001",
        "operator_id_h": "op-123",
        "reason_text_sha8": "deadbeef",
        "produced_at": "2026-06-05T12:00:00Z",
    }
    errors = bus_schemas.validate("maint.event.v1", payload)
    assert errors == [], f"maint.event.v1 validation failed for nlp_pii_recovered_for_trace: {errors}"


def test_phase10_27_nlp_preview_dir_config_default() -> None:
    assert cfg.nlp_preview_dir == "data/nlp/preview"


def test_phase10_27_nlp_abuse_k8s_manifest_replicas_one() -> None:
    path = Path("infra") / "k8s" / "nlp" / "abuse" / "deployment.yaml"
    assert path.exists(), f"{path} must exist for Phase 14 K8s single-replica abuse deployment"
    assert re.search(r"^\s*replicas:\s*1\s*$", path.read_text(encoding="utf-8"), re.MULTILINE), (
        f"{path} must set replicas: 1 for single-publisher nlp.abuse.v1"
    )


def _find_nlp_agent_class(tree: ast.AST, class_name: str) -> ast.ClassDef | None:
    return next(
        (node for node in ast.walk(tree) if isinstance(node, ast.ClassDef) and node.name == class_name),
        None,
    )


def _build_parent_map(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    parents: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    return parents


def test_phase10_27_nlp_dispatcher_fixture_state_is_league_agnostic() -> None:
    source_path = Path(__file__).resolve().parents[1] / "swarm" / "agents" / "nlp" / "__init__.py"
    source_text = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source_text, filename=str(source_path))

    answer_class = _find_nlp_agent_class(tree, "NlpAnswerAgent")
    assert answer_class is not None, "NlpAnswerAgent class not found"

    on_predict_def = next(
        (member for member in answer_class.body if isinstance(member, ast.FunctionDef) and member.name == "_on_predict_approved"),
        None,
    )
    assert on_predict_def is not None, "NlpDispatcherAgent._on_predict_approved not found"

    parent_map = _build_parent_map(on_predict_def)
    league_terms = {"league", "league_id", "league_ids"}

    for node in ast.walk(on_predict_def):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if isinstance(node.func.value, ast.Name) and node.func.value.id == "FixtureStateLookup" and node.func.attr == "get":
                ancestor = parent_map.get(node)
                while ancestor is not None:
                    if isinstance(ancestor, ast.If):
                        for test_node in ast.walk(ancestor.test):
                            if isinstance(test_node, ast.Name) and test_node.id in league_terms:
                                raise AssertionError(
                                    "Fixture-state routing must not branch on league identifiers within the FixtureStateLookup path"
                                )
                            if isinstance(test_node, ast.Attribute) and test_node.attr in league_terms:
                                raise AssertionError(
                                    "Fixture-state routing must not branch on league identifiers within the FixtureStateLookup path"
                                )
                    ancestor = parent_map.get(ancestor)


def test_phase10_27_nlp_disclosures_tier_blind_ast() -> None:
    source_path = Path(__file__).resolve().parents[1] / "swarm" / "agents" / "nlp" / "__init__.py"
    source_text = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source_text, filename=str(source_path))

    answer_class = _find_nlp_agent_class(tree, "NlpAnswerAgent")
    assert answer_class is not None, "NlpAnswerAgent class not found"

    append_def = next(
        (member for member in answer_class.body if isinstance(member, ast.FunctionDef) and member.name == "_append_disclosures"),
        None,
    )
    assert append_def is not None, "NlpDispatcherAgent._append_disclosures not found"

    for node in ast.walk(append_def):
        if isinstance(node, ast.Name) and node.id in {"tier_id_required", "tier"}:
            raise AssertionError(
                "Disclosure assembly must not branch on tier or tier_id_required in NlpDispatcherAgent._append_disclosures"
            )


def test_phase10_27_nlp_preview_budget_ignores_tier_ast() -> None:
    source_path = Path(__file__).resolve().parents[1] / "swarm" / "agents" / "nlp" / "__init__.py"
    source_text = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source_text, filename=str(source_path))

    answer_class = _find_nlp_agent_class(tree, "NlpAnswerAgent")
    assert answer_class is not None, "NlpAnswerAgent class not found"

    for fn_name in {"_preview_budget_available", "_consume_preview_tokens"}:
        fn_def = next(
            (member for member in answer_class.body if isinstance(member, ast.FunctionDef) and member.name == fn_name),
            None,
        )
        assert fn_def is not None, f"NlpDispatcherAgent.{fn_name} not found"
        for node in ast.walk(fn_def):
            if isinstance(node, ast.Name) and node.id in {"tier_id_required", "tier"}:
                raise AssertionError(
                    f"Preview budgeting must not branch on tier or tier_id_required in NlpDispatcherAgent.{fn_name}"
                )
