"""Phase 8 §8.13.1 — Model-artifact lineage sidecar + cold mirror.

Two concrete guarantees, both required at v1:

(a) **Reproducibility floor.** Every trained artifact under
    ``data/models/<predictor_id>/<version>/`` carries a sidecar
    ``<artifact>.lineage.json`` with fields::

        predictor_id               str   — matches the enclosing dir
        version                    str   — matches the enclosing dir
        trained_at                 str   — ISO-8601 UTC timestamp
        trainer_commit_sha         str   — git SHA of the trainer code
        training_data_window_utc   dict  — {"start": ISO, "end": ISO}
        source_calibration_row_ids list  — PK list from predictor_calibration
        source_outcome_row_ids     list  — PK list from predictor_outcomes
        hyperparameters_sha256     str   — SHA-256 of the canonical JSON
                                           of the training hyperparameters

    After a worst-case restore, the trainer can re-derive byte-equivalent
    artifacts from the calibration/outcome rows + commit SHA at
    ``cfg.maint_backup_model_reproducibility_window_h`` (default 24 h)
    latency.

(b) **Cold artifact mirror.** A nightly tarball
    ``models-YYYY-MM-DD.tar.zst`` (zstd level 9) of ``data/models/`` is
    uploaded to the same ``OffsiteBackupTarget`` as §8.12, encrypted with
    the same DR-class recipients, retained per
    ``cfg.maint_backup_model_offsite_retention_days`` (default 30 d).
    A **monthly** cold-verify pass extracts the oldest retained tarball
    into a throwaway dir, calls ``predictor.load(...)`` on each artifact,
    and asserts the load completes.

Legacy artifacts (pre-§8.13.1) that have no sidecar emit ONE
``maint.event.v1{kind=backup_model_lineage_legacy}`` per artifact at
agent startup — not the warn alert — so operators see the legacy set
without paging fatigue.

**Gate-dormant deviation (§8.16.15 prerequisite).** The Phase 5 trainer
reactor that *writes* lineage sidecars is gated behind §8.16.15 (not yet
landed).  Until at least one sidecar exists under ``data/models/``, this
monitor operates in **dormant** mode: :func:`iter_lineage_missing_alerts`
yields nothing and logs a WARNING instead of flooding ``sec.alert.v1``
with ``backup_model_lineage_missing`` for every artifact.  Callers must
check :func:`is_lineage_writer_available` and pass the result as
``writer_available`` to :func:`iter_lineage_missing_alerts`.  Once the
Phase 5 trainer lands and writes its first sidecar, dormancy lifts
automatically (the flag becomes ``True`` on the next audit pass).
"""
from __future__ import annotations

import hashlib
import json
import logging
import subprocess
import tarfile as _tarfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, Iterator, Optional

_log = logging.getLogger("swarm.agents.maint.model_lineage")

# Supported model artifact extensions scanned during tarball build and
# cold-verify pass.  Calibration JSON sidecars (.calibration.json) are
# included alongside the model binary; raw .lineage.json sidecars are
# included in the tarball but NOT treated as loadable artifacts by the
# cold-verify pass.
_ARTIFACT_EXTENSIONS: frozenset[str] = frozenset({
    ".json",
    ".ubj",       # XGBoost binary (UBJSON)
    ".txt",       # LightGBM text format
    ".onnx",
    ".joblib",
    ".pkl",
})

SIDECAR_SUFFIX = ".lineage.json"

# ── maint.event.v1 kind constants (§8.13.1) ───────────────────────────
# Single-source definitions — callers emit these strings rather than
# repeating the literals, so a rename is a one-file change.
BACKUP_MODEL_UPLOADED = "backup_model_uploaded"
BACKUP_MODEL_OFFSITE_FAILED = "backup_model_offsite_failed"
BACKUP_MODEL_COLD_VERIFY_COMPLETED = "backup_model_cold_verify_completed"
BACKUP_MODEL_COLD_VERIFY_FAILED = "backup_model_cold_verify_failed"
BACKUP_MODEL_LINEAGE_DRIFT = "backup_model_lineage_drift"

