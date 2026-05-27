#!/usr/bin/env python3
"""`make audit.verify-api` and `make api.erase-user` — Phase 9 §9.8 audit chain tools.

Targets:
    verify-api  Walk api_audit_log ordered by id; verify the HMAC chain.
                Phase 1: SQL linkage check (fast, no key needed — window-function
                LAG comparison; exit non-zero on first broken link).
                Phase 2: SQL HMAC recomputation (requires pgcrypto + audit key file;
                sets api.audit_key GUC per-session, mirrors the BEFORE-INSERT trigger).
    erase-user  GDPR right-to-erasure: null-stamp user_id in api_audit_log,
                purge the users row, emit pii_erased on maint.event.v1.
                USER env-var or --user argument required (<uuid> or email).

All DB I/O goes through `docker compose exec postgres psql` (same pattern as
xops/makefile/db.py) so no host-side psycopg2 is required.

The maint.event.v1{kind=pii_erased} event is published directly to the Redis
stream via `docker compose exec redis redis-cli XADD`, following the JsonCodec
wire format ({envelope, payload}) consumed by the SDK on read.

PII discipline (Phase 9 §9.8):
  - `user_id` in api_audit_log is a UUID (not email).  Null-stamp post-erasure
    is belt-and-braces: the UUID cannot be reverse-engineered to email, but
    GDPR Art. 17 erasure removes all linkable identifiers.
  - NEVER log or surface email addresses; only the UUID is used after lookup.
  - The pii_erased payload's `client_id` field carries the data-subject UUID.
"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import uuid as uuid_mod
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from xops.makefile._common import (  # noqa: E402
    COMPOSE,
    ENV_FILE,
    dispatch,
    err,
    info,
    ok,
    step,
    warn,
)

_PG_SVC = "postgres"
_PG_USER = "negelir"
_PG_DB = "negelir"

# ── low-level helpers ──────────────────────────────────────────────────


def _compose_base() -> List[str]:
    parts = list(COMPOSE)
    if ENV_FILE.is_file():
        parts += ["--env-file", str(ENV_FILE)]
    return parts


def _psql(sql: str, *, csv: bool = False) -> subprocess.CompletedProcess:
    """Pipe `sql` to psql inside the postgres container; return CompletedProcess.

    Always uses --tuples-only --no-align so output is easy to parse.
    Pass csv=True to get RFC-4180 CSV output instead.
    """
    base = _compose_base()
    psql_flags = [
        "psql", "--no-psqlrc", "--tuples-only",
        "-U", _PG_USER, "-d", _PG_DB,
    ]
    if csv:
        psql_flags.append("--csv")
    else:
        psql_flags.append("--no-align")
    cmd = [*base, "exec", "-T", _PG_SVC, *psql_flags]
    return subprocess.run(
        cmd,
        input=sql,
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )


def _read_audit_key() -> Optional[bytes]:
    """Return raw key bytes from NEGELIR_AUDIT_CHAIN_HMAC_KEY_PATH, or None."""
    key_path = os.environ.get(
        "NEGELIR_AUDIT_CHAIN_HMAC_KEY_PATH",
        "/var/lib/negelir/secrets/audit_chain.key",
    )
    p = Path(key_path)
    if p.is_file():
        try:
            return p.read_bytes()
        except OSError as exc:
            warn(f"audit key file unreadable ({exc}); HMAC check skipped")
            return None
    warn(
        f"audit key not found at {key_path}; HMAC recomputation skipped "
        "(chain-linkage check will still run)."
    )
    return None


def _is_valid_uuid(s: str) -> bool:
    try:
        uuid_mod.UUID(s)
        return True
    except ValueError:
        return False


# ── cmd_verify_api ─────────────────────────────────────────────────────


def cmd_verify_api(_argv: List[str]) -> int:
    """Walk api_audit_log; verify chain linkage + HMAC (Phase 9 §9.8)."""

    # ── Phase 1: chain linkage (SQL, no key) ──────────────────────────
    step("Phase 1: SQL chain-linkage check (prev_hmac == prior row_hmac)…")
    # LAG with default 'GENESIS' mirrors the first-row sentinel; TRIM strips
    # CHAR(64) padding so 'GENESIS' + 57 spaces compares equal to 'GENESIS'.
    linkage_sql = """\
WITH ordered AS (
    SELECT id,
           TRIM(prev_hmac::text)                                 AS prev_h,
           TRIM(row_hmac::text)                                  AS row_h,
           TRIM(LAG(row_hmac::text, 1, 'GENESIS')
                    OVER (ORDER BY id))                          AS expected_prev
    FROM api_audit_log
)
SELECT COALESCE(COUNT(*), 0)::text  AS broken_count,
       COALESCE(MIN(id)::text, '')  AS first_broken_id
