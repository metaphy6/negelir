"""Phase 2.8.4 integration test: snapshot_store + planner end-to-end
against frozen fixtures committed under ./fixtures/.

Exercises:
  • Loading two versions of the same source from disk.
  • Storing both as snapshots in a tmp history root.
  • Running the classifier on the diff.
  • Asserting the planner's action set is the one documented in
    ROADMAP §2.8 for schema-breaking drift.

No network, no LLM, no mocks — pure data-in / assertion-out.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from swarm.source_watcher import snapshot_store
from swarm.source_watcher.classifier import SCHEMA_BREAKING, classify, worst_severity
from swarm.source_watcher.differ import diff_json
from swarm.source_watcher.planner import (
    ACTION_OPEN_TICKET,
    ACTION_PAGE_HUMAN,
    ACTION_RUN_PARITY_TESTS,
    plan,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_openfootball_v1_vs_v2_schema_breaking(tmp_path: Path) -> None:
    v1 = _load("openfootball_v1.json")
    v2 = _load("openfootball_v2_breaking.json")

    history = tmp_path / "history"
    source = "openfootball.local"

    s1 = snapshot_store.store(source, v1, root=history, now="2026-04-20T09-00-00Z")
    s2 = snapshot_store.store(source, v2, root=history, now="2026-04-20T09-00-05Z")
    assert s1.sha256 != s2.sha256

    diffs = diff_json(s1.payload, s2.payload)
    classified = classify(diffs)
    assert worst_severity(classified) == SCHEMA_BREAKING, (
        "dropping 'teams' and flipping score.ft type must be schema_breaking"
    )

    plan_out = plan(source, classified)
    # Three actions from ROADMAP §2.8 for schema-breaking drift
    assert ACTION_RUN_PARITY_TESTS in plan_out.actions
    assert ACTION_OPEN_TICKET in plan_out.actions
    assert ACTION_PAGE_HUMAN in plan_out.actions


def test_snapshot_roundtrip_persists_fixture_unchanged(tmp_path: Path) -> None:
    v1 = _load("openfootball_v1.json")
    history = tmp_path / "history"

    stored = snapshot_store.store("of.local", v1, root=history)
    fetched = snapshot_store.latest("of.local", root=history)
    assert fetched is not None
    assert fetched.payload == v1
    assert fetched.sha256 == stored.sha256


def test_two_identical_snapshots_are_idempotent(tmp_path: Path) -> None:
    v1 = _load("openfootball_v1.json")
    history = tmp_path / "history"

    s1 = snapshot_store.store("of.local", v1, root=history)
    s2 = snapshot_store.store("of.local", v1, root=history)
    assert s1.sha256 == s2.sha256
    # Same path → only one file on disk.
    assert s1.path == s2.path
    files = snapshot_store.list_snapshots("of.local", root=history)
    assert len(files) == 1
