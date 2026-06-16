"""Phase 18.7 — Component-namespaced env vars (ledger #28).

All NEGELIR_* entries in xops/env/.env.example must match the pattern:
  ^NEGELIR_(DATASOURCE|SWARM|SERVER|COMMON|PATCHER|GITOPS|INFRA|DOCS)_[A-Z0-9_]+=
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_EXAMPLE = REPO_ROOT / "xops" / "env" / ".env.example"

# Valid NEGELIR_* namespace pattern
NAMESPACED_PATTERN = re.compile(
    r"^NEGELIR_(DATASOURCE|SWARM|SERVER|COMMON|PATCHER|GITOPS|INFRA|DOCS)_[A-Z0-9_]+="
)


@pytest.mark.slow
def test_env_vars_component_namespaced() -> None:
    """Every NEGELIR_* var in .env.example must be component-namespaced."""
    assert ENV_EXAMPLE.exists(), f"{ENV_EXAMPLE} does not exist"

    content = ENV_EXAMPLE.read_text(encoding="utf-8")
    lines = content.splitlines()

    violations = []
    for line_num, line in enumerate(lines, 1):
        line = line.strip()
        # Skip comments and empty lines
        if not line or line.startswith("#"):
            continue

        # Check if it's a NEGELIR_* var
        if line.startswith("NEGELIR_"):
            if not NAMESPACED_PATTERN.match(line):
                violations.append((line_num, line))

    if violations:
        msg = "NEGELIR_* vars must be component-namespaced:\n"
        for line_num, line in violations:
            msg += f"  Line {line_num}: {line}\n"
        pytest.fail(msg)
