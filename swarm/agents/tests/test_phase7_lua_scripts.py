"""Phase 7 §7.3 — Lua-script integrity gate.

The Go gateway loads `infra/redis/lua/sec_*.lua` via `EVALSHA`, keyed
on each script's sha256. A silent edit would leave the gateway's
in-memory cache stale AND let a human-introduced bug ship undetected.
This test re-runs `make verify.lua` logic in-process so a stale header
fails CI just like any other broken contract.
"""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
LUA_DIR = REPO_ROOT / "infra" / "redis" / "lua"
PLACEHOLDER = "PLACEHOLDER"

# Make `xops/makefile/lua.py` importable so we exercise the SAME code
# the human runs locally — no parallel implementation that could drift.
sys.path.insert(0, str(REPO_ROOT / "xops" / "makefile"))


def test_lua_dir_exists() -> None:
    assert LUA_DIR.is_dir(), f"missing {LUA_DIR}"


def test_lua_scripts_have_required_headers() -> None:
    scripts = sorted(LUA_DIR.glob("*.lua"))
    assert scripts, "no Lua scripts present — Phase 7 §7.3 not landed"
    for path in scripts:
        text = path.read_text(encoding="utf-8")
        assert re.search(r"^-- VERSION: ", text, re.MULTILINE), (
            f"{path.name}: missing `-- VERSION:` header"
        )
        assert re.search(r"^-- SHA256: ", text, re.MULTILINE), (
            f"{path.name}: missing `-- SHA256:` header"
        )


def test_lua_sha_headers_match_recompute() -> None:
    """Drift-detection. `make verify.lua` is the canonical entry point;
    we reimplement the digest here ONLY to assert the same bytes from
    a different angle — if both paths agree the gate is safe.
    """
    scripts = sorted(LUA_DIR.glob("*.lua"))
    sha_re = re.compile(r"^-- SHA256: (.+)$", re.MULTILINE)
    for path in scripts:
        text = path.read_text(encoding="utf-8")
        m = sha_re.search(text)
        assert m, f"{path.name}: no SHA line"
        actual = m.group(1).strip()
        assert actual != PLACEHOLDER, (
            f"{path.name}: SHA header still PLACEHOLDER — run `make fix.lua`"
        )
        normalized = sha_re.sub(f"-- SHA256: {PLACEHOLDER}", text, count=1)
        expected = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        assert actual == expected, (
            f"{path.name}: SHA header out of date\n"
            f"  header   = {actual}\n"
            f"  computed = {expected}\n"
            "Edit the script intentionally? Run `make fix.lua` and commit."
        )


def test_lua_verify_cli_returns_zero() -> None:
    """End-to-end: invoke the verifier the way CI/the human does."""
    import lua  # type: ignore[import-not-found]

    rc = lua.cmd_verify([])
    assert rc == 0, "lua.cmd_verify reported failure — see stderr"


def test_required_phase7_scripts_present() -> None:
    """Pin the set of scripts Phase 7 §7.3 says must exist. Adding or
    removing a script must be a deliberate, reviewed change."""
    have = {p.name for p in LUA_DIR.glob("*.lua")}
    want = {"sec_rate_check.lua", "sec_denylist_mutate.lua"}
    missing = want - have
    assert not missing, f"missing required Phase 7 Lua scripts: {missing}"
