"""Phase 8 §8.9 proof — pattern_allowlist partial-index plan.

Live Postgres test (skipped unless NEGELIR_PG_INTEGRATION=1 is set and a
reachable Postgres is available).

Populates an isolated ``pattern_allowlist`` table with 10k expired +
100 active rows and runs::

    EXPLAIN (ANALYZE, FORMAT JSON, BUFFERS)
    SELECT pattern FROM pattern_allowlist
    WHERE state = 'a'
    AND (expires_at IS NULL OR expires_at > now())

Asserts:

1. The planner chooses ``idx_pattern_allowlist_active`` (the partial
   index on ``state = 'a'`` rows) — NOT a sequential scan and NOT the
   full B-tree index over all rows.
2. Total shared blocks touched (hit + read) ≤ 20 — confirming that only
   the partial-index pages (covering 100 active rows) are accessed, not
   the 10k expired rows that the full table contains.  A sequential scan
   of 10 100 rows would produce orders of magnitude more buffer
   accesses.
"""
from __future__ import annotations

import json
import os
import socket
import uuid
from typing import Any

import pytest

# ── Live-PG guard ─────────────────────────────────────────────────────────

_PG_INTEGRATION = os.environ.get("NEGELIR_PG_INTEGRATION") == "1"


def _pg_available() -> bool:
    if not _PG_INTEGRATION:
        return False
    try:
        import psycopg2  # noqa: PLC0415 F401
    except ImportError:
        return False
    host = os.environ.get("POSTGRES_HOST", "localhost")
    port = int(os.environ.get("POSTGRES_PORT", "5432"))
    try:
        with socket.create_connection((host, port), timeout=1.0):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(
    not _pg_available(),
    reason="set NEGELIR_PG_INTEGRATION=1 with a reachable Postgres to run",
)


# ── Fixture: isolated schema + table ──────────────────────────────────────

@pytest.fixture()
def pg_allowlist_schema():
    """Create a temp schema with pattern_allowlist + partial index; drop on teardown."""
    import psycopg2  # noqa: PLC0415

    dsn = os.environ.get(
        "NEGELIR_MAINT_BACKUP_PG_DSN",
        "host={host} port={port} dbname={db} user={user} password={pw}".format(
            host=os.environ.get("POSTGRES_HOST", "localhost"),
            port=os.environ.get("POSTGRES_PORT", "5432"),
            db=os.environ.get("POSTGRES_DB", "negelir"),
            user=os.environ.get("POSTGRES_USER", "negelir"),
            pw=os.environ.get("POSTGRES_PASSWORD", ""),
        ),
    )
    conn = psycopg2.connect(dsn)
    conn.autocommit = True

    schema = f"test_pa_{uuid.uuid4().hex[:8]}"
    with conn.cursor() as cur:
        cur.execute(f"CREATE SCHEMA {schema}")
        # Mirror migrations/010_pattern_allowlist.sql: table + TWO indexes.
        cur.execute(f"""
            CREATE TABLE {schema}.pattern_allowlist (
                id          BIGSERIAL     PRIMARY KEY,
                pattern     TEXT          NOT NULL UNIQUE,
                state       CHAR(1)       NOT NULL
                    CONSTRAINT pa_state_chk CHECK (state IN ('p', 'a', 'e')),
                expires_at  TIMESTAMPTZ,
                created_at  TIMESTAMPTZ   NOT NULL DEFAULT now()
            )
        """)
        # (a) Full B-tree index — operator queries.
        cur.execute(f"""
            CREATE INDEX idx_pa_full
                ON {schema}.pattern_allowlist (pattern, state)
        """)
        # (b) Partial index — hot read path (sec.input.v1 eval query).
        # Named exactly as in the production migration so the EXPLAIN
        # assertion is identical to what CI sees against the real DB.
        cur.execute(f"""
            CREATE INDEX idx_pattern_allowlist_active
                ON {schema}.pattern_allowlist (pattern)
                WHERE state = 'a'
        """)

    yield schema, conn

    with conn.cursor() as cur:
        cur.execute(f"DROP SCHEMA {schema} CASCADE")
    conn.close()


# ── Helpers ──────────────────────────────────────────────────────────────

