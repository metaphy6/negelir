"""Phase 18.7 ledger #28 proof test: env-var namespace lint runs successfully."""

import subprocess
import sys


def test_env_var_namespace_lint() -> None:
    """The env-var namespace lint passes without violations."""
    result = subprocess.run(
        [sys.executable, "xops/lint/env_var_namespace.py"],
        cwd="/home/tech/code/negelir",
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"Lint failed:\n{result.stderr}"


if __name__ == "__main__":
    test_env_var_namespace_lint()
    print("✓ Env-var namespace lint passed")
