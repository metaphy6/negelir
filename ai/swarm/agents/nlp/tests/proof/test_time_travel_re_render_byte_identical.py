from __future__ import annotations

import json
import tempfile
from pathlib import Path

from nlp.audit_rerender import rerender_bundle


def test_time_travel_re_render_byte_identical() -> None:
    request_id = "qa_rerender_time_travel_test"
    bundle_sha = "deadbeef" * 8
    expected_answer = "Üzgünüm, bu soruyu yanıtlayamıyorum."
    conversation_graph = {
        "schema_version": 1,
        "conversation_id": "conv-1",
        "turn_index": 200,
        "entities": [
            {"kind": "team", "canonical_id": f"team-{i}"}
            for i in range(200)
        ],
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        request_backup_dir = Path(tmpdir) / "backup" / "qa.request.v1"
        predict_backup_dir = Path(tmpdir) / "backup" / "predict.approved.v1"
        audit_root = Path(tmpdir) / "data" / "nlp" / "audit"
        bundle_root = Path(tmpdir) / "data" / "nlp" / "audit_bundles"
        request_backup_dir.mkdir(parents=True)
        predict_backup_dir.mkdir(parents=True)
        audit_root.mkdir(parents=True)
        (bundle_root / bundle_sha).mkdir(parents=True)

        (request_backup_dir / f"{request_id}.json").write_text(
            json.dumps(
                {
                    "request_id": request_id,
                    "sanitized_text": "Galatasaray Fenerbahçe",
                    "locale": "tr",
                    "sec_verdict": "pass",
                    "nlp_pipeline_version": "10.0.0",
                    "lexicon_versions": {
                        "players": "lex-sha-2",
                        "teams": "lex-sha-1",
                    },
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (predict_backup_dir / f"{request_id}.json").write_text(
            json.dumps(
                {
                    "final": {
                        "prediction_id": "pred-1",
                        "intent": "meta.unsupported",
                        "template_name": "meta.unsupported.tr.j2",
                        "calibration_version": 1,
                        "produced_at_utc": "2026-06-01T12:00:00Z",
                        "model_versions": ["predictor-v1@1.0.0"],
                    }
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (audit_root / f"{request_id}.json").write_text(
            json.dumps(
                {
                    "qa_correlation_id": request_id,
                    "answer_text_redacted": expected_answer,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (bundle_root / bundle_sha / "manifest.json").write_text(
            json.dumps({"bundle_sha": bundle_sha}, ensure_ascii=False),
            encoding="utf-8",
        )
        (bundle_root / bundle_sha / "conversation_entity_graph.json").write_text(
            json.dumps(conversation_graph, ensure_ascii=False),
            encoding="utf-8",
        )

        def render_func(predict_payload: dict[str, object], request_payload: dict[str, object]) -> str:
            assert request_payload["conversation_entity_graph"] == conversation_graph
            assert request_payload["nlp_pipeline_version"] == "10.0.0"
            assert request_payload["lexicon_versions"] == {
                "players": "lex-sha-2",
                "teams": "lex-sha-1",
            }
            return expected_answer

        result = rerender_bundle(
            bundle_sha,
            request_id,
            request_backup_dir=request_backup_dir,
            predict_backup_dir=predict_backup_dir,
            audit_root=audit_root,
            bundle_root=bundle_root,
            render_func=render_func,
        )

        assert result == expected_answer
