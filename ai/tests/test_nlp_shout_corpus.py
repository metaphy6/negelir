"""Phase 10 §10.28.8 proof tests for shout detection and resolution."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from nlp.normalize import detect_all_caps
from tqu.classifier import classify

import common.telemetry as telemetry

TEST_ROOT = Path(__file__).resolve().parent


def _load_corpus() -> list[dict[str, object]]:
    path = TEST_ROOT / "fixtures" / "shout_corpus.tr.json"
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def test_shout_corpus_has_minimum_coverage() -> None:
    corpus = _load_corpus()
    assert len(corpus) >= 30, "Shout corpus must contain at least 30 entries"
    positives = [row for row in corpus if row.get("expected_shout") is True]
    assert len(positives) >= 15, "Shout corpus must contain at least 15 positive shout entries"


def test_detect_all_caps_matches_expected_flags() -> None:
    corpus = _load_corpus()
    for row in corpus:
        text = str(row["input"])
        expected = bool(row["expected_shout"])
        assert detect_all_caps(text) is expected, f"detect_all_caps failed for {row['id']}: {text!r}"


def test_clean_shout_queries_still_resolve() -> None:
    corpus = _load_corpus()
    for row in corpus:
        if not row.get("should_resolve"):
            continue
        text = str(row["input"])
        result = classify(text)
        assert result.success, f"Shout query should resolve: {text!r}"


def test_shout_counter_increments_on_shout() -> None:
    counter = getattr(telemetry, "NLP_INPUT_SHOUT_TOTAL", None)
    if counter is None:
        pytest.skip("Prometheus metrics unavailable; cannot verify shout counter")

    before = float(counter._value.get())
    sink = telemetry.TelemetrySink()
    sink.record_nlp_input_shout("subject_shout_counter", True)
    after = float(counter._value.get())
    assert after == before + 1, "nlp_input_shout_total must increment on shout input"
