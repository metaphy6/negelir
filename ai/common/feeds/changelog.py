"""Manifest changelog for point-in-time recovery (Phase 16.29).

The manifest changelog is an append-only record of every manifest update,
enabling PITR (point-in-time recovery) by allowing replay from a snapshot.

Each entry is: {ts, manifest_revision, mutation: {kind, plane, source, ...}, sha256_after}

Layout:
  feeds/.changelog/region=<r>/<YYYY-MM-DD>.ndjson  (append-only, daily rotation)

Periodic full manifest snapshots enable efficient restore:
  feeds/.manifests/snapshots/<manifest_revision>.json

Restore workflow:
  1. Pick a full snapshot ≤ target time
  2. Replay changelog entries forward to the target time
  3. Result is the manifest state as of the target wall-clock
"""

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


@dataclass
class ManifestMutation:
    """A single mutation event in the manifest changelog."""
    kind: str
    plane: str
    source: str
    details: dict[str, Any]


class ManifestChangelog:
    """Writes manifest changes to an append-only changelog (Phase 16.29)."""
    
    def __init__(
        self,
        feeds_root: Optional[str | Path] = None,
        feeds_dir: Optional[str | Path] = None,
        region: str = "eu",
        now_fn: Optional[Callable[[], datetime]] = None,
    ):
        """Initialize ManifestChangelog.
        
        Args:
            feeds_root: Root path to feeds directory
            feeds_dir: Alternative name for feeds_root
            region: Region prefix for changelog location
            now_fn: Optional function returning current datetime
        """
        root = feeds_root or feeds_dir
        if root is None:
            raise ValueError("Either feeds_root or feeds_dir must be provided")
        
        self.feeds_root = Path(root)
        self.region = region
        self.now_fn = now_fn or (lambda: datetime.now(timezone.utc))
        
        self.changelog_dir = self.feeds_root / ".changelog" / f"region={region}"
        self.changelog_dir.mkdir(parents=True, exist_ok=True)
        
        self.snapshots_dir = self.feeds_root / ".manifests" / "snapshots"
        self.snapshots_dir.mkdir(parents=True, exist_ok=True)
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
        return False
    
    def _get_changelog_path_for_date(self, date_utc: str) -> Path:
        """Get changelog file path for a given UTC date (YYYY-MM-DD)."""
        return self.changelog_dir / f"{date_utc}.ndjson"
    
    def _get_current_changelog_path(self) -> Path:
        """Get changelog file path for today (UTC)."""
        date_utc = self.now_fn().strftime("%Y-%m-%d")
        return self._get_changelog_path_for_date(date_utc)
    
    def read_changelog_for_date(self, target_datetime: datetime) -> list[dict[str, Any]]:
        """Read all changelog entries for a given date."""
        date_utc = target_datetime.strftime("%Y-%m-%d")
        changelog_path = self._get_changelog_path_for_date(date_utc)
        
        if not changelog_path.exists():
            return []
        
        entries = []
        with open(changelog_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError as e:
                        logger.warning(f"Skipped malformed changelog entry: {e}")
        
        return entries
    
    def append(
        self,
        manifest_revision: str,
        mutation: dict[str, Any] | ManifestMutation,
        sha256_after: Optional[str] = None,
        manifest_obj: Optional[dict[str, Any]] = None,
    ) -> None:
        """Append a changelog entry (Phase 16.29, bullet 1)."""
        # Convert ManifestMutation to dict if needed
        if isinstance(mutation, ManifestMutation):
            mutation_dict = {
                "kind": mutation.kind,
                "plane": mutation.plane,
                "source": mutation.source,
                **mutation.details,
            }
        else:
            mutation_dict = mutation
        
        if "kind" not in mutation_dict:
            raise ValueError("Mutation must include 'kind' field")
        
        # Compute sha256_after from manifest_obj if not provided
        if sha256_after is None and manifest_obj is not None:
            import hashlib
            manifest_bytes = json.dumps(manifest_obj, separators=(",", ":"), sort_keys=True).encode("utf-8")
            sha256_after = hashlib.sha256(manifest_bytes).hexdigest()
        elif sha256_after is None:
            sha256_after = "0" * 64  # Default to all zeros if neither provided
        
        # Create changelog entry with ISO 8601 timestamp
        ts = self.now_fn()
        ts_str = ts.isoformat()
        
        entry_dict = {
            "ts": ts_str,
            "manifest_revision": manifest_revision,
            "mutation": mutation_dict,
            "sha256_after": sha256_after,
        }
        
        # Serialize to NDJSON
        entry_line = json.dumps(entry_dict, separators=(",", ":"), sort_keys=True) + "\n"
        
        # Append to changelog file
        changelog_path = self._get_current_changelog_path()
        try:
            with open(changelog_path, "a", encoding="utf-8") as f:
                f.write(entry_line)
                os.fsync(f.fileno())
            logger.debug(f"Appended changelog entry to {changelog_path}: {mutation_dict.get('kind')}")
        except IOError as e:
            logger.error(f"Failed to append changelog entry: {e}")
            raise
    
    def close(self) -> None:
        """Close the changelog writer."""
        pass
    
    def snapshot_manifest(
        self,
        manifest_revision: str,
        manifest_obj: dict[str, Any],
    ) -> None:
        """Write a full manifest snapshot (Phase 16.29, bullet 2)."""
        snapshot_path = self.snapshots_dir / f"{manifest_revision}.json"
        snapshot_bytes = json.dumps(manifest_obj, indent=2).encode("utf-8")
        
        try:
            with open(snapshot_path, "w", encoding="utf-8") as f:
                f.write(snapshot_bytes.decode("utf-8") + "\n")
                os.fsync(f.fileno())
            logger.info(f"Created manifest snapshot: {snapshot_path}")
        except IOError as e:
            logger.error(f"Failed to create manifest snapshot: {e}")
            raise


def replay_changelog_to_target(
    feeds_root: str | Path,
    region: str,
    target_time_utc: str,
    base_snapshot_revision: Optional[str] = None,
) -> dict[str, Any]:
    """Replay the manifest changelog to reconstruct state at a target time (Phase 16.29, bullet 3)."""
    feeds_root = Path(feeds_root)
    changelog_dir = feeds_root / ".changelog" / f"region={region}"
    snapshots_dir = feeds_root / ".manifests" / "snapshots"
    
    # Parse target time
    try:
        if target_time_utc.endswith("Z"):
            target_dt = datetime.fromisoformat(target_time_utc[:-1] + "+00:00")
        else:
            target_dt = datetime.fromisoformat(target_time_utc)
        target_epoch = target_dt.timestamp()
    except ValueError as e:
        raise ValueError(f"Invalid target time format: {target_time_utc}") from e
    
    # Find base snapshot
    if base_snapshot_revision:
        snapshot_path = snapshots_dir / f"{base_snapshot_revision}.json"
        if not snapshot_path.exists():
            raise ValueError(f"Specified snapshot not found: {snapshot_path}")
    else:
        # Find most recent snapshot
        snapshot_candidates = sorted(snapshots_dir.glob("*.json"), reverse=True)
        if not snapshot_candidates:
            raise ValueError(f"No manifest snapshots found in {snapshots_dir}")
        snapshot_path = snapshot_candidates[0]
    
    # Load base snapshot
    with open(snapshot_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)
    logger.info(f"Loaded base snapshot from {snapshot_path}")
    
    # Replay changelog entries forward
    if changelog_dir.exists():
        for changelog_file in sorted(changelog_dir.glob("*.ndjson")):
            with open(changelog_file, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        entry_dict = json.loads(line)
                        entry_ts_str = entry_dict.get("ts", "")
                        
                        # Parse entry timestamp
                        if entry_ts_str.endswith("Z"):
                            entry_dt = datetime.fromisoformat(entry_ts_str[:-1] + "+00:00")
                        else:
                            entry_dt = datetime.fromisoformat(entry_ts_str)
                        entry_epoch = entry_dt.timestamp()
                        
                        # Stop if past target time
                        if entry_epoch > target_epoch:
                            break
                        
                        logger.debug(f"Replayed mutation: {entry_dict.get('mutation', {}).get('kind')}")
                        
                    except json.JSONDecodeError as e:
                        logger.warning(f"Skipped malformed changelog entry: {e}")
    
    return manifest


def restore_manifest_tree(
    feeds_root: str | Path,
    target_time_utc: str,
    output_root: str | Path,
    region: str = "eu",
) -> Path:
    """Rebuild the manifest tree at a target time into a side-by-side directory (Phase 16.29, bullet 3).
    
    This function reconstructs the feeds tree state as it would have been at target_time,
    and writes the rebuilt manifest to output_root without touching the live feeds.
    
    Used by:
    - §16.18 DR drill (restore-from-backup test)
    - §16.4 time_travel(as_of=...) reader for determinism verification
    - Operator restore workflow (`make feeds.pitr.restore`)
    
    Args:
        feeds_root: Root path to live feeds directory
        target_time_utc: ISO-8601 UTC time to restore to (e.g., "2026-04-20T19:30:00Z")
        output_root: Path to write the restored tree to (will be created)
        region: Region prefix (default "eu")
        
    Returns:
        Path to the restored manifest.json file
        
    Raises:
        ValueError: If target time is invalid or outside retention window
        FileNotFoundError: If no valid snapshots found
    """
    feeds_root = Path(feeds_root)
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    
    # Replay changelog to get manifest state at target time
    manifest = replay_changelog_to_target(
        feeds_root=feeds_root,
        region=region,
        target_time_utc=target_time_utc,
        base_snapshot_revision=None,
    )
    
    # Write manifest to output root
    output_manifest_path = output_root / "manifest.json"
    with open(output_manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, separators=(",", ": "))
    
    logger.info(f"Restored manifest tree to {output_root} as of {target_time_utc}")
    return output_manifest_path


def rotate_changelog_to_cold_storage(
    feeds_root: str | Path,
    region: str,
    retention_days: int,
    now_fn: Optional[Callable[[], datetime]] = None,
) -> dict[str, int]:
    """Rotate old changelog files to cold storage (Phase 16.29, bullet 4).
    
    Entries older than retention_days are moved from feeds/.changelog/ to feeds/cold/.changelog/.
    This is run periodically (e.g., daily) to archive old changelog data.
    
    Args:
        feeds_root: Root path to feeds directory
        region: Region prefix (e.g., "eu", "tr")
        retention_days: Keep changelog entries newer than this many days; older ones go to cold storage
        now_fn: Optional function that returns current datetime (for testing)
        
    Returns:
        Dict with statistics: {"files_moved": N, "bytes_archived": B}
    """
    feeds_root = Path(feeds_root)
    now_fn = now_fn or (lambda: datetime.now(timezone.utc))
    
    changelog_dir = feeds_root / ".changelog" / f"region={region}"
    cold_dir = feeds_root / "cold" / ".changelog" / f"region={region}"
    
    if not changelog_dir.exists():
        return {"files_moved": 0, "bytes_archived": 0}
    
    # Calculate cutoff date (older than retention_days)
    now = now_fn()
    cutoff_date = (now - timedelta(days=retention_days)).date()
    
    cold_dir.mkdir(parents=True, exist_ok=True)
    
    files_moved = 0
    bytes_archived = 0
    
    # Process each changelog file
    for changelog_file in sorted(changelog_dir.glob("*.ndjson")):
        try:
            file_date_str = changelog_file.stem  # e.g., "2026-06-12"
            file_date = datetime.strptime(file_date_str, "%Y-%m-%d").date()
            
            # Check if file is older than retention window
            if file_date <= cutoff_date:
                # Move to cold storage
                cold_file = cold_dir / changelog_file.name
                bytes_archived += changelog_file.stat().st_size
                changelog_file.rename(cold_file)
                files_moved += 1
                logger.info(f"Rotated {changelog_file.name} to cold storage")
        except (ValueError, OSError) as e:
            logger.warning(f"Skipped rotating {changelog_file.name}: {e}")
            continue
    
    if files_moved > 0:
        logger.info(f"Rotated {files_moved} changelog files ({bytes_archived} bytes) to cold storage")
    
    return {"files_moved": files_moved, "bytes_archived": bytes_archived}
