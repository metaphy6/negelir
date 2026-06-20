from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from nlp.audit_rerender import _default_render

DEFAULT_REQUEST_BACKUP_DIR = Path("data") / "backup" / "qa.request.v1"
DEFAULT_PREDICT_BACKUP_DIR = Path("data") / "backup" / "predict.approved.v1"
DEFAULT_AUDIT_ROOT = Path("data") / "nlp" / "audit"
DEFAULT_AUDIT_BUNDLES_ROOT = Path("data") / "nlp" / "audit_bundles"
DEFAULT_COMPLAINT_TRACE_DIR = Path("data") / "nlp" / "complaint_traces"
DEFAULT_MAINT_EVENT_DIR = Path("data") / "maint" / "nlp_pii_recovered_for_trace"

UUID7_PATTERN = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-7[0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$"
)


class ComplaintTraceError(Exception):
    pass


class RequestIdCollision(ComplaintTraceError):
    pass


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ComplaintTraceError(f"missing required file: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ComplaintTraceError(f"invalid JSON in {path}: {exc}") from exc


def _parse_uuid7_timestamp_ms(request_id: str) -> int:
    if not UUID7_PATTERN.fullmatch(request_id):
        raise ComplaintTraceError("request_id must be a valid UUIDv7")
    canonical = request_id.replace("-", "")
    return int(canonical[:12], 16)


def _window_bounds(request_id: str, window_h: int) -> tuple[datetime, datetime]:
    if window_h <= 0:
        raise ComplaintTraceError("nlp_complaint_trace_default_window_h must be positive")
    ts_ms = _parse_uuid7_timestamp_ms(request_id)
    center = datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc)
    half = timedelta(hours=window_h)
    return center - half, center + half


def _row_timestamp(payload: dict[str, Any], path: Path) -> datetime:
    for key in ("emitted_at", "produced_at_utc", "answer_created_at"):
        value = payload.get(key)
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                continue
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)


def _find_audit_rows(request_id: str, audit_root: Path) -> list[tuple[dict[str, Any], Path]]:
    if not audit_root.exists():
        raise ComplaintTraceError(f"audit root does not exist: {audit_root}")

    rows: list[tuple[dict[str, Any], Path]] = []
    for path in sorted(audit_root.rglob(f"{request_id}.json")):
        payload = _load_json(path)
        rows.append((payload, path))
    return rows


def _pick_audit_row(
    request_id: str,
    audit_root: Path,
    strict_uniqueness: bool,
    window_h: int,
) -> tuple[dict[str, Any], Path]:
    rows = _find_audit_rows(request_id, audit_root)
    if not rows:
        raise ComplaintTraceError(
            f"audit row for request_id={request_id} not found under {audit_root}"
        )

    window_start, window_end = _window_bounds(request_id, window_h)
    valid_rows: list[tuple[dict[str, Any], Path, datetime]] = []
    for payload, path in rows:
        timestamp = _row_timestamp(payload, path)
        if window_start <= timestamp <= window_end:
            valid_rows.append((payload, path, timestamp))

    if not valid_rows:
        raise ComplaintTraceError(
            f"no audit row for request_id={request_id} was found within the {window_h}h window"
        )

    if len(valid_rows) > 1:
        if strict_uniqueness:
            raise RequestIdCollision(
                f"multiple audit rows found for request_id={request_id}; "
                "use --no-strict-uniqueness to accept the latest"
            )
        valid_rows.sort(key=lambda item: item[2])

    payload, path, _ = valid_rows[-1]
    return payload, path


def _bundle_root(bundle_sha: str, bundle_parent: Path) -> Path:
    return bundle_parent / bundle_sha


