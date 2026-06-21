"""Phase 8 §8.1 — opsctl boundary AST scan.

The ops console MUST NOT import storage clients (psycopg, redis
mutators) or shell out to psql / redis-cli. The bus is the only
sanctioned write surface; storage agents own their tables. This
test walks every ``.py`` under ``xops/opsctl/`` (excluding the
test dir) and rejects forbidden imports + ``subprocess`` calls
referencing those tools.
"""
from __future__ import annotations

import ast
import unittest
from pathlib import Path

OPSCTL_ROOT = Path(__file__).resolve().parents[1]
THIS_TESTS_DIR = Path(__file__).resolve().parent

FORBIDDEN_IMPORT_PREFIXES = (
    "psycopg",
    "psycopg2",
    "redis",  # the redis-py mutator surface (XADD/HSET/etc.)
    "asyncpg",
    "sqlalchemy",
)
# These are allowed because they ARE the bus seam.
ALLOWED_OVERRIDES = {
    # ai.swarm.sdk.bus *uses* redis internally, but opsctl talks to
    # it through the Bus protocol. We allow the indirection.
    "ai.swarm.sdk.bus",
}

FORBIDDEN_SUBPROCESS_TARGETS = ("psql", "redis-cli")


def _iter_opsctl_py() -> list[Path]:
    out: list[Path] = []
    for p in OPSCTL_ROOT.rglob("*.py"):
        if THIS_TESTS_DIR in p.parents:
            continue
        out.append(p)
    return sorted(out)


