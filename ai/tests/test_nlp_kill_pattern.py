"""Phase 10 §10.27.4 — proof tests for operator NLP kill-pattern arms."""
from __future__ import annotations

import ast
import datetime as _dt
from pathlib import Path

import pytest

from ai.common.config import cfg
from ai.swarm.agents.nlp import NlpAnswerAgent


def _make_payload(**kwargs) -> dict[str, object]:
    payload = {
        "kind": "nlp_kill_pattern_armed",
        "kind_schema_version": 1,
        "target": "nlp.kill_pattern",
        "request_id": "req-001",
        "client_id": "opsctl",
        "produced_at": "2026-06-05T00:00:00Z",
        "operator_id_h": "operator-123",
        "pattern_pack_sha8": "pksha8",
        "ttl_s": 3600,
        "reason": "test",
    }
    payload.update(kwargs)
    return payload


def test_kill_pattern_arm_increments_generation() -> None:
    agent = NlpAnswerAgent()
    assert agent._kill_pattern_generation == 0
    msgs = list(agent._arm_kill_pattern(_make_payload()))
    assert len(msgs) == 1
    assert agent._kill_pattern_generation == 1
    assert "pksha8" in agent._kill_patterns


def test_kill_pattern_ttl_capped_at_opsctl_nlp_kill_max_ttl_s(monkeypatch) -> None:
    agent = NlpAnswerAgent()
    now = _dt.datetime(2026, 6, 5, 0, 0, tzinfo=_dt.timezone.utc)
    agent._utcnow = lambda: now
    monkeypatch.setattr(cfg, "opsctl_nlp_kill_max_ttl_s", 1)

    msgs = list(agent._arm_kill_pattern(_make_payload(ttl_s=3600)))
    assert len(msgs) == 1
    pattern = agent._kill_patterns["pksha8"]
    assert pattern["expires_at"] == now + _dt.timedelta(seconds=1)


def test_kill_pattern_disarm_removes_pattern_and_increments_generation() -> None:
    agent = NlpAnswerAgent()
    list(agent._arm_kill_pattern(_make_payload()))
    assert "pksha8" in agent._kill_patterns
    assert agent._kill_pattern_generation == 1

    msgs = list(agent._disarm_kill_pattern({"pattern_pack_sha8": "pksha8"}))
    assert len(msgs) == 1
    assert "pksha8" not in agent._kill_patterns
    assert agent._kill_pattern_generation == 2


def test_kill_pattern_pack_no_regex_compile_path() -> None:
    source = Path(__file__).resolve().parents[1] / "swarm" / "agents" / "nlp" / "__init__.py"
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))

    class_defs = [
        node for node in tree.body if isinstance(node, ast.ClassDef)
        and node.name == "NlpAnswerAgent"
    ]
    assert len(class_defs) == 1
    class_node = class_defs[0]

    function_defs = [
        node for node in class_node.body if isinstance(node, ast.FunctionDef)
        and node.name == "_kill_pattern_filter_matches"
    ]
    assert len(function_defs) == 1
    function_def = function_defs[0]

    for node in ast.walk(function_def):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr == "compile":
                assert not (
                    isinstance(func.value, ast.Name) and func.value.id == "re"
                ), "regex compilation found in _kill_pattern_filter_matches"
            if isinstance(func, ast.Name) and func.id == "compile":
                assert False, "compile() call found in _kill_pattern_filter_matches"


def test_arm_stale_payload_is_ignored(monkeypatch) -> None:
    agent = NlpAnswerAgent()
    now = _dt.datetime(2026, 6, 5, 0, 0, tzinfo=_dt.timezone.utc)
    agent._utcnow = lambda: now
    payload = _make_payload(ttl_s=0)
    msgs = list(agent._arm_kill_pattern(payload))
    assert msgs == []
    assert agent._kill_pattern_generation == 0
