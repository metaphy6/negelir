"""Phase 10 §10.29.1 — geminate restoration support."""
from __future__ import annotations

from pathlib import Path
from typing import Any, NamedTuple, Optional

import yaml

from ai.common.text.turkish import lowercase_tr

_DEFAULT_GEMINATE_RESTORATION_PATH: Path = (
    Path(__file__).parent / "lang_tr" / "spelling" / "geminate_restoration.tr.yaml"
)
_SCHEMA_VERSION = 1
_VOWELS = set("aeıioöuü")


class GeminateRestorationRule(NamedTuple):
    stem: str
    doubled_form: str
    source: str


class GeminateRestorationSchemaError(ValueError):
    """Raised when the geminate restoration YAML carries an unexpected schema version."""


def _load_yaml(path: Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    if not isinstance(raw, dict):
        raise GeminateRestorationSchemaError(
            f"{path.name}: expected a YAML mapping at top level"
        )
    version = int(raw.get("_meta", {}).get("schema_version", 0))
    if version != _SCHEMA_VERSION:
        raise GeminateRestorationSchemaError(
            f"{path.name}: expected schema_version={_SCHEMA_VERSION}, got {version}"
        )
    return raw


def load_geminate_restorations(
    path: Path | None = None,
) -> tuple[GeminateRestorationRule, ...]:
    actual_path = path or _DEFAULT_GEMINATE_RESTORATION_PATH
    raw = _load_yaml(actual_path)
    restorations: list[GeminateRestorationRule] = []
    for entry in raw.get("geminate_restorations", []):
        if not isinstance(entry, dict):
            continue
        stem = lowercase_tr(str(entry.get("stem", "")).strip())
        doubled_form = lowercase_tr(str(entry.get("doubled_form", "")).strip())
        source = str(entry.get("source", "manual"))
        if not stem or not doubled_form:
            raise ValueError(f"Invalid geminate restoration row: {entry}")
        if not doubled_form.startswith(stem):
            raise ValueError(
                f"geminate_restoration.tr.yaml: doubled_form {doubled_form!r} must start with stem {stem!r}"
            )
        if not doubled_form[len(stem) :].isalnum():
            # suffixes are not validated here; only the doubled stem prefix is required.
            pass
        restorations.append(
            GeminateRestorationRule(
                stem=stem,
                doubled_form=doubled_form,
                source=source,
            )
        )
    return tuple(restorations)


def _lookup_term(token: str, lookup: Any) -> Optional[str]:
    if lookup is None:
        return None
    candidate = lookup(token)
    if candidate is None:
        return None
    if isinstance(candidate, str):
        return candidate
    return getattr(candidate, "term", None)


def _is_vowel_initial_suffix(token: str, prefix: str) -> bool:
    if len(token) <= len(prefix):
        return False
    return token[len(prefix)] in _VOWELS


def restore_geminate(
    token: str,
    lookup: Any,
    restorations: tuple[GeminateRestorationRule, ...] | None = None,
) -> tuple[str, dict[str, str] | None]:
    if not token:
        return token, None
    restorations = restorations or load_geminate_restorations()
    for rule in restorations:
        if not token.startswith(rule.doubled_form):
            continue
        if not _is_vowel_initial_suffix(token, rule.doubled_form):
            continue
        if _lookup_term(token, lookup) is None:
            continue
        return (
            token,
            {
                "kind": "geminate_restoration",
                "original": token,
                "stem": rule.stem,
                "doubled_form": rule.doubled_form,
                "source": rule.source,
            },
        )
    return token, None
