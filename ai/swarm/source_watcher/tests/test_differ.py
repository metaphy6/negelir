"""Tests for the source_watcher differ + classifier (Phase 2.8 scaffolding)."""

from __future__ import annotations

from ai.swarm.source_watcher.classifier import (
    COSMETIC,
    SCHEMA_BREAKING,
    SEMANTIC,
    classify,
    worst_severity,
)
from ai.swarm.source_watcher.differ import diff_json, summarize


# ── differ ────────────────────────────────────────────────────


def test_diff_identical_payloads_is_empty() -> None:
    assert diff_json({"a": 1}, {"a": 1}) == []


def test_diff_detects_added_removed_changed() -> None:
    diffs = diff_json(
        {"a": 1, "b": 2, "c": 3},
        {"a": 1, "b": 99, "d": 4},
    )
    kinds = sorted(d.kind for d in diffs)
    assert kinds == ["added", "changed", "removed"]


def test_diff_detects_type_change() -> None:
    diffs = diff_json({"score": 2}, {"score": "two"})
    assert len(diffs) == 1
    assert diffs[0].kind == "type_changed"


def test_diff_descends_into_lists() -> None:
    diffs = diff_json(
        {"matches": [{"home": "A", "away": "B"}]},
        {"matches": [{"home": "A", "away": "C"}]},
    )
    assert len(diffs) == 1
    assert diffs[0].path == "$.matches[0].away"


def test_summarize_counts_kinds() -> None:
    diffs = diff_json({"a": 1, "b": 2}, {"a": 2, "c": 3})
    counts = summarize(diffs)
    assert counts["changed"] == 1
    assert counts["added"] == 1
    assert counts["removed"] == 1


# ── classifier ────────────────────────────────────────────────


def test_removed_field_is_schema_breaking() -> None:
    diffs = diff_json({"a": 1, "b": 2}, {"a": 1})
    assert worst_severity(classify(diffs)) == SCHEMA_BREAKING


def test_added_field_is_semantic() -> None:
    diffs = diff_json({"a": 1}, {"a": 1, "b": 2})
    assert worst_severity(classify(diffs)) == SEMANTIC


def test_whitespace_change_is_cosmetic() -> None:
    diffs = diff_json({"name": "Galatasaray "}, {"name": "Galatasaray"})
    assert worst_severity(classify(diffs)) == COSMETIC


def test_worst_severity_picks_highest() -> None:
    diffs = diff_json(
        {"a": 1, "b": "x ", "c": 3},
        {"a": "1", "b": "x"},  # type change wins
    )
    assert worst_severity(classify(diffs)) == SCHEMA_BREAKING
