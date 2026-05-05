"""Phase 7 §7.4 — Open-enum discipline tests.

`sec.alert.v1.kind` is an *open enum* on the wire (consumers tolerate
unknown kinds and route by `severity`) but a *closed* set at producer
emission sites. The hand-rolled JSON Schema validator in
`ai/swarm/sdk/schemas/__init__.py` only enforces the kebab-pattern
at the wire boundary; this test enforces the producer-side closed set
via an AST scan.

Two complementary properties:

  1. **Producer side**: every `SecAlert(...)` constructor call in the
     repo must pass a `kind=` argument that is either a `KNOWN_SEC_ALERT_KINDS`
     literal or a name re-exported from `payloads.py` (the
     `KNOWN_SEC_ALERT_KINDS` frozenset itself, used in pattern guards
     elsewhere). This test scans `ai/swarm/agents/` Python source.
     Tests files are ignored — they may legitimately exercise the
     consumer-tolerance branch with synthetic future kinds.

  2. **Consumer side**: a SecAlert payload with a kind not in
     `KNOWN_SEC_ALERT_KINDS` but matching the kebab pattern must
     pass schema validation (proves `additionalProperties: false`
     does not accidentally reject unknown kinds — the wire enum
     stays open).

Until the §7.1-7.3 agents land, there are no production emission
sites, so the AST scan is necessarily vacuous. The scan is wired now
so that the moment the first `SecAlert(...)` literal lands, the
guard is already in force — this is the same pattern used for the
`SINGLE_INSTANCE_AGENTS` frozenset in bootstrap.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

from swarm.agents.payloads import (
    KNOWN_SEC_ALERT_KINDS,
    SecAlert,
)
from swarm.sdk.schemas import validate

_AGENTS_DIR = Path(__file__).resolve().parents[1]
# Walk only production agent code; tests are intentionally exempt.
_PROD_FILES = [
    p for p in _AGENTS_DIR.rglob("*.py")
    if "tests" not in p.parts and p.name != "__init__.py"
]


def _kind_literal_from_call(call: ast.Call) -> str | None:
    """Return the `kind=` literal passed to a `SecAlert(...)` call, or
    None if the call does not use a string literal (e.g. computed
    via a variable that is itself constrained — out of scope for
    this scan; we only flag literal drift)."""
    if not isinstance(call.func, ast.Name) or call.func.id != "SecAlert":
        return None
    for kw in call.keywords:
        if kw.arg == "kind" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
            return kw.value.value
    return None


def test_producer_sites_emit_only_known_sec_alert_kinds() -> None:
    """Every `SecAlert(kind="literal")` in production code must use a
    `KNOWN_SEC_ALERT_KINDS` value."""
    offending: list[tuple[str, int, str]] = []
    for src in _PROD_FILES:
        try:
            tree = ast.parse(src.read_text(encoding="utf-8"))
        except SyntaxError:
            # Skip — separate syntax-check tests already cover this.
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                lit = _kind_literal_from_call(node)
                if lit is not None and lit not in KNOWN_SEC_ALERT_KINDS:
                    offending.append((str(src), node.lineno, lit))
    assert not offending, (
        "SecAlert(kind=...) emission sites must use KNOWN_SEC_ALERT_KINDS;"
        " unknown literals found:\n  "
        + "\n  ".join(f"{p}:{ln} kind={k!r}" for p, ln, k in offending)
    )


def test_consumer_accepts_unknown_sec_alert_kind_round_trip() -> None:
    """Wire schema must tolerate kinds outside `KNOWN_SEC_ALERT_KINDS`
    so consumers can round-trip future producer additions without a
    coordinated deploy. The kebab pattern is the only gate."""
    future_kind = "future_unknown_kind_v999"
    assert future_kind not in KNOWN_SEC_ALERT_KINDS, (
        "test would be vacuous if this leaked into the known set"
    )
    payload = SecAlert(
        alert_id="alert-future",
        kind=future_kind,
        severity="info",
        source="sec.input.v1",
        reason="forward-compat round-trip test",
        produced_at="2026-04-28T12:00:00+00:00",
    ).as_dict()
    errors = validate("sec.alert.v1", payload)
    assert not errors, f"future kind rejected: {errors}"


def test_sec_alert_kind_pattern_anchors_open_enum_shape() -> None:
    """The `^[a-z][a-z0-9_]{0,63}$` shape is the ONLY producer-side
    structural constraint on `kind` (no metric labels, no spaces, no
    capital letters → log-injection + cardinality safe)."""
    pattern = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
    for kind in KNOWN_SEC_ALERT_KINDS:
        assert pattern.match(kind), f"KNOWN_SEC_ALERT_KINDS member {kind!r} violates kebab shape"


def test_retired_phase7_knobs_do_not_creep_back() -> None:
    """The streaming-statistic baseline (Welford / P² / count-min)
    in `sec.scrape.v1` deliberately replaces the capped-LRU baseline.
    The `sec_scrape_baseline_max_per_source` knob from the §7.2
    pre-pivot draft must not leak back into config — its presence
    would imply a regression to the bounded-cardinality baseline.
    """
    from common import config as _cfg
    # Look for the name as either a dataclass field or an env-var
    # reference — both would be smoking guns. The comment block in
    # config.py that explains *why* the knob was retired uses the
    # name in prose (intentional regression marker) and must not
    # itself trip the gate; the regexes below ignore comment context.
    src_lines = Path(_cfg.__file__).read_text(encoding="utf-8").splitlines()
    field_re = re.compile(r"^\s*sec_scrape_baseline_max_per_source\s*:")
    env_re = re.compile(r"NEGELIR_SEC_SCRAPE_BASELINE_MAX_PER_SOURCE")
    offenders = [
        (i + 1, line)
        for i, line in enumerate(src_lines)
        if field_re.match(line) or env_re.search(line)
    ]
    assert not offenders, (
        "retired knob `sec_scrape_baseline_max_per_source` must not "
        "reappear in config.py as a field or env reference — the "
        "streaming-statistic baseline supersedes it (ROADMAP §7.2). "
        f"Offending lines: {offenders}"
    )


# ── F7.9 / P8 — registry exhaustiveness ───────────────────────────


def test_open_enum_registry_is_exhaustive_over_schema_directory() -> None:
    """F7.9 (P8): every JSON Schema field tagged ``x-enum-open: true``
    must have a matching entry in ``OPEN_ENUM_REGISTRY``.

    This catches the failure mode where a schema author flips a new
    field to open-enum (lifting the wire constraint) but forgets to
    register the producer-side closed set. Without registration, the
    parametrized contract tests in this file silently exclude the new
    field, and a typoed producer literal would round-trip uncaught.

    The scan walks ``ai/swarm/sdk/schemas/*.json`` and recursively
    inspects every property for the ``x-enum-open`` marker. Schema
    file basename (without ``.json``) is the topic id.
    """
    import json
    from swarm.sdk.schemas.open_enum import OPEN_ENUM_REGISTRY

    schema_dir = Path(__file__).resolve().parents[3] / "swarm" / "sdk" / "schemas"
    registered: set[tuple[str, str]] = {(e.topic, e.field) for e in OPEN_ENUM_REGISTRY}

    declared: set[tuple[str, str]] = set()

    def _walk(node, *, topic: str, path: tuple[str, ...]) -> None:
        if isinstance(node, dict):
            if node.get("x-enum-open") is True and path:
                declared.add((topic, ".".join(path)))
            props = node.get("properties")
            if isinstance(props, dict):
                for name, sub in props.items():
                    _walk(sub, topic=topic, path=path + (name,))
            # Also descend into items (arrays of objects).
            items = node.get("items")
            if isinstance(items, dict):
                _walk(items, topic=topic, path=path)
        elif isinstance(node, list):
            for sub in node:
                _walk(sub, topic=topic, path=path)

    for schema_file in schema_dir.glob("*.json"):
        topic = schema_file.stem  # e.g. "sec.alert.v1"
        try:
            doc = json.loads(schema_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        _walk(doc, topic=topic, path=())

    missing = declared - registered
    assert not missing, (
        f"Schemas declare x-enum-open at {sorted(missing)} but "
        "OPEN_ENUM_REGISTRY does not list them. Either register the "
        "producer-side closed set in ai/swarm/sdk/schemas/open_enum.py "
        "or remove the x-enum-open marker from the schema."
    )
    # Also: every registered entry should still correspond to a real
    # x-enum-open declaration — guards against stale registry rows
    # outliving a schema renaming.
    stale = registered - declared
    assert not stale, (
        f"OPEN_ENUM_REGISTRY entries {sorted(stale)} have no matching "
        "x-enum-open: true field in the schemas directory. Update or "
        "remove the registry row."
    )
