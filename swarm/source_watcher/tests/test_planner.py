"""Tests for the planner — pure logic, no I/O."""

from __future__ import annotations

from swarm.source_watcher.classifier import classify
from swarm.source_watcher.differ import FieldDiff
from swarm.source_watcher.planner import (
    ACTION_OPEN_TICKET,
    ACTION_PAGE_HUMAN,
    ACTION_REFRESH_FIXTURES,
    ACTION_RUN_PARITY_TESTS,
    ACTION_SKIP,
    plan,
)


def test_empty_diffs_produce_skip_plan() -> None:
    p = plan("mackolik", classify([]))
    assert p.actions == [ACTION_SKIP]
    assert p.severity == "cosmetic"
    assert "mackolik" in p.summary
    assert p.diffs == []


def test_cosmetic_only_diffs_produce_skip() -> None:
    diffs = [FieldDiff(path="$.name", kind="changed", old=" foo ", new="foo")]
    p = plan("nesine", classify(diffs))
    assert p.severity == "cosmetic"
    assert p.actions == [ACTION_SKIP]


def test_semantic_changes_trigger_parity_and_refresh() -> None:
    diffs = [
        FieldDiff(path="$.score", kind="changed", old=1, new=2),
        FieldDiff(path="$.new_field", kind="added", new="hi"),
    ]
    p = plan("tff", classify(diffs))
    assert p.severity == "semantic"
    assert ACTION_RUN_PARITY_TESTS in p.actions
    assert ACTION_REFRESH_FIXTURES in p.actions
    assert ACTION_PAGE_HUMAN not in p.actions


def test_schema_breaking_pages_human() -> None:
    diffs = [FieldDiff(path="$.id", kind="type_changed", old="x", new=1)]
    p = plan("openfootball", classify(diffs))
    assert p.severity == "schema_breaking"
    assert ACTION_PAGE_HUMAN in p.actions
    assert ACTION_OPEN_TICKET in p.actions
    assert "HUMAN ATTENTION" in p.summary


def test_severity_picked_by_worst_diff() -> None:
    diffs = [
        FieldDiff(path="$.a", kind="changed", old=1, new=2),     # semantic
        FieldDiff(path="$.b", kind="removed", old="x"),          # schema_breaking
        FieldDiff(path="$.c", kind="added", new="y"),            # semantic
    ]
    p = plan("any", classify(diffs))
    assert p.severity == "schema_breaking"


def test_plan_round_trips_to_dict() -> None:
    diffs = [FieldDiff(path="$.x", kind="changed", old=1, new=2)]
    p = plan("src", classify(diffs))
    d = p.to_dict()
    assert d["source"] == "src"
    assert d["severity"] == "semantic"
    assert isinstance(d["diffs"], list)
    assert d["diffs"][0]["path"] == "$.x"
