from __future__ import annotations

import pathlib
import yaml

from nlp.render import build_environment, render

TEMPLATES_DIR = pathlib.Path("ai/nlp/templates")
TRANSLATIONS_PATH = pathlib.Path("ai/nlp/lang_tr/degraded_reasons.tr.yaml")


def test_summary_partial_template_renders_with_missing_fixtures() -> None:
    env = build_environment()
    text = render(
        "summary_partial.tr.j2",
        {
            "returned_count": 3,
            "total_count": 5,
            "missing_fixtures": [
                {
                    "label": "Galatasaray - Fenerbahçe",
                    "degraded_reason_tr": "Tahmin zaman aşımına uğradı",
                }
            ],
        },
        env=env,
    )

    assert "3/5 maç tahmini hazır" in text
    assert "Galatasaray - Fenerbahçe" in text
    assert "Tahmin zaman aşımına uğradı" in text


def test_summary_per_fixture_only_template_renders_with_missing_fixtures() -> None:
    env = build_environment()
    text = render(
        "summary_per_fixture_only.tr.j2",
        {
            "returned_count": 2,
            "total_count": 5,
            "missing_fixtures": [
                {
                    "label": "Fenerbahçe - Trabzonspor",
                    "degraded_reason_tr": "Tahmin zaman aşımına uğradı",
                }
            ],
        },
        env=env,
    )

    assert text.startswith("Tüm maçları kapsayan bir özet hazırlanamadı")
    assert "2/5 maç hazır" in text
    assert "Fenerbahçe - Trabzonspor" in text


def test_render_screen_reader_format_removes_decorative_characters(tmp_path: pathlib.Path) -> None:
    sample_dir = tmp_path / "templates"
    sample_dir.mkdir()
    sample_template = sample_dir / "screen_reader_sample.tr.j2"
    sample_template.write_text(
        "Tahmin %67 ✓ ⚽ ▶\n",
        encoding="utf-8",
    )

    env = build_environment(template_dir=sample_dir)
    text = render(
        "screen_reader_sample.tr.j2",
        {},
        env=env,
        answer_format="screen_reader",
    )

    assert "yüzde 67" in text
    assert "evet" in text
    assert "⚽" not in text
    assert "▶" not in text
    assert "✓" not in text


def test_degraded_reason_translation_table_covers_expected_reasons() -> None:
    data = yaml.safe_load(TRANSLATIONS_PATH.read_text(encoding="utf-8")) or {}
    assert isinstance(data, dict)

    expected = {
        "predict_timeout",
        "predict_unavailable",
        "data_lookup_failed",
        "calibration_mismatch_refused",
        "humanizer_tenant_budget_exceeded",
        "lexicon_safe_mode_active",
        "summary_quorum_missed_per_fixture_only",
        "summary quorum not met",
        "summary_quorum_zero_received",
        "summary calibration mismatch",
    }
    missing = sorted(expected - set(data))
    assert not missing, f"Missing degraded reason translations: {missing}"
