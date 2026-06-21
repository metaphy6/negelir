"""Phase 10 §10.10 — graceful degradation matrix coverage."""

from __future__ import annotations

import pathlib
import yaml


DATA_PATH = pathlib.Path("ai/nlp/data/degradation_matrix.yaml")
TEMPLATES_DIR = pathlib.Path("ai/nlp/templates")


def _load_available_meta_reason_codes() -> set[str]:
    result: set[str] = set()
    for tpl_path in TEMPLATES_DIR.glob("*.tr.j2"):
        if tpl_path.name.startswith("meta."):
            result.add(tpl_path.name[: -len(".tr.j2")])
    return result


def test_degradation_matrix_every_failure_class_has_user_visible_template() -> None:
    raw = yaml.safe_load(DATA_PATH.read_text(encoding="utf-8"))
    assert isinstance(raw, dict), f"{DATA_PATH} must contain a YAML mapping"

    entries = raw.get("failure_classes")
    assert isinstance(entries, list), f"{DATA_PATH} must contain a top-level failure_classes list"
    assert entries, f"{DATA_PATH}.failure_classes must not be empty"

    allowed_reason_codes = _load_available_meta_reason_codes()
    assert allowed_reason_codes, "No meta.* templates found in ai/nlp/templates"

    missing_templates: list[str] = []
    missing_reason_codes: list[str] = []
    invalid_ids: list[str] = []

    for entry in entries:
        if not isinstance(entry, dict):
            invalid_ids.append(str(entry))
            continue

        failure_id = entry.get("id")
        template_name = entry.get("template_name")
        reason_code = entry.get("reason_code")

        if not isinstance(failure_id, str) or not failure_id:
            invalid_ids.append(str(entry))
            continue

        if not isinstance(template_name, str) or not template_name.endswith(".tr.j2"):
            missing_templates.append(str(entry))
            continue

        template_path = TEMPLATES_DIR / template_name
        if not template_path.is_file():
            missing_templates.append(template_name)

        if not isinstance(reason_code, str) or not reason_code.startswith("meta."):
            missing_reason_codes.append(f"{failure_id}: invalid reason_code {reason_code!r}")
            continue

        if reason_code not in allowed_reason_codes:
            missing_reason_codes.append(f"{failure_id}: {reason_code!r}")

    assert not invalid_ids, (
        "Invalid degradation_matrix entries; each failure class must be a mapping with a non-empty id, template_name, and reason_code:\n"
        + "\n".join(f"  {item}" for item in invalid_ids)
    )
    assert not missing_templates, (
        "Missing or invalid Turkish template files for degradation matrix entries:\n"
        + "\n".join(f"  {item}" for item in sorted(missing_templates))
    )
    assert not missing_reason_codes, (
        "Missing or invalid meta.* reason codes for degradation matrix entries:\n"
        + "\n".join(f"  {item}" for item in sorted(missing_reason_codes))
    )
