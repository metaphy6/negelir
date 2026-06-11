# FeedWriter Crash Recovery Runbook

## Overview

This document describes the crash-recovery procedure for `FeedWriter` (Phase 16.2, bullet 10).
When a writer process crashes or is force-killed, it may leave behind partial/corrupted state.
On next startup, the writer detects these "half-states" and either **RESUMES** or **ROLLBACKS** 
based on a deterministic decision tree.

**Key principle:** Never lose acknowledged records; it's better to replay duplicates than lose data.

## Half-States

Half-states are artifacts left behind by crashes:

| Artifact | Cause | Recovery |
|---|---|---|
| `manifest.json.tmp` | Manifest write interrupted by SIGKILL | Delete (manifest never committed) |
| `.ndjson` + `.ndjson.zst` for same date | Rotation in progress when killed | Delete `.ndjson` (live), keep `.ndjson.zst` (sealed) |
| `.ndjson.zst` without `.sha256` | Sidecar write failed after sealing | Delete `.ndjson.zst` (unsafe without checksum) |
| Manifest `revision` > highest sealed file revision | Manifest updated but not all seals reflected | Depends on context (see decision tree) |

## Decision Tree (Bullet 10)

```
START: Writer.open() on (plane, source)

├─ Scan partition_dir for half-states
├─ Check for: tmp_files, partial_rotations, missing_sidecars
│
├─ IF any tmp_files exist
│  └─ DECISION: ROLLBACK (manifest write incomplete, not durable)
│
├─ ELSE IF any partial_rotations exist
│  └─ DECISION: ROLLBACK (rotation incomplete, may corrupt sequence)
│
├─ ELSE IF any missing_sidecars exist
│  └─ DECISION: ROLLBACK (checksums lost, cannot verify on read)
│
└─ ELSE
   └─ DECISION: RESUME (clean state, safe to continue)

EXECUTE decision:
├─ ROLLBACK: Clean up all artifacts
│  ├─ Delete all tmp_files
│  ├─ Delete all .ndjson (live files in partial_rotations)
│  ├─ Delete all .ndjson.zst without sidecars
│  └─ Load manifest (will recreate if corrupted)
│
└─ RESUME: No changes, load manifest and continue
```

## Implementation

The decision tree is implemented in `ai/common/feeds/writer.py`:

- `_detect_half_states()` → scans partition_dir, returns dict of artifacts
- `_decide_recovery_action(half_states)` → applies decision tree, returns "RESUME" or "ROLLBACK"
- `_perform_recovery(action, half_states)` → executes cleanup or no-op
- `open()` → calls the three above before opening current file

### Code Walkthrough

```python
# In FeedWriter.open()
half_states = self._detect_half_states()       # Scan for artifacts
recovery_action = self._decide_recovery_action(half_states)  # Apply tree
self._perform_recovery(recovery_action, half_states)  # Cleanup
self._load_or_create_manifest()                # Load manifest
self.current_file_handle = open(...)           # Resume or start fresh
```

## Correctness Guarantees

1. **No record loss on RESUME:** If no half-states exist, last manifest state is valid.
   - Manifest is written atomically (write-tmp + rename + fsync parent)
   - If manifest write was incomplete, a `.tmp` file remains → triggers ROLLBACK
   
2. **No corruption on ROLLBACK:** All cleanup targets are either:
   - Unfinished writes (tmp files) → safe to delete
   - Partial rotations (live file still open) → old data can be replayed by extractor
   - Unsealed files (missing checksum) → unverifiable, better to discard

3. **At-least-once semantics:** Writers enforce deduplication via idempotency keys (bullet 13).
   - Rollback may cause duplicates in the feed
   - Readers/consumers handle via idempotency key dedup (Redis bloom filter)

## Operational Scenarios

### Scenario 1: Writer killed during manifest write

```
Partition state:
  2026-06-09.ndjson          (current file, ~1000 records)
  manifest.json              (last successful state, says 900 records)
  manifest.json.tmp          (interrupted write, deleted on next startup)

Recovery:
  1. _detect_half_states() finds: tmp_files = ["manifest.json.tmp"]
  2. _decide_recovery_action() → ROLLBACK
  3. _perform_recovery() deletes manifest.json.tmp
  4. _load_or_create_manifest() loads manifest.json (900 records)
  5. Writer resumes, appends new records to 2026-06-09.ndjson
  
Result: Records 901–1000 are replayed (minor duplicates, deduplicated by idempotency key)
```

