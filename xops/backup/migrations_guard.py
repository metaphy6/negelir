"""Phase 8 §8.13.4 — forward-only migration doctrine guard.

Scans ``migrations/*.sql`` files for destructive DDL statements that would
violate the Phase 8 forward-only assumption (CLAUDE.md doctrine: never DROP).

Doctrine: Restore-verify never runs migrations backward.  See Phase 8
doctrine (AGENTS.md §2, CLAUDE.md: "never DROP").  A future destructive
migration (Phase 14+) requires explicit escape-hatch design.

Doctrine respected:

* Rule 1 — Single-source config: no new tunables; paths resolved relative
  to module location; callers can inject ``migrations_dir`` for tests.
* Rule 3 — No fabricated production data.
* Rule 6 — English infra.
* Rule 7 — Adversarial tests are first-class (see test_migrations_guard.py).
"""
from __future__ import annotations

import logging
import re
import threading
from pathlib import Path
from typing import Optional

_log = logging.getLogger("xops.backup.migrations_guard")

# sec.alert.v1 kind emitted when a forbidden destructive DDL statement is
# found in a migration file.  Consumers tolerate unknown kinds (open-enum).
SEC_ALERT_BACKUP_MIGRATION_DROP_DETECTED: str = "backup_migration_drop_detected"

# Forbidden patterns that violate the forward-only assumption.
# Checked case-insensitively after stripping SQL single-line comments.
# ``GRANT ... TRUNCATE ON ...`` is excluded — that is a privilege grant,
# not a destructive TRUNCATE statement.
_FORBIDDEN: tuple[tuple[str, str], ...] = (
    (r"\bDROP\s+TABLE\b",   "DROP TABLE"),
    (r"\bDROP\s+COLUMN\b",  "DROP COLUMN"),
    (r"\bDROP\s+INDEX\b",   "DROP INDEX"),
    # TRUNCATE as a standalone DDL statement: "TRUNCATE [TABLE] <name>".
    # Excludes "GRANT DELETE, TRUNCATE ON ..." (TRUNCATE immediately
    # followed by ON belongs to a GRANT, not a TRUNCATE command).
    (r"\bTRUNCATE\s+(?:TABLE\s+)?(?!ON\b)\w", "TRUNCATE"),
)

_COMPILED: tuple[tuple[re.Pattern, str], ...] = tuple(
    (re.compile(pattern, re.IGNORECASE), label)
    for pattern, label in _FORBIDDEN
)

_MIGRATION_RE: re.Pattern = re.compile(r"^(\d+)_.+\.sql$", re.IGNORECASE)

# Module-level boot sentinel: fires the scan once per process lifetime.
_BOOT_LOCK: threading.Lock = threading.Lock()
_BOOT_ALERT_EMITTED: bool = False


def _strip_line_comment(line: str) -> str:
    """Remove the SQL single-line comment portion (``-- ...``) from *line*."""
    idx = line.find("--")
    return line[:idx] if idx != -1 else line


def scan_migrations_for_drops(
    migrations_dir: Optional[Path] = None,
) -> list[dict]:
    """Scan migration files for destructive DDL that violates the forward-only
    assumption.

    Parameters
    ----------
    migrations_dir:
        Override scan root.  Defaults to ``<repo_root>/migrations/``.

    Returns
    -------
    list[dict]
        One dict per violation with keys ``file``, ``line``, ``statement``,
        ``kind``.  Empty list means all migrations are clean.

    Examples
    --------
    ::

        violations = scan_migrations_for_drops()
        if violations:
            for v in violations:
                agent.emit_sec_alert(
                    kind=v["kind"], severity="warn",
                    reason=f"{v['file']}:{v['line']} contains {v['statement']}",
                )
    """
    from xops.backup.migration_state import _REPO_ROOT  # local to avoid circulars

    root = migrations_dir if migrations_dir is not None else (_REPO_ROOT / "migrations")
    violations: list[dict] = []

    if not root.is_dir():
        return violations

    for entry in sorted(root.iterdir()):
        if not _MIGRATION_RE.match(entry.name):
            continue
        try:
            text = entry.read_text(encoding="utf-8")
        except OSError as exc:
            _log.warning("migrations_guard: cannot read %s: %s", entry.name, exc)
            continue

        for lineno, raw_line in enumerate(text.splitlines(), start=1):
            stripped = _strip_line_comment(raw_line)
            for compiled, label in _COMPILED:
                if compiled.search(stripped):
                    violations.append({
                        "file": entry.name,
                        "line": lineno,
                        "statement": label,
                        "kind": SEC_ALERT_BACKUP_MIGRATION_DROP_DETECTED,
                    })
                    break  # one violation per line is sufficient

    return violations


def consume_drop_detected_boot_alert(
    migrations_dir: Optional[Path] = None,
) -> list[dict]:
    """Return violations exactly once per process lifetime for the boot-time
    forward-only doctrine check.

    Returns the list of violations the first time it is called if any are
    found; returns ``[]`` on all subsequent calls (sentinel prevents
    re-emission) and when the scan is clean.

    Used by the backup agent to emit
    ``sec.alert.v1{kind=backup_migration_drop_detected, severity=warn}``
    at most once per process boot.
    """
    global _BOOT_ALERT_EMITTED  # noqa: PLW0603
    with _BOOT_LOCK:
        if _BOOT_ALERT_EMITTED:
            return []
        violations = scan_migrations_for_drops(migrations_dir=migrations_dir)
        if violations:
            _BOOT_ALERT_EMITTED = True
            return violations
        return []
