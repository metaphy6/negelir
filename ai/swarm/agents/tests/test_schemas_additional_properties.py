"""Pre-Phase-6 audit SK1: every shipped schema must explicitly
declare `additionalProperties` at the root.

The validator default flipped from `True` to `False` (closed by
default) — but defaults are easy to miss in review. This contract
test enforces the stricter rule: every schema must say so out
loud, so changes to the default cannot silently re-loosen the
contract.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

_SCHEMA_DIR = Path(__file__).resolve().parents[2] / "sdk" / "schemas"


def _schema_files() -> list[Path]:
    return sorted(p for p in _SCHEMA_DIR.glob("*.json") if p.is_file())


@pytest.mark.parametrize("path", _schema_files(), ids=lambda p: p.name)
def test_schema_declares_additional_properties(path: Path) -> None:
    schema = json.loads(path.read_text(encoding="utf-8"))
    assert "additionalProperties" in schema, (
        f"{path.name}: must explicitly declare additionalProperties "
        f"(SK1 — closed-by-default contract)"
    )
    # We don't force the value: contract evolution sometimes wants
    # an open envelope. But the choice must be deliberate.
    assert isinstance(schema["additionalProperties"], (bool, dict))
