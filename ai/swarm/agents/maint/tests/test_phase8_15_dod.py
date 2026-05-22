"""Phase 8 §8.15.11 — cross-section DoD proof tests.

Each test spot-checks a key symbol or structural invariant introduced
in §8.15.1–§8.15.10, mirroring the §8.9 proof-test pattern.  Tests
are intentionally lightweight: import-level smoke checks and
hasattr/callable/len assertions.  Deeper functional tests live in the
per-sub-phase test files (test_phase8_15_*.py).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

# ── §8.15.1 — MonotonicClock exposes boot_utc ─────────────────────────────

def test_monotonic_clock_class_importable() -> None:
    """MonotonicClock class must be importable from swarm.sdk.clock."""
    from ai.swarm.sdk.clock import MonotonicClock  # noqa: F401


def test_monotonic_clock_has_boot_utc() -> None:
    """MonotonicClock must carry a boot_utc class attribute (§8.15.1)."""
    from ai.swarm.sdk.clock import MonotonicClock
    assert hasattr(MonotonicClock, "boot_utc"), (
        "MonotonicClock.boot_utc is missing — §8.15.11 proof test requires "
        "a stable boot-time UTC reference on the class."
    )


def test_monotonic_clock_boot_utc_is_datetime() -> None:
    """MonotonicClock.boot_utc must be a datetime instance."""
    import datetime
    from ai.swarm.sdk.clock import MonotonicClock
    assert isinstance(MonotonicClock.boot_utc, datetime.datetime), (
        f"MonotonicClock.boot_utc is {type(MonotonicClock.boot_utc)!r}; "
        "expected datetime.datetime."
    )


# ── §8.15.2 — Per-kind sub-schemas directory has ≥ 2 schemas ─────────────

def test_maint_event_kind_schemas_directory_has_entries() -> None:
    """At least 2 kind sub-schema files must exist under maint.event.v1/."""
    schema_dir = (
        Path(__file__).parents[4]
        / "swarm" / "sdk" / "schemas" / "maint.event.v1"
    )
    jsons = list(schema_dir.glob("*.json"))
    assert len(jsons) >= 2, (
        f"Expected ≥2 per-kind sub-schemas in {schema_dir}, found {len(jsons)}."
    )


def test_maint_event_kind_schemas_are_valid_json() -> None:
    """Every file in maint.event.v1/ must be parseable JSON."""
    schema_dir = (
        Path(__file__).parents[4]
        / "swarm" / "sdk" / "schemas" / "maint.event.v1"
    )
    for p in schema_dir.glob("*.json"):
        try:
            json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            pytest.fail(f"Invalid JSON in {p.name}: {exc}")


# ── §8.15.4 — verify_envelope_signature is callable ──────────────────────

def test_verify_envelope_signature_importable() -> None:
    """verify_envelope_signature must be importable from _op_signature."""
    from ai.swarm.agents.maint._op_signature import verify_envelope_signature  # noqa: F401


def test_verify_envelope_signature_callable() -> None:
    """verify_envelope_signature must be callable (§8.15.4)."""
    from ai.swarm.agents.maint._op_signature import verify_envelope_signature
    assert callable(verify_envelope_signature)


# ── §8.15.5 — truncate_oversize is callable ───────────────────────────────

def test_truncate_oversize_importable() -> None:
    """truncate_oversize must be importable from swarm.sdk.maint_audit."""
    from ai.swarm.sdk.maint_audit import truncate_oversize  # noqa: F401


def test_truncate_oversize_callable() -> None:
    """truncate_oversize must be callable (§8.15.5)."""
    from ai.swarm.sdk.maint_audit import truncate_oversize
    assert callable(truncate_oversize)


# ── §8.15.6 — CATALOGUE has ≥ 5 entries ──────────────────────────────────

def test_catalogue_importable() -> None:
    """CATALOGUE must be importable from _catalogue."""
    from ai.swarm.agents.maint._catalogue import CATALOGUE  # noqa: F401


def test_catalogue_has_at_least_five_entries() -> None:
    """CATALOGUE must contain ≥ 5 AgentCatalogueRow entries (§8.15.6)."""
    from ai.swarm.agents.maint._catalogue import CATALOGUE
    assert len(CATALOGUE) >= 5, (
        f"CATALOGUE has {len(CATALOGUE)} entries; §8.15.6 requires ≥ 5."
    )


# ── §8.15.7 — AUDIT_HEADER contains 'user' ───────────────────────────────

def test_audit_header_importable() -> None:
    """AUDIT_HEADER must be importable from xops.opsctl._audit."""
    from xops.opsctl._audit import AUDIT_HEADER  # noqa: F401


def test_audit_header_contains_user() -> None:
    """AUDIT_HEADER must include the 'user' column (§8.15.7 HMAC chain)."""
    from xops.opsctl._audit import AUDIT_HEADER
    assert "user" in AUDIT_HEADER, (
        f"AUDIT_HEADER={AUDIT_HEADER!r} is missing 'user'; "
        "§8.15.7 requires operator identity in the hash-chain."
    )


def test_audit_header_contains_prev_hmac_and_row_hmac() -> None:
    """AUDIT_HEADER must include both hash-chain columns (§8.15.7)."""
    from xops.opsctl._audit import AUDIT_HEADER
    assert "prev_hmac" in AUDIT_HEADER
    assert "row_hmac" in AUDIT_HEADER


# ── §8.15.8 — ShedStateStore is callable ─────────────────────────────────

def test_shed_state_store_importable() -> None:
    """ShedStateStore must be importable from swarm.sdk.shed_state."""
    from ai.swarm.sdk.shed_state import ShedStateStore  # noqa: F401


def test_shed_state_store_callable() -> None:
    """ShedStateStore must be callable (§8.15.8)."""
    from ai.swarm.sdk.shed_state import ShedStateStore
    assert callable(ShedStateStore)


# ── §8.15.9 — dlq_dropped in KIND_SCHEMA_VERSIONS ────────────────────────

def test_dlq_dropped_in_kind_schema_versions() -> None:
    """dlq_dropped must be in KIND_SCHEMA_VERSIONS (§8.15.9 / §7.4)."""
    from ai.swarm.sdk.kind_schema_version import KIND_SCHEMA_VERSIONS
    assert "dlq_dropped" in KIND_SCHEMA_VERSIONS, (
        "'dlq_dropped' not in KIND_SCHEMA_VERSIONS. "
        "§8.15.9 requires this kind to be registered and versioned."
    )


def test_verify_forensic_captured_in_kind_schema_versions() -> None:
    """verify_forensic_captured must be in KIND_SCHEMA_VERSIONS (§8.15.10)."""
    from ai.swarm.sdk.kind_schema_version import KIND_SCHEMA_VERSIONS
    assert "verify_forensic_captured" in KIND_SCHEMA_VERSIONS, (
        "'verify_forensic_captured' not in KIND_SCHEMA_VERSIONS. "
        "§8.15.11 requires this kind to be registered."
    )


# ── §8.15.10 — RestoreVerifyConcurrencyLock is callable ──────────────────

def test_restore_verify_concurrency_lock_importable() -> None:
    """RestoreVerifyConcurrencyLock must be importable from xops.backup."""
    from xops.backup.verify_concurrency import RestoreVerifyConcurrencyLock  # noqa: F401


def test_restore_verify_concurrency_lock_callable() -> None:
    """RestoreVerifyConcurrencyLock must be callable (§8.15.10)."""
    from xops.backup.verify_concurrency import RestoreVerifyConcurrencyLock
    assert callable(RestoreVerifyConcurrencyLock)
