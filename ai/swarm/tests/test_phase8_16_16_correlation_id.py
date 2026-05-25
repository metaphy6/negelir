"""Phase 8.16.16 — event_correlation_id schema field + dual_emit_correlation_id helper tests.

Covers:
  * dual_emit_correlation_id importable from swarm.sdk.payloads
  * Helper is deterministic and returns a 16-char hex string
  * sec.alert.v1.json carries schema_version property with 2 in the allowed set
  * sec.alert.v1.json has event_correlation_id field
  * maint.event.v1.json has event_correlation_id field (additive — schema_version unchanged)
  * AST scan: no code site outside payloads.py constructs event_correlation_id ad-hoc
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

# ── Constants ────────────────────────────────────────────────────────────

_SWARM_ROOT = Path(__file__).resolve().parent.parent  # ai/swarm/
_SCHEMAS_DIR = _SWARM_ROOT / "sdk" / "schemas"
_CANONICAL_PRODUCER = _SWARM_ROOT / "sdk" / "payloads.py"
_DUAL_EMIT_HELPER = _SWARM_ROOT / "sdk" / "_dual_emit_helper.py"

# Pattern for the internal sha256-slice that only the helper may use.
_SHA256_SLICE_RE = re.compile(r"sha256\b.*\[:16\]")

# ── Helper import and contract ────────────────────────────────────────────


def test_dual_emit_correlation_id_importable_from_payloads() -> None:
    from swarm.sdk.payloads import dual_emit_correlation_id  # noqa: F401


def test_dual_emit_correlation_id_deterministic() -> None:
    from swarm.sdk.payloads import dual_emit_correlation_id

    cid1 = dual_emit_correlation_id(
        kind="backup_verify_failed", target="pred.elo.v1", produced_at="2026-05-25T00:00:00Z"
    )
    cid2 = dual_emit_correlation_id(
        kind="backup_verify_failed", target="pred.elo.v1", produced_at="2026-05-25T00:00:00Z"
    )
    assert cid1 == cid2, "dual_emit_correlation_id must be deterministic"


def test_dual_emit_correlation_id_format() -> None:
    from swarm.sdk.payloads import dual_emit_correlation_id

    cid = dual_emit_correlation_id(
        kind="backup_verify_failed", target="pred.elo.v1", produced_at="2026-05-25T00:00:00Z"
    )
    assert re.fullmatch(r"[0-9a-f]{16}", cid), (
        f"dual_emit_correlation_id must return exactly 16 lowercase hex chars; got {cid!r}"
    )


def test_dual_emit_correlation_id_none_target() -> None:
    """target=None must not raise."""
    from swarm.sdk.payloads import dual_emit_correlation_id

    cid = dual_emit_correlation_id(
        kind="opsctl_signature_invalid", target=None, produced_at="2026-05-25T12:00:00Z"
    )
    assert re.fullmatch(r"[0-9a-f]{16}", cid)


# ── Schema field presence ─────────────────────────────────────────────────


def _load_schema(name: str) -> dict:
    path = _SCHEMAS_DIR / f"{name}.json"
    assert path.exists(), f"schema not found: {path}"
    return json.loads(path.read_text(encoding="utf-8"))


def test_sec_alert_v1_has_event_correlation_id() -> None:
    schema = _load_schema("sec.alert.v1")
    props = schema.get("properties", {})
    assert "event_correlation_id" in props, (
        "sec.alert.v1.json must declare event_correlation_id property"
    )


def test_maint_event_v1_has_event_correlation_id() -> None:
    schema = _load_schema("maint.event.v1")
    props = schema.get("properties", {})
    assert "event_correlation_id" in props, (
        "maint.event.v1.json must declare event_correlation_id property"
    )


def test_sec_alert_v1_schema_version_is_2() -> None:
    """sec.alert.v1 schema_version bumped to 2 in §8.16.16."""
    schema = _load_schema("sec.alert.v1")
    props = schema.get("properties", {})
    sv = props.get("schema_version", {})
    allowed = sv.get("enum", [])
    assert 2 in allowed, (
        f"sec.alert.v1.json schema_version enum must include 2 (§8.16.16 bump); got enum={allowed!r}"
    )


def test_maint_event_v1_schema_version_unchanged() -> None:
    """maint.event.v1 envelope-level schema_version must NOT be present
    (per-kind sub-schema carries kind_schema_version; the envelope is additive-only).
    """
    schema = _load_schema("maint.event.v1")
    props = schema.get("properties", {})
    assert "schema_version" not in props, (
        "maint.event.v1.json envelope must NOT carry a top-level schema_version; "
        "additive optional field is enough (per-kind sub-schemas own kind_schema_version)"
    )


# ── AST scan: no ad-hoc event_correlation_id derivation ──────────────────


def _files_to_scan() -> list[Path]:
    """All .py files under ai/swarm/, excluding the two canonical files."""
    canonical = {_CANONICAL_PRODUCER.resolve(), _DUAL_EMIT_HELPER.resolve()}
    return [
        p for p in _SWARM_ROOT.rglob("*.py")
        if p.resolve() not in canonical and "__pycache__" not in p.parts
    ]


def _is_dual_emit_call(node: ast.expr) -> bool:
    """Return True if node is a call to dual_emit_correlation_id."""
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    # direct name: dual_emit_correlation_id(...)
    if isinstance(func, ast.Name) and func.id == "dual_emit_correlation_id":
        return True
    # attribute: something.dual_emit_correlation_id(...)
    if isinstance(func, ast.Attribute) and func.attr == "dual_emit_correlation_id":
        return True
    return False


class _AdHocCorrelationVisitor(ast.NodeVisitor):
    """Collect subscript assignments where key='event_correlation_id'
    and the value is NOT a call to dual_emit_correlation_id.
    """

    def __init__(self, source: str) -> None:
        self.violations: list[int] = []  # line numbers

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            if (
                isinstance(target, ast.Subscript)
                and isinstance(target.slice, ast.Constant)
                and target.slice.value == "event_correlation_id"
                and not _is_dual_emit_call(node.value)
            ):
                self.violations.append(node.lineno)
        self.generic_visit(node)


def test_no_adhoc_event_correlation_id_derivation() -> None:
    """AST scan: outside payloads.py and _dual_emit_helper.py, no code site
    may assign dict["event_correlation_id"] to anything other than a call to
    dual_emit_correlation_id.
    """
    violations: list[str] = []
    for path in _files_to_scan():
        try:
            src = path.read_text(encoding="utf-8")
        except OSError:
            continue
        # Quick pre-filter: skip files that don't mention the key at all.
        if "event_correlation_id" not in src:
            continue
        try:
            tree = ast.parse(src, filename=str(path))
        except SyntaxError:
            continue
        visitor = _AdHocCorrelationVisitor(src)
        visitor.visit(tree)
        for lineno in visitor.violations:
            rel = path.relative_to(_SWARM_ROOT.parent.parent)
            violations.append(f"{rel}:{lineno}")

    assert not violations, (
        "Ad-hoc event_correlation_id construction detected outside the canonical helper.\n"
        "Use swarm.sdk.payloads.dual_emit_correlation_id() instead.\n"
        "Violations:\n" + "\n".join(f"  {v}" for v in violations)
    )
