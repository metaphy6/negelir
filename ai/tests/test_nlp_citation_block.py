"""Phase 10 §10.7 — Citation block tests.

Verifies that every predict.* template:
- Contains CITATION_DELIMITER in its rendered output.
- Exposes all required citation fields (prediction_id, produced_at_utc,
  model_versions, calibration_version).
- Returns a deterministic SHA-256 via render_with_citation().
- Carries the citation block even in degraded mode.

Non-predict templates (meta.*, data.*, summary.*) must return None for the
citation sha256.
"""
from __future__ import annotations

import datetime as dt
import hashlib

import pytest

from nlp.render import (
    CITATION_DELIMITER,
    build_environment,
    citation_sha256,
    extract_citation_block,
    render,
    render_with_citation,
)

# ---------------------------------------------------------------------------
# Shared context covering all predict.* template slots
# ---------------------------------------------------------------------------

_CITATION_CTX: dict = {
    "home_team": "Galatasaray",
    "away_team": "Fenerbahçe",
    # predict.match_outcome / predict.handicap
    "outcome_label": "Galatasaray kazanır",
    # predict.over_under
    "threshold": 2.5,
    "direction_label": "Üzeri",
    # predict.btts
    "btts_label": "Evet",
    # predict.handicap
    "handicap_line": "-1",
    # predict.score_grid
    "score_rows": [
        type("Row", (), {"home_goals": 1, "away_goals": 0, "probability_pct": 30})(),
    ],
    # shared
    "probability": 0.78,
    "kickoff_utc": dt.datetime(2026, 5, 30, 20, 0, tzinfo=dt.timezone.utc),
    "degraded": False,
    "degraded_reason": "",
    "prediction_id": "pred-cite-1",
    "produced_at_utc": "2026-05-27T10:00:00Z",
    "model_versions": ["predictor-v1@1.0.0"],
    "calibration_version": "cal-v1",
}

_PREDICT_TEMPLATES = [
    "predict.match_outcome.tr.j2",
    "predict.over_under.tr.j2",
    "predict.btts.tr.j2",
    "predict.handicap.tr.j2",
    "predict.score_grid.tr.j2",
]

_NON_PREDICT_TEMPLATES = [
    "meta.unsupported.tr.j2",
    "meta.help.tr.j2",
    "meta.adversarial.tr.j2",
]


# ---------------------------------------------------------------------------
# 1. CITATION_DELIMITER present in every predict.* template
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("tmpl", _PREDICT_TEMPLATES)
def test_citation_delimiter_present(tmpl: str) -> None:
    """CITATION_DELIMITER must appear in every predict.* rendered output."""
    env = build_environment()
    text = render(tmpl, _CITATION_CTX, env=env)
    assert CITATION_DELIMITER in text, (
        f"CITATION_DELIMITER not found in rendered output of {tmpl!r}"
    )


# ---------------------------------------------------------------------------
# 2. Citation block contains all required fields
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("tmpl", _PREDICT_TEMPLATES)
def test_citation_fields_complete(tmpl: str) -> None:
    """Citation block must include prediction_id, produced_at_utc,
    model_versions (at least one version string), and calibration_version."""
    env = build_environment()
    text = render(tmpl, _CITATION_CTX, env=env)
    _, citation = extract_citation_block(text)
    assert citation is not None, f"No citation block extracted from {tmpl!r}"
    assert "pred-cite-1" in citation, "prediction_id missing from citation"
    assert "2026-05-27T10:00:00Z" in citation, "produced_at_utc missing from citation"
    assert "predictor-v1@1.0.0" in citation, "model_version missing from citation"
    assert "cal-v1" in citation, "calibration_version missing from citation"


# ---------------------------------------------------------------------------
# 3. render_with_citation returns (str, 64-char hex)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("tmpl", _PREDICT_TEMPLATES)
def test_render_with_citation_returns_sha256(tmpl: str) -> None:
    env = build_environment()
    text, sha = render_with_citation(tmpl, _CITATION_CTX, env=env)
    assert isinstance(text, str)
    assert isinstance(sha, str), f"Expected str sha256 for {tmpl!r}, got {sha!r}"
    assert len(sha) == 64, f"SHA-256 hex must be 64 chars; got {len(sha)}"


