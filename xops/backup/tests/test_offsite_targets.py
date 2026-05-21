"""ROADMAP §8.12 — unit tests for OffsiteBackupTarget implementations.

Tests the target abstraction, the fail-safe boot gate, S3 upload path
selection (single vs multipart), RsyncSshTarget argv construction, and
the SigV4 signer.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from subprocess import CompletedProcess
from typing import Any, Sequence

import pytest

from xops.backup.offsite.targets import (
    BackupOffsiteConfigError,
    NoopTarget,
    OffsiteBackupTarget,
    RsyncSshTarget,
    S3CompatibleTarget,
)
from xops.backup.s3_sigv4 import sign_s3_headers

# ── Test helpers ──────────────────────────────────────────────────────────────


@dataclass
class FakeS3Response:
    status: int
    data: bytes = b""
    headers: dict[str, str] = field(default_factory=dict)


class FakeS3Pool:
    """Records every HTTP request; returns pre-queued responses."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, bytes]] = []  # (method, url, body)
        self.headers_log: list[dict[str, str]] = []    # signed headers per call
        self._responses: list[FakeS3Response] = []

    def enqueue(self, *responses: FakeS3Response) -> None:
        self._responses.extend(responses)

    def request(
        self,
        method: str,
        url: str,
        body: bytes = b"",
        headers: dict[str, str] | None = None,
        **_kwargs: Any,
    ) -> FakeS3Response:
        self.calls.append((method, url, body or b""))
        self.headers_log.append(dict(headers or {}))
        if self._responses:
            return self._responses.pop(0)
        return FakeS3Response(status=200)


def _fake_runner(argv: Sequence[str]) -> CompletedProcess[bytes]:
    return CompletedProcess(args=list(argv), returncode=0, stdout=b"", stderr=b"")


def _make_s3(pool: FakeS3Pool, **kw: Any) -> S3CompatibleTarget:
    defaults: dict[str, Any] = dict(
        endpoint="http://s3.local:9000",
        bucket="bkt",
        access_key_id="ak",
        secret_access_key="sk",
        region="us-east-1",
        http_pool=pool,
    )
    defaults.update(kw)
    return S3CompatibleTarget(**defaults)


# ── NoopTarget ────────────────────────────────────────────────────────────────


def test_noop_upload_is_silent(tmp_path: Path) -> None:
    f = tmp_path / "dump.age"
    f.write_bytes(b"\x00" * 100)
    NoopTarget().upload(f, "2026-05-21/dump.age")  # must not raise


def test_noop_delete_is_silent() -> None:
    NoopTarget().delete("2026-05-21/dump.age")  # must not raise


def test_noop_refuses_prod_profile() -> None:
    with pytest.raises(BackupOffsiteConfigError, match="fail_safe_no_offsite_in_prod"):
        NoopTarget(profile="prod")


def test_noop_accepts_mock_profile() -> None:
    NoopTarget(profile="mock")  # no exception


# ── Protocol conformance ─────────────────────────────────────────────────────


def test_protocol_conformance_noop() -> None:
    assert isinstance(NoopTarget(), OffsiteBackupTarget)


def test_protocol_conformance_s3() -> None:
    target = _make_s3(FakeS3Pool())
    assert isinstance(target, OffsiteBackupTarget)


def test_protocol_conformance_rsync() -> None:
    target = RsyncSshTarget(
        host="backup.example.com",
        dest_path="/srv/backups",
        ssh_known_hosts_file="/etc/ssh/known_hosts",
        subprocess_runner=_fake_runner,
    )
    assert isinstance(target, OffsiteBackupTarget)


# ── S3CompatibleTarget — single upload ───────────────────────────────────────


def test_s3_single_upload_uses_put(tmp_path: Path) -> None:
    f = tmp_path / "dump.age"
    f.write_bytes(b"x" * 100)
    pool = FakeS3Pool()
    pool.enqueue(FakeS3Response(status=200))
    _make_s3(pool, multipart_threshold_mb=64).upload(f, "key/dump.age")

    assert len(pool.calls) == 1
    method, url, _ = pool.calls[0]
    assert method == "PUT"
    assert "bkt/key/dump.age" in url


def test_s3_single_upload_error_raises(tmp_path: Path) -> None:
    f = tmp_path / "dump.age"
    f.write_bytes(b"x")
    pool = FakeS3Pool()
    pool.enqueue(FakeS3Response(status=500, data=b"InternalError"))
    with pytest.raises(OSError):
        _make_s3(pool).upload(f, "key/dump.age")