def _write_metadata(
    trace_root: Path,
    request_id: str,
    bundle_sha: str,
    audit_path: Path,
    status: str,
) -> None:
    trace_root.mkdir(parents=True, exist_ok=True)
    metadata = {
        "request_id": request_id,
        "bundle_sha": bundle_sha,
        "audit_path": str(audit_path),
        "status": status,
        "produced_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    metadata_path = trace_root / "metadata.json"
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    os.chmod(metadata_path, 0o600)


def _emit_pii_recovered_event(
    request_id: str,
    operator_id_h: str,
    reason_text_sha8: str | None,
    maint_event_dir: Path,
) -> None:
    maint_event_dir.mkdir(parents=True, exist_ok=True)
    event_path = maint_event_dir / f"{request_id}.json"
    event = {
        "kind": "nlp_pii_recovered_for_trace",
        "request_id": request_id,
        "operator_id_h": operator_id_h,
        "reason_text_sha8": reason_text_sha8,
        "produced_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    event_path.write_text(json.dumps(event, ensure_ascii=False, indent=2), encoding="utf-8")
    os.chmod(event_path, 0o600)


def complaint_trace(
    request_id: str,
    *,
    strict_uniqueness: bool = True,
    window_h: int = 24,
    request_backup_dir: Path | None = None,
    predict_backup_dir: Path | None = None,
    audit_root: Path | None = None,
    audit_bundles_root: Path | None = None,
    complaint_trace_dir: Path | None = None,
    maint_event_dir: Path | None = None,
    render_func: Any | None = None,
    confirm_pii: bool = False,
    operator_id_h: str | None = None,
    reason_text_sha8: str | None = None,
) -> int:
    request_backup_dir = request_backup_dir or DEFAULT_REQUEST_BACKUP_DIR
    predict_backup_dir = predict_backup_dir or DEFAULT_PREDICT_BACKUP_DIR
    audit_root = audit_root or DEFAULT_AUDIT_ROOT
    audit_bundles_root = audit_bundles_root or DEFAULT_AUDIT_BUNDLES_ROOT
    complaint_trace_dir = complaint_trace_dir or DEFAULT_COMPLAINT_TRACE_DIR
    maint_event_dir = maint_event_dir or DEFAULT_MAINT_EVENT_DIR
    render_func = render_func or _default_render

    if confirm_pii and not operator_id_h:
        raise ComplaintTraceError("operator_id_h is required for confirmed PII complaint traces")

    audit_row, audit_path = _pick_audit_row(request_id, audit_root, strict_uniqueness, window_h)

    bundle_sha = (
        audit_row.get("nlp_audit_bundle_sha")
        or audit_row.get("bundle_sha")
        or audit_row.get("qa_audit_bundle_sha")
    )
    if not isinstance(bundle_sha, str) or not bundle_sha:
        raise ComplaintTraceError(
            f"audit row for request_id={request_id} is missing bundle SHA"
        )

    bundle_root = _bundle_root(bundle_sha, audit_bundles_root)
    manifest = _load_json(bundle_root / "manifest.json")
    if manifest.get("bundle_sha") != bundle_sha:
        raise ComplaintTraceError(
            f"manifest bundle_sha mismatch for {bundle_root}"
        )

    request_payload = _load_json(request_backup_dir / f"{request_id}.json")
    predict_payload = _load_json(predict_backup_dir / f"{request_id}.json")

    output_text = render_func(predict_payload, request_payload)
    expected_text = audit_row.get("answer_text_redacted")
    if not isinstance(expected_text, str):
        raise ComplaintTraceError(
            f"audit row for request_id={request_id} missing answer_text_redacted"
        )

    trace_root = complaint_trace_dir / request_id
    _write_metadata(trace_root, request_id, bundle_sha, audit_path, "match" if output_text == expected_text else "drift")

    if confirm_pii:
        _emit_pii_recovered_event(request_id, operator_id_h, reason_text_sha8, maint_event_dir)

    if output_text == expected_text:
        return 0

    diff_path = trace_root / "diff.txt"
    expected_lines = expected_text.splitlines(keepends=True)
    output_lines = output_text.splitlines(keepends=True)
    diff_text = "".join(
        difflib.unified_diff(
            expected_lines,
            output_lines,
            fromfile="expected",
            tofile="rendered",
        )
    )
    diff_path.write_text(diff_text, encoding="utf-8")
    os.chmod(diff_path, 0o600)
    return 7


def main(argv: list[str] | None = None) -> int:
    from ai.common.config import cfg

    parser = argparse.ArgumentParser(prog="python -m nlp.complaint_trace")
    parser.add_argument("--request-id", required=False)
    parser.add_argument("--no-strict-uniqueness", action="store_false", dest="strict_uniqueness")
    parser.add_argument("--with-text", action="store_true")
    parser.add_argument("--confirm-pii", action="store_true")
    parser.add_argument("--operator-id-h", required=False)
    parser.add_argument("--reason-text-sha8", required=False)
    args = parser.parse_args(argv)

    request_id = args.request_id or os.getenv("REQUEST_ID")
    if not request_id:
        parser.error("--request-id is required")
    if args.with_text and not args.confirm_pii:
        parser.error("--confirm-pii is required when --with-text is set")
    if args.confirm_pii and not args.with_text:
        parser.error("--with-text is required when --confirm-pii is set")
    if args.confirm_pii and not (args.operator_id_h or os.getenv("OPERATOR_ID_H")):
        parser.error("--operator-id-h is required when --confirm-pii is set")

    operator_id_h = args.operator_id_h or os.getenv("OPERATOR_ID_H")

    try:
        return complaint_trace(
            request_id,
            strict_uniqueness=args.strict_uniqueness,
            window_h=cfg.nlp_complaint_trace_default_window_h,
            confirm_pii=args.confirm_pii,
            operator_id_h=operator_id_h,
            reason_text_sha8=args.reason_text_sha8,
        )
    except ComplaintTraceError as exc:
        print(f"❌ complaint trace failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())


