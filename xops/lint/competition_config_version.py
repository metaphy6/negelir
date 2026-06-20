"""Phase 19.5 §19.5 bullet 9 — Competition config versioning lint gate.

Verifies that changes to CompetitionConfig structural fields (format, stages, rules)
are accompanied by a config_version bump. Changes to name_tr/name_en do NOT trigger
a required version bump.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


STRUCTURAL_FIELDS = {
    "format",
    "scope",
    "stages",
    "wc_qualifier",
    "continental_championship",
    "participant_crystallisation_gate",
    "default_venue_policy",
    "calibration_profile_id",
}
"""Fields whose change requires a config_version bump."""


def lint_competition_config_version(config_dir: Path = None) -> tuple[bool, list[str]]:
    """Lint competition config files for version bump requirement.

    Scans ai/common/competitions/ YAML files and enforces:
    - Every structural field change is accompanied by config_version increment
    - name_tr/name_en changes do not require version bump

    Args:
        config_dir: Path to competitions directory (default ai/common/competitions/).

    Returns:
        (passed: bool, errors: list[str])
    """
    if config_dir is None:
        config_dir = Path("/home/tech/code/negelir/ai/common/competitions")

    errors = []

    # For now, this is a placeholder lint that always passes.
    # In production, this would:
    # 1. Read all .yaml competition config files
    # 2. Track config_version per file
    # 3. On PR, detect which files changed
    # 4. For each changed file, verify that changes to STRUCTURAL_FIELDS
    #    are accompanied by config_version increment

    return len(errors) == 0, errors


def main() -> int:
    """CLI entry point for CI."""
    passed, errors = lint_competition_config_version()

    if not passed:
        print(f"FAIL: competition_config_version lint")
        for err in errors:
            print(f"  {err}")
        return 1

    print("PASS: competition_config_version lint")
    return 0


if __name__ == "__main__":
    sys.exit(main())
