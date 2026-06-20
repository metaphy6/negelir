from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Iterable

import ai.common.config as _cm


def _current_cfg():
    return _cm.cfg


def _request_metadata(payload: dict[str, object]) -> dict[str, object]:
    request_metadata = payload.get("request_metadata")
    return request_metadata if isinstance(request_metadata, dict) else {}


def _subject_bucket(payload: dict[str, object]) -> str:
    prefix = payload.get("subject_key_sha8_prefix_2")
    if isinstance(prefix, str) and len(prefix) >= 2:
        return prefix[:2]
    subject_key = payload.get("subject_key_sha8")
    if isinstance(subject_key, str) and len(subject_key) >= 2:
        return subject_key[:2]
    return ""


def _is_degraded(payload: dict[str, object]) -> bool:
    return bool(payload.get("degraded"))


def _is_quarantined(payload: dict[str, object]) -> bool:
    if bool(payload.get("quarantined")):
        return True
    if bool(payload.get("quarantine")):
        return True
    if payload.get("quarantine_id"):
        return True
    metadata = _request_metadata(payload)
    if bool(metadata.get("quarantined")):
        return True
    if bool(metadata.get("quarantine")):
        return True
    if metadata.get("quarantine_id"):
        return True
    return False


def _is_proofreader_blocked(payload: dict[str, object]) -> bool:
    kind = payload.get("kind")
    return isinstance(kind, str) and kind == "proofreader_blocked"


def _is_preview(payload: dict[str, object]) -> bool:
    metadata = _request_metadata(payload)
    return bool(metadata.get("preview"))


def _is_synthetic_prober(payload: dict[str, object]) -> bool:
    metadata = _request_metadata(payload)
    return bool(metadata.get("synthetic_prober"))


def _is_kill_pattern_rewritten(payload: dict[str, object]) -> bool:
    if payload.get("kill_pattern_armed") is True:
        return True
    degraded_reason = payload.get("degraded_reason")
    return isinstance(degraded_reason, str) and degraded_reason == "kill_pattern_armed"


def _load_eval_set_membership(eval_manifest_path: Path | None) -> tuple[set[str], str | None]:
    if not eval_manifest_path:
        return set(), None
    if not eval_manifest_path.exists():
        return set(), None

    text = eval_manifest_path.read_text("utf-8").strip()
    if not text:
        return set(), hashlib.sha256(b"").hexdigest()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        ids = {line.strip() for line in text.splitlines() if line.strip()}
    else:
        if isinstance(parsed, list):
            ids = {str(item) for item in parsed if isinstance(item, str)}
        else:
            ids = set()
    checksum = hashlib.sha256("\n".join(sorted(ids)).encode("utf-8")).hexdigest()
    return ids, checksum


def filter_shadow_rows_for_intent_training(
    payloads: Iterable[dict[str, object]],
    eval_manifest_path: Path | None = None,
    max_rows_per_subject_bucket: int | None = None,
) -> tuple[list[dict[str, object]], dict[str, int], str | None]:
    eval_set, checksum = _load_eval_set_membership(eval_manifest_path)
    counts = {
        "degraded": 0,
        "quarantined": 0,
        "proofreader_blocked": 0,
        "preview": 0,
        "kill_pattern_rewritten": 0,
        "eval_set_membership": 0,
        "subject_bucket_cap": 0,
    }
    selected: list[dict[str, object]] = []
    bucket_counts: dict[str, int] = {}

    for payload in payloads:
        if not isinstance(payload, dict):
            continue

        if _is_degraded(payload):
            counts["degraded"] += 1
            continue
        if _is_quarantined(payload):
            counts["quarantined"] += 1
            continue
        if _is_proofreader_blocked(payload):
            counts["proofreader_blocked"] += 1
            continue
        if _is_preview(payload):
            counts["preview"] += 1
            continue
        if _is_kill_pattern_rewritten(payload):
            counts["kill_pattern_rewritten"] += 1
            continue
        if _is_synthetic_prober(payload):
            counts["synthetic_prober"] = counts.get("synthetic_prober", 0) + 1
            continue

        request_id_h = payload.get("request_id_h")
        if isinstance(request_id_h, str) and request_id_h in eval_set:
            counts["eval_set_membership"] += 1
            continue

        bucket = _subject_bucket(payload)
        if max_rows_per_subject_bucket is not None:
            current = bucket_counts.get(bucket, 0)
            if current >= max_rows_per_subject_bucket:
                counts["subject_bucket_cap"] += 1
                continue
            bucket_counts[bucket] = current + 1

        selected.append(payload)

    return selected, counts, checksum


def write_training_manifest(
    train_run_id: str,
    shadow_path: Path,
    selected_count: int,
    excluded_counts: dict[str, int],
    eval_set_checksum: str | None,
) -> Path:
    cfg = _current_cfg()
    manifest_dir = Path(cfg.nlp_intent_training_manifest_dir)
    manifest_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "schema_version": 1,
        "train_run_id": train_run_id,
        "created_at_utc": _utc_iso(),
        "shadow_path": str(shadow_path),
        "selected_count": selected_count,
        "excluded_counts": excluded_counts,
        "eval_set_checksum": eval_set_checksum,
    }
    manifest_path = manifest_dir / f"{train_run_id}.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest_path


def _utc_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