### Scenario 2: Writer killed during midnight rotation

```
Partition state:
  2026-06-09.ndjson          (live file, newly created at midnight)
  2026-06-09.ndjson.zst      (sealed file, rotation in progress)
  2026-06-09.ndjson.sha256   (sidecar, already written)
  manifest.json              (says current_date=2026-06-09, files include .zst)

Recovery:
  1. _detect_half_states() finds: partial_rotations = [{ live: ..., sealed: ... }]
  2. _decide_recovery_action() → ROLLBACK
  3. _perform_recovery() deletes 2026-06-09.ndjson (live file)
  4. _load_or_create_manifest() loads manifest
  5. Writer resumes with empty 2026-06-09.ndjson (midnight rotation already logged)
  
Result: Records written during the killed rotation are replayed
```

### Scenario 3: Writer killed after rotation, before sidecar write

```
Partition state:
  2026-06-09.ndjson          (left from previous day, should be .ndjson.zst)
  2026-06-09.ndjson.zst      (sealed but no .sha256)
  2026-06-10.ndjson          (new live file after midnight)
  manifest.json              (says current_date=2026-06-10)

Recovery:
  1. _detect_half_states() finds: missing_sidecars = ["2026-06-09.ndjson.zst"]
  2. _decide_recovery_action() → ROLLBACK
  3. _perform_recovery() deletes 2026-06-09.ndjson.zst (unverifiable)
  4. Records from 2026-06-09 will be replayed by extractor (idempotency key dedup)
  
Result: Safe removal of unverifiable sealed file
```

### Scenario 4: Clean state (no half-states)

```
Partition state:
  2026-06-10.ndjson          (current live file, 5000 records)
  2026-06-09.ndjson.zst      (sealed, verified)
  2026-06-09.ndjson.sha256   (sidecar)
  manifest.json              (current_date=2026-06-10, last_rotation_at=...)

Recovery:
  1. _detect_half_states() finds: all empty
  2. _decide_recovery_action() → RESUME
  3. _perform_recovery(RESUME) → no-op
  4. Writer continues appending to 2026-06-10.ndjson
  
Result: No records replayed, no data loss
```

## Testing Strategy

See `ai/tests/test_feedwriter_crash_recovery.py`:

- `test_crash_recovery_tmp_file_cleanup` — Half-state: manifest.json.tmp
- `test_crash_recovery_partial_rotation_cleanup` — Half-state: both .ndjson and .zst
- `test_crash_recovery_missing_sidecar_cleanup` — Half-state: .ndjson.zst without .sha256
- `test_crash_recovery_resume_clean_state` — No half-states, clean resume
- `test_crash_recovery_partial_rotation_preserves_sealed_file` — .zst is preserved
- `test_crash_recovery_multiple_half_states` — Multiple artifacts combined
- `test_crash_recovery_state_after_recovery` — Writer is ready to accept records post-recovery

## Monitoring & Alerts

Recovery events are logged:

```python
# WARNING level when recovery needed
logger.warning(f"Found tmp files for {plane}/{source} — will ROLLBACK")
logger.warning(f"Found partial rotations for {plane}/{source} — will ROLLBACK")

# INFO level for actual recovery
logger.info(f"Performing ROLLBACK recovery for {plane}/{source}")
logger.info(f"RESUME recovery for {plane}/{source} — no half-states found")
```

Operators should monitor for excessive ROLLBACK events, which may indicate:
- High crash rate (check supervisor logs, pod restart loops)
- Disk full or IO errors (check dmesg, fsck)
- Lease contention (check Redis key conflicts)

## References

- **EMITTER.md §5:** Manifest atomicity (write-tmp + rename + fsync)
- **EMITTER.md §6.1:** Crash-recovery spec and decision tree
- **Phase 16.2, bullet 10:** ROADMAP reference
- **SCRAPER_PATCHER.md §12:** Patcher harness (may invoke writer recovery on auto-patch)
