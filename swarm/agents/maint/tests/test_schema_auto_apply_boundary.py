"""Phase 8 §8.6 binding-boundary tests for the
``maint.schema.v1`` sentinel.

Covers the *out-of-scope* checkbox: auto-applying migrations is
**not** part of Phase 8 — humans (or the Phase 17 patcher under
``migration`` scope) drive the fix. The
``cfg.maint_schema_auto_apply_enabled`` knob exists for forward
compatibility only:

1. Default is ``False`` (3-way config sync — config.py + defaults.yaml
   + .env.example).
2. When set to ``True``, the agent emits a loud one-shot warning at
   boot **and** queues a ``sec.alert.v1{
   kind=schema_auto_apply_misconfigured, severity=warn}`` message.
3. **AST boundary (Rule 7 adversarial):** the schema sentinel module
   must contain *no* auto-migration code path — no ``subprocess``
   import, no ``psql -f migrations/...`` strings, no DDL verbs in
   ``execute(...)`` calls. This locks the detect-only contract so a
   future patch wiring auto-apply is caught by CI, not by an
   operator at 03:00.
"""
from __future__ import annotations

import ast
import logging
import re
from pathlib import Path

import pytest

from common.config import Config, cfg as _cfg
from swarm.agents.maint.schema import MaintSchemaSentinel
from swarm.agents.payloads import KNOWN_SEC_ALERT_KINDS
from swarm.agents.topics import SEC_ALERT


SCHEMA_MODULE = Path(__file__).resolve().parents[1] / "schema.py"


# ── 1. Default is False ──────────────────────────────────────────


def test_maint_schema_auto_apply_default_false() -> None:
    """A freshly constructed Config (no env overrides) must report the
    auto-apply knob as False — Phase 8 is detect-only by default."""
    assert Config().maint_schema_auto_apply_enabled is False


def test_maint_schema_auto_apply_default_false_runtime() -> None:
    """The module-level singleton must also default to False so
    every importer sees the safe value."""
    assert _cfg.maint_schema_auto_apply_enabled is False


def test_default_construction_emits_no_boot_alerts() -> None:
    """With the knob at its default (False), the sentinel must boot
    silently — no warning, no sec.alert."""
    agent = MaintSchemaSentinel()
    assert agent.boot_alerts == []


# ── 2. Setting True surfaces the misconfiguration ────────────────


def test_known_kind_registered_for_misconfig_alert() -> None:
    """The open-enum kind we emit must be registered in
    KNOWN_SEC_ALERT_KINDS so consumers (sec.* aggregators, Phase 7
    routing) recognise it."""
    assert "schema_auto_apply_misconfigured" in KNOWN_SEC_ALERT_KINDS


