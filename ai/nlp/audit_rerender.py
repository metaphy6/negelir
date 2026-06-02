from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from nlp.render import render_with_citation


DEFAULT_REQUEST_BACKUP_DIR = Path("data") / "backup" / "qa.request.v1"
DEFAULT_PREDICT_BACKUP_DIR = Path("data") / "backup" / "predict.approved.v1"
DEFAULT_AUDIT_ROOT = Path("data") / "nlp" / "audit"
DEFAULT_MAINT_EVENT_DIR = Path("data") / "maint" / "nlp_audit_rerender_executed"


class AuditRerenderError(Exception):
    pass


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise AuditRerenderError(f"missing required file: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise AuditRerenderError(f"invalid JSON in {path}: {exc}") from exc


def _find_audit_row(request_id: str, audit_root: Path) -> tuple[dict[str, Any], Path]:
    for path in sorted(audit_root.rglob(f"{request_id}.json")):
        payload = _load_json(path)
        return payload, path
    raise AuditRerenderError(
        f"audit row for request_id={request_id} not found under {audit_root}"
    )


def _default_render(predict_payload: dict[str, Any], request_payload: dict[str, Any]) -> str:
    final = predict_payload.get("final")
    if not isinstance(final, dict):
        raise AuditRerenderError("predict.approved.v1 payload missing final data")

    template_name = final.get("template_name")
    if isinstance(template_name, str) and template_name:
        pass
    else:
        intent = final.get("intent")
        if isinstance(intent, str) and intent:
            template_name = intent if intent.endswith(".j2") else f"{intent}.tr.j2"

    if not isinstance(template_name, str) or not template_name:
        raise AuditRerenderError(
            "cannot infer template name from predict.approved.v1 payload"
        )

    context = dict(final)
    if "citation_block" not in context and "prediction_id" in context:
        # render_with_citation synthesizes the citation block when absent.
        pass

    return render_with_citation(template_name, context)[0]


def rerender_bundle(
    bundle_sha: str,
    request_id: str,
    *,
    request_backup_dir: Path | None = None,
    predict_backup_dir: Path | None = None,
    audit_root: Path | None = None,
    bundle_root: Path | None = None,
    maint_event_dir: Path | None = None,
    render_func: Any | None = None,
) -> str:
    request_backup_dir = request_backup_dir or DEFAULT_REQUEST_BACKUP_DIR
    predict_backup_dir = predict_backup_dir or DEFAULT_PREDICT_BACKUP_DIR
    audit_root = audit_root or DEFAULT_AUDIT_ROOT
    bundle_root = bundle_root or (Path("data") / "nlp" / "audit_bundles")
    maint_event_dir = maint_event_dir or DEFAULT_MAINT_EVENT_DIR
    render_func = render_func or _default_render

    bundle_manifest = _load_json(bundle_root / bundle_sha / "manifest.json")
    request_payload = _load_json(request_backup_dir / f"{request_id}.json")
    predict_payload = _load_json(predict_backup_dir / f"{request_id}.json")
    audit_row, audit_path = _find_audit_row(request_id, audit_root)

    rendered = render_func(predict_payload, request_payload)
    expected = audit_row.get("answer_text_redacted")
    if expected is None:
        raise AuditRerenderError(
            f"audit row {audit_path} missing answer_text_redacted"
        )
    if rendered != expected:
        raise AuditRerenderError(
            "rerender output does not match audited answer_text_redacted"
        )

    maint_event_dir.mkdir(parents=True, exist_ok=True)
    event_path = maint_event_dir / f"{bundle_sha}_{request_id}.json"
    event = {
        "kind": "nlp_audit_rerender_executed",
        "produced_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "request_id": request_id,
        "bundle_sha": bundle_sha,
        "audit_path": str(audit_path),
    }
    event_path.write_text(json.dumps(event, ensure_ascii=False, indent=2), encoding="utf-8")
    os.chmod(event_path, 0o600)
    return rendered


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m nlp.audit_rerender",
        description="Re-render an NLP audit bundle and assert byte-stable reproduceability.",
    )
    parser.add_argument("--bundle", required=False)
    parser.add_argument("--request-id", required=False)
    args = parser.parse_args(argv)

    bundle_sha = args.bundle or os.getenv("BUNDLE")
    request_id = args.request_id or os.getenv("REQUEST_ID")
    if not bundle_sha or not request_id:
        parser.error("--bundle and --request-id are required")

    try:
        rerender_bundle(bundle_sha, request_id)
        print("✅ nlp.audit-rerender: re-render succeeded")
        return 0
    except AuditRerenderError as exc:
        print(f"❌ nlp.audit-rerender failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
