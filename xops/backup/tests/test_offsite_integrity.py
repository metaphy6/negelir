"""ROADMAP §8.12 — tests for per-object integrity (sidecar + post-upload probe).

Covers:
* build_manifest field contract
* upload_with_integrity uploads main + two sidecars
* sha256.txt and manifest.json sidecar contents
* S3 probe: HEAD + first/last 4 KiB range-GET on happy path
* S3 probe: ObjectIntegrityError on first-block or last-block mismatch
* S3 probe: small file (< 4 KiB) uses single range-GET
* S3 probe: empty file uses HEAD only
* Non-S3 targets (Noop) skip the probe entirely
* S3CompatibleTarget.head() and range_get() method shapes
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from xops.backup.offsite.integrity import (
    ObjectIntegrityError,
    build_manifest,
    upload_with_integrity,
)
from xops.backup.offsite.targets import (
    NoopTarget,
    S3CompatibleTarget,
)

_FIXED_NOW = datetime(2026, 5, 21, 10, 0, 0, tzinfo=timezone.utc)
_PROBE = 4 * 1024  # 4 KiB


# -- Minimal recording target ------------------------------------------------


class _FakeTarget:
    """Records upload calls; silently no-ops delete."""

    def __init__(self) -> None:
        self.upload_calls: list[tuple[Path, str]] = []

    def upload(self, local_path: Path, remote_key: str) -> None:
        self.upload_calls.append((local_path, remote_key))

    def delete(self, remote_key: str) -> None:
        pass


# -- FakeS3Pool / _make_s3 (mirrors test_offsite_targets.py) ------------------


@dataclass
class _FakeS3Resp:
    status: int
    data: bytes = b""
    headers: dict[str, str] = field(default_factory=dict)


class _FakeS3Pool:
    """Records every HTTP call; returns pre-queued responses."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, bytes]] = []
        self.headers_log: list[dict[str, str]] = []
        self._responses: list[_FakeS3Resp] = []

    def enqueue(self, *responses: _FakeS3Resp) -> None:
        self._responses.extend(responses)

    def request(
        self,
        method: str,
        url: str,
        body: bytes = b"",
        headers: dict[str, str] | None = None,
        **_: Any,
    ) -> _FakeS3Resp:
        self.calls.append((method, url, body or b""))
        self.headers_log.append(dict(headers or {}))
        if self._responses:
            return self._responses.pop(0)
        return _FakeS3Resp(status=200)


def _make_s3(pool: _FakeS3Pool, **kw: Any) -> S3CompatibleTarget:
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


# -- build_manifest -----------------------------------------------------------


def test_build_manifest_all_required_fields(tmp_path: Path) -> None:
    f = tmp_path / "dump.age"
    f.write_bytes(b"x" * 1234)
    m = build_manifest(
        f,
        "deadbeef",
        uploaded_at_utc=_FIXED_NOW,
        encryption_key_versions=["k1", "k2"],
        producer_pod_instance_id="pod-abc",
    )
    assert m["date"] == "2026-05-21"
    assert m["size_bytes"] == 1234
    assert m["checksum_sha256"] == "deadbeef"
    assert m["encryption_key_versions"] == ["k1", "k2"]
    assert m["producer_pod_instance_id"] == "pod-abc"
    assert m["uploaded_at_utc"] == "2026-05-21T10:00:00Z"


def test_build_manifest_default_optional_fields(tmp_path: Path) -> None:
    f = tmp_path / "dump.age"
    f.write_bytes(b"")
    m = build_manifest(f, "aabbcc", uploaded_at_utc=_FIXED_NOW)
    assert m["encryption_key_versions"] == []
    assert m["producer_pod_instance_id"] == ""
    assert m["size_bytes"] == 0


# -- upload_with_integrity — upload structure ---------------------------------


def test_upload_with_integrity_uploads_main_and_two_sidecars(
    tmp_path: Path,
) -> None:
    """Three upload calls: main object, sha256.txt, manifest.json."""
    f = tmp_path / "backup.age"
    f.write_bytes(b"hello")
    target = _FakeTarget()
    upload_with_integrity(target, f, "dr/backup.age", now=_FIXED_NOW)

    keys = [c[1] for c in target.upload_calls]
    assert len(keys) == 3
    assert keys[0] == "dr/backup.age"
    assert keys[1] == "dr/backup.age.sha256.txt"
    assert keys[2] == "dr/backup.age.manifest.json"


def test_upload_with_integrity_sha256_sidecar_content(tmp_path: Path) -> None:
    """sha256.txt must contain only the hex digest, no newline, no other text."""
    payload = b"deterministic-payload"
    f = tmp_path / "dump.age"
    f.write_bytes(payload)
    expected_hex = hashlib.sha256(payload).hexdigest()

    # Capture sidecar content during the upload() call (temp dir is removed after).
    captured: dict[str, str] = {}

    class _Recording:
        def upload(self_inner, local_path: Path, remote_key: str) -> None:
            if remote_key.endswith(".sha256.txt"):
                captured[remote_key] = local_path.read_text(encoding="utf-8")

        def delete(self_inner, remote_key: str) -> None:
            pass

    upload_with_integrity(_Recording(), f, "key/dump.age", now=_FIXED_NOW)

    assert captured.get("key/dump.age.sha256.txt") == expected_hex


