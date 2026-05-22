"""Phase 8 §8.13.4 — dump-time migration-state capture.

Scans ``migrations/*.sql`` filename inventory and reads
``xops/versioning/build_metadata.json`` for repo commit SHA.

Doctrine respected:

* Rule 1 — Single-source config: no new tunables; paths resolved
  relative to module location; callers can inject overrides for tests.
* Rule 3 — No fabricated production data: returns None for SHA when
  the file is absent; never falls back to a fake value.
* Rule 6 — English infra.
"""
from __future__ import annotations

import json
import logging
import re
import threading
from pathlib import Path
from typing import Optional

_log = logging.getLogger("xops.backup.migration_state")

# xops/backup/migration_state.py → xops/backup/ → xops/ → repo root
_MODULE_DIR: Path = Path(__file__).parent
_REPO_ROOT: Path = _MODULE_DIR.parent.parent

# sec.alert.v1 kind emitted when build_metadata.json is absent at boot.
SEC_ALERT_BACKUP_COMMIT_SHA_UNAVAILABLE: str = "backup_commit_sha_unavailable"

# Module-level sentinel — guards the once-per-process-lifetime boot alert.
# Thread-safe via _ALERT_LOCK.  Starts False; flipped to True the first
# time consume_commit_sha_unavailable_alert() returns True.
_ALERT_LOCK: threading.Lock = threading.Lock()
_COMMIT_SHA_ALERT_EMITTED: bool = False

_MIGRATION_RE: re.Pattern = re.compile(r"^(\d+)_.+\.sql$", re.IGNORECASE)


def scan_in_tree_migrations(
    migrations_dir: Optional[Path] = None,
) -> dict:
    """Return ``{max_version: int, applied_versions: list[int]}`` by
    scanning ``NNN_<description>.sql`` filenames under *migrations_dir*.

    Purely filename-based — no live database query.  Files that do not
    match the naming convention are silently skipped.  Returns
    ``max_version=0`` when the directory is absent or contains no
    migration files.

    Parameters
    ----------
    migrations_dir:
        Override the scan root.  Defaults to ``<repo_root>/migrations/``.
    """
    root = migrations_dir if migrations_dir is not None else (_REPO_ROOT / "migrations")
    versions: list[int] = []
    if root.is_dir():
        for entry in root.iterdir():
            m = _MIGRATION_RE.match(entry.name)
            if m:
                versions.append(int(m.group(1)))
    versions.sort()
    return {
        "max_version": versions[-1] if versions else 0,
        "applied_versions": versions,
    }


def read_repo_commit_sha(
    build_metadata_path: Optional[Path] = None,
) -> Optional[str]:
    """Return the ``repo_commit_sha`` from ``build_metadata.json``.

    Returns ``None`` when the file does not exist, is not valid JSON, or
    the ``repo_commit_sha`` key is missing / falsy.  Never raises.

    Parameters
    ----------
    build_metadata_path:
        Override the default path.  Defaults to
        ``<repo_root>/xops/versioning/build_metadata.json``.
    """
    path = (
        build_metadata_path
        if build_metadata_path is not None
        else (_REPO_ROOT / "xops" / "versioning" / "build_metadata.json")
    )
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
        sha = data.get("repo_commit_sha") or None
        return str(sha) if sha else None
    except (FileNotFoundError, OSError):
        _log.debug(
            "build_metadata.json not found at %s (expected outside built image)",
            path,
        )
        return None
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        _log.debug("build_metadata.json parse error at %s: %s", path, exc)
        return None


def build_migrations_at_dump_time(
    migrations_dir: Optional[Path] = None,
    build_metadata_path: Optional[Path] = None,
) -> dict:
    """Assemble the ``migrations_at_dump_time`` manifest field.

    Returns a dict with shape::

        {
            "max_version": int,
            "applied_versions": [int, ...],
            "repo_commit_sha": str | null,
        }

    Suitable for direct JSON serialisation inside ``negelir.manifest.json``.
    """
    mig = scan_in_tree_migrations(migrations_dir=migrations_dir)
    sha = read_repo_commit_sha(build_metadata_path=build_metadata_path)
    return {
        "max_version": mig["max_version"],
        "applied_versions": mig["applied_versions"],
        "repo_commit_sha": sha,
    }


def consume_commit_sha_unavailable_alert(
    build_metadata_path: Optional[Path] = None,
) -> bool:
    """Return ``True`` exactly once per process lifetime when
    ``build_metadata.json`` is absent (repo_commit_sha unavailable).

    The module-level ``_COMMIT_SHA_ALERT_EMITTED`` sentinel ensures the
    backup agent emits
    ``sec.alert.v1{kind=backup_commit_sha_unavailable, severity=info}``
    at most once per process, never per-dump.

    Returns ``False`` when:

    * the SHA is available (file present and non-empty); or
    * the sentinel is already set (alert was emitted in a prior
      agent-instance construction within the same process).
    """
    global _COMMIT_SHA_ALERT_EMITTED  # noqa: PLW0603
    with _ALERT_LOCK:
        if _COMMIT_SHA_ALERT_EMITTED:
            return False
        sha = read_repo_commit_sha(build_metadata_path=build_metadata_path)
        if sha is None:
            _COMMIT_SHA_ALERT_EMITTED = True
            return True
        return False