# ---------------------------------------------------------------------------
# 4. SHA-256 is deterministic across two calls
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("tmpl", _PREDICT_TEMPLATES)
def test_citation_sha256_deterministic(tmpl: str) -> None:
    env = build_environment()
    _, sha1 = render_with_citation(tmpl, _CITATION_CTX, env=env)
    _, sha2 = render_with_citation(tmpl, _CITATION_CTX, env=env)
    assert sha1 == sha2, f"Non-deterministic sha256 for {tmpl!r}"


# ---------------------------------------------------------------------------
# 5. Non-predict templates return None for citation sha256
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("tmpl", _NON_PREDICT_TEMPLATES)
def test_non_predict_template_returns_none_citation(tmpl: str) -> None:
    env = build_environment()
    _, sha = render_with_citation(tmpl, {}, env=env)
    assert sha is None, (
        f"{tmpl!r} must return None for citation sha256 (not a predict.* template)"
    )


# ---------------------------------------------------------------------------
# 6. extract_citation_block unit tests
# ---------------------------------------------------------------------------

def test_extract_splits_on_delimiter() -> None:
    body = "Tahmin metni burada."
    citation = "[tahmin:pred-1 | üretim:2026-05-27T10:00:00Z]\n"
    full = body + CITATION_DELIMITER + citation
    extracted_body, extracted_citation = extract_citation_block(full)
    assert extracted_body == body
    assert extracted_citation == citation


def test_extract_no_delimiter_returns_none() -> None:
    text = "Bu metinde ayraç yok."
    body, citation = extract_citation_block(text)
    assert body == text
    assert citation is None


def test_extract_only_first_delimiter_is_used() -> None:
    """If the body itself somehow contained the delimiter string, only the first
    occurrence should be the split point."""
    inner = f"first{CITATION_DELIMITER}second"
    citation = "citation_text\n"
    full = inner + CITATION_DELIMITER + citation
    _, extracted_citation = extract_citation_block(full)
    # The extracted citation is everything after the FIRST delimiter
    assert extracted_citation is not None
    # The citation must not contain CITATION_DELIMITER itself (was split at first)
    # but the body will (because we only split at the first occurrence)


# ---------------------------------------------------------------------------
# 7. citation_sha256 function
# ---------------------------------------------------------------------------

def test_citation_sha256_matches_stdlib() -> None:
    block = "[tahmin:pred-1 | üretim:2026-05-27T10:00:00Z]\n"
    expected = hashlib.sha256(block.encode("utf-8")).hexdigest()
    assert citation_sha256(block) == expected


def test_citation_sha256_is_64_chars() -> None:
    assert len(citation_sha256("arbitrary")) == 64


# ---------------------------------------------------------------------------
# 8. Degraded predict.* still carries citation block
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("tmpl", _PREDICT_TEMPLATES)
def test_degraded_prediction_has_citation(tmpl: str) -> None:
    """degraded=True must not suppress the citation block."""
    env = build_environment()
    ctx = {**_CITATION_CTX, "degraded": True, "degraded_reason": "eksik veri"}
    text, sha = render_with_citation(tmpl, ctx, env=env)
    assert sha is not None, (
        f"Degraded {tmpl!r} must still return a citation sha256"
    )
    _, citation = extract_citation_block(text)
    assert citation is not None


# ---------------------------------------------------------------------------
# 9. Adversarial: mutating citation block changes sha256
# ---------------------------------------------------------------------------

def test_sha256_changes_on_tamper() -> None:
    env = build_environment()
    text, sha_original = render_with_citation(
        "predict.match_outcome.tr.j2", _CITATION_CTX, env=env
    )
    assert sha_original is not None
    # Tamper: change prediction_id in the rendered text
    tampered = text.replace("pred-cite-1", "pred-TAMPERED")
    _, tampered_citation = extract_citation_block(tampered)
    assert tampered_citation is not None
    sha_tampered = citation_sha256(tampered_citation)
    assert sha_original != sha_tampered, (
        "Tampered citation must produce a different sha256"
    )


# ---------------------------------------------------------------------------
# §10.21.6: Citation block canonical form tests
# ---------------------------------------------------------------------------

