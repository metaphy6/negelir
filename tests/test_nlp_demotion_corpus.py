"""Phase 13.11.5 — Gazetteer regression corpus (demotion corpus) tests.

Per LEAGUE_CATALOG.md §2.2 and §13.11.5, each league commits a demotion corpus
alongside its promotion corpus. The demotion corpus contains queries that
historically caused mis-resolution and must continue to resolve correctly.

Demotion corpus location:
  ai/tests/fixtures/nlp/<league_id>/demotion_corpus.jsonl

Format (JSONL):
  {"query": "...", "intent": "...", "expected_entities": [...], "notes": "..."}

Tests ensure that:
  1. All demotion corpus queries resolve correctly
  2. No regression: previously-fixed entities must not become ambiguous again
  3. Recall on demotion corpus >= cfg.nlp_promotion_recall_min
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
    pytest.skip("Demotion corpus tests run only in dev or ci profiles.", allow_module_level=True)


def _find_league_demotion_corpus_paths() -> dict[str, Path]:
    """Find all per-league demotion_corpus.jsonl files."""
    paths = {}
    if FIXTURES_ROOT.exists():
        for league_dir in FIXTURES_ROOT.iterdir():
            if not league_dir.is_dir():
                continue
            corpus_path = league_dir / "demotion_corpus.jsonl"
            if corpus_path.exists():
                paths[league_dir.name] = corpus_path
    return paths


def _load_corpus(corpus_path: Path) -> list[dict[str, Any]]:
    """Load a demotion_corpus.jsonl file."""
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
        return 1.0
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
        for league_id, corpus_path in _find_league_demotion_corpus_paths().items()
    ],
    ids=lambda x: x[0] if isinstance(x, tuple) else x,
)
def test_league_demotion_corpus_recall_no_regression(
    league_id: str,
    corpus_path: Path,
    entity_extractor: EntityExtractor,
) -> None:
    """Demotion corpus: previously-fixed queries must still resolve correctly (no regression).
    
    This is a regression test: demotion corpus queries are examples of past
    mis-resolutions. They must continue to resolve to their expected entities.
    If any query in the demotion corpus fails, it indicates a regression.
    """
    corpus = _load_corpus(corpus_path)
    assert len(corpus) > 0, (
        f"League {league_id} demotion corpus must have at least one query"
    )

    tp = 0  # true positives
    fn = 0  # false negatives
    failed_queries = []

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
        matches = extracted_ids & expected_ids
        misses = expected_ids - extracted_ids
        tp += len(matches)
        fn += len(misses)

        if misses:
            failed_queries.append({
                "query": query,
                "expected": sorted(expected_ids),
                "extracted": sorted(extracted_ids),
                "missed": sorted(misses),
            })

    recall = _compute_recall(tp, fn)
    min_recall = cfg.nlp_promotion_recall_min

    assert recall >= min_recall, (
        f"League {league_id} demotion corpus recall {recall:.4f} < {min_recall:.4f} "
        f"(TP={tp}, FN={fn}). This indicates a regression in entity extraction. "
        f"Failed queries: {failed_queries}"
    )

    assert len(failed_queries) == 0, (
        f"League {league_id} demotion corpus: {len(failed_queries)} queries regressed. "
        f"Details: {failed_queries}"
    )


def test_demotion_corpus_exists_for_promotion_corpus() -> None:
    """Every league with a promotion corpus should ideally have a demotion corpus."""
    promotion_paths = {}
    demotion_paths = _find_league_demotion_corpus_paths()

    if FIXTURES_ROOT.exists():
        for league_dir in FIXTURES_ROOT.iterdir():
            if not league_dir.is_dir():
                continue
            corpus_path = league_dir / "promotion_corpus.jsonl"
            if corpus_path.exists():
                promotion_paths[league_dir.name] = corpus_path

    # Check that all promotion leagues have demotion corpora
    # (This is a "should" not a "must" — some leagues may not have a demotion corpus yet)
    for league_id in promotion_paths.keys():
        if league_id not in demotion_paths:
            pytest.skip(f"League {league_id} has promotion corpus but no demotion corpus yet")
