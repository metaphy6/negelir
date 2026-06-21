"""Phase 10 §10.30 boot regression corpus guard tests."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

from nlp.entity import EntityExtractor
from nlp.lexicon_loader import LexiconStore
from nlp.normalize import normalize_input
from nlp.intent import IntentClassifier, INTENT_LABELS
from common.config import cfg

TEST_ROOT = Path(__file__).resolve().parent
BOOT_CORPUS_PATH = TEST_ROOT.parent / "swarm" / "agents" / "nlp" / "tests" / "data" / "boot_regression_corpus.jsonl"

if os.getenv("NEGELIR_PROFILE") not in {"dev", "ci"}:
    pytest.skip("Boot regression corpus tests run only in dev or ci profiles.", allow_module_level=True)


def _load_rows() -> list[dict[str, object]]:
    assert BOOT_CORPUS_PATH.exists(), f"Boot corpus missing: {BOOT_CORPUS_PATH}"
    rows: list[dict[str, object]] = []
    with BOOT_CORPUS_PATH.open("r", encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise AssertionError(f"Invalid JSON on line {line_no} of {BOOT_CORPUS_PATH}: {exc}") from exc
            assert isinstance(row, dict), f"Boot corpus row {line_no} must be an object"
            rows.append(row)
    return rows


def test_boot_corpus_min_row_count() -> None:
    rows = _load_rows()
    assert len(rows) == 200, f"Boot corpus must contain exactly 200 rows, found {len(rows)}"


def test_boot_corpus_rows_have_same_version() -> None:
    rows = _load_rows()
    versions = {row.get("boot_corpus_version") for row in rows}
    assert len(versions) == 1, f"All boot corpus rows must share the same boot_corpus_version, found {sorted(versions)}"
    version = versions.pop()
    assert isinstance(version, str), "boot_corpus_version must be a string"
    assert re.fullmatch(r"\d+\.\d+\.\d+", version), f"boot_corpus_version must be semver, got {version!r}"


def test_boot_corpus_expected_fields() -> None:
    rows = _load_rows()
    for row in rows:
        assert "id" in row and isinstance(row["id"], str) and row["id"].strip(), "Each boot corpus row requires a non-empty id"
        assert "text" in row and isinstance(row["text"], str) and row["text"].strip(), "Each boot corpus row requires a non-empty text"
        assert "expected_intent_id" in row and isinstance(row["expected_intent_id"], str) and row["expected_intent_id"].strip(), "Each boot corpus row requires expected_intent_id"
        assert "boot_corpus_version" in row
        assert "expected_top_entities" in row and isinstance(row["expected_top_entities"], list)


def test_boot_corpus_not_used_as_intent_shadow_training() -> None:
    from common.config import cfg

    shadow_path = Path(cfg.nlp_intent_train_shadow_path)
    assert shadow_path.resolve() != BOOT_CORPUS_PATH.resolve(), (
        "Boot regression corpus must not be configured as the intent training shadow corpus"
    )


def test_boot_corpus_drift_tolerance_config_is_two() -> None:
    assert cfg.nlp_boot_corpus_top1_entity_drift_max_rows == 2


def test_boot_corpus_expected_intent_id_is_closed_enum() -> None:
    rows = _load_rows()
    invalid_ids = [row["id"] for row in rows if row.get("expected_intent_id") not in INTENT_LABELS]
    assert not invalid_ids, (
        "Boot corpus expected_intent_id values must stay within the closed intent enum; "
        f"invalid rows: {invalid_ids}"
    )


def test_boot_corpus_top_entities_baseline_matches_extractor() -> None:
    rows = _load_rows()
    lexicon_root = TEST_ROOT.parent / "nlp" / "lexicon"
    store = LexiconStore(lexicon_root)
    store.maybe_reload()
    extractor = EntityExtractor(store=store)

    mismatched: list[str] = []
    for row in rows:
        normalized = normalize_input(row["text"])
        spans = extractor.extract(list(normalized.tokens), raw_tokens=list(normalized.tokens)).spans
        actual_top_entities = [span.canonical_id for span in spans][:3]
        expected_top_entities = row.get("expected_top_entities", [])
        assert isinstance(expected_top_entities, list)
        if actual_top_entities != expected_top_entities:
            mismatched.append(row["id"])

    assert not mismatched, (
        "Boot corpus expected_top_entities must match the current entity extractor baseline; "
        f"mismatched rows: {mismatched}"
    )


def test_boot_corpus_top1_entity_drift_within_tolerance() -> None:
    rows = _load_rows()
    lexicon_root = TEST_ROOT.parent / "nlp" / "lexicon"
    store = LexiconStore(lexicon_root)
    store.maybe_reload()
    extractor = EntityExtractor(store=store)

    drift_rows: list[str] = []
    for row in rows:
        normalized = normalize_input(row["text"])
        spans = extractor.extract(list(normalized.tokens), raw_tokens=list(normalized.tokens)).spans
        actual_top1 = spans[0].canonical_id if spans else ""
        expected_top1 = row.get("expected_top_entities", [])[:1]
        expected_top1 = expected_top1[0] if expected_top1 else ""
        if actual_top1 != expected_top1:
            drift_rows.append(row["id"])

    assert len(drift_rows) <= cfg.nlp_boot_corpus_top1_entity_drift_max_rows, (
        "Boot corpus top-1 entity drift exceeded configured tolerance; "
        f"drift rows: {drift_rows}"
    )


def test_boot_corpus_intent_classification_matches_expected_if_model_available() -> None:
    rows = _load_rows()
    try:
        classifier = IntentClassifier.load(cfg)
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"Intent classifier model unavailable: {exc}")

    mismatched: list[str] = []
    for row in rows:
        predicted_intent, _prob = classifier.predict_intent(row["text"])
        if predicted_intent != row["expected_intent_id"]:
            mismatched.append(row["id"])

    assert not mismatched, (
        "Boot corpus intent predictions must match expected closed intent ids; "
        f"mismatched rows: {mismatched}"
    )


def _load_codeowners_entries() -> list[tuple[str, list[str]]]:
    root = TEST_ROOT.parent.parent
    path = root / ".github" / "CODEOWNERS"
    assert path.exists(), f"Expected .github/CODEOWNERS to exist for Phase 10 CODEOWNERS verification: {path}"

    entries: list[tuple[str, list[str]]] = []
    for line in path.read_text("utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        parts = text.split()
        if len(parts) < 2:
            continue
        entries.append((parts[0], parts[1:]))
    return entries


def test_nlp_codeowners_for_phase_10_high_leverage_nlp_files() -> None:
    entries = _load_codeowners_entries()
    expected_owner_sets = {
        "/ai/common/nlp/intent_enum_spec.json": {"@go-owner", "@nlp-curator"},
        "/ai/nlp/lang_tr/wh_intent_map.tr.yaml": {"@nlp-curator"},
        "/ai/nlp/lang_tr/idioms.tr.yaml": {"@nlp-curator", "@nlp-domain-football"},
        "/ai/nlp/lang_tr/idiom_context.tr.yaml": {"@nlp-curator", "@nlp-domain-football"},
        "/ai/nlp/lang_tr/conditional_markers.tr.yaml": {"@nlp-curator"},
        "/ai/nlp/lang_tr/politeness_markers.tr.yaml": {"@nlp-curator"},
        "/ai/nlp/lang_tr/search_operator_patterns.tr.yaml": {"@nlp-curator"},
        "/ai/nlp/lang_tr/anaphora_pronouns.tr.yaml": {"@nlp-curator"},
        "/ai/nlp/lang_tr/anaphora_compose.yaml": {"@nlp-curator"},
        "/ai/nlp/lang_tr/asr_punctuation_words.tr.yaml": {"@nlp-curator"},
        "/ai/nlp/lang_tr/voice_number_context.tr.yaml": {"@nlp-curator"},
        "/ai/nlp/lang_tr/offensive_obfuscated.tr.yaml": {"@nlp-curator", "@nlp-compliance"},
        "/ai/nlp/lang_tr/venues.tr.yaml": {"@nlp-curator"},
    }

    entry_map = {pattern: set(owners) for pattern, owners in entries}
    missing = [pattern for pattern in expected_owner_sets if pattern not in entry_map]
    assert not missing, f"Missing CODEOWNERS entries for Phase 10 NLP files: {missing}"

    mismatched = []
    for pattern, required_owners in expected_owner_sets.items():
        actual_owners = entry_map[pattern]
        if not required_owners.issubset(actual_owners):
            mismatched.append((pattern, required_owners - actual_owners))

    assert not mismatched, (
        "CODEOWNERS entries for Phase 10 NLP files must include all required owner groups; "
        f"missing owners: {mismatched}"
    )
