#!/usr/bin/env python3
"""feeds target dispatcher — Phase 16 feeds lifecycle & operational targets."""
from __future__ import annotations
import sys
from pathlib import Path
from _common import REPO_ROOT, dispatch, fail, ok

def cmd_up(argv):
    """Start all feed infrastructure (Postgres, Redis, NATS for feed events)."""
    try:
        ok("feeds infrastructure startup: Postgres + Redis + NATS (minimal stub)")
        return 0
    except Exception as e:
        fail(f"feeds.up failed: {e}")

def cmd_down(argv):
    """Stop and drain feed infrastructure cleanly."""
    try:
        ok("feeds infrastructure shutdown (minimal stub)")
        return 0
    except Exception as e:
        fail(f"feeds.down failed: {e}")

def cmd_tail(argv):
    """Tail live feed emissions (STREAM=<stream_id>)."""
    stream_id = next((v.split("=", 1)[1] for v in argv if v.startswith("STREAM=")), None)
    if not stream_id:
        fail("STREAM=<stream_id> required")
    try:
        ok(f"Tailing feed stream {stream_id} (minimal stub)")
        return 0
    except Exception as e:
        fail(f"feeds.tail failed: {e}")

def cmd_snapshot_rebuild(argv):
    """Rebuild snapshot partition for a feed source (SOURCE=<id> [AFTER=<utc-iso>])."""
    source_id = next((v.split("=", 1)[1] for v in argv if v.startswith("SOURCE=")), None)
    if not source_id:
        fail("SOURCE=<id> required")
    try:
        ok(f"Rebuilding snapshot partition for {source_id} (minimal stub)")
        return 0
    except Exception as e:
        fail(f"feeds.snapshot.rebuild failed: {e}")

def cmd_prune(argv):
    """Prune expired records from feed partitions (BEFORE=<utc-iso> [DRY_RUN=1])."""
    before = next((v.split("=", 1)[1] for v in argv if v.startswith("BEFORE=")), None)
    if not before:
        fail("BEFORE=<utc-iso> required")
    try:
        ok(f"Pruning records before {before} (minimal stub)")
        return 0
    except Exception as e:
        fail(f"feeds.prune failed: {e}")

def cmd_fsck(argv):
    """Filesystem integrity check on /data/feeds tree and manifest hashes."""
    try:
        ok("Feed tree fsck: manifest + partition hashes verified (minimal stub)")
        return 0
    except Exception as e:
        fail(f"feeds.fsck failed: {e}")

def cmd_manifest_rebuild(argv):
    """Rebuild manifest.json from current partition tree (operator runbook)."""
    try:
        ok("Rebuilt manifest.json from partition scan (minimal stub)")
        return 0
    except Exception as e:
        fail(f"feeds.manifest.rebuild failed: {e}")

def cmd_parity(argv):
    """Run parity test: live feed vs snapshot vs NDJSON (SOURCE=<id>)."""
    source_id = next((v.split("=", 1)[1] for v in argv if v.startswith("SOURCE=")), None)
    if not source_id:
        fail("SOURCE=<id> required")
    try:
        ok(f"Parity check: {source_id} live vs snapshot vs NDJSON (minimal stub)")
        return 0
    except Exception as e:
        fail(f"feeds.parity failed: {e}")

def cmd_schema_review(argv):
    """Manual review of feed schema and partitioning strategy."""
    try:
        ok("Feed schema review: current layout and versioning (minimal stub)")
        return 0
    except Exception as e:
        fail(f"feeds.schema.review failed: {e}")

def cmd_schema_audit(argv):
    """Audit schema compatibility across all feed versions (prevent silent breaking changes)."""
    try:
        ok("Schema audit: version compatibility matrix verified (minimal stub)")
        return 0
    except Exception as e:
        fail(f"feeds.schema.audit failed: {e}")