def test_upload_with_integrity_manifest_sidecar_content(tmp_path: Path) -> None:
    """manifest.json must be valid JSON with all required fields."""
    f = tmp_path / "dump.age"
    f.write_bytes(b"data")

    # Capture manifest content during the upload() call (temp dir is removed after).
    captured: dict[str, Any] = {}

    class _Recording:
        def upload(self_inner, local_path: Path, remote_key: str) -> None:
            if remote_key.endswith(".manifest.json"):
                captured["manifest"] = json.loads(local_path.read_text("utf-8"))

        def delete(self_inner, remote_key: str) -> None:
            pass

    upload_with_integrity(
        _Recording(),
        f,
        "key/dump.age",
        encryption_key_versions=["v1"],
        producer_pod_instance_id="pod-xyz",
        now=_FIXED_NOW,
    )

    manifest = captured["manifest"]
    assert manifest["date"] == "2026-05-21"
    assert manifest["size_bytes"] == 4
    assert manifest["checksum_sha256"] == hashlib.sha256(b"data").hexdigest()
    assert manifest["encryption_key_versions"] == ["v1"]
    assert manifest["producer_pod_instance_id"] == "pod-xyz"
    assert manifest["uploaded_at_utc"] == "2026-05-21T10:00:00Z"


def test_upload_with_integrity_returns_manifest_dict(tmp_path: Path) -> None:
    f = tmp_path / "dump.age"
    f.write_bytes(b"ok")
    result = upload_with_integrity(_FakeTarget(), f, "key/dump.age", now=_FIXED_NOW)
    assert isinstance(result, dict)
    assert result["checksum_sha256"] == hashlib.sha256(b"ok").hexdigest()


# -- S3 probe: happy path -----------------------------------------------------


def test_upload_s3_probe_happy_path_large_file(tmp_path: Path) -> None:
    """Happy path: HEAD + 2 range-GETs for a file larger than 4 KiB."""
    file_data = bytes(range(256)) * 24  # 6 144 bytes (> 4 KiB)
    f = tmp_path / "dump.age"
    f.write_bytes(file_data)
    pool = _FakeS3Pool()
    pool.enqueue(
        _FakeS3Resp(status=200),  # main PUT
        _FakeS3Resp(status=200),  # sha256 PUT
        _FakeS3Resp(status=200),  # manifest PUT
        _FakeS3Resp(status=200),  # HEAD
        _FakeS3Resp(status=206, data=file_data[:_PROBE]),    # first 4 KiB GET
        _FakeS3Resp(status=206, data=file_data[-_PROBE:]),   # last 4 KiB GET
    )
    result = upload_with_integrity(_make_s3(pool), f, "dr/dump.age", now=_FIXED_NOW)

    assert isinstance(result, dict)
    methods = [c[0] for c in pool.calls]
    assert methods.count("PUT") == 3
    assert methods.count("HEAD") == 1
    assert methods.count("GET") == 2


def test_upload_s3_probe_small_file_single_range_get(tmp_path: Path) -> None:
    """Small file (< 4 KiB): only one range-GET (first == last window)."""
    file_data = b"z" * 100
    f = tmp_path / "small.age"
    f.write_bytes(file_data)
    pool = _FakeS3Pool()
    pool.enqueue(
        _FakeS3Resp(status=200),                          # main PUT
        _FakeS3Resp(status=200),                          # sha256 PUT
        _FakeS3Resp(status=200),                          # manifest PUT
        _FakeS3Resp(status=200),                          # HEAD
        _FakeS3Resp(status=200, data=file_data),          # single range-GET
    )
    upload_with_integrity(_make_s3(pool), f, "dr/small.age", now=_FIXED_NOW)
    get_calls = [c for c in pool.calls if c[0] == "GET"]
    assert len(get_calls) == 1


def test_upload_s3_probe_empty_file_head_only(tmp_path: Path) -> None:
    """Empty file: HEAD probe only, no range-GETs."""
    f = tmp_path / "empty.age"
    f.write_bytes(b"")
    pool = _FakeS3Pool()
    pool.enqueue(
        _FakeS3Resp(status=200),  # main PUT
        _FakeS3Resp(status=200),  # sha256 PUT
        _FakeS3Resp(status=200),  # manifest PUT
        _FakeS3Resp(status=200),  # HEAD
    )
    upload_with_integrity(_make_s3(pool), f, "dr/empty.age", now=_FIXED_NOW)
    get_calls = [c for c in pool.calls if c[0] == "GET"]
    assert not get_calls


# -- S3 probe: mismatch -> ObjectIntegrityError --------------------------------


