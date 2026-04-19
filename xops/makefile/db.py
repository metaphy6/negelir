#!/usr/bin/env python3
"""
`make db-migrate|db-seed|db-shell|db-reset|redis-shell`

The original db-migrate target used a bash for-loop to apply every
migration via `docker compose exec`. Re-implemented here in Python so
Windows operators can run the same command.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

from _common import (
    COMPOSE,
    REPO_ROOT,
    compose_exec,
    compose_run,
    dispatch,
    err,
    info,
    ok,
    step,
    warn,
)


def cmd_db_migrate(_argv):
    info("🗄️  Running migrations…")
    migrations_dir = REPO_ROOT / "migrations"
    files = sorted(migrations_dir.glob("*.sql"))
    if not files:
        warn("No .sql files in migrations/")
        return 0
    for f in files:
        rel = f.relative_to(REPO_ROOT)
        step(str(rel))
        sql = f.read_text(encoding="utf-8")
        # Pipe SQL via stdin; works regardless of whether the file is
        # bind-mounted into the postgres container.
        result = subprocess.run(
            [*COMPOSE, "exec", "-T", "postgres",
             "psql", "-U", "negelir", "-d", "negelir"],
            input=sql, text=True, cwd=str(REPO_ROOT),
        )
        if result.returncode != 0:
            err(f"Migration failed: {rel}")
            return result.returncode
    ok("Migrations complete")
    return 0


def cmd_db_seed(_argv):
    info("🌱 Seeding database from local JSON cache…")
    compose_run(
        "run", "--rm",
        "-v", f"{REPO_ROOT}/data:/data:ro",
        "ai", "python", "/data/seed_db.py",
    )
    ok("Seed complete — now try: make server-matches")
    return 0


def cmd_db_shell(_argv):
    compose_run("up", "-d", "postgres")
    compose_exec("exec", "postgres", "psql", "-U", "negelir", "-d", "negelir")


def cmd_db_reset(_argv):
    warn("This will destroy all data. Press Ctrl+C within 3s to cancel.")
    try:
        time.sleep(3)
    except KeyboardInterrupt:
        warn("Aborted.")
        return 130
    compose_run("down", "-v")
    compose_run("up", "-d", "postgres")
    ok("Database reset complete")
    return 0


def cmd_redis_shell(_argv):
    compose_run("up", "-d", "redis")
    compose_exec("exec", "redis", "redis-cli")


COMMANDS = {
    "db-migrate": cmd_db_migrate,
    "db-seed": cmd_db_seed,
    "db-shell": cmd_db_shell,
    "db-reset": cmd_db_reset,
    "redis-shell": cmd_redis_shell,
}


def main(argv=None):
    return dispatch(
        argv if argv is not None else sys.argv[1:],
        COMMANDS,
        script_name="db.py",
    )


if __name__ == "__main__":
    raise SystemExit(main())
