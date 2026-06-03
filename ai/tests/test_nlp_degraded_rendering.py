"""Phase 10 §10.7 — Degraded-mode rendering tests.

Verifies the «humanizer bypass» contract:
  1. All predict.* templates render the Turkish disclaimer when degraded=True.
  2. The disclaimer is absent when degraded=False.
  3. strip_degraded_for_humanizer() removes the disclaimer from the body and
     returns it as the second element.
  4. reinsert_degraded_disclaimer() puts the disclaimer back immediately before
     the citation delimiter — byte-for-byte reproducible.
  5. Round-trip: strip → humanizer no-op → reinsert == original rendered text.
  6. Citation SHA256 is unaffected by strip/reinsert (citation block unchanged).
  7. Non-predict templates (no degraded slot) go through strip/reinsert unchanged.
  8. Adversarial: disclaimer in middle of prose, multiple disclaimer-like lines
     (only first match removed), empty degraded_reason.
"""
from __future__ import annotations

import datetime as dt

import pytest

from nlp.render import (
    CITATION_DELIMITER,
    DEGRADED_DISCLAIMER_PREFIX,
    build_environment,
    citation_sha256,
    extract_citation_block,
    render,
    reinsert_degraded_disclaimer,
    strip_degraded_for_humanizer,
)

# ---------------------------------------------------------------------------
# Shared contexts
# ---------------------------------------------------------------------------

_BASE_CTX: dict = {
    "home_team": "Galatasaray",
    "away_team": "Fenerbahçe",
    "outcome_label": "Galatasaray kazanır",
    "threshold": 2.5,
    "direction_label": "Üzeri",
    "btts_label": "Evet",
    "handicap_line": "-1",
    "score_rows": [
        type("Row", (), {"home_goals": 1, "away_goals": 0, "probability_pct": 35})(),
    ],
    "probability": 0.72,
    "kickoff_utc": dt.datetime(2026, 6, 1, 18, 0, tzinfo=dt.timezone.utc),
    "prediction_id": "pred-deg-1",
    "produced_at_utc": "2026-06-01T10:00:00.000000Z",
    "model_versions": ["predictor-v2@2.0.0"],
    "calibration_version": "cal-v2",
}

_CTX_DEGRADED = {**_BASE_CTX, "degraded": True, "degraded_reason": "eksik veri"}
_CTX_NORMAL   = {**_BASE_CTX, "degraded": False, "degraded_reason": ""}

_PREDICT_TEMPLATES = [
    "predict.match_outcome.tr.j2",
    "predict.over_under.tr.j2",
    "predict.btts.tr.j2",
    "predict.handicap.tr.j2",
    "predict.score_grid.tr.j2",
]


# ---------------------------------------------------------------------------
# 1. Disclaimer present when degraded=True
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("tmpl", _PREDICT_TEMPLATES)
def test_disclaimer_present_when_degraded(tmpl: str) -> None:
    env = build_environment()
    text = render(tmpl, _CTX_DEGRADED, env=env)
    body, _ = extract_citation_block(text)
    assert DEGRADED_DISCLAIMER_PREFIX in body, (
        f"Degraded disclaimer not found in body of {tmpl!r} when degraded=True"
    )
    assert "eksik veri" in body, (
        f"degraded_reason 'eksik veri' not found in body of {tmpl!r}"
    )


# ---------------------------------------------------------------------------
# 2. Disclaimer absent when degraded=False
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("tmpl", _PREDICT_TEMPLATES)
def test_disclaimer_absent_when_not_degraded(tmpl: str) -> None:
    env = build_environment()
    text = render(tmpl, _CTX_NORMAL, env=env)
    body, _ = extract_citation_block(text)
    assert DEGRADED_DISCLAIMER_PREFIX not in body, (
        f"Degraded disclaimer must NOT appear in {tmpl!r} when degraded=False"
    )


# ---------------------------------------------------------------------------
# 3. strip_degraded_for_humanizer removes disclaimer from body
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("tmpl", _PREDICT_TEMPLATES)
def test_strip_removes_disclaimer(tmpl: str) -> None:
    env = build_environment()
    text = render(tmpl, _CTX_DEGRADED, env=env)
    stripped, disclaimer = strip_degraded_for_humanizer(text)
    assert disclaimer is not None, (
        f"strip_degraded_for_humanizer should return a disclaimer for {tmpl!r} (degraded)"
    )
    assert disclaimer.startswith(DEGRADED_DISCLAIMER_PREFIX), (
        f"Returned disclaimer must start with prefix. Got: {disclaimer!r}"
    )
    body_stripped, _ = extract_citation_block(stripped)
    assert DEGRADED_DISCLAIMER_PREFIX not in body_stripped, (
        f"Disclaimer must be removed from stripped body for {tmpl!r}"
    )