# ── sec.alert.v1 kind constant (§8.13.1 post-hoc audit) ──────────────
# Emitted by the backup agent when audit_model_artifacts() finds an
# artifact that is NOT legacy but lacks a lineage sidecar.  The Phase 5
# trainer reactor MUST write one on every training run; this alert
# surfaces post-hoc when it did not.
SEC_ALERT_BACKUP_MODEL_LINEAGE_MISSING = "backup_model_lineage_missing"


# ── Lineage-missing debouncer ──────────────────────────────────────────


@dataclass
class LineageMissingDebouncer:
    """Debounce ``sec.alert.v1{kind=backup_model_lineage_missing}`` per predictor_id.

    Prevents the periodic lineage audit from flooding the bus when a
    predictor is persistently sidecar-free.  A single alert is emitted at
    most once per *window_h* hours for each ``predictor_id``.

    *window_h* is injected from
    ``cfg.maint_backup_model_lineage_missing_debounce_h`` (default 24 h).
    Pass ``window_h=0`` to disable debouncing (useful in tests).
    """

    window_h: float = 24.0
    _last_emitted: Dict[str, datetime] = field(
        default_factory=dict, init=False, repr=False
    )

    def should_emit(self, predictor_id: str, now: datetime) -> bool:
        """Return ``True`` if an alert for *predictor_id* is due.

        Always returns ``True`` on the first call for a given predictor_id.
        Subsequently returns ``True`` only after *window_h* hours have
        elapsed since the last emission.  When ``window_h == 0`` the
        check is always bypassed (always returns ``True``).
        """
        if self.window_h <= 0:
            return True
        last = self._last_emitted.get(predictor_id)
        if last is None:
            return True
        return (now - last).total_seconds() >= self.window_h * 3600.0

    def record_emitted(self, predictor_id: str, now: datetime) -> None:
        """Mark *predictor_id* as having been alerted at *now*."""
        self._last_emitted[predictor_id] = now


def is_lineage_writer_available(models_dir: Path) -> bool:
    """Return ``True`` if at least one lineage sidecar exists under *models_dir*.

    When this returns ``False``, the Phase 5 trainer reactor has not yet
    written any sidecars (§8.16.15 prerequisite not yet landed).  Callers
    should pass ``writer_available=False`` to
    :func:`iter_lineage_missing_alerts` to keep the monitor dormant and
    avoid flooding ``sec.alert.v1`` with spurious alerts.
    """
    if not models_dir.exists():
        return False
    return any(models_dir.rglob(f"*{SIDECAR_SUFFIX}"))


