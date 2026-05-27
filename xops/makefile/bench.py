#!/usr/bin/env python3
"""`make api.bench` — §9.17.5 per-endpoint latency budget k6 benchmark.

Targets:
    api.bench   Run the k6 benchmark against the compose stack.

The k6 script is at xops/bench/api_bench.js.  This dispatcher:
  1. Verifies that k6 is available on the host.
  2. Reads NEGELIR_API_BENCH_TARGET_RPS from the env (default 200) and
     NEGELIR_API_BENCH_BASE_URL (default http://localhost:8080).
  3. Invokes k6 run with the appropriate -e flags forwarded.

Install k6 if missing:
  macOS:   brew install k6
  Linux:   https://k6.io/docs/getting-started/installation/
  Windows: winget install k6
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from xops.makefile._common import REPO_ROOT as _R, dispatch, err, info, ok, warn  # noqa: E402

_BENCH_SCRIPT = REPO_ROOT / "xops" / "bench" / "api_bench.js"

# Environment variables forwarded to k6 with their defaults.
_K6_ENV_VARS = [
    ("NEGELIR_API_BENCH_BASE_URL",      "http://localhost:8080"),
    ("NEGELIR_API_BENCH_TARGET_RPS",    "200"),
    ("NEGELIR_API_BENCH_DURATION",      "60s"),
    ("NEGELIR_API_BENCH_MATCH_ID",      "1"),
    ("NEGELIR_API_BENCH_AUTH_EMAIL",    "bench@negelir.local"),
    ("NEGELIR_API_BENCH_AUTH_PASSWORD", "bench_password_1!"),
]


def _k6_binary() -> str | None:
    """Return the path to the k6 binary, or None if not found."""
    return shutil.which("k6")


def _install_instructions() -> str:
    platform = sys.platform
    if platform == "darwin":
        return "  brew install k6"
    if platform == "win32":
        return "  winget install k6\n  # or: choco install k6"
    # Linux fallback
    return (
        "  # Debian/Ubuntu:\n"
        "  sudo gpg -k\n"
        "  sudo gpg --no-default-keyring --keyring /usr/share/keyrings/k6-archive-keyring.gpg "
        "--keyserver hkp://keyserver.ubuntu.com:80 --recv-keys C5AD17C747E3415A3642D57D77C6C491D6AC1D69\n"
        "  echo 'deb [signed-by=/usr/share/keyrings/k6-archive-keyring.gpg] "
        "https://dl.k6.io/deb stable main' | sudo tee /etc/apt/sources.list.d/k6.list\n"
        "  sudo apt-get update && sudo apt-get install k6\n"
        "  # Or download a binary from https://k6.io/docs/getting-started/installation/"
    )


def cmd_api_bench(argv: List[str]) -> int:
    """Run the §9.17.5 per-endpoint latency benchmark via k6.

    All NEGELIR_API_BENCH_* environment variables are forwarded to k6
    via -e flags so the script picks them up regardless of whether the
    .env file is loaded by Make.
    """
    k6 = _k6_binary()
    if k6 is None:
        err(
            "k6 not found on PATH.  Install k6 to run `make api.bench`.\n"
            + _install_instructions()
        )
        return 1

    if not _BENCH_SCRIPT.is_file():
        err(f"bench script not found: {_BENCH_SCRIPT}")
        return 1

    # Build -e KEY=VALUE flags for each env var (prefer live env, fall back to default).
    env_flags: List[str] = []
    for key, default in _K6_ENV_VARS:
        value = os.environ.get(key, default)
        env_flags += ["-e", f"{key}={value}"]

    target_rps = os.environ.get("NEGELIR_API_BENCH_TARGET_RPS", "200")
    duration   = os.environ.get("NEGELIR_API_BENCH_DURATION",   "60s")
    base_url   = os.environ.get("NEGELIR_API_BENCH_BASE_URL",   "http://localhost:8080")

    info(
        f"api.bench: k6 constant-arrival-rate {target_rps} RPS "
        f"for {duration} → {base_url}"
    )
    info(f"script: {_BENCH_SCRIPT.relative_to(REPO_ROOT)}")

    cmd = [k6, "run", *env_flags, str(_BENCH_SCRIPT), *argv]
    info(" ".join(cmd))

    result = subprocess.run(cmd, cwd=str(REPO_ROOT))
    if result.returncode == 0:
        ok("api.bench: all §9.17.5 latency thresholds passed")
    else:
        err(f"api.bench: k6 exited with code {result.returncode} — threshold(s) violated")
    return result.returncode


COMMANDS = {"api.bench": cmd_api_bench}


def main(argv=None):
    return dispatch(
        argv if argv is not None else sys.argv[1:],
        COMMANDS,
        script_name="bench.py",
    )


if __name__ == "__main__":
    sys.exit(main())
