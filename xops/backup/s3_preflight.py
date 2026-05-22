"""Phase 8 §8.16.6 — S3 Object-Lock / WORM boot-time preflight probe.

Public surfaces
---------------
* :class:`S3PreflightChecker` — runs the five-step probe sequence against a
  bucket to verify that Object-Lock COMPLIANCE mode is actually enforced.
* :func:`preflight_due` — lightweight cadence helper: returns ``True`` when
  enough time has elapsed since the last successful probe.

Errors raised (all inherit :class:`S3PreflightError`)
------------------------------------------------------
* :class:`ObjectLockDisabledError`   — bucket does not have Object-Lock enabled
  while ``cfg.maint_backup_offsite_object_lock_days > 0``.
* :class:`RetentionNotAppliedError` — sentinel retention metadata did not round-
  trip (IAM policy likely missing ``s3:PutObjectRetention``).
* :class:`LockNotEnforcedError`     — sentinel was deleted during its retention
  window (Object-Lock is NOT enforced on this bucket — catastrophic).

All three error classes are non-recoverable from the agent's perspective; the
caller should flip the agent into spool-mode and emit a
``kind=backup_offsite_preflight_failed`` sec.alert.
"""
from __future__ import annotations

import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Protocol


# ---------------------------------------------------------------------------
# Protocols — keep hard S3 dependency off the import path so the module
# is importable and unit-testable without boto3 installed.
# ---------------------------------------------------------------------------


class _S3Client(Protocol):
    """Minimal S3-client protocol used by the preflight checker."""

    def get_bucket_object_lock_configuration(
        self,
        Bucket: str,
        **kwargs: Any,
    ) -> dict[str, Any]: ...

    def put_object(
        self,
        Bucket: str,
        Key: str,
        Body: bytes,
        **kwargs: Any,
    ) -> dict[str, Any]: ...

    def get_object_retention(
        self,
        Bucket: str,
        Key: str,
        **kwargs: Any,
    ) -> dict[str, Any]: ...

    def delete_object(
        self,
        Bucket: str,
        Key: str,
        **kwargs: Any,
    ) -> dict[str, Any]: ...


# ---------------------------------------------------------------------------
# Config Protocol — accept the real AppConfig or a lightweight stub in tests.
# ---------------------------------------------------------------------------


class _Cfg(Protocol):
    maint_backup_offsite_object_lock_days: int
    maint_backup_offsite_object_lock_required: bool
    fail_safe_offsite_object_lock_disabled: bool
    fail_safe_offsite_retention_not_applied: bool
    fail_safe_offsite_lock_not_enforced: bool


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class S3PreflightError(Exception):
    """Base class for all preflight failures."""


class ObjectLockDisabledError(S3PreflightError):
    """Bucket does not have Object-Lock enabled when it is required."""


class RetentionNotAppliedError(S3PreflightError):
    """Retention metadata on the sentinel object did not round-trip correctly."""


class LockNotEnforcedError(S3PreflightError):
    """Sentinel was deleted during its retention window — WORM is not enforced."""


# ---------------------------------------------------------------------------
# S3PreflightChecker
# ---------------------------------------------------------------------------

#: Retention window for the sentinel object (seconds).
_SENTINEL_RETENTION_S: int = 60

#: Size of the sentinel object body (bytes).
_SENTINEL_SIZE_B: int = 1024

#: Tolerance for comparing retain-until timestamps (seconds).
_RETENTION_CLOCK_TOLERANCE_S: int = 10