def iter_lineage_missing_alerts(
    entries: list,
    debouncer: "LineageMissingDebouncer",
    *,
    now: Optional[datetime] = None,
    writer_available: bool = True,
) -> Iterator[tuple]:
    """Yield ``(predictor_id, reason)`` pairs for artifacts missing a lineage sidecar.

    Iterates *entries* (a list of :class:`ModelArtifactAuditEntry` as
    returned by :func:`audit_model_artifacts`) and emits at most one
    ``(predictor_id, reason)`` tuple per distinct ``predictor_id`` per
    call, subject to the debounce window in *debouncer*.

    Callers build a ``sec.alert.v1{kind=backup_model_lineage_missing,
    severity=warn}`` from each yielded pair.

    **Dormant mode (gate-dormant deviation §8.16.15).** When
    ``writer_available=False`` (i.e. no sidecar exists in the models
    directory yet), this function logs a WARNING and yields nothing.  This
    prevents ``sec.alert.v1`` floods before the Phase 5 trainer reactor has
    ever written a sidecar.  Use :func:`is_lineage_writer_available` to
    compute this flag at the start of each audit pass.

    Args:
        entries:          audit entries from :func:`audit_model_artifacts`.
        debouncer:        stateful debouncer (one per agent instance).
        now:              wall-clock for the debounce comparison; defaults to
                          ``datetime.now(timezone.utc)``.
        writer_available: pass ``False`` when no sidecar exists anywhere in
                          the models directory (dormant-mode gate).  Yields
                          nothing and logs a WARNING instead of alerting.

    Yields:
        ``(predictor_id: str, reason: str)``
    """
    if not writer_available:
        _log.warning(
            "iter_lineage_missing_alerts: dormant — no lineage sidecars found in "
            "models directory; Phase 5 trainer reactor (§8.16.15) has not yet "
            "written any sidecars. backup_model_lineage_missing alerts suppressed."
        )
        return

    if now is None:
        now = datetime.now(timezone.utc)

    seen: set = set()
    for entry in entries:
        if entry.has_sidecar:
            continue
        pid: str = entry.predictor_id
        if pid in seen:
            # One alert per predictor_id per audit pass — merge multiple
            # missing artifacts under the same predictor into one signal.
            continue
        seen.add(pid)
        if not debouncer.should_emit(pid, now):
            continue
        debouncer.record_emitted(pid, now)
        reason = (
            f"predictor_id={pid!r}: model artifact "
            f"{entry.artifact_path.name!r} has no lineage sidecar; "
            "Phase 5 trainer reactor must always write one "
            "(post-hoc audit, §8.13.1)"
        )
        yield pid, reason


# ── Sidecar schema ────────────────────────────────────────────────────


@dataclass(frozen=True)
class ModelLineageSidecar:
    """Lineage record written alongside every trained model artifact.

    All fields are mandatory; the sidecar is rejected (``ValueError``)
    during read if any are missing.  ``trainer_commit_sha`` may be the
    sentinel ``"unknown"`` when the build metadata file is absent
    (running outside a built container image).
    """

    predictor_id: str
    version: str
    trained_at: str                    # ISO-8601 UTC
    trainer_commit_sha: str            # git SHA or "unknown"
    training_data_window_utc: dict     # {"start": ISO, "end": ISO}
    source_calibration_row_ids: list   # [int, ...] from predictor_calibration
    source_outcome_row_ids: list       # [int, ...] from predictor_outcomes
    hyperparameters_sha256: str        # SHA-256 hex of canonical hyper-param JSON

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ModelLineageSidecar":
        required = {
            "predictor_id",
            "version",
            "trained_at",
            "trainer_commit_sha",
            "training_data_window_utc",
            "source_calibration_row_ids",
            "source_outcome_row_ids",
            "hyperparameters_sha256",
        }
        missing = required - d.keys()
        if missing:
            raise ValueError(
                f"lineage sidecar missing required fields: {sorted(missing)}"
            )
        return cls(
            predictor_id=d["predictor_id"],
            version=d["version"],
            trained_at=d["trained_at"],
            trainer_commit_sha=d["trainer_commit_sha"],
            training_data_window_utc=d["training_data_window_utc"],
            source_calibration_row_ids=d["source_calibration_row_ids"],
            source_outcome_row_ids=d["source_outcome_row_ids"],
            hyperparameters_sha256=d["hyperparameters_sha256"],
        )