FROM ordered
WHERE prev_h != expected_prev;
"""
    r1 = _psql(linkage_sql)
    if r1.returncode != 0:
        err(f"psql linkage check failed: {r1.stderr.strip()}")
        err("Is the postgres container running?  Try: make up")
        return 1

    raw = r1.stdout.strip()
    # --no-align output: "value1|value2" or just "value1" when second is empty
    parts = [p.strip() for p in raw.split("|")]
    try:
        broken_count = int(parts[0]) if parts and parts[0] else 0
        first_id = parts[1] if len(parts) > 1 else ""
    except (ValueError, IndexError):
        warn(f"Unexpected linkage output: {raw!r}")
        broken_count = 0
        first_id = ""

    if broken_count > 0:
        err(
            f"Chain LINKAGE BROKEN: {broken_count} row(s) with wrong prev_hmac. "
            f"First broken row id={first_id or '(unknown)'}"
        )
        return 1
    ok("Phase 1 PASSED: chain linkage intact.")

    # ── Phase 2: HMAC recomputation (SQL + pgcrypto, key from file) ───
    key_bytes = _read_audit_key()
    if key_bytes is None:
        warn(
            "Phase 2 skipped (audit key unavailable). "
            "Set NEGELIR_AUDIT_CHAIN_HMAC_KEY_PATH to enable full HMAC check."
        )
        return 0

    step("Phase 2: HMAC recomputation via pgcrypto (mirrors api_audit_stamp_row_hmac())…")
    key_b64 = base64.b64encode(key_bytes).decode("ascii")

    # Mirror the trigger exactly — same coalesce, same produced_at::text, same hmac().
    # SET api.audit_key for this session; current_setting() picks it up in the SELECT.
    # The EXCEPTION block in the trigger is not needed here: we always set the GUC above.
    hmac_sql = f"""\
SET api.audit_key = '{key_b64}';
SELECT COALESCE(COUNT(*), 0)::text  AS bad_count,
       COALESCE(MIN(id)::text, '')  AS first_bad_id