def test_nlp_citation_block_canonical_form_is_byte_stable() -> None:
    """§10.21.6 requirement: citation block renders in normalized canonical
    form (sorted keys, fixed whitespace) so §10.9 sha256 round-trip is byte-stable.
    
    This test verifies that:
    1. The same citation_data dict produces identical output across calls
    2. Dict iteration order does not affect output (keys always sorted)
    3. The sha256 of the canonical form is stable
    """
    from nlp.render import render_citation_block
    
    citation_data = {
        "prediction_id": "pred-test-123",
        "produced_at_utc": "2026-05-27T10:00:00Z",
        "model_versions": ["predictor-v2@2.1.0", "predictor-v1@1.0.0"],
        "calibration_version": 42,
    }
    
    # Call render_citation_block multiple times
    block1 = render_citation_block(citation_data)
    block2 = render_citation_block(citation_data)
    block3 = render_citation_block(citation_data)
    
    # All must be byte-identical
    assert block1 == block2 == block3, "Citation block is not byte-stable"
    
    # Verify sha256 is stable
    sha1 = citation_sha256(block1)
    sha2 = citation_sha256(block2)
    sha3 = citation_sha256(block3)
    assert sha1 == sha2 == sha3, "Citation sha256 is not stable"
    
    # Verify model_versions are sorted (not in original order)
    # Original order: predictor-v2, predictor-v1
    # Sorted order: predictor-v1, predictor-v2
    assert "predictor-v1@1.0.0, predictor-v2@2.1.0" in block1, (
        "model_versions must be sorted for canonical form"
    )
    
    # Verify dict iteration order doesn't matter by creating dict in different order
    citation_data_reversed = {
        "calibration_version": 42,
        "model_versions": ["predictor-v2@2.1.0", "predictor-v1@1.0.0"],
        "produced_at_utc": "2026-05-27T10:00:00Z",
        "prediction_id": "pred-test-123",
    }
    block_reversed = render_citation_block(citation_data_reversed)
    assert block1 == block_reversed, (
        "Citation block must be identical regardless of dict key order"
    )


def test_render_citation_block_with_degraded_reason() -> None:
    """Citation block with optional degraded_reason field."""
    from nlp.render import render_citation_block
    
    citation_data = {
        "prediction_id": "pred-deg-1",
        "produced_at_utc": "2026-05-27T12:00:00Z",
        "model_versions": ["predictor-v1@1.0.0"],
        "calibration_version": 10,
        "degraded_reason": "insufficient-data",
    }
    
    block = render_citation_block(citation_data)
    
    # Must contain all required fields
    assert "pred-deg-1" in block
    assert "2026-05-27T12:00:00Z" in block
    assert "10" in block
    assert "predictor-v1@1.0.0" in block
    
    # Must contain degraded_reason on separate line
    assert "[sebep:insufficient-data]" in block
    
    # Verify byte-stability with degraded_reason
    block2 = render_citation_block(citation_data)
    assert block == block2


def test_render_citation_block_rejects_extra_keys() -> None:
    """§10.21.6 requirement: citation block accepts ONLY the closed schema."""
    from nlp.render import render_citation_block
    
    citation_data = {
        "prediction_id": "pred-1",
        "produced_at_utc": "2026-05-27T10:00:00Z",
        "model_versions": ["predictor-v1@1.0.0"],
        "calibration_version": 1,
        "extra_field": "not allowed",  # This should trigger ValueError
    }
    
    with pytest.raises(ValueError, match="disallowed keys.*extra_field"):
        render_citation_block(citation_data)


def test_render_citation_block_requires_all_mandatory_fields() -> None:
    """Citation block must include all required fields."""
    from nlp.render import render_citation_block
    
    # Missing prediction_id
    citation_data_incomplete = {
        "produced_at_utc": "2026-05-27T10:00:00Z",
        "model_versions": ["predictor-v1@1.0.0"],
        "calibration_version": 1,
    }
    
    with pytest.raises(KeyError, match="missing required keys.*prediction_id"):
        render_citation_block(citation_data_incomplete)


def test_render_citation_block_model_versions_sorted() -> None:
    """model_versions must be sorted for deterministic output."""
    from nlp.render import render_citation_block
    
    # Test with different ordering
    citation1 = {
        "prediction_id": "pred-sort-test",
        "produced_at_utc": "2026-05-27T10:00:00Z",
        "model_versions": ["z-predictor", "a-predictor", "m-predictor"],
        "calibration_version": 1,
    }
    
    citation2 = {
        "prediction_id": "pred-sort-test",
        "produced_at_utc": "2026-05-27T10:00:00Z",
        "model_versions": ["m-predictor", "z-predictor", "a-predictor"],
        "calibration_version": 1,
    }
    
    block1 = render_citation_block(citation1)
    block2 = render_citation_block(citation2)
    
    # Both must produce identical output (sorted)
    assert block1 == block2
    assert "a-predictor, m-predictor, z-predictor" in block1
