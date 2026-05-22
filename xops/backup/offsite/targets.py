"""ROADMAP §8.12 — replication target abstraction for off-host backup DR.

Three first-class implementations of :class:`OffsiteBackupTarget`:

* :class:`S3CompatibleTarget` — S3, MinIO, Cloudflare R2, GCS-via-S3-API,
  Backblaze B2. Uses ``urllib3`` + AWS Signature Version 4 (no boto3).
  Multipart upload for dumps >= ``multipart_threshold_mb`` (default 64 MiB).

* :class:`RsyncSshTarget` — operator-managed second host. Wraps
  ``rsync -aHAXz --partial --inplace`` over SSH with strict host-key
  checking. Optional bandwidth cap via ``--bwlimit``.

* :class:`NoopTarget` — explicit dev/mock selection only.
  Boot validation refuses this target when ``profile=prod``
  (``fail_safe_no_offsite_in_prod``).

Design constraints (binding):
* Stdlib-preference: S3 signer is pure stdlib; ``urllib3`` is the only
  third-party dep and is already in requirements via ``requests``.
* Credentials are read once at construction time from the secret-ref file
  path and NEVER logged, raised, or returned.
* ``upload()`` / ``delete()`` are the only public I/O methods. Higher-level
  concerns (upload window, multipart resume, object-lock, per-object
  integrity) are the callers' responsibility.
"""

from __future__ import annotations

import hashlib
import json
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from xml.etree import ElementTree
from pathlib import Path
from subprocess import CompletedProcess, SubprocessError
from typing import Any, Callable, Protocol, Sequence, runtime_checkable

from xops.backup.s3_sigv4 import sign_s3_headers

# ── Sentinel exception ────────────────────────────────────────────────────────


class BackupOffsiteConfigError(RuntimeError):
    """Raised when a safety gate blocks an offsite target configuration.

    Surface tokens (stable; greppable from logs/tests):
    ``fail_safe_no_offsite_in_prod``, ``secret_ref_not_found``,
    ``secret_ref_empty``, ``unknown_offsite_target_kind``.
    """


# ── Protocol ─────────────────────────────────────────────────────────────────


@runtime_checkable
class OffsiteBackupTarget(Protocol):
    """Transport contract for off-host backup replication.

    Every implementation must be:

    * **Idempotent on upload**: uploading the same key twice is safe.
    * **Silent on missing-object delete**: deleting a key that does not
      exist (or is object-lock protected) MUST NOT raise.
    * **Credential-safe**: credentials must never appear in logs,
      exceptions, or return values.
    """

    target_kind: str

    def upload(self, local_path: Path, remote_key: str) -> None:
        """Upload ``local_path`` to the remote target under ``remote_key``."""
        ...

    def delete(self, remote_key: str) -> None:
        """Delete ``remote_key`` from the remote target.

        Must not raise when the key does not exist or when an object-lock
        prevents deletion — in both cases the method returns silently.
        """
        ...


# ── Internal helpers ──────────────────────────────────────────────────────────

_EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()
_PART_SIZE_BYTES = 8 * 1024 * 1024  # 8 MiB per part (S3 minimum is 5 MiB)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class _TokenBucket:
    """Simple monotonic-clock token-bucket for upload bandwidth throttling."""

    def __init__(self, bw_kbps: int) -> None:
        self._bps = bw_kbps * 1024 if bw_kbps > 0 else 0
        self._start = time.monotonic()
        self._sent = 0

    def charge(self, n_bytes: int) -> None:
        """Record ``n_bytes`` uploaded; sleep if ahead of the rate cap."""
        if self._bps == 0:
            return
        self._sent += n_bytes
        expected_s = self._sent / self._bps
        elapsed_s = time.monotonic() - self._start
        lag = expected_s - elapsed_s
        if lag > 0:
            time.sleep(lag)