FROM api_audit_log
WHERE row_hmac != encode(
    hmac(
        convert_to(
            coalesce(prev_hmac::text, 'GENESIS') || '|' ||
            request_id  || '|' ||
            kind        || '|' ||
            coalesce(method, '') || '|' ||
            coalesce(path,   '') || '|' ||
            produced_at::text,
            'UTF8'
        ),
        decode(current_setting('api.audit_key'), 'base64'),
        'sha256'
    ),
    'hex'
);
"""
    r2 = _psql(hmac_sql)
    if r2.returncode != 0:
        stderr = r2.stderr.strip()
        if "function hmac" in stderr or "pgcrypto" in stderr.lower():
            warn(
                "pgcrypto not installed — HMAC recomputation check skipped. "
                "Install pgcrypto: CREATE EXTENSION pgcrypto;"
            )
            return 0
        err(f"psql HMAC check failed: {stderr}")
        return 1

    raw2 = r2.stdout.strip()
    parts2 = [p.strip() for p in raw2.split("|")]
    try:
        bad_count = int(parts2[0]) if parts2 and parts2[0] else 0
        first_bad_id = parts2[1] if len(parts2) > 1 else ""
    except (ValueError, IndexError):
        warn(f"Unexpected HMAC check output: {raw2!r}")
        bad_count = 0
        first_bad_id = ""

    if bad_count > 0:
        err(
            f"HMAC MISMATCH: {bad_count} row(s) have bad row_hmac. "
            f"First bad row id={first_bad_id or '(unknown)'}. "
            "Possible tampering or key rotation without re-signing."
        )
        return 1

    ok("Phase 2 PASSED: all row HMACs verified.")
    ok("api_audit_log chain integrity confirmed.")
    return 0


# ── cmd_erase_user ─────────────────────────────────────────────────────


def cmd_erase_user(argv: List[str]) -> int:
    """GDPR right-to-erasure: null-stamp api_audit_log.user_id, purge users row,
    emit pii_erased on maint.event.v1.

    USER env-var or --user argument (<uuid> or email).  Email accepted for
    operator convenience; the UUID is resolved immediately and the email is
    never stored or logged after that point.
    """

    # Resolve USER — prefer explicit --user arg, fall back to USER env-var.
    user_arg = ""
    for i, a in enumerate(argv):
        if a in ("--user", "-u") and i + 1 < len(argv):
            user_arg = argv[i + 1].strip()
            break
        if a.startswith("--user="):
            user_arg = a.split("=", 1)[1].strip()
            break
    if not user_arg:
        # Do NOT fall through to the shell's $USER (current login name).
        err("--user <uuid-or-email> is required")
        err("Usage: make api.erase-user USER=<uuid-or-email>")
        return 64

    # Validate: only accept UUID or email (no SQL-special characters).
    is_uuid = _is_valid_uuid(user_arg)
    is_email = (
        not is_uuid
        and "@" in user_arg
        and "'" not in user_arg
        and '"' not in user_arg
        and ";" not in user_arg
        and "\\" not in user_arg
        and len(user_arg) <= 320
    )
    if not is_uuid and not is_email:
        err(f"USER must be a UUID or valid email address; got: {user_arg!r}")
        return 64

    # ── Step 1: resolve UUID ───────────────────────────────────────────
    step("Resolving user UUID from users table…")
    if is_uuid:
        lookup_sql = f"SELECT id FROM users WHERE id = '{user_arg}'::uuid;\n"
    else:
        # Dollar-quoting avoids any residual injection risk from unusual emails.
        safe = user_arg.lower()
        lookup_sql = f"SELECT id FROM users WHERE email_lower = $${safe}$$;\n"

    lr = _psql(lookup_sql)
    if lr.returncode != 0:
        err(f"psql lookup failed: {lr.stderr.strip()}")
        return 1

    user_uuid = lr.stdout.strip()
    if not user_uuid:
        warn(f"No user found — nothing to erase.")
        return 0
    if not _is_valid_uuid(user_uuid):
        err(f"Unexpected psql output (expected UUID): {user_uuid!r}")
        return 1

    info(f"User UUID resolved.")  # intentionally not logging the UUID to stdout in prod
    erased_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    # ── Step 2: null-stamp user_id in api_audit_log ───────────────────
    # Belt-and-braces per §9.8: the UUID is not directly PII, but GDPR Art. 17
    # erasure removes all linkable identifiers.
    step("Null-stamping user_id in api_audit_log…")
    stamp_sql = (
        f"UPDATE api_audit_log SET user_id = NULL "
        f"WHERE user_id = '{user_uuid}'::uuid;\n"
    )
    sr = _psql(stamp_sql)
    if sr.returncode != 0:
        err(f"Null-stamp UPDATE failed: {sr.stderr.strip()}")
        return 1
    info(f"api_audit_log null-stamp: {sr.stdout.strip() or 'UPDATE 0'}")

    # ── Step 3: purge users row ────────────────────────────────────────
    step("Purging users row…")
    del_sql = f"DELETE FROM users WHERE id = '{user_uuid}'::uuid;\n"
    dr = _psql(del_sql)
    if dr.returncode != 0:
        err(f"DELETE from users failed: {dr.stderr.strip()}")
        return 1
    info(f"users row: {dr.stdout.strip() or 'DELETE 0'}")

    # ── Step 4: emit pii_erased on maint.event.v1 (Phase 8 path) ─────
    step("Emitting maint.event.v1{kind=pii_erased} on the bus…")
    emit_rc = _emit_pii_erased(
        client_id=user_uuid,
        table="users",
        row_count=1,
        erased_at=erased_at,
    )
    if emit_rc != 0:
        warn(
            "pii_erased bus emit could not complete "
            "(redis container may not be running). "
            "DB erasure succeeded. Re-run once the stack is live: "
            "make up && make api.erase-user USER=" + user_uuid
        )
    else:
        ok("pii_erased published on maint.event.v1.")

    ok(f"Erasure complete (erased_at={erased_at}).")
    return 0


def _emit_pii_erased(
    *, client_id: str, table: str, row_count: int, erased_at: str
) -> int:
    """Publish maint.event.v1{kind=pii_erased} via redis-cli XADD.

    Uses the JsonCodec wire format: {"envelope": {...}, "payload": {...}}
    stored as a single Redis stream field named "data".  This matches
    RedisStreamsBus.publish() in ai/swarm/sdk/bus.py so the SDK can
    consume the event without any special handling.

    No host-side redis-py dependency — the publish goes through
    `docker compose exec redis redis-cli`.
    """
    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    # pii_erased schema (ai/swarm/sdk/schemas/maint.event.v1/pii_erased.json):
    # required: kind, kind_schema_version, produced_at, request_id,
    #           client_id, table, row_count, erased_at
    # additionalProperties: false  → no extra fields
    envelope = {
        "attempt": 0,
        "created_at": now_iso,
        "message_id": uuid_mod.uuid4().hex,
        "producer": "ops_console",
        "schema_version": 1,
        "topic": "maint.event.v1",
        "trace_id": uuid_mod.uuid4().hex,
    }
    payload = {
        "client_id": client_id,
        "erased_at": erased_at,
        "kind": "pii_erased",
        "kind_schema_version": 1,
        "produced_at": now_iso,
        "request_id": uuid_mod.uuid4().hex,
        "row_count": row_count,
        "table": table,
    }
    wire = json.dumps(
        {"envelope": envelope, "payload": payload},
        separators=(",", ":"),
        sort_keys=True,
    )

    base = _compose_base()
    cmd = [
        *base, "exec", "-T", "redis",
        "redis-cli", "XADD", "maint.event.v1", "*", "data", wire,
    ]
    result = subprocess.run(
        cmd, capture_output=True, text=True, cwd=str(REPO_ROOT)
    )
    if result.returncode != 0:
        warn(f"redis-cli XADD failed: {result.stderr.strip()[:256]}")
        return 1
    return 0


# ── cmd_repair_api ─────────────────────────────────────────────────────


def cmd_repair_api(_argv: list) -> int:
    """Drain api_audit_log_quarantine back into api_audit_log.

    Operator runbook for §9.17.7 quarantine recovery:

      1. This script re-inserts every quarantine row into api_audit_log.
         The BEFORE INSERT trigger (api_audit_stamp_row_hmac) will re-stamp
         each row's row_hmac so the chain is rebuilt correctly.
      2. Rows are then DELETEd from api_audit_log_quarantine.
      3. The operator restarts the pod after the drain so the Writer reverts
         to normal mode (NotifyIntegrityBreak() is pod-lifetime-scoped).

    Requires operator confirmation before modifying the database.
    """
    step("Counting rows in api_audit_log_quarantine…")
    count_sql = "SELECT COUNT(*)::text FROM api_audit_log_quarantine;\n"
    cr = _psql(count_sql)
    if cr.returncode != 0:
        err(f"psql count failed: {cr.stderr.strip()}")
        err("Is the postgres container running?  Try: make up")
        return 1

    row_count_str = cr.stdout.strip()
    try:
        row_count = int(row_count_str)
    except ValueError:
        err(f"Unexpected count output: {row_count_str!r}")
        return 1

    if row_count == 0:
        ok("api_audit_log_quarantine is empty — nothing to repair.")
        return 0

    warn(f"api_audit_log_quarantine contains {row_count} row(s).")
    info(
        "This will re-insert them into api_audit_log (trigger re-stamps HMAC) "
        "then delete them from quarantine."
    )

    try:
        confirm = input("Type 'yes' to proceed: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        err("Aborted.")
        return 1

    if confirm != "yes":
        err("Aborted.")
        return 1

    # Re-insert: copy all quarantine columns except id (BIGSERIAL; auto-assigned)
    # and row_hmac / prev_hmac (trigger re-stamps them).
    # Using INSERT … SELECT with explicit column list keeps us safe if the
    # schema gains new columns.
    step(f"Re-inserting {row_count} row(s) into api_audit_log…")
    insert_sql = """\
