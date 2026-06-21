"""Phase 8 §8.15.10 Fix C — restore-verify forensic capture.

When a ``pg_restore --jobs=N`` restore-verify fails the operator has
nothing to work with because the captured stderr/stdout are logged
at runtime then discarded.

This module writes a **forensic sidecar** to
``<backup_dir>/<date>.failed/verify_forensic.json`` on every failed
restore-verify, bounded to ``cfg.maint_backup_forensic_max_bytes``
(default 256 KiB).

Schema::

    {
        "verifier_kind": "local|sidecar",
        "pg_restore_exit_code": <int|null>,
        "pg_restore_stderr": "<≤64KB tail>",
        "pg_restore_stdout": "<≤64KB tail>",
        "verify_sql_results": [{"query": "...", "error": "...|null", "row_count": 0}],
        "duration_ms": <int|null>,
        "verify_pg_image": "<image>",
        "manifest_server_version_num": <int|null>,
        "file_manifest_failures": [...]
    }

**Size discipline:**
When the JSON exceeds ``max_bytes`` the largest of the text fields is
truncated (tail-first, in priority order: ``pg_restore_stderr`` →
``pg_restore_stdout`` → ``verify_sql_results`` string representations)
until the serialised result fits the budget.  The file mode is 0600.

The caller (maint.backup.v1) emits
``maint.event.v1{kind=verify_forensic_captured, target, size_bytes}``
after the file is written.

Usage::

    from xops.backup.forensic import write_forensic_sidecar, ForensicData

    data = ForensicData(
        verifier_kind="local",
        pg_restore_exit_code=1,
        pg_restore_stderr="ERROR: ...",
        pg_restore_stdout="",
        verify_sql_results=[],
        duration_ms=2300,
        verify_pg_image="postgres:16-alpine",
        manifest_server_version_num=160001,
        file_manifest_failures=[],
    )
    size = write_forensic_sidecar(failed_dir_path, data)
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, List, Optional

from common.config import cfg  # type: ignore[import]  # xops runs with ai/ on PYTHONPATH

_log = logging.getLogger("xops.backup.forensic")

# Per-field tail cap (bytes) before the overall-size budget trim loop.
_FIELD_TAIL_CAP_BYTES: int = 65_536  # 64 KiB per text field

# Priority order in which text fields are trimmed when the JSON
# exceeds the overall budget.
_TRIM_PRIORITY: list[str] = [
    "pg_restore_stderr",
    "pg_restore_stdout",
]

# Filename written inside <date>.failed/
FORENSIC_FILENAME: str = "verify_forensic.json"


@dataclass
class VerifySqlResult:
    query: str
    error: Optional[str] = None
    row_count: Optional[int] = None


@dataclass
class ForensicData:
    verifier_kind: str  # "local" | "sidecar"
    pg_restore_exit_code: Optional[int]
    pg_restore_stderr: str
    pg_restore_stdout: str
    verify_sql_results: List[VerifySqlResult] = field(default_factory=list)
    duration_ms: Optional[int] = None
    verify_pg_image: str = ""
    manifest_server_version_num: Optional[int] = None
    file_manifest_failures: List[Any] = field(default_factory=list)


def write_forensic_sidecar(
    failed_dir: str | Path,
    data: ForensicData,
) -> int:
    """Write verify_forensic.json to *failed_dir* and return file size.

    The file is written atomically (temp + rename) with mode 0600.
    Truncates the largest text field first when the JSON would exceed
    ``cfg.maint_backup_forensic_max_bytes``.

    Returns the final file size in bytes.
    """
    max_bytes = _resolve_max_bytes()
    raw = _build_payload(data)
    raw = _enforce_size_budget(raw, max_bytes)

    content = json.dumps(raw, ensure_ascii=False, indent=2).encode("utf-8")
    if max_bytes > 0 and len(content) > max_bytes:
        # Safety net: drop verify_sql_results entirely if still over budget.
        raw["verify_sql_results"] = []
        content = json.dumps(raw, ensure_ascii=False, indent=2).encode("utf-8")

    target = Path(failed_dir) / FORENSIC_FILENAME
    target.parent.mkdir(parents=True, exist_ok=True)

    tmp = target.with_suffix(".json.tmp")
    try:
        tmp.write_bytes(content)
        os.chmod(tmp, 0o600)
        tmp.rename(target)
    except Exception:
        with contextlib_suppress():
            tmp.unlink(missing_ok=True)
        raise

    _log.info(
        "verify_forensic written: %s (%d bytes, exit_code=%s)",
        target,
        len(content),
        data.pg_restore_exit_code,
    )
    return len(content)


# ── helpers ────────────────────────────────────────────────────────────


def _build_payload(data: ForensicData) -> dict[str, Any]:
    """Convert ForensicData to a JSON-serialisable dict, applying the
    per-field 64 KiB tail cap on text fields."""
    return {
        "verifier_kind": data.verifier_kind,
        "pg_restore_exit_code": data.pg_restore_exit_code,
        "pg_restore_stderr": _tail(data.pg_restore_stderr, _FIELD_TAIL_CAP_BYTES),
        "pg_restore_stdout": _tail(data.pg_restore_stdout, _FIELD_TAIL_CAP_BYTES),
        "verify_sql_results": [
            {
                "query": r.query,
                "error": r.error,
                "row_count": r.row_count,
            }
            for r in data.verify_sql_results
        ],
        "duration_ms": data.duration_ms,
        "verify_pg_image": data.verify_pg_image,
        "manifest_server_version_num": data.manifest_server_version_num,
        "file_manifest_failures": list(data.file_manifest_failures),
    }


def _enforce_size_budget(raw: dict[str, Any], max_bytes: int) -> dict[str, Any]:
    """Iteratively trim _TRIM_PRIORITY fields until json fits max_bytes.

    When max_bytes is 0 the budget is disabled (development shortcut).
    """
    if max_bytes == 0:
        return raw

    for field_name in _TRIM_PRIORITY:
        encoded = json.dumps(raw, ensure_ascii=False).encode("utf-8")
        if len(encoded) <= max_bytes:
            break
        current: str = raw.get(field_name, "")
        if not current:
            continue
        # How much do we need to shed?
        excess = len(encoded) - max_bytes
        # Trim from the END of the field (most recent output is most relevant).
        keep = max(0, len(current.encode("utf-8")) - excess - 64)
        trimmed_bytes = current.encode("utf-8")[-keep:] if keep > 0 else b""
        raw[field_name] = trimmed_bytes.decode("utf-8", errors="replace")

    return raw


def _tail(text: str, max_bytes: int) -> str:
    """Return the last *max_bytes* UTF-8 bytes of *text* as a string."""
    if not text:
        return text
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    return encoded[-max_bytes:].decode("utf-8", errors="replace")


def _resolve_max_bytes() -> int:
    """Read cfg.maint_backup_forensic_max_bytes."""
    return int(cfg.maint_backup_forensic_max_bytes)


class contextlib_suppress:
    """Minimal contextmanager that swallows all exceptions (stdlib-free)."""

    def __enter__(self) -> "contextlib_suppress":
        return self

    def __exit__(self, *args: object) -> bool:
        return True


__all__ = [
    "ForensicData",
    "FORENSIC_FILENAME",
    "VerifySqlResult",
    "write_forensic_sidecar",
]
