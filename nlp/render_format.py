from __future__ import annotations

import pathlib
from typing import Any

from nlp.render import build_environment, render as _render

_ALLOWED_FORMATS = frozenset(
    {
        "plain",
        "markdown_safe",
        "screen_reader",
        "whatsapp_4096",
        "sms_160",
        "tts_neutral",
    }
)

_TEMPLATES_BASE = pathlib.Path(__file__).resolve().parent / "templates"


def _resolve_template_dir(answer_format: str) -> pathlib.Path:
    if answer_format not in _ALLOWED_FORMATS:
        raise ValueError(f"unsupported answer_format: {answer_format!r}")
    template_dir = _TEMPLATES_BASE / answer_format
    if not template_dir.is_dir():
        raise FileNotFoundError(f"template directory not found: {template_dir}")
    return template_dir


def render(answer_blocks: dict[str, Any], answer_format: str = "plain") -> str:
    """Render answer blocks using a format-specific template directory.

    Parameters
    ----------
    answer_blocks:
        Must contain ``template_name`` and an optional ``context`` dict.
    answer_format:
        One of ``plain``, ``markdown_safe``, ``screen_reader``,
        ``whatsapp_4096``, ``sms_160``, or ``tts_neutral``.
    """
    if not isinstance(answer_blocks, dict):
        raise TypeError("answer_blocks must be a dict")

    template_name = answer_blocks.get("template_name")
    if not isinstance(template_name, str):
        raise TypeError("answer_blocks must include a template_name string")

    context = answer_blocks.get("context", {})
    if not isinstance(context, dict):
        raise TypeError("answer_blocks context must be a dict")

    env = build_environment(template_dir=_resolve_template_dir(answer_format))
    return _render(
        template_name,
        context,
        env=env,
        answer_format=answer_format,
    )
