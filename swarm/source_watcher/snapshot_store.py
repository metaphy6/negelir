"""Append-only snapshot store for source_watcher.

Each snapshot is a JSON file under ``infra/mock/seeds/history/<source>/``
with an ISO-8601 UTC timestamp filename. Lookups are by (source, prior-N).
Pure file I/O — no concurrency assumptions beyond "one writer at a time".
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[3]
HISTORY_ROOT = REPO_ROOT / "infra" / "mock" / "seeds" / "history"

_TS_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})T(\d{2})-(\d{2})-(\d{2})Z\.json$")


@dataclass(frozen=True)
class Snapshot:
    source: str
    captured_at: str       # ISO-8601 UTC
    sha256: str
    payload: Any
    path: Path


def _utc_now_filename() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ") + ".json"


def _sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def store(
    source: str,
    payload: Any,
    *,
    root: Path = HISTORY_ROOT,
    now: Optional[str] = None,
) -> Snapshot:
    """Append a new snapshot for ``source``. No-op if last snapshot is byte-identical."""
    sub = root / source
    sub.mkdir(parents=True, exist_ok=True)
    body = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    digest = _sha256_bytes(body)

    last = latest(source, root=root)
    if last is not None and last.sha256 == digest:
        return last  # idempotent: identical bytes means no new file

    fname = (now + ".json") if now else _utc_now_filename()
    path = sub / fname
    # Avoid overwriting an existing snapshot in the same second.
    if path.exists():
        path = sub / fname.replace(".json", f"-{digest[:6]}.json")
    path.write_bytes(body)
    return Snapshot(
        source=source,
        captured_at=fname.removesuffix(".json").replace("-", ":", 5).replace("Z", "+00:00"),
        sha256=digest,
        payload=payload,
        path=path,
    )


def list_snapshots(source: str, *, root: Path = HISTORY_ROOT) -> List[Path]:
    sub = root / source
    if not sub.exists():
        return []
    return sorted(p for p in sub.iterdir() if _TS_RE.match(p.name))


def latest(source: str, *, root: Path = HISTORY_ROOT) -> Optional[Snapshot]:
    snaps = list_snapshots(source, root=root)
    if not snaps:
        return None
    return _load(snaps[-1], source)


def previous(source: str, *, root: Path = HISTORY_ROOT) -> Optional[Snapshot]:
    snaps = list_snapshots(source, root=root)
    if len(snaps) < 2:
        return None
    return _load(snaps[-2], source)


def _load(path: Path, source: str) -> Snapshot:
    body = path.read_bytes()
    payload = json.loads(body.decode("utf-8"))
    # Re-canonicalize so digests compare cleanly with newly-stored snapshots.
    canon = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return Snapshot(
        source=source,
        captured_at=path.name.removesuffix(".json"),
        sha256=_sha256_bytes(canon),
        payload=payload,
        path=path,
    )


def prune(source: str, *, keep: int = 30, root: Path = HISTORY_ROOT) -> List[Path]:
    """Delete the oldest snapshots beyond ``keep``. Returns deleted paths."""
    snaps = list_snapshots(source, root=root)
    if len(snaps) <= keep:
        return []
    to_delete = snaps[:-keep]
    for p in to_delete:
        p.unlink()
    return to_delete
