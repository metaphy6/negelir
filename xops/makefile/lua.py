#!/usr/bin/env python3
"""`make verify.lua` — Phase 7 §7.3 Lua-script integrity gate.

The Go gateway loads `infra/redis/lua/*.lua` via `EVALSHA`, keyed
on each script's sha256. A silent edit to the script file would
leave the in-memory cache stale (since the SHA1 Redis uses for
EVALSHA changes only when scripts are reloaded) AND would let a
human-introduced bug ship without anyone noticing the bytes shifted.

The contract: every script carries two header lines that the agent
re-derives from its own bytes. Drift = build-blocking failure.

    -- VERSION: <semver>
    -- SHA256: <hex digest of the file with the SHA256 line replaced
              by the placeholder string "PLACEHOLDER">

Subcommands:
    verify   — read every .lua, fail if header doesn't match recompute
    fix      — rewrite header to match current bytes (use after intended edits)
"""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _common import dispatch  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
LUA_DIR = REPO_ROOT / "infra" / "redis" / "lua"
PLACEHOLDER = "PLACEHOLDER"
SHA_LINE_RE = re.compile(r"^-- SHA256: (.+)$", re.MULTILINE)
VERSION_LINE_RE = re.compile(r"^-- VERSION: (.+)$", re.MULTILINE)


def _expected_sha(text: str) -> str:
    """Recompute the digest with the SHA line stripped to placeholder.

    Done over UTF-8 bytes so the digest is portable across LF/CRLF
    checkouts: callers must keep these files LF-only (CI enforces).
    """
    normalized = SHA_LINE_RE.sub(f"-- SHA256: {PLACEHOLDER}", text, count=1)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _scripts() -> list[Path]:
    if not LUA_DIR.exists():
        return []
    return sorted(LUA_DIR.glob("*.lua"))


def cmd_verify(_argv):
    scripts = _scripts()
    if not scripts:
        print(f"verify.lua: no scripts under {LUA_DIR}", file=sys.stderr)
        return 1
    failures = []
    for path in scripts:
        text = path.read_text(encoding="utf-8")
        ver_match = VERSION_LINE_RE.search(text)
        sha_match = SHA_LINE_RE.search(text)
        if not ver_match:
            failures.append(f"{path.name}: missing `-- VERSION:` header")
            continue
        if not sha_match:
            failures.append(f"{path.name}: missing `-- SHA256:` header")
            continue
        actual = sha_match.group(1).strip()
        expected = _expected_sha(text)
        if actual == PLACEHOLDER:
            failures.append(
                f"{path.name}: SHA header is still PLACEHOLDER — run "
                f"`make verify.lua fix` after intended edits"
            )
            continue
        if actual != expected:
            failures.append(
                f"{path.name}: SHA mismatch\n"
                f"  header   = {actual}\n"
                f"  computed = {expected}"
            )
        else:
            print(f"  ok  {path.name}  v{ver_match.group(1).strip()}  {actual[:12]}…")
    if failures:
        print("\nverify.lua: FAILED", file=sys.stderr)
        for line in failures:
            print(f"  {line}", file=sys.stderr)
        return 1
    print(f"verify.lua: {len(scripts)} script(s) ok")
    return 0


def cmd_fix(_argv):
    scripts = _scripts()
    if not scripts:
        print(f"verify.lua: no scripts under {LUA_DIR}", file=sys.stderr)
        return 1
    rewritten = 0
    for path in scripts:
        text = path.read_text(encoding="utf-8")
        if not SHA_LINE_RE.search(text):
            print(f"  skip  {path.name}: no SHA header to rewrite", file=sys.stderr)
            continue
        expected = _expected_sha(text)
        new_text = SHA_LINE_RE.sub(f"-- SHA256: {expected}", text, count=1)
        if new_text != text:
            path.write_text(new_text, encoding="utf-8")
            print(f"  fixed {path.name} -> {expected[:12]}…")
            rewritten += 1
        else:
            print(f"  ok    {path.name}")
    print(f"verify.lua: {rewritten} script(s) rewritten")
    return 0


COMMANDS = {
    "verify": cmd_verify,
    "fix": cmd_fix,
}


def main(argv=None):
    return dispatch(
        argv if argv is not None else sys.argv[1:],
        COMMANDS,
        script_name="lua.py",
    )


if __name__ == "__main__":
    raise SystemExit(main())