# ── Multipart-resume state helpers ────────────────────────────────────────────
# State file: ``<dump_dir>/.offsite_state.json`` (mode 0600)
# Format: {remote_key, upload_id, parts:[{part_number, etag}], byte_offset}
# Lifecycle: written before first part (so crash is resumable); updated after
# each successful part; deleted on CompleteMultipartUpload success.


def _state_path(local_path: Path) -> Path:
    """Return the multipart-resume state file path for *local_path*.

    The state file lives next to the dump in the same date directory::

        data/backups/2026-05-21/.offsite_state.json
    """
    return local_path.parent / ".offsite_state.json"


def _load_resume_state(
    state_path: Path,
    remote_key: str,
) -> tuple[str, list[tuple[int, str]], int] | None:
    """Load ``(upload_id, parts, byte_offset)`` from *state_path*, or ``None``.

    Returns ``None`` when the file is absent, unreadable, or keyed to a
    different *remote_key* (stale state from a previous upload attempt).
    The caller must treat ``None`` as "start a fresh multipart upload".
    """
    if not state_path.is_file():
        return None
    try:
        raw = json.loads(state_path.read_text("utf-8"))
        if raw.get("remote_key") != remote_key:
            return None  # stale — different object, start fresh
        parts: list[tuple[int, str]] = [
            (int(p["part_number"]), str(p["etag"]))
            for p in raw.get("parts", [])
        ]
        return raw["upload_id"], parts, int(raw.get("byte_offset", 0))
    except Exception:  # noqa: BLE001 — corrupt state → start fresh
        return None


def _save_resume_state(
    state_path: Path,
    remote_key: str,
    upload_id: str,
    parts: list[tuple[int, str]],
    byte_offset: int,
) -> None:
    """Atomically overwrite *state_path* with the current upload state.

    Written to a ``.tmp`` sibling then renamed so a crash mid-write never
    leaves a corrupt state file.  Mode is set to ``0600`` so only the
    process owner can read the upload ID.
    """
    payload = json.dumps(
        {
            "remote_key": remote_key,
            "upload_id": upload_id,
            "parts": [{"part_number": pn, "etag": et} for pn, et in parts],
            "byte_offset": byte_offset,
        },
        indent=2,
    ).encode("utf-8")
    tmp = state_path.parent / (state_path.name + ".tmp")
    tmp.write_bytes(payload)
    tmp.chmod(0o600)
    tmp.rename(state_path)


def _delete_resume_state(state_path: Path) -> None:
    """Remove *state_path*; silent when already gone."""
    try:
        state_path.unlink()
    except FileNotFoundError:
        pass


# ── NoopTarget ────────────────────────────────────────────────────────────────


class NoopTarget:
    """No-op target for dev/mock stacks.

    Raises :class:`BackupOffsiteConfigError` at construction when
    ``profile="prod"`` (``fail_safe_no_offsite_in_prod``).
    """

    target_kind: str = "noop"

    def __init__(self, *, profile: str = "mock") -> None:
        if profile == "prod":
            raise BackupOffsiteConfigError(
                "fail_safe_no_offsite_in_prod: offsite target is 'none' but "
                "profile=prod. Configure a real DR target or explicitly set "
                "NEGELIR_MAINT_BACKUP_OFFSITE_TARGET=none only in dev/mock."
            )

    def upload(self, local_path: Path, remote_key: str) -> None:
        """No-op upload."""

    def delete(self, remote_key: str) -> None:
        """No-op delete."""


# ── S3CompatibleTarget ────────────────────────────────────────────────────────


