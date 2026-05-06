"""Phase 8 §8.15.3 — advisory-lock key registry tests."""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from xops.maint.advisory_lock import BoundLock  # noqa: E402
from xops.maint.advisory_lock_keys import (  # noqa: E402
    ALL_LOCK_KEYS,
    LOCK_MAINT_DLQ_REPLAY,
    LOCK_MAINT_SCALER_LEADER,
    ensure_unique,
)


def test_all_keys_registered_unique() -> None:
    values = list(ALL_LOCK_KEYS.values())
    assert len(values) == len(set(values)), (
        f"Duplicate advisory-lock int8 keys: {values}"
    )


def test_known_constants_present() -> None:
    assert LOCK_MAINT_DLQ_REPLAY in ALL_LOCK_KEYS.values()
    assert LOCK_MAINT_SCALER_LEADER in ALL_LOCK_KEYS.values()


def test_keys_are_int8_safe() -> None:
    """Postgres advisory lock keys are bigint — fit in [-2^63, 2^63-1]."""
    for name, val in ALL_LOCK_KEYS.items():
        assert isinstance(val, int), f"{name} is not int"
        assert -(2 ** 63) <= val < 2 ** 63, f"{name}={val} overflows bigint"


def test_bound_lock_rejects_unregistered_key() -> None:
    """Defense in depth: callers must use a registered constant."""
    import pytest
    with pytest.raises(ValueError):
        BoundLock(conn=None, key=999_999)


def test_bound_lock_returns_false_when_conn_is_none() -> None:
    """Best-effort: a None connection cannot acquire — the ctx mgr
    must report not-acquired rather than crash. (Real Postgres is
    exercised by the integration suite.)"""
    with BoundLock(conn=None, key=LOCK_MAINT_DLQ_REPLAY) as acquired:
        assert acquired is False


def test_ensure_unique_passes_for_canonical_registry() -> None:
    """Boot-time validator: the canonical registry has no duplicates."""
    assert ensure_unique() is True


def test_ensure_unique_raises_on_duplicate_value() -> None:
    """Per ROADMAP §8.15.3 proof bullet (a): a registry with a
    duplicate int8 key value MUST raise loud."""
    import pytest
    bogus = {
        "ALPHA": 9_001,
        "BETA": 9_002,
        "ALPHA_DUP": 9_001,  # collision with ALPHA
    }
    with pytest.raises(ValueError) as exc:
        ensure_unique(bogus)
    assert "9001" in str(exc.value).replace("_", "").replace(" ", "")
