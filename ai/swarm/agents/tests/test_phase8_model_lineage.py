"""Phase 8 §8.13.1 — model-artifact lineage sidecar + cold mirror tests.

Boundary tests:

1. **Sidecar write/read round-trip.** Write a sidecar, read it back,
   assert all fields are equal.
2. **Sidecar file permissions.** Written sidecar must be 0o600.
3. **Sidecar absent → None.** ``read_model_lineage_sidecar`` returns
   ``None`` for an artifact with no sidecar (legacy path).
4. **Sidecar malformed → ValueError.** Reading a sidecar with a missing
   required field raises ``ValueError``.
5. **Hyperparameter hash stability.** Same dict in different key-insertion
   order produces identical ``hyperparameters_sha256``.
6. **Hyperparameter hash discriminates differences.** Different dicts
   produce different digests.
7. **Hash matches sidecar field.** The ``hyperparameters_sha256`` stored
   in ``SAMPLE_LINEAGE`` equals a fresh computation from the same dict —
   the reproducibility-floor assertion.
8. **Audit scan — with sidecar.** ``audit_model_artifacts`` correctly
   identifies the sidecar and returns the parsed record.
9. **Audit scan — without sidecar.** All entries report
   ``has_sidecar=False`` when no sidecars exist.
10. **Audit scan — empty dir.** Returns an empty list.
11. **Audit scan — nonexistent dir.** Returns an empty list (no crash).
12. **Tarball build + cold-verify (green path).** Build a gzip-mode
    tarball of a synthetic models dir; run cold-verify; assert every
    artifact loads OK.
13. **Cold-verify detects load failure.** Inject a raising load fn;
    assert ``load_errors`` is non-empty and
    ``result.outcome == "backup_model_cold_verify_failed"``.
14. **Tarball build raises for missing models_dir.**
15. **Config keys present.** ``cfg.maint_backup_model_reproducibility_window_h``
    and ``cfg.maint_backup_model_offsite_retention_days`` are accessible
    with their documented defaults.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from common.config import cfg
from swarm.agents.maint.model_lineage import (
    ModelArtifactAuditEntry,
    ModelColdVerifyResult,
    ModelLineageSidecar,
    ModelTarballResult,
    BACKUP_MODEL_COLD_VERIFY_COMPLETED,
    BACKUP_MODEL_COLD_VERIFY_FAILED,
    BACKUP_MODEL_LINEAGE_DRIFT,
    BACKUP_MODEL_OFFSITE_FAILED,
    BACKUP_MODEL_UPLOADED,
    LineageMissingDebouncer,
    SEC_ALERT_BACKUP_MODEL_LINEAGE_MISSING,
    audit_model_artifacts,
    build_model_tarball,
    check_sidecar_consistency,
    cold_verify_model_tarball,
    hash_hyperparameters,
    is_lineage_writer_available,
    iter_lineage_missing_alerts,
    read_model_lineage_sidecar,
    sidecar_path,
    write_model_lineage_sidecar,
)


# ── Shared fixtures ────────────────────────────────────────────────────

SAMPLE_HYPERPARAMETERS: dict = {
    "n_estimators": 200,
    "max_depth": 5,
    "learning_rate": 0.05,
    "subsample": 0.8,
}

SAMPLE_LINEAGE = ModelLineageSidecar(
    predictor_id="super_lig_v1",
    version="1.0.0",
    trained_at="2025-01-15T03:00:00+00:00",
    trainer_commit_sha="abc123def456",
    training_data_window_utc={
        "start": "2024-07-01T00:00:00+00:00",
        "end": "2025-01-15T00:00:00+00:00",
    },
    source_calibration_row_ids=[1, 2, 3, 100, 101],
    source_outcome_row_ids=[10, 11, 12, 200, 201],
    hyperparameters_sha256=hash_hyperparameters(SAMPLE_HYPERPARAMETERS),
)


def _make_artifact(tmp_path: Path, name: str = "model.joblib") -> Path:
    artifact = tmp_path / name
    artifact.write_bytes(b"stub-model-bytes")
    return artifact


def _make_models_dir(tmp_path: Path) -> Path:
    """Create a synthetic data/models/ tree with two artifacts."""
    models_dir = tmp_path / "models"
    v1 = models_dir / "super_lig_v1" / "1.0.0"
    v1.mkdir(parents=True)
    (v1 / "model.joblib").write_bytes(b"model-bytes-v1")
    (v1 / "calibration.json").write_text('{"calibration": true}', encoding="utf-8")
    return models_dir


# ── Test 1: sidecar write/read round-trip ─────────────────────────────

def test_sidecar_write_read_roundtrip(tmp_path: Path) -> None:
    artifact = _make_artifact(tmp_path)
    written = write_model_lineage_sidecar(artifact, SAMPLE_LINEAGE)
    assert written.exists()
    recovered = read_model_lineage_sidecar(artifact)
    assert recovered is not None
    assert recovered == SAMPLE_LINEAGE


# ── Test 2: file permissions ──────────────────────────────────────────

def test_sidecar_file_permissions(tmp_path: Path) -> None:
    artifact = _make_artifact(tmp_path)
    written = write_model_lineage_sidecar(artifact, SAMPLE_LINEAGE)
    mode = written.stat().st_mode & 0o777
    assert mode == 0o600, f"expected 0o600, got {oct(mode)}"


# ── Test 3: absent sidecar returns None ──────────────────────────────

def test_sidecar_absent_returns_none(tmp_path: Path) -> None:
    artifact = _make_artifact(tmp_path, "no_sidecar.joblib")
    result = read_model_lineage_sidecar(artifact)
    assert result is None


# ── Test 4: malformed sidecar raises ValueError ───────────────────────

def test_sidecar_malformed_raises_valueerror(tmp_path: Path) -> None:
    artifact = _make_artifact(tmp_path)
    p = sidecar_path(artifact)
    # Write sidecar missing required fields.
    p.write_text('{"predictor_id": "x"}', encoding="utf-8")
    with pytest.raises(ValueError, match="missing required fields"):
        read_model_lineage_sidecar(artifact)


# ── Test 5: hyperparameter hash stability (key-insertion order) ───────

def test_hyperparameter_hash_key_order_invariance() -> None:
    hp1 = {"n_estimators": 200, "max_depth": 5}
    hp2 = {"max_depth": 5, "n_estimators": 200}
    assert hash_hyperparameters(hp1) == hash_hyperparameters(hp2)


# ── Test 6: different dicts produce different digests ─────────────────

def test_hyperparameter_hash_discriminates_differences() -> None:
    hp1 = {"n_estimators": 200}
    hp2 = {"n_estimators": 201}
    assert hash_hyperparameters(hp1) != hash_hyperparameters(hp2)


# ── Test 7: reproducibility floor — stored hash matches fresh computation

def test_hyperparameter_hash_matches_lineage_sidecar() -> None:
    """Reproducibility floor: the hash stored in the sidecar must equal a
    fresh computation from the same hyperparameter dict.  After a restore,
    the trainer can re-derive a byte-equivalent artifact starting from this
    same dict + the referenced Postgres rows."""
    expected_sha = hash_hyperparameters(SAMPLE_HYPERPARAMETERS)
    assert SAMPLE_LINEAGE.hyperparameters_sha256 == expected_sha


# ── Test 8: audit scan — artifact with sidecar ────────────────────────

def test_audit_model_artifacts_with_sidecar(tmp_path: Path) -> None:
    models_dir = _make_models_dir(tmp_path)
    artifact = models_dir / "super_lig_v1" / "1.0.0" / "model.joblib"
    write_model_lineage_sidecar(artifact, SAMPLE_LINEAGE)

    entries = audit_model_artifacts(models_dir)
    assert len(entries) > 0
    with_sidecar = [e for e in entries if e.has_sidecar]
    assert len(with_sidecar) >= 1
    assert with_sidecar[0].sidecar == SAMPLE_LINEAGE
    assert with_sidecar[0].predictor_id == "super_lig_v1"
    assert with_sidecar[0].version == "1.0.0"


# ── Test 9: audit scan — no sidecars ──────────────────────────────────

def test_audit_model_artifacts_without_sidecar(tmp_path: Path) -> None:
    models_dir = _make_models_dir(tmp_path)
    entries = audit_model_artifacts(models_dir)
    assert len(entries) > 0
    assert all(not e.has_sidecar for e in entries)


# ── Test 10: audit scan — empty dir ───────────────────────────────────

def test_audit_empty_models_dir(tmp_path: Path) -> None:
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    entries = audit_model_artifacts(models_dir)
    assert entries == []


# ── Test 11: audit scan — nonexistent dir ─────────────────────────────

def test_audit_nonexistent_models_dir(tmp_path: Path) -> None:
    entries = audit_model_artifacts(tmp_path / "nonexistent_models")
    assert entries == []


# ── Test 12: tarball build + cold-verify (green path) ─────────────────

def test_build_tarball_and_cold_verify_ok(tmp_path: Path) -> None:
    models_dir = _make_models_dir(tmp_path)
    dest_dir = tmp_path / "tarballs"

    result = build_model_tarball(
        models_dir, "2025-01-15", dest_dir, compress=False
    )
    assert isinstance(result, ModelTarballResult)
    assert result.tarball_path.exists()
    assert result.tarball_path.name == "models-2025-01-15.tar.zst"
    assert result.compressed_bytes > 0
    assert result.artifact_count > 0

    extract_dir = tmp_path / "extracted"
    loaded: list[Path] = []

    def _load_ok(p: Path) -> None:
        loaded.append(p)

    verify = cold_verify_model_tarball(
        result.tarball_path, extract_dir, _load_ok, compress=False
    )
    assert isinstance(verify, ModelColdVerifyResult)
    assert verify.passed
    assert verify.outcome == "backup_model_cold_verify_completed"
    assert verify.loaded_ok == result.artifact_count
    assert verify.load_errors == []
    assert len(loaded) == result.artifact_count


# ── Test 13: cold-verify detects load failure ─────────────────────────

def test_cold_verify_detects_load_failure(tmp_path: Path) -> None:
    models_dir = _make_models_dir(tmp_path)
    dest_dir = tmp_path / "tarballs"
    result = build_model_tarball(
        models_dir, "2025-01-15", dest_dir, compress=False
    )
    extract_dir = tmp_path / "extracted"

    def _load_fail(p: Path) -> None:
        raise RuntimeError("corrupt model payload")

    verify = cold_verify_model_tarball(
        result.tarball_path, extract_dir, _load_fail, compress=False
    )
    assert not verify.passed
    assert verify.outcome == "backup_model_cold_verify_failed"
    assert len(verify.load_errors) > 0
    assert "corrupt model payload" in verify.load_errors[0]


# ── Test 14: tarball build raises for missing models_dir ──────────────

def test_build_tarball_raises_for_missing_models_dir(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        build_model_tarball(
            tmp_path / "nonexistent_models",
            "2025-01-15",
            tmp_path / "out",
            compress=False,
        )


# ── Test 15: config keys present with documented defaults ─────────────

def test_config_keys_present() -> None:
    """§8.13.1 config keys must be accessible with their documented defaults."""
    assert cfg.maint_backup_model_reproducibility_window_h == 24
    assert cfg.maint_backup_model_offsite_retention_days == 30


# ── Tests 16-20: §8.13.1 new maint.event.v1 kinds ────────────────────

def test_new_maint_event_kinds_in_known_set() -> None:
    """All 5 new §8.13.1 maint.event.v1 kinds must be in KNOWN_MAINT_EVENT_KINDS."""
    from swarm.agents.maint import KNOWN_MAINT_EVENT_KINDS

    expected = {
        BACKUP_MODEL_UPLOADED,
        BACKUP_MODEL_OFFSITE_FAILED,
        BACKUP_MODEL_COLD_VERIFY_COMPLETED,
        BACKUP_MODEL_COLD_VERIFY_FAILED,
        BACKUP_MODEL_LINEAGE_DRIFT,
    }
    for kind in expected:
        assert kind in KNOWN_MAINT_EVENT_KINDS, (
            f"{kind!r} missing from KNOWN_MAINT_EVENT_KINDS"
        )


def test_cold_verify_outcome_uses_constants() -> None:
    """ModelColdVerifyResult.outcome must return the module-level kind constants."""
    from pathlib import Path

    passed = ModelColdVerifyResult(
        tarball_path=Path("dummy.tar.zst"),
        total_artifacts=2,
        loaded_ok=2,
        load_errors=[],
    )
    assert passed.outcome == BACKUP_MODEL_COLD_VERIFY_COMPLETED

    failed = ModelColdVerifyResult(
        tarball_path=Path("dummy.tar.zst"),
        total_artifacts=2,
        loaded_ok=1,
        load_errors=["err"],
    )
    assert failed.outcome == BACKUP_MODEL_COLD_VERIFY_FAILED


def test_check_sidecar_consistency_ok(tmp_path: Path) -> None:
    """No drift reported when sidecar exists and matches the directory structure."""
    models_dir = tmp_path / "models"
    v1 = models_dir / "super_lig_v1" / "1.0.0"
    v1.mkdir(parents=True)
    artifact = v1 / "model.joblib"
    artifact.write_bytes(b"model-bytes")
    write_model_lineage_sidecar(artifact, SAMPLE_LINEAGE)

    result = check_sidecar_consistency(artifact, models_dir)
    assert result is None


def test_check_sidecar_consistency_missing_sidecar(tmp_path: Path) -> None:
    """BACKUP_MODEL_LINEAGE_DRIFT returned when sidecar file is absent."""
    models_dir = tmp_path / "models"
    v1 = models_dir / "super_lig_v1" / "1.0.0"
    v1.mkdir(parents=True)
    artifact = v1 / "model.joblib"
    artifact.write_bytes(b"model-bytes")
    # No sidecar written.

    result = check_sidecar_consistency(artifact, models_dir)
    assert result == BACKUP_MODEL_LINEAGE_DRIFT


def test_check_sidecar_consistency_predictor_id_mismatch(tmp_path: Path) -> None:
    """BACKUP_MODEL_LINEAGE_DRIFT returned when sidecar predictor_id mismatches dir."""
    models_dir = tmp_path / "models"
    # Place artifact under a directory whose name does NOT match sidecar.predictor_id.
    v1 = models_dir / "wrong_predictor" / "1.0.0"
    v1.mkdir(parents=True)
    artifact = v1 / "model.joblib"
    artifact.write_bytes(b"model-bytes")
    # SAMPLE_LINEAGE has predictor_id="super_lig_v1", but dir is "wrong_predictor".
    write_model_lineage_sidecar(artifact, SAMPLE_LINEAGE)

    result = check_sidecar_consistency(artifact, models_dir)
    assert result == BACKUP_MODEL_LINEAGE_DRIFT


def test_check_sidecar_consistency_version_mismatch(tmp_path: Path) -> None:
    """BACKUP_MODEL_LINEAGE_DRIFT returned when sidecar version mismatches dir."""
    models_dir = tmp_path / "models"
    # predictor_id matches, but version dir does not.
    v1 = models_dir / "super_lig_v1" / "9.9.9"
    v1.mkdir(parents=True)
    artifact = v1 / "model.joblib"
    artifact.write_bytes(b"model-bytes")
    # SAMPLE_LINEAGE has version="1.0.0", but dir is "9.9.9".
    write_model_lineage_sidecar(artifact, SAMPLE_LINEAGE)

    result = check_sidecar_consistency(artifact, models_dir)
    assert result == BACKUP_MODEL_LINEAGE_DRIFT


def test_new_maint_event_kinds_are_notification_only() -> None:
    """All 5 new §8.13.1 kinds must be in KINDS_NOTIFICATION_ONLY (no ack expected)."""
    from swarm.agents.maint._ack_routing import KINDS_NOTIFICATION_ONLY

    expected = {
        BACKUP_MODEL_UPLOADED,
        BACKUP_MODEL_OFFSITE_FAILED,
        BACKUP_MODEL_COLD_VERIFY_COMPLETED,
        BACKUP_MODEL_COLD_VERIFY_FAILED,
        BACKUP_MODEL_LINEAGE_DRIFT,
    }
    for kind in expected:
        assert kind in KINDS_NOTIFICATION_ONLY, (
            f"{kind!r} missing from KINDS_NOTIFICATION_ONLY"
        )


def test_new_kind_schemas_exist() -> None:
    """JSON sub-schema files must exist for all 5 new §8.13.1 kinds."""
    import pathlib

    schemas_dir = pathlib.Path(__file__).parents[3] / "swarm" / "sdk" / "schemas" / "maint.event.v1"
    expected_kinds = [
        BACKUP_MODEL_UPLOADED,
        BACKUP_MODEL_OFFSITE_FAILED,
        BACKUP_MODEL_COLD_VERIFY_COMPLETED,
        BACKUP_MODEL_COLD_VERIFY_FAILED,
        BACKUP_MODEL_LINEAGE_DRIFT,
    ]
    for kind in expected_kinds:
        schema_file = schemas_dir / f"{kind}.json"
        assert schema_file.exists(), f"missing sub-schema: {schema_file}"


# ── Tests for §8.13.1 bullet 3: sec.alert.v1{kind=backup_model_lineage_missing}

def test_backup_model_lineage_missing_in_known_sec_alert_kinds() -> None:
    """The new kind must be registered in KNOWN_SEC_ALERT_KINDS (open-enum contract)."""
    from swarm.agents.payloads import KNOWN_SEC_ALERT_KINDS

    assert SEC_ALERT_BACKUP_MODEL_LINEAGE_MISSING in KNOWN_SEC_ALERT_KINDS, (
        f"{SEC_ALERT_BACKUP_MODEL_LINEAGE_MISSING!r} missing from KNOWN_SEC_ALERT_KINDS"
    )


def test_lineage_missing_debouncer_first_call_always_emits() -> None:
    """Debouncer emits on the first call for a predictor_id."""
    from datetime import datetime, timezone

    debouncer = LineageMissingDebouncer(window_h=24.0)
    now = datetime.now(timezone.utc)
    assert debouncer.should_emit("pred.elo.v1", now) is True


def test_lineage_missing_debouncer_suppresses_within_window() -> None:
    """Debouncer suppresses re-emission within the window."""
    from datetime import datetime, timedelta, timezone

    debouncer = LineageMissingDebouncer(window_h=24.0)
    now = datetime.now(timezone.utc)
    debouncer.record_emitted("pred.elo.v1", now)
    # Only 1 hour later — still inside the 24 h window.
    later = now + timedelta(hours=1)
    assert debouncer.should_emit("pred.elo.v1", later) is False


def test_lineage_missing_debouncer_re_emits_after_window() -> None:
    """Debouncer allows re-emission once the window has expired."""
    from datetime import datetime, timedelta, timezone

    debouncer = LineageMissingDebouncer(window_h=24.0)
    now = datetime.now(timezone.utc)
    debouncer.record_emitted("pred.elo.v1", now)
    # 25 hours later — window has expired.
    later = now + timedelta(hours=25)
    assert debouncer.should_emit("pred.elo.v1", later) is True


def test_lineage_missing_debouncer_zero_window_always_emits() -> None:
    """window_h=0 disables debounce (useful in tests)."""
    from datetime import datetime, timezone

    debouncer = LineageMissingDebouncer(window_h=0)
    now = datetime.now(timezone.utc)
    debouncer.record_emitted("pred.elo.v1", now)
    # Immediately afterwards — zero window means always emit.
    assert debouncer.should_emit("pred.elo.v1", now) is True


def test_iter_lineage_missing_alerts_yields_for_missing_sidecar(tmp_path: Path) -> None:
    """Happy path: artifact without sidecar yields one (predictor_id, reason) pair."""
    from datetime import datetime, timezone

    models_dir = tmp_path / "models"
    pid_dir = models_dir / "pred.elo.v1" / "1.0.0"
    pid_dir.mkdir(parents=True)
    (pid_dir / "model.joblib").write_bytes(b"model-bytes")

    entries = audit_model_artifacts(models_dir)
    assert len(entries) == 1
    assert not entries[0].has_sidecar

    debouncer = LineageMissingDebouncer(window_h=0)  # no debounce in tests
    now = datetime.now(timezone.utc)
    alerts = list(iter_lineage_missing_alerts(entries, debouncer, now=now))
    assert len(alerts) == 1
    pid, reason = alerts[0]
    assert pid == "pred.elo.v1"
    assert "pred.elo.v1" in reason
    assert "lineage sidecar" in reason


def test_iter_lineage_missing_alerts_no_yield_when_sidecar_present(tmp_path: Path) -> None:
    """No alert yielded when all artifacts have sidecars."""
    from datetime import datetime, timezone

    models_dir = tmp_path / "models"
    v1 = models_dir / "super_lig_v1" / "1.0.0"
    v1.mkdir(parents=True)
    artifact = v1 / "model.joblib"
    artifact.write_bytes(b"model-bytes")
    write_model_lineage_sidecar(artifact, SAMPLE_LINEAGE)

    entries = audit_model_artifacts(models_dir)
    assert all(e.has_sidecar for e in entries)

    debouncer = LineageMissingDebouncer(window_h=0)
    now = datetime.now(timezone.utc)
    alerts = list(iter_lineage_missing_alerts(entries, debouncer, now=now))
    assert alerts == []


def test_iter_lineage_missing_alerts_debounce_suppresses_second_call(tmp_path: Path) -> None:
    """Debounce: same predictor_id → only one alert within the window."""
    from datetime import datetime, timedelta, timezone

    models_dir = tmp_path / "models"
    pid_dir = models_dir / "pred.elo.v1" / "1.0.0"
    pid_dir.mkdir(parents=True)
    (pid_dir / "model.joblib").write_bytes(b"model-bytes")

    entries = audit_model_artifacts(models_dir)
    debouncer = LineageMissingDebouncer(window_h=24.0)
    now = datetime.now(timezone.utc)

    # First call — should emit.
    first = list(iter_lineage_missing_alerts(entries, debouncer, now=now))
    assert len(first) == 1

    # Second call 5 minutes later — still inside window, should NOT emit.
    second = list(iter_lineage_missing_alerts(entries, debouncer, now=now + timedelta(minutes=5)))
    assert second == []


def test_iter_lineage_missing_alerts_merges_multiple_artifacts_same_predictor(
    tmp_path: Path,
) -> None:
    """Multiple missing-sidecar artifacts for the same predictor_id yield only one alert."""
    from datetime import datetime, timezone

    models_dir = tmp_path / "models"
    pid_dir = models_dir / "pred.elo.v1" / "1.0.0"
    pid_dir.mkdir(parents=True)
    (pid_dir / "model.joblib").write_bytes(b"bytes-a")
    (pid_dir / "model.onnx").write_bytes(b"bytes-b")

    entries = audit_model_artifacts(models_dir)
    assert len(entries) == 2
    assert all(not e.has_sidecar for e in entries)

    debouncer = LineageMissingDebouncer(window_h=0)
    now = datetime.now(timezone.utc)
    alerts = list(iter_lineage_missing_alerts(entries, debouncer, now=now))
    # Two artifacts, one predictor → one alert only.
    assert len(alerts) == 1
    assert alerts[0][0] == "pred.elo.v1"


def test_config_key_lineage_missing_debounce_h_present() -> None:
    """§8.13.1 config key maint_backup_model_lineage_missing_debounce_h must exist."""
    assert cfg.maint_backup_model_lineage_missing_debounce_h == 24


# ── Test: AST boundary discipline — pg_dump path must not reference data/models/ ──

def test_backup_agent_pg_dump_path_does_not_reference_data_models() -> None:
    """Boundary discipline: the §8.3 pg_dump backup agent (backup.py) must NEVER
    contain a string literal or f-string segment that references ``data/models``
    or ``data\\models``.

    The doctrine is explicit: pg_dump backs up the Postgres database only.
    Model artifacts follow a separate cold-mirror path
    (``build_model_tarball`` / ``cold_verify_model_tarball``).
    This AST scan prevents an accidental merge of the two paths — e.g. a
    developer inadvertently constructing a path to ``data/models/`` inside
    the dump state machine.
    """
    import ast as _ast
    import pathlib

    backup_src = pathlib.Path(__file__).parents[3] / "swarm" / "agents" / "maint" / "backup.py"
    assert backup_src.exists(), f"backup.py not found at {backup_src}"

    source_text = backup_src.read_text(encoding="utf-8")
    tree = _ast.parse(source_text, filename=str(backup_src))

    forbidden_patterns = ("data/models", "data\\models")
    violations: list[tuple[int, str]] = []

    for node in _ast.walk(tree):
        # Plain string constants (including bytes literals are skipped — they
        # hold binary backup payloads, not path strings).
        if isinstance(node, _ast.Constant) and isinstance(node.value, str):
            for pat in forbidden_patterns:
                if pat in node.value:
                    lineno = getattr(node, "lineno", "?")
                    violations.append((lineno, node.value))

        # f-string segments: each JoinedStr child may be a Constant.
        elif isinstance(node, _ast.JoinedStr):
            for child in _ast.walk(node):
                if isinstance(child, _ast.Constant) and isinstance(child.value, str):
                    for pat in forbidden_patterns:
                        if pat in child.value:
                            lineno = getattr(child, "lineno", "?")
                            violations.append((lineno, child.value))

    assert not violations, (
        "backup.py (§8.3 pg_dump path) must never reference data/models/. "
        "Model artifacts use a separate cold-mirror path. "
        f"Violations found: {violations}"
    )


# ── Test: retrain-from-lineage reproduces hyperparameter hash (Finding 2) ─────


def test_retrain_from_lineage_reproduces_hyperparameter_hash(tmp_path: Path) -> None:
    """Given a lineage sidecar, a trainer configured with the same hyperparameters
    reproduces the identical hyperparameters_sha256.

    This is the reproducibility guarantee at the core of §8.13.1: after a
    worst-case restore, re-running the trainer with the recorded hyperparameters
    must yield a byte-equivalent hash so the restored model can be validated.

    A pure-Python stub trainer is used instead of XGBoost/sklearn to keep this
    test lightweight and dependency-free.
    """
    # Step 1: Original training run — trainer records its hyperparameters.
    original_hyperparameters: dict = {
        "n_estimators": 150,
        "max_depth": 4,
        "learning_rate": 0.1,
        "subsample": 0.75,
        "colsample_bytree": 0.8,
    }

    class StubTrainer:
        """Minimal stand-in for an XGBoost/sklearn trainer.

        In production the trainer would call XGBoost.train() and then
        compute hash_hyperparameters(params) to write the sidecar.
        Here we skip the actual fitting and only exercise the hash path.
        """

        def __init__(self, hyperparameters: dict) -> None:
            self._hyperparameters = hyperparameters

        def hyperparameter_hash(self) -> str:
            return hash_hyperparameters(self._hyperparameters)

    original_trainer = StubTrainer(original_hyperparameters)
    original_hash = original_trainer.hyperparameter_hash()

    # Step 2: Trainer writes lineage sidecar alongside the model artifact.
    artifact = _make_artifact(tmp_path)
    lineage = ModelLineageSidecar(
        predictor_id="test_retrain_predictor",
        version="2.0.0",
        trained_at="2025-06-01T00:00:00+00:00",
        trainer_commit_sha="deadbeef1234",
        training_data_window_utc={
            "start": "2024-01-01T00:00:00+00:00",
            "end": "2025-06-01T00:00:00+00:00",
        },
        source_calibration_row_ids=[10, 20, 30],
        source_outcome_row_ids=[40, 50, 60],
        hyperparameters_sha256=original_hash,
    )
    write_model_lineage_sidecar(artifact, lineage)

    # Step 3: Disaster recovery — read lineage sidecar back from disk.
    recovered_lineage = read_model_lineage_sidecar(artifact)
    assert recovered_lineage is not None, "sidecar must be present after write"

    # Step 4: Retrain simulation — reconstruct trainer with the same hyperparameters
    # (sourced from the versioned trainer config at the recorded commit SHA).
    retrain_trainer = StubTrainer(original_hyperparameters)
    retrain_hash = retrain_trainer.hyperparameter_hash()

    # The retrain hash must match what is stored in the recovered sidecar.
    assert retrain_hash == recovered_lineage.hyperparameters_sha256, (
        "hyperparameter hash from retrain must match the lineage sidecar; "
        f"retrain={retrain_hash!r}, sidecar={recovered_lineage.hyperparameters_sha256!r}"
    )


# ── Test: dormancy gate — iter_lineage_missing_alerts with writer_available=False ─


def test_iter_lineage_missing_alerts_dormant_when_writer_unavailable(
    tmp_path: Path,
) -> None:
    """When writer_available=False, iter_lineage_missing_alerts yields nothing.

    Gate-dormant deviation (§8.16.15): before the Phase 5 trainer reactor has
    written any sidecar, is_lineage_writer_available() returns False and the
    monitor must not emit backup_model_lineage_missing alerts.
    """
    from datetime import datetime, timezone

    models_dir = tmp_path / "models"
    pid_dir = models_dir / "pred.elo.v1" / "1.0.0"
    pid_dir.mkdir(parents=True)
    (pid_dir / "model.joblib").write_bytes(b"model-bytes")

    entries = audit_model_artifacts(models_dir)
    assert len(entries) == 1
    assert not entries[0].has_sidecar

    # No sidecars exist anywhere — writer not available yet.
    assert is_lineage_writer_available(models_dir) is False

    debouncer = LineageMissingDebouncer(window_h=0)
    now = datetime.now(timezone.utc)
    alerts = list(
        iter_lineage_missing_alerts(entries, debouncer, now=now, writer_available=False)
    )
    # Dormant: must yield nothing despite missing sidecar.
    assert alerts == []


def test_is_lineage_writer_available_true_when_sidecar_exists(tmp_path: Path) -> None:
    """is_lineage_writer_available returns True once at least one sidecar is present."""
    models_dir = tmp_path / "models"
    pid_dir = models_dir / "super_lig_v1" / "1.0.0"
    pid_dir.mkdir(parents=True)
    artifact = pid_dir / "model.joblib"
    artifact.write_bytes(b"model-bytes")

    assert is_lineage_writer_available(models_dir) is False

    write_model_lineage_sidecar(artifact, SAMPLE_LINEAGE)

    assert is_lineage_writer_available(models_dir) is True
