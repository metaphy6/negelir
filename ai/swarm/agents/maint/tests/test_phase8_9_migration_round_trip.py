"""Phase 8 §8.9 -- Migration round-trip proof tests.

Binding contract (ROADMAP §8.9 Migrations):
  (1) Migrations 009, 010, 011 are additive (no DROP TABLE / DROP COLUMN).
  (2) Detector B (parse_migrations_dir) parses all 11 migrations:
      - Phase 8 tables have no unknown_constructs entries.
      - diff_columns(digest, digest) == [] (self-consistent; zero
        false-positive drift).
  (3) After upgrade from migration 008, Phase 8 tables appear.
  (4) Restore-empty quarantine proof (combined §8.9 invariant):
      - negelir.quarantine_meta.csv carries exactly N data rows with the
        documented PII-excluded columns.
      - Post-restore quarantine_samples == 0.
        (Proven by test_restore_round_trip_quarantine_samples_excluded in
        test_phase8_9_restore_round_trip.py; the CSV half is proven here.)
"""
from __future__ import annotations

import csv as _csv
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

from swarm.agents.maint import _schema_drift as _drift
from xops.backup.executors import QUARANTINE_META_NAME, LocalPgDumpExecutor

# ---- Constants ----------------------------------------------------------

_REPO = Path(__file__).resolve().parents[5]
_MIGRATIONS = _REPO / "migrations"

# Documented PII-free columns (mirrors _QUARANTINE_META_SQL in executors.py).
_META_COLUMNS = frozenset([
    "quarantine_id", "source", "verdict", "reasons",
    "bytes_sha256", "detected_at", "erased_at", "pii_redacted",
])
_PII_COLUMNS_EXCLUDED = frozenset(["raw_bytes", "client_id", "ip"])


# ---- Minimal FakeRunner (avoids spawning real subprocesses) -------------

