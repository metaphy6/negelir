"""Phase 10 §10.27.3 — Complaint trace rebuild operator runbook tests."""

import json
import tempfile
from pathlib import Path

import pytest

from nlp.complaint_trace import (
    ComplaintTraceError,
    RequestIdCollision,
    complaint_trace,
)


REQUEST_ID = "019e830e-1a00-7abc-89ab-cdef01234567"
BUNDLE_SHA = "deadbeef" * 8


def _write_tracing_files(tmpdir: str, expected_answer: str, drift: bool = False):
    request_dir = Path(tmpdir) / "backup" / "qa.request.v1"
    predict_dir = Path(tmpdir) / "backup" / "predict.approved.v1"
    audit_root = Path(tmpdir) / "data" / "nlp" / "audit"
    bundle_root = Path(tmpdir) / "data" / "nlp" / "audit_bundles" / BUNDLE_SHA
    trace_root = Path(tmpdir) / "data" / "nlp" / "complaint_traces"
    request_dir.mkdir(parents=True)
    predict_dir.mkdir(parents=True)
    audit_root.mkdir(parents=True)
    bundle_root.mkdir(parents=True)

    (request_dir / f"{REQUEST_ID}.json").write_text(
        json.dumps({
            "request_id": REQUEST_ID,
            "sanitized_text": "Galatasaray Fenerbahçe",
            "locale": "tr",
            "sec_verdict": "pass",
            "emitted_at": "2026-06-01T12:00:00Z",
        }),
        encoding="utf-8",
    )
    (predict_dir / f"{REQUEST_ID}.json").write_text(
        json.dumps({
            "final": {
                "prediction_id": "pred-1",
                "intent": "meta.unsupported",
                "template_name": "meta.unsupported.tr.j2",
                "calibration_version": 1,
                "produced_at_utc": "2026-06-01T12:00:00Z",
                "model_versions": ["predictor-v1@1.0.0"],
            }
        }),
        encoding="utf-8",
    )
    (audit_root / f"{REQUEST_ID}.json").write_text(
        json.dumps({
            "qa_correlation_id": REQUEST_ID,
            "answer_text_redacted": expected_answer,
            "nlp_audit_bundle_sha": BUNDLE_SHA,
            "emitted_at": "2026-06-01T12:00:00Z",
        }),
        encoding="utf-8",
    )
    (bundle_root / "manifest.json").write_text(
        json.dumps({"bundle_sha": BUNDLE_SHA}), encoding="utf-8"
    )
    return request_dir, predict_dir, audit_root, trace_root


def test_complaint_trace_byte_identical_when_artifacts_pinned():
    with tempfile.TemporaryDirectory() as tmpdir:
        expected_answer = "Üzgünüm, bu soruyu yanıtlayamıyorum."
        request_dir, predict_dir, audit_root, trace_root = _write_tracing_files(
            tmpdir, expected_answer
        )

        result = complaint_trace(
            REQUEST_ID,
            request_backup_dir=request_dir,
            predict_backup_dir=predict_dir,
            audit_root=audit_root,
            audit_bundles_root=Path(tmpdir) / "data" / "nlp" / "audit_bundles",
            complaint_trace_dir=trace_root,
            render_func=lambda predict, request: expected_answer,
        )

        assert result == 0
        assert (trace_root / REQUEST_ID / "metadata.json").exists()
        assert not (trace_root / REQUEST_ID / "diff.txt").exists()


def test_complaint_trace_exit_7_on_drift():
    with tempfile.TemporaryDirectory() as tmpdir:
        expected_answer = "Üzgünüm, bu soruyu yanıtlayamıyorum."
        request_dir, predict_dir, audit_root, trace_root = _write_tracing_files(
            tmpdir, expected_answer
        )

        result = complaint_trace(
            REQUEST_ID,
            request_backup_dir=request_dir,
            predict_backup_dir=predict_dir,
            audit_root=audit_root,
            audit_bundles_root=Path(tmpdir) / "data" / "nlp" / "audit_bundles",
            complaint_trace_dir=trace_root,
            render_func=lambda predict, request: "Bu cevap farklı.",
        )

        assert result == 7
        assert (trace_root / REQUEST_ID / "diff.txt").exists()


