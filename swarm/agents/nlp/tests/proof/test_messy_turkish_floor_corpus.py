from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pytest

from common.config import cfg
from nlp.entity import EntityExtractor
from nlp.intent import (
    IntentClassifier,
    IntentModelNotFoundError,
    IntentModelUnavailable,
    INTENT_LABELS,
)
from nlp.lexicon_loader import LexiconStore
from nlp.normalize import normalize_input

TEST_ROOT = Path(__file__).resolve().parent
DATA_ROOT = TEST_ROOT.parent / "data"
CORPUS_PATH = DATA_ROOT / "messy_turkish_floor_corpus.jsonl"
METADATA_PATH = DATA_ROOT / "messy_turkish_floor_corpus.yaml"
LEXICON_ROOT = TEST_ROOT.parents[4] / "nlp" / "lexicon"

if os.getenv("NEGELIR_PROFILE") not in {"dev", "ci"}:
    pytest.skip(
        "Messy Turkish floor corpus tests run only in dev or ci profiles.",
        allow_module_level=True,
    )


def _load_rows() -> list[dict[str, Any]]:
    assert CORPUS_PATH.exists(), f"Messy Turkish floor corpus missing: {CORPUS_PATH}"
    rows: list[dict[str, Any]] = []
    with CORPUS_PATH.open("r", encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise AssertionError(
                    f"Invalid JSON on line {line_no} of {CORPUS_PATH}: {exc}"
                ) from exc
            assert isinstance(row, dict), (
                f"Row {line_no} of {CORPUS_PATH} must be a JSON object"
            )
            rows.append(row)
    return rows


def test_messy_turkish_floor_corpus_has_1000_rows() -> None:
    rows = _load_rows()
    assert len(rows) == 1000, (
        f"Messy Turkish floor corpus must contain exactly 1000 rows, got {len(rows)}"
    )


def test_messy_turkish_floor_corpus_metadata_matches() -> None:
    assert METADATA_PATH.exists(), f"Corpus metadata missing: {METADATA_PATH}"
    import yaml

    metadata = yaml.safe_load(METADATA_PATH.read_text(encoding="utf-8"))
    assert metadata.get("row_count") == 1000, (
        f"Corpus metadata row_count must be 1000, got {metadata.get('row_count')!r}"
    )
    assert metadata.get("corpus_name") == "messy_turkish_floor_corpus"
    assert isinstance(metadata.get("sha256"), str)

    actual_sha = hashlib.sha256(CORPUS_PATH.read_bytes()).hexdigest()
    assert metadata["sha256"] == actual_sha, (
        "Corpus metadata sha256 must match the current JSONL payload"
    )


def test_messy_turkish_floor_corpus_schema_is_valid() -> None:
    rows = _load_rows()
    ids: set[str] = set()
    for row in rows:
        assert "id" in row and isinstance(row["id"], str) and row["id"].strip(), (
            "Every row must have a non-empty id"
        )
        assert row["id"] not in ids, f"Duplicate corpus id: {row['id']}"
        ids.add(row["id"])

        assert "text" in row and isinstance(row["text"], str) and row["text"].strip(), (
            f"Row {row['id']} requires non-empty text"
        )
        assert "expected_intent" in row and row["expected_intent"] in INTENT_LABELS, (
            f"Row {row['id']} has invalid expected_intent: {row.get('expected_intent')!r}"
        )
        assert "expected_top_entity" in row and isinstance(row["expected_top_entity"], str), (
            f"Row {row['id']} requires expected_top_entity"
        )


def test_messy_turkish_floor_corpus_end_to_end_metrics() -> None:
    rows = _load_rows()
    try:
        classifier = IntentClassifier.load(cfg)
    except (IntentModelNotFoundError, IntentModelUnavailable) as exc:
        pytest.skip(f"Intent classifier model unavailable: {exc}")

    store = LexiconStore(LEXICON_ROOT)
    store.maybe_reload()
    assert store.is_loaded, "Lexicon store failed to load the NLP lexicon snapshot"

    extractor = EntityExtractor(store=store)

    correct_intent = 0
    correct_entity = 0
    refusal_count = 0

    for row in rows:
        text = row["text"]
        normalized = normalize_input(text)

        predicted_intent, _ = classifier.predict_intent(" ".join(normalized.tokens))
        if predicted_intent.startswith("meta."):
            refusal_count += 1
        if predicted_intent == row["expected_intent"]:
            correct_intent += 1

        result = extractor.extract(list(normalized.tokens), raw_tokens=list(normalized.tokens))
        actual_top1 = result.spans[0].canonical_id if result.spans else ""
        if actual_top1 == row["expected_top_entity"]:
            correct_entity += 1

    total = len(rows)
    intent_accuracy = correct_intent / total
    entity_top1_accuracy = correct_entity / total
    refusal_rate = refusal_count / total

    print(
        f"Messy Turkish floor corpus metrics: intent_accuracy={intent_accuracy:.4f}, "
        f"entity_top1_accuracy={entity_top1_accuracy:.4f}, refusal_rate={refusal_rate:.4f}, n={total}"
    )

    assert intent_accuracy >= 0.92, (
        f"Intent top-1 accuracy {intent_accuracy:.4f} < 0.92 on messy Turkish floor corpus"
    )
    assert entity_top1_accuracy >= 0.88, (
        f"Entity top-1 accuracy {entity_top1_accuracy:.4f} < 0.88 on messy Turkish floor corpus"
    )
    assert refusal_rate <= 0.05, (
        f"Refusal rate {refusal_rate:.4f} > 0.05 on messy Turkish floor corpus"
    )
