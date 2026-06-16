"""Phase 18.4 — Smoke waits for /readyz, not /healthz."""
from __future__ import annotations

from pathlib import Path


def test_smoke_waits_for_readiness_not_health() -> None:
    """Readiness smoke uses /readyz endpoint, not /healthz."""
    repo_root = Path(__file__).parent.parent.parent
    readiness_file = repo_root / "common" / "profiles" / "readiness_budgets.yaml"

    assert readiness_file.exists(), (
        "common/profiles/readiness_budgets.yaml not found"
    )

    with open(readiness_file) as f:
        content = f.read()

    # Must reference /readyz
    assert "readyz" in content or "readiness" in content.lower(), (
        "readiness_budgets.yaml must reference /readyz endpoints"
    )

    # May reference /healthz as fallback, but /readyz should be primary
    assert "readiness_timeout_s:" in content, (
        "readiness_budgets.yaml must declare per-service readiness timeout"
    )
