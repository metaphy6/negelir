"""Tests for ``xops.mock.manifest`` (Phase 2 seed-corpus integrity)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from xops.mock import manifest as m  # noqa: E402


def test_default_manifest_loads() -> None:
    data = m.load_manifest()
    assert data["schema"] == 1
    assert isinstance(data["entries"], list)


def test_validate_rejects_bad_schema() -> None:
    with pytest.raises(m.ManifestError):
        m.validate({"schema": 2, "entries": []})


def test_validate_rejects_missing_keys() -> None:
    with pytest.raises(m.ManifestError):
        m.validate({"schema": 1, "entries": [{"source": "x"}]})


def test_make_entry_round_trip(tmp_path: Path, monkeypatch) -> None:
    seeds_root = tmp_path / "seeds"
    seeds_root.mkdir()
    payload = seeds_root / "mackolik" / "fixtures.json"
    payload.parent.mkdir()
    payload.write_bytes(b'{"hello":"world"}')

    monkeypatch.setattr(m, "SEEDS_ROOT", seeds_root)

    entry = m.make_entry(
        source="mackolik.local",
        url="https://mackolik.local/fixtures",
        payload_path=payload,
        captured_at="2026-04-20T00:00:00+00:00",
        content_type="application/json",
    )
    assert entry["path"] == "mackolik/fixtures.json"
    assert entry["bytes"] == len(b'{"hello":"world"}')
    assert len(entry["sha256"]) == 64
    assert entry["status"] == 200


def test_verify_detects_drift(tmp_path: Path, monkeypatch) -> None:
    seeds_root = tmp_path / "seeds"
    seeds_root.mkdir()
    payload = seeds_root / "x.bin"
    payload.write_bytes(b"original")

    monkeypatch.setattr(m, "SEEDS_ROOT", seeds_root)

    entry = m.make_entry(
        source="src",
        url="https://example/x",
        payload_path=payload,
        captured_at="2026-04-20T00:00:00+00:00",
    )
    manifest = {"schema": 1, "captured_at": None, "entries": [entry]}
    assert m.verify(manifest) == []

    payload.write_bytes(b"tampered!")
    failures = m.verify(manifest)
    assert any("sha256 mismatch" in f for f in failures)


def test_verify_detects_missing_payload(tmp_path: Path, monkeypatch) -> None:
    seeds_root = tmp_path / "seeds"
    seeds_root.mkdir()
    payload = seeds_root / "y.bin"
    payload.write_bytes(b"data")

    monkeypatch.setattr(m, "SEEDS_ROOT", seeds_root)
    entry = m.make_entry(
        source="src",
        url="https://example/y",
        payload_path=payload,
        captured_at="2026-04-20T00:00:00+00:00",
    )
    payload.unlink()
    failures = m.verify({"schema": 1, "captured_at": None, "entries": [entry]})
    assert any("missing payload" in f for f in failures)