def test_complaint_trace_collision_strict_default():
    with tempfile.TemporaryDirectory() as tmpdir:
        expected_answer = "Üzgünüm, bu soruyu yanıtlayamıyorum."
        request_dir, predict_dir, audit_root, trace_root = _write_tracing_files(
            tmpdir, expected_answer
        )
        duplicate_dir = audit_root / "duplicate"
        duplicate_dir.mkdir(parents=True)
        (duplicate_dir / f"{REQUEST_ID}.json").write_text(
            json.dumps({
                "qa_correlation_id": REQUEST_ID,
                "answer_text_redacted": expected_answer,
                "nlp_audit_bundle_sha": BUNDLE_SHA,
                "emitted_at": "2026-06-01T12:00:00Z",
            }),
            encoding="utf-8",
        )

        with pytest.raises(RequestIdCollision):
            complaint_trace(
                REQUEST_ID,
                request_backup_dir=request_dir,
                predict_backup_dir=predict_dir,
                audit_root=audit_root,
                audit_bundles_root=Path(tmpdir) / "data" / "nlp" / "audit_bundles",
                complaint_trace_dir=trace_root,
                render_func=lambda predict, request: expected_answer,
            )


def test_complaint_trace_no_raw_text_in_output_dir_default_path():
    with tempfile.TemporaryDirectory() as tmpdir:
        expected_answer = "Üzgünüm, bu soruyu yanıtlayamıyorum."
        request_dir, predict_dir, audit_root, trace_root = _write_tracing_files(
            tmpdir, expected_answer
        )
        raw_payload = {
            "request_id": REQUEST_ID,
            "raw_text": "Kullanıcı bilgisi: support@negelir.com",
            "sanitized_text": "Galatasaray Fenerbahçe",
            "locale": "tr",
            "sec_verdict": "pass",
            "emitted_at": "2026-06-01T12:00:00Z",
        }
        (request_dir / f"{REQUEST_ID}.json").write_text(
            json.dumps(raw_payload), encoding="utf-8"
        )

        result = complaint_trace(
            REQUEST_ID,
            request_backup_dir=request_dir,
            predict_backup_dir=predict_dir,
            audit_root=audit_root,
            audit_bundles_root=Path(tmpdir) / "data" / "nlp" / "audit_bundles",
            complaint_trace_dir=trace_root,
            render_func=lambda predict, request: expected_answer,
        )

        assert result == 0
        file_contents = "".join(
            path.read_text(encoding="utf-8")
            for path in (trace_root / REQUEST_ID).glob("**/*")
            if path.is_file()
        )
        assert "support@negelir.com" not in file_contents


def test_complaint_trace_with_text_requires_confirm_pii_token():
    with tempfile.TemporaryDirectory() as tmpdir:
        expected_answer = "Üzgünüm, bu soruyu yanıtlayamıyorum."
        request_dir, predict_dir, audit_root, trace_root = _write_tracing_files(
            tmpdir, expected_answer
        )

        with pytest.raises(ComplaintTraceError,
                           match="operator_id_h is required for confirmed PII complaint traces"):
            complaint_trace(
                REQUEST_ID,
                request_backup_dir=request_dir,
                predict_backup_dir=predict_dir,
                audit_root=audit_root,
                audit_bundles_root=Path(tmpdir) / "data" / "nlp" / "audit_bundles",
                complaint_trace_dir=trace_root,
                render_func=lambda predict, request: expected_answer,
                confirm_pii=True,
            )


def test_complaint_trace_with_text_emits_pii_recovered_audit_row():
    with tempfile.TemporaryDirectory() as tmpdir:
        expected_answer = "Üzgünüm, bu soruyu yanıtlayamıyorum."
        request_dir, predict_dir, audit_root, trace_root = _write_tracing_files(
            tmpdir, expected_answer
        )
        maint_dir = Path(tmpdir) / "data" / "maint" / "nlp_pii_recovered_for_trace"

        result = complaint_trace(
            REQUEST_ID,
            request_backup_dir=request_dir,
            predict_backup_dir=predict_dir,
            audit_root=audit_root,
            audit_bundles_root=Path(tmpdir) / "data" / "nlp" / "audit_bundles",
            complaint_trace_dir=trace_root,
            maint_event_dir=maint_dir,
            render_func=lambda predict, request: expected_answer,
            confirm_pii=True,
            operator_id_h="operator123",
            reason_text_sha8="deadbeef1234",
        )

        assert result == 0
        event_path = maint_dir / f"{REQUEST_ID}.json"
        assert event_path.exists()
        event = json.loads(event_path.read_text(encoding="utf-8"))
        assert event["kind"] == "nlp_pii_recovered_for_trace"
        assert event["operator_id_h"] == "operator123"
