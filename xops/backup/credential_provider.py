"""Phase 8 §8.15.10 Fix B — offsite credential hot-reload.

§8.12's ``S3CompatibleTarget`` reads access keys once at startup.
When the operator rotates the S3 access key (90-day cadence) the
only remediation was to restart the agent (races with leader handover
and loses any partial multipart upload) or keep the old key alive
(security risk).

This module ships two credential-provider implementations:

:class:`FileSecretProvider`
    Compose / dev mode.  Polls the secret file's ``mtime`` every
    ``cfg.maint_backup_offsite_cred_reload_s`` seconds (default 60 s)
    and atomically swaps the in-process credentials on change.

:class:`K8sSecretProvider` *(stub — Phase 14)*
    Will use ``k8s.io/client-go``-style watch on the named Secret
    with the same atomic-swap semantics.

**Continuity contract:**
Active multipart uploads **continue on the old credentials** until
they complete — S3 multipart upload state is server-side and keyed to
the original STS context; switching credentials mid-stream can
invalidate the upload.  Only *new* uploads use the rotated credentials.

**Age alerts:**
The provider tracks when the current credential was last observed to
change (or first loaded at boot).  When the age exceeds
``cfg.maint_backup_offsite_credential_max_age_days`` (default 90 d)
a ``sec.alert.v1{kind=offsite_credential_rotation_required, severity=warn}``
fires daily (debounced).  Past ``max_age + grace_days`` (default 30 d)
the severity escalates to ``critical`` and the provider transitions to
``upload_blocked`` state — the ``is_upload_allowed()`` predicate
returns ``False`` so the backup agent skips new uploads (it keeps
running so the rest of the maint plane is unaffected).

Usage::

    from xops.backup.credential_provider import FileSecretProvider

    provider = FileSecretProvider(
        access_key_id_path="/run/secrets/s3_key_id",
        secret_access_key_path="/run/secrets/s3_key_secret",
        alert_sink=my_alert_sink,
    )
    provider.start()   # starts background mtime-poll thread

    ...

    creds = provider.get()   # thread-safe; returns current S3Credentials
    provider.stop()
"""
from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Optional, Protocol

from ai.common.config import cfg  # type: ignore[import]  # xops runs with ai/ on PYTHONPATH

_log = logging.getLogger("xops.backup.credential_provider")

# Alert-sink type: same convention as advisory_lock.AlertSink
AlertSink = Callable[[str, str, str, dict], None]

# Maximum bytes read from a secret file (prevents accidental huge-file reads).
_SECRET_FILE_MAX_BYTES: int = 4096

# Debounce: emit the age alert at most once per this many seconds (24 h).
_AGE_ALERT_DEBOUNCE_S: float = 86_400.0


@dataclass(frozen=True)
class S3Credentials:
    """Immutable value object: one generation of S3 access credentials."""

    access_key_id: str
    secret_access_key: str
    loaded_at: float  # time.monotonic() — used for age tracking


class CredentialProvider(Protocol):
    """Duck-typed credential source consumed by S3CompatibleTarget."""

    def get(self) -> S3Credentials:
        """Return the current (possibly hot-reloaded) credentials."""
        ...

    def is_upload_allowed(self) -> bool:
        """Return False when the credentials are past the grace-period
        and new uploads must be blocked."""
        ...

    def start(self) -> None:
        """Start any background hot-reload mechanism (idempotent)."""
        ...

    def stop(self) -> None:
        """Stop the background mechanism (idempotent, best-effort)."""
        ...


