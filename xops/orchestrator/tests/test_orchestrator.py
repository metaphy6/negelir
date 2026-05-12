"""Tests for the xops.orchestrator package.

Pure stdlib (pytest-style) — no compose, no network. Covers the four
contracts: ROADMAP parsing, include/exclude selection (the "exclude
9.17.11" requirement), parallel-safe locks, and the state machine.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from xops.orchestrator import locks, roadmap, selector, state

# A miniature ROADMAP fragment that exercises every grammar branch the
# real parser must handle: emoji-prefixed phase headings, R-prefixed
# pivot ids, dotted sub-phases, and three checkbox states.
FIXTURE = """\
# Title

## ⚙️ Phase 1 — Centralized Configuration
- [x] phase-level rollup (already done elsewhere)

### 1.1 Foundations
- [x] python config landed
- [ ] go config landed
- [~] deferred follow-up

#### 1.1.1 Sub-foundations
- [ ] add validator
- [ ] add round-trip test

### 1.2 Hardcode audit
- [ ] sweep ai/

## 🌐 Phase 2 — Mock Stack
### 2.1 Seed corpus
- [x] capture mackolik
- [x] capture nesine

## 📤 Phase R3 — Pivot v3 Feeds
### R3.1 FeedWriter
- [ ] implement writer
"""


@pytest.fixture()
def fixture_tree(tmp_path: Path):
    src = tmp_path / "ROADMAP.md"
    src.write_text(FIXTURE, encoding="utf-8")
    tree, source = roadmap.parse_roadmap(src)
    return tree, source


# ── roadmap.py ────────────────────────────────────────────────


def test_parse_extracts_root_phases_with_emoji_prefix(fixture_tree):
    tree, _ = fixture_tree
    assert "1" in tree.nodes
    assert "2" in tree.nodes
    assert "R3" in tree.nodes
    assert tree.nodes["1"].title.startswith("Centralized Configuration")
    assert tree.nodes["R3"].title.startswith("Pivot v3 Feeds")


def test_parse_resolves_parent_chain(fixture_tree):
    tree, _ = fixture_tree
    assert tree.nodes["1.1"].parent_id == "1"
    assert tree.nodes["1.1.1"].parent_id == "1.1"
    assert "1.1" in tree.nodes["1"].children
    assert "1.1.1" in tree.nodes["1.1"].children


def test_parse_classifies_checkbox_states(fixture_tree):
    tree, _ = fixture_tree
    n = tree.nodes["1.1"]
    states = [c.state for c in n.checkboxes]
    assert states.count("x") == 1
    assert states.count(" ") == 1
    assert states.count("~") == 1
    assert n.open_boxes == 1
    assert n.done_boxes == 1
    assert n.deferred_boxes == 1
    assert n.is_complete is False


def test_slice_returns_only_the_phase_body(fixture_tree):
    tree, source = fixture_tree
    body = tree.slice_text("1.1", source)
    assert body.startswith("### 1.1 Foundations")
    assert "1.1.1 Sub-foundations" in body
    assert "Phase 2" not in body
    assert "Hardcode audit" not in body


# ── selector.py ───────────────────────────────────────────────


def test_select_include_expands_descendants(fixture_tree):
    tree, _ = fixture_tree
    ids = selector.select_phase_ids(tree, include=["1"], leaves_only=True, skip_complete=False)
    assert "1.1.1" in ids
    assert "1.2" in ids
    assert "2.1" not in ids


def test_select_exclude_subtracts_subtree(fixture_tree):
    """The verbatim user requirement: 'exclude 9.17.11'."""
    tree, _ = fixture_tree
    ids = selector.select_phase_ids(
        tree, include=["1"], exclude=["1.1.1"], leaves_only=True, skip_complete=False
    )
    assert "1.1.1" not in ids
    assert "1.2" in ids


def test_select_skip_complete_drops_done_phases(fixture_tree):
    tree, _ = fixture_tree
    # 2.1 has both checkboxes ticked → considered complete.
    ids = selector.select_phase_ids(tree, include=["2"], leaves_only=True, skip_complete=True)
    assert "2.1" not in ids


def test_select_unknown_token_raises(fixture_tree):
    tree, _ = fixture_tree
    with pytest.raises(ValueError):
        selector.select_phase_ids(tree, include=["999.999"])


def test_parse_filter_handles_commas_and_whitespace():
    assert selector.parse_filter("1, 2 ,3.4") == ["1", "2", "3.4"]
    assert selector.parse_filter("") == []


# ── locks.py ──────────────────────────────────────────────────


@pytest.fixture()
def sandboxed_locks(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(locks, "LOCK_DIR", tmp_path / "locks")
    return tmp_path


def test_claim_then_second_claim_raises_LockBusy(sandboxed_locks):
    locks.try_claim("9.17.11", claimer_id="agent-a")
    with pytest.raises(locks.LockBusy):
        locks.try_claim("9.17.11", claimer_id="agent-b")
    assert locks.release("9.17.11") is True


def test_release_missing_lock_raises(sandboxed_locks):
    with pytest.raises(locks.LockMissing):
        locks.release("never.claimed")
    # force=True swallows the missing-file error.
    assert locks.release("never.claimed", force=True) is False


def test_inspect_and_list_held_round_trip(sandboxed_locks):
    locks.try_claim("1.1", claimer_id="agent-x")
    locks.try_claim("2.1", claimer_id="agent-y")
    held = {h.phase_id: h.claimer_id for h in locks.list_held()}
    assert held == {"1.1": "agent-x", "2.1": "agent-y"}
    assert locks.inspect("1.1").claimer_id == "agent-x"
    assert locks.inspect("never.held") is None
    locks.release("1.1")
    locks.release("2.1")


def test_contextmanager_releases_on_exit(sandboxed_locks):
    with locks.claim("R3.1") as h:
        assert h.phase_id == "R3.1"
        assert locks.inspect("R3.1") is not None
    assert locks.inspect("R3.1") is None


# ── state.py ──────────────────────────────────────────────────


@pytest.fixture()
def sandboxed_state(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(state, "STATE_DIR", tmp_path / "state")
    return tmp_path


def test_save_and_load_round_trip(sandboxed_state):
    s = state.PhaseState(phase_id="1.1", title="Foundations")
    state.transition(s, "implementing")
    state.record_pass(s, role="implementer", outcome="ok", model="opus-4.7", notes="wired config")
    state.save(s)

    loaded = state.load("1.1")
    assert loaded is not None
    assert loaded.status == "implementing"
    assert len(loaded.passes) == 1
    assert loaded.passes[0].role == "implementer"
    assert loaded.passes[0].model == "opus-4.7"


def test_transition_rejects_unknown_status(sandboxed_state):
    s = state.PhaseState(phase_id="1.1", title="x")
    with pytest.raises(ValueError):
        state.transition(s, "frobnicated")


def test_record_pass_rejects_unknown_role(sandboxed_state):
    s = state.PhaseState(phase_id="1.1", title="x")
    with pytest.raises(ValueError):
        state.record_pass(s, role="hacker", outcome="ok")


def test_list_states_returns_every_saved_phase(sandboxed_state):
    for pid in ("1.1", "2.1", "R3.1"):
        s = state.PhaseState(phase_id=pid, title=pid)
        state.save(s)
    ids = sorted(s.phase_id for s in state.list_states())
    assert ids == ["1.1", "2.1", "R3.1"]


def test_save_is_atomic(sandboxed_state, monkeypatch):
    """An interrupted save must not corrupt the on-disk file."""
    s = state.PhaseState(phase_id="1.1", title="x")
    state.save(s)
    original = state.state_path("1.1").read_text(encoding="utf-8")

    s2 = state.PhaseState(phase_id="1.1", title="x")
    # Force os.replace to fail mid-write.
    import os as _os
    real_replace = _os.replace

    def boom(*_a, **_k):
        raise OSError("simulated crash")

    monkeypatch.setattr(_os, "replace", boom)
    with pytest.raises(OSError):
        state.save(s2)
    monkeypatch.setattr(_os, "replace", real_replace)

    # Original content survived; no half-written tmp left behind in path.
    assert state.state_path("1.1").read_text(encoding="utf-8") == original


# ── End-to-end smoke (real ROADMAP) ───────────────────────────


def test_real_roadmap_parses_with_known_root_phases():
    tree, _ = roadmap.parse_roadmap()
    # Sanity: every emoji-prefixed root phase the README mentions is found.
    for pid in ("0", "1", "2", "9", "16", "17"):
        assert pid in tree.nodes, f"missing root phase {pid!r}"
    # Sub-phase grammar must work too.
    assert "16.1" in tree.nodes
    assert tree.nodes["16.1"].parent_id == "16"
