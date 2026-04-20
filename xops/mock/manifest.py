"""Seed-corpus manifest schema (Phase 2.4).

Each entry pins one frozen capture from a real upstream so the mock
nginx can serve the exact bytes during dev / CI. Stdlib only.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
SEEDS_ROOT = REPO_ROOT / "infra" / "mock" / "seeds"
MANIFEST_PATH = SEEDS_ROOT / "manifest.json"

REQUIRED_KEYS = ("source", "url", "path", "captured_at", "sha256", "bytes")


class ManifestError(RuntimeError):
    pass


def load_manifest(path: Path = MANIFEST_PATH) -> Dict[str, Any]:
    if not path.exists():
        raise ManifestError(f"manifest not found: {path}")
    with path.open("r", encoding="utf-8") as fh:
        manifest = json.load(fh)
    validate(manifest)
    return manifest


def save_manifest(manifest: Dict[str, Any], path: Path = MANIFEST_PATH) -> None:
    validate(manifest)
    text = json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
    path.write_text(text, encoding="utf-8")


def validate(manifest: Dict[str, Any]) -> None:
    if manifest.get("schema") != 1:
        raise ManifestError("manifest.schema must be 1")
    entries = manifest.get("entries")
    if not isinstance(entries, list):
        raise ManifestError("manifest.entries must be a list")
    for idx, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ManifestError(f"entries[{idx}] must be an object")
        missing = [k for k in REQUIRED_KEYS if k not in entry]
        if missing:
            raise ManifestError(
                f"entries[{idx}] missing keys: {missing}"
            )


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def make_entry(
    *,
    source: str,
    url: str,
    payload_path: Path,
    captured_at: str,
    content_type: Optional[str] = None,
    status: int = 200,
    seeds_root: Optional[Path] = None,
) -> Dict[str, Any]:
    root = (seeds_root or SEEDS_ROOT).resolve()
    rel = payload_path.resolve().relative_to(root)
    return {
        "source": source,
        "url": url,
        "path": str(rel),
        "captured_at": captured_at,
        "sha256": sha256_file(payload_path),
        "bytes": payload_path.stat().st_size,
        "status": status,
        "content_type": content_type or "application/octet-stream",
    }


def verify(manifest: Optional[Dict[str, Any]] = None) -> List[str]:
    """Re-hash every entry; return list of human-readable failure messages."""
    manifest = manifest or load_manifest()
    failures: List[str] = []
    for entry in manifest["entries"]:
        path = SEEDS_ROOT / entry["path"]
        if not path.exists():
            failures.append(f"missing payload: {entry['path']}")
            continue
        actual = sha256_file(path)
        if actual != entry["sha256"]:
            failures.append(
                f"sha256 mismatch on {entry['path']}: "
                f"manifest={entry['sha256'][:12]}…, actual={actual[:12]}…"
            )
        actual_bytes = path.stat().st_size
        if actual_bytes != entry["bytes"]:
            failures.append(
                f"byte-count mismatch on {entry['path']}: "
                f"manifest={entry['bytes']}, actual={actual_bytes}"
            )
    return failures