class S3CompatibleTarget:
    """S3-compatible target (AWS S3, MinIO, Cloudflare R2, GCS, Backblaze B2).

    Uses ``urllib3`` for HTTP and AWS Signature Version 4 for authentication
    (no boto3 — stdlib-preference for ``xops/``). Multipart upload is used
    for files whose size is at or above ``multipart_threshold_mb``.
    """

    target_kind: str = "s3"

    def __init__(
        self,
        *,
        endpoint: str,
        bucket: str,
        access_key_id: str,
        secret_access_key: str,
        region: str,
        multipart_threshold_mb: int = 64,
        bw_kbps: int = 0,
        object_lock_days: int = 0,
        http_pool: Any | None = None,
    ) -> None:
        """Construct an S3-compatible target.

        Args:
            endpoint: Base URL, e.g. ``"https://s3.amazonaws.com"`` or
                ``"http://minio.local:9000"``. Trailing slash stripped.
            bucket: Destination bucket name.
            access_key_id: S3 access key ID.
            secret_access_key: S3 secret access key. NEVER logged.
            region: AWS region (e.g. ``"us-east-1"``; ``"auto"`` for
                non-AWS services that don't enforce a region).
            multipart_threshold_mb: Files at or above this size (MiB) use
                multipart upload. Files below use a single-part PUT.
            bw_kbps: Bandwidth cap in KB/s. 0 = unlimited.
            object_lock_days: When > 0, every uploaded object receives
                ``x-amz-object-lock-mode=COMPLIANCE`` with a retain-until
                date of ``now + object_lock_days``. 0 = no lock (default).
                Mismatch with the bucket's lock configuration raises
                :exc:`BackupOffsiteConfigError` (``fail_safe_object_lock_misconfigured``).
            http_pool: Injectable ``urllib3.PoolManager`` for unit testing.
                Production code leaves this ``None`` (pool created lazily).
        """
        self._endpoint = endpoint.rstrip("/")
        self._bucket = bucket
        self._access_key_id = access_key_id
        self._secret_access_key = secret_access_key  # NEVER logged
        self._region = region
        self._threshold = multipart_threshold_mb * 1024 * 1024
        self._bw_kbps = bw_kbps
        self._object_lock_days = object_lock_days
        if http_pool is not None:
            self._http = http_pool
        else:
            import urllib3  # lazy import — keeps xops importable without urllib3 in test envs

            self._http = urllib3.PoolManager()

    # ── URL helpers ───────────────────────────────────────────────────────────

    def _object_url(self, key: str) -> str:
        """Path-style URL: ``{endpoint}/{bucket}/{key}``."""
        return f"{self._endpoint}/{self._bucket}/{key.lstrip('/')}"

    def _bucket_url(self, query: str = "") -> str:
        """Path-style bucket URL optionally suffixed with an S3 subresource."""
        suffix = f"?{query}" if query else ""
        return f"{self._endpoint}/{self._bucket}{suffix}"

    # ── Object Lock (WORM) helpers ────────────────────────────────────────────

    def _object_lock_headers(
        self,
        now: datetime | None = None,
    ) -> dict[str, str]:
        """Return ``x-amz-object-lock-*`` headers for WORM, or empty dict.

        Returns ``{}`` when ``object_lock_days == 0`` (the default).
        Called at upload-time so the retain-until timestamp reflects the
        actual upload moment.  An injectable *now* supports deterministic
        unit tests.
        """
        if self._object_lock_days <= 0:
            return {}
        _now = now if now is not None else datetime.now(timezone.utc)
        until = _now + timedelta(days=self._object_lock_days)
        return {
            "x-amz-object-lock-mode": "COMPLIANCE",
            "x-amz-object-lock-retain-until-date": until.strftime(
                "%Y-%m-%dT%H:%M:%S.000Z"
            ),
        }

    def _check_object_lock_resp(self, resp: Any, context: str) -> None:
        """Raise :exc:`BackupOffsiteConfigError` on Object Lock misconfiguration.

        Fires only when ``object_lock_days > 0``.  HTTP 400 whose body
        contains "ObjectLock" or "Object Lock" indicates the bucket does
        not have Object Lock enabled — treated as a misconfiguration, not
        a transient error.  Surface token: ``fail_safe_object_lock_misconfigured``.
        """
        if self._object_lock_days <= 0:
            return
        if resp.status == 400 and (
            b"ObjectLock" in resp.data or b"Object Lock" in resp.data
        ):
            raise BackupOffsiteConfigError(
                f"fail_safe_object_lock_misconfigured: {context} — S3 rejected "
                "the Object Lock headers (bucket may not have Object Lock "
                "enabled). Set NEGELIR_MAINT_BACKUP_OFFSITE_OBJECT_LOCK_DAYS=0 "
                "or enable Object Lock on the target bucket."
            )

    # ── SigV4 helpers ─────────────────────────────────────────────────────────

    def _sign(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        payload_sha256: str,
    ) -> dict[str, str]:
        return sign_s3_headers(
            method=method,
            url=url,
            headers=headers,
            payload_sha256=payload_sha256,
            access_key_id=self._access_key_id,
            secret_access_key=self._secret_access_key,
            region=self._region,
        )

    # ── HTTP helpers ──────────────────────────────────────────────────────────

    def _request(
        self,
        method: str,
        url: str,
        body: bytes = b"",
        extra_headers: dict[str, str] | None = None,
    ) -> Any:
        """Sign and execute an HTTP request; raise :exc:`OSError` on non-2xx."""
        headers: dict[str, str] = {
            "Content-Type": "application/octet-stream",
            **(extra_headers or {}),
        }
        payload_sha256 = _sha256_bytes(body)
        signed = self._sign(method, url, headers, payload_sha256)
        resp = self._http.request(method, url, body=body, headers=signed)
        if resp.status >= 400:
            raise OSError(
                f"S3 {method} {url} returned HTTP {resp.status}: "
                f"{resp.data[:256]!r}"
            )
        return resp

    def _request_allow_status(
        self,
        method: str,
        url: str,
        *,
        body: bytes = b"",
        extra_headers: dict[str, str] | None = None,
        allowed_statuses: tuple[int, ...] = (),
    ) -> Any:
        """Sign and execute an HTTP request, allowing selected non-2xx statuses."""
        headers: dict[str, str] = {
            "Content-Type": "application/octet-stream",
            **(extra_headers or {}),
        }
        payload_sha256 = _sha256_bytes(body)
        signed = self._sign(method, url, headers, payload_sha256)
        resp = self._http.request(method, url, body=body, headers=signed)
        if resp.status >= 400 and resp.status not in allowed_statuses:
            raise OSError(
                f"S3 {method} {url} returned HTTP {resp.status}: "
                f"{resp.data[:256]!r}"
            )
        return resp

    def get_bucket_object_lock_configuration(self, *, Bucket: str) -> dict[str, Any]:
        """Boto-style wrapper used by §8.16.6 preflight checks."""
        if Bucket != self._bucket:
            raise ValueError(f"unexpected bucket {Bucket!r}; expected {self._bucket!r}")
        resp = self._request_allow_status("GET", self._bucket_url("object-lock"), allowed_statuses=(404,))
        if resp.status == 404:
            return {"ObjectLockConfiguration": {"ObjectLockEnabled": "Disabled"}}
        root = ElementTree.fromstring(resp.data or b"<ObjectLockConfiguration />")
        enabled = root.findtext("{*}ObjectLockEnabled") or root.findtext("ObjectLockEnabled") or "Disabled"
        return {"ObjectLockConfiguration": {"ObjectLockEnabled": enabled}}

    def put_object(
        self,
        *,
        Bucket: str,
        Key: str,
        Body: bytes,
        ObjectLockMode: str,
        ObjectLockRetainUntilDate: datetime,
    ) -> dict[str, Any]:
        """Boto-style wrapper used by §8.16.6 preflight checks."""
        if Bucket != self._bucket:
            raise ValueError(f"unexpected bucket {Bucket!r}; expected {self._bucket!r}")
        headers = {
            "x-amz-object-lock-mode": ObjectLockMode,
            "x-amz-object-lock-retain-until-date": ObjectLockRetainUntilDate.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        }
        self._request("PUT", self._object_url(Key), body=Body, extra_headers=headers)
        return {}

    def get_object_retention(self, *, Bucket: str, Key: str) -> dict[str, Any]:
        """Boto-style wrapper used by §8.16.6 preflight checks."""
        if Bucket != self._bucket:
            raise ValueError(f"unexpected bucket {Bucket!r}; expected {self._bucket!r}")
        resp = self._request("GET", f"{self._object_url(Key)}?retention")
        root = ElementTree.fromstring(resp.data or b"<Retention />")
        mode = root.findtext("{*}Mode") or root.findtext("Mode") or ""
        retain_text = (
            root.findtext("{*}RetainUntilDate")
            or root.findtext("RetainUntilDate")
            or ""
        )
        retain_until = None
        if retain_text:
            retain_until = datetime.fromisoformat(retain_text.replace("Z", "+00:00"))
        return {"Retention": {"Mode": mode, "RetainUntilDate": retain_until}}

    def delete_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:
        """Boto-style wrapper used by §8.16.6 preflight checks."""
        if Bucket != self._bucket:
            raise ValueError(f"unexpected bucket {Bucket!r}; expected {self._bucket!r}")
        self._request("DELETE", self._object_url(Key))
        return {}

    # ── Upload ────────────────────────────────────────────────────────────────

    def upload(self, local_path: Path, remote_key: str) -> None:
        """Upload ``local_path`` to ``remote_key`` in the configured bucket.

        Selects multipart upload when
        ``local_path.stat().st_size >= multipart_threshold_mb * 1024 ** 2``.
        """
        file_size = local_path.stat().st_size
        if file_size >= self._threshold:
            self._multipart_upload(local_path, remote_key, file_size)
        else:
            self._single_upload(local_path, remote_key)

    def _single_upload(self, local_path: Path, remote_key: str) -> None:
        data = local_path.read_bytes()
        url = self._object_url(remote_key)
        lock_hdrs = self._object_lock_headers()
        headers: dict[str, str] = {
            "Content-Length": str(len(data)),
            "Content-Type": "application/octet-stream",
            **lock_hdrs,
        }
        payload_sha256 = _sha256_bytes(data)
        signed = self._sign("PUT", url, headers, payload_sha256)
        resp = self._http.request("PUT", url, body=data, headers=signed)
        self._check_object_lock_resp(resp, f"PUT {remote_key!r}")
        if resp.status >= 400:
            raise OSError(
                f"S3 PUT {url} returned HTTP {resp.status}: {resp.data[:256]!r}"
            )

    def _multipart_upload(
        self,
        local_path: Path,
        remote_key: str,
        file_size: int,  # noqa: ARG002 — kept for callers that pass it
    ) -> None:
        url = self._object_url(remote_key)
        state_path = _state_path(local_path)

        # ── 1. Resume or create multipart upload ──────────────────────────────
        resume = _load_resume_state(state_path, remote_key)
        if resume is not None:
            upload_id, parts, byte_offset = resume
        else:
            create_url = f"{url}?uploads"
            lock_hdrs = self._object_lock_headers()
            create_req_headers: dict[str, str] = {
                "Content-Type": "application/xml",
                **lock_hdrs,
            }
            create_sha256 = _sha256_bytes(b"")
            signed_create = self._sign(
                "POST", create_url, create_req_headers, create_sha256
            )
            _cr = self._http.request(
                "POST", create_url, body=b"", headers=signed_create
            )
            self._check_object_lock_resp(
                _cr, f"CreateMultipartUpload {remote_key!r}"
            )
            if _cr.status >= 400:
                raise OSError(
                    f"S3 CreateMultipartUpload {create_url} returned HTTP "
                    f"{_cr.status}: {_cr.data[:256]!r}"
                )
            upload_id = self._parse_xml_text(_cr.data, "UploadId")
            parts = []
            byte_offset = 0
            # Persist upload_id before first part so a crash here is resumable.
            _save_resume_state(state_path, remote_key, upload_id, parts, byte_offset)

        # ── 2. Upload remaining parts ─────────────────────────────────────────
        throttle = _TokenBucket(self._bw_kbps)
        part_num = len(parts)  # already-committed part count

        with local_path.open("rb") as fh:
            if byte_offset:
                fh.seek(byte_offset)
            while True:
                chunk = fh.read(_PART_SIZE_BYTES)
                if not chunk:
                    break
                part_num += 1
                part_sha256 = _sha256_bytes(chunk)
                part_url = (
                    f"{url}?partNumber={part_num}&uploadId={upload_id}"
                )
                headers_part: dict[str, str] = {
                    "Content-Length": str(len(chunk)),
                    "Content-Type": "application/octet-stream",
                }
                signed = self._sign("PUT", part_url, headers_part, part_sha256)
                resp = self._http.request(
                    "PUT", part_url, body=chunk, headers=signed
                )
                if resp.status >= 400:
                    raise OSError(
                        f"S3 UploadPart {part_num} returned HTTP {resp.status}: "
                        f"{resp.data[:128]!r}"
                    )
                etag = resp.headers.get("ETag", "").strip('"')
                parts.append((part_num, etag))
                byte_offset += len(chunk)
                throttle.charge(len(chunk))
                # Persist progress: crash after this point is resumable.
                _save_resume_state(
                    state_path, remote_key, upload_id, parts, byte_offset
                )

        # ── 3. Complete multipart upload ──────────────────────────────────────
        complete_url = f"{url}?uploadId={upload_id}"
        complete_body = self._build_complete_xml(parts).encode("utf-8")
        self._request(
            "POST",
            complete_url,
            complete_body,
            {"Content-Type": "application/xml"},
        )
        # Delete state file: successful CompleteMultipartUpload means no resume needed.
        _delete_resume_state(state_path)

    @staticmethod
    def _parse_xml_text(data: bytes, tag: str) -> str:
        """Extract text of the first element matching ``tag`` (local-name)."""
        root = ET.fromstring(data.decode("utf-8"))
        for el in root.iter():
            if el.tag.split("}")[-1] == tag:
                return el.text or ""
        raise OSError(f"XML response missing <{tag}>: {data[:256]!r}")

    @staticmethod
    def _build_complete_xml(parts: list[tuple[int, str]]) -> str:
        lines = ["<CompleteMultipartUpload>"]
        for part_num, etag in parts:
            lines.append(
                f"  <Part><PartNumber>{part_num}</PartNumber>"
                f'<ETag>"{etag}"</ETag></Part>'
            )
        lines.append("</CompleteMultipartUpload>")
        return "\n".join(lines)

    # ── Delete ────────────────────────────────────────────────────────────────

    def delete(self, remote_key: str) -> None:
        """Delete ``remote_key``; silently ignores 403/404 (object-lock / gone)."""
        url = self._object_url(remote_key)
        signed = self._sign("DELETE", url, {}, _EMPTY_SHA256)
        resp = self._http.request("DELETE", url, headers=signed)
        # 403 = object-lock active; 404 = already gone — both are silent no-ops.
        if resp.status not in (200, 204, 403, 404):
            raise OSError(
                f"S3 DELETE {url} returned HTTP {resp.status}: {resp.data[:128]!r}"
            )

    # ── Per-object integrity probes (§8.12) ───────────────────────────────────

    def head(self, remote_key: str) -> dict[str, str]:
        """HEAD ``remote_key``; returns the response headers dict.

        Used by the per-object integrity probe to confirm the uploaded
        object exists and is reachable before issuing range-GET probes.

        Raises:
            OSError: Non-2xx response from the storage backend.
        """
        url = self._object_url(remote_key)
        signed = self._sign("HEAD", url, {}, _EMPTY_SHA256)
        resp = self._http.request("HEAD", url, headers=signed)
        if resp.status >= 400:
            raise OSError(
                f"S3 HEAD {url} returned HTTP {resp.status}: {resp.data[:128]!r}"
            )
        return dict(resp.headers)

    def range_get(
        self,
        remote_key: str,
        byte_start: int,
        byte_end_inclusive: int,
    ) -> bytes:
        """GET a byte range from ``remote_key`` (RFC 7233 semantics).

        Args:
            remote_key: Object key in the configured bucket.
            byte_start: First byte index (0-based, inclusive).
            byte_end_inclusive: Last byte index (0-based, inclusive).

        Returns:
            The raw bytes of the requested range.

        Raises:
            OSError: Non-200/206 response from the storage backend.
        """
        url = self._object_url(remote_key)
        range_hdr = f"bytes={byte_start}-{byte_end_inclusive}"
        extra: dict[str, str] = {"Range": range_hdr}
        signed = self._sign("GET", url, extra, _EMPTY_SHA256)
        resp = self._http.request("GET", url, headers=signed)
        if resp.status not in (200, 206):
            raise OSError(
                f"S3 GET {url} Range:{range_hdr!r} returned HTTP "
                f"{resp.status}: {resp.data[:128]!r}"
            )
        return bytes(resp.data)

    def preflight(self, cfg: Any) -> None:  # type: ignore[type-arg]
        """Run the §8.16.6 Object-Lock preflight probe.

        Delegates to :class:`xops.backup.s3_preflight.S3PreflightChecker`.
        Raises :exc:`ObjectLockDisabledError`, :exc:`RetentionNotAppliedError`,
        or :exc:`LockNotEnforcedError` on failure.
        """
        from xops.backup.s3_preflight import S3PreflightChecker  # lazy — keeps
        # targets.py importable without s3_preflight optional deps
        S3PreflightChecker().run(self, self._bucket, cfg)


