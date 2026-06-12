# Point-in-Time Recovery (PITR) Runbook — feeds/

> **Phase:** 16.29 (Point-in-time recovery & manifest changelog)
> **Audience:** On-call operators, SREs, incident responders
> **Last updated:** 2026-06-12

## 1. When to use PITR

PITR (point-in-time recovery) allows you to:
- **Restore the manifest tree to a historical state** without touching live feeds
- **Audit what existed at a specific timestamp** (e.g., "what was the scope at 2026-04-20T19:30:00Z?")
- **Test DR procedures** (§16.18 DR drill uses PITR)
- **Debug writer bugs** that corrupted the live manifest (side-by-side restore + compare)

## 2. Restore a manifest tree to a specific time

### Command

```bash
make feeds.pitr.restore \
  TARGET="2026-04-20T19:30:00Z" \
  ROOT=/tmp/feeds-restore-20260420 \
  REGION=eu
```

**Parameters:**
- `TARGET`: ISO-8601 UTC timestamp (required). E.g., `2026-04-20T19:30:00Z` or `2026-06-12T15:30:00Z`.
- `ROOT`: Output directory for restored tree (required). Created if doesn't exist; must be writable.
- `REGION`: Region prefix (optional, default `eu`). Use `tr` for Turkey region.

### What happens

1. **Find base snapshot.** Locates the most recent snapshot ≤ `TARGET`. If multiple snapshots exist, picks the newest one before the target time.
2. **Replay changelog.** Starting from the base snapshot, replays all manifest mutations recorded in the changelog up to `TARGET`.
3. **Write manifest.json.** Outputs the reconstructed state to `ROOT/manifest.json`.
4. **Non-destructive.** The live feeds are never touched. Restored tree is entirely contained within `ROOT`.

### Result

- `ROOT/manifest.json` — reconstructed manifest as it existed at `TARGET` time
- All data file paths in the manifest point to their live locations (e.g., `feeds/live/score/mackolik/2026-04-20.ndjson.zst`)

### Example: Comparing live vs historical state

```bash
# Restore state from 1 hour ago
NOW=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
ONE_HOUR_AGO=$(date -u -d "-1 hour" +"%Y-%m-%dT%H:%M:%SZ")

make feeds.pitr.restore TARGET="$ONE_HOUR_AGO" ROOT=/tmp/feeds-1h-ago REGION=eu

# Compare manifests
diff -u /tmp/feeds-1h-ago/manifest.json feeds/manifest.json | head -50
```

## 3. Non-destructive semantics

PITR is **non-destructive** by design:

| Aspect | Design |
|--------|--------|
| **Output location** | Separate `ROOT` directory; never touches live `feeds/` |
| **Read-only operation** | No mutations to the live tree; snapshot and changelog are read-only accessed |
| **Data files untouched** | Restored manifest only *references* live NDJSON/Parquet paths; doesn't copy or modify them |
| **Writer-independent** | Restore can happen while emitter is actively writing to `feeds/` |
| **Reversible** | Simply delete `ROOT` to undo (no state changes to revert) |

## 4. Atomic swap (under writer-lease pause)

When you want to **replace** the live tree with a restored version:

1. **Pause the writer.** The emitter acquires a writer lease (Phase 16.2 mechanism) that blocks new mutations temporarily.
2. **Perform restore.** PITR rebuilds the manifest into a scratch directory.
3. **Atomic swap.** Rename the scratch `manifest.json` to `feeds/manifest.json.new`, then atomically rename to `feeds/manifest.json` (single `rename()` syscall = atomic on POSIX).
4. **Resume writer.** Writer lease is released; emitter resumes normal writes.

### Swap procedure (automated)

This is **not a manual operation** — it is orchestrated by the Phase 8 maintenance loop when invoked. Do not attempt manual swaps without coordinating with the on-call architect.

If you believe the live manifest is corrupted and you need to restore from a snapshot:

```bash
# Contact the on-call architect or SRE team
# DO NOT manually move files or delete feeds/manifest.json
# File: create an incident ticket describing the corruption
```

## 5. Retention and availability

- **Changelog retention:** Entries are kept for `NEGELIR_FEEDS_MANIFEST_CHANGELOG_RETENTION_DAYS` (default 90 days)
- **Snapshot retention:** Full snapshots every `NEGELIR_FEEDS_MANIFEST_SNAPSHOT_INTERVAL_MIN` minutes (default 60)
- **Cold storage:** Changelog entries older than retention_days are rotated to `cold/.changelog/` (read-only archive)

**Restore outside retention window:**

```bash
# This will fail — TARGET is before the oldest snapshot
make feeds.pitr.restore TARGET="2025-01-01T00:00:00Z" ROOT=/tmp/restore REGION=eu
# Error: ValueError: No manifest snapshots found in /data/feeds/.manifests/snapshots
```

To restore from cold storage (if needed), coordinate with the SRE team.

## 6. Troubleshooting

### "No manifest snapshots found"
- **Cause:** TARGET is older than all snapshots (outside retention window).
- **Solution:** Verify TARGET is within the last 90 days. Check `ls -la /data/feeds/.manifests/snapshots/` for available snapshots.

### "Invalid target time format"
- **Cause:** TARGET is not ISO-8601 UTC.
- **Solution:** Use format `YYYY-MM-DDTHH:MM:SSZ` (with Z suffix). Examples: `2026-04-20T19:30:00Z`, `2026-06-12T15:30:00Z`.

### "ROOT directory is not writable"
- **Cause:** Permissions issue or directory doesn't exist.
- **Solution:** Ensure ROOT path is writable. Create parent directories if needed: `mkdir -p /tmp/feeds-restore && make feeds.pitr.restore TARGET=... ROOT=/tmp/feeds-restore`.

### "manifest.json restored but looks empty"
- **Cause:** No mutations were recorded before TARGET time (e.g., manifest was not yet initialized).
- **Solution:** Verify TARGET is after the first write to the changelog. Check `ls /data/feeds/.changelog/region=eu/ | head`.

## 7. Proof tests

- `test_pitr_replay_reconstructs_manifest.py` — restored manifest matches snapshot + replay
- `test_pitr_to_arbitrary_second_within_retention.py` — restore works at any second granularity
- `test_pitr_rebuild_is_side_by_side.py` — live tree untouched after restore
- `test_pitr_outside_retention_refuses.py` — restore fails gracefully outside retention window
- `test_pitr_determinism.py` — replaying same TARGET yields identical manifest (SHA256 match)

---

## Related runbooks

- [`DR_RECOVERY.md`](DR_RECOVERY.md) — full disaster recovery (includes PITR as one step)
- [`MANIFEST_REPAIR.md`](MANIFEST_REPAIR.md) — what to do if manifest is corrupted
- [`WRITER_LEASE.md`](WRITER_LEASE.md) — writer lease pause mechanism (Phase 16.2)
