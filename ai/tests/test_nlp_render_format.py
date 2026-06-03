from __future__ import annotations

import pathlib
import jinja2
from jinja2 import meta

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
