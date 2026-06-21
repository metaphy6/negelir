"""Phase 2.8.5 end-to-end tampered-seed test.

Flow:
  1. Baseline snapshot for a source.
  2. Tamper the payload (drop a top-level key + flip a value's type) →
     schema_breaking drift.
  3. New snapshot; diff + classify vs baseline.
  4. Assert: classifier emits ``schema_breaking`` entries; planner
     escalates to OPEN_TICKET + PAGE_HUMAN (never SKIP).

Uses a tmp ``HISTORY_ROOT`` so the real on-disk history isn't mutated.
"""

from __future__ import annotations

import json
from pathlib import Path

from swarm.source_watcher import snapshot_store
from swarm.source_watcher.classifier import SCHEMA_BREAKING, classify, worst_severity
from swarm.source_watcher.differ import diff_json
from swarm.source_watcher.planner import (
    ACTION_OPEN_TICKET,
    ACTION_PAGE_HUMAN,
    ACTION_SKIP,
    plan,
)

BASELINE = {
    "name": "Turkish Süper Lig 2024-25",
    "rounds": [
        {
            "matchday": 1,
            "matches": [
                {"home": "Galatasaray", "away": "Fenerbahçe", "score": {"ft": [2, 1]}},
                {"home": "Beşiktaş",    "away": "Trabzonspor", "score": {"ft": [1, 1]}},
            ],
        },
    ],
    "teams": [{"id": "GS", "name": "Galatasaray"}, {"id": "FB", "name": "Fenerbahçe"}],
}


def test_tampered_seed_triggers_schema_breaking_plan(tmp_path: Path) -> None:
    history = tmp_path / "history"
    source = "openfootball.local"

    baseline_snap = snapshot_store.store(source, BASELINE, root=history, now="2026-04-20T09-00-00Z")
    assert baseline_snap.sha256
    assert snapshot_store.latest(source, root=history) is not None

    # Tamper: drop 'teams' entirely (schema removal) and flip a nested type.
    tampered = json.loads(json.dumps(BASELINE))
    tampered.pop("teams")
    tampered["rounds"][0]["matches"][0]["score"]["ft"] = "2-1"    # list → str

    tampered_snap = snapshot_store.store(source, tampered, root=history, now="2026-04-20T09-00-05Z")
    assert tampered_snap.sha256 != baseline_snap.sha256

    prev = snapshot_store.previous(source, root=history)
    assert prev is not None and prev.sha256 == baseline_snap.sha256

    diffs = diff_json(prev.payload, tampered_snap.payload)
    assert diffs, "tampered seed must produce a non-empty diff"

    classified = classify(diffs)
    severities = {c.severity for c in classified}
    assert SCHEMA_BREAKING in severities, (
        f"dropping a top-level key must be schema_breaking; got {severities}"
    )
    assert worst_severity(classified) == SCHEMA_BREAKING

    update_plan = plan(source, classified)
    assert ACTION_OPEN_TICKET in update_plan.actions
    assert ACTION_PAGE_HUMAN in update_plan.actions
    assert ACTION_SKIP not in update_plan.actions


def test_cosmetic_tamper_produces_only_skip(tmp_path: Path) -> None:
    """Whitespace-only change → cosmetic severity → planner=SKIP only."""
    history = tmp_path / "history"
    source = "cosmetic.local"

    snapshot_store.store(source, {"greeting": "merhaba"}, root=history, now="2026-04-20T09-00-00Z")
    snapshot_store.store(source, {"greeting": "merhaba "}, root=history, now="2026-04-20T09-00-05Z")

    prev = snapshot_store.previous(source, root=history)
    cur = snapshot_store.latest(source, root=history)
    assert prev and cur and prev.sha256 != cur.sha256

    diffs = diff_json(prev.payload, cur.payload)
    classified = classify(diffs)
    assert all(c.severity == "cosmetic" for c in classified)

    update_plan = plan(source, classified)
    assert update_plan.actions == [ACTION_SKIP]


def test_planner_skips_on_empty_classification() -> None:
    update_plan = plan("noop.local", [])
    assert update_plan.actions == [ACTION_SKIP]
    assert update_plan.severity == "cosmetic"