def test_maint_schema_auto_apply_enabled_warns_at_boot(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Flipping ``cfg.maint_schema_auto_apply_enabled`` to True must:

    * log a WARNING through the ``swarm.agents.maint.schema`` logger
      whose body names the offending knob; AND
    * queue exactly one ``sec.alert.v1{
      kind=schema_auto_apply_misconfigured, severity=warn}`` message
      onto :attr:`MaintSchemaSentinel.boot_alerts` (one-shot, not
      debounced — the runner drains it on startup).
    """
    monkeypatch.setattr(
        _cfg, "maint_schema_auto_apply_enabled", True, raising=False
    )
    caplog.set_level(logging.WARNING, logger="swarm.agents.maint.schema")

    agent = MaintSchemaSentinel()

    # ── log assertion ──
    warnings = [
        rec
        for rec in caplog.records
        if rec.name == "swarm.agents.maint.schema"
        and rec.levelno == logging.WARNING
    ]
    assert len(warnings) == 1, (
        f"expected exactly one boot warning, got {len(warnings)}: "
        f"{[(r.name, r.levelname, r.getMessage()) for r in caplog.records]}"
    )
    msg = warnings[0].getMessage()
    assert "maint_schema_auto_apply_enabled" in msg
    assert "Phase 8 is detect-only" in msg

    # ── sec.alert assertion ──
    assert len(agent.boot_alerts) == 1, (
        f"expected exactly one boot sec.alert, got {len(agent.boot_alerts)}"
    )
    alert = agent.boot_alerts[0]
    assert alert.envelope.topic == SEC_ALERT
    assert alert.envelope.producer == "maint.schema.v1"
    assert alert.payload["kind"] == "schema_auto_apply_misconfigured"
    assert alert.payload["severity"] == "warn"
    assert alert.payload["source"] == "maint.schema.v1"
    assert alert.payload["subject"] == "cfg.maint_schema_auto_apply_enabled"


# ── 3. Adversarial — AST boundary (Rule 7) ───────────────────────


_DDL_VERBS = ("CREATE", "ALTER", "DROP", "TRUNCATE")


def _module_source() -> str:
    return SCHEMA_MODULE.read_text(encoding="utf-8")


def test_schema_module_has_no_subprocess_import() -> None:
    """No ``import subprocess`` (or ``from subprocess import ...``)
    anywhere in the schema sentinel module. Auto-applying a
    migration file would shell out to ``psql``; banning subprocess
    at the AST level kills that surface before it can land."""
    tree = ast.parse(_module_source(), filename=str(SCHEMA_MODULE))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith("subprocess"), (
                    f"subprocess import in {SCHEMA_MODULE.name} — Phase 8 "
                    f"is detect-only; auto-apply belongs in Phase 17."
                )
        elif isinstance(node, ast.ImportFrom):
            assert node.module != "subprocess", (
                f"`from subprocess import ...` in {SCHEMA_MODULE.name} — "
                f"Phase 8 is detect-only; auto-apply belongs in Phase 17."
            )


def test_schema_module_has_no_psql_or_migrations_string_literals() -> None:
    """Lock against any string literal that looks like a shell-out
    to ``psql`` or to ``migrations/...``. Belt-and-suspenders with
    the subprocess ban — if someone wires a ``Popen`` indirectly,
    the literals still trip this gate."""
    src = _module_source()
    psql_re = re.compile(r"\bpsql\b")
    migrations_flag_re = re.compile(r"-f\s+migrations\b")
    psql_hits = [m.group(0) for m in psql_re.finditer(src)]
    flag_hits = [m.group(0) for m in migrations_flag_re.finditer(src)]
    assert not psql_hits, (
        f"`psql` literal found in {SCHEMA_MODULE.name}: {psql_hits} — "
        f"detect-only boundary violated."
    )
    assert not flag_hits, (
        f"`-f migrations` literal found in {SCHEMA_MODULE.name}: "
        f"{flag_hits} — detect-only boundary violated."
    )


def test_schema_module_has_no_ddl_string_literals() -> None:
    """No DDL verb in any string literal in the module body. The
    one comment legitimately mentioning ``ALTER TABLE`` lives in
    detector B's docstring describing the *parser* — but as a
    *comment*, not a string literal — so this scan walks AST
    string nodes only."""
    tree = ast.parse(_module_source(), filename=str(SCHEMA_MODULE))
    offenders: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            upper = node.value.upper()
            for verb in _DDL_VERBS:
                # Word-boundary check; "CREATE" inside "create_at" or
                # "CREATED_AT" is fine. Real DDL prefixes a space.
                if re.search(rf"\b{verb}\s+(TABLE|INDEX|COLUMN|VIEW|SCHEMA)\b", upper):
                    offenders.append((node.lineno, node.value[:80]))
                    break
    assert not offenders, (
        f"DDL string literals in {SCHEMA_MODULE.name}: {offenders} — "
        f"Phase 8 is detect-only; DDL execution belongs to humans."
    )


def test_schema_module_has_no_execute_calls_with_ddl() -> None:
    """No ``something.execute(<ddl literal>)`` call site. Catches the
    case where a future patcher imports ``psycopg`` and tries to
    push DDL through the same connection the Detector-B crawl uses.
    """
    tree = ast.parse(_module_source(), filename=str(SCHEMA_MODULE))
    offenders: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "execute"):
            continue
        if not node.args:
            continue
        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            upper = first.value.upper().lstrip()
            for verb in _DDL_VERBS:
                if upper.startswith(verb + " "):
                    offenders.append((node.lineno, first.value[:80]))
                    break
    assert not offenders, (
        f"DDL execute() call sites in {SCHEMA_MODULE.name}: "
        f"{offenders} — Phase 8 is detect-only."
    )
