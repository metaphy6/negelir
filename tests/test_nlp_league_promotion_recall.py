"""Phase 13 §13.11 — Per-league entity-extraction recall gate for T2→T1 promotion.

Tests that every league in the catalog with a per-league test corpus
meets the minimum entity-extraction recall threshold (cfg.nlp_promotion_recall_min)
required for T2→T1 promotion.

Corpus format (JSONL):
  {"query": "...", "intent": "...", "expected_entities": [...], "notes": "..."}

Each league's corpus is committed to:
  ai/tests/fixtures/nlp/<league_id>/promotion_corpus.jsonl
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from common.config import cfg
from nlp.entity import EntityExtractor
from nlp.lexicon_loader import LexiconStore
from nlp.normalize import normalize_input

TEST_ROOT = Path(__file__).resolve().parent
FIXTURES_ROOT = TEST_ROOT / "fixtures" / "nlp"
LEXICON_ROOT = TEST_ROOT.parent / "nlp" / "lexicon"

if os.getenv("NEGELIR_PROFILE") not in {"dev", "ci"}:
    pytest.skip("League promotion recall tests run only in dev or ci profiles.", allow_module_level=True)


def _find_league_corpus_paths() -> dict[str, Path]:
    """Find all per-league promotion_corpus.jsonl files."""
    paths = {}
    if FIXTURES_ROOT.exists():
        for league_dir in FIXTURES_ROOT.iterdir():
            if not league_dir.is_dir():
                continue
            corpus_path = league_dir / "promotion_corpus.jsonl"
            if corpus_path.exists():
                paths[league_dir.name] = corpus_path
    return paths


def _load_promotion_corpus(corpus_path: Path) -> list[dict[str, Any]]:
    """Load a promotion_corpus.jsonl file."""
    rows: list[dict[str, Any]] = []
    with corpus_path.open("r", encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise AssertionError(
                    f"Invalid JSON on line {line_no} of {corpus_path}: {exc}"
                ) from exc
            assert isinstance(row, dict), f"Corpus row {line_no} must be an object"
            assert "query" in row, f"Corpus row {line_no} missing 'query'"
            assert "expected_entities" in row, f"Corpus row {line_no} missing 'expected_entities'"
            rows.append(row)
    return rows


def _compute_recall(tp: int, fn: int) -> float:
    """Compute recall: TP / (TP + FN)."""
    if tp + fn == 0:
        return 1.0  # No entities to extract = perfect recall
    return tp / (tp + fn)


@pytest.fixture(scope="session")
def entity_extractor() -> EntityExtractor:
    """Load the entity extractor once per session."""
    store = LexiconStore(LEXICON_ROOT)
    store.maybe_reload()
    return EntityExtractor(store=store)


@pytest.mark.parametrize(
    "league_id,corpus_path",
    [
        (league_id, corpus_path)
        for league_id, corpus_path in _find_league_corpus_paths().items()
    ],
    ids=lambda x: x[0] if isinstance(x, tuple) else x,
)
def test_league_entity_extraction_recall_gate(
    league_id: str,
    corpus_path: Path,
    entity_extractor: EntityExtractor,
) -> None:
    """Entity-extraction recall ≥ cfg.nlp_promotion_recall_min on per-league corpus."""
    corpus = _load_promotion_corpus(corpus_path)
    assert len(corpus) >= 50, (
        f"League {league_id} promotion corpus must have ≥ 50 queries, "
        f"found {len(corpus)}"
    )

    tp = 0  # true positives
    fn = 0  # false negatives

    for entry in corpus:
        query = entry["query"]
        expected_entity_ids = entry.get("expected_entities", [])

        # Normalize and tokenize the query
        normalized = normalize_input(query)
        tokens = list(normalized.tokens)

        # Extract entities
        result = entity_extractor.extract(tokens, raw_tokens=tokens)
        extracted_ids = {span.canonical_id for span in result.spans}

        # Expected entity IDs
        expected_ids = set(expected_entity_ids)

        # Compute TP and FN for this query
        tp += len(extracted_ids & expected_ids)
        fn += len(expected_ids - extracted_ids)

    recall = _compute_recall(tp, fn)
    min_recall = cfg.nlp_promotion_recall_min

    assert recall >= min_recall, (
        f"League {league_id}: entity-extraction recall {recall:.4f} < {min_recall:.4f} "
        f"(TP={tp}, FN={fn}, total_expected={tp + fn})"
    )


def test_promotion_corpus_coverage_exists() -> None:
    """At least one league's promotion_corpus.jsonl exists."""
    corpus_paths = _find_league_corpus_paths()
    assert len(corpus_paths) > 0, (
        "No promotion_corpus.jsonl files found under "
        f"ai/tests/fixtures/nlp/<league_id>/; please create at least one per-league corpus"
    )


def test_each_promotion_corpus_has_minimum_rows() -> None:
    """Each promotion_corpus.jsonl has at least 50 rows."""
    corpus_paths = _find_league_corpus_paths()
    for league_id, corpus_path in corpus_paths.items():
        corpus = _load_promotion_corpus(corpus_path)
        assert len(corpus) >= 50, (
            f"League {league_id} promotion corpus must have ≥ 50 queries, "
            f"found {len(corpus)}"
        )


def test_promotion_corpus_expected_entities_are_strings() -> None:
    """Each 'expected_entities' value is a list of strings."""
    corpus_paths = _find_league_corpus_paths()
    for league_id, corpus_path in corpus_paths.items():
        corpus = _load_promotion_corpus(corpus_path)
        for i, entry in enumerate(corpus):
            expected = entry.get("expected_entities", [])
            assert isinstance(expected, list), (
                f"League {league_id} row {i}: 'expected_entities' must be a list, "
                f"got {type(expected)}"
            )
            for j, entity_id in enumerate(expected):
                assert isinstance(entity_id, str), (
                    f"League {league_id} row {i} item {j}: expected_entities items must be "
                    f"strings (canonical entity IDs), got {type(entity_id)}"
                )
