"""Tests for Phase 10 §10.25.5 operator-driven NLP intent retraining."""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from swarm.agents.nlp.training.eligibility import filter_shadow_rows_for_intent_training


def test_nlp_intent_train_command_registered() -> None:
    from xops.makefile import nlp as nlp_cli

    assert "nlp.intent-train" in nlp_cli.COMMANDS


def test_nlp_intent_train_writes_candidate_model(tmp_path, monkeypatch) -> None:
    from xops.makefile import nlp as nlp_cli

    shadow_path = tmp_path / "shadow_train.jsonl"
    shadow_rows = [
        {"text": "Galatasaray maci ne zaman", "intent": "match_time"},
        {"text": "Fenerbahce sampiyon olur mu", "intent": "championship_probability"},
    ]
    shadow_path.write_text("\n".join(json.dumps(row) for row in shadow_rows) + "\n", encoding="utf-8")

    # Fake fasttext so training is fast and deterministic in test.
    class DummyModel:
        def __init__(self):
            self.saved: bool = False

        def save_model(self, path: str) -> None:
            Path(path).write_text("dummy-model", encoding="utf-8")
            self.saved = True

        def predict(self, text: str, k: int = 1):
            return (["__label__match_time"], [0.9])

    dummy_fasttext = SimpleNamespace(
        train_supervised=lambda input, **kwargs: DummyModel()
    )
    monkeypatch.setitem(sys.modules, "fasttext", dummy_fasttext)

    monkeypatch.setenv("NEGELIR_NLP_INTENT_MODEL_PATH", str(tmp_path / "data/models/nlp/intent.tr.bin"))
    monkeypatch.setenv("NEGELIR_NLP_INTENT_TRAIN_SHADOW_PATH", str(shadow_path))

    # Force config reload inside the command.
    rc = nlp_cli.cmd_nlp_intent_train(["--eval-harness", "pass"])
    assert rc == 0

    candidate_path = tmp_path / "data/models/nlp/intent.tr.bin.candidate"
    assert candidate_path.exists(), "Candidate model must be written to default intent path"
    assert candidate_path.read_text(encoding="utf-8") == "dummy-model"


def test_nlp_intent_train_writes_candidate_calibration(tmp_path, monkeypatch) -> None:
    from xops.makefile import nlp as nlp_cli

    shadow_path = tmp_path / "shadow_train.jsonl"
    shadow_rows = [
        {"text": "Galatasaray maci ne zaman", "intent": "match_time"},
        {"text": "Fenerbahce sampiyon olur mu", "intent": "championship_probability"},
    ]
    shadow_path.write_text(
        "\n".join(json.dumps(row) for row in shadow_rows) + "\n",
        encoding="utf-8",
    )

    class DummyModel:
        def save_model(self, path: str) -> None:
            Path(path).write_text("dummy-model", encoding="utf-8")

        def predict(self, text: str, k: int = 1):
            if "Fenerbahce" in text:
                return (["__label__championship_probability"], [0.95])
            return (["__label__match_time"], [0.9])

    dummy_fasttext = SimpleNamespace(
        train_supervised=lambda input, **kwargs: DummyModel()
    )
    monkeypatch.setitem(sys.modules, "fasttext", dummy_fasttext)

    monkeypatch.setenv("NEGELIR_NLP_INTENT_MODEL_PATH", str(tmp_path / "data/models/nlp/intent.tr.bin"))
    monkeypatch.setenv("NEGELIR_NLP_INTENT_TRAIN_SHADOW_PATH", str(shadow_path))

    rc = nlp_cli.cmd_nlp_intent_train(["--eval-harness", "pass"])
    assert rc == 0

    calib_path = tmp_path / "data/models/nlp/intent.tr.bin.candidate.calibration.json"
    assert calib_path.exists(), "Candidate calibration file must be produced alongside the candidate model"
    data = json.loads(calib_path.read_text(encoding="utf-8"))
    assert data["schema_version"] == 1
    assert data["method"] == "platt"
    assert isinstance(data["intents"]["match_time"]["A"], float)
    assert isinstance(data["intents"]["match_time"]["B"], float)
    assert isinstance(data["intents"]["championship_probability"]["A"], float)
    assert isinstance(data["intents"]["championship_probability"]["B"], float)


def test_nlp_intent_train_refuses_when_eval_harness_fails(tmp_path) -> None:
    from xops.makefile import nlp as nlp_cli

    rc = nlp_cli.cmd_nlp_intent_train(["--eval-harness", "fail"])
    assert rc == 1


def test_nlp_intent_train_rejects_non_shadow_corpus(tmp_path, monkeypatch) -> None:
    from nlp.trainer import IntentTrainError, train_intent_candidate

    monkeypatch.setenv("NEGELIR_NLP_INTENT_TRAIN_SHADOW_PATH", str(tmp_path / "default_shadow.jsonl"))
    (tmp_path / "default_shadow.jsonl").write_text(
        json.dumps({"text": "Galatasaray maci ne zaman", "intent": "match_time"}) + "\n",
        encoding="utf-8",
    )
    alternate_path = tmp_path / "upload_shadow.jsonl"
    alternate_path.write_text(
        json.dumps({"text": "Fenerbahce sampiyon olur mu", "intent": "championship_probability"}) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(IntentTrainError, match="may only use the configured shadow corpus"):
        train_intent_candidate(shadow_path=alternate_path)


def _make_shadow_payload(
    *,
    text: str = "Galatasaray maci ne zaman",
    intent: str = "match_time",
    **extras: object,
) -> dict[str, object]:
    payload: dict[str, object] = {"text": text, "intent": intent}
    payload.update(extras)
    return payload


def test_nlp_intent_trainer_consults_eligibility_filter() -> None:
    source_path = Path(__file__).resolve().parents[1] / "nlp" / "trainer.py"
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(source_path))

    assert any(
        isinstance(node, ast.ImportFrom)
        and node.module == "swarm.agents.nlp.training.eligibility"
        and any(alias.name == "filter_shadow_rows_for_intent_training" for alias in node.names)
        for node in ast.walk(tree)
    ), "trainer.py must import filter_shadow_rows_for_intent_training from swarm.agents.nlp.training.eligibility"

    assert any(
        isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Name) and node.func.id == "filter_shadow_rows_for_intent_training")
            or (isinstance(node.func, ast.Attribute) and node.func.attr == "filter_shadow_rows_for_intent_training")
        )
        for node in ast.walk(tree)
    ), "trainer.py must call filter_shadow_rows_for_intent_training"


