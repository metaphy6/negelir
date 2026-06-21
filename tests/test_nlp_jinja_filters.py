"""Phase 10 \u00a710.7 \u2014 Tests for the Jinja2 render environment and Turkish filters.

Covers:
- build_environment() returns an Environment with autoescape=False,
  StrictUndefined, all expected filters registered.
- confidence_band filter/global uses the correct 3-band defaults.
- kickoff_time global formats datetime correctly.
- match_label uses en-dash.
- Turkish case suffixes (dative, locative, ablative, accusative, genitive,
  plural) on a selection of back-vowel and front-vowel stems.
- render() on predict.match_outcome.tr.j2 with a complete context succeeds.
- render() on predict.match_outcome.tr.j2 with a missing required slot falls
  back to meta.unsupported (no raise).
- render() with StrictUndefined raises UndefinedError when accessed directly
  from the environment (adversarial path).
"""
from __future__ import annotations

import ast
import datetime as dt
import inspect
import math
import sys
import pathlib

import pytest

# Ensure ai/ is on the path.
_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "ai"))

import jinja2  # noqa: E402

from common.config import cfg  # noqa: E402
from nlp.jinja_filters_tr import (  # noqa: E402
    dative,
    accusative,
    locative,
    ablative,
    genitive,
    plural,
    kickoff_time,
    match_label,
    confidence_band,
    FILTERS,
)
from nlp.render import build_environment, render  # noqa: E402


# \u2500\u2500 Environment smoke tests \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500

def test_env_autoescape_off():
    env = build_environment()
    assert env.autoescape is False


def test_env_strict_undefined():
    env = build_environment()
    assert env.undefined is jinja2.StrictUndefined


def test_env_all_filters_registered():
    env = build_environment()
    required = {"dative", "accusative", "locative", "ablative", "genitive",
                "plural", "kickoff_time", "match_label", "number_tr",
                "money_tr", "clock_tr", "date_tr", "date_tr_short",
                "score_tr", "confidence_band"}
    missing = required - set(env.filters)
    assert not missing, f"Missing Jinja2 filters: {missing}"


def test_env_confidence_band_global():
    """confidence_band must also be a Jinja2 global (templates call it as a function)."""
    env = build_environment()
    assert "confidence_band" in env.globals


def test_env_kickoff_time_global():
    """kickoff_time must also be a Jinja2 global (templates call it as a function)."""
    env = build_environment()
    assert "kickoff_time" in env.globals


# \u2500\u2500 confidence_band filter \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500

@pytest.mark.parametrize("prob,expected", [
    (0.0,  "d\u00fc\u015f\u00fck"),
    (0.3,  "d\u00fc\u015f\u00fck"),
    (0.54, "d\u00fc\u015f\u00fck"),
    (0.55, "orta"),
    (0.60, "orta"),
    (0.74, "orta"),
    (0.75, "y\u00fcksek"),
    (0.99, "y\u00fcksek"),
    (1.0,  "y\u00fcksek"),  # edge: 1.0 falls through exclusive upper bound of last band
])
def test_confidence_band_default_bands(prob, expected):
    assert confidence_band(prob) == expected


def test_confidence_band_boundary_semantics_regression():
    """Half-open default intervals must stay stable at 0.55 and 0.75 boundaries."""
    lower = 0.55
    upper = 0.75
    assert confidence_band(math.nextafter(lower, 0.0)) == "d\u00fc\u015fük"
    assert confidence_band(lower) == "orta"
    assert confidence_band(math.nextafter(lower, 1.0)) == "orta"
    assert confidence_band(math.nextafter(upper, 0.0)) == "orta"
    assert confidence_band(upper) == "yüksek"
    assert confidence_band(math.nextafter(upper, 1.0)) == "yüksek"


def test_nlp_band_boundary_intervals():
    """§10.21.10: canonical 8-point probe for half-open [low, mid, high] intervals."""
    probes = [
        (0.0, "düşük"),
        (0.5499, "düşük"),
        (0.55, "orta"),
        (0.5501, "orta"),
        (0.7499, "orta"),
        (0.75, "yüksek"),
        (0.7501, "yüksek"),
        (1.0, "yüksek"),
    ]
    for prob, expected in probes:
        assert confidence_band(prob) == expected, (
            f"confidence_band({prob}) -> {confidence_band(prob)!r}, expected {expected!r}"
        )