def hash_hyperparameters(hyperparameters: dict) -> str:
    """Return a stable SHA-256 hex digest of a hyperparameter dict.

    Uses canonical JSON (``sort_keys=True``, no extra whitespace) so
    key-insertion order never affects the digest.
    """
    canonical = json.dumps(hyperparameters, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def sidecar_path(artifact_path: Path) -> Path:
    """Return the ``.lineage.json`` sidecar path for *artifact_path*."""
    return artifact_path.parent / (artifact_path.name + SIDECAR_SUFFIX)


def write_model_lineage_sidecar(
    artifact_path: Path, sidecar: ModelLineageSidecar
) -> Path:
    """Write *sidecar* as ``<artifact_path>.lineage.json``.

    Writes atomically (temp file + rename) so a concurrent reader never
    sees a half-written sidecar.  Permissions are set to 0o600 before
    rename to satisfy the §8.3 file-permission contract.

    Returns the path of the written sidecar.
    """
    dest = sidecar_path(artifact_path)
    tmp = dest.with_suffix(".lineage.json.tmp")
    payload = json.dumps(sidecar.to_dict(), indent=2, sort_keys=True)
    tmp.write_text(payload, encoding="utf-8")
    tmp.chmod(0o600)
    tmp.rename(dest)
    _log.debug("lineage sidecar written: %s", dest)
    return dest


def read_model_lineage_sidecar(
    artifact_path: Path,
) -> Optional[ModelLineageSidecar]:
    """Read the lineage sidecar for *artifact_path*.

    Returns ``None`` when the sidecar file is absent (legacy artifact).
    Raises ``ValueError`` when the file exists but is malformed or
    missing required fields.
    """
    p = sidecar_path(artifact_path)
    if not p.exists():
        return None
    raw = json.loads(p.read_text(encoding="utf-8"))
    return ModelLineageSidecar.from_dict(raw)


# ── Audit helper ──────────────────────────────────────────────────────


@dataclass
class ModelArtifactAuditEntry:
    """Result of scanning one model artifact for its lineage sidecar."""

    artifact_path: Path
    predictor_id: str
    version: str
    has_sidecar: bool
    sidecar: Optional[ModelLineageSidecar] = None


def iter_model_artifacts(models_dir: Path) -> Iterator[Path]:
    """Yield every model artifact file (non-sidecar) under *models_dir*.

    Skips ``.lineage.json`` sidecars themselves; yields files whose
    extension is in :data:`_ARTIFACT_EXTENSIONS`.
    """
    if not models_dir.exists():
        return
    for p in sorted(models_dir.rglob("*")):
        if not p.is_file():
            continue
        if p.name.endswith(SIDECAR_SUFFIX):
            continue
        if p.suffix in _ARTIFACT_EXTENSIONS:
            yield p


def audit_model_artifacts(models_dir: Path) -> list:
    """Scan *models_dir* and return one :class:`ModelArtifactAuditEntry` per artifact.

    Each entry records whether the artifact has a valid lineage sidecar.
    Callers use the result to emit ``backup_model_lineage_legacy`` events
    for legacy artifacts (those without a sidecar) and to build
    dashboards tracking sidecar coverage.
    """
    entries: list[ModelArtifactAuditEntry] = []
    for artifact_path in iter_model_artifacts(models_dir):
        parts = artifact_path.relative_to(models_dir).parts
        predictor_id = parts[0] if len(parts) >= 1 else "unknown"
        version = parts[1] if len(parts) >= 2 else "unknown"
        sidecar: Optional[ModelLineageSidecar] = None
        try:
            sidecar = read_model_lineage_sidecar(artifact_path)
        except (ValueError, json.JSONDecodeError) as exc:
            _log.warning("malformed lineage sidecar for %s: %s", artifact_path, exc)
        entries.append(
            ModelArtifactAuditEntry(
                artifact_path=artifact_path,
                predictor_id=predictor_id,
                version=version,
                has_sidecar=sidecar is not None,
                sidecar=sidecar,
            )
        )
    return entries


# ── Tarball build ─────────────────────────────────────────────────────


@dataclass
class ModelTarballResult:
    """Returned by :func:`build_model_tarball` on success."""

    tarball_path: Path
    compressed_bytes: int
    artifact_count: int


def build_model_tarball(
    models_dir: Path,
    date: str,
    dest_dir: Path,
    *,
    compress: bool = True,
) -> ModelTarballResult:
    """Create a tarball of *models_dir* at *dest_dir/models-<date>.tar.zst*.

    Uses ``tar`` piped through ``zstd -9`` (the §8.13.1 cold-mirror
    algorithm) when *compress* is ``True`` (production default).
    Falls back to gzip via stdlib when *compress* is ``False`` — in that
    case the file extension is still ``.tar.zst`` but the payload is gzip,
    which is accepted by the companion :func:`cold_verify_model_tarball`
    when called with ``compress=False``.  This shim exists so the test
    suite can run without the ``zstd`` binary.

    Returns a :class:`ModelTarballResult` describing the created file.

    Raises:
        FileNotFoundError: when *models_dir* does not exist.
        subprocess.CalledProcessError: when ``tar`` or ``zstd`` exits non-zero.
    """
    if not models_dir.exists():
        raise FileNotFoundError(f"models_dir does not exist: {models_dir}")
    dest_dir.mkdir(parents=True, exist_ok=True)
    tarball_path = dest_dir / f"models-{date}.tar.zst"

    artifact_count = sum(1 for _ in iter_model_artifacts(models_dir))

    if compress:
        # Two-stage pipeline: tar produces an uncompressed archive on stdout;
        # zstd -9 reads it and writes the compressed output to disk.
        # Paths are passed as list arguments (no shell=True) to prevent
        # injection through operator-controlled path values.
        tar_proc = subprocess.Popen(
            ["tar", "-C", str(models_dir.parent), "-cf", "-", models_dir.name],
            stdout=subprocess.PIPE,
        )
        assert tar_proc.stdout is not None
        zstd_proc = subprocess.Popen(
            ["zstd", "-9", "--force", "-o", str(tarball_path)],
            stdin=tar_proc.stdout,
        )
        tar_proc.stdout.close()
        zstd_proc.wait()
        tar_proc.wait()
        if tar_proc.returncode != 0 or zstd_proc.returncode != 0:
            raise subprocess.CalledProcessError(
                tar_proc.returncode or zstd_proc.returncode,
                "tar|zstd",
            )
    else:
        # Gzip fallback: used only in the test environment.
        with _tarfile.open(str(tarball_path), "w:gz") as tf:
            tf.add(str(models_dir), arcname=models_dir.name)

    compressed_bytes = tarball_path.stat().st_size
    _log.info(
        "model tarball built: %s (%d bytes, %d artifacts)",
        tarball_path,
        compressed_bytes,
        artifact_count,
    )
    return ModelTarballResult(
        tarball_path=tarball_path,
        compressed_bytes=compressed_bytes,
        artifact_count=artifact_count,
    )


# ── Cold-verify pass ──────────────────────────────────────────────────


@dataclass
class ModelColdVerifyResult:
    """Result of a cold-verify pass over a model tarball."""

    tarball_path: Path
    total_artifacts: int
    loaded_ok: int
    load_errors: list  # list[str] — artifact paths that failed to load

    @property
    def passed(self) -> bool:
        return len(self.load_errors) == 0 and self.total_artifacts > 0

    @property
    def outcome(self) -> str:
        if not self.passed:
            return BACKUP_MODEL_COLD_VERIFY_FAILED
        return BACKUP_MODEL_COLD_VERIFY_COMPLETED


def cold_verify_model_tarball(
    tarball_path: Path,
    extract_dir: Path,
    predictor_load_fn: Callable[[Path], None],
    *,
    compress: bool = True,
) -> ModelColdVerifyResult:
    """Extract *tarball_path* into *extract_dir* and call *predictor_load_fn*
    on every model artifact found.

    *predictor_load_fn* must raise on failure and return ``None`` on success.
    Any exception is caught, recorded in :attr:`ModelColdVerifyResult.load_errors`,
    and the pass continues (full failure inventory rather than early-exit).

    The *compress* flag must match the value used when the tarball was
    built (``True`` → zstd decompress via subprocess, ``False`` → gzip
    via stdlib).

    Returns a :class:`ModelColdVerifyResult`.
    """
    extract_dir.mkdir(parents=True, exist_ok=True)

    if compress:
        zstd_proc = subprocess.Popen(
            ["zstd", "-d", str(tarball_path), "--force", "-o", "-"],
            stdout=subprocess.PIPE,
        )
        assert zstd_proc.stdout is not None
        tar_proc = subprocess.Popen(
            ["tar", "-C", str(extract_dir), "-xf", "-"],
            stdin=zstd_proc.stdout,
        )
        zstd_proc.stdout.close()
        tar_proc.wait()
        zstd_proc.wait()
        if zstd_proc.returncode != 0 or tar_proc.returncode != 0:
            raise subprocess.CalledProcessError(
                zstd_proc.returncode or tar_proc.returncode,
                "zstd|tar",
            )
    else:
        with _tarfile.open(str(tarball_path), "r:gz") as tf:
            tf.extractall(path=str(extract_dir), filter="data")

    errors: list[str] = []
    loaded_ok = 0
    for artifact_path in iter_model_artifacts(extract_dir):
        try:
            predictor_load_fn(artifact_path)
            loaded_ok += 1
        except Exception as exc:  # pylint: disable=broad-except
            _log.warning("cold-verify load failure: %s — %s", artifact_path, exc)
            errors.append(f"{artifact_path}: {exc}")

    result = ModelColdVerifyResult(
        tarball_path=tarball_path,
        total_artifacts=loaded_ok + len(errors),
        loaded_ok=loaded_ok,
        load_errors=errors,
    )
    _log.info(
        "cold-verify %s: %s (loaded=%d, errors=%d)",
        tarball_path.name,
        result.outcome,
        loaded_ok,
        len(errors),
    )
    return result


# ── Lineage-drift check ───────────────────────────────────────────────


def check_sidecar_consistency(
    artifact_path: Path, models_dir: Path
) -> Optional[str]:
    """Check whether the lineage sidecar for *artifact_path* is consistent
    with its location under *models_dir*.

    Returns one of the :data:`BACKUP_MODEL_LINEAGE_DRIFT` kind string when
    drift is detected, or ``None`` when the sidecar is present and
    structurally consistent.

    Drift is reported for three root causes (the caller may include a
    ``drift_reason`` field in the emitted event payload):

    * ``"sidecar_missing"`` — no sidecar file exists for the artifact.
    * ``"predictor_id_mismatch"`` — the sidecar's ``predictor_id`` field
      does not match the first path component under *models_dir*.
    * ``"version_mismatch"`` — the sidecar's ``version`` field does not
      match the second path component under *models_dir*.

    Raises:
        ValueError: when the sidecar exists but is malformed (delegates
            to :func:`read_model_lineage_sidecar`).
    """
    sidecar = read_model_lineage_sidecar(artifact_path)
    if sidecar is None:
        _log.debug("lineage drift (sidecar_missing): %s", artifact_path)
        return BACKUP_MODEL_LINEAGE_DRIFT

    try:
        parts = artifact_path.relative_to(models_dir).parts
    except ValueError:
        # artifact_path is outside models_dir — treat as missing sidecar
        _log.debug("lineage drift (outside models_dir): %s", artifact_path)
        return BACKUP_MODEL_LINEAGE_DRIFT

    expected_predictor_id = parts[0] if len(parts) >= 1 else None
    expected_version = parts[1] if len(parts) >= 2 else None

    if expected_predictor_id is not None and sidecar.predictor_id != expected_predictor_id:
        _log.debug(
            "lineage drift (predictor_id_mismatch): %s — sidecar=%r, dir=%r",
            artifact_path,
            sidecar.predictor_id,
            expected_predictor_id,
        )
        return BACKUP_MODEL_LINEAGE_DRIFT

    if expected_version is not None and sidecar.version != expected_version:
        _log.debug(
            "lineage drift (version_mismatch): %s — sidecar=%r, dir=%r",
            artifact_path,
            sidecar.version,
            expected_version,
        )
        return BACKUP_MODEL_LINEAGE_DRIFT

    return None
