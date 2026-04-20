#!/usr/bin/env python3
"""
`make api ENDPOINT=<path> METHOD=<verb>`

Calls the local Go server REST API. Replaces the curl + bash pipeline
with stdlib urllib + json, so it works on Windows out of the box.

Examples:
    make api ENDPOINT=health
    make api ENDPOINT=matches
    make api ENDPOINT=teams
    make api ENDPOINT=scrape/trigger METHOD=POST
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Optional
from urllib import error as urlerr
from urllib import request as urlreq

from _common import dispatch, info, warn

BASE = "http://localhost:8080/api/v1"


def _call(path: str, *, method: str = "GET", timeout: float = 5.0) -> Optional[dict]:
    if not path.startswith("/"):
        path = "/" + path
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


def cmd_call(argv):
    p = argparse.ArgumentParser(prog="server_api.py call")
    p.add_argument("--endpoint", required=True,
                   help="Path under /api/v1, e.g. 'health', 'matches', 'scrape/trigger'.")
    p.add_argument("--method", default="GET")
    a = p.parse_args(argv)
    data = _call(a.endpoint, method=a.method.upper())
    if data is not None:
        _print_json(data)
        if a.endpoint.strip("/") == "matches" and isinstance(data, list) and not data:
            print()
            info("Empty? Run: make db.seed  (imports local JSON cache into PostgreSQL)")


COMMANDS = {
    "call": cmd_call,
}


def main(argv=None):
    return dispatch(
        argv if argv is not None else sys.argv[1:],
        COMMANDS,
        script_name="server_api.py",
    )


if __name__ == "__main__":
    raise SystemExit(main())
