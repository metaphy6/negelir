"""Phase 8 §8.9 — Allowlist promote-while-evaluating race proof test.

Uses pg_advisory_lock semantics (modelled as threading.RLock in the
in-memory shim) to interleave: operator promotes pending→active while
sec.input.v1 is mid-evaluation.  Assert the eval sees a self-consistent
snapshot — either (row_state='p', in_cache=False) OR (row_state='a',
in_cache=True), never a split state.  Retried under load 100×.

Binding bullet: ROADMAP §8.9 DoD "Allowlist promote-while-evaluating race".
"""
from __future__ import annotations

import threading

import pytest

from swarm.agents.maint.sec import InMemoryPatternStore

_PATTERN = "/* SAFE_QUERY */"
_QID = "qid:test-race"
_NOW_PENDING = "2024-01-01T00:00:00+00:00"
_NOW_PROMOTED = "2024-01-01T01:00:00+00:00"
_TTL_S = 3600


# ── helpers ──────────────────────────────────────────────────────────────

def _fresh_store() -> InMemoryPatternStore:
    store = InMemoryPatternStore()
    store.upsert_pending(_PATTERN, qid=_QID, now_iso=_NOW_PENDING)
    return store


# ── unit-level snapshot consistency (no threading) ───────────────────────

def test_snapshot_pending_before_promote() -> None:
    """Before any promote, snapshot shows (state='p', in_cache=False)."""
    store = _fresh_store()
    snap = store.read_eval_snapshot(_PATTERN)
    assert snap is not None
    row_state, in_cache = snap
    assert row_state == "p"
    assert in_cache is False


def test_snapshot_active_after_promote() -> None:
    """After promote, snapshot shows (state='a', in_cache=True)."""
    store = _fresh_store()
    store.promote_to_active(_PATTERN, now_iso=_NOW_PROMOTED, ttl_s=_TTL_S)
    snap = store.read_eval_snapshot(_PATTERN)
    assert snap is not None
    row_state, in_cache = snap
    assert row_state == "a"
    assert in_cache is True


def test_snapshot_after_reset_to_pending() -> None:
    """After _reset_to_pending, snapshot shows (state='p', in_cache=False)."""
    store = _fresh_store()
    store.promote_to_active(_PATTERN, now_iso=_NOW_PROMOTED, ttl_s=_TTL_S)
    store._reset_to_pending(_PATTERN, qid=_QID, now_iso=_NOW_PENDING)
    snap = store.read_eval_snapshot(_PATTERN)
    assert snap is not None
    row_state, in_cache = snap
    assert row_state == "p"
    assert in_cache is False


def test_snapshot_unknown_pattern_returns_none() -> None:
    """read_eval_snapshot returns None for a pattern never inserted."""
    store = InMemoryPatternStore()
    assert store.read_eval_snapshot("unknown_pattern") is None


# ── concurrent race proof (100 rounds) ───────────────────────────────────

def test_no_split_state_under_promote_race() -> None:
    """Operator promotes pending→active 100× concurrent with evaluations.

    A split state is defined as:
    - row_state == 'a'  AND  in_active_cache == False  (DB ahead of cache)
    - row_state != 'a'  AND  in_active_cache == True   (cache ahead of DB)

    pg_advisory_lock semantics (threading.RLock) must prevent both.
    """
    store = _fresh_store()
    split_states: list[tuple[str, bool]] = []
    stop_event = threading.Event()

    def promoter() -> None:
        for i in range(100):
            now = f"2024-01-01T{i % 24:02d}:00:00+00:00"
            store.promote_to_active(_PATTERN, now_iso=now, ttl_s=_TTL_S)
            store._reset_to_pending(_PATTERN, qid=f"q{i}", now_iso=_NOW_PENDING)
        stop_event.set()

    def evaluator() -> None:
        while not stop_event.is_set():
            snap = store.read_eval_snapshot(_PATTERN)
            if snap is None:
                continue
            row_state, in_cache = snap
            # Consistency invariant: state=='a' ↔ in_cache
            if row_state == "a" and not in_cache:
                split_states.append((row_state, in_cache))
            elif row_state != "a" and in_cache:
                split_states.append((row_state, in_cache))

    t_evaluator = threading.Thread(target=evaluator, daemon=True)
    t_promoter = threading.Thread(target=promoter, daemon=True)
    t_evaluator.start()
    t_promoter.start()
    t_promoter.join(timeout=10.0)
    stop_event.set()  # ensure evaluator exits even if promoter was skipped
    t_evaluator.join(timeout=2.0)

    assert not split_states, (
        f"Observed {len(split_states)} split state(s): {split_states[:5]}"
    )


def test_no_split_state_multi_evaluator_load() -> None:
    """Four concurrent evaluator threads × 100 promoter rounds.

    Exercises higher contention to surface any lock gap between the
    `rows` dict update and the `_active_cache` update.
    """
    store = _fresh_store()
    split_states: list[tuple[str, bool]] = []
    stop_event = threading.Event()
    lock = threading.Lock()

    def promoter() -> None:
        for i in range(100):
            now = f"2024-01-01T{i % 24:02d}:00:00+00:00"
            store.promote_to_active(_PATTERN, now_iso=now, ttl_s=_TTL_S)
            store._reset_to_pending(_PATTERN, qid=f"q{i}", now_iso=_NOW_PENDING)
        stop_event.set()

    def evaluator() -> None:
        while not stop_event.is_set():
            snap = store.read_eval_snapshot(_PATTERN)
            if snap is None:
                continue
            row_state, in_cache = snap
            if (row_state == "a") != in_cache:
                with lock:
                    split_states.append((row_state, in_cache))

    threads = [threading.Thread(target=evaluator, daemon=True) for _ in range(4)]
    t_promoter = threading.Thread(target=promoter, daemon=True)
    for t in threads:
        t.start()
    t_promoter.start()
    t_promoter.join(timeout=10.0)
    stop_event.set()
    for t in threads:
        t.join(timeout=2.0)

    assert not split_states, (
        f"Observed {len(split_states)} split state(s) under load: {split_states[:5]}"
    )
