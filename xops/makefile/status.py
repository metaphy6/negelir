#!/usr/bin/env python3
"""`make health|status|ports` — read-only inspection."""

from __future__ import annotations

import subprocess
import sys
from urllib import error as urlerr
from urllib import request as urlreq

from _common import COMPOSE, compose_exec, compose_run, dispatch


def _ok(label, hint=""):
    print(f"✅  {label} OK")


def _down(label, hint):
    print(f"❌  {label} DOWN ({hint})")


def cmd_health(_argv):
    print("🏥  Service health check…")
    # Go server
    try:
        with urlreq.urlopen("http://localhost:8080/api/v1/health", timeout=2) as r:
            _ok("Go server  ") if r.status == 200 else _down("Go server  ", "non-200")
    except (urlerr.URLError, ConnectionError, TimeoutError):
        _down("Go server  ", "run 'make server'")

    # Postgres
    pg = subprocess.run(
        [*COMPOSE, "exec", "-T", "postgres",
         "pg_isready", "-U", "negelir", "-d", "negelir", "-q"],
        capture_output=True,
    )
    _ok("PostgreSQL ") if pg.returncode == 0 else _down("PostgreSQL ", "run 'make infra'")

    # Redis
    rd = subprocess.run(
        [*COMPOSE, "exec", "-T", "redis", "redis-cli", "ping"],
        capture_output=True, text=True,
    )
    if rd.returncode == 0 and "PONG" in (rd.stdout or ""):
        _ok("Redis      ")
    else:
        _down("Redis      ", "run 'make infra'")
    return 0


def cmd_status(_argv):
    compose_exec("ps")


def cmd_ports(_argv):
    print("📡 Service Ports:")
    print("  PostgreSQL : localhost:5432")
    print("  Redis      : localhost:6379")
    print("  Go Server  : localhost:8080")
    print("")
    print("🔗 Useful URLs:")
    print("  Health     : http://localhost:8080/api/v1/health")
    print("  Matches    : http://localhost:8080/api/v1/matches")
    print("  Teams      : http://localhost:8080/api/v1/teams")
    return 0


COMMANDS = {
    "health": cmd_health,
    "status": cmd_status,
    "ports": cmd_ports,
}


def main(argv=None):
    return dispatch(
        argv if argv is not None else sys.argv[1:],
        COMMANDS,
        script_name="status.py",
    )


if __name__ == "__main__":
    raise SystemExit(main())
