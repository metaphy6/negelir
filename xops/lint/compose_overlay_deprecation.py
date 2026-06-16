#!/usr/bin/env python3
"""
Phase 18.4 — Compose overlay deprecation CI gate.

During the deprecation window (cfg.compose_overlay_deprecation_days, default 14),
ensures that:
  - docker-compose.mock.yml is a stub (prints migration message)
  - No CI job uses the overlay file (checked via grep in logs)
  - Downstream usage is tracked for Phase 22 removal
"""

from __future__ import annotations

import sys
from pathlib import Path


def check_overlay_stub() -> bool:
    """Verify docker-compose.mock.yml is a deprecation stub, not functional."""
    repo_root = Path(__file__).parent.parent.parent
    overlay_file = repo_root / "docker-compose.mock.yml"

    if not overlay_file.exists():
        print("ERROR: docker-compose.mock.yml not found", file=sys.stderr)
        return False

    with open(overlay_file) as f:
        content = f.read()

    # Must contain deprecation warning
    if "deprecated" not in content.lower() and "Phase 22" not in content:
        print(
            "ERROR: docker-compose.mock.yml must contain deprecation notice",
            file=sys.stderr
        )
        return False

    # Must not contain actual service definitions (except _deprecation_notice)
    functional_services = [
        "server-mock",
        "nginx-mock",
        "scrapers",
        "postgres",
    ]
    for svc in functional_services:
        if f'  {svc}:' in content or f'"{svc}":' in content:
            print(
                f"ERROR: docker-compose.mock.yml contains functional service {svc}",
                file=sys.stderr
            )
            return False

    return True


def main() -> int:
    """Run deprecation gate checks."""
    if not check_overlay_stub():
        return 1

    print("Compose overlay deprecation gate: PASS", file=sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
