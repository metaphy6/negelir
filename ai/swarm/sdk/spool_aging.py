"""Phase 8 §8.13.3 — spool entry max-age pruning helpers.

Shared utility called by both the opsctl spool-flush
(``xops/opsctl/subcommands/spool_flush.py``) and the per-agent
bus circuit-breaker (``ai/swarm/agents/maint/_bus_circuit_breaker.py``)
to prune stale spool entries on every flush attempt.

Doctrine:

* Entries older than ``max_age_h`` hours (wall-clock, measured via
  the millisecond epoch prefix embedded in every spool filename) are
  deleted without republishing.
* For each pruned entry: one ``maint.event.v1{kind=spool_entry_aged_out}``
  audit notification is generated.
* For each distinct ``target`` that had at least one pruned entry: one
  ``sec.alert.v1{kind=spool_entry_aged_out, severity=warn}`` is
  generated (per-target debounce collapses multiple aged entries on the
  same target into a single alert per flush run).
* If ``max_age_h`` is 0 or negative the function is a no-op.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Sequence
from uuid import uuid4

from .types import Envelope, Message, Topic

_log = logging.getLogger("swarm.sdk.spool_aging")

MAINT_EVENT_TOPIC: Topic = Topic("maint.event.v1")
SEC_ALERT_TOPIC: Topic = Topic("sec.alert.v1")

_SPOOL_FILENAME_RE_HELP = (
    "Expected format: <16-digit-ms>-<msg_id>.envelope.json"
)


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _extract_ms_from_filename(name: str) -> int | None:
    """Return the epoch-millisecond prefix from a spool filename.

    Format: ``{ms:016d}-{msg_id}.envelope.json``
    Returns ``None`` on parse failure (caller skips the file).
    """
    try:
        prefix = name.split("-", 1)[0]
        return int(prefix)
    except (ValueError, IndexError):
        return None


@dataclass
class SpoolPruneResult:
    """Summary returned by :func:`prune_aged_spool_entries`."""

    pruned_paths: list[Path] = field(default_factory=list)
    maint_events: list[Message] = field(default_factory=list)
    sec_alerts: list[Message] = field(default_factory=list)


def prune_aged_spool_entries(
    spool_dir: Path,
    max_age_h: int,
    now_s: float,
    target: str,
    producer: str,
    spool_label: str = "agent",
    new_id: Callable[[], str] | None = None,
    clock_iso: Callable[[], str] | None = None,
) -> SpoolPruneResult:
    """Scan *spool_dir* and prune entries older than *max_age_h* hours.

    Parameters
    ----------
    spool_dir:
        Directory to scan for ``*.envelope.json`` files.
    max_age_h:
        Maximum entry age in hours. ``0`` or negative → no-op.
    now_s:
        Current time as seconds since epoch (wall-clock).
    target:
        Logical owner of this spool (e.g. ``"maint.scaler.v1"`` or
        ``"opsctl"``). Used as ``target`` in both emitted events.
    producer:
        Producer name placed on generated :class:`Envelope` objects.
    spool_label:
        ``"agent"`` or ``"opsctl"`` — placed in the ``spool`` field of
        the maint.event.v1 payload for operator-side disambiguation.
    new_id:
        UUID generator (injectable for tests).
    clock_iso:
        ISO-8601 clock (injectable for tests).

    Returns
    -------
    :class:`SpoolPruneResult` containing deleted paths and messages to
    publish (caller is responsible for publishing).
    """
    result = SpoolPruneResult()

    if max_age_h <= 0:
        return result

    _new_id = new_id or (lambda: uuid4().hex)
    _clock_iso = clock_iso or _utc_iso

    if not spool_dir.exists():
        return result

    max_age_ms = int(max_age_h) * 3600 * 1000
    now_ms = int(now_s * 1000)
    produced_at = _clock_iso()

    seen_target_alerted = False  # one sec.alert per target per call

    for path in sorted(spool_dir.glob("*.envelope.json")):
        entry_ms = _extract_ms_from_filename(path.name)
        if entry_ms is None:
            _log.debug("spool_aging: cannot parse ms from %s, skipping", path.name)
            continue

        age_ms = now_ms - entry_ms
        if age_ms <= max_age_ms:
            continue  # not yet aged out

        age_h = age_ms / 3_600_000.0

        # Load to extract request_id and entry kind from payload.
        request_id = path.stem.split("-", 1)[-1] if "-" in path.stem else path.stem
        entry_kind = "unknown"
        try:
            raw = path.read_bytes()
            data = json.loads(raw)
            payload = data.get("payload") or {}
            entry_kind = str(payload.get("kind", "unknown"))
            if "request_id" in payload:
                request_id = str(payload["request_id"])
        except Exception:  # noqa: BLE001
            pass

        # Delete the aged-out entry.
        try:
            path.unlink()
            result.pruned_paths.append(path)
            _log.info(
                "spool_aging: pruned aged entry %s (target=%s, age_h=%.1f, kind=%s)",
                path.name, target, age_h, entry_kind,
            )
        except OSError as exc:
            _log.warning("spool_aging: could not delete %s: %s", path.name, exc)
            continue

        # Emit one maint.event.v1{kind=spool_entry_aged_out} per pruned entry.
        event_payload = {
            "kind": "spool_entry_aged_out",
            "kind_schema_version": 1,
            "produced_at": produced_at,
            "target": target,
            "request_id": request_id,
            "age_h": round(age_h, 2),
            "entry_kind": entry_kind,
            "spool": spool_label,
        }
        result.maint_events.append(
            Message.new(
                topic=MAINT_EVENT_TOPIC,
                payload=event_payload,
                producer=producer,
            )
        )

        # Emit one sec.alert per target per call (debounce within flush run).
        if not seen_target_alerted:
            seen_target_alerted = True
            result.sec_alerts.append(
                Message.new(
                    topic=SEC_ALERT_TOPIC,
                    payload={
                        "kind": "spool_entry_aged_out",
                        "severity": "warn",
                        "source": producer,
                        "subject": target,
                        "ts": produced_at,
                        "note": (
                            f"spool entry aged out: target={target} "
                            f"age_h={age_h:.1f} entry_kind={entry_kind}"
                        ),
                    },
                    producer=producer,
                )
            )

    return result


# ── Retired-kind / schema-outdated quarantine ──────────────────────────────
#
# Phase 8 §8.13.3 bullet 2. When a spool entry's kind is no longer
# in KNOWN_MAINT_EVENT_KINDS (retired by a patch during the spool's
# lifetime) or its schema_version is below
# cfg.swarm_min_supported_schema_version, the envelope is NOT silently
# dropped and NOT silently retained — it is moved to
# spool_dir/.retired/ and a sidecar is written.


@dataclass
class SpoolRetiredResult:
    """Summary returned by :func:`quarantine_retired_spool_entries`."""

    retired_paths: list[Path] = field(default_factory=list)
    sidecar_paths: list[Path] = field(default_factory=list)
    sec_alerts: list[Message] = field(default_factory=list)


def quarantine_retired_spool_entries(
    spool_dir: Path,
    known_kinds: frozenset[str],
    min_schema_version: int,
    target: str,
    producer: str,
    current_version: str = "",
    spool_label: str = "agent",
    new_id: Callable[[], str] | None = None,
    clock_iso: Callable[[], str] | None = None,
) -> SpoolRetiredResult:
    """Scan *spool_dir* and quarantine entries with an unknown kind or
    schema_version below *min_schema_version*.

    Parameters
    ----------
    spool_dir:
        Directory to scan for ``*.envelope.json`` files.
    known_kinds:
        The live ``KNOWN_MAINT_EVENT_KINDS`` frozenset. Entries whose
        ``kind`` is not in this set are quarantined as
        ``reason=unknown_kind``.
    min_schema_version:
        Minimum supported envelope ``schema_version``. Entries with a
        lower value are quarantined as ``reason=schema_outdated``.
        Pass ``0`` or ``1`` to accept all current schema versions.
    target:
        Logical owner of this spool. Placed in the sec.alert payload.
    producer:
        Producer name for generated :class:`Message` objects.
    current_version:
        Swarm component version at the time of quarantine (informational
        only; placed in the ``.retired.json`` sidecar). Injectable for
        tests.
    spool_label:
        ``"agent"`` or ``"opsctl"`` — informational, not used in
        routing.
    new_id:
        UUID generator (injectable for tests).
    clock_iso:
        ISO-8601 clock (injectable for tests).

    Returns
    -------
    :class:`SpoolRetiredResult` with the retired paths, sidecar paths, and
    sec.alert messages (caller is responsible for publishing).
    """
    result = SpoolRetiredResult()

    if not spool_dir.exists():
        return result

    _new_id = new_id or (lambda: uuid4().hex)
    _clock_iso = clock_iso or _utc_iso

    retired_dir = spool_dir / ".retired"
    produced_at = _clock_iso()

    # One sec.alert per distinct (kind, reason) pair per call.
    alerted: set[tuple[str, str]] = set()

    for path in sorted(spool_dir.glob("*.envelope.json")):
        try:
            raw = path.read_bytes()
            data = json.loads(raw)
        except Exception:  # noqa: BLE001
            _log.debug("spool_aging: cannot read %s for retired-kind scan", path.name)
            continue

        payload = data.get("payload") or {}
        env = data.get("envelope") or {}
        entry_kind = str(payload.get("kind", "unknown"))
        request_id = (
            str(payload["request_id"])
            if "request_id" in payload
            else (path.stem.split("-", 1)[-1] if "-" in path.stem else path.stem)
        )
        schema_version = int(env.get("schema_version", 1))

        # Determine quarantine reason (kind check takes priority).
        reason: str | None = None
        if entry_kind not in known_kinds:
            reason = "unknown_kind"
        elif min_schema_version > 1 and schema_version < min_schema_version:
            reason = "schema_outdated"

        if reason is None:
            continue

        # ── Move envelope to .retired/ ───────────────────────────────────
        retired_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
        retired_path = retired_dir / path.name
        try:
            path.rename(retired_path)
        except OSError as exc:
            _log.warning(
                "spool_aging: could not retire %s: %s", path.name, exc
            )
            continue

        result.retired_paths.append(retired_path)
        _log.info(
            "spool_aging: quarantined retired entry %s "
            "(target=%s, kind=%s, reason=%s)",
            path.name, target, entry_kind, reason,
        )

        # ── Write <request_id>.retired.json sidecar ──────────────────────
        sidecar: dict = {
            "kind": entry_kind,
            "reason": reason,
            "retired_at_version": current_version,
            "current_version": current_version,
            "request_id": request_id,
            "quarantined_at": produced_at,
            "spool": spool_label,
        }
        if reason == "schema_outdated":
            sidecar["envelope_schema_version"] = schema_version
            sidecar["min_supported_schema_version"] = min_schema_version

        sidecar_path = retired_dir / f"{request_id}.retired.json"
        try:
            sidecar_bytes = json.dumps(
                sidecar, sort_keys=True, ensure_ascii=False
            ).encode("utf-8")
            fd = os.open(str(sidecar_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            try:
                os.write(fd, sidecar_bytes)
                os.fsync(fd)
            finally:
                os.close(fd)
            result.sidecar_paths.append(sidecar_path)
        except OSError as exc:
            _log.warning(
                "spool_aging: could not write sidecar %s: %s", sidecar_path, exc
            )

        # ── Emit sec.alert.v1{kind=spool_entry_retired_kind} ────────────
        alert_key = (entry_kind, reason)
        if alert_key not in alerted:
            alerted.add(alert_key)
            result.sec_alerts.append(
                Message.new(
                    topic=SEC_ALERT_TOPIC,
                    payload={
                        "kind": "spool_entry_retired_kind",
                        "kind_schema_version": 1,
                        "severity": "warn",
                        "source": producer,
                        "subject": target,
                        "ts": produced_at,
                        "entry_kind": entry_kind,
                        "reason": reason,
                        "note": (
                            f"spool entry quarantined: target={target} "
                            f"entry_kind={entry_kind} reason={reason}"
                        ),
                    },
                    producer=producer,
                )
            )

    return result


__all__ = [
    "SpoolPruneResult",
    "SpoolRetiredResult",
    "prune_aged_spool_entries",
    "quarantine_retired_spool_entries",
]
