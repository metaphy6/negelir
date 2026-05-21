#!/usr/bin/env python3
"""`make codegraph.*` — CodeGraph MCP server lifecycle dispatcher.

Subcommands:

    status   — sanity-check the local index (agent-safe, cheap)
    reindex  — rebuild the index from scratch (after big refactors)
    check    — query npm for the latest version and compare to the pin
    upgrade  — bump the pinned version across all 5 wirings in lockstep
               (4 MCP configs + the docs guide), reindex, and remind
               the human to run `make version.bump COMPONENT=codegraph …`

The pinned npm version is stored *inline* in each wiring file (no
separate manifest) — this is what every agent spawn actually resolves,
so it is also the single source of truth this script edits.

Doctrine notes:
    • The npm pin is intentionally explicit. `@latest` is rejected
      because it would re-resolve on every `npx` spawn (network on
      every agent startup), silently drift across developers, and
      bypass the audit trail in `xops/versioning/chart.json`.
    • This script never installs anything globally — every invocation
      goes through `npx -y`. Sanctioned host-tool exception per
      AGENTS.md §2 Rule 2.
    • Agents may run `status`, `reindex`, and `check`. `upgrade`
      mutates committed config files; the human still drives
      `make git` to land them.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from xops.makefile._common import dispatch, err  # noqa: E402

# ── Constants ─────────────────────────────────────────────────

NPM_PACKAGE = "@colbymchenry/codegraph"

# Files that embed the pinned version. Order = update order.
WIRING_FILES: List[Path] = [
    REPO_ROOT / ".vscode" / "mcp.json",
    REPO_ROOT / ".mcp.json",
    REPO_ROOT / ".cursor" / "mcp.json",
    REPO_ROOT / "docs" / "guides" / "CODEGRAPH.md",
]

# User-global Codex config — outside the repo, mentioned for the human.
CODEX_GLOBAL_HINT = Path.home() / ".codex" / "config.toml"

# Matches `@colbymchenry/codegraph@X.Y.Z` (semver, optional pre-release).
PIN_RE = re.compile(
    rf"({re.escape(NPM_PACKAGE)})@(\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.\-]+)?)"
)

# ── npx wrapper ───────────────────────────────────────────────


def _have(binary: str) -> bool:
    return shutil.which(binary) is not None


def _npx(args: List[str]) -> int:
    """Run `npx -y @colbymchenry/codegraph@<pin> <args>` against repo root."""
    if not _have("npx"):
        err("npx not found on PATH — install Node.js 20–24.")
        return 127
    pin = _read_pin()
    if pin is None:
        err("Could not determine pinned codegraph version. "
            "Check .vscode/mcp.json.")
        return 1
    cmd = ["npx", "-y", f"{NPM_PACKAGE}@{pin}", *args]
    return subprocess.call(cmd, cwd=str(REPO_ROOT))


# ── Pin discovery ─────────────────────────────────────────────


def _read_pin() -> Optional[str]:
    """Return the pinned version found in .vscode/mcp.json (the
    canonical wiring — all others must match it)."""
    canonical = REPO_ROOT / ".vscode" / "mcp.json"
    if not canonical.is_file():
        return None
    text = canonical.read_text(encoding="utf-8")
    match = PIN_RE.search(text)
    return match.group(2) if match else None


def _audit_pins() -> Tuple[Optional[str], List[Tuple[Path, str]]]:
    """Return (canonical_pin, mismatches). Mismatches is a list of
    (file, found_version) for any wiring file whose pin differs from
    the canonical one or is missing entirely."""
    canonical = _read_pin()
    mismatches: List[Tuple[Path, str]] = []
    for path in WIRING_FILES:
        if not path.is_file():
            mismatches.append((path, "<missing file>"))
            continue
        text = path.read_text(encoding="utf-8")
        match = PIN_RE.search(text)
        if not match:
            mismatches.append((path, "<no pin found>"))
        elif match.group(2) != canonical:
            mismatches.append((path, match.group(2)))
    return canonical, mismatches


# ── npm metadata ──────────────────────────────────────────────


def _npm_latest() -> Optional[str]:
    """Query npm registry for the latest published version. Returns
    None if npm is unreachable."""
    if not _have("npm"):
        err("npm not found on PATH — install Node.js 20–24.")
        return None
    try:
        out = subprocess.check_output(
            ["npm", "view", NPM_PACKAGE, "version"],
            cwd=str(REPO_ROOT),
            stderr=subprocess.STDOUT,
            timeout=20,
        )
        return out.decode().strip() or None
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        err(f"npm view failed: {e}")
        return None


def _semver_tuple(version: str) -> Tuple[int, int, int]:
    base = version.split("-", 1)[0].split("+", 1)[0]
    parts = base.split(".")
    return tuple(int(p) for p in parts[:3])  # type: ignore[return-value]


def _semver_level(old: str, new: str) -> str:
    o = _semver_tuple(old)
    n = _semver_tuple(new)
    if n[0] != o[0]:
        return "major"
    if n[1] != o[1]:
        return "minor"
    return "patch"


# ── Commands ──────────────────────────────────────────────────


def cmd_status(_argv: List[str]) -> int:
    """Cheap health check. Agents should run this after large diffs."""
    rc = _npx(["status"])
    if rc == 0:
        print()
        print("→ Tip: if structure looks stale, run `make codegraph.reindex`.")
    return rc


def cmd_reindex(_argv: List[str]) -> int:
    """Force a full rebuild. Run after big refactors, mass renames,
    or a `git rebase` that moved many files."""
    print(f"→ Rebuilding CodeGraph index at {REPO_ROOT / '.codegraph'} …")
    rc = _npx(["init", "-i"])
    if rc != 0:
        return rc
    print()
    print("→ Verifying …")
    return _npx(["status"])


def cmd_check(_argv: List[str]) -> int:
    """Print pinned vs latest. Audit all 4 wirings agree. Exit 0
    even if behind — this is informational. Agents can grep stdout."""
    pinned, mismatches = _audit_pins()
    latest = _npm_latest()

    print(f"package:    {NPM_PACKAGE}")
    print(f"pinned:     {pinned or '<unknown>'}")
    print(f"latest:     {latest or '<offline>'}")
    print()

    if mismatches:
        err("⚠ wiring drift detected:")
        for path, found in mismatches:
            rel = path.relative_to(REPO_ROOT)
            err(f"    {rel}: {found}")
        err("  fix with: make codegraph.upgrade VERSION=<pin>")
        print()

    if pinned and latest and pinned != latest:
        level = _semver_level(pinned, latest)
        print(f"→ upgrade available ({level}): {pinned} → {latest}")
        print(f"  run: make codegraph.upgrade")
        print(f"       (or pin a specific version: "
              f"make codegraph.upgrade VERSION={latest})")
    elif pinned and latest and pinned == latest:
        print("✓ pin matches latest")

    if not CODEX_GLOBAL_HINT.is_file():
        return 0
    text = CODEX_GLOBAL_HINT.read_text(encoding="utf-8", errors="replace")
    match = PIN_RE.search(text)
    if match and pinned and match.group(2) != pinned:
        print()
        print(f"→ ~/.codex/config.toml is at {match.group(2)} — "
              f"update by hand (user-global, not in repo).")
    return 0


def cmd_upgrade(argv: List[str]) -> int:
    """Bump the pin across all 4 wiring files in lockstep, reindex,
    then remind the human to record the bump in chart.json.

    Args (via env vars, parsed by Make):
        VERSION  — explicit target (e.g. 0.9.1). Default: latest from npm.
    """
    import os

    target = os.environ.get("VERSION", "").strip()
    if not target:
        target = _npm_latest() or ""
        if not target:
            err("Could not resolve latest from npm and no VERSION= override given.")
            return 1

    old = _read_pin()
    if old is None:
        err("No canonical pin in .vscode/mcp.json to upgrade from.")
        return 1
    if old == target:
        print(f"✓ already at {target} — nothing to do.")
        return 0

    print(f"→ bumping pin: {old} → {target}")
    for path in WIRING_FILES:
        if not path.is_file():
            err(f"  skipped (missing): {path.relative_to(REPO_ROOT)}")
            continue
        text = path.read_text(encoding="utf-8")
        new_text, n = PIN_RE.subn(rf"\1@{target}", text)
        if n == 0:
            err(f"  skipped (no pin found): {path.relative_to(REPO_ROOT)}")
            continue
        path.write_text(new_text, encoding="utf-8")
        print(f"  patched ({n}×): {path.relative_to(REPO_ROOT)}")

    # Sanity re-read
    after, mismatches = _audit_pins()
    if mismatches or after != target:
        err("upgrade left wirings inconsistent — review diff before committing.")
        return 1

    print()
    print("→ reindexing with new version …")
    rc = _npx(["init", "-i"])
    if rc != 0:
        err("reindex failed — old binary may still be cached. "
            "Try: rm -rf ~/.npm/_npx && make codegraph.reindex")
        return rc

    level = _semver_level(old, target)
    print()
    print("✓ upgrade complete. Next steps:")
    print(f"  1. make version.bump COMPONENT=codegraph LEVEL={level} \\")
    print(f"       NOTE=\"codegraph npm pin {old} → {target}\"")
    if CODEX_GLOBAL_HINT.is_file():
        print(f"  2. update ~/.codex/config.toml by hand "
              f"(user-global, not in repo): "
              f"sed -i 's/codegraph@{old}/codegraph@{target}/' "
              f"~/.codex/config.toml")
    print("  3. make git   # land the diff")
    return 0


COMMANDS = {
    "status": cmd_status,
    "reindex": cmd_reindex,
    "check": cmd_check,
    "upgrade": cmd_upgrade,
}


def main(argv: List[str]) -> int:
    return dispatch(argv, COMMANDS, script_name="codegraph.py")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
