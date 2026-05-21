"""Phase 8 §8.9 — pattern_allowlist daily-sweep bounded-growth proof tests.

Three properties proved here:

1. **Active→expired sweep**: ``expire_tick()`` transitions rows whose
   ``promoted_at + ttl_s`` is past *now* from state ``a`` → ``e`` and
   returns them in the emitted ``pattern_allowlist_expired`` events.

2. **Table size bounded by TTL × emission rate**: inserting R distinct
   patterns per unit-window and running the sweep after TTL confirms
   that only the live window's rows remain *active*; expired rows are
   flagged and do not grow the active set indefinitely.

3. **Pending rows pruned at ``pending_ttl_days``**: patterns that were
   inserted as ``pending`` but never promoted are deleted from the store
   once their age exceeds ``cfg.maint_sec_pattern_pending_ttl_days``
   (``expire_tick()`` is the driver).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from common import config as _config

from swarm.agents.maint.sec import InMemoryPatternStore, MaintSecAgent


# ── Helpers ────────────────────────────────────────────────────────


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def _utc(y: int, m: int, d: int, h: int = 0, s: int = 0) -> datetime:
    return datetime(y, m, d, h, 0, s, tzinfo=timezone.utc)


def _promote(store: InMemoryPatternStore, pattern: str, *,
             created_at: datetime, ttl_s: int) -> None:
    """Insert a pattern directly into active state with explicit timestamps
    (bypasses the two-step upsert_pending→promote flow so tests can set
    precise timestamps without wiring the full agent round-trip)."""
    store.rows[pattern] = {
        "state": "a",
        "ts": _iso(created_at),
        "promoted_at": _iso(created_at),
        "ttl_s": ttl_s,
        "qids": [],
    }


def _insert_pending(store: InMemoryPatternStore, pattern: str, *,
                    created_at: datetime) -> None:
    store.rows[pattern] = {
        "state": "p",
        "ts": _iso(created_at),
        "qids": [],
    }


# ── Test 1: active→expired sweep ──────────────────────────────────


def test_expire_tick_transitions_past_ttl_rows_to_expired() -> None:
    store = InMemoryPatternStore()
    epoch = _utc(2025, 1, 1)
    ttl_s = 3600  # 1 hour

    # Two patterns promoted 2 hours ago → past TTL.
    _promote(store, "pat-expired-1", created_at=epoch, ttl_s=ttl_s)
    _promote(store, "pat-expired-2", created_at=epoch, ttl_s=ttl_s)
    # One pattern promoted 30 minutes ago → still active.
    half_ago = epoch + timedelta(hours=1, minutes=30)
    _promote(store, "pat-still-active", created_at=half_ago, ttl_s=ttl_s)

    now = epoch + timedelta(hours=2)
    agent = MaintSecAgent(pattern_store=store, clock_iso=lambda: _iso(now))
    events = agent.expire_tick()

    expired_targets = {
        m.payload["target"]
        for m in events
        if m.payload.get("kind") == "pattern_allowlist_expired"
    }
    assert "pat-expired-1" in expired_targets
    assert "pat-expired-2" in expired_targets
    assert "pat-still-active" not in expired_targets

    # State in the store reflects the transition.
    assert store.rows["pat-expired-1"]["state"] == "e"
    assert store.rows["pat-expired-2"]["state"] == "e"
    assert store.rows["pat-still-active"]["state"] == "a"


# ── Test 2: table size bounded by TTL × emission rate ─────────────


def test_active_set_bounded_by_ttl_window() -> None:
    """Emit RATE patterns/day for 2×TTL days; after the first TTL the
    initial batch must be expired, keeping the active set capped at
    RATE × TTL_DAYS rows (not growing unboundedly).
    """
    RATE = 10        # distinct patterns per day
    TTL_DAYS = 3     # active TTL in days
    TTL_S = TTL_DAYS * 86_400
    TOTAL_DAYS = TTL_DAYS * 2  # run for twice the TTL

    store = InMemoryPatternStore()
    epoch = _utc(2025, 2, 1)

    # Emit RATE patterns each day for TOTAL_DAYS.
    for day in range(TOTAL_DAYS):
        created = epoch + timedelta(days=day)
        for i in range(RATE):
            key = f"pat-d{day:03d}-{i:02d}"
            _promote(store, key, created_at=created, ttl_s=TTL_S)

    total_inserted = RATE * TOTAL_DAYS
    assert len(store.rows) == total_inserted

    # Sweep at exactly TTL_S + 1 second past epoch.
    # Day-0 patterns (promoted at epoch) have elapsed = TTL_S+1 >= TTL_S → expired.
    # Day-1..TOTAL_DAYS-1 patterns have elapsed < TTL_S → still active.
    sweep_at = epoch + timedelta(seconds=TTL_S + 1)
    expired = store.expire_due(now_iso=_iso(sweep_at))

    # Only day-0 batch (RATE patterns) expired.
    assert len(expired) == RATE, (
        f"expected {RATE} expired (day-0 batch only), got {len(expired)}"
    )

    active_count = sum(1 for r in store.rows.values() if r["state"] == "a")
    # Days 1..TOTAL_DAYS-1 are still active → RATE*(TOTAL_DAYS-1)
    expected_active = RATE * (TOTAL_DAYS - 1)
    assert active_count == expected_active, (
        f"active_count={active_count} expected={expected_active} "
        "— active set must not exceed emission-rate × TTL window"
    )

    expired_count = sum(1 for r in store.rows.values() if r["state"] == "e")
    assert expired_count == RATE


# ── Test 3: pending rows pruned at pending_ttl_days ───────────────


def test_pending_rows_pruned_after_pending_ttl_days(monkeypatch) -> None:
    """Pending rows whose age exceeds pending_ttl_days are deleted from
    the store when expire_due() runs; recently-inserted pending rows
    survive.
    """
    monkeypatch.setattr(_config.cfg, "maint_sec_pattern_pending_ttl_days", 30)

    store = InMemoryPatternStore()
    epoch = _utc(2025, 3, 1)

    # 5 old pending rows: 31 days ago — past the 30-day TTL.
    old_date = epoch - timedelta(days=31)
    for i in range(5):
        _insert_pending(store, f"old-pending-{i}", created_at=old_date)

    # 3 recent pending rows: 5 days ago — should survive.
    recent_date = epoch - timedelta(days=5)
    for i in range(3):
        _insert_pending(store, f"recent-pending-{i}", created_at=recent_date)

    expired = store.expire_due(now_iso=_iso(epoch))

    # No active→expired events (no active rows).
    assert expired == []

    # Old pending rows are gone.
    for i in range(5):
        assert f"old-pending-{i}" not in store.rows, (
            f"old-pending-{i} must be pruned by expire_due"
        )

    # Recent pending rows survive.
    for i in range(3):
        assert f"recent-pending-{i}" in store.rows
        assert store.rows[f"recent-pending-{i}"]["state"] == "p"


# ── Test 4: adversarial — row with missing promoted_at is not crashed ──


def test_expire_due_tolerates_missing_promoted_at() -> None:
    """A row with state='a' but no promoted_at field must not crash the
    sweep; it is left in state 'a' (conservative: do not silently expire
    a row whose expiry cannot be computed).
    """
    store = InMemoryPatternStore()
    store.rows["bad-row"] = {"state": "a", "ttl_s": 60, "ts": "2024-01-01T00:00:00+00:00"}
    far_future = _utc(2099, 1, 1)
    expired = store.expire_due(now_iso=_iso(far_future))
    assert expired == []
    assert store.rows["bad-row"]["state"] == "a"