# ── S3CompatibleTarget — multipart upload ────────────────────────────────────


def test_s3_multipart_upload_for_large_file(tmp_path: Path) -> None:
    threshold_mb = 1
    data = b"z" * (threshold_mb * 1024 * 1024 + 1)  # 1 byte above threshold
    f = tmp_path / "big.age"
    f.write_bytes(data)

    pool = FakeS3Pool()
    pool.enqueue(
        FakeS3Response(
            status=200,
            data=(
                b"<?xml version='1.0'?>"
                b"<InitiateMultipartUploadResult>"
                b"<UploadId>UPID</UploadId>"
                b"</InitiateMultipartUploadResult>"
            ),
        ),
        FakeS3Response(status=200, headers={"ETag": '"p1etag"'}),
        FakeS3Response(status=200, data=b"<CompleteMultipartUploadResult/>"),
    )

    _make_s3(pool, multipart_threshold_mb=threshold_mb).upload(f, "big/big.age")

    methods = [c[0] for c in pool.calls]
    urls = [c[1] for c in pool.calls]
    assert methods[0] == "POST"
    assert "?uploads" in urls[0]
    assert methods[1] == "PUT"
    assert "partNumber" in urls[1]
    assert methods[2] == "POST"
    assert "uploadId" in urls[2]


def test_s3_small_file_below_threshold_uses_single_put(tmp_path: Path) -> None:
    f = tmp_path / "small.age"
    f.write_bytes(b"y" * 100)  # 100 bytes << 10 MiB
    pool = FakeS3Pool()
    pool.enqueue(FakeS3Response(status=200))
    _make_s3(pool, multipart_threshold_mb=10).upload(f, "small/small.age")

    assert len(pool.calls) == 1
    assert pool.calls[0][0] == "PUT"


# ── S3CompatibleTarget — delete ───────────────────────────────────────────────


def test_s3_delete_sends_delete_request() -> None:
    pool = FakeS3Pool()
    pool.enqueue(FakeS3Response(status=204))
    _make_s3(pool).delete("2026-05-21/dump.age")
    assert pool.calls[0][0] == "DELETE"


def test_s3_delete_silently_ignores_403() -> None:
    """Object-lock active → 403 must not raise."""
    pool = FakeS3Pool()
    pool.enqueue(FakeS3Response(status=403, data=b"ObjectLocked"))
    _make_s3(pool).delete("locked/dump.age")  # must not raise


def test_s3_delete_silently_ignores_404() -> None:
    """Already-gone object → 404 must not raise."""
    pool = FakeS3Pool()
    pool.enqueue(FakeS3Response(status=404, data=b"NoSuchKey"))
    _make_s3(pool).delete("gone/dump.age")  # must not raise


# ── RsyncSshTarget ────────────────────────────────────────────────────────────


