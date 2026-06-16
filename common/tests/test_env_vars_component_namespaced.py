"""Phase 18.7 ledger #28 proof test: env vars are component-namespaced."""

import os
import re
from pathlib import Path


_PATTERN = re.compile(
    r"^NEGELIR_(DATASOURCE|SWARM|SERVER|COMMON|PATCHER|GITOPS|INFRA|DOCS)_[A-Z0-9_]+="
)

_ENV_FILE = Path(__file__).resolve().parent.parent.parent / "xops" / "env" / ".env.example"


def test_env_vars_component_namespaced() -> None:
    """Every NEGELIR_* var in .env.example must match the component namespace pattern."""
    assert _ENV_FILE.exists(), f"{_ENV_FILE} not found"
    
    violations = []
    with open(_ENV_FILE, encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            
            key = line.split("=")[0].strip()
            if key.startswith("NEGELIR_") and not _PATTERN.match(line):
                violations.append((line_no, key))
    
    assert not violations, f"Found {len(violations)} non-namespaced vars:\n" + "\n".join(
        f"  Line {ln}: {key}" for ln, key in violations
    )


if __name__ == "__main__":
    test_env_vars_component_namespaced()
    print("✓ All NEGELIR_* vars are component-namespaced")
