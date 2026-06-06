"""Phase 10 §10.19 — Test for NLP answer audit sampling.

This test covers the sampled answer audit feature:
  1. Triangle-test: config keys exist in config.py, defaults.yaml, .env.example
  2. Sampling rate: 1-in-cfg.nlp_answer_sample_inverse answers are captured
  3. Daily cap: no more than cfg.nlp_answer_sample_daily_cap captures per day
  4. I/O failure: audit errors do not block the user
  5. PII redaction: email and phone patterns are redacted before writing
"""
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from common.config import Config, cfg
from common.security.tr_pii import detect_tr_pii_spans
from swarm.agents.nlp import AUDIT_REDACTION_WHITELIST, NlpAnswerAgent, NlpIntentAgent


# ── Triangle test ──────────────────────────────────────────────────────────

def test_audit_config_keys_exist():
    """Triangle test: config keys exist in config.py, defaults.yaml, .env.example."""
    # Check Config dataclass has the fields
    assert hasattr(cfg, "nlp_answer_sample_inverse")
    assert hasattr(cfg, "nlp_answer_sample_daily_cap")
    
    # Check defaults match
    assert cfg.nlp_answer_sample_inverse == 1000
    assert cfg.nlp_answer_sample_daily_cap == 5000
    assert cfg.nlp_audit_bundle_retention_days == 2555
    assert cfg.nlp_template_git_sha == ""
    
    # Check env.example documents them
    env_example_path = Path(__file__).parents[2] / "xops" / "env" / ".env.example"
    env_text = env_example_path.read_text(encoding="utf-8")
    assert "NEGELIR_NLP_ANSWER_SAMPLE_INVERSE" in env_text
    assert "NEGELIR_NLP_ANSWER_SAMPLE_DAILY_CAP" in env_text
    assert "NEGELIR_NLP_AUDIT_BUNDLE_RETENTION_DAYS" in env_text
    assert "NEGELIR_NLP_TEMPLATE_GIT_SHA" in env_text
    assert "NEGELIR_NLP_DEFAULT_ANSWER_FORMAT" in env_text
    assert "NEGELIR_NLP_ANSWER_FORMATS" in env_text
    assert "NEGELIR_NLP_ANSWER_FORMAT_ENABLED" in env_text

    # Check defaults.yaml documents them
    defaults_path = Path(__file__).parents[1] / "common" / "defaults.yaml"
    defaults_text = defaults_path.read_text(encoding="utf-8")
    assert "answer_sample_inverse: 1000" in defaults_text
    assert "answer_sample_daily_cap: 5000" in defaults_text
    assert "audit_bundle_retention_days: 2555" in defaults_text
    assert "default_answer_format: \"plain\"" in defaults_text
    assert "answer_formats: \"plain,markdown_safe,screen_reader,whatsapp_4096,sms_160,tts_neutral\"" in defaults_text
    assert "answer_format_enabled: '{\"plain\": true, \"markdown_safe\": true, \"screen_reader\": true, \"whatsapp_4096\": false, \"sms_160\": false, \"tts_neutral\": false}'" in defaults_text