# ── RsyncSshTarget ────────────────────────────────────────────────────────────


class RsyncSshTarget:
    """Off-host rsync-over-SSH target for self-hosted and air-gapped deployments.

    Wraps ``rsync -aHAXz --partial --inplace`` over SSH with strict host-key
    checking (``StrictHostKeyChecking=yes``). Bandwidth is capped via
    ``--bwlimit`` when ``bw_kbps > 0``.
    """

    target_kind: str = "rsync_ssh"

    def __init__(
        self,
        *,
        host: str,
        dest_path: str,
        ssh_known_hosts_file: str,
        bw_kbps: int = 0,
        subprocess_runner: (
            Callable[[Sequence[str]], CompletedProcess[bytes]] | None
        ) = None,
    ) -> None:
        """Construct an rsync-SSH target.

        Args:
            host: SSH hostname or ``user@host``.
            dest_path: Absolute destination path on the remote host.
            ssh_known_hosts_file: Path to a ``known_hosts`` file for strict
                host-key checking. Empty string falls back to the system
                ``known_hosts`` (acceptable in well-configured K8s pods).
            bw_kbps: Bandwidth cap for ``rsync --bwlimit`` in KB/s. 0 = unlimited.
            subprocess_runner: Injected callable for unit testing. Must accept
                a ``Sequence[str]`` argv and return a
                ``subprocess.CompletedProcess``.
        """
        self._host = host
        self._dest_path = dest_path.rstrip("/")
        self._ssh_known_hosts_file = ssh_known_hosts_file
        self._bw_kbps = bw_kbps
        if subprocess_runner is not None:
            self._run = subprocess_runner
        else:
            import subprocess as _sp

            self._run = lambda argv: _sp.run(argv, check=True, capture_output=True)

    def _ssh_opts(self) -> str:
        """Build SSH option flags for strict host-key checking."""
        opts = "StrictHostKeyChecking=yes"
        if self._ssh_known_hosts_file:
            opts += f" -o UserKnownHostsFile={self._ssh_known_hosts_file}"
        return f"ssh -o {opts}"

    def _rsync_argv(self, local_path: Path, remote_dest: str) -> list[str]:
        argv: list[str] = [
            "rsync",
            "-aHAXz",
            "--partial",
            "--inplace",
            f"--rsh={self._ssh_opts()}",
        ]
        if self._bw_kbps > 0:
            argv.append(f"--bwlimit={self._bw_kbps}")
        argv += [str(local_path), remote_dest]
        return argv

    def upload(self, local_path: Path, remote_key: str) -> None:
        """Rsync ``local_path`` to ``{host}:{dest_path}/{remote_key}``."""
        remote_dest = f"{self._host}:{self._dest_path}/{remote_key}"
        argv = self._rsync_argv(local_path, remote_dest)
        try:
            self._run(argv)
        except SubprocessError as exc:
            raise OSError(
                f"rsync upload failed for {remote_key!r}: {exc}"
            ) from exc

    def delete(self, remote_key: str) -> None:
        """Delete ``remote_key`` on the remote host via ``ssh … rm -f``."""
        remote_file = f"{self._dest_path}/{remote_key}"
        argv: list[str] = ["ssh"]
        if self._ssh_known_hosts_file:
            argv += ["-o", f"UserKnownHostsFile={self._ssh_known_hosts_file}"]
        argv += [
            "-o", "StrictHostKeyChecking=yes",
            self._host,
            "rm", "-f", remote_file,
        ]
        try:
            self._run(argv)
        except SubprocessError as exc:
            raise OSError(
                f"rsync_ssh delete failed for {remote_key!r}: {exc}"
            ) from exc