class FileSecretProvider:
    """Compose-mode credential provider that polls two secret files
    (access_key_id and secret_access_key) for mtime changes and
    atomically swaps the in-process :class:`S3Credentials` on change.

    Thread-safe: :meth:`get` may be called from any thread at any time.
    Active multipart uploads must capture credentials at upload-start
    and hold their own reference — they will continue with the old
    credentials while this provider has already swapped to the new one.

    Parameters
    ----------
    access_key_id_path:
        Path to the file containing just the access key ID (no trailing newline
        or whitespace is assumed; the provider strips both).
    secret_access_key_path:
        Path to the file containing the secret access key.
    alert_sink:
        Optional callback for age-alert emission.  Signature:
        ``(kind, severity, subject, observed) -> None``.
    """

    def __init__(
        self,
        access_key_id_path: str,
        secret_access_key_path: str,
        alert_sink: Optional[AlertSink] = None,
    ) -> None:
        self._id_path = access_key_id_path
        self._key_path = secret_access_key_path
        self._alert_sink = alert_sink

        # Load at construction time so get() is usable before start().
        self._creds: S3Credentials = self._load()
        self._lock = threading.Lock()
        self._last_mtime_id: float = self._mtime(self._id_path)
        self._last_mtime_key: float = self._mtime(self._key_path)

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._last_age_alert_at: float = 0.0

    # ── public interface ───────────────────────────────────────────────

    def get(self) -> S3Credentials:
        """Return the current credentials (thread-safe)."""
        with self._lock:
            return self._creds

    def is_upload_allowed(self) -> bool:
        """Return False when age is past max_age + grace_days."""
        creds = self.get()
        age_s = time.monotonic() - creds.loaded_at
        max_age_s, grace_s = _resolve_age_thresholds()
        if max_age_s == 0:
            return True  # age check disabled
        return age_s < (max_age_s + grace_s)

    def start(self) -> None:
        """Start the background mtime-poll thread (idempotent)."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._poll_loop,
            name="FileSecretProvider-poll",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """Signal the poll thread to stop (idempotent, best-effort)."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=_resolve_reload_interval() + 1.0)
            self._thread = None

    # ── internals ─────────────────────────────────────────────────────

    def _poll_loop(self) -> None:
        interval = _resolve_reload_interval()
        while not self._stop_event.wait(timeout=interval):
            self._check_and_reload()
            self._maybe_emit_age_alert()

    def _check_and_reload(self) -> None:
        """Reload credentials if either secret file's mtime has changed."""
        try:
            mtime_id = self._mtime(self._id_path)
            mtime_key = self._mtime(self._key_path)
        except OSError:
            _log.exception("FileSecretProvider: cannot stat secret files")
            return

        if mtime_id == self._last_mtime_id and mtime_key == self._last_mtime_key:
            return

        try:
            new_creds = self._load()
        except Exception:  # noqa: BLE001
            _log.exception("FileSecretProvider: failed to reload credentials")
            return

        with self._lock:
            self._creds = new_creds
            self._last_mtime_id = mtime_id
            self._last_mtime_key = mtime_key
        _log.info("FileSecretProvider: credentials reloaded (mtime change detected)")

    def _maybe_emit_age_alert(self) -> None:
        """Emit sec.alert.v1 if credential age exceeds thresholds."""
        if self._alert_sink is None:
            return
        creds = self.get()
        age_s = time.monotonic() - creds.loaded_at
        max_age_s, grace_s = _resolve_age_thresholds()
        if max_age_s == 0:
            return  # age check disabled

        age_days = age_s / 86_400.0
        max_age_days = max_age_s / 86_400.0
        grace_days = grace_s / 86_400.0

        if age_s < max_age_s:
            return  # still within max_age

        # Debounce: at most once per 24 h.
        now = time.monotonic()
        if now - self._last_age_alert_at < _AGE_ALERT_DEBOUNCE_S:
            return
        self._last_age_alert_at = now

        if age_s >= max_age_s + grace_s:
            severity = "critical"
        else:
            severity = "warn"

        try:
            self._alert_sink(
                "offsite_credential_rotation_required",
                severity,
                "s3_access_key",
                {
                    "age_days": round(age_days, 1),
                    "max_age_days": max_age_days,
                    "grace_days": grace_days,
                    "upload_blocked": severity == "critical",
                },
            )
        except Exception:  # noqa: BLE001
            _log.exception("FileSecretProvider: age alert sink raised")

    @staticmethod
    def _mtime(path: str) -> float:
        try:
            return os.stat(path).st_mtime
        except OSError:
            return 0.0

    def _load(self) -> S3Credentials:
        """Read both secret files and return a new S3Credentials object."""
        key_id = _read_secret_file(self._id_path)
        secret = _read_secret_file(self._key_path)
        return S3Credentials(
            access_key_id=key_id,
            secret_access_key=secret,
            loaded_at=time.monotonic(),
        )


class K8sSecretProvider:
    """Phase 14 stub — K8s watch-based credential provider.

    Not implemented in Phase 8.  Exists so code that imports
    ``CredentialProvider`` via structural typing can reference this
    class name without an import error.  The constructor raises
    :class:`NotImplementedError` to make the Phase 14 boundary clear.
    """

    def __init__(self, *args: object, **kwargs: object) -> None:
        raise NotImplementedError(
            "K8sSecretProvider is deferred to Phase 14 — use FileSecretProvider "
            "in compose / dev mode"
        )

    def get(self) -> S3Credentials:  # pragma: no cover
        raise NotImplementedError

    def is_upload_allowed(self) -> bool:  # pragma: no cover
        raise NotImplementedError

    def start(self) -> None:  # pragma: no cover
        raise NotImplementedError

    def stop(self) -> None:  # pragma: no cover
        raise NotImplementedError


# ── helpers ────────────────────────────────────────────────────────────


def _read_secret_file(path: str) -> str:
    """Read a secret file, strip whitespace, enforce max-size guard."""
    with open(path, "rb") as fh:
        raw = fh.read(_SECRET_FILE_MAX_BYTES)
    return raw.decode("utf-8", errors="replace").strip()


def _resolve_reload_interval() -> float:
    """Read cfg.maint_backup_offsite_cred_reload_s."""
    val = int(cfg.maint_backup_offsite_cred_reload_s)
    return float(val) if val > 0 else 60.0


def _resolve_age_thresholds() -> tuple[float, float]:
    """Return (max_age_s, grace_s) from cfg."""
    max_days = int(cfg.maint_backup_offsite_credential_max_age_days)
    grace_days = int(cfg.maint_backup_offsite_credential_grace_days)
    return float(max_days) * 86_400.0, float(grace_days) * 86_400.0


__all__ = [
    "AlertSink",
    "CredentialProvider",
    "FileSecretProvider",
    "K8sSecretProvider",
    "S3Credentials",
]