def test_audit_sampling_rate():
    """1-in-1000 sampling: mock random to verify sampling logic."""
    agent = NlpAnswerAgent()
    
    # Mock cfg to use sampling rate of 10 (for faster test)
    with mock.patch("common.config.cfg") as mock_cfg:
        mock_cfg.nlp_answer_sample_inverse = 10
        mock_cfg.nlp_answer_sample_daily_cap = 1000
        
        with tempfile.TemporaryDirectory() as tmpdir:
            # Mock os.path.join to use tmpdir
            original_join = os.path.join
            
            def mock_join(*args):
                if len(args) >= 3 and args[0] == "data" and args[1] == "nlp":
                    return original_join(tmpdir, *args[2:])
                return original_join(*args)
            
            with mock.patch("os.path.join", side_effect=mock_join):
                # Force random to return 1 (sampled)
                with mock.patch("random.randint", return_value=1):
                    agent._maybe_audit_answer(
                        "Test answer",
                        {"test": "envelope"},
                        "qa_correlation_id_1",
                    )
                
                # Force random to return 2 (not sampled)
                with mock.patch("random.randint", return_value=2):
                    agent._maybe_audit_answer(
                        "Another answer",
                        {"test": "envelope2"},
                        "qa_correlation_id_2",
                    )
                
                # Check that only the first answer row was written
                audit_files = list((Path(tmpdir) / "audit").rglob("*.json"))
                assert len(audit_files) == 1
                
                # Verify content
                with open(audit_files[0], "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                    assert data["qa_correlation_id"] == "qa_correlation_id_1"
                    assert "Test answer" in data["answer_text_redacted"]


def test_audit_records_repair_classes_list():
    """Sampled answer audit slices include the per-rule-class repair list."""
    agent = NlpAnswerAgent()

    with mock.patch("common.config.cfg") as mock_cfg:
        mock_cfg.nlp_answer_sample_inverse = 1
        mock_cfg.nlp_answer_sample_daily_cap = 1000

        with tempfile.TemporaryDirectory() as tmpdir:
            original_join = os.path.join

            def mock_join(*args):
                if len(args) >= 3 and args[0] == "data" and args[1] == "nlp":
                    return original_join(tmpdir, *args[2:])
                return original_join(*args)

            with mock.patch("os.path.join", side_effect=mock_join):
                with mock.patch("random.randint", return_value=1):
                    agent._maybe_audit_answer(
                        "Üzgünüm, yanlış anladım.",
                        {"intent": "predict.final", "request_id": "req-1"},
                        "qa_repair_test",
                        repair_classes=[
                            "ascii_restored",
                            "particle_repaired_de_da",
                            "ascii_restored",
                        ],
                    )

            audit_files = list((Path(tmpdir) / "audit").rglob("*.json"))
            assert len(audit_files) == 1

            with open(audit_files[0], "r", encoding="utf-8") as fh:
                data = json.load(fh)

            assert data["repair_classes"] == [
                "ascii_restored",
                "particle_repaired_de_da",
            ]


def test_nlp_audit_row_carries_bundle_sha() -> None:
    """Sampled NLP audit rows include a stable bundle SHA pointer."""
    agent = NlpAnswerAgent()

    with mock.patch("common.config.cfg") as mock_cfg:
        mock_cfg.nlp_answer_sample_inverse = 1
        mock_cfg.nlp_answer_sample_daily_cap = 1000
        mock_cfg.nlp_intent_model_sha256 = "intent-sha"
        mock_cfg.nlp_entity_crf_model_sha256 = "crf-sha"
        mock_cfg.nlp_template_git_sha = "template-sha"

        with tempfile.TemporaryDirectory() as tmpdir:
            original_join = os.path.join

            def mock_join(*args):
                if len(args) >= 3 and args[0] == "data" and args[1] == "nlp":
                    return original_join(tmpdir, *args[2:])
                return original_join(*args)

            with mock.patch("os.path.join", side_effect=mock_join):
                with mock.patch("random.randint", return_value=1):
                    agent._maybe_audit_answer(
                        "NLP answer text",
                        {
                            "intent": "predict.final",
                            "request_id": "req-1",
                            "calibration_version": "cal-v1",
                            "nlp_pipeline_version": "10.0.0",
                            "lexicon_versions": {
                                "players": "lex-sha-2",
                                "teams": "lex-sha-1",
                            },
                        },
                        "qa_bundle_test",
                    )

            audit_files = list((Path(tmpdir) / "audit").rglob("*.json"))
            assert len(audit_files) == 1

            with open(audit_files[0], "r", encoding="utf-8") as fh:
                data = json.load(fh)

            assert "nlp_audit_bundle_sha" in data
            assert len(data["nlp_audit_bundle_sha"]) == 64


def test_nlp_audit_bundle_includes_conversation_entity_graph_sha() -> None:
    agent = NlpAnswerAgent()

    with mock.patch("common.config.cfg") as mock_cfg:
        mock_cfg.nlp_answer_sample_inverse = 1
        mock_cfg.nlp_answer_sample_daily_cap = 1000
        mock_cfg.nlp_intent_model_sha256 = "intent-sha"
        mock_cfg.nlp_entity_crf_model_sha256 = "crf-sha"
        mock_cfg.nlp_template_git_sha = "template-sha"

        with mock.patch("swarm.agents.nlp.ConversationStore.load", return_value={
            "conversation_id": "conv-1",
            "turn_index": 1,
            "entities": [
                {
                    "kind": "team",
                    "canonical_id": "galatasaray",
                    "account_id_h": "acct-1",
                }
            ],
            "anaphora_mentions": [
                {
                    "kind": "team",
                    "canonical_id": "galatasaray",
                }
            ],
        }):
            with tempfile.TemporaryDirectory() as tmpdir:
                original_join = os.path.join

                def mock_join(*args):
                    if len(args) >= 3 and args[0] == "data" and args[1] == "nlp":
                        return original_join(tmpdir, *args[2:])
                    return original_join(*args)

                with mock.patch("os.path.join", side_effect=mock_join):
                    with mock.patch("random.randint", return_value=1):
                        agent._maybe_audit_answer(
                            "NLP answer text",
                            {
                                "intent": "predict.final",
                                "request_id": "req-1",
                                "conversation_id": "conv-1",
                                "calibration_version": "cal-v1",
                                "nlp_pipeline_version": "10.0.0",
                                "lexicon_versions": {
                                    "players": "lex-sha-2",
                                    "teams": "lex-sha-1",
                                },
                            },
                            "qa_bundle_graph_test",
                        )

                audit_file = list((Path(tmpdir) / "audit").rglob("qa_bundle_graph_test.json"))[0]
                bundle_sha = json.loads(audit_file.read_text(encoding="utf-8"))["nlp_audit_bundle_sha"]
                bundle_root = Path(tmpdir) / "audit_bundles" / bundle_sha
                manifest = json.loads((bundle_root / "manifest.json").read_text(encoding="utf-8"))
                graph = json.loads((bundle_root / "conversation_entity_graph.json").read_text(encoding="utf-8"))

                expected_graph_sha = hashlib.sha256(
                    json.dumps(graph, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
                ).hexdigest()
                assert manifest["conversation_entity_graph_sha"] == expected_graph_sha
                assert graph["conversation_id"] == "conv-1"
                assert graph["entities"][0]["canonical_id"] == "galatasaray"


def test_nlp_audit_rerender_with_conversation_context_byte_identical() -> None:
    from nlp.audit_rerender import rerender_bundle

    request_id = "qa_rerender_context_test"
    bundle_sha = "deadbeef" * 8
    expected_answer = "Üzgünüm, bu soruyu yanıtlayamıyorum."

    with tempfile.TemporaryDirectory() as tmpdir:
        backup_request_dir = Path(tmpdir) / "backup" / "qa.request.v1"
        backup_predict_dir = Path(tmpdir) / "backup" / "predict.approved.v1"
        audit_root = Path(tmpdir) / "data" / "nlp" / "audit"
        bundle_root = Path(tmpdir) / "data" / "nlp" / "audit_bundles" / bundle_sha
        maint_event_dir = Path(tmpdir) / "data" / "maint" / "nlp_audit_rerender_executed"
        backup_request_dir.mkdir(parents=True)
        backup_predict_dir.mkdir(parents=True)
        audit_root.mkdir(parents=True)
        bundle_root.mkdir(parents=True)

        (backup_request_dir / f"{request_id}.json").write_text(
            json.dumps({
                "request_id": request_id,
                "sanitized_text": "Galatasaray Fenerbahçe",
                "locale": "tr",
                "sec_verdict": "pass",
                "emitted_at": "2026-06-01T12:00:00Z",
            }),
            encoding="utf-8",
        )
        (backup_predict_dir / f"{request_id}.json").write_text(
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
        (audit_root / f"{request_id}.json").write_text(
            json.dumps({
                "qa_correlation_id": request_id,
                "answer_text_redacted": expected_answer,
            }),
            encoding="utf-8",
        )
        (bundle_root / "manifest.json").write_text(
            json.dumps({"bundle_sha": bundle_sha}), encoding="utf-8"
        )
        (bundle_root / "intent.tr.bin.sha256").write_text("intent-sha", encoding="utf-8")
        (bundle_root / "crf.tr.model.sha256").write_text("crf-sha", encoding="utf-8")
        (bundle_root / "conversation_entity_graph.json").write_text(
            json.dumps({
                "schema_version": 1,
                "conversation_id": "conv-1",
                "turn_index": 1,
                "entities": [
                    {
                        "kind": "team",
                        "canonical_id": "galatasaray",
                    }
                ],
            }),
            encoding="utf-8",
        )

        def render_func(predict_payload: dict[str, object], request_payload: dict[str, object]) -> str:
            assert request_payload.get("conversation_entity_graph") is not None
            assert request_payload["conversation_entity_graph"]["conversation_id"] == "conv-1"
            return expected_answer

        result = rerender_bundle(
            bundle_sha,
            request_id,
            request_backup_dir=backup_request_dir,
            predict_backup_dir=backup_predict_dir,
            audit_root=audit_root,
            bundle_root=bundle_root.parent,
            maint_event_dir=maint_event_dir,
            render_func=render_func,
        )

        assert result == expected_answer
        assert (Path(tmpdir) / "data" / "maint" / "nlp_audit_rerender_executed" / f"{bundle_sha}_{request_id}.json").exists()


def test_nlp_audit_erasure_drops_account_id_h_from_graph_file() -> None:
    from swarm.agents.nlp import _erase_account_id_h_from_conversation_entity_graph

    with tempfile.TemporaryDirectory() as tmpdir:
        bundle_root = Path(tmpdir) / "bundle"
        bundle_root.mkdir(parents=True)
        graph_path = bundle_root / "conversation_entity_graph.json"
        graph_path.write_text(
            json.dumps({
                "schema_version": 1,
                "conversation_id": "conv-erase",
                "entities": [
                    {
                        "kind": "team",
                        "canonical_id": "fener",
                        "account_id_h": "acct-erase",
                    }
                ],
            }),
            encoding="utf-8",
        )

        _erase_account_id_h_from_conversation_entity_graph(str(bundle_root), "acct-erase")

        graph = json.loads(graph_path.read_text(encoding="utf-8"))
        assert "account_id_h" not in graph["entities"][0]


def test_nlp_bundle_quintet_canonical_form_byte_stable() -> None:
    """The bundle SHA is stable across equivalent lexicon orderings."""
    agent = NlpAnswerAgent()

    with mock.patch("common.config.cfg") as mock_cfg:
        mock_cfg.nlp_answer_sample_inverse = 1
        mock_cfg.nlp_answer_sample_daily_cap = 1000
        mock_cfg.nlp_intent_model_sha256 = "intent-sha"
        mock_cfg.nlp_entity_crf_model_sha256 = "crf-sha"
        mock_cfg.nlp_template_git_sha = "template-sha"

        with tempfile.TemporaryDirectory() as tmpdir:
            original_join = os.path.join

            def mock_join(*args):
                if len(args) >= 3 and args[0] == "data" and args[1] == "nlp":
                    return original_join(tmpdir, *args[2:])
                return original_join(*args)

            with mock.patch("os.path.join", side_effect=mock_join):
                with mock.patch("random.randint", return_value=1):
                    agent._maybe_audit_answer(
                        "NLP answer text 1",
                        {
                            "intent": "predict.final",
                            "request_id": "req-1",
                            "calibration_version": "cal-v1",
                            "nlp_pipeline_version": "10.0.0",
                            "lexicon_versions": {
                                "teams": "lex-sha-1",
                                "players": "lex-sha-2",
                            },
                        },
                        "qa_bundle_1",
                    )
                with mock.patch("random.randint", return_value=1):
                    agent._maybe_audit_answer(
                        "NLP answer text 2",
                        {
                            "intent": "predict.final",
                            "request_id": "req-2",
                            "calibration_version": "cal-v1",
                            "nlp_pipeline_version": "10.0.0",
                            "lexicon_versions": {
                                "players": "lex-sha-2",
                                "teams": "lex-sha-1",
                            },
                        },
                        "qa_bundle_2",
                    )

            audit_files = sorted((Path(tmpdir) / "audit").rglob("*.json"))
            assert len(audit_files) == 2

            with open(audit_files[0], "r", encoding="utf-8") as fh1, open(audit_files[1], "r", encoding="utf-8") as fh2:
                data1 = json.load(fh1)
                data2 = json.load(fh2)

            assert data1["nlp_audit_bundle_sha"] == data2["nlp_audit_bundle_sha"]


def test_nlp_audit_bundle_manifest_and_metadata_files() -> None:
    """Audit bundle creation writes manifest and SHA-only metadata files."""
    agent = NlpAnswerAgent()

    with mock.patch("common.config.cfg") as mock_cfg:
        mock_cfg.nlp_answer_sample_inverse = 1
        mock_cfg.nlp_answer_sample_daily_cap = 1000
        mock_cfg.nlp_intent_model_sha256 = "intent-sha"
        mock_cfg.nlp_entity_crf_model_sha256 = "crf-sha"
        mock_cfg.nlp_template_git_sha = "template-sha"

        with tempfile.TemporaryDirectory() as tmpdir:
            original_join = os.path.join

            def mock_join(*args):
                if len(args) >= 3 and args[0] == "data" and args[1] == "nlp":
                    return original_join(tmpdir, *args[2:])
                return original_join(*args)

            with mock.patch("os.path.join", side_effect=mock_join):
                with mock.patch("random.randint", return_value=1):
                    agent._maybe_audit_answer(
                        "NLP answer text",
                        {
                            "intent": "predict.final",
                            "request_id": "req-1",
                            "calibration_version": "cal-v1",
                            "nlp_pipeline_version": "10.0.0",
                            "lexicon_versions": {
                                "teams": "lex-sha-1",
                                "players": "lex-sha-2",
                            },
                        },
                        "qa_bundle_manifest_test",
                    )

            audit_file = list((Path(tmpdir) / "audit").rglob("qa_bundle_manifest_test.json"))[0]
            bundle_sha = json.loads(audit_file.read_text(encoding="utf-8"))["nlp_audit_bundle_sha"]
            bundle_root = Path(tmpdir) / "audit_bundles" / bundle_sha
            manifest_path = bundle_root / "manifest.json"

            assert manifest_path.exists()
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            assert manifest["bundle_sha"] == bundle_sha
            assert manifest["intent_model_sha256"] == "intent-sha"
            assert manifest["crf_model_sha256"] == "crf-sha"
            assert manifest["template_git_sha"] == "template-sha"
            assert manifest["pipeline_version"] == "10.0.0"
            assert manifest["retention_class"] == "legal_hold"

            assert (bundle_root / "lexicons" / "players.tr.yaml.sha256").read_text(encoding="utf-8") == "lex-sha-2"
            assert (bundle_root / "lexicons" / "teams.tr.yaml.sha256").read_text(encoding="utf-8") == "lex-sha-1"
            assert (bundle_root / "intent.tr.bin.sha256").read_text(encoding="utf-8") == "intent-sha"
            assert (bundle_root / "crf.tr.model.sha256").read_text(encoding="utf-8") == "crf-sha"
            assert any(bundle_root.glob("templates/*.sha256"))


def test_nlp_bundle_dir_dedupes_across_requests() -> None:
    """Multiple audit rows with the same bundle SHA reuse the same bundle dir."""
    agent = NlpAnswerAgent()

    with mock.patch("common.config.cfg") as mock_cfg:
        mock_cfg.nlp_answer_sample_inverse = 1
        mock_cfg.nlp_answer_sample_daily_cap = 1000
        mock_cfg.nlp_intent_model_sha256 = "intent-sha"
        mock_cfg.nlp_entity_crf_model_sha256 = "crf-sha"
        mock_cfg.nlp_template_git_sha = "template-sha"

        with tempfile.TemporaryDirectory() as tmpdir:
            original_join = os.path.join

            def mock_join(*args):
                if len(args) >= 3 and args[0] == "data" and args[1] == "nlp":
                    return original_join(tmpdir, *args[2:])
                return original_join(*args)

            with mock.patch("os.path.join", side_effect=mock_join):
                with mock.patch("random.randint", return_value=1):
                    agent._maybe_audit_answer(
                        "NLP answer text 1",
                        {
                            "intent": "predict.final",
                            "request_id": "req-1",
                            "calibration_version": "cal-v1",
                            "nlp_pipeline_version": "10.0.0",
                            "lexicon_versions": {
                                "teams": "lex-sha-1",
                                "players": "lex-sha-2",
                            },
                        },
                        "qa_bundle_dedupe_1",
                    )
                with mock.patch("random.randint", return_value=1):
                    agent._maybe_audit_answer(
                        "NLP answer text 2",
                        {
                            "intent": "predict.final",
                            "request_id": "req-2",
                            "calibration_version": "cal-v1",
                            "nlp_pipeline_version": "10.0.0",
                            "lexicon_versions": {
                                "players": "lex-sha-2",
                                "teams": "lex-sha-1",
                            },
                        },
                        "qa_bundle_dedupe_2",
                    )

            audit_file = list((Path(tmpdir) / "audit").rglob("qa_bundle_dedupe_1.json"))[0]
            bundle_sha = json.loads(audit_file.read_text(encoding="utf-8"))["nlp_audit_bundle_sha"]
            bundle_root = Path(tmpdir) / "audit_bundles" / bundle_sha

            assert bundle_root.exists(), "Bundle directory must exist after two audit rows"
            assert (bundle_root / "manifest.json").exists()
            assert len(list(bundle_root.glob("*.json"))) == 1


def test_nlp_bundle_dir_contains_no_raw_user_text() -> None:
    """Audit bundle metadata must never contain raw user text."""
    agent = NlpAnswerAgent()

    with mock.patch("common.config.cfg") as mock_cfg:
        mock_cfg.nlp_answer_sample_inverse = 1
        mock_cfg.nlp_answer_sample_daily_cap = 1000
        mock_cfg.nlp_intent_model_sha256 = "intent-sha"
        mock_cfg.nlp_entity_crf_model_sha256 = "crf-sha"
        mock_cfg.nlp_template_git_sha = "template-sha"

        with tempfile.TemporaryDirectory() as tmpdir:
            original_join = os.path.join

            def mock_join(*args):
                if len(args) >= 3 and args[0] == "data" and args[1] == "nlp":
                    return original_join(tmpdir, *args[2:])
                return original_join(*args)

            with mock.patch("os.path.join", side_effect=mock_join):
                with mock.patch("random.randint", return_value=1):
                    agent._maybe_audit_answer(
                        "Kullanıcı bilgisi: support@negelir.com",
                        {
                            "intent": "predict.final",
                            "request_id": "req-raw-1",
                            "calibration_version": "cal-v1",
                            "nlp_pipeline_version": "10.0.0",
                            "lexicon_versions": {"teams": "lex-sha-1"},
                        },
                        "qa_bundle_no_raw_test",
                    )

            audit_file = list((Path(tmpdir) / "audit").rglob("qa_bundle_no_raw_test.json"))[0]
            bundle_sha = json.loads(audit_file.read_text(encoding="utf-8"))["nlp_audit_bundle_sha"]
            bundle_root = Path(tmpdir) / "audit_bundles" / bundle_sha
            manifest_text = bundle_root.joinpath("manifest.json").read_text(encoding="utf-8")
            assert "support@negelir.com" not in manifest_text
            for path in bundle_root.rglob("*.sha256"):
                assert "support@negelir.com" not in path.read_text(encoding="utf-8")


def test_nlp_audit_rerender_dry_run_produces_byte_identical_answer() -> None:
    """The rerender runbook reads backups and verifies the audited answer."""
    from nlp.audit_rerender import rerender_bundle

    request_id = "qa_rerender_test"
    bundle_sha = "deadbeef" * 8
    expected_answer = "Üzgünüm, bu soruyu yanıtlayamıyorum."

    with tempfile.TemporaryDirectory() as tmpdir:
        backup_request_dir = Path(tmpdir) / "backup" / "qa.request.v1"
        backup_predict_dir = Path(tmpdir) / "backup" / "predict.approved.v1"
        audit_root = Path(tmpdir) / "data" / "nlp" / "audit"
        bundle_root = Path(tmpdir) / "data" / "nlp" / "audit_bundles" / bundle_sha
        bundle_root_parent = bundle_root.parent
        maint_event_dir = Path(tmpdir) / "data" / "maint" / "nlp_audit_rerender_executed"
        backup_request_dir.mkdir(parents=True)
        backup_predict_dir.mkdir(parents=True)
        audit_root.mkdir(parents=True)
        bundle_root.mkdir(parents=True)

        (backup_request_dir / f"{request_id}.json").write_text(
            json.dumps({
                "request_id": request_id,
                "sanitized_text": "Galatasaray Fenerbahçe",
                "locale": "tr",
                "sec_verdict": "pass",
                "emitted_at": "2026-06-01T12:00:00Z",
            }),
            encoding="utf-8",
        )
        (backup_predict_dir / f"{request_id}.json").write_text(
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
        (audit_root / f"{request_id}.json").write_text(
            json.dumps({
                "qa_correlation_id": request_id,
                "answer_text_redacted": expected_answer,
            }),
            encoding="utf-8",
        )
        (bundle_root / "manifest.json").write_text(
            json.dumps({"bundle_sha": bundle_sha}), encoding="utf-8"
        )
        (bundle_root / "intent.tr.bin.sha256").write_text("intent-sha", encoding="utf-8")
        (bundle_root / "crf.tr.model.sha256").write_text("crf-sha", encoding="utf-8")

        result = rerender_bundle(
            bundle_sha,
            request_id,
            request_backup_dir=backup_request_dir,
            predict_backup_dir=backup_predict_dir,
            audit_root=audit_root,
            bundle_root=bundle_root_parent,
            maint_event_dir=maint_event_dir,
            render_func=lambda predict, request: expected_answer,
        )

        assert result == expected_answer
        assert (Path(tmpdir) / "data" / "maint" / "nlp_audit_rerender_executed" / f"{bundle_sha}_{request_id}.json").exists()


# ── Daily cap ──────────────────────────────────────────────────────────────

def test_audit_daily_cap():
    """Daily cap: no more than cfg.nlp_answer_sample_daily_cap captures per day."""
    agent = NlpAnswerAgent()
    
    with mock.patch("common.config.cfg") as mock_cfg:
        mock_cfg.nlp_answer_sample_inverse = 1  # Always sample
        mock_cfg.nlp_answer_sample_daily_cap = 3  # Cap at 3
        
        with tempfile.TemporaryDirectory() as tmpdir:
            original_join = os.path.join
            
            def mock_join(*args):
                if len(args) >= 3 and args[0] == "data" and args[1] == "nlp":
                    return original_join(tmpdir, *args[2:])
                return original_join(*args)
            
            with mock.patch("os.path.join", side_effect=mock_join):
                with mock.patch("random.randint", return_value=1):
                    # Try to write 5 answers
                    for i in range(5):
                        agent._maybe_audit_answer(
                            f"Answer {i}",
                            {"index": i},
                            f"qa_corr_{i}",
                        )
                    
                    # Only 3 audit rows should be written (cap)
                    audit_files = list((Path(tmpdir) / "audit").rglob("*.json"))
                    assert len(audit_files) == 3


def test_audit_daily_cap_resets_on_date_change():
    """Daily cap resets when the date changes."""
    agent = NlpAnswerAgent()
    
    with mock.patch("common.config.cfg") as mock_cfg:
        mock_cfg.nlp_answer_sample_inverse = 1
        mock_cfg.nlp_answer_sample_daily_cap = 2
        
        with tempfile.TemporaryDirectory() as tmpdir:
            original_join = os.path.join
            
            def mock_join(*args):
                if len(args) >= 3 and args[0] == "data" and args[1] == "nlp":
                    return original_join(tmpdir, *args[2:])
                return original_join(*args)
            
            with mock.patch("os.path.join", side_effect=mock_join):
                with mock.patch("random.randint", return_value=1):
                    # Write 2 answers on day 1
                    with mock.patch("ai.swarm.agents.nlp._dt.datetime") as mock_dt:
                        mock_dt.now.return_value.strftime.return_value = "2026-05-01"
                        mock_dt.now.return_value.isoformat.return_value = "2026-05-01T12:00:00"
                        
                        agent._maybe_audit_answer("Day 1 answer 1", {}, "qa_1")
                        agent._maybe_audit_answer("Day 1 answer 2", {}, "qa_2")
                        agent._maybe_audit_answer("Day 1 answer 3", {}, "qa_3")  # Exceeds cap
                    
                    # Write 2 more on day 2 (should succeed after reset)
                    with mock.patch("ai.swarm.agents.nlp._dt.datetime") as mock_dt:
                        mock_dt.now.return_value.strftime.return_value = "2026-05-02"
                        mock_dt.now.return_value.isoformat.return_value = "2026-05-02T12:00:00"
                        
                        agent._maybe_audit_answer("Day 2 answer 1", {}, "qa_4")
                        agent._maybe_audit_answer("Day 2 answer 2", {}, "qa_5")
                    
                    # Total: 2 from day 1 + 2 from day 2 = 4
                    audit_files = list((Path(tmpdir) / "audit").rglob("*.json"))
                    assert len(audit_files) == 4


# ── I/O failure handling ───────────────────────────────────────────────────

def test_audit_does_not_block_on_error():
    """I/O error swallowed: audit errors do not raise exceptions."""
    agent = NlpAnswerAgent()
    
    with mock.patch("common.config.cfg") as mock_cfg:
        mock_cfg.nlp_answer_sample_inverse = 1  # Always sample
        mock_cfg.nlp_answer_sample_daily_cap = 1000
        
        # Mock os.makedirs to raise an OSError
        with mock.patch("os.makedirs", side_effect=OSError("Disk full")):
            with mock.patch("random.randint", return_value=1):
                # Should not raise
                agent._maybe_audit_answer(
                    "Test answer",
                    {"test": "envelope"},
                    "qa_correlation_id",
                )


# ── PII redaction ──────────────────────────────────────────────────────────

def test_audit_redacts_email():
    """PII redaction: email patterns are redacted before writing."""
    agent = NlpAnswerAgent()
    
    with mock.patch("common.config.cfg") as mock_cfg:
        mock_cfg.nlp_answer_sample_inverse = 1
        mock_cfg.nlp_answer_sample_daily_cap = 1000
        
        with tempfile.TemporaryDirectory() as tmpdir:
            original_join = os.path.join
            
            def mock_join(*args):
                if len(args) >= 3 and args[0] == "data" and args[1] == "nlp":
                    return original_join(tmpdir, *args[2:])
                return original_join(*args)
            
            with mock.patch("os.path.join", side_effect=mock_join):
                with mock.patch("random.randint", return_value=1):
                    agent._maybe_audit_answer(
                        "Contact us at support@negelir.com for help.",
                        {"test": "envelope"},
                        "qa_email_test",
                    )
                    
                    audit_files = list((Path(tmpdir) / "audit").rglob("*.json"))
                    assert len(audit_files) == 1
                    
                    with open(audit_files[0], "r", encoding="utf-8") as fh:
                        data = json.load(fh)
                        assert "support@negelir.com" not in data["answer_text_redacted"]
                        assert "[REDACTED_EMAIL]" in data["answer_text_redacted"]


def test_audit_redacts_phone():
    """PII redaction: Turkish phone patterns are redacted before writing."""
    agent = NlpAnswerAgent()
    
    with mock.patch("common.config.cfg") as mock_cfg:
        mock_cfg.nlp_answer_sample_inverse = 1
        mock_cfg.nlp_answer_sample_daily_cap = 1000
        
        with tempfile.TemporaryDirectory() as tmpdir:
            original_join = os.path.join
            
            def mock_join(*args):
                if len(args) >= 3 and args[0] == "data" and args[1] == "nlp":
                    return original_join(tmpdir, *args[2:])
                return original_join(*args)
            
            with mock.patch("os.path.join", side_effect=mock_join):
                with mock.patch("random.randint", return_value=1):
                    agent._maybe_audit_answer(
                        "Destek hattımız: 0555 123 45 67",
                        {"test": "envelope"},
                        "qa_phone_test",
                    )
                    
                    audit_files = list((Path(tmpdir) / "audit").rglob("*.json"))
                    assert len(audit_files) == 1
                    
                    with open(audit_files[0], "r", encoding="utf-8") as fh:
                        data = json.load(fh)
                        assert "0555 123 45 67" not in data["answer_text_redacted"]
                        assert "[REDACTED:PHONE_TR" in data["answer_text_redacted"]


def test_storage_no_unredacted_tr_pii_at_rest():
    """Phase 4 boundary: persisted NLP audit rows must not contain raw TR PII."""
    agent = NlpAnswerAgent()

    with mock.patch("common.config.cfg") as mock_cfg:
        mock_cfg.nlp_answer_sample_inverse = 1
        mock_cfg.nlp_answer_sample_daily_cap = 1000

        with tempfile.TemporaryDirectory() as tmpdir:
            original_join = os.path.join

            def mock_join(*args):
                if len(args) >= 3 and args[0] == "data" and args[1] == "nlp":
                    return original_join(tmpdir, *args[2:])
                return original_join(*args)

            with mock.patch("os.path.join", side_effect=mock_join):
                with mock.patch("random.randint", return_value=1):
                    agent._maybe_audit_answer(
                        "TC kimlik: 10000000146, IBAN: TR33 0006 1005 1978 6457 8413 26, telefon: 0555 123 45 67",
                        {
                            "extra_text": "Lütfen 10000000146 kaydedin",
                            "nested": {"iban": "TR33 0006 1005 1978 6457 8413 26"},
                        },
                        "qa_tr_pii_storage_test",
                    )

                    audit_files = list((Path(tmpdir) / "audit").rglob("*.json"))
                    assert len(audit_files) == 1

                    redacted_token_re = re.compile(r"\[REDACTED:[A-Z_]+:sha8=[0-9a-f]{8}\]")

                    def _collect_strings(value):
                        if isinstance(value, str):
                            return [redacted_token_re.sub("", value)]
                        if isinstance(value, list):
                            strings: list[str] = []
                            for item in value:
                                strings.extend(_collect_strings(item))
                            return strings
                        if isinstance(value, dict):
                            strings = []
                            for item in value.values():
                                strings.extend(_collect_strings(item))
                            return strings
                        return []

                    with open(audit_files[0], "r", encoding="utf-8") as fh:
                        audit = json.load(fh)

                    strings_to_check = [redacted_token_re.sub("", audit["answer_text_redacted"])] + _collect_strings(audit["envelope"])
                    for string in strings_to_check:
                        assert detect_tr_pii_spans(string) == []


def test_nlp_audit_whitelist_is_closed_set():
    """§10.21.7 guard: sampled-audit whitelist is explicit and non-glob."""
    expected = {
        "qa_correlation_id",
        "request_id",
        "intent",
        "intent_confidence",
        "entity_count",
        "proofreader_status",
        "humanizer_used",
        "degraded",
        "degraded_reason",
        "tier_id_required",
        "model_versions",
        "calibration_version",
        "nlp_pipeline_version",
        "lexicon_versions",
        "produced_at_utc",
    }
    assert AUDIT_REDACTION_WHITELIST == expected
    assert all("*" not in key for key in AUDIT_REDACTION_WHITELIST)


def test_audit_redacts_non_whitelisted_envelope_fields_with_same_pii_set():
    """Non-whitelisted envelope fields are recursively redacted before persistence."""
    agent = NlpAnswerAgent()

    with mock.patch("common.config.cfg") as mock_cfg:
        mock_cfg.nlp_answer_sample_inverse = 1
        mock_cfg.nlp_answer_sample_daily_cap = 1000

        with tempfile.TemporaryDirectory() as tmpdir:
            original_join = os.path.join

            def mock_join(*args):
                if len(args) >= 3 and args[0] == "data" and args[1] == "nlp":
                    return original_join(tmpdir, *args[2:])
                return original_join(*args)

            envelope = {
                "intent": "predict.final",
                "request_id": "req-1",
                "entities": [{"name": "support@negelir.com", "note": "0555 123 45 67"}],
                "answer_text": "mail support@negelir.com",
                "debug": {
                    "contact": "0555 123 45 67",
                    "owner": "help@negelir.com",
                },
            }

            with mock.patch("os.path.join", side_effect=mock_join):
                with mock.patch("random.randint", return_value=1):
                    agent._maybe_audit_answer(
                        "Destek için support@negelir.com veya 0555 123 45 67",
                        envelope,
                        "qa_whitelist_test",
                    )

            audit_files = list((Path(tmpdir) / "audit").rglob("*.json"))
            assert len(audit_files) == 1
            with open(audit_files[0], "r", encoding="utf-8") as fh:
                data = json.load(fh)

            written = data["envelope"]
            assert written["intent"] == "predict.final"
            assert written["request_id"] == "req-1"
            assert "support@negelir.com" not in written["entities"][0]["name"]
            assert "0555 123 45 67" not in written["entities"][0]["note"]
            assert "[REDACTED_EMAIL]" in written["entities"][0]["name"]
            assert "[REDACTED:PHONE_TR" in written["entities"][0]["note"]
            assert "support@negelir.com" not in written["answer_text"]
            assert "help@negelir.com" not in written["debug"]["owner"]


def test_nlp_spool_audit_dir_modes_enforced_at_startup(tmp_path, monkeypatch):
    """§10.21.8 startup mode gate: refuse start on non-0600 files."""
    spool_root = tmp_path / "spool"
    audit_root = tmp_path / "data" / "nlp" / "audit"
    spool_root.mkdir(parents=True)
    audit_root.mkdir(parents=True)

    insecure = audit_root / "old.json"
    insecure.write_text("{}", encoding="utf-8")
    insecure.chmod(0o644)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cfg, "nlp_agent_spool_dir", str(spool_root), raising=False)

    with pytest.raises(RuntimeError, match="NLP startup refused"):
        NlpIntentAgent()

    insecure.chmod(0o600)
    NlpIntentAgent()

    import stat

    assert stat.S_IMODE(spool_root.stat().st_mode) == 0o700
    assert stat.S_IMODE(audit_root.stat().st_mode) == 0o700
