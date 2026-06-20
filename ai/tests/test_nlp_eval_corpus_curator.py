from __future__ import annotations

import json
import datetime
from pathlib import Path

import pytest

from ai.common.security.tr_pii import detect_tr_pii_spans

from xops.nlp.eval_corpus_curator import curate_eval_corpus


def _make_shadow_row(index: int, force_drift: bool = False) -> dict[str, object]:
    return {
        "input_hash": f"hash-{index}",
        "request_id": f"req-{index}",
        "baseline_intent": "data.fixture_lookup" if force_drift else "predict.match_outcome",
        "baseline_conf": 0.98,
        "canary_intent": "predict.match_outcome",
        "canary_conf": 0.97,
        "agreement": not force_drift,
        "producer": "nlp.intent.v1",
        "emitted_at": "2026-05-01T12:00:00Z",
        "query": "Galatasaray Beşiktaş maçı ne zaman?",
        "intent_class": "data.fixture_lookup" if force_drift else "predict.match_outcome",
        "dialect_class": "standard",
        "has_dialect": False,
        "has_anaphora": False,
        "has_negation": False,
    }


def test_curator_deterministic_on_fixed_shadow_sample(tmp_path: Path) -> None:
    shadow_path = tmp_path / "shadow.jsonl"
    rows = [_make_shadow_row(i, force_drift=(i % 3 == 0)) for i in range(20)]
    with shadow_path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    output_dir_a = tmp_path / "eval_corpus_a"
    output_dir_b = tmp_path / "eval_corpus_b"
    generated_at = datetime.datetime(2026, 6, 1, 0, 0, 0, tzinfo=datetime.timezone.utc)
    first = curate_eval_corpus(shadow_path, output_dir_a, seed=42, generated_at=generated_at)
    second = curate_eval_corpus(shadow_path, output_dir_b, seed=42, generated_at=generated_at)

    assert first.read_bytes() == second.read_bytes()
    assert first.exists()
    lines = first.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) >= 2
    meta = json.loads(lines[0])
    assert meta["_meta"]["reviewer_signoffs"]
    assert meta["_meta"]["schema_version"] == 1


def test_curator_writes_versioned_quarterly_output_file(tmp_path: Path) -> None:
    shadow_path = tmp_path / "shadow.jsonl"
    rows = [
        {
            "input_hash": "hash-1",
            "request_id": "req-1",
            "baseline_intent": "data.fixture_lookup",
            "baseline_conf": 0.9,
            "canary_intent": "predict.match_outcome",
            "canary_conf": 0.6,
            "agreement": False,
            "producer": "nlp.intent.v1",
            "emitted_at": "2026-04-02T12:00:00Z",
            "query": "Test query 1",
            "intent_class": "data.fixture_lookup",
            "dialect_class": "standard",
            "has_dialect": False,
            "has_anaphora": False,
            "has_negation": False,
        }
    ]
    with shadow_path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    output_dir = tmp_path / "eval_corpus"
    generated_at = datetime.datetime(2026, 4, 2, 12, 0, 0, tzinfo=datetime.timezone.utc)
    output_file = curate_eval_corpus(shadow_path, output_dir, seed=7, generated_at=generated_at)

    assert output_file.name == "2026q2.jsonl"
    assert output_file.parent == output_dir
    lines = output_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    meta = json.loads(lines[0])
    assert meta["_meta"]["schema_version"] == 1
    assert meta["_meta"]["reviewer_signoffs"]
    assert meta["_meta"]["source_window_start"] == "2026-04-02T12:00:00Z"
    assert meta["_meta"]["source_window_end"] == "2026-04-02T12:00:00Z"

    with pytest.raises(FileExistsError):
        curate_eval_corpus(shadow_path, output_dir, seed=7, generated_at=generated_at)


def test_curator_output_passes_pii_detector(tmp_path: Path) -> None:
    shadow_path = tmp_path / "shadow.jsonl"
    rows = [
        {
            "input_hash": "pii-1",
            "request_id": "req-pii",
            "baseline_intent": "data.fixture_lookup",
            "baseline_conf": 0.9,
            "canary_intent": "predict.match_outcome",
            "canary_conf": 0.6,
            "agreement": False,
            "producer": "nlp.intent.v1",
            "emitted_at": "2026-05-02T08:00:00Z",
            "query": "+90 532 123 45 67 ile ilgili bilgi",
            "intent_class": "data.fixture_lookup",
            "dialect_class": "standard",
            "has_dialect": False,
            "has_anaphora": False,
            "has_negation": False,
        }
    ]
    with shadow_path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    output_dir = tmp_path / "eval_corpus"
    output_file = curate_eval_corpus(shadow_path, output_dir, seed=0)
    output_text = output_file.read_text(encoding="utf-8")
    assert "+90 532 123 45 67" not in output_text
    for line in output_text.strip().splitlines()[1:]:
        record = json.loads(line)
        for value in record.values():
            if isinstance(value, str):
                assert not detect_tr_pii_spans(value)


def test_curator_diff_cap_enforced(tmp_path: Path) -> None:
    shadow_path = tmp_path / "shadow.jsonl"
    rows = [
        {
            "input_hash": f"hash-{i}",
            "request_id": f"req-{i}",
            "baseline_intent": "data.fixture_lookup",
            "baseline_conf": 0.9,
            "canary_intent": "predict.match_outcome",
            "canary_conf": 0.6,
            "agreement": False,
            "producer": "nlp.intent.v1",
            "emitted_at": "2026-05-02T08:00:00Z",
            "query": f"Test query {i}",
            "intent_class": "data.fixture_lookup",
            "dialect_class": "standard",
            "has_dialect": False,
            "has_anaphora": False,
            "has_negation": False,
        }
        for i in range(3)
    ]
    with shadow_path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    output_dir = tmp_path / "eval_corpus"
    try:
        curate_eval_corpus(shadow_path, output_dir, seed=0, max_added_rows=1)
        assert False, "Expected diff-cap enforcement to raise"
    except ValueError as exc:
        assert "exceeds cap" in str(exc)