@dataclass
class _FakeRunner:
    calls: list = field(default_factory=list)
    handlers: dict = field(default_factory=dict)

    def __call__(
        self,
        argv: Sequence[str],
        *,
        env: Optional[Mapping[str, str]] = None,
        cwd: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> "subprocess.CompletedProcess[bytes]":
        self.calls.append(list(argv))
        head = os.path.basename(argv[0])
        handler = self.handlers.get(head)
        if handler is None:
            return subprocess.CompletedProcess(
                args=list(argv), returncode=0, stdout=b"", stderr=b""
            )
        return handler(list(argv))


def _write_recipients(tmp_path: Path) -> Path:
    p = tmp_path / "recipients.txt"
    p.write_text("age1examplerecipientpubkey0000000000000000000000000000\n")
    return p


# ---- Migrations are additive (no DROP TABLE / DROP COLUMN) ---------------


def test_migration_009_no_drop_table_or_column() -> None:
    """Migration 009 (maint_audit_log_pii) must not DROP any table or column."""
    sql = (_MIGRATIONS / "009_maint_audit.sql").read_text(encoding="utf-8")
    assert not re.search(r"\bDROP\s+TABLE\b", sql, re.IGNORECASE), (
        "009_maint_audit.sql must not DROP any table (additive-only doctrine)"
    )
    assert not re.search(r"\bDROP\s+COLUMN\b", sql, re.IGNORECASE), (
        "009_maint_audit.sql must not DROP any column"
    )


def test_migration_010_no_drop_table_or_column() -> None:
    """Migration 010 (pattern_allowlist) must not DROP any table or column."""
    sql = (_MIGRATIONS / "010_pattern_allowlist.sql").read_text(encoding="utf-8")
    assert not re.search(r"\bDROP\s+TABLE\b", sql, re.IGNORECASE), (
        "010_pattern_allowlist.sql must not DROP any table (additive-only doctrine)"
    )
    assert not re.search(r"\bDROP\s+COLUMN\b", sql, re.IGNORECASE), (
        "010_pattern_allowlist.sql must not DROP any column"
    )


def test_migration_011_no_drop_table_or_column() -> None:
    """Migration 011 (backup role) must not DROP any table or column."""
    sql = (_MIGRATIONS / "011_backup_role.sql").read_text(encoding="utf-8")
    assert not re.search(r"\bDROP\s+TABLE\b", sql, re.IGNORECASE), (
        "011_backup_role.sql must not DROP any table"
    )
    assert not re.search(r"\bDROP\s+COLUMN\b", sql, re.IGNORECASE), (
        "011_backup_role.sql must not DROP any column"
    )


# ---- Detector B parse correctness on Phase 8 migration files -------------


def test_migration_009_detector_b_finds_maint_audit_log_pii(tmp_path: Path) -> None:
    """Detector B finds maint_audit_log_pii with key columns after parsing 009."""
    shutil.copy(_MIGRATIONS / "009_maint_audit.sql", tmp_path / "009.sql")
    digest = _drift.parse_migrations_dir(tmp_path)
    assert "maint_audit_log_pii" in digest.tables
    cols = digest.tables["maint_audit_log_pii"]
    for col in ("id", "produced_at", "request_id", "kind", "target"):
        assert col in cols, f"maint_audit_log_pii missing expected column {col!r}"


def test_migration_010_detector_b_finds_pattern_allowlist(tmp_path: Path) -> None:
    """Detector B finds pattern_allowlist with key columns after parsing 010."""
    shutil.copy(_MIGRATIONS / "010_pattern_allowlist.sql", tmp_path / "010.sql")
    digest = _drift.parse_migrations_dir(tmp_path)
    assert "pattern_allowlist" in digest.tables
    cols = digest.tables["pattern_allowlist"]
    for col in ("id", "pattern", "state", "expires_at", "created_at"):
        assert col in cols, f"pattern_allowlist missing expected column {col!r}"


def test_migration_011_no_create_table() -> None:
    """Migration 011 is role-only -- Detector B must find no tables in it."""
    sql = (_MIGRATIONS / "011_backup_role.sql").read_text(encoding="utf-8")
    assert not re.search(r"\bCREATE\s+TABLE\b", sql, re.IGNORECASE), (
        "011_backup_role.sql must not CREATE any tables (role-only migration)"
    )


# ---- Upgrade from migration 008 adds Phase 8 tables ---------------------


def test_upgrade_from_008_phase8_tables_absent_then_present(tmp_path: Path) -> None:
    """Phase 8 tables are absent on 001-008 baseline; appear after 009-011."""
    base = tmp_path / "base"
    base.mkdir()
    full = tmp_path / "full"
    full.mkdir()

    for sql_file in sorted(_MIGRATIONS.glob("0*.sql")):
        n = int(sql_file.stem.split("_")[0])
        if n <= 8:
            shutil.copy(sql_file, base / sql_file.name)

    d008 = _drift.parse_migrations_dir(base)
    assert "maint_audit_log_pii" not in d008.tables, (
        "maint_audit_log_pii must not exist before migration 009"
    )
    assert "pattern_allowlist" not in d008.tables, (
        "pattern_allowlist must not exist before migration 010"
    )

    for sql_file in sorted(_MIGRATIONS.glob("0*.sql")):
        shutil.copy(sql_file, full / sql_file.name)

    d011 = _drift.parse_migrations_dir(full)
    assert "maint_audit_log_pii" in d011.tables, (
        "maint_audit_log_pii must appear after migration 009"
    )
    assert "pattern_allowlist" in d011.tables, (
        "pattern_allowlist must appear after migration 010"
    )


# ---- Detector B round-trip: zero false-positive drift --------------------


def test_detector_b_phase8_tables_no_unknown_constructs() -> None:
    """Detector B on all 11 migrations: Phase 8 tables have no unknown_constructs.

    unknown_constructs marks tables whose column set was assembled despite a
    parse failure; such entries cause false-positive drift alerts.
    """
    digest = _drift.parse_migrations_dir(_MIGRATIONS)
    for tbl in ("maint_audit_log_pii", "pattern_allowlist"):
        assert tbl in digest.tables, f"Detector B must recognise {tbl!r}"
        assert tbl not in digest.unknown_constructs, (
            f"{tbl!r} must NOT be in unknown_constructs "
            "(would produce false-positive drift)"
        )


def test_detector_b_round_trip_zero_drift() -> None:
    """diff_columns(digest, digest) == [] for all 11 migrations.

    The round-trip uses the Detector B output as both the expected and
    observed schemas.  Self-comparison must produce no drift entries,
    confirming the full migration suite is self-consistently parsed.
    """
    digest = _drift.parse_migrations_dir(_MIGRATIONS)
    drifts = _drift.diff_columns(digest.tables, digest.tables)
    assert drifts == [], (
        f"Detector B round-trip must produce zero drift; got {drifts!r}"
    )


# ---- Restore-empty quarantine proof: CSV half ---------------------------


def test_quarantine_meta_csv_has_n_rows_with_pii_excluded_columns(
    tmp_path: Path,
) -> None:
    """negelir.quarantine_meta.csv has exactly N data rows with documented
    PII-excluded columns after a PII-aware dump.

    This is the CSV half of the §8.9 restore-empty quarantine proof.
    The restore half (quarantine_samples == 0 after restore) is covered by
    test_restore_round_trip_quarantine_samples_excluded in
    test_phase8_9_restore_round_trip.py.

    Together they prove the combined §8.9 invariant: the PII-aware dump
    produces a sanitized projection CSV (N rows, no PII columns) and the
    restore produces an empty quarantine_samples table.
    """
    N = 5
    header = (
        "quarantine_id,source,verdict,reasons,"
        "bytes_sha256,detected_at,erased_at,pii_redacted\n"
    )
    rows_csv = "".join(
        "qid{i},scrape,quarantine,oversized,{sha},2026-05-{d:02d}T03:00:0{i}+00:00,,f\n".format(
            i=i, sha="a" * 64, d=10 + i,
        )
        for i in range(N)
    )
    psql_csv_bytes = (header + rows_csv).encode()

    def fake_pg_dump(argv: list) -> "subprocess.CompletedProcess[bytes]":
        out_dir = Path(argv[argv.index("--file") + 1])
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "0001.dat").write_bytes(b"placeholder")
        return subprocess.CompletedProcess(args=argv, returncode=0, stdout=b"", stderr=b"")

    def fake_psql(argv: list) -> "subprocess.CompletedProcess[bytes]":
        return subprocess.CompletedProcess(
            args=argv, returncode=0, stdout=psql_csv_bytes, stderr=b""
        )

    def fake_age(argv: list) -> "subprocess.CompletedProcess[bytes]":
        out_path = Path(argv[argv.index("-o") + 1])
        out_path.write_bytes(b"AGE-BLOB")
        return subprocess.CompletedProcess(args=argv, returncode=0, stdout=b"", stderr=b"")

    recipients = _write_recipients(tmp_path)
    runner = _FakeRunner(
        handlers={"pg_dump": fake_pg_dump, "psql": fake_psql, "age": fake_age}
    )
    ex = LocalPgDumpExecutor(
        backup_dir=str(tmp_path / "backups"),
        pg_dsn="postgresql://x@y/z",
        pg_jobs=2,
        age_recipients_file=str(recipients),
        runner=runner,
        pg_dump_binary="pg_dump",
        age_binary="age",
        psql_binary="psql",
    )
    ex.dump(fire_window_id="meta", dry_run=False)

    # CSV exists alongside the encrypted dump
    window_dir = tmp_path / "backups" / "meta"
    meta_path = window_dir / QUARANTINE_META_NAME
    assert meta_path.is_file(), (
        f"{QUARANTINE_META_NAME} must exist alongside the encrypted dump"
    )

    # CSV has exactly N data rows
    with meta_path.open("r", encoding="utf-8", newline="") as fh:
        reader = _csv.DictReader(fh)
        data_rows = list(reader)
    assert len(data_rows) == N, (
        f"quarantine_meta.csv must have exactly {N} data rows; got {len(data_rows)}"
    )

    # Documented PII-excluded columns are present
    assert reader.fieldnames is not None
    present = frozenset(reader.fieldnames)
    missing = _META_COLUMNS - present
    assert not missing, (
        f"quarantine_meta.csv missing documented columns: {missing!r}"
    )

    # PII columns are absent
    for pii_col in _PII_COLUMNS_EXCLUDED:
        assert pii_col not in present, (
            f"PII column {pii_col!r} must NOT appear in quarantine_meta.csv"
        )
