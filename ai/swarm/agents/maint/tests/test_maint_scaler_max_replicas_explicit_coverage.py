"""Phase 8 §8.16.1 — warn-only lint coverage test.

Doctrine:

> The §8.9 boundary test that previously asserted "every registered
> agent has an explicit cfg entry" downgrades to a *lint* test
> (warn-only, doesn't fail CI) named
> ``test_maint_scaler_max_replicas_explicit_coverage`` — operators
> are nudged toward explicit declarations without blocking releases.

This test ALWAYS PASSES. Its only job is to surface a stderr warning
listing agents that are registered in :func:`build_default_agents`
but missing from
``cfg.maint_scaler_max_replicas_overrides_csv``. Operators chasing
deployment ergonomics noise can read the warning and add the
entries; nothing here fails their build.
"""
from __future__ import annotations

import warnings

from common.config import cfg
from swarm.agents.maint.scaler import _parse_overrides_csv
from swarm.bootstrap import build_agents


def test_maint_scaler_max_replicas_explicit_coverage() -> None:
    overrides = _parse_overrides_csv(
        str(cfg.maint_scaler_max_replicas_overrides_csv)
    )
    try:
        agents = build_agents()
    except Exception as exc:  # pragma: no cover — bootstrap path drift
        warnings.warn(
            f"build_agents() raised {type(exc).__name__}: {exc}; "
            "skipping max_replicas coverage lint",
            stacklevel=1,
        )
        return
    registered = sorted({getattr(a, "name", "") for a in agents if getattr(a, "name", "")})
    missing = [
        name for name in registered
        if name not in overrides
    ]
    if missing:
        warnings.warn(
            "maint_scaler max_replicas coverage gap (warn-only per "
            "ROADMAP §8.16.1): the following agents have no entry in "
            "cfg.maint_scaler_max_replicas_overrides_csv and will use "
            "the default-policy fallback (or legacy global cap when "
            "cfg.maint_scaler_default_max_replicas=0). Add explicit "
            "entries to raise the operator signal-to-noise ratio:\n  - "
            + "\n  - ".join(missing),
            stacklevel=1,
        )
    # Always pass — this is a lint, not a gate.
    assert True
