"""ROADMAP §8.12 — Per-object integrity: sidecar upload and post-upload probe.

Each uploaded backup object must carry two sidecars:

* ``<key>.sha256.txt``  — bare SHA-256 hex digest of the dump bytes
  (ASCII hex string, no trailing newline).
* ``<key>.manifest.json`` — JSON object with keys:
  ``date``, ``size_bytes``, ``checksum_sha256``,
  ``encryption_key_versions``, ``producer_pod_instance_id``,
  ``uploaded_at_utc``.

After the main object and both sidecars are uploaded, a HEAD + two
range-GET probes (first 4 KiB + last 4 KiB) verify the remote copy
matches the local source before the upload is considered complete.

Probe scope:

* :class:`~xops.backup.offsite.targets.S3CompatibleTarget` — HEAD +
  range-GET are natively supported; probe is mandatory.
* :class:`~xops.backup.offsite.targets.RsyncSshTarget` /
  :class:`~xops.backup.offsite.targets.NoopTarget` — probe is skipped.
  rsync's own exit-zero provides the integrity guarantee for the SSH
  path; noop is dev-only.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_PROBE_SIZE = 4 * 1024  # 4 KiB per probe window


class ObjectIntegrityError(RuntimeError):
    """Raised when the post-upload range-GET probe detects a byte mismatch.

    Surface token: ``post_upload_probe_mismatch``.
    """


def _sha256_file(path: Path) -> str:
    """Compute the SHA-256 hex digest of *path* in streaming 1 MiB chunks."""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def build_manifest(
    local_path: Path,
    sha256_hex: str,
    *,
    uploaded_at_utc: datetime,
    encryption_key_versions: list[str] | None = None,
    producer_pod_instance_id: str = "",
) -> dict[str, Any]:
    """Build the per-dump manifest dict for *local_path*.

    The ``date`` field is derived from the ISO-8601 date component of
    *uploaded_at_utc* so it is always accurate regardless of the
    local directory structure.

    Args:
        local_path: Path to the dump file on disk.
        sha256_hex: Hex SHA-256 digest of the dump bytes (pre-computed).
        uploaded_at_utc: Upload timestamp (UTC). Used for ``date`` and
            ``uploaded_at_utc`` fields.
        encryption_key_versions: Optional list of version identifiers for
            the encryption keys used to produce the dump.
        producer_pod_instance_id: Kubernetes pod / host identifier of the
            agent that produced this dump.

    Returns:
        Manifest dict with keys ``date``, ``size_bytes``,
        ``checksum_sha256``, ``encryption_key_versions``,
        ``producer_pod_instance_id``, ``uploaded_at_utc``.
    """
    return {
        "date": uploaded_at_utc.date().isoformat(),
        "size_bytes": local_path.stat().st_size,
        "checksum_sha256": sha256_hex,
        "encryption_key_versions": encryption_key_versions or [],
        "producer_pod_instance_id": producer_pod_instance_id,
        "uploaded_at_utc": uploaded_at_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def upload_with_integrity(
    target: Any,
    local_path: Path,
    remote_key: str,
    *,
    encryption_key_versions: list[str] | None = None,
    producer_pod_instance_id: str = "",
    now: datetime | None = None,
) -> dict[str, Any]:
    """Upload *local_path*, add sidecars, and verify the remote copy.

    Steps performed in order:

    1. Compute SHA-256 of *local_path* (streaming, any size).
    2. Upload *local_path* to *remote_key*.
    3. Upload ``<remote_key>.sha256.txt`` -- the bare hex digest.
    4. Upload ``<remote_key>.manifest.json`` -- the manifest JSON.
    5. For :class:`~xops.backup.offsite.targets.S3CompatibleTarget` only:
       HEAD + first/last 4 KiB range-GET probe to confirm the remote
       copy matches the local source before declaring the upload complete.

    For :class:`~xops.backup.offsite.targets.RsyncSshTarget` and
    :class:`~xops.backup.offsite.targets.NoopTarget` the probe is
    skipped -- rsync's own exit-zero provides integrity for the SSH path;
    noop is dev-only.

    Args:
        target: Any ``OffsiteBackupTarget`` implementation.
        local_path: Local file to replicate.
        remote_key: Destination key on the target.
        encryption_key_versions: Key version identifiers for the manifest.
        producer_pod_instance_id: Agent pod name for the manifest.
        now: Injectable UTC datetime for deterministic tests.

    Returns:
        The manifest dict on success.

    Raises:
        ObjectIntegrityError: Range-GET probe bytes differ from the local
            source (remote copy is corrupted or truncated).
        OSError: Low-level upload or HTTP error from the target.
    """
    # Lazy import breaks the circular dependency between integrity and targets.
    from xops.backup.offsite.targets import S3CompatibleTarget  # noqa: PLC0415

    uploaded_at = now or datetime.now(timezone.utc)
    sha256_hex = _sha256_file(local_path)
    manifest = build_manifest(
        local_path,
        sha256_hex,
        uploaded_at_utc=uploaded_at,
        encryption_key_versions=encryption_key_versions,
        producer_pod_instance_id=producer_pod_instance_id,
    )

    # -- 1. Upload main object -----------------------------------------------
    target.upload(local_path, remote_key)

    # -- 2 & 3. Upload sidecars (temp dir; cleaned up on context exit) -------
    with tempfile.TemporaryDirectory() as _tmpdir:
        tmp = Path(_tmpdir)

        sha_local = tmp / (local_path.name + ".sha256.txt")
        sha_local.write_text(sha256_hex, encoding="utf-8")
        target.upload(sha_local, remote_key + ".sha256.txt")

        mf_local = tmp / (local_path.name + ".manifest.json")
        mf_local.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        target.upload(mf_local, remote_key + ".manifest.json")

    # -- 4. Post-upload probe (S3 targets only) --------------------------------
    if isinstance(target, S3CompatibleTarget):
        _probe_s3(target, local_path, remote_key)

    return manifest


def _probe_s3(
    target: Any,
    local_path: Path,
    remote_key: str,
) -> None:
    """HEAD + first/last 4 KiB range-GET integrity probe.

    Raises :exc:`ObjectIntegrityError` when either probe's remote bytes
    diverge from the local source file.

    Empty files are verified by HEAD only (no bytes to probe).
    Files whose size is <= 4 KiB use a single range-GET (first == last window).
    """
    file_size = local_path.stat().st_size

    # HEAD -- confirms the object is reachable (raises OSError on 4xx/5xx).
    target.head(remote_key)

    if file_size == 0:
        return  # empty dump: existence confirmed by HEAD; nothing else to check

    # Read local reference bytes.
    with local_path.open("rb") as fh:
        first_local = fh.read(_PROBE_SIZE)
        if file_size > _PROBE_SIZE:
            fh.seek(file_size - _PROBE_SIZE)
            last_local = fh.read(_PROBE_SIZE)
        else:
            last_local = first_local  # small file: same window for both probes

    # Range-GET: first 4 KiB (or entire file if smaller).
    first_end = min(_PROBE_SIZE, file_size) - 1
    first_remote = target.range_get(remote_key, 0, first_end)
    if first_remote != first_local[: first_end + 1]:
        raise ObjectIntegrityError(
            f"post_upload_probe_mismatch: {remote_key!r} -- "
            f"first {_PROBE_SIZE} bytes differ between local and remote"
        )

    # Range-GET: last 4 KiB (skip when file size <= 4 KiB -- already covered).
    if file_size > _PROBE_SIZE:
        last_start = file_size - _PROBE_SIZE
        last_remote = target.range_get(remote_key, last_start, file_size - 1)
        if last_remote != last_local:
            raise ObjectIntegrityError(
                f"post_upload_probe_mismatch: {remote_key!r} -- "
                f"last {_PROBE_SIZE} bytes differ between local and remote"
            )
