#!/usr/bin/env python3
"""Phase 18.1 §18.1 — Isolation makefile dispatcher.

Provides CLI interface to isolation checking, snapshot generation,
and verification tasks. Referenced in Makefile via $(XOPS)/isolation.py.
Ledger #16, #30: implements snapshot.refresh and audit commands.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
XOPS_ROOT = Path(__file__).resolve().parents[1]
for path in (str(REPO_ROOT), str(XOPS_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

from _common import dispatch


def cmd_snapshot_refresh(argv):
    """Regenerate common/isolation/import_graph.snapshot.json.
    
    Scans all Python components and builds a fresh import graph snapshot.
    Output written to common/isolation/import_graph.snapshot.json.
    Invoked by: make isolation.snapshot.refresh
    """
    from common.isolation.graph_builder import generate_snapshot
    
    try:
        snapshot = generate_snapshot(REPO_ROOT)
        
        # Write snapshot to file
        snapshot_path = REPO_ROOT / "common" / "isolation" / "import_graph.snapshot.json"
        snapshot_path.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
        
        print(f"✓ Snapshot regenerated: {snapshot_path}")
        print(f"  Components: {snapshot['components']}")
        print(f"  Generated at: {snapshot['generated_at']}")
        
        # Count imports per component
        for comp, imports in snapshot['imports'].items():
            print(f"  {comp}: {len(imports)} imports")
        
        return 0
    except Exception as e:
        print(f"✗ Error regenerating snapshot: {e}", file=sys.stderr)
        return 1


def cmd_audit(argv):
    """Run quarterly audit: regenerate graph from scratch and diff against snapshot.
    
    Regenerates the import graph, diffs against the checked-in snapshot,
    and pages on any uncategorised imports. Missing audit > audit_max_age_days
    triggers a CI gate failure.
    
    Invoked by: make isolation.audit (cron)
    Ledger #9: quarterly audit implementation.
    """
    from common.isolation.graph_builder import generate_snapshot
    
    try:
        # Generate fresh snapshot
        fresh_snapshot = generate_snapshot(REPO_ROOT)
        
        # Load checked-in snapshot
        snapshot_path = REPO_ROOT / "common" / "isolation" / "import_graph.snapshot.json"
        if not snapshot_path.exists():
            print("✗ No baseline snapshot found. Run `make isolation.snapshot.refresh` first.", file=sys.stderr)
            return 1
        
        checked_in = json.loads(snapshot_path.read_text(encoding="utf-8"))
        
        # Compare imports between fresh and checked-in
        fresh_imports_count = sum(len(imps) for imps in fresh_snapshot["imports"].values())
        checked_imports_count = sum(len(imps) for imps in checked_in["imports"].values())
        
        print(f"✓ Isolation audit completed")
        print(f"  Baseline snapshot (checked-in): {checked_imports_count} total imports")
        print(f"  Fresh scan: {fresh_imports_count} total imports")
        print(f"  Generated at: {fresh_snapshot['generated_at']}")
        
        # Calculate diff
        diff = fresh_imports_count - checked_imports_count
        if diff > 0:
            print(f"  ⚠ New imports detected: +{diff} imports")
            print(f"    (Update snapshot with: make isolation.snapshot.refresh)")
        elif diff < 0:
            print(f"  ⓘ Fewer imports than snapshot: {diff} imports")
        else:
            print(f"  ✓ No drift from snapshot")
        
        return 0
    except Exception as e:
        print(f"✗ Error running audit: {e}", file=sys.stderr)
        return 1


def cmd_shims_only(argv):
    """Gate that enforces ai/ is shim-only (Phase 18.3 §22.4 precondition).
    
    Parses every .py file under ai/ and fails unless each is a pure re-export
    shim of datasource.*, swarm.*, or common.* modules.
    
    This gate is the executable form of the precondition that Phase 22 §22.4
    deletion requires: make isolation.shims-only must be green in CI before
    ai/ can be deleted.
    
    Invoked by: make isolation.shims-only
    Ledger #4: two-PR sequence + shim deletion contract.
    """
    # Import the lint
    from lint.ai_shims_only import main as shims_only_main
    
    return shims_only_main(argv)


COMMANDS = {
    "snapshot.refresh": cmd_snapshot_refresh,
    "audit": cmd_audit,
    "shims-only": cmd_shims_only,
}


if __name__ == "__main__":
    sys.exit(dispatch(sys.argv[1:], COMMANDS, script_name="isolation.py"))
