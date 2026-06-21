"""Phase 10 §10.15 — Adversarial corpus alignment with Phase 12.

Per §10.15: Phase 12 §12.2 fixture set (``ai/tests/fixtures/adversarial/``) is
the **single source** for NLP adversarial tests. NLP DoD requires 100% block
of every entry mapped to NLP plane (no xfail).

This test validates that the NLP injection probe correctly routes all
adversarial inputs to ``meta.adversarial`` intent.
"""
import pytest
import yaml
from pathlib import Path

from nlp.injection_probe import probe_normalized_text
from nlp.normalize import normalize_input


CORPUS_PATH = Path(__file__).parent / "fixtures" / "adversarial" / "nlp_corpus.yaml"


@pytest.fixture(scope="module")
def adversarial_corpus():
    """Load the adversarial corpus from Phase 12 §12.2 fixture set."""
    if not CORPUS_PATH.exists():
        pytest.skip(f"Adversarial corpus not found: {CORPUS_PATH}")
    
    with open(CORPUS_PATH, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    
    assert data.get("version") == 1, "Corpus must be version 1"
    corpus = data.get("corpus", [])
    assert len(corpus) > 0, "Corpus must not be empty"
    
    return corpus


def test_adversarial_corpus_structure(adversarial_corpus):
    """Validate the corpus structure matches the schema."""
    required_fields = {"id", "text", "expected_intent", "category", "severity", "notes"}
    
    for entry in adversarial_corpus:
        missing = required_fields - set(entry.keys())
        assert not missing, f"Entry {entry.get('id', '?')} missing fields: {missing}"
        
        # All adversarial entries must expect meta.adversarial intent
        assert entry["expected_intent"] == "meta.adversarial", (
            f"Entry {entry['id']} must expect meta.adversarial, got {entry['expected_intent']}"
        )
        
        # Category must be one of the known types
        valid_categories = {"prompt_injection", "off_topic", "abuse", "jailbreak"}
        assert entry["category"] in valid_categories, (
            f"Entry {entry['id']} has invalid category: {entry['category']}"
        )
        
        # Severity must be valid
        valid_severities = {"info", "warn", "error", "critical"}
        assert entry["severity"] in valid_severities, (
            f"Entry {entry['id']} has invalid severity: {entry['severity']}"
        )


def test_adversarial_corpus_100_percent_block(adversarial_corpus):
    """Phase 10 §10.15: NLP must block 100% of adversarial corpus (no xfail).
    
    This is the binding test. Every entry in the corpus must be detected
    by the injection probe after normalization.
    
    Note: Entries marked ``requires_intent_classifier=true`` are skipped
    for now as the intent classifier (§10.4) is a separate bullet. Once
    §10.4 lands, this skip will be removed.
    """
    failed = []
    skipped_count = 0
    
    for entry in adversarial_corpus:
        # Skip entries that require the intent classifier (§10.4 not yet landed)
        if entry.get('requires_intent_classifier', False):
            skipped_count += 1
            continue
        
        text = entry["text"]
        entry_id = entry["id"]
        
        # Run through the NLP normalization pipeline
        normalized_result = normalize_input(text)
        normalized_text = " ".join(normalized_result.tokens)
        
        # Apply the injection probe
        result = probe_normalized_text(normalized_text)
        
        if not result.detected:
            failed.append({
                "id": entry_id,
                "text": text,
                "normalized": normalized_text,
                "category": entry["category"],
                "notes": entry["notes"]
            })
    
    # 100% block rate requirement (excluding intent-classifier-dependent entries)
    if failed:
        msg_lines = ["Phase 10 §10.15 VIOLATION: Adversarial inputs not blocked:"]
        for f in failed:
            msg_lines.append(f"  - {f['id']}: {f['text']!r}")
            msg_lines.append(f"    Category: {f['category']}, Normalized: {f['normalized']!r}")
            msg_lines.append(f"    Notes: {f['notes']}")
        
        if skipped_count > 0:
            msg_lines.append(f"\n(Note: {skipped_count} entries skipped pending §10.4 intent classifier)")
        
        pytest.fail("\n".join(msg_lines))
    
    # Log how many were tested vs skipped
    if skipped_count > 0:
        pytest.skip(
            f"Tested {len(adversarial_corpus) - skipped_count} entries; "
            f"{skipped_count} skipped pending §10.4 intent classifier"
        )


def test_adversarial_corpus_ids_unique(adversarial_corpus):
    """All corpus IDs must be unique."""
    ids = [entry["id"] for entry in adversarial_corpus]
    duplicates = [id for id in ids if ids.count(id) > 1]
    
    assert not duplicates, f"Duplicate corpus IDs found: {set(duplicates)}"


def test_adversarial_corpus_minimum_coverage():
    """Corpus must cover minimum categories per §10.15."""
    if not CORPUS_PATH.exists():
        pytest.skip(f"Adversarial corpus not found: {CORPUS_PATH}")
    
    with open(CORPUS_PATH, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    
    corpus = data.get("corpus", [])
    categories = {entry["category"] for entry in corpus}
    
    # Minimum categories from §10.15
    required_categories = {"prompt_injection", "off_topic"}
    missing = required_categories - categories
    
    assert not missing, (
        f"Corpus must cover minimum categories: {missing} not found"
    )


def test_adversarial_corpus_no_clean_queries():
    """Adversarial corpus must not contain clean football queries.
    
    This is a negative test: the corpus is for adversarial inputs only.
    Clean queries belong in the positive test corpus (§10.18).
    """
    if not CORPUS_PATH.exists():
        pytest.skip(f"Adversarial corpus not found: {CORPUS_PATH}")
    
    with open(CORPUS_PATH, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    
    corpus = data.get("corpus", [])
    
    # Heuristic: if the text contains Turkish football terms and no
    # adversarial markers, flag it for review
    football_keywords = {"galatasaray", "fenerbahçe", "beşiktaş", "trabzonspor", 
                         "maç", "gol", "skor", "tahmin", "oyna"}
    adversarial_markers = {"ignore", "forget", "system", "disregard", "capital", 
                           "cook", "pasta", "weather", "hava"}
    
    for entry in corpus:
        text_lower = entry["text"].lower()
        has_football = any(kw in text_lower for kw in football_keywords)
        has_adversarial = any(marker in text_lower for marker in adversarial_markers)
        
        # If it looks like a football query with no adversarial markers, flag it
        if has_football and not has_adversarial:
            pytest.fail(
                f"Entry {entry['id']} appears to be a clean football query: {entry['text']!r}. "
                "Clean queries belong in the positive corpus (§10.18), not adversarial."
            )