def _sum_shared_blocks(plan_node: dict[str, Any]) -> int:
    """Recursively sum Shared Hit Blocks + Shared Read Blocks across the plan tree."""
    total = (
        plan_node.get("Shared Hit Blocks", 0)
        + plan_node.get("Shared Read Blocks", 0)
    )
    for child in plan_node.get("Plans", []):
        total += _sum_shared_blocks(child)
    return total


def _plan_uses_index(plan_node: dict[str, Any], index_name: str) -> bool:
    """Return True if any plan node uses the named index."""
    if plan_node.get("Index Name", "").lower() == index_name.lower():
        return True
    return any(
        _plan_uses_index(child, index_name)
        for child in plan_node.get("Plans", [])
    )


def _has_seqscan(plan_node: dict[str, Any]) -> bool:
    """Return True if any plan node is a sequential scan."""
    if plan_node.get("Node Type") == "Seq Scan":
        return True
    return any(_has_seqscan(child) for child in plan_node.get("Plans", []))


# ── Test ─────────────────────────────────────────────────────────────────

def test_pattern_allowlist_eval_uses_partial_index(pg_allowlist_schema) -> None:
    """EXPLAIN ANALYZE BUFFERS of the sec.input.v1 eval query uses
    ``idx_pattern_allowlist_active`` and touches ≤ 20 shared blocks.

    Table is populated with:
    - 10k expired rows (state='e')  — bulk of the table
    -  100 active  rows (state='a') — only these should be scanned

    Total shared blocks (hit + read) must be ≤ 20.  A sequential scan
    of 10 100 rows would produce hundreds of buffer accesses.
    """
    schema, conn = pg_allowlist_schema

    with conn.cursor() as cur:
        # Insert 10 000 expired rows.
        cur.execute(
            f"""
            INSERT INTO {schema}.pattern_allowlist (pattern, state, expires_at)
            SELECT
                md5(g::text),
                'e',
                now() - interval '1 day'
            FROM generate_series(1, 10000) AS g
            """
        )
        # Insert 100 active rows (expires_at NULL → never expires).
        cur.execute(
            f"""
            INSERT INTO {schema}.pattern_allowlist (pattern, state, expires_at)
            SELECT
                md5((g + 10000)::text),
                'a',
                NULL
            FROM generate_series(1, 100) AS g
            """
        )

        # ANALYZE so the planner uses accurate statistics.
        cur.execute(f"ANALYZE {schema}.pattern_allowlist")

        # sec.input.v1 eval query — mirrored from PgAllowlistReader.read_active_snapshot.
        eval_sql = (
            f"SELECT pattern FROM {schema}.pattern_allowlist"
            " WHERE state = 'a'"
            " AND (expires_at IS NULL OR expires_at > now())"
        )

        cur.execute(
            f"EXPLAIN (ANALYZE, FORMAT JSON, BUFFERS) {eval_sql}"
        )
        explain_rows = cur.fetchall()

    # psycopg2 returns EXPLAIN JSON as a Python list already parsed.
    plan_json = explain_rows[0][0]
    if isinstance(plan_json, str):
        plan_json = json.loads(plan_json)

    assert isinstance(plan_json, list) and len(plan_json) == 1, (
        "EXPLAIN JSON must return a single-element list"
    )
    top_plan = plan_json[0]["Plan"]

    # 1. The planner must use idx_pattern_allowlist_active.
    assert _plan_uses_index(top_plan, "idx_pattern_allowlist_active"), (
        f"Expected idx_pattern_allowlist_active in plan but got:\n"
        f"{json.dumps(plan_json, indent=2)}"
    )

    # 2. No sequential scan — the 10k expired rows must not be touched.
    assert not _has_seqscan(top_plan), (
        f"Unexpected sequential scan (partial index not being used):\n"
        f"{json.dumps(plan_json, indent=2)}"
    )

    # 3. Buffers read ≤ active-row footprint.
    # 100 active rows + partial-index pages ≈ 2-4 PG pages.
    # Generous upper bound of 20 still far below a seqscan of 10 100 rows.
    shared_blocks = _sum_shared_blocks(top_plan)
    assert shared_blocks <= 20, (
        f"Expected ≤ 20 shared blocks (active-row footprint) but got "
        f"{shared_blocks}.\nPlan:\n{json.dumps(plan_json, indent=2)}"
    )