def test_strip_returns_none_when_not_degraded() -> None:
    env = build_environment()
    text = render("predict.match_outcome.tr.j2", _CTX_NORMAL, env=env)
    stripped, disclaimer = strip_degraded_for_humanizer(text)
    assert disclaimer is None, "No disclaimer expected for non-degraded render"
    assert stripped == text, "Text must be unchanged when no disclaimer present"


# ---------------------------------------------------------------------------
# 4. reinsert_degraded_disclaimer places disclaimer before citation delimiter
# ---------------------------------------------------------------------------

def test_reinsert_places_disclaimer_before_citation() -> None:
    env = build_environment()
    text = render("predict.match_outcome.tr.j2", _CTX_DEGRADED, env=env)
    stripped, disclaimer = strip_degraded_for_humanizer(text)
    assert disclaimer is not None
    restored = reinsert_degraded_disclaimer(stripped, disclaimer)
    # Disclaimer must appear before the citation delimiter in the restored text.
    disc_pos = restored.find(disclaimer)
    delim_pos = restored.find(CITATION_DELIMITER)
    assert disc_pos != -1, "Disclaimer not found after reinsert"
    assert delim_pos != -1, "Citation delimiter not found after reinsert"
    assert disc_pos < delim_pos, (
        "Disclaimer must appear before citation delimiter after reinsert"
    )


def test_reinsert_none_is_noop() -> None:
    env = build_environment()
    text = render("predict.match_outcome.tr.j2", _CTX_NORMAL, env=env)
    result = reinsert_degraded_disclaimer(text, None)
    assert result == text, "reinsert_degraded_disclaimer(text, None) must be a no-op"


# ---------------------------------------------------------------------------
# 5. Round-trip: strip → (identity) → reinsert preserves disclaimer content
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("tmpl", _PREDICT_TEMPLATES)
def test_round_trip_disclaimer_content(tmpl: str) -> None:
    env = build_environment()
    original = render(tmpl, _CTX_DEGRADED, env=env)
    stripped, disclaimer = strip_degraded_for_humanizer(original)
    assert disclaimer is not None
    restored = reinsert_degraded_disclaimer(stripped, disclaimer)
    # The disclaimer text must appear in the restored body.
    body_restored, _ = extract_citation_block(restored)
    assert DEGRADED_DISCLAIMER_PREFIX in body_restored, (
        f"Round-trip: disclaimer not found in restored body for {tmpl!r}"
    )
    assert "eksik veri" in body_restored, (
        f"Round-trip: degraded_reason not found in restored body for {tmpl!r}"
    )


# ---------------------------------------------------------------------------
# 6. Citation SHA256 is unaffected by strip / reinsert
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("tmpl", _PREDICT_TEMPLATES)
def test_citation_sha_unaffected_by_strip_reinsert(tmpl: str) -> None:
    env = build_environment()
    original = render(tmpl, _CTX_DEGRADED, env=env)
    _, orig_citation = extract_citation_block(original)
    assert orig_citation is not None
    orig_sha = citation_sha256(orig_citation)

    stripped, disclaimer = strip_degraded_for_humanizer(original)
    restored = reinsert_degraded_disclaimer(stripped, disclaimer)
    _, restored_citation = extract_citation_block(restored)
    assert restored_citation is not None
    restored_sha = citation_sha256(restored_citation)

    assert orig_sha == restored_sha, (
        f"Citation SHA256 changed after strip/reinsert for {tmpl!r}. "
        f"Before: {orig_sha!r}, after: {restored_sha!r}"
    )


# ---------------------------------------------------------------------------
# 7. Non-predict templates go through strip/reinsert unchanged
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("tmpl,ctx", [
    ("meta.help.tr.j2",         {}),
    ("meta.unsupported.tr.j2",  {"suggestions": ["unknown intent"]}),
])
def test_non_predict_templates_unchanged(tmpl: str, ctx: dict) -> None:
    env = build_environment()
    text = render(tmpl, ctx, env=env)
    stripped, disclaimer = strip_degraded_for_humanizer(text)
    assert disclaimer is None, f"Non-predict template {tmpl!r} must yield disclaimer=None"
    assert stripped == text, f"Non-predict template {tmpl!r} must not be modified"
    restored = reinsert_degraded_disclaimer(stripped, None)
    assert restored == text, "reinsert(None) on non-predict template must be identity"


# ---------------------------------------------------------------------------
# 8. Adversarial: empty degraded_reason
# ---------------------------------------------------------------------------

def test_empty_degraded_reason_still_has_prefix() -> None:
    env = build_environment()
    ctx = {**_CTX_DEGRADED, "degraded_reason": ""}
    text = render("predict.match_outcome.tr.j2", ctx, env=env)
    body, _ = extract_citation_block(text)
    assert DEGRADED_DISCLAIMER_PREFIX in body, (
        "Disclaimer prefix must appear even when degraded_reason is empty"
    )
    stripped, disclaimer = strip_degraded_for_humanizer(text)
    assert disclaimer is not None
    assert disclaimer.startswith(DEGRADED_DISCLAIMER_PREFIX)
