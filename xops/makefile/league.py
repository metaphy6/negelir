#!/usr/bin/env python3
"""Make league.scaffold — generate new league preset + scaffold."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List

from _common import REPO_ROOT, dispatch, err, info, ok, step, warn, run

# ── Preset template ────────────────────────────────────────


PRESET_TEMPLATE = '''"""League preset configuration for Negelir Phase 13.

This module exposes a single CONFIG constant containing all league-specific
parameters, following Phase 13.3 discipline:
- Structural data only (no computed values, no os.environ, no function calls)
- No side effects at import time
- Supports auditability via config checksum (Phase 13.21)
"""

from common.league_config import LeagueConfig

# {league_name} with baseline parameters (to be tuned after data collection)
CONFIG = LeagueConfig(
    # Identity
    league_id="{league_id}",
    league_name="{league_name}",
    country="{country}",
    language="tr",
    
    # External source mapping (populate after source discovery)
    openfootball_path="",
    footballdata_country="",
    
    # Structure (baseline; adjust after first season analysis)
    teams_count=18,
    rounds_per_season=34,
    promotion_slots=2,
    relegation_slots=2,
    
    # Elo parameters (copied from tr_super_lig; tune per league data)
    elo_initial=1500.0,
    elo_k=32.0,
    elo_home_advantage=65.0,
    
    # Goal distribution (baseline)
    first_half_goal_pct=0.47,
    league_avg_goals=2.65,
    
    # Poisson limits (baseline; refine after match data collection)
    poisson_max_goals=7,
    poisson_ht_max_goals=5,
    poisson_home_goal_cap=7,
    poisson_away_goal_cap=7,
    poisson_draw_goal_cap=5,
    poisson_market_goal_cap=6,
    min_xg_floor=0.3,
    
    # Dixon-Coles low-scoring adjustment
    dixon_coles_rho=-0.13,
    
    # Elo → xG adjustment curve
    elo_xg_divisor=600.0,
    xg_elo_factor_min=0.7,
    xg_elo_factor_range=0.6,
    
    # Venue-specific xG ratio bounds
    venue_ratio_floor=0.7,
    venue_ratio_ceiling=1.4,
    
    # Derby pairs (to be populated after team discovery)
    derbies=set(),
    
    # Ensemble weights
    xgb_weight=0.35,
    
    # Draw detection thresholds
    draw_ha_gap_threshold=0.15,
    draw_prob_threshold=0.26,
    draw_bayesian_threshold=0.20,
    
    # XGBoost hyperparameters (baseline)
    xgb_n_estimators=300,
    xgb_max_depth=4,
    xgb_learning_rate=0.08,
    xgb_min_child_weight=3,
    xgb_reg_alpha=0.5,
    xgb_reg_lambda=1.5,
    xgb_subsample=0.8,
    xgb_colsample_bytree=0.8,
    xgb_gamma=0.1,
    
    # Training
    draw_sample_weight=2.0,
    val_split=0.15,
    train_pct=0.75,
    
    # Confidence calibration
    calibrate_probabilities=True,
    
    # Team name map (to be populated after source parsing)
    team_name_map={{}},
    
    # Demo strings (placeholder; localize after league goes live)
    demo_label="{league_name} Demo",
    demo_sentiment_samples=[
        "Taraftar desteği çok kuvvetli, takım morali yüksek",
        "Sakatlık problemleri yaşanıyor, dikkat gerekli",
        "Savunma istikrarlı, iyi oyun gösteriliyor",
    ],
)
'''


def cmd_scaffold(argv: List[str]) -> int:
    """Scaffold a new league preset + mock-seed structure.
    
    Usage: make league.scaffold LEAGUE_ID=<id> COUNTRY=<iso> CONFEDERATION=<x>
    
    Example: make league.scaffold LEAGUE_ID=en_championship COUNTRY=GB CONFEDERATION=UEFA
    
    Generates:
    - ai/common/leagues/<league_id>.py (preset template)
    - ai/common/leagues/__init__.py entry (auto-imported)
    - stub entry in infra/mock/seeds/manifest.json
    - tracker row (status: in-progress, Phase 13.3)
    - version bump (xops component, patch level)
    """
    import os
    
    league_id = os.environ.get("LEAGUE_ID", "").strip()
    country = os.environ.get("COUNTRY", "").strip()
    confederation = os.environ.get("CONFEDERATION", "").strip()
    
    if not league_id:
        err("LEAGUE_ID not set")
        return 1
    if not country:
        err("COUNTRY not set")
        return 1
    if not confederation:
        err("CONFEDERATION not set")
        return 1
    
    # Validate league_id format (snake_case)
    if not league_id.replace("_", "").isalnum() or league_id[0].isdigit():
        err(f"Invalid LEAGUE_ID '{league_id}'; must be alphanumeric + underscores, not start with digit")
        return 1
    
    step("Scaffolding league preset for " + league_id)
    
    # ── Step 1: Create the preset file ────
    preset_path = REPO_ROOT / "ai" / "common" / "leagues" / f"{league_id}.py"
    if preset_path.exists():
        err(f"Preset already exists: {preset_path}")
        return 1
    
    # Generate from template
    league_name = league_id.replace("_", " ").title()
    preset_content = PRESET_TEMPLATE.format(
        league_id=league_id,
        league_name=league_name,
        country=country,
    )
    
    preset_path.write_text(preset_content, encoding="utf-8")
    ok(f"Created preset: {preset_path.relative_to(REPO_ROOT)}")
    
    # ── Step 2: Update __init__.py to import the new preset ────
    init_path = preset_path.parent / "__init__.py"
    init_content = init_path.read_text(encoding="utf-8")
    
    # Check if already imported
    import_line = f"from .{league_id} import CONFIG as {league_id}_config"
    if f"from .{league_id} import" in init_content:
        warn(f"{league_id} already imported in __init__.py")
    else:
        # Add import after other league imports (or at the end of imports)
        lines = init_content.split("\n")
        
        # Find the last import statement
        last_import_idx = -1
        for i, line in enumerate(lines):
            if line.startswith("from ") or line.startswith("import "):
                last_import_idx = i
        
        if last_import_idx >= 0:
            lines.insert(last_import_idx + 1, import_line)
        else:
            # No imports found, add before first non-comment line
            lines.insert(0, import_line)
        
        init_content = "\n".join(lines)
        init_path.write_text(init_content, encoding="utf-8")
        ok(f"Updated __init__.py with import for {league_id}")
    
    # ── Step 3: Add stub entry to manifest ────
    manifest_path = REPO_ROOT / "infra" / "mock" / "seeds" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    
    # Check if already exists
    if any(e.get("source") == league_id for e in manifest.get("entries", [])):
        warn(f"{league_id} already in manifest.json")
    else:
        now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
        stub_entry = {
            "source": league_id,
            "url": f"https://www.example.com/{league_id}/",
            "path": f"{league_id}/stub.json",
            "captured_at": now_iso,
            "sha256": "0" * 64,  # Placeholder
            "bytes": 0,
            "status": 200,
            "content_type": "application/json",
            "note": f"Stub entry for {league_name}; to be populated by Phase 13.3 scraper setup"
        }
        manifest["entries"].append(stub_entry)
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        ok(f"Added stub manifest entry for {league_id}")
    
    # ── Step 4: Add tracker row ────
    tracker_cmd = [
        sys.executable,
        "docs/tracking/track.py",
        "add",
        "13",
        "--subphase", "3",
        "--status", "in-progress",
        "--note", f"Phase 13.3 scaffold: created league preset for {league_name} ({league_id}, {country}, {confederation})",
    ]
    result = run(tracker_cmd, cwd=REPO_ROOT, check=False)
    if result.returncode != 0:
        warn(f"Tracker row add failed (exit code {result.returncode}); check that docs/tracking/track.py is accessible")
    else:
        ok("Added tracker row (Phase 13.3)")
    
    # ── Step 5: Bump version ────
    bump_cmd = [
        sys.executable,
        "xops/versioning/version.py",
        "bump",
        "--component", "xops",
        "--level", "patch",
        f"--note", f"Phase 13.3: scaffolded {league_name} preset",
    ]
    result = run(bump_cmd, cwd=REPO_ROOT, check=False)
    if result.returncode != 0:
        warn(f"Version bump failed (exit code {result.returncode}); check xops/versioning/version.py")
    else:
        ok("Bumped xops version (patch)")
    
    # ── Summary ────
    info("")
    info("Scaffold complete!")
    info("")
    info("Next steps:")
    info(f"  1. Edit {preset_path.relative_to(REPO_ROOT)} with league-specific parameters")
    info(f"  2. Populate derbies, team_name_map, and source mappings (openfootball, footballdata)")
    info("  3. Capture initial seed data: make mock.capture <league_id>")
    info("  4. Run Phase 13.3 lint checks: make lint")
    info("")
    
    return 0


COMMANDS = {"scaffold": cmd_scaffold}


def main(argv=None):
    return dispatch(argv if argv is not None else sys.argv[1:], COMMANDS, script_name="league.py")


if __name__ == "__main__":
    raise SystemExit(main())