def test_nlp_confidence_band_default_comparator_ast():
    """Default confidence-band branch must use strict upper-bound `<` checks."""
    source = inspect.getsource(confidence_band)
    tree = ast.parse(source)

    func = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "confidence_band"
    )
    if_none = next(
        node
        for node in func.body
        if isinstance(node, ast.If)
        and isinstance(node.test, ast.Compare)
        and isinstance(node.test.left, ast.Name)
        and node.test.left.id == "bands"
    )

    first_cmp = if_none.body[0].test
    second_cmp = if_none.body[1].test

    assert isinstance(first_cmp, ast.Compare)
    assert isinstance(second_cmp, ast.Compare)
    assert isinstance(first_cmp.ops[0], ast.Lt)
    assert isinstance(second_cmp.ops[0], ast.Lt)
    assert isinstance(first_cmp.left, ast.Name) and first_cmp.left.id == "prob"
    assert isinstance(second_cmp.left, ast.Name) and second_cmp.left.id == "prob"


def test_nlp_band_signature_is_float():
    """Reject explicit numpy.float32 call sites for confidence_band in NLP runtime code."""
    nlp_root = _REPO_ROOT / "ai" / "nlp"
    runtime_files = sorted(
        path
        for path in nlp_root.rglob("*.py")
        if "tests" not in path.parts
    )

    offenders: list[str] = []

    def _is_np_float32(expr: ast.AST) -> bool:
        if not isinstance(expr, ast.Call):
            return False
        func = expr.func
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            return func.value.id in {"np", "numpy"} and func.attr == "float32"
        return False

    for file_path in runtime_files:
        tree = ast.parse(file_path.read_text(encoding="utf-8"), filename=str(file_path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue

            func = node.func
            called_confidence_band = (
                isinstance(func, ast.Name) and func.id == "confidence_band"
            ) or (
                isinstance(func, ast.Attribute) and func.attr == "confidence_band"
            )
            if not called_confidence_band:
                continue

            if node.args and _is_np_float32(node.args[0]):
                offenders.append(f"{file_path}:{node.lineno}")
                continue

            for keyword in node.keywords:
                if keyword.arg == "prob" and _is_np_float32(keyword.value):
                    offenders.append(f"{file_path}:{node.lineno}")
                    break

    assert not offenders, (
        "confidence_band must not receive numpy.float32; use float64 flow instead. "
        f"Offenders: {offenders}"
    )


def test_confidence_band_custom_bands():
    bands = [[0.0, 0.5, "d\u00fc\u015f\u00fck"], [0.5, 1.01, "y\u00fcksek"]]
    assert confidence_band(0.4, bands) == "d\u00fc\u015f\u00fck"
    assert confidence_band(0.5, bands) == "y\u00fcksek"


def test_confidence_band_via_env_global():
    env = build_environment()
    result = env.globals["confidence_band"](0.8)
    assert result == "y\u00fcksek"


# \u2500\u2500 kickoff_time filter \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500

def test_kickoff_time_datetime():
    # 2026-05-30T21:30Z is Sunday 00:30 in Europe/Istanbul.
    d = dt.datetime(2026, 5, 30, 21, 30, tzinfo=dt.timezone.utc)
    assert kickoff_time(d) == "Pazar 00:30"


def test_kickoff_time_iso_string():
    result = kickoff_time("2026-05-30T21:30:00Z")
    assert result == "Pazar 00:30"


def test_kickoff_time_uses_configured_render_timezone(monkeypatch):
    monkeypatch.setattr(cfg, "nlp_render_timezone", "UTC")
    d = dt.datetime(2026, 5, 30, 21, 30, tzinfo=dt.timezone.utc)
    assert kickoff_time(d) == "Cumartesi 21:30"


def test_kickoff_time_none():
    assert kickoff_time(None) == "Bilinmiyor"


def test_kickoff_time_all_weekdays():
    # Monday 2026-05-25 .. Sunday 2026-05-31
    expected = [
        "Pazartesi", "Sal\u0131", "\u00c7ar\u015famba", "Per\u015fembe",
        "Cuma", "Cumartesi", "Pazar",
    ]
    for i, name in enumerate(expected):
        d = dt.datetime(2026, 5, 25 + i, 10, 0, tzinfo=dt.timezone.utc)
        assert kickoff_time(d).startswith(name), f"weekday {i}: expected {name}"


# \u2500\u2500 match_label \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500

def test_match_label_en_dash():
    result = match_label("Galatasaray", "Fenerbah\u00e7e")
    assert "\u2013" in result, "match_label must use en-dash (U+2013)"
    assert result == "Galatasaray\u2013Fenerbah\u00e7e"


# \u2500\u2500 Turkish case suffix filters \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500

@pytest.mark.parametrize("word,expected", [
    # Back-vowel proper nouns (apostrophe, -a)
    ("Galatasaray", "Galatasaray'a"),
    # Front-vowel proper nouns (apostrophe, -e or -ye)
    ("Fenerbah\u00e7e", "Fenerbah\u00e7e'ye"),
    # Common noun back vowel
    ("masa", "masaya"),
    # Common noun front vowel ending in consonant
    ("\u015fehir", "\u015fehire"),
])
def test_dative(word, expected):
    assert dative(word) == expected


@pytest.mark.parametrize("word,expected", [
    ("Galatasaray", "Galatasaray'da"),
    ("Be\u015fkta\u015f", "Be\u015fkta\u015f'ta"),   # voiceless \u015f final
    ("Trabzonspor", "Trabzonspor'da"),
    ("ev", "evde"),
    ("araba", "arabada"),
])
def test_locative(word, expected):
    assert locative(word) == expected


@pytest.mark.parametrize("word,expected", [
    ("Galatasaray", "Galatasaray'dan"),
    ("Be\u015fkta\u015f", "Be\u015fkta\u015f'tan"),
    ("ev", "evden"),
    ("kap\u0131", "kap\u0131dan"),
])
def test_ablative(word, expected):
    assert ablative(word) == expected


@pytest.mark.parametrize("word,expected", [
    ("Galatasaray", "Galatasaray'\u0131"),
    ("Fenerbah\u00e7e", "Fenerbah\u00e7e'yi"),
    ("Trab\u00fczspor", "Trab\u00fczspor'u"),
    ("G\u00f6ztepe", "G\u00f6ztepe'yi"),  # front rounded -> \u00fc but vowel-final
])
def test_accusative(word, expected):
    assert accusative(word) == expected


@pytest.mark.parametrize("word,expected", [
    ("Galatasaray", "Galatasaray'\u0131n"),
    ("Fenerbah\u00e7e", "Fenerbah\u00e7e'nin"),
    ("ev", "evin"),
    ("araba", "araban\u0131n"),
])
def test_genitive(word, expected):
    assert genitive(word) == expected


@pytest.mark.parametrize("word,expected", [
    ("Galatasaray", "Galatasaray'lar"),
    ("Fenerbah\u00e7e", "Fenerbah\u00e7e'ler"),
    ("ev", "evler"),
    ("araba", "arabalar"),
])
def test_plural(word, expected):
    assert plural(word) == expected


# \u2500\u2500 render() integration \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500

_MATCH_OUTCOME_CTX = {
    "home_team": "Galatasaray",
    "away_team": "Fenerbah\u00e7e",
    "outcome_label": "Galatasaray kazan\u0131r",
    "probability": 0.78,
    "kickoff_utc": dt.datetime(2026, 5, 30, 20, 0, tzinfo=dt.timezone.utc),
    "degraded": False,
    "prediction_id": "pred-test-1",
    "produced_at_utc": "2026-05-27T10:00:00.000000Z",
    "model_versions": ["predictor-v1"],
    "calibration_version": "cal-v1",
}


def test_render_predict_match_outcome():
    env = build_environment()
    result = render("predict.match_outcome.tr.j2", _MATCH_OUTCOME_CTX, env=env)
    assert "Galatasaray" in result
    assert "y\u00fcksek" in result           # confidence band for 0.78
    assert "Cumartesi" in result              # weekday from kickoff_time
    assert "pred-test-1" in result            # citation block


def test_render_missing_slot_falls_back_to_unsupported():
    """Missing required slot must NOT raise; must return meta.unsupported text."""
    env = build_environment()
    result = render("predict.match_outcome.tr.j2", {}, env=env)
    # meta.unsupported always contains this phrase
    assert "yan\u0131tlayam\u0131yorum" in result or "\u00dczg\u00fcn\u00fcm" in result


def test_render_meta_unsupported_no_suggestions():
    env = build_environment()
    result = render("meta.unsupported.tr.j2", {}, env=env)
    assert "\u00dczg\u00fcn\u00fcm" in result


def test_render_degraded_flag_shown():
    """When degraded=True the template must include the disclaimer."""
    env = build_environment()
    ctx = {**_MATCH_OUTCOME_CTX, "degraded": True, "degraded_reason": "eksik veri"}
    result = render("predict.match_outcome.tr.j2", ctx, env=env)
    assert "s\u0131n\u0131rl\u0131" in result   # "sınırlı" in degraded disclaimer


def test_render_strict_undefined_from_template_object():
    """Adversarial: directly accessing an undefined variable on a template raises."""
    env = build_environment()
    tmpl = env.from_string("{{ no_such_var }}")
    with pytest.raises(jinja2.UndefinedError):
        tmpl.render()


def test_filters_dict_complete():
    required = {"dative", "accusative", "locative", "ablative", "genitive",
                "plural", "kickoff_time", "match_label", "confidence_band"}
    assert required.issubset(set(FILTERS)), (
        f"FILTERS missing: {required - set(FILTERS)}"
    )