class TestOpsctlBoundary(unittest.TestCase):
    def test_no_forbidden_imports(self) -> None:
        offenders: list[tuple[str, str]] = []
        for path in _iter_opsctl_py():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name in ALLOWED_OVERRIDES:
                            continue
                        if any(alias.name.split(".")[0] == p for p in FORBIDDEN_IMPORT_PREFIXES):
                            offenders.append((str(path.relative_to(OPSCTL_ROOT.parent)), alias.name))
                elif isinstance(node, ast.ImportFrom):
                    mod = node.module or ""
                    if mod in ALLOWED_OVERRIDES:
                        continue
                    if any(mod.split(".")[0] == p for p in FORBIDDEN_IMPORT_PREFIXES):
                        offenders.append((str(path.relative_to(OPSCTL_ROOT.parent)), mod))
        self.assertEqual(
            offenders, [],
            msg=(
                "xops/opsctl/ MUST NOT import storage-mutator modules; "
                "the bus is the only write surface. Offenders: " + repr(offenders)
            ),
        )

    def test_no_subprocess_psql_or_redis_cli(self) -> None:
        """Reject string-arg references to forbidden tools that appear
        inside Call nodes (subprocess.run, os.system, Popen, etc.).
        Docstrings, comments, and identifier names are NOT flagged."""
        offenders: list[tuple[str, str]] = []
        for path in _iter_opsctl_py():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                # Collect every literal-string arg (positional + kw).
                literals: list[str] = []
                for arg in list(node.args) + [kw.value for kw in node.keywords]:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        literals.append(arg.value)
                    elif isinstance(arg, (ast.List, ast.Tuple)):
                        for elt in arg.elts:
                            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                literals.append(elt.value)
                for s in literals:
                    for tool in FORBIDDEN_SUBPROCESS_TARGETS:
                        # Whole-token match guarded by non-word chars
                        # to avoid false positives ('psqlite' etc).
                        if tool == s or s.startswith(tool + " ") or (" " + tool) in s:
                            offenders.append(
                                (str(path.relative_to(OPSCTL_ROOT.parent)), tool)
                            )
        self.assertEqual(
            offenders, [],
            msg=("xops/opsctl/ MUST NOT shell out to: " + repr(offenders)),
        )

    # ── §8.9 boundary: opsctl topic publish + read discipline ────────────────

    def test_opsctl_only_imports_maint_topics(self) -> None:
        """opsctl may only import MAINT_EVENT and MAINT_ACK from
        ai.swarm.agents.topics; no sec/predict/freshness/match symbols."""
        ALLOWED_TOPIC_IMPORTS = frozenset({"MAINT_EVENT", "MAINT_ACK"})
        offenders: list[tuple[str, str]] = []
        for path in _iter_opsctl_py():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.ImportFrom):
                    continue
                mod = node.module or ""
                if not (
                    mod == "ai.swarm.agents.topics"
                    or mod.endswith(".topics")
                    and "swarm" in mod
                ):
                    continue
                for alias in node.names:
                    if alias.name not in ALLOWED_TOPIC_IMPORTS:
                        offenders.append(
                            (str(path.relative_to(OPSCTL_ROOT.parent)), alias.name)
                        )
        self.assertEqual(
            offenders, [],
            msg=(
                "xops/opsctl/ may only import {MAINT_EVENT, MAINT_ACK} "
                "from the topics module; forbidden import(s): " + repr(offenders)
            ),
        )

    def test_opsctl_envelope_topic_is_maint_event(self) -> None:
        """Every Envelope(topic=...) call in opsctl must use MAINT_EVENT_TOPIC
        or MAINT_EVENT — never a forbidden prefix (sec/predict/freshness/match).
        """
        ALLOWED_NAMES = frozenset({"MAINT_EVENT_TOPIC", "MAINT_EVENT"})
        FORBIDDEN_PREFIXES = ("sec.", "predict.", "freshness.", "match.")
        offenders: list[tuple[str, str]] = []
        for path in _iter_opsctl_py():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                # Look for Call nodes where the function is named "Envelope"
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                func_name = ""
                if isinstance(func, ast.Name):
                    func_name = func.id
                elif isinstance(func, ast.Attribute):
                    func_name = func.attr
                if func_name != "Envelope":
                    continue
                # Find the 'topic' keyword argument
                for kw in node.keywords:
                    if kw.arg != "topic":
                        continue
                    val = kw.value
                    if isinstance(val, ast.Name):
                        # A named constant — must be in the allowed set
                        if val.id not in ALLOWED_NAMES:
                            offenders.append(
                                (str(path.relative_to(OPSCTL_ROOT.parent)), val.id)
                            )
                    elif isinstance(val, ast.Constant) and isinstance(val.value, str):
                        # A raw string literal — must not start with forbidden prefix
                        if any(val.value.startswith(p) for p in FORBIDDEN_PREFIXES):
                            offenders.append(
                                (str(path.relative_to(OPSCTL_ROOT.parent)), val.value)
                            )
        self.assertEqual(
            offenders, [],
            msg=(
                "Envelope(topic=...) in xops/opsctl/ must only publish on "
                "maint.event.v1; forbidden topic(s) found: " + repr(offenders)
            ),
        )

    def test_opsctl_bus_read_topic_is_maint_ack(self) -> None:
        """Every bus.read(...) call in opsctl must use MAINT_ACK_TOPIC or
        MAINT_ACK — never a forbidden prefix (sec/predict/freshness/match).
        """
        ALLOWED_NAMES = frozenset({"MAINT_ACK_TOPIC", "MAINT_ACK"})
        FORBIDDEN_PREFIXES = ("sec.", "predict.", "freshness.", "match.")
        offenders: list[tuple[str, str]] = []
        for path in _iter_opsctl_py():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                # Match bus.read(...) or self.bus.read(...) patterns
                if not (
                    isinstance(func, ast.Attribute) and func.attr == "read"
                ):
                    continue
                if not node.args:
                    continue
                first = node.args[0]
                if isinstance(first, ast.Name):
                    if first.id not in ALLOWED_NAMES:
                        offenders.append(
                            (str(path.relative_to(OPSCTL_ROOT.parent)), first.id)
                        )
                elif isinstance(first, ast.Constant) and isinstance(first.value, str):
                    if any(first.value.startswith(p) for p in FORBIDDEN_PREFIXES):
                        offenders.append(
                            (str(path.relative_to(OPSCTL_ROOT.parent)), first.value)
                        )
        self.assertEqual(
            offenders, [],
            msg=(
                "bus.read(...) in xops/opsctl/ must only read from maint.ack.v1; "
                "forbidden topic(s) found: " + repr(offenders)
            ),
        )


    # ── §8.16.16 boundary: exit-code range 5..10 continuous ─────────────────

    def test_exit_code_runbook_range_continuous_5_to_10(self) -> None:
        """ExitCode enum and _EXIT_CODE_LABELS must BOTH cover exactly {5..10}.

        This guards the runbook / dead-man's-switch alerter: if a code is
        added to _exit_codes.py without a matching entry in _classify.py
        (or vice-versa), operators see un-routable integers in their
        runbook branches.
        """
        from xops.opsctl._classify import _EXIT_CODE_LABELS
        from xops.opsctl._exit_codes import ExitCode

        EXPECTED = frozenset(range(5, 11))  # 5, 6, 7, 8, 9, 10

        # ExitCode enum must define all codes 5..10.
        enum_codes_in_range = frozenset(
            e.value for e in ExitCode if 5 <= e.value <= 10
        )
        self.assertEqual(
            enum_codes_in_range,
            EXPECTED,
            msg=(
                "ExitCode enum is missing codes in the 5..10 runbook range "
                f"or has unexpected entries. Got: {sorted(enum_codes_in_range)}"
            ),
        )

        # _EXIT_CODE_LABELS must cover exactly the same 5..10 range.
        label_keys = frozenset(_EXIT_CODE_LABELS.keys())
        self.assertEqual(
            label_keys,
            EXPECTED,
            msg=(
                "_EXIT_CODE_LABELS in _classify.py must cover exactly {5..10}. "
                f"Got: {sorted(label_keys)}"
            ),
        )

        # Every label must be a non-empty string.
        for code, label in _EXIT_CODE_LABELS.items():
            self.assertIsInstance(label, str, msg=f"Label for code {code} must be str")
            self.assertTrue(label, msg=f"Label for code {code} must be non-empty")

        # exit_code_to_label must return the label for each code.
        from xops.opsctl._classify import exit_code_to_label
        for code in EXPECTED:
            self.assertIsNotNone(
                exit_code_to_label(code),
                msg=f"exit_code_to_label({code}) must not return None",
            )
        # And must return None for codes outside the runbook range.
        self.assertIsNone(exit_code_to_label(4))
        self.assertIsNone(exit_code_to_label(11))


if __name__ == "__main__":
    unittest.main()
