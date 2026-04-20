"""Phase 2.5 property test: every manifest entry is a contract.

For every capture listed in ``infra/mock/seeds/manifest.json`` we assert:
  • payload file exists on disk at the declared path
  • sha256 matches the current file bytes
  • byte count matches
  • declared content_type has a matching file extension

This is the "property test parametrized over manifest.json" called out
in ROADMAP §2.5. It is the mirror of ``xops/mock/verify.py`` but with
per-entry pytest nodes so CI reports pinpoint which seed drifted.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Dict, List

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SEEDS_ROOT = REPO_ROOT / "infra" / "mock" / "seeds"
MANIFEST_PATH = SEEDS_ROOT / "manifest.json"


def _load_entries() -> List[Dict]:
    if not MANIFEST_PATH.exists():
        return []
    with MANIFEST_PATH.open("r", encoding="utf-8") as fh:
        return json.load(fh).get("entries", [])


_ENTRIES = _load_entries()
_IDS = [f"{e['source']}:{e['path']}" for e in _ENTRIES] if _ENTRIES else []


@pytest.mark.skipif(not _ENTRIES, reason="no seeds captured yet (run `make mock.capture`)")
@pytest.mark.parametrize("entry", _ENTRIES, ids=_IDS)
def test_seed_hash_matches_manifest(entry: Dict) -> None:
    payload = SEEDS_ROOT / entry["path"]
    assert payload.exists(), f"seed file missing: {payload}"

    actual_bytes = payload.stat().st_size
    assert actual_bytes == entry["bytes"], (
        f"size drift for {entry['path']}: manifest={entry['bytes']}, disk={actual_bytes}"
    )

    h = hashlib.sha256()
    with payload.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    assert h.hexdigest() == entry["sha256"], (
        f"sha256 drift for {entry['path']}: manifest={entry['sha256']}, "
        f"disk={h.hexdigest()}"
    )


@pytest.mark.skipif(not _ENTRIES, reason="no seeds captured yet")
@pytest.mark.parametrize("entry", _ENTRIES, ids=_IDS)
def test_seed_extension_matches_content_type(entry: Dict) -> None:
    ct = entry["content_type"].split(";", 1)[0].strip().lower()
    ext = Path(entry["path"]).suffix.lower()
    allowed = {
        "application/json": {".json"},
        "text/html": {".html"},
        "text/plain": {".txt"},
        "application/xml": {".xml"},
    }
    valid_exts = allowed.get(ct)
    if valid_exts is None:
        pytest.skip(f"no extension rule for content_type {ct!r}")
    assert ext in valid_exts, (
        f"{entry['path']} has extension {ext!r} but content_type is {ct!r}"
    )


@pytest.mark.skipif(not _ENTRIES, reason="no seeds captured yet")
def test_manifest_has_no_duplicate_source_paths() -> None:
    """Each (source, path) pair must be unique — mocksrv routes on it."""
    keys = [(e["source"], e["path"]) for e in _ENTRIES]
    assert len(keys) == len(set(keys)), f"duplicate keys in manifest: {keys}"


@pytest.mark.skipif(not _ENTRIES, reason="no seeds captured yet")
def test_every_registered_source_has_at_least_one_seed() -> None:
    """The source registry and the manifest must agree on coverage."""
    from xops.mock.sources import SOURCES

    sources_in_manifest = {e["source"] for e in _ENTRIES}
    expected = {s.mock_host for s in SOURCES}
    missing = expected - sources_in_manifest
    assert not missing, (
        f"registered sources without seeds: {missing}; run `make mock.capture`"
    )
