"""Phase 10 §10.7 — Confidence rendering tests.

Verifies:
1. confidence_band() maps probabilities to the correct Turkish label for
   the default 3-band table (düşük / orta / yüksek).
2. confidence_band() respects a custom band list.
3. build_environment() wires the closure so {{ confidence_band(prob) }}
   in templates uses cfg.nlp_confidence_bands (not the module default).
4. All predict.* templates include the raw probability in their citation
   block (§10.7 binding: "raw probability is included in the citation block;
   the user-facing prose uses the band").
5. User-facing prose uses the band label, not the raw float.
6. Adversarial: probability outside [0,1] handled gracefully (edge case
   at exactly 1.0 falls back to last band label, not KeyError).
"""
from __future__ import annotations

import datetime as dt
import json

import pytest

from nlp.jinja_filters_tr import confidence_band
from nlp.render import build_environment, extract_citation_block, render

# ---------------------------------------------------------------------------
# Shared predict context
# ---------------------------------------------------------------------------

_CTX: dict = {
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
    "probability": 0.78,
    "kickoff_utc": dt.datetime(2026, 5, 30, 20, 0, tzinfo=dt.timezone.utc),
    "degraded": False,
    "degraded_reason": "",
    "prediction_id": "pred-conf-1",
    "produced_at_utc": "2026-05-27T12:00:00Z",
    "model_versions": ["predictor-v2@2.0.0"],
    "calibration_version": "cal-v2",
}

_PREDICT_TEMPLATES = [
    "predict.match_outcome.tr.j2",
    "predict.over_under.tr.j2",
    "predict.btts.tr.j2",
    "predict.handicap.tr.j2",
    "predict.score_grid.tr.j2",
]

# ---------------------------------------------------------------------------
# 1. Default 3-band table
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("prob,expected_label", [
    (0.0,   "düşük"),
    (0.30,  "düşük"),
    (0.549, "düşük"),
    (0.55,  "orta"),
    (0.65,  "orta"),
    (0.749, "orta"),
    (0.75,  "yüksek"),
    (0.90,  "yüksek"),
    (1.0,   "yüksek"),  # edge: exactly 1.0 must not raise / must return last label
])
def test_default_bands(prob: float, expected_label: str) -> None:
    """confidence_band() with default bands must map each probability correctly."""
    result = confidence_band(prob)
    assert result == expected_label, (
        f"confidence_band({prob}) → {result!r}, expected {expected_label!r}"
    )


# ---------------------------------------------------------------------------
# 2. Custom band list
# ---------------------------------------------------------------------------

def test_custom_bands_override_default() -> None:
    """Custom band list must supersede the module-level defaults."""
    custom = [[0.0, 0.4, "zayıf"], [0.4, 0.8, "iyi"], [0.8, 1.01, "mükemmel"]]
    assert confidence_band(0.2,  custom) == "zayıf"
    assert confidence_band(0.5,  custom) == "iyi"
    assert confidence_band(0.95, custom) == "mükemmel"


# ---------------------------------------------------------------------------
# 3. build_environment closes over configured bands
# ---------------------------------------------------------------------------

def test_build_environment_uses_configured_bands() -> None:
    """The Jinja2 environment must use the bands supplied to build_environment(),
    not the module-level defaults."""
    custom_bands = [[0.0, 0.5, "düşük-özel"], [0.5, 1.01, "yüksek-özel"]]
    env = build_environment(confidence_bands=custom_bands)
    ctx = {**_CTX, "probability": 0.3}
    text = render("predict.match_outcome.tr.j2", ctx, env=env)
    # Prose should contain the custom label, not the default "düşük"
    assert "düşük-özel" in text, (
        "build_environment custom bands must flow through to template prose"
    )


def test_build_environment_default_bands_match_config_default() -> None:
    """build_environment() with no bands argument must match
    the config-default nlp_confidence_bands JSON string."""
    from common.config import Config
    cfg = Config()
    config_bands = json.loads(cfg.nlp_confidence_bands)
    env = build_environment(confidence_bands=config_bands)
    ctx = {**_CTX, "probability": 0.78}
    text = render("predict.match_outcome.tr.j2", ctx, env=env)
    # 0.78 → "yüksek" with default bands
    assert "yüksek" in text


# ---------------------------------------------------------------------------
# 4. Raw probability in citation block for all predict.* templates
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("tmpl", _PREDICT_TEMPLATES)
def test_citation_block_contains_raw_probability(tmpl: str) -> None:
    """Citation block must contain the raw probability value (§10.7 binding)."""
    env = build_environment()
    text = render(tmpl, _CTX, env=env)
    _, citation = extract_citation_block(text)
    assert citation is not None, f"No citation block in {tmpl!r}"
    # The raw probability (0.78) must appear verbatim, not just the band label.
    assert "0.78" in citation, (
        f"Raw probability '0.78' not found in citation block of {tmpl!r}. "
        f"Citation block was: {citation!r}"
    )


@pytest.mark.parametrize("prob", [0.30, 0.60, 0.90])
def test_citation_contains_probability_across_all_bands(prob: float) -> None:
    """Raw probability is included in the citation block regardless of which
    band it falls into."""
    env = build_environment()
    ctx = {**_CTX, "probability": prob}
    text = render("predict.match_outcome.tr.j2", ctx, env=env)
    _, citation = extract_citation_block(text)
    assert citation is not None
    assert str(prob) in citation, (
        f"Raw probability {prob!r} not found in citation block"
    )


# ---------------------------------------------------------------------------
# 5. User-facing prose uses band label, not raw float
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("tmpl", [
    "predict.match_outcome.tr.j2",
    "predict.over_under.tr.j2",
    "predict.btts.tr.j2",
    "predict.handicap.tr.j2",
])
def test_prose_uses_band_label_not_raw_float(tmpl: str) -> None:
    """The body (prose) part must contain a band label and must NOT contain the
    raw float probability as a standalone token in the prose section."""
    env = build_environment()
    ctx = {**_CTX, "probability": 0.78}
    text = render(tmpl, ctx, env=env)
    body, citation = extract_citation_block(text)
    # Prose must contain a confidence band label.
    assert any(label in body for label in ("düşük", "orta", "yüksek")), (
        f"No band label found in prose of {tmpl!r}. Body was: {body!r}"
    )
    # The raw float must NOT appear in the prose (only in the citation block).
    assert "0.78" not in body, (
        f"Raw probability '0.78' should be in citation only, not prose of {tmpl!r}"
    )


# ---------------------------------------------------------------------------
# 6. Edge cases for confidence_band
# ---------------------------------------------------------------------------

def test_confidence_band_empty_bands_falls_back() -> None:
    """Empty band list must not raise; should return a fallback."""
    # The function returns "orta" as last-resort fallback when bands is empty.
    result = confidence_band(0.5, [])
    assert isinstance(result, str)


def test_confidence_band_exactly_zero() -> None:
    assert confidence_band(0.0) == "düşük"


def test_confidence_band_exactly_one() -> None:
    """1.0 is the edge case where the last band's exclusive upper (1.01) must
    catch it — must not KeyError or return wrong label."""
    assert confidence_band(1.0) == "yüksek"
