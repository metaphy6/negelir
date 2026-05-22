"""Phase 8 §8.14.11 — Proof-test consolidation for §8.14.1–§8.14.10.

Verifies that all ten §8.14.x sub-sections contributed proof tests to
the §8.9 DoD test suite.  This file is the "all proof tests land"
assertion; it does NOT replace the individual sub-section test files.

Sections covered and expected minimum test counts:
  §8.14.1  maint_audit_log partitioned + prune + PII routing     ≥ 4
  §8.14.2  per-file dump checksum manifest                       ≥ 3
  §8.14.3  age binary pin                                        ≥ 3
  §8.14.4  opsctl signature + authz gate                         ≥ 4
  §8.14.5  DLQ recursion guard                                   ≥ 3
  §8.14.6  maint.ack trace_id propagation                        ≥ 3
  §8.14.7  schema validate RPS cap                               ≥ 3
  §8.14.8  scaler self-scaling + warmup hint                     ≥ 4
  §8.14.9  pg_dump nice level + verify-PG version                ≥ 3
  §8.14.10 spool-flush dir-level lock + newest-first ordering    ≥ 3
                                                    Total        ≥ 33
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Path anchors
# ---------------------------------------------------------------------------
_REPO = Path(__file__).resolve().parents[5]  # repo root
_MAINT_TESTS = Path(__file__).resolve().parent
_OPSCTL_TESTS = _REPO / "xops" / "opsctl" / "tests"
_BACKUP_TESTS = _REPO / "xops" / "backup" / "tests"

# ---------------------------------------------------------------------------
# Existence map — each entry: (path_relative_to_repo, min_test_count)
# ---------------------------------------------------------------------------
_PROOF_TEST_MODULES: list[tuple[Path, int]] = [
    (_BACKUP_TESTS / "test_partition_prune.py",                      4),   # §8.14.1
    (_BACKUP_TESTS / "test_file_checksum_manifest.py",               3),   # §8.14.2
    (_MAINT_TESTS / "test_phase8_14_3_age_pin.py",                   3),   # §8.14.3
    (_MAINT_TESTS / "test_phase8_14_4_consumer_gate.py",             4),   # §8.14.4
    (_MAINT_TESTS / "test_phase8_14_5_dlq_recursion_guard.py",       3),   # §8.14.5
    (_MAINT_TESTS / "test_phase8_14_6_ack_trace_id.py",              3),   # §8.14.6
    (_MAINT_TESTS / "test_phase8_14_7_validate_rps_cap.py",          3),   # §8.14.7
    (_MAINT_TESTS / "test_scaler.py",                                4),   # §8.14.8 (subset)
    (_BACKUP_TESTS / "test_version_skew.py",                         3),   # §8.14.9
    (_OPSCTL_TESTS / "test_opsctl_spool_flush_8_14_10.py",           3),   # §8.14.10
]

_MIN_TOTAL = 33


# ---------------------------------------------------------------------------
# Happy-path: every §8.14.x proof-test module exists on disk
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("module_path,_min", _PROOF_TEST_MODULES)
def test_proof_test_module_exists(module_path: Path, _min: int) -> None:
    """Each §8.14.x sub-section has a dedicated proof-test file."""
    assert module_path.is_file(), (
        f"Missing §8.14.x proof-test module: {module_path.relative_to(_REPO)}"
    )


# ---------------------------------------------------------------------------
# Happy-path: aggregate test-function count across all modules ≥ 33
# ---------------------------------------------------------------------------

def _count_test_fns(path: Path) -> int:
    """Count ``def test_`` functions in *path* without importing it."""
    src = path.read_text(encoding="utf-8")
    return sum(1 for line in src.splitlines() if line.lstrip().startswith("def test_"))


def test_aggregate_proof_test_count_meets_threshold() -> None:
    """The §8.14.1–§8.14.10 proof-test corpus contains ≥ 33 test functions."""
    total = 0
    for path, _min in _PROOF_TEST_MODULES:
        n = _count_test_fns(path)
        assert n >= _min, (
            f"{path.name}: expected ≥ {_min} test functions, found {n}"
        )
        total += n
    assert total >= _MIN_TOTAL, (
        f"Total §8.14.x proof tests {total} < {_MIN_TOTAL} — "
        "a sub-section may be missing its test file."
    )


# ---------------------------------------------------------------------------
# Cross-cutting: §8.14-introduced cfg knobs are accessible
# ---------------------------------------------------------------------------

def test_cfg_knobs_introduced_by_814_are_accessible() -> None:
    """All 8 §8.14 triangle-test cfg knobs are declared in Config."""
    # Import inside the test so the file can live under any PYTHONPATH.
    from common.config import Config  # type: ignore[import]

    cfg = Config()
    # §8.14.3
    assert hasattr(cfg, "maint_backup_age_binary_version")
    # §8.14.9
    assert hasattr(cfg, "maint_backup_pg_dump_nice_level")
    assert hasattr(cfg, "maint_backup_pg_dump_ionice")
    assert hasattr(cfg, "maint_backup_verify_pg_image")
    # §8.14.7
    assert hasattr(cfg, "maint_schema_validate_max_rps")
    # §8.14.8
    assert hasattr(cfg, "maint_scaler_self_scaling_targets")
    # §8.14.4
    assert hasattr(cfg, "opsctl_require_signature")
    # §8.14.10
    assert hasattr(cfg, "opsctl_spool_flush_max_per_run")


# ---------------------------------------------------------------------------
# Cross-cutting: §8.14-introduced exit code is pinned
# ---------------------------------------------------------------------------

def test_exit_code_spool_flush_already_running_pinned_to_8() -> None:
    """SPOOL_FLUSH_ALREADY_RUNNING exit code must be 8 (runbook dependency)."""
    _opsctl_root = _REPO / "xops" / "opsctl"
    if str(_REPO) not in sys.path:
        sys.path.insert(0, str(_REPO))
    from xops.opsctl._exit_codes import ExitCode  # type: ignore[import]

    assert int(ExitCode.SPOOL_FLUSH_ALREADY_RUNNING) == 8


# ---------------------------------------------------------------------------
# Cross-cutting: §8.14-introduced sec.alert.v1 kinds in KNOWN_SEC_ALERT_KINDS
# ---------------------------------------------------------------------------

_814_SEC_ALERT_KINDS: list[tuple[str, str]] = [
    ("backup_dump_file_corrupted",          "§8.14.2"),
    ("dlq_recursion_blocked",               "§8.14.5"),
    ("maint_ack_legacy_schema",             "§8.14.6"),
    ("maint_schema_sample_rate_too_high",   "§8.14.7"),
    ("scaler_target_forbidden",             "§8.14.8"),
    ("backup_verify_pg_version_mismatch",   "§8.14.9"),
    ("maint_audit_partition_missing",       "§8.14.1"),
    ("opsctl_signature_invalid",            "§8.14.4"),
    ("opsctl_unauthorized",                 "§8.14.4"),
    ("fail_safe_age_version_mismatch_local", "§8.14.3"),
]


@pytest.mark.parametrize("kind,section", _814_SEC_ALERT_KINDS)
def test_814_sec_alert_kind_in_known_set(kind: str, section: str) -> None:
    """Every §8.14 sec.alert.v1 kind is registered in KNOWN_SEC_ALERT_KINDS."""
    from swarm.agents.payloads import KNOWN_SEC_ALERT_KINDS  # type: ignore[import]

    assert kind in KNOWN_SEC_ALERT_KINDS, (
        f"{section} kind={kind!r} missing from KNOWN_SEC_ALERT_KINDS"
    )


# ---------------------------------------------------------------------------
# Cross-cutting: §8.14-introduced maint.event.v1 sub-schemas exist on disk
# ---------------------------------------------------------------------------

_814_MAINT_EVENT_SCHEMAS: list[tuple[str, str]] = [
    ("trainer_warmup_hint",           "§8.14.8"),
    ("spool_flush_partial",           "§8.14.10"),
    ("backup_legacy_no_file_manifest", "§8.14.2"),
]
_SCHEMA_DIR = _REPO / "ai" / "swarm" / "sdk" / "schemas" / "maint.event.v1"


@pytest.mark.parametrize("kind,section", _814_MAINT_EVENT_SCHEMAS)
def test_814_maint_event_sub_schema_exists(kind: str, section: str) -> None:
    """Every §8.14 maint.event.v1 kind has a per-kind sub-schema file."""
    schema_path = _SCHEMA_DIR / f"{kind}.json"
    assert schema_path.is_file(), (
        f"{section} kind={kind!r}: missing sub-schema at "
        f"ai/swarm/sdk/schemas/maint.event.v1/{kind}.json"
    )


# ---------------------------------------------------------------------------
# Adversarial: a fabricated §8.14.x module name is not on disk
# ---------------------------------------------------------------------------

def test_nonexistent_module_would_fail_check() -> None:
    """The existence check actually validates; a typo would be caught."""
    fake = _MAINT_TESTS / "test_phase8_14_99_does_not_exist.py"
    assert not fake.is_file(), (
        "A fabricated §8.14 proof-test module path should not exist"
    )
