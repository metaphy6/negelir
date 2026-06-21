from __future__ import annotations

from pathlib import Path
from typing import Any, NamedTuple, Optional

import yaml

from common.text.turkish import lowercase_tr

_DEFAULT_LOANWORD_SINGULARISATION_PATH: Path = (
    Path(__file__).parent / "lang_tr" / "loanwords" / "loan_singularisation.tr.yaml"
)
_SCHEMA_VERSION = 1
_VALID_DECISIONS = {"singular", "plural", "both"}


class LoanwordSingularisationSchemaError(ValueError):
    pass


class LoanwordSingularisationRule(NamedTuple):
    loan_form: str
    accepted_plural: str
    decision: str
    source: str


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    if not isinstance(raw, dict):
        raise LoanwordSingularisationSchemaError(
            f"{path.name}: expected a YAML mapping at top level"
        )
    meta = raw.get("_meta")
    if not isinstance(meta, dict):
        raise LoanwordSingularisationSchemaError(
            f"{path.name}: missing or malformed _meta block"
        )
    version = meta.get("schema_version")
    if version != _SCHEMA_VERSION:
        raise LoanwordSingularisationSchemaError(
            f"{path.name}: expected schema_version={_SCHEMA_VERSION}, got {version!r}"
        )
    return raw


def load_loanword_singularisation_rules(
    path: Path | None = None,
) -> tuple[LoanwordSingularisationRule, ...]:
    actual_path = path or _DEFAULT_LOANWORD_SINGULARISATION_PATH
    if not actual_path.exists():
        return ()

    raw = _load_yaml(actual_path)
    entries = raw.get("loanword_singularisation", [])
    if not isinstance(entries, list):
        raise LoanwordSingularisationSchemaError(
            f"{actual_path.name}: missing required 'loanword_singularisation' list"
        )

    result: list[LoanwordSingularisationRule] = []
    seen: set[tuple[str, str]] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise LoanwordSingularisationSchemaError(
                f"{actual_path.name}: each entry must be a mapping"
            )
        loan_form = lowercase_tr(str(entry.get("loan_form", "")).strip())
        accepted_plural = lowercase_tr(str(entry.get("accepted_plural", "")).strip())
        decision = str(entry.get("decision", "")).strip().lower()
        source = str(entry.get("source", "manual")).strip() or "manual"

        if not loan_form or not accepted_plural or decision not in _VALID_DECISIONS:
            raise LoanwordSingularisationSchemaError(
                f"{actual_path.name}: invalid entry {entry!r}"
            )

        key = (loan_form, accepted_plural)
        if key in seen:
            raise LoanwordSingularisationSchemaError(
                f"{actual_path.name}: duplicate loanword singularisation entry {loan_form!r} / {accepted_plural!r}"
            )
        seen.add(key)

        result.append(
            LoanwordSingularisationRule(
                loan_form=loan_form,
                accepted_plural=accepted_plural,
                decision=decision,
                source=source,
            )
        )

    return tuple(result)


def _lookup_term(token: str, lookup: Any, exact_only: bool = False) -> Optional[str]:
    if lookup is None:
        return None
    candidate = lookup(token)
    if candidate is None:
        return None
    if isinstance(candidate, str):
        return candidate if not exact_only or candidate == token else None
    term = getattr(candidate, "term", None)
    if term is None:
        return None
    return term if not exact_only or term == token else None


def singularise_loanword_plural(
    token: str,
    lookup: Any,
    rules: tuple[LoanwordSingularisationRule, ...] | None = None,
) -> tuple[str, dict[str, str] | None]:
    if not token:
        return token, None

    exact_candidate = _lookup_term(token, lookup, exact_only=True)
    if exact_candidate == token:
        return token, None

    rules = rules or load_loanword_singularisation_rules()
    for rule in rules:
        if token != rule.accepted_plural:
            continue

        candidate = _lookup_term(rule.loan_form, lookup, exact_only=True)
        if candidate is not None:
            return (
                candidate,
                {
                    "kind": "loanword_singularised",
                    "original": token,
                    "repaired": candidate,
                    "loan_form": rule.loan_form,
                    "accepted_plural": rule.accepted_plural,
                    "decision": rule.decision,
                    "source": rule.source,
                },
            )

    return token, None
