from __future__ import annotations

import pathlib
import jinja2
from jinja2 import meta

from nlp import render_format
from nlp.render import build_environment, render as nlp_render
from nlp.render_format import render


def _extract_template_variables(path: pathlib.Path) -> set[str]:
    source = path.read_text(encoding="utf-8")
    env = jinja2.Environment()
    ast = env.parse(source)
    return meta.find_undeclared_variables(ast)


def test_render_format_dispatches_to_format_specific_template_dir() -> None:
    text = render(
        {
            "template_name": "meta.unsupported.tr.j2",
            "context": {"suggestions": ["Bu bir test önerisidir"]},
        },
        answer_format="plain",
    )

    assert "Bu bir test önerisidir" in text


def test_format_unsupported_returns_meta_template(monkeypatch) -> None:
    import ai.common.config as config

    monkeypatch.setattr(
        config.cfg,
        "_nlp_answer_format_enabled_raw",
        '{"plain": true, "markdown_safe": true, "screen_reader": true, "whatsapp_4096": false, "sms_160": false, "tts_neutral": false}',
    )

    text = nlp_render(
        "meta.unsupported.tr.j2",
        {},
        answer_format="whatsapp_4096",
    )

    assert "Üzgünüm" in text
    assert "desteklenmiyor" in text


def test_nlp_per_format_templates_share_slots() -> None:
    base = pathlib.Path("ai/nlp/templates")
    formats = ["plain", "markdown_safe", "screen_reader"]
    dirs = [base / fmt for fmt in formats]
    common_names = set(dirs[0].glob("*.tr.j2"))
    expected_names = {p.name for p in common_names}

    for fmt_dir in dirs[1:]:
        missing = sorted(expected_names - {p.name for p in fmt_dir.glob("*.tr.j2")})
        assert not missing, f"Missing templates in {fmt_dir}: {missing}"

    for template_name in sorted(expected_names):
        slot_sets = [
            _extract_template_variables(fmt_dir / template_name)
            for fmt_dir in dirs
        ]
        assert slot_sets[0] == slot_sets[1] == slot_sets[2], (
            f"Slot mismatch in {template_name}: "
            f"{dict(zip(formats, slot_sets))}"
        )


def test_nlp_screen_reader_format_strips_all_emoji(tmp_path: pathlib.Path) -> None:
    sample_dir = tmp_path / "templates"
    sample_dir.mkdir()
    sample_template = sample_dir / "screen_reader_emoji.tr.j2"
    sample_template.write_text(
        "Tahmin % 67 ✓ ⚽ 🏟️ ▶\n",
        encoding="utf-8",
    )

    env = build_environment(template_dir=sample_dir)
    text = nlp_render(
        "screen_reader_emoji.tr.j2",
        {},
        env=env,
        answer_format="screen_reader",
    )

    assert "✓" not in text
    assert "⚽" not in text
    assert "🏟️" not in text
    assert "▶" not in text
    assert "evet" in text


def test_nlp_screen_reader_renders_percent_as_words(tmp_path: pathlib.Path) -> None:
    sample_dir = tmp_path / "templates"
    sample_dir.mkdir()
    sample_template = sample_dir / "screen_reader_percent.tr.j2"
    sample_template.write_text(
        "Tahmin %67\n",
        encoding="utf-8",
    )

    env = build_environment(template_dir=sample_dir)
    text = nlp_render(
        "screen_reader_percent.tr.j2",
        {},
        env=env,
        answer_format="screen_reader",
    )

    assert "yüzde 67" in text


def test_nlp_plain_format_strips_all_emoji_by_default(tmp_path: pathlib.Path, monkeypatch) -> None:
    sample_dir = tmp_path / "templates"
    sample_dir.mkdir()
    plain_dir = sample_dir / "plain"
    plain_dir.mkdir()
    sample_template = plain_dir / "plain_emoji.tr.j2"
    sample_template.write_text(
        "Galatasaray ⚽ kazandı ✓\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(render_format, "_TEMPLATES_BASE", sample_dir)

    text = render(
        {
            "template_name": "plain_emoji.tr.j2",
            "context": {},
        },
        answer_format="plain",
    )

    assert "⚽" not in text
    assert "✓" not in text
    assert "Galatasaray" in text


def test_nlp_markdown_safe_strips_all_emoji_by_default(tmp_path: pathlib.Path, monkeypatch) -> None:
    sample_dir = tmp_path / "templates"
    sample_dir.mkdir()
    markdown_dir = sample_dir / "markdown_safe"
    markdown_dir.mkdir()
    sample_template = markdown_dir / "markdown_safe_emoji.tr.j2"
    sample_template.write_text(
        "<b>Skor</b> ⚽ ✓\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(render_format, "_TEMPLATES_BASE", sample_dir)

    text = render(
        {
            "template_name": "markdown_safe_emoji.tr.j2",
            "context": {},
        },
        answer_format="markdown_safe",
    )

    assert "⚽" not in text
    assert "✓" not in text
    assert "&lt;b&gt;" in text


def test_nlp_screen_reader_format_normalizes_combining_marks(tmp_path: pathlib.Path) -> None:
    sample_dir = tmp_path / "templates"
    sample_dir.mkdir()
    sample_template = sample_dir / "screen_reader_combining.tr.j2"
    sample_template.write_text(
        "ȧ ȩ ✓\n",
        encoding="utf-8",
    )

    env = build_environment(template_dir=sample_dir)
    text = nlp_render(
        "screen_reader_combining.tr.j2",
        {},
        env=env,
        answer_format="screen_reader",
    )

    assert "̇" not in text
    assert "̧" not in text
    assert "✓" not in text
    assert "evet" in text


def test_nlp_markdown_safe_no_inline_html(tmp_path: pathlib.Path) -> None:
    sample_dir = tmp_path / "templates"
    sample_dir.mkdir()
    sample_template = sample_dir / "markdown_safe_inline_html.tr.j2"
    sample_template.write_text(
        "HTML etiketi <b>yasak</b> metin\n",
        encoding="utf-8",
    )

    env = build_environment(template_dir=sample_dir)
    text = nlp_render(
        "markdown_safe_inline_html.tr.j2",
        {},
        env=env,
        answer_format="markdown_safe",
    )

    assert "<b>" not in text
    assert "</b>" not in text
    assert "&lt;b&gt;" in text
    assert "yasak" in text
