"""Phase 8 §8.15.5 — maint_audit_log per-row size cap + per-kind details budget.

Single helper :func:`truncate_oversize` is shared between:

* **Producer-side soft fence** — ``MaintEvent.<kind>(...)`` factory caps the
  ``details`` kwarg BEFORE emit, applying the per-kind budget from
  ``cfg.maint_audit_per_kind_details_max_bytes``.
* **Trigger backstop** — the §8.14.1 ``BEFORE INSERT`` trigger (in SQL) applies
  the global ``cfg.maint_audit_row_max_bytes`` cap to the whole ``payload``
  JSONB column; Python callers can simulate the same logic via
  :func:`apply_row_cap` (used in tests and in the audit writer helper).

Sentinel format (ROADMAP §8.15.5 binding)::

    {
        "_truncated": True,
        "_original_size_bytes": <N>,
        "_kind": "<kind>",
        "_first_4kb": "<base64-of-first-4096-bytes>",
    }

The sentinel replaces the original ``details`` value (producer-side) or the
full ``payload`` JSONB (trigger backstop).  The original bytes are written to
``<oversize_dir>/<row_id>.json`` (mode 0600) so operators can investigate
out-of-band.  The sidecar write is **not** retried on failure — a failure is
logged at WARNING level but the sentinel is still returned (the audit row must
not be blocked by a filesystem issue).
"""
from __future__ import annotations

import base64
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

__all__ = [
    "SENTINEL_KEY",
    "build_sentinel",
    "is_sentinel",
    "truncate_oversize",
    "apply_row_cap",
]

logger = logging.getLogger(__name__)

# Sentinel dict key that marks a truncated payload.
SENTINEL_KEY = "_truncated"

_SIDECAR_INDENT = 2
_FIRST_4KB = 4096


def build_sentinel(
    original_bytes: bytes,
    kind: str,
    original_size: int,
) -> Dict[str, Any]:
    """Return the sentinel dict for a truncated details/payload.

    :param original_bytes: serialized JSON of the original value.
    :param kind: the ``maint.event.v1`` kind string.
    :param original_size: pre-computed byte length (avoids a second serialise).
    """
    first_chunk = original_bytes[:_FIRST_4KB]
    return {
        SENTINEL_KEY: True,
        "_original_size_bytes": original_size,
        "_kind": kind,
        "_first_4kb": base64.b64encode(first_chunk).decode("ascii"),
    }


def is_sentinel(value: Any) -> bool:
    """Return True if *value* is a sentinel dict (was truncated)."""
    return isinstance(value, dict) and value.get(SENTINEL_KEY) is True


def _write_sidecar(row_id: str, original_bytes: bytes, oversize_dir: Path) -> None:
    """Write *original_bytes* to ``<oversize_dir>/<row_id>.json`` (mode 0600).

    Uses atomic temp-file + rename to avoid partial writes.  Failure is logged
    at WARNING (not propagated — the caller must not be blocked by FS issues).
    """
    try:
        oversize_dir.mkdir(parents=True, exist_ok=True)
        target = oversize_dir / f"{row_id}.json"
        # Write to a temp file in the same directory then rename atomically.
        fd, tmp_path = tempfile.mkstemp(dir=oversize_dir, suffix=".tmp")
        try:
            os.write(fd, original_bytes)
        finally:
            os.close(fd)
        os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, target)
        os.chmod(target, 0o600)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "maint_audit: failed to write oversize sidecar for row_id=%r to %s: %s",
            row_id,
            oversize_dir,
            exc,
        )


def truncate_oversize(
    details: Dict[str, Any],
    *,
    kind: str,
    row_id: str,
    oversize_dir: Path,
    cap_bytes: int,
) -> Dict[str, Any]:
    """Cap *details* to *cap_bytes* (UTF-8 JSON bytes).

    If the serialised size of *details* exceeds *cap_bytes*:

    1. Write the original JSON to ``<oversize_dir>/<row_id>.json`` (mode 0600).
    2. Return the sentinel dict (see module docstring).

    If the size is within the cap, *details* is returned unchanged (same object).

    :param details: the kind-specific payload dict to cap.
    :param kind: the ``maint.event.v1`` kind string; embedded in the sentinel.
    :param row_id: unique identifier for the audit row; used as the sidecar
        filename so the operator can correlate the DB row with the oversize file.
    :param oversize_dir: directory to write sidecar files.
    :param cap_bytes: maximum allowed byte length of the serialized ``details``.
    :raises ValueError: if *cap_bytes* is not positive.
    """
    if cap_bytes <= 0:
        raise ValueError(f"truncate_oversize: cap_bytes must be positive, got {cap_bytes!r}")

    raw = json.dumps(details, sort_keys=True, ensure_ascii=False).encode("utf-8")
    if len(raw) <= cap_bytes:
        return details

    _write_sidecar(row_id, raw, oversize_dir)
    return build_sentinel(raw, kind=kind, original_size=len(raw))


def apply_row_cap(
    payload: Dict[str, Any],
    *,
    kind: str,
    row_id: str,
    oversize_dir: Path,
    cap_bytes: int,
    alert_fn: Optional[Any] = None,
) -> Dict[str, Any]:
    """Apply the per-row hard cap to the full *payload* dict (trigger backstop).

    This is the Python-side simulation of the §8.14.1 ``BEFORE INSERT`` trigger
    branch added in §8.15.5.  Both the trigger (SQL) and this function use the
    same sentinel format so the wire contract is consistent.

    When the payload is over-cap:
    - The original is written to ``<oversize_dir>/<row_id>.json``.
    - *alert_fn* is called with keyword arguments ``(kind=<kind>, original_size=<N>)``
      so the caller can emit a debounced ``sec.alert.v1{kind=audit_row_oversize}``.
    - The sentinel dict is returned.

    :param payload: the full maint_audit_log ``payload`` JSONB dict.
    :param kind: the ``maint.event.v1`` kind string.
    :param row_id: unique identifier for the sidecar filename.
    :param oversize_dir: directory to write sidecar files.
    :param cap_bytes: maximum allowed byte length of the serialized payload.
    :param alert_fn: optional callable(kind, original_size) for sec alert emission.
    """
    if cap_bytes <= 0:
        raise ValueError(f"apply_row_cap: cap_bytes must be positive, got {cap_bytes!r}")

    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    if len(raw) <= cap_bytes:
        return payload

    _write_sidecar(row_id, raw, oversize_dir)

    if alert_fn is not None:
        try:
            alert_fn(kind=kind, original_size=len(raw))
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "maint_audit: apply_row_cap alert_fn failed for kind=%r: %s",
                kind,
                exc,
            )

    return build_sentinel(raw, kind=kind, original_size=len(raw))
