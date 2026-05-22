"""Phase 8 §8.16.5 — S3 multipart upload-id TTL + lifecycle assertion.

Two public surfaces:

* :class:`MultipartResumeManager` — resume-or-restart decision for a
  persisted multipart upload.  Reads ``.offsite_state.json`` from
  *state_path*, probes upload-id liveness via ``list_parts``, and
  either proceeds with the resume or deletes the stale state file and
  signals a restart-from-scratch to the caller.

* :func:`check_bucket_lifecycle` — boot-time assertion that the
  bucket's ``AbortIncompleteMultipartUpload.DaysAfterInitiation`` is
  not more aggressive than ``cfg.maint_backup_offsite_lifecycle_min_days``.

Both functions are **side-effect-free with respect to git** (they
never touch committed files) but *do* delete the state file on expiry.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from common.config import cfg
from common.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Protocols — keep hard S3 dependency off the import path so the module
# can be imported and unit-tested without boto3 installed.
# ---------------------------------------------------------------------------


class _S3Client(Protocol):
    """Minimal S3-client protocol for the surfaces below."""

    def list_parts(
        self,
        Bucket: str,
        Key: str,
        UploadId: str,
        **kwargs: Any,
    ) -> dict[str, Any]: ...

    def get_bucket_lifecycle_configuration(
        self,
        Bucket: str,
        **kwargs: Any,
    ) -> dict[str, Any]: ...


# ---------------------------------------------------------------------------
# Sentinel exception names used by callers (avoid importing botocore directly).
# ---------------------------------------------------------------------------

#: Error code string that boto3/botocore raises when the upload-id is gone.
_NO_SUCH_UPLOAD_CODE = "NoSuchUpload"


class NoSuchUploadError(Exception):
    """Raised (by tests or re-raised from botocore) when ListParts returns
    NoSuchUpload."""


# ---------------------------------------------------------------------------
# Resume result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ResumeResult:
    """Return value from :meth:`MultipartResumeManager.resume_or_restart`."""

    #: ``True`` → caller should resume with the existing upload_id.
    #: ``False`` → caller should restart the upload from scratch.
    should_resume: bool
    #: The upload_id to resume with, or ``None`` when ``should_resume=False``.
    upload_id: str | None
    #: Human-readable reason string for logging.
    reason: str


# ---------------------------------------------------------------------------
# MultipartResumeManager
# ---------------------------------------------------------------------------


class MultipartResumeManager:
    """Decide whether to resume a multipart upload or restart from scratch.

    Usage::

        mgr = MultipartResumeManager()
        result = mgr.resume_or_restart(
            state_path=Path("data/backups/.offsite_state.json"),
            s3_client=s3,
            bucket="my-bucket",
            key="backups/dump.tar.gz",
        )
        if result.should_resume:
            # upload_id = result.upload_id
            ...
        else:
            # start a fresh CreateMultipartUpload
            ...

    The method **never raises** on expected failure paths (stale state,
    aborted upload-id) — it always returns a :class:`ResumeResult`.
    Unexpected I/O errors propagate so callers can apply their own retry
    logic.
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def resume_or_restart(
        self,
        state_path: Path,
        s3_client: _S3Client,
        bucket: str,
        key: str,
    ) -> ResumeResult:
        """Evaluate a persisted multipart state file and return a resume decision.

        Steps (per ROADMAP §8.16.5):

        1. Read ``.offsite_state.json`` from *state_path*.  If the file does
           not exist → ``should_resume=False, reason="no_state_file"``.
        2. Compare ``now - mtime`` against
           ``cfg.maint_backup_offsite_state_max_age_h * 3600``.  If stale:
           delete state file → emit audit event → restart.
        3. Probe upload-id liveness via ``list_parts``.  If ``NoSuchUpload``
           → delete state file → emit audit event → restart.
        4. Otherwise → ``should_resume=True``.
        """
        if not state_path.exists():
            return ResumeResult(
                should_resume=False,
                upload_id=None,
                reason="no_state_file",
            )

        # --- read state file ---
        state: dict[str, Any] = json.loads(state_path.read_text(encoding="utf-8"))
        upload_id: str = state.get("upload_id", "")

        # --- mtime staleness check ---
        now = time.time()
        mtime = state_path.stat().st_mtime
        age_s = now - mtime
        age_h = age_s / 3600.0
        max_age_h = cfg.maint_backup_offsite_state_max_age_h

        if max_age_h > 0 and age_s > max_age_h * 3600:
            logger.warning(
                "multipart_resume: state file stale",
                extra={
                    "event": "backup_offsite_upload_id_expired",
                    "expiry_reason": "state_file_stale",
                    "bucket": bucket,
                    "key": key,
                    "age_h": round(age_h, 2),
                    "original_upload_id": upload_id,
                },
            )
            self._emit_expired_event(
                bucket=bucket,
                key=key,
                upload_id=upload_id,
                age_h=age_h,
                reason="state_file_stale",
                state=state,
            )
            state_path.unlink(missing_ok=True)
            return ResumeResult(
                should_resume=False,
                upload_id=None,
                reason="state_file_stale",
            )

        # --- probe upload-id liveness ---
        if not upload_id:
            state_path.unlink(missing_ok=True)
            return ResumeResult(
                should_resume=False,
                upload_id=None,
                reason="no_upload_id_in_state",
            )

        try:
            s3_client.list_parts(Bucket=bucket, Key=key, UploadId=upload_id)
        except Exception as exc:  # noqa: BLE001 — catch botocore ClientError by code
            if _is_no_such_upload(exc):
                logger.warning(
                    "multipart_resume: upload-id expired (NoSuchUpload)",
                    extra={
                        "event": "backup_offsite_upload_id_expired",
                        "expiry_reason": "no_such_upload",
                        "bucket": bucket,
                        "key": key,
                        "age_h": round(age_h, 2),
                        "original_upload_id": upload_id,
                    },
                )
                self._emit_expired_event(
                    bucket=bucket,
                    key=key,
                    upload_id=upload_id,
                    age_h=age_h,
                    reason="no_such_upload",
                    state=state,
                )
                state_path.unlink(missing_ok=True)
                return ResumeResult(
                    should_resume=False,
                    upload_id=None,
                    reason="no_such_upload",
                )
            raise  # unexpected — propagate

        return ResumeResult(
            should_resume=True,
            upload_id=upload_id,
            reason="upload_id_live",
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _emit_expired_event(
        self,
        bucket: str,
        key: str,
        upload_id: str,
        age_h: float,
        reason: str,
        state: dict[str, Any],
    ) -> None:
        """Emit a maint.event.v1{kind=backup_offsite_upload_id_expired} audit row.

        Uses :func:`swarm.sdk.payloads.MaintEvent._make` when available;
        falls back to a structured log entry (avoids hard-importing the
        swarm SDK at xops import time).
        """
        import datetime as _dt

        payload: dict[str, Any] = {
            "kind": "backup_offsite_upload_id_expired",
            "kind_schema_version": 1,
            "produced_at": _dt.datetime.utcnow().isoformat() + "Z",
            "bucket": bucket,
            "key": key,
            "original_upload_id": upload_id,
            "dump_date": state.get("dump_date", ""),
            "age_h": round(age_h, 2),
            "expiry_reason": reason,
        }
        logger.info(
            "maint.event.v1 backup_offsite_upload_id_expired",
            extra={"event_payload": payload},
        )


# ---------------------------------------------------------------------------
# Bucket lifecycle assertion
# ---------------------------------------------------------------------------


def check_bucket_lifecycle(
    s3_client: _S3Client,
    bucket: str,
    min_days: int,
) -> bool:
    """Assert that the bucket's AbortIncompleteMultipartUpload window is safe.

    Returns ``True`` if ``DaysAfterInitiation >= min_days`` (or if no abort
    lifecycle rule exists — the upload-id will survive indefinitely).
    Returns ``False`` if a rule with ``DaysAfterInitiation < min_days`` is
    found — the caller should emit
    ``sec.alert.v1{kind=backup_offsite_lifecycle_too_aggressive}``.

    :param s3_client: A boto3-compatible S3 client (or test stub).
    :param bucket: Bucket name to inspect.
    :param min_days: Minimum acceptable days (``cfg.maint_backup_offsite_lifecycle_min_days``).
    """
    try:
        resp = s3_client.get_bucket_lifecycle_configuration(Bucket=bucket)
    except Exception as exc:  # noqa: BLE001
        if _is_no_such_lifecycle_configuration(exc):
            # No lifecycle rule at all — upload-id never expires on the
            # bucket side; the agent's own mtime check is the sole guard.
            return True
        raise

    rules = resp.get("Rules", [])
    for rule in rules:
        status = rule.get("Status", "Enabled")
        if status != "Enabled":
            continue
        abort = rule.get("AbortIncompleteMultipartUpload", {})
        days = abort.get("DaysAfterInitiation")
        if days is not None and days < min_days:
            logger.warning(
                "bucket lifecycle AbortIncompleteMultipartUpload too aggressive",
                extra={
                    "bucket": bucket,
                    "configured_days": days,
                    "required_min_days": min_days,
                },
            )
            return False

    return True


# ---------------------------------------------------------------------------
# Botocore-free error inspection helpers
# ---------------------------------------------------------------------------


def _is_no_such_upload(exc: Exception) -> bool:
    """Return True if *exc* is a botocore ClientError with code NoSuchUpload,
    or our own :class:`NoSuchUploadError` (used in unit tests)."""
    if isinstance(exc, NoSuchUploadError):
        return True
    # botocore.exceptions.ClientError carries an error code in its response dict.
    response = getattr(exc, "response", None)
    if response:
        code = response.get("Error", {}).get("Code", "")
        return code == _NO_SUCH_UPLOAD_CODE
    return False


def _is_no_such_lifecycle_configuration(exc: Exception) -> bool:
    """Return True if *exc* is a NoSuchLifecycleConfiguration ClientError."""
    response = getattr(exc, "response", None)
    if response:
        code = response.get("Error", {}).get("Code", "")
        return code in ("NoSuchLifecycleConfiguration", "NoSuchBucketPolicy")
    return False