def test_rsync_upload_argv_shape(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def runner(argv: Sequence[str]) -> CompletedProcess[bytes]:
        calls.append(list(argv))
        return CompletedProcess(args=list(argv), returncode=0, stdout=b"", stderr=b"")

    f = tmp_path / "dump.age"
    f.write_bytes(b"\x00")
    target = RsyncSshTarget(
        host="backup.example.com",
        dest_path="/srv/backups",
        ssh_known_hosts_file="/etc/known_hosts",
        subprocess_runner=runner,
    )
    target.upload(f, "2026-05-21/dump.age")

    assert len(calls) == 1
    argv = calls[0]
    assert argv[0] == "rsync"
    assert "-aHAXz" in argv
    assert "--partial" in argv
    assert "--inplace" in argv
    rsh = next(a for a in argv if a.startswith("--rsh="))
    assert "StrictHostKeyChecking=yes" in rsh
    assert "/etc/known_hosts" in rsh
    assert "backup.example.com:/srv/backups/2026-05-21/dump.age" in argv


def test_rsync_upload_with_bwlimit(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def runner(argv: Sequence[str]) -> CompletedProcess[bytes]:
        calls.append(list(argv))
        return CompletedProcess(args=list(argv), returncode=0, stdout=b"", stderr=b"")

    f = tmp_path / "dump.age"
    f.write_bytes(b"\x00")
    target = RsyncSshTarget(
        host="backup.example.com",
        dest_path="/srv/backups",
        ssh_known_hosts_file="",
        bw_kbps=50000,
        subprocess_runner=runner,
    )
    target.upload(f, "dump.age")
    assert any("--bwlimit=50000" in a for a in calls[0])


def test_rsync_delete_uses_ssh_rm() -> None:
    calls: list[list[str]] = []

    def runner(argv: Sequence[str]) -> CompletedProcess[bytes]:
        calls.append(list(argv))
        return CompletedProcess(args=list(argv), returncode=0, stdout=b"", stderr=b"")

    target = RsyncSshTarget(
        host="backup.example.com",
        dest_path="/srv/backups",
        ssh_known_hosts_file="/etc/known_hosts",
        subprocess_runner=runner,
    )
    target.delete("2026-05-21/dump.age")
    assert calls[0][0] == "ssh"
    assert "rm" in calls[0]
    assert "-f" in calls[0]


# ── SigV4 signer ─────────────────────────────────────────────────────────────

_FIXED_NOW = datetime(2026, 5, 21, 3, 0, 0, tzinfo=timezone.utc)


def test_sigv4_authorization_header_present() -> None:
    signed = sign_s3_headers(
        method="PUT",
        url="http://s3.local:9000/bucket/key",
        headers={"Content-Type": "application/octet-stream"},
        payload_sha256=hashlib.sha256(b"hello").hexdigest(),
        access_key_id="AKIAIOSFODNN7EXAMPLE",
        secret_access_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        region="us-east-1",
        now=_FIXED_NOW,
    )
    assert "Authorization" in signed
    assert signed["Authorization"].startswith("AWS4-HMAC-SHA256 ")
    assert "AKIAIOSFODNN7EXAMPLE" in signed["Authorization"]
    assert "x-amz-date" in signed
    assert signed["x-amz-date"] == "20260521T030000Z"
    assert "x-amz-content-sha256" in signed


def test_sigv4_secret_not_in_signed_headers() -> None:
    """The secret access key must NOT appear in any returned header value."""
    secret = "SUPER_SECRET_KEY_THAT_MUST_NOT_LEAK"
    signed = sign_s3_headers(
        method="PUT",
        url="http://s3.local:9000/bucket/key",
        headers={},
        payload_sha256=hashlib.sha256(b"").hexdigest(),
        access_key_id="AKID",
        secret_access_key=secret,
        region="us-east-1",
        now=_FIXED_NOW,
    )
    for k, v in signed.items():
        assert secret not in v, f"Secret leaked in header {k!r}: {v!r}"


# ── S3CompatibleTarget — multipart resume (idempotent) ───────────────────────

_PART_SIZE = 8 * 1024 * 1024  # 8 MiB == targets._PART_SIZE_BYTES


def test_s3_multipart_resume_skips_create(tmp_path: Path) -> None:
    """When .offsite_state.json exists for the same key, no CreateMultipartUpload."""
    # Two-part file: first 8 MiB already uploaded, only second part (1 byte) remains.
    data = b"z" * _PART_SIZE + b"\x00"  # 8 MiB + 1 byte
    f = tmp_path / "big.age"
    f.write_bytes(data)

    # Pre-existing resume state: part 1 done.
    state = {
        "remote_key": "dr/big.age",
        "upload_id": "RESUME_UPID",
        "parts": [{"part_number": 1, "etag": "p1etag"}],
        "byte_offset": _PART_SIZE,
    }
    (tmp_path / ".offsite_state.json").write_text(json.dumps(state))

    pool = FakeS3Pool()
    # Expect: one UploadPart (part 2) + one CompleteMultipartUpload, NO CREATE.
    pool.enqueue(
        FakeS3Response(status=200, headers={"ETag": '"p2etag"'}),
        FakeS3Response(status=200, data=b"<CompleteMultipartUploadResult/>"),
    )
    _make_s3(pool, multipart_threshold_mb=1).upload(f, "dr/big.age")

    create_calls = [c for c in pool.calls if c[0] == "POST" and "?uploads" in c[1]]
    assert not create_calls, "resume must not issue CreateMultipartUpload"

    put_calls = [c for c in pool.calls if c[0] == "PUT"]
    assert len(put_calls) == 1, "should upload exactly the remaining part"
    assert "RESUME_UPID" in put_calls[0][1]
    assert "partNumber=2" in put_calls[0][1]

    # State file must be deleted after successful upload.
    assert not (tmp_path / ".offsite_state.json").exists()


def test_s3_multipart_state_deleted_on_success(tmp_path: Path) -> None:
    """State file must not exist after a successful multipart upload."""
    data = b"z" * (_PART_SIZE + 1)
    f = tmp_path / "big.age"
    f.write_bytes(data)

    pool = FakeS3Pool()
    pool.enqueue(
        FakeS3Response(
            status=200,
            data=(
                b"<?xml version='1.0'?>"
                b"<InitiateMultipartUploadResult>"
                b"<UploadId>UPID_CLEAN</UploadId>"
                b"</InitiateMultipartUploadResult>"
            ),
        ),
        FakeS3Response(status=200, headers={"ETag": '"p1etag"'}),
        FakeS3Response(status=200, headers={"ETag": '"p2etag"'}),
        FakeS3Response(status=200, data=b"<CompleteMultipartUploadResult/>"),
    )
    _make_s3(pool, multipart_threshold_mb=1).upload(f, "dr/clean.age")

    assert not (tmp_path / ".offsite_state.json").exists()


def test_s3_multipart_state_preserved_on_part_failure(tmp_path: Path) -> None:
    """State file must survive a failed UploadPart so the next tick can resume."""
    data = b"z" * (_PART_SIZE + 1)
    f = tmp_path / "big.age"
    f.write_bytes(data)

    pool = FakeS3Pool()
    pool.enqueue(
        FakeS3Response(
            status=200,
            data=(
                b"<?xml version='1.0'?>"
                b"<InitiateMultipartUploadResult>"
                b"<UploadId>UPID_FAIL</UploadId>"
                b"</InitiateMultipartUploadResult>"
            ),
        ),
        FakeS3Response(status=500, data=b"InternalError"),  # part 1 fails
    )

    with pytest.raises(OSError):
        _make_s3(pool, multipart_threshold_mb=1).upload(f, "dr/fail.age")

    state_file = tmp_path / ".offsite_state.json"
    assert state_file.exists(), "state file must be preserved for next-tick resume"
    saved = json.loads(state_file.read_text())
    assert saved["upload_id"] == "UPID_FAIL"
    assert saved["remote_key"] == "dr/fail.age"
    # byte_offset == 0: no bytes acknowledged yet (part failed before save)
    assert saved["byte_offset"] == 0


def test_sigv4_different_payloads_produce_different_signatures() -> None:
    """Different payload hashes must yield different Authorization signatures."""
    common: dict[str, Any] = dict(
        method="PUT",
        url="http://s3.local:9000/bucket/key",
        headers={},
        access_key_id="AKID",
        secret_access_key="SECRET",
        region="us-east-1",
        now=_FIXED_NOW,
    )
    sig1 = sign_s3_headers(**common, payload_sha256=hashlib.sha256(b"a").hexdigest())
    sig2 = sign_s3_headers(**common, payload_sha256=hashlib.sha256(b"b").hexdigest())
    assert sig1["Authorization"] != sig2["Authorization"]


# ── S3CompatibleTarget — Object Lock / WORM (§8.12) ──────────────────────────


def test_s3_object_lock_headers_present_on_single_upload(tmp_path: Path) -> None:
    """x-amz-object-lock-* headers must be sent when object_lock_days > 0."""
    f = tmp_path / "dump.age"
    f.write_bytes(b"x" * 100)
    pool = FakeS3Pool()
    pool.enqueue(FakeS3Response(status=200))
    _make_s3(pool, object_lock_days=30).upload(f, "2026-05-21/dump.age")

    hdrs = pool.headers_log[0]
    assert hdrs.get("x-amz-object-lock-mode") == "COMPLIANCE"
    retain = hdrs.get("x-amz-object-lock-retain-until-date", "")
    assert retain.endswith(".000Z"), f"unexpected retain-until format: {retain!r}"


def test_s3_no_object_lock_headers_when_zero_days(tmp_path: Path) -> None:
    """No lock headers when object_lock_days == 0 (the default)."""
    f = tmp_path / "dump.age"
    f.write_bytes(b"x" * 100)
    pool = FakeS3Pool()
    pool.enqueue(FakeS3Response(status=200))
    _make_s3(pool, object_lock_days=0).upload(f, "2026-05-21/dump.age")

    hdrs = pool.headers_log[0]
    assert "x-amz-object-lock-mode" not in hdrs
    assert "x-amz-object-lock-retain-until-date" not in hdrs


def test_s3_object_lock_headers_on_multipart_create(tmp_path: Path) -> None:
    """Object Lock headers go on CreateMultipartUpload, not on individual parts."""
    threshold_mb = 1
    data = b"z" * (threshold_mb * 1024 * 1024 + 1)
    f = tmp_path / "big.age"
    f.write_bytes(data)
    pool = FakeS3Pool()
    pool.enqueue(
        FakeS3Response(
            status=200,
            data=(
                b"<?xml version='1.0'?>"
                b"<InitiateMultipartUploadResult>"
                b"<UploadId>UPID_LOCK</UploadId>"
                b"</InitiateMultipartUploadResult>"
            ),
        ),
        FakeS3Response(status=200, headers={"ETag": '"p1etag"'}),
        FakeS3Response(status=200, data=b"<CompleteMultipartUploadResult/>"),
    )
    _make_s3(pool, multipart_threshold_mb=threshold_mb, object_lock_days=30).upload(
        f, "big/big.age"
    )

    # First call is CreateMultipartUpload (POST ?uploads)
    create_hdrs = pool.headers_log[0]
    assert create_hdrs.get("x-amz-object-lock-mode") == "COMPLIANCE"
    retain = create_hdrs.get("x-amz-object-lock-retain-until-date", "")
    assert retain.endswith(".000Z"), f"unexpected retain-until format: {retain!r}"

    # Individual UploadPart must NOT carry lock headers (set at initiate time)
    put_hdrs = pool.headers_log[1]
    assert "x-amz-object-lock-mode" not in put_hdrs


def test_s3_object_lock_misconfigured_raises_fail_safe_single(tmp_path: Path) -> None:
    """400 with ObjectLock in body on single PUT → fail_safe_object_lock_misconfigured."""
    f = tmp_path / "dump.age"
    f.write_bytes(b"x" * 100)
    pool = FakeS3Pool()
    pool.enqueue(
        FakeS3Response(
            status=400,
            data=(
                b"<Error><Code>InvalidRequest</Code>"
                b"<Message>Bucket is missing ObjectLock Configuration</Message></Error>"
            ),
        )
    )
    with pytest.raises(
        BackupOffsiteConfigError, match="fail_safe_object_lock_misconfigured"
    ):
        _make_s3(pool, object_lock_days=30).upload(f, "2026-05-21/dump.age")


def test_s3_object_lock_misconfigured_raises_fail_safe_multipart(
    tmp_path: Path,
) -> None:
    """400 with ObjectLock in body on CreateMultipartUpload → fail_safe_object_lock_misconfigured."""
    threshold_mb = 1
    data = b"z" * (threshold_mb * 1024 * 1024 + 1)
    f = tmp_path / "big.age"
    f.write_bytes(data)
    pool = FakeS3Pool()
    pool.enqueue(
        FakeS3Response(
            status=400,
            data=(
                b"<Error><Code>InvalidRequest</Code>"
                b"<Message>Bucket is missing ObjectLock Configuration</Message></Error>"
            ),
        )
    )
    with pytest.raises(
        BackupOffsiteConfigError, match="fail_safe_object_lock_misconfigured"
    ):
        _make_s3(
            pool, multipart_threshold_mb=threshold_mb, object_lock_days=30
        ).upload(f, "big/big.age")


def test_s3_object_lock_overwrite_during_retention_raises_oserror(
    tmp_path: Path,
) -> None:
    """Attempted PUT over a WORM-locked object → S3 returns 403 (ObjectLockedException) → OSError."""
    f = tmp_path / "dump.age"
    f.write_bytes(b"x" * 100)
    pool = FakeS3Pool()
    pool.enqueue(
        FakeS3Response(
            status=403,
            data=(
                b"<Error><Code>ObjectLockedException</Code>"
                b"<Message>Object is protected by Object Lock</Message></Error>"
            ),
        )
    )
    with pytest.raises(OSError):
        _make_s3(pool, object_lock_days=30).upload(f, "2026-05-21/dump.age")


def test_s3_object_lock_delete_during_retention_silently_ignored() -> None:
    """Attempted DELETE on a WORM-locked object → S3 returns 403 → silently ignored."""
    pool = FakeS3Pool()
    pool.enqueue(
        FakeS3Response(
            status=403,
            data=(
                b"<Error><Code>ObjectLockedException</Code>"
                b"<Message>Object is WORM protected and cannot be deleted</Message></Error>"
            ),
        )
    )
    _make_s3(pool).delete("2026-05-21/dump.age")  # must not raise
