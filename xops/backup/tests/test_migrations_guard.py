"""Phase 8 §8.13.4 — forward-only migration doctrine guard proof tests.

Two mandated scenarios:

(a) Migration file with ``DROP TABLE`` → guard fires; violation dict has
    correct ``file``, ``line``, ``statement``, ``kind`` fields.
(b) Migration file with only additive DDL (``CREATE TABLE``,
    ``ALTER TABLE … ADD COLUMN``, etc.) → guard returns empty list.

Additional adversarial cases:
(c) ``DROP COLUMN`` detected.
(d) ``DROP INDEX`` detected.
(e) ``TRUNCATE`` statement detected (but ``GRANT … TRUNCATE ON …`` is NOT
    flagged — that is a privilege grant, not a destructive command).
(f) DROP in a SQL comment (``-- DROP TABLE``) is NOT flagged.
(g) ``DROP TRIGGER IF EXISTS`` is NOT flagged (not TABLE/COLUMN/INDEX).
(h) ``consume_drop_detected_boot_alert`` returns violations once then ``[]``.
(i) ``backup_migration_drop_detected`` is registered in
    ``KNOWN_SEC_ALERT_KINDS``.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import xops.backup.migrations_guard as _guard


# ── helpers ─────────────────────────────────────────────────────────────


def _make_mig(tmp_path: Path, name: str, content: str) -> Path:
    f = tmp_path / name
    f.write_text(content, encoding="utf-8")
    return f


# ── (a) DROP TABLE detected ──────────────────────────────────────────────


def test_drop_table_detected(tmp_path: Path) -> None:
    """Scenario (a): Migration file with DROP TABLE triggers a violation."""
    _make_mig(tmp_path, "012_bad.sql", "DROP TABLE users;\n")
    violations = _guard.scan_migrations_for_drops(migrations_dir=tmp_path)

    assert len(violations) == 1
    v = violations[0]
    assert v["file"] == "012_bad.sql"
    assert v["line"] == 1
    assert v["statement"] == "DROP TABLE"
    assert v["kind"] == "backup_migration_drop_detected"


# ── (b) Additive migration passes cleanly ────────────────────────────────


def test_additive_migration_clean(tmp_path: Path) -> None:
    """Scenario (b): CREATE TABLE, ALTER TABLE ADD COLUMN → no violations."""
    content = (
        "CREATE TABLE events (\n"
        "    id BIGSERIAL PRIMARY KEY,\n"
        "    kind TEXT NOT NULL\n"
        ");\n"
        "ALTER TABLE events ADD COLUMN produced_at TIMESTAMPTZ;\n"
    )
    _make_mig(tmp_path, "012_add_events.sql", content)
    violations = _guard.scan_migrations_for_drops(migrations_dir=tmp_path)
    assert violations == []


# ── (c) DROP COLUMN detected ────────────────────────────────────────────


def test_drop_column_detected(tmp_path: Path) -> None:
    """Scenario (c): DROP COLUMN is a forbidden destructive DDL."""
    _make_mig(
        tmp_path, "013_bad.sql",
        "ALTER TABLE users DROP COLUMN legacy_field;\n"
    )
    violations = _guard.scan_migrations_for_drops(migrations_dir=tmp_path)

    assert len(violations) == 1
    assert violations[0]["statement"] == "DROP COLUMN"
    assert violations[0]["kind"] == "backup_migration_drop_detected"


# ── (d) DROP INDEX detected ──────────────────────────────────────────────


def test_drop_index_detected(tmp_path: Path) -> None:
    """Scenario (d): DROP INDEX is forbidden."""
    _make_mig(tmp_path, "013_bad_idx.sql", "DROP INDEX IF EXISTS idx_users_email;\n")
    violations = _guard.scan_migrations_for_drops(migrations_dir=tmp_path)

    assert len(violations) == 1
    assert violations[0]["statement"] == "DROP INDEX"


# ── (e) TRUNCATE statement vs GRANT TRUNCATE ─────────────────────────────


def test_truncate_statement_detected(tmp_path: Path) -> None:
    """TRUNCATE <table> (a DDL command) is forbidden."""
    _make_mig(tmp_path, "013_bad_trunc.sql", "TRUNCATE TABLE staging_events;\n")
    violations = _guard.scan_migrations_for_drops(migrations_dir=tmp_path)

    assert len(violations) == 1
    assert violations[0]["statement"] == "TRUNCATE"


def test_grant_truncate_not_flagged(tmp_path: Path) -> None:
    """GRANT DELETE, TRUNCATE ON … is a privilege grant — must NOT fire."""
    _make_mig(
        tmp_path, "009_grant.sql",
        "GRANT DELETE, TRUNCATE ON maint_audit_log_pii TO negelir_audit_pruner;\n"
    )
    violations = _guard.scan_migrations_for_drops(migrations_dir=tmp_path)
    assert violations == [], f"Unexpected violations: {violations}"


# ── (f) DROP in a SQL comment ────────────────────────────────────────────


def test_drop_in_comment_not_flagged(tmp_path: Path) -> None:
    """-- DROP TABLE inside a comment must NOT trigger a violation."""
    _make_mig(
        tmp_path, "012_ok.sql",
        "-- DROP TABLE users;  (this was done in the previous release)\n"
        "CREATE TABLE users (id BIGSERIAL PRIMARY KEY);\n"
    )
    violations = _guard.scan_migrations_for_drops(migrations_dir=tmp_path)
    assert violations == []


# ── (g) DROP TRIGGER not flagged ─────────────────────────────────────────


def test_drop_trigger_not_flagged(tmp_path: Path) -> None:
    """DROP TRIGGER IF EXISTS is a safe idempotent guard — not TABLE/COLUMN/INDEX."""
    content = (
        "DROP TRIGGER IF EXISTS trg_audit_stamp ON maint_audit_log_pii;\n"
        "CREATE TRIGGER trg_audit_stamp BEFORE INSERT ON maint_audit_log_pii\n"
        "    FOR EACH ROW EXECUTE FUNCTION set_produced_at();\n"
    )
    _make_mig(tmp_path, "009_trigger.sql", content)
    violations = _guard.scan_migrations_for_drops(migrations_dir=tmp_path)
    assert violations == []


# ── (h) Boot sentinel fires once then never again ────────────────────────


def test_boot_sentinel_fires_once_then_silent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """consume_drop_detected_boot_alert returns violations the first call
    when drops are found, then [] on all subsequent calls."""
    # Reset module-level sentinel for isolation.
    monkeypatch.setattr(_guard, "_BOOT_ALERT_EMITTED", False)

    _make_mig(tmp_path, "012_bad.sql", "DROP TABLE old_table;\n")

    first = _guard.consume_drop_detected_boot_alert(migrations_dir=tmp_path)
    assert len(first) == 1
    assert first[0]["kind"] == "backup_migration_drop_detected"

    # Subsequent calls return empty even though the file still has DROP TABLE.
    second = _guard.consume_drop_detected_boot_alert(migrations_dir=tmp_path)
    assert second == []
    third = _guard.consume_drop_detected_boot_alert(migrations_dir=tmp_path)
    assert third == []


def test_boot_sentinel_clean_stays_silent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """consume_drop_detected_boot_alert returns [] when migrations are clean."""
    monkeypatch.setattr(_guard, "_BOOT_ALERT_EMITTED", False)

    _make_mig(tmp_path, "012_ok.sql", "CREATE TABLE foo (id BIGSERIAL);\n")
    result = _guard.consume_drop_detected_boot_alert(migrations_dir=tmp_path)
    assert result == []


# ── (i) KNOWN_SEC_ALERT_KINDS registration ──────────────────────────────


def test_kind_in_known_sec_alert_kinds() -> None:
    """backup_migration_drop_detected must be in KNOWN_SEC_ALERT_KINDS."""
    from swarm.agents.payloads import KNOWN_SEC_ALERT_KINDS
    assert "backup_migration_drop_detected" in KNOWN_SEC_ALERT_KINDS


# ── (j) Real migrations are all clean ────────────────────────────────────


def test_real_repo_migrations_clean() -> None:
    """The actual migrations in the repo must not contain forbidden DDL."""
    violations = _guard.scan_migrations_for_drops()
    assert violations == [], (
        "One or more migration files contain forbidden DROP/TRUNCATE DDL — "
        "Phase 8 doctrine (forward-only) violation:\n"
        + "\n".join(
            f"  {v['file']}:{v['line']} — {v['statement']}"
            for v in violations
        )
    )