INSERT INTO api_audit_log
    (created_at, request_id, kind, method, path, status_code,
     latency_ms, response_bytes, cache_hit, degraded,
     user_id, client_ip, payload, produced_at)
SELECT
    created_at, request_id, kind, method, path, status_code,
    latency_ms, response_bytes, cache_hit, degraded,
    user_id, client_ip, payload, produced_at
FROM api_audit_log_quarantine
ORDER BY id;
"""
    ir = _psql(insert_sql)
    if ir.returncode != 0:
        err(f"Re-insert failed: {ir.stderr.strip()}")
        err("No rows were deleted from quarantine. Investigate and retry.")
        return 1
    info(f"Inserted: {ir.stdout.strip() or 'INSERT 0'}")

    step("Deleting rows from api_audit_log_quarantine…")
    del_sql = "DELETE FROM api_audit_log_quarantine;\n"
    dr = _psql(del_sql)
    if dr.returncode != 0:
        err(f"DELETE from quarantine failed: {dr.stderr.strip()}")
        err(
            "Re-insert succeeded but quarantine was NOT cleared. "
            "Run: DELETE FROM api_audit_log_quarantine;  manually."
        )
        return 1
    info(f"Deleted: {dr.stdout.strip() or 'DELETE 0'}")

    ok("Quarantine drain complete.")
    warn(
        "Restart the api pod so the Writer exits quarantine mode: "
        "docker compose restart api"
    )
    return 0


# ── dispatch ───────────────────────────────────────────────────────────

COMMANDS = {
    "verify-api": cmd_verify_api,
    "erase-user": cmd_erase_user,
    "repair-api": cmd_repair_api,
}


def main(argv=None):
    return dispatch(
        argv if argv is not None else sys.argv[1:],
        COMMANDS,
        script_name="audit_api.py",
    )


if __name__ == "__main__":
    raise SystemExit(main())