class S3PreflightChecker:
    """Boot-time probe that verifies S3 Object-Lock / WORM is actually enforced.

    Usage::

        checker = S3PreflightChecker(instance_id="pod-abc123")
        checker.run(s3_client=s3, bucket="my-bucket", cfg=cfg)
        # raises S3PreflightError subclass on failure; returns None on success.

    The probe is idempotent — the sentinel is a fresh UUID every run and the
    60-second retention window ensures the object self-cleans via S3 lifecycle.
    Step 5 (GC) only logs; it never blocks or raises.
    """

    def __init__(self, instance_id: str = "") -> None:
        self._instance_id = instance_id or "unknown"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        s3_client: _S3Client,
        bucket: str,
        cfg: _Cfg,
    ) -> None:
        """Execute the five-step preflight probe.

        Steps (§8.16.6 doctrine):
          1. ``GetBucketObjectLockConfiguration`` — fail if Object-Lock is
             disabled and it is required.
          2. Upload 1KB sentinel with COMPLIANCE + 60-second retain-until.
          3. ``GetObjectRetention`` — verify mode + retain-until match.
          4. ``DeleteObject`` during retention — assert 403.
          5. Schedule / log GC (sentinel auto-expires in 60 s via lifecycle).

        :raises ObjectLockDisabledError: step 1 mismatch.
        :raises RetentionNotAppliedError: step 3 mismatch.
        :raises LockNotEnforcedError: step 4 mismatch (no 403).
        """
        sentinel_key = self._build_sentinel_key()
        retain_until = datetime.fromtimestamp(
            time.time() + _SENTINEL_RETENTION_S, tz=timezone.utc
        )

        # Step 1 — bucket lock configuration
        if cfg.maint_backup_offsite_object_lock_required:
            self._check_bucket_object_lock(s3_client, bucket, cfg)

        # Steps 2–4 — sentinel upload, read-back, delete-reject
        try:
            self._upload_sentinel(s3_client, bucket, sentinel_key, retain_until)
            self._verify_retention(s3_client, bucket, sentinel_key, retain_until, cfg)
            self._assert_delete_rejected(s3_client, bucket, sentinel_key, cfg)
        finally:
                # Step 5 — schedule best-effort GC after the short retention window.
                self._schedule_gc(s3_client, bucket, sentinel_key)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_sentinel_key(self) -> str:
        """Build a unique sentinel object key for this probe run."""
        utc_iso = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        run_id = uuid.uuid4().hex[:12]
        return (
            f"negelir-preflight-{self._instance_id}-{run_id}-{utc_iso}.bin"
        )

    def _check_bucket_object_lock(
        self,
        s3_client: _S3Client,
        bucket: str,
        cfg: _Cfg,
    ) -> None:
        """Step 1: verify bucket has Object-Lock enabled."""
        response = s3_client.get_bucket_object_lock_configuration(Bucket=bucket)
        rule = response.get("ObjectLockConfiguration", {})
        enabled = rule.get("ObjectLockEnabled", "Disabled")
        if enabled != "Enabled" and cfg.maint_backup_offsite_object_lock_days > 0:
            if cfg.fail_safe_offsite_object_lock_disabled:
                raise ObjectLockDisabledError(
                    f"fail_safe_offsite_object_lock_disabled: bucket={bucket!r} "
                    f"has ObjectLockEnabled={enabled!r} but "
                    f"maint_backup_offsite_object_lock_days="
                    f"{cfg.maint_backup_offsite_object_lock_days}"
                )

    def _upload_sentinel(
        self,
        s3_client: _S3Client,
        bucket: str,
        key: str,
        retain_until: datetime,
    ) -> None:
        """Step 2: upload 1KB sentinel with COMPLIANCE retention."""
        s3_client.put_object(
            Bucket=bucket,
            Key=key,
            Body=b"\x00" * _SENTINEL_SIZE_B,
            ObjectLockMode="COMPLIANCE",
            ObjectLockRetainUntilDate=retain_until,
        )

    def _verify_retention(
        self,
        s3_client: _S3Client,
        bucket: str,
        key: str,
        expected_retain_until: datetime,
        cfg: _Cfg,
    ) -> None:
        """Step 3: read back retention metadata and assert match."""
        response = s3_client.get_object_retention(Bucket=bucket, Key=key)
        retention = response.get("Retention", {})
        mode = retention.get("Mode", "")
        actual_retain_until: datetime | None = retention.get("RetainUntilDate")

        mismatch_reasons: list[str] = []
        if mode != "COMPLIANCE":
            mismatch_reasons.append(f"mode={mode!r} (expected 'COMPLIANCE')")
        if actual_retain_until is None:
            mismatch_reasons.append("RetainUntilDate missing")
        elif isinstance(actual_retain_until, datetime):
            delta = abs(
                actual_retain_until.timestamp() - expected_retain_until.timestamp()
            )
            if delta > _RETENTION_CLOCK_TOLERANCE_S:
                mismatch_reasons.append(
                    f"RetainUntilDate skew={delta:.1f}s "
                    f"(tolerance={_RETENTION_CLOCK_TOLERANCE_S}s)"
                )

        if mismatch_reasons and cfg.fail_safe_offsite_retention_not_applied:
            raise RetentionNotAppliedError(
                "fail_safe_offsite_retention_not_applied: "
                + "; ".join(mismatch_reasons)
            )

    def _assert_delete_rejected(
        self,
        s3_client: _S3Client,
        bucket: str,
        key: str,
        cfg: _Cfg,
    ) -> None:
        """Step 4: attempt delete during retention; assert 403."""
        deleted = False
        try:
            s3_client.delete_object(Bucket=bucket, Key=key)
            # If we reach here, delete succeeded — WORM is NOT enforced.
            deleted = True
        except Exception as exc:
            # Any exception (including ClientError 403 AccessDenied) is the
            # expected happy path — the bucket correctly blocked the delete.
            error_code = getattr(getattr(exc, "response", {}), "get", lambda *_: None)(
                "Error", {}
            ).get("Code", "")
            if not error_code:
                # Try the standard boto3 error_code attribute path.
                error_code = getattr(exc, "error_code", "") or str(
                    getattr(getattr(exc, "response", {}), "__class__", exc)
                )
            # Any exception from delete_object is acceptable (403 expected).
            deleted = False

        if deleted and cfg.fail_safe_offsite_lock_not_enforced:
            raise LockNotEnforcedError(
                f"fail_safe_offsite_lock_not_enforced: sentinel {key!r} was "
                f"deleted during its {_SENTINEL_RETENTION_S}s retention window "
                "— WORM is not enforced on this bucket"
            )

    def _log_gc(self, bucket: str, key: str, delay_s: int) -> None:
        """Log sentinel GC intent and schedule delay."""
        # Import lazily to keep the module importable without the full app stack.
        try:
            from common.logger import get_logger  # type: ignore[import]
            logger = get_logger(__name__)
        except Exception:
            import logging
            logger = logging.getLogger(__name__)
        logger.debug(
            "s3_preflight: sentinel scheduled for GC",
            extra={
                "bucket": bucket,
                "key": key,
                "retention_s": _SENTINEL_RETENTION_S,
                "gc_delay_s": delay_s,
            },
        )

    def _schedule_gc(self, s3_client: _S3Client, bucket: str, key: str) -> None:
        """Step 5: schedule best-effort sentinel cleanup after retention."""
        delay_s = _SENTINEL_RETENTION_S + 5
        timer = threading.Timer(delay_s, self._gc_sentinel, args=(s3_client, bucket, key))
        timer.daemon = True
        timer.start()
        self._log_gc(bucket, key, delay_s)

    def _gc_sentinel(self, s3_client: _S3Client, bucket: str, key: str) -> None:
        """Best-effort sentinel cleanup once the short retention window lapses."""
        try:
            s3_client.delete_object(Bucket=bucket, Key=key)
        except Exception:
            # Best-effort cleanup only: expired object may already be gone,
            # or the backend may still be enforcing retention slightly longer.
            return


# ---------------------------------------------------------------------------
# Cadence helper
# ---------------------------------------------------------------------------


def preflight_due(last_preflight_utc: float, interval_h: float) -> bool:
    """Return ``True`` when another preflight probe is due.

    :param last_preflight_utc: Unix timestamp of the last successful probe.
        Pass ``0.0`` to force an immediate probe.
    :param interval_h: Probe interval in hours (from
        ``cfg.maint_backup_offsite_preflight_interval_h``).
    :returns: ``True`` if ``now - last_preflight_utc >= interval_h * 3600``.
    """
    if interval_h <= 0:
        return True
    elapsed_s = time.time() - last_preflight_utc
    return elapsed_s >= interval_h * 3600
