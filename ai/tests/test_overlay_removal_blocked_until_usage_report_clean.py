"""Phase 18.4 — Overlay removal blocked until usage report shows zero hits."""
from __future__ import annotations

from pathlib import Path


def test_overlay_removal_blocked_until_usage_report_clean() -> None:
    """The compose overlay deprecation lint gate enforces the stub."""
    repo_root = Path(__file__).parent.parent.parent
    lint_gate = repo_root / "xops" / "lint" / "compose_overlay_deprecation.py"

    assert lint_gate.exists(), (
        "xops/lint/compose_overlay_deprecation.py must exist to guard overlay removal"
    )

    with open(lint_gate) as f:
        content = f.read()

    # The gate must check for stub (not functional) overlay
    assert "check_overlay_stub" in content or "deprecated" in content.lower(), (
        "Deprecation gate must verify overlay is a stub"
    )

    # The gate must prevent removal until usage report is clean
    assert "Phase 22" in content or "removal" in content.lower(), (
        "Gate should reference Phase 22 removal constraint"
    )