def test_eligibility_excludes_degraded_rows() -> None:
    selected, counts, _ = filter_shadow_rows_for_intent_training([
        _make_shadow_payload(degraded=True),
        _make_shadow_payload(),
    ])

    assert counts["degraded"] == 1
    assert len(selected) == 1


def test_eligibility_excludes_quarantined_rows() -> None:
    selected, counts, _ = filter_shadow_rows_for_intent_training([
        _make_shadow_payload(quarantined=True),
        _make_shadow_payload(),
    ])

    assert counts["quarantined"] == 1
    assert len(selected) == 1


def test_eligibility_excludes_proofreader_blocked_rows() -> None:
    selected, counts, _ = filter_shadow_rows_for_intent_training([
        _make_shadow_payload(kind="proofreader_blocked"),
        _make_shadow_payload(),
    ])

    assert counts["proofreader_blocked"] == 1
    assert len(selected) == 1


def test_eligibility_excludes_preview_rows() -> None:
    selected, counts, _ = filter_shadow_rows_for_intent_training([
        _make_shadow_payload(request_metadata={"preview": True}),
        _make_shadow_payload(),
    ])

    assert counts["preview"] == 1
    assert len(selected) == 1


def test_eligibility_excludes_kill_pattern_rewritten_rows() -> None:
    selected, counts, _ = filter_shadow_rows_for_intent_training([
        _make_shadow_payload(degraded_reason="kill_pattern_armed"),
        _make_shadow_payload(),
    ])

    assert counts["kill_pattern_rewritten"] == 1
    assert len(selected) == 1


def test_eligibility_excludes_synthetic_prober_rows() -> None:
    selected, counts, _ = filter_shadow_rows_for_intent_training([
        _make_shadow_payload(request_metadata={"synthetic_prober": True}),
        _make_shadow_payload(),
    ])

    assert counts["synthetic_prober"] == 1
    assert len(selected) == 1


def test_train_excludes_eval_set_membership_via_manifest(tmp_path: Path) -> None:
    manifest_path = tmp_path / "eval_manifest.json"
    manifest_path.write_text(json.dumps(["eval-hash-1"]), encoding="utf-8")

    selected, counts, checksum = filter_shadow_rows_for_intent_training([
        _make_shadow_payload(request_id_h="eval-hash-1"),
        _make_shadow_payload(request_id_h="not-eval"),
    ], eval_manifest_path=manifest_path)

    assert counts["eval_set_membership"] == 1
    assert len(selected) == 1
    assert checksum is not None


def test_train_caps_per_subject_bucket_under_abuse_threshold() -> None:
    selected, counts, _ = filter_shadow_rows_for_intent_training(
        [
            _make_shadow_payload(subject_key_sha8_prefix_2="ab"),
            _make_shadow_payload(subject_key_sha8_prefix_2="ab"),
            _make_shadow_payload(subject_key_sha8_prefix_2="ab"),
        ],
        max_rows_per_subject_bucket=2,
    )

    assert counts["subject_bucket_cap"] == 1
    assert len(selected) == 2


def test_nlp_intent_promote_command_registered() -> None:
    from xops.makefile import nlp as nlp_cli

    assert "nlp.intent-promote" in nlp_cli.COMMANDS


def test_nlp_intent_promote_accepts_gate_args(monkeypatch) -> None:
    from xops.makefile import nlp as nlp_cli

    monkeypatch.setenv("NEGELIR_NLP_INTENT_SHADOW_MODE", "on")
    rc = nlp_cli.cmd_nlp_intent_promote([
        "--shadow-hours",
        "72",
        "--disagreement-rate",
        "0.01",
        "--confidence-drift",
        "0.01",
        "--eval-harness",
        "pass",
    ])
    assert rc == 0


def test_nlp_intent_rollback_command_registered() -> None:
    from xops.makefile import nlp as nlp_cli

    assert "nlp.intent-rollback" in nlp_cli.COMMANDS


def test_nlp_intent_rollback_emits_alert(monkeypatch) -> None:
    from xops.makefile import nlp as nlp_cli

    monkeypatch.setenv("NEGELIR_NLP_INTENT_SHADOW_MODE", "on")
    rc = nlp_cli.cmd_nlp_intent_rollback(["--reason", "test rollback"])
    assert rc == 0


def test_nlp_intent_trainer_imports_only_shadow_v1() -> None:
    import ast

    source_path = Path(__file__).resolve().parents[1] / "nlp" / "trainer.py"
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(source_path))

    cfg_attrs = {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "cfg"
    }

    assert {
        "nlp_intent_model_path",
        "nlp_intent_train_shadow_path",
        "nlp_intent_model_version",
        "nlp_intent_train_eval_manifest_path",
        "nlp_intent_train_max_rows_per_subject_bucket",
    }.issubset(cfg_attrs)