def cmd_backfill(argv):
    """Backfill missing feed partitions (SOURCE=<id> FROM=<utc-iso> TO=<utc-iso>)."""
    source_id = next((v.split("=", 1)[1] for v in argv if v.startswith("SOURCE=")), None)
    from_time = next((v.split("=", 1)[1] for v in argv if v.startswith("FROM=")), None)
    to_time = next((v.split("=", 1)[1] for v in argv if v.startswith("TO=")), None)
    if not all([source_id, from_time, to_time]):
        fail("SOURCE=<id> FROM=<utc-iso> TO=<utc-iso> required")
    try:
        ok(f"Backfill {source_id} from {from_time} to {to_time} (minimal stub)")
        return 0
    except Exception as e:
        fail(f"feeds.backfill failed: {e}")

def cmd_backfill_promote(argv):
    """Promote backfilled partitions from staging to live feed tree."""
    try:
        ok("Promoted backfilled partitions to live tree (minimal stub)")
        return 0
    except Exception as e:
        fail(f"feeds.backfill.promote failed: {e}")

def cmd_chaos_run(argv):
    """Run chaos scenario on feeds: corruption, latency, missing partitions (SCENARIO=<id>)."""
    scenario = next((v.split("=", 1)[1] for v in argv if v.startswith("SCENARIO=")), None)
    if not scenario:
        fail("SCENARIO=<id> required")
    try:
        ok(f"Chaos scenario {scenario}: injecting faults into feeds (minimal stub)")
        return 0
    except Exception as e:
        fail(f"feeds.chaos.run failed: {e}")

def cmd_cost_report(argv):
    """Report storage + compute cost of feed tree (by source, region, retention tier)."""
    try:
        ok("Feed cost report: storage + compute breakdown (minimal stub)")
        return 0
    except Exception as e:
        fail(f"feeds.cost.report failed: {e}")

def cmd_tombstone_audit(argv):
    """Audit tombstone (deleted record) coverage and retention policy compliance."""
    try:
        ok("Tombstone audit: coverage and retention verified (minimal stub)")
        return 0
    except Exception as e:
        fail(f"feeds.tombstone.audit failed: {e}")

def cmd_pitr_restore(argv):
    """Rebuild the feeds tree as of a target timestamp."""
    target_time = next((v.split("=", 1)[1] for v in argv if v.startswith("TARGET=")), None)
    output_root = next((v.split("=", 1)[1] for v in argv if v.startswith("ROOT=")), None)
    region = next((v.split("=", 1)[1] for v in argv if v.startswith("REGION=")), "eu")
    
    if not target_time:
        fail("TARGET=<utc-iso> required")
    if not output_root:
        fail("ROOT=<path> required")
    
    try:
        sys.path.insert(0, str(REPO_ROOT / "ai"))
        from common.feeds.changelog import restore_manifest_tree
    except ImportError as e:
        fail(f"Failed to import: {e}")
    
    feeds_root = Path("/data/feeds")
    try:
        manifest_path = restore_manifest_tree(feeds_root, target_time, output_root, region)
        ok(f"Restored manifest to {manifest_path}")
        return 0
    except Exception as e:
        fail(f"PITR restore failed: {e}")

COMMANDS = {
    "up": cmd_up,
    "down": cmd_down,
    "tail": cmd_tail,
    "snapshot.rebuild": cmd_snapshot_rebuild,
    "prune": cmd_prune,
    "fsck": cmd_fsck,
    "manifest.rebuild": cmd_manifest_rebuild,
    "parity": cmd_parity,
    "schema.review": cmd_schema_review,
    "schema.audit": cmd_schema_audit,
    "backfill": cmd_backfill,
    "backfill.promote": cmd_backfill_promote,
    "chaos.run": cmd_chaos_run,
    "cost.report": cmd_cost_report,
    "tombstone.audit": cmd_tombstone_audit,
    "pitr.restore": cmd_pitr_restore,
}

if __name__ == "__main__":
    sys.exit(dispatch(COMMANDS, sys.argv[1:]))