# ── Secret reference reader ───────────────────────────────────────────────────


def _read_secret_from_ref(secret_ref: str) -> str:
    """Read a secret value from a file-path reference.

    The secret is NEVER logged, NEVER returned in an error message,
    and NEVER stored beyond the return value of this function.

    In K8s, ``secret_ref`` is typically a ``secretKeyRef`` volume-mount path.
    In Docker Compose / dev, it is a plain file path (0600).

    Raises:
        BackupOffsiteConfigError: If the file is missing or empty.
    """
    path = Path(secret_ref)
    if not path.is_file():
        raise BackupOffsiteConfigError(
            f"secret_ref_not_found: offsite secret file does not exist: {path}"
        )
    value = path.read_text(encoding="utf-8").strip()
    if not value:
        raise BackupOffsiteConfigError(
            f"secret_ref_empty: offsite secret file is empty: {path}"
        )
    return value


# ── Factory ───────────────────────────────────────────────────────────────────


def target_from_cfg(cfg: Any) -> OffsiteBackupTarget:
    """Construct the :class:`OffsiteBackupTarget` dictated by ``cfg``.

    Intended call site: ``maint.backup.v1`` agent startup. The returned
    target is cached for the lifetime of the agent — it is NOT re-constructed
    per upload.

    Args:
        cfg: A :class:`common.config.Config` instance.

    Returns:
        A concrete :class:`OffsiteBackupTarget` implementation.

    Raises:
        BackupOffsiteConfigError: When the configured target kind is unknown,
            or when a required credential / path is missing.
    """
    kind: str = cfg.maint_backup_offsite_target
    if kind == "none":
        return NoopTarget(profile=cfg.profile)
    if kind == "s3":
        secret = _read_secret_from_ref(
            cfg.maint_backup_offsite_secret_access_key_secret_ref
        )
        return S3CompatibleTarget(
            endpoint=cfg.maint_backup_offsite_endpoint,
            bucket=cfg.maint_backup_offsite_bucket,
            access_key_id=cfg.maint_backup_offsite_access_key_id,
            secret_access_key=secret,
            region=cfg.maint_backup_offsite_s3_region,
            multipart_threshold_mb=cfg.maint_backup_offsite_multipart_threshold_mb,
            bw_kbps=cfg.maint_backup_offsite_bw_kbps,
            object_lock_days=cfg.maint_backup_offsite_object_lock_days,
        )
    if kind == "rsync_ssh":
        return RsyncSshTarget(
            host=cfg.maint_backup_offsite_rsync_host,
            dest_path=cfg.maint_backup_offsite_rsync_dest_path,
            ssh_known_hosts_file=cfg.maint_backup_offsite_rsync_ssh_known_hosts,
            bw_kbps=cfg.maint_backup_offsite_bw_kbps,
        )
    raise BackupOffsiteConfigError(
        f"unknown_offsite_target_kind: {kind!r}. "
        "Valid values: 'none', 's3', 'rsync_ssh'."
    )