def test_upload_s3_probe_first_block_mismatch_raises(tmp_path: Path) -> None:
    """Corrupted first 4 KiB on remote must raise ObjectIntegrityError."""
    file_data = b"x" * 8192
    f = tmp_path / "dump.age"
    f.write_bytes(file_data)
    pool = _FakeS3Pool()
    corrupt_first = b"corrupted" + b"\x00" * (_PROBE - 9)
    pool.enqueue(
        _FakeS3Resp(status=200),  # main PUT
        _FakeS3Resp(status=200),  # sha256 PUT
        _FakeS3Resp(status=200),  # manifest PUT
        _FakeS3Resp(status=200),  # HEAD
        _FakeS3Resp(status=206, data=corrupt_first),  # first range-GET (bad)
    )
    with pytest.raises(ObjectIntegrityError, match="first"):
        upload_with_integrity(_make_s3(pool), f, "dr/dump.age", now=_FIXED_NOW)


def test_upload_s3_probe_last_block_mismatch_raises(tmp_path: Path) -> None:
    """Corrupted last 4 KiB on remote must raise ObjectIntegrityError."""
    file_data = b"y" * 8192
    f = tmp_path / "dump.age"
    f.write_bytes(file_data)
    pool = _FakeS3Pool()
    pool.enqueue(
        _FakeS3Resp(status=200),  # main PUT
        _FakeS3Resp(status=200),  # sha256 PUT
        _FakeS3Resp(status=200),  # manifest PUT
        _FakeS3Resp(status=200),  # HEAD
        _FakeS3Resp(status=206, data=file_data[:_PROBE]),          # first OK
        _FakeS3Resp(status=206, data=b"bad" + b"\x00" * (_PROBE - 3)),  # last BAD
    )
    with pytest.raises(ObjectIntegrityError, match="last"):
        upload_with_integrity(_make_s3(pool), f, "dr/dump.age", now=_FIXED_NOW)


# -- Non-S3 targets skip the probe --------------------------------------------


def test_upload_noop_target_skips_probe(tmp_path: Path) -> None:
    """NoopTarget has no head/range_get; upload_with_integrity must not call them."""
    f = tmp_path / "dump.age"
    f.write_bytes(b"data")
    target = NoopTarget(profile="mock")
    # Should complete without AttributeError (noop has no head/range_get).
    result = upload_with_integrity(target, f, "dr/dump.age", now=_FIXED_NOW)
    assert isinstance(result, dict)


def test_upload_fake_target_skips_probe(tmp_path: Path) -> None:
    """A non-S3 target without head/range_get must not be probed."""
    f = tmp_path / "dump.age"
    f.write_bytes(b"data")
    target = _FakeTarget()
    result = upload_with_integrity(target, f, "dr/dump.age", now=_FIXED_NOW)
    assert len(target.upload_calls) == 3  # main + 2 sidecars, no extra calls


# -- S3CompatibleTarget.head() ------------------------------------------------


def test_s3_head_sends_head_request() -> None:
    pool = _FakeS3Pool()
    pool.enqueue(_FakeS3Resp(status=200, headers={"ETag": '"abc"', "Content-Length": "100"}))
    s3 = _make_s3(pool)
    hdrs = s3.head("dr/dump.age")
    assert pool.calls[0][0] == "HEAD"
    assert "bkt/dr/dump.age" in pool.calls[0][1]
    assert hdrs.get("ETag") == '"abc"'


def test_s3_head_raises_oserror_on_404() -> None:
    pool = _FakeS3Pool()
    pool.enqueue(_FakeS3Resp(status=404, data=b"NoSuchKey"))
    with pytest.raises(OSError):
        _make_s3(pool).head("dr/missing.age")


def test_s3_head_raises_oserror_on_403() -> None:
    pool = _FakeS3Pool()
    pool.enqueue(_FakeS3Resp(status=403, data=b"Forbidden"))
    with pytest.raises(OSError):
        _make_s3(pool).head("dr/locked.age")


# -- S3CompatibleTarget.range_get() -------------------------------------------


def test_s3_range_get_sends_range_header() -> None:
    pool = _FakeS3Pool()
    pool.enqueue(_FakeS3Resp(status=206, data=b"partial"))
    s3 = _make_s3(pool)
    data = s3.range_get("dr/dump.age", 0, 4095)
    assert pool.calls[0][0] == "GET"
    assert "bkt/dr/dump.age" in pool.calls[0][1]
    assert pool.headers_log[0].get("Range") == "bytes=0-4095"
    assert data == b"partial"


def test_s3_range_get_accepts_206() -> None:
    pool = _FakeS3Pool()
    pool.enqueue(_FakeS3Resp(status=206, data=b"chunk"))
    data = _make_s3(pool).range_get("dr/dump.age", 100, 199)
    assert data == b"chunk"


def test_s3_range_get_accepts_200() -> None:
    """Some S3-compatible backends return 200 instead of 206 for range requests."""
    pool = _FakeS3Pool()
    pool.enqueue(_FakeS3Resp(status=200, data=b"full"))
    data = _make_s3(pool).range_get("dr/dump.age", 0, 3)
    assert data == b"full"


def test_s3_range_get_raises_oserror_on_4xx() -> None:
    pool = _FakeS3Pool()
    pool.enqueue(_FakeS3Resp(status=403, data=b"Forbidden"))
    with pytest.raises(OSError):
        _make_s3(pool).range_get("dr/dump.age", 0, 100)
