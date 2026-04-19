#!/usr/bin/env python3
"""
`make server-scrape|server-health|server-matches|server-teams`

Replaces the curl + bash pipeline with stdlib urllib + json.tool, so it
works on Windows out of the box (no curl required).
"""

from __future__ import annotations

import json
import sys
from typing import Optional
from urllib import error as urlerr
from urllib import request as urlreq

from _common import dispatch, info, warn

BASE = "http://localhost:8080/api/v1"


def _call(path: str, *, method: str = "GET", timeout: float = 5.0) -> Optional[dict]:
    url = f"{BASE}{path}"
    req = urlreq.Request(url, method=method)
    try:
        with urlreq.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
    except (urlerr.URLError, ConnectionError, TimeoutError) as exc:
        warn(f"Server not reachable at {url}: {exc}. Run 'make server' first.")
        return None
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        print(body)
        return None


def _print_json(data) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False))


def cmd_scrape(_argv):
    data = _call("/scrape/trigger", method="POST")
    if data is not None:
        _print_json(data)


def cmd_health(_argv):
    data = _call("/health")
    if data is not None:
        _print_json(data)


def cmd_matches(_argv):
    data = _call("/matches")
    if data is not None:
        _print_json(data)
        print()
        info("Empty? Run: make db-seed  (imports local JSON cache into PostgreSQL)")


def cmd_teams(_argv):
    data = _call("/teams")
    if data is not None:
        _print_json(data)


COMMANDS = {
    "server-scrape": cmd_scrape,
    "server-health": cmd_health,
    "server-matches": cmd_matches,
    "server-teams": cmd_teams,
}


def main(argv=None):
    return dispatch(
        argv if argv is not None else sys.argv[1:],
        COMMANDS,
        script_name="server_api.py",
    )


if __name__ == "__main__":
    raise SystemExit(main())
