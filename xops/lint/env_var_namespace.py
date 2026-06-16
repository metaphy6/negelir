#!/usr/bin/env python3
"""
Phase 18.7 ledger #28 — env-var namespace CI lint.

Asserts every entry in xops/env/.env.example matches the regex:
  ^NEGELIR_(DATASOURCE|SWARM|SERVER|COMMON|PATCHER|GITOPS|INFRA|DOCS)_[A-Z0-9_]+=

Legacy un-namespaced vars in a deprecation window (cfg.env_var_alias_days, default 90)
are allowed but flagged.
"""

import re
import sys
from pathlib import Path


_COMPONENT_NAMESPACED_PATTERN = re.compile(
    r"^NEGELIR_(DATASOURCE|SWARM|SERVER|COMMON|PATCHER|GITOPS|INFRA|DOCS)_[A-Z0-9_]+="
)

_ENV_FILE = Path(__file__).resolve().parent.parent / "env" / ".env.example"


def lint_env_vars() -> int:
    """Check that all NEGELIR_* keys are component-namespaced.
    
    Returns:
        0 if all keys pass; 1 otherwise.
    """
    violations = []
    in_deprecation_window = False
    
    if not _ENV_FILE.exists():
        print(f"ERROR: {_ENV_FILE} not found", file=sys.stderr)
        return 1
    
    with open(_ENV_FILE, encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, 1):
            line_stripped = line.strip()
            
            # Check if we've entered the deprecation window section
            if "Legacy (deprecated, 90-day alias window):" in line:
                in_deprecation_window = True
                continue
            
            # Skip comments, empty lines
            if not line_stripped or line_stripped.startswith("#"):
                continue
            
            # Check if it's a variable assignment
            if "=" not in line_stripped:
                continue
            
            key = line_stripped.split("=")[0].strip()
            
            # Check if it matches the required pattern
            if key.startswith("NEGELIR_") and not _COMPONENT_NAMESPACED_PATTERN.match(line_stripped):
                violations.append((line_no, key, "does not match NEGELIR_<COMPONENT>_ pattern"))
            
            # Check for legacy POSTGRES_, REDIS_, etc. (these should ONLY appear in deprecation window)
            if key.startswith(("POSTGRES_", "REDIS_", "DB_", "HTTP_", "CACHE_", "SERVER_", "SCRAPE_", "AI_")):
                if not in_deprecation_window:
                    violations.append((line_no, key, "legacy prefix; must be in 'Legacy (deprecated, 90-day alias window):' section"))
    
    if violations:
        print("Env-var namespace violations:", file=sys.stderr)
        for line_no, key, reason in violations:
            print(f"  Line {line_no}: {key:<50} {reason}", file=sys.stderr)
        return 1
    
    print(f"✓ All {len([1 for line in _ENV_FILE.read_text().splitlines() if '=' in line and not line.strip().startswith('#')])} env vars are component-namespaced.")
    return 0


if __name__ == "__main__":
    sys.exit(lint_env_vars())
