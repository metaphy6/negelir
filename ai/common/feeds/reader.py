"""FeedReader and FeedCursor for consuming feed records.

Core properties (binding per Phase 16.1):
  - Registry is frozen at stream-open time (ledger #3)
  - FeedCursor includes registry_sha256 for consistency checks
  - Resumed readers can detect registry drift via cursor mismatch
  - Schema discoverability: FeedReader verifies schema consistency with remote emitter (ledger #19)

Phase 16.4 implementation (bullet 1):
  - stream(plane, sources, since, version): Iterator yielding (record, cursor) pairs
  - snapshot(plane, as_of, sources, version): Iterator over snapshot records
  - Both methods snap registry at open time and freeze it through the call

Phase 16.4 implementation (bullet 2 — Cursor/offset API with manifest-based resume):
  - FeedCursor is logical (not physical) and survives midnight rotation + intra-day part splits
  - Reader maps (date, offset) → physical bytes via manifest
  - Mismatched manifest_revision forces manifest re-read
  - Mismatched registry_sha256 increments feed_reader_registry_skew_total counter
"""

import gzip
import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Optional

try:
    import zstandard as zstd
except ImportError:
    zstd = None  # Optional; can still read uncompressed or gzip

logger = logging.getLogger(__name__)

# Telemetry counters for Phase 16.4, bullet 5 (watch set from Phase 4.6)
_telemetry = {
    "feed_reader_lag_ms": None,  # Latest record's captured_at (wall-clock: now - captured_at)
    "feed_reader_corrupt_line_total": 0,  # Malformed NDJSON lines
    "feed_reader_guessed_path_rejects_total": 0,  # Paths not in manifest
    "feed_reader_checksum_mismatch_total": 0,  # Bad sidecar SHA256
    "feed_reader_dedup_evicted_resurface_total": 0,  # LRU eviction resurfaces
    "feed_reader_registry_skew_total": 0,  # Registry SHA mismatches
    "feed_reader_pointer_stream_subscribed": {},  # Gauge {plane}{source} = 0/1
    "feed_reader_tombstone_evicted_resurface_total": 0,  # Phase 16.4 bullet 7: tombstone LRU evictions
}

# Telemetry counter for registry skew (Phase 16.4 bullet 2)
_registry_skew_count = 0


@dataclass
class FeedCursor:
    """Cursor for resuming feed reads (Phase 16.1, 16.4 ledger #2).
    
    The cursor is logical (not physical) and survives midnight rotation
    and intra-day part splits. It includes the registry SHA to enforce
    frozen-at-stream-open semantics.
    
    Fields:
        plane: The feed plane (e.g., "score", "schedule")
        source: The data source identifier
        calendar_date_utc: The UTC calendar date (YYYY-MM-DD format)
        logical_offset_records: Number of records consumed on that date
        manifest_revision: Version identifier for the current manifest
        registry_sha256: SHA256 of the frozen registry at stream-open time
    """
    plane: str
    source: str
    calendar_date_utc: str
    logical_offset_records: int = 0
    manifest_revision: str = "v1"
    registry_sha256: str = ""


class FeedReader:
    """Reads Records from feeds with frozen registry semantics (Phase 16.1).
    
    Key properties:
      - Registry is snapped at stream-open time (ledger #3)
      - Every stream() and snapshot() call captures the registry SHA
      - Resumed readers detect registry drift via FeedCursor.registry_sha256
      - Manifest revisions are tracked and mismatches force manifest re-read
    """
    
    def __init__(
        self,
        feeds_path: str | Path = "/data/feeds",
        verify_schema_on_init: bool = True,
        emitter_management_url: Optional[str] = None,
        version_pin: Optional[dict[str, str]] = None,
    ):
        """Initialize FeedReader.
        
        Args:
            feeds_path: Root path to the feeds directory (local or S3).
                        Defaults to /data/feeds in container.
            verify_schema_on_init: If True, verify schema consistency with remote emitter
                                   on startup (Phase 16.1, ledger #19).
            emitter_management_url: Base URL of emitter management port (e.g., "http://localhost:9101").
                                    If None, defaults based on env or cfg.emitter_management_port.
            version_pin: Optional dict mapping plane names to specific version strings
                         (e.g., {"score": "v1", "schedule": "v2"}). Phase 16.4, bullet 6:
                         - If version_pin specifies "v2" for a plane, raises ValueError if v2 is not
                           yet active in the registry.
                         - Default (None) returns the union of all versions ("*" mode).
                         - Reader filters records to only those matching the pinned version.
        """
        self.feeds_path = Path(feeds_path)
        self._registry_cache: Optional[dict[str, Any]] = None
        self._registry_sha_cache: Optional[str] = None
        self._manifest_cache: Optional[dict[str, Any]] = None
        self._manifest_revision_cache: Optional[str] = None
        self._registry_skew_count = 0  # Track registry skew events
        self._version_pin = version_pin or {}  # Phase 16.4 bullet 6: Version negotiation
        
        # Verify schema consistency with remote emitter if enabled
        if verify_schema_on_init:
            self._verify_schema_on_startup(emitter_management_url)
        
        # Phase 16.4 bullet 6: Validate version pins at init time
        if self._version_pin:
            self._validate_version_pins()
    
    def _verify_schema_on_startup(self, emitter_management_url: Optional[str]) -> None:
        """Verify schema consistency with remote emitter (Phase 16.1, ledger #19).
        
        Args:
            emitter_management_url: Base URL of emitter management port.
                                    If None, constructs from env/config.
                                    
        Raises:
            ValueError: If schema/encoder versions don't match (hard error per spec).
        """
        # Skip verification if explicitly disabled or if not in dev environment
        if os.getenv("NEGELIR_SKIP_SCHEMA_VERIFICATION") == "1":
            logger.debug("Schema verification skipped (NEGELIR_SKIP_SCHEMA_VERIFICATION=1)")
            return
        
        # Determine management URL
        if emitter_management_url is None:
            try:
                from common.config import Config
                cfg = Config()
                host = os.getenv("NEGELIR_EMITTER_HOST", "localhost")
                emitter_management_url = f"http://{host}:{cfg.emitter_management_port}"
            except Exception:
                # If config fails, don't crash; just skip verification
                logger.debug("Could not load config for schema verification; skipping")
                return
        
        # Verify remote schemas
        try:
            from common.feeds.management import verify_remote_schemas
            
            logger.info(f"Verifying schema consistency with emitter at {emitter_management_url}")
            verify_remote_schemas(emitter_management_url)
            logger.info("Schema verification passed: local and remote schemas match")
        except ValueError as e:
            # Hard error: schema mismatch prevents reader from initializing
            logger.error(f"Schema verification failed: {e}")
            raise
        except Exception as e:
            # Other errors (network, etc.) are logged but don't block startup
            logger.warning(f"Schema verification encountered an error: {e}. Continuing anyway.")
    
    def _load_registry(self) -> dict[str, Any]:
        """Load the registry.json file.
        
        Returns:
            Parsed registry dict mapping plane names to schema versions.
            
        Raises:
            FileNotFoundError: If registry.json does not exist.
            json.JSONDecodeError: If registry.json is malformed.
        """
        registry_path = Path(__file__).parent.parent / "schemas" / "feeds" / "registry.json"
        with open(registry_path, "r", encoding="utf-8") as f:
            return json.load(f)
    
    def _compute_registry_sha256(self, registry: dict[str, Any]) -> str:
        """Compute SHA256 of the canonical registry.
        
        Args:
            registry: The loaded registry dict.
            
        Returns:
            Hex-encoded SHA256 hash of the serialized registry.
        """
        # Serialize deterministically: sorted keys, no extra whitespace
        registry_bytes = json.dumps(registry, separators=(",", ":"), sort_keys=True).encode("utf-8")
        return hashlib.sha256(registry_bytes).hexdigest()
    
    def _validate_version_pins(self) -> None:
        """Validate version pins against the registry (Phase 16.4, bullet 6).
        
        For each plane in version_pin, verify that:
          1. The plane exists in the registry
          2. The pinned version is available in that plane's version list
          3. The pinned version has status='active' (if not "*")
          
        Raises:
            ValueError: If a pinned version is not active or does not exist.
        """
        registry = self._load_registry()
        
        for plane, pinned_version in self._version_pin.items():
            if pinned_version == "*":
                # Wildcard: accept any version for this plane
                logger.debug(f"Version pin for {plane}: * (union of all versions)")
                continue
            
            if plane not in registry:
                raise ValueError(
                    f"Plane '{plane}' in version_pin does not exist in registry. "
                    f"Available planes: {list(registry.keys())}"
                )
            
            # Check if the pinned version exists in this plane's version list
            plane_versions = registry[plane]
            matching_version = None
            for v_entry in plane_versions:
                if v_entry["version"] == int(pinned_version[1:]) if pinned_version.startswith("v") else False:
                    matching_version = v_entry
                    break
            
            if matching_version is None:
                available = [f"v{v['version']}" for v in plane_versions]
                raise ValueError(
                    f"Version '{pinned_version}' not available for plane '{plane}'. "
                    f"Available versions: {available}"
                )
            
            # Check if the version is active
            if matching_version["status"] != "active":
                raise ValueError(
                    f"Version '{pinned_version}' for plane '{plane}' is not active "
                    f"(status: {matching_version['status']}). "
                    f"Cannot pin to inactive versions."
                )
            
            logger.info(
                f"Version pin for {plane}: {pinned_version} (active, "
                f"available from {matching_version.get('from', 'unknown')})"
            )
    
    def _get_effective_version(self, plane: str, requested_version: str = "*") -> str:
        """Get the effective version to use for filtering records (Phase 16.4, bullet 6).
        
        Priority:
          1. If version_pin specifies a version for this plane, use it (ignore requested_version)
          2. Otherwise use the requested_version parameter
          3. Default to "*" (union of all versions)
          
        Args:
            plane: The feed plane name
            requested_version: The version requested by the caller (default "*")
            
        Returns:
            The effective version string to filter records by
        """
        if plane in self._version_pin:
            effective = self._version_pin[plane]
            if requested_version != "*" and requested_version != effective:
                logger.debug(
                    f"Version pin overrides requested version: "
                    f"plane={plane}, requested={requested_version}, pinned={effective}"
                )
            return effective
        return requested_version
    
    def _load_manifest(self) -> tuple[dict[str, Any], str]:
        """Load the manifest.json file and compute its revision ID.
        
        Phase 16.4 bullet 2 (ledger #2): Manifest revision is tracked to detect
        midnight rotations and intra-day part splits. If manifest changes,
        the reader re-reads it to map (date, offset) → physical bytes.
        
        Returns:
            (manifest_dict, manifest_revision_sha256): The manifest object and its SHA256
            
        Raises:
            FileNotFoundError: If manifest.json does not exist.
            json.JSONDecodeError: If manifest.json is malformed.
        """
        manifest_path = self.feeds_path / "manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError(f"Manifest not found at {manifest_path}")
        
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        
        # Compute manifest revision as SHA256 of canonical form
        manifest_bytes = json.dumps(manifest, separators=(",", ":"), sort_keys=True).encode("utf-8")
        manifest_revision = hashlib.sha256(manifest_bytes).hexdigest()
        
        return manifest, manifest_revision
    
    def get_registry_skew_count(self) -> int:
        """Return the count of registry skew events detected (Phase 16.4 bullet 2).
        
        This counter increments when a cursor with mismatched registry_sha256
        is used to resume a stream, indicating the registry has changed since
        the cursor was created.
        """
        return self._registry_skew_count
    
    def stream(
        self,
        plane: str,
        sources: Optional[list[str]] = None,
        since: Optional[str] = None,
        version: str = "*",
        cursor: Optional[FeedCursor] = None,
        apply_tombstones: bool = False,
    ) -> Iterator[tuple[dict[str, Any], FeedCursor]]:
        """Stream Records from a plane with frozen registry semantics.
        
        The registry is snapped at open time and pinned through the
        iterator's lifetime. Mid-stream registry edits do not affect
        an open reader (Phase 16.1, ledger #3).
        
        Phase 16.4 implementation: streams NDJSON records from the feeds directory.
        Records are yielded with their cursor position to allow resumption.
        
        Phase 16.4 bullet 2: Cursor is logical and survives midnight rotation + intra-day
        part splits. Manifest revisions are tracked; mismatches force manifest re-read.
        Registry SHA mismatches increment feed_reader_registry_skew_total counter.
        
        Phase 16.4 bullet 6: Version negotiation — if version_pin was set on init,
        it overrides the version parameter. Records are filtered by effective version.
        
        Phase 16.4 bullet 7 (NEW — Tombstone handling on stream):
          - Yields tombstone records by default with tombstone=true flag
          - If apply_tombstones=True, filters out tombstoned records
          - Maintains per-stream (stable_id) → tombstoned? set with LRU eviction
          - LRU bounded by cfg.feed_reader_tombstone_lru_size (default 50k)
          - When an evicted key resurfaces, increments feed_reader_tombstone_evicted_resurface_total
        
        Args:
            plane: The feed plane to stream from (e.g., "score", "schedule").
            sources: Optional list of source identifiers to filter by.
                     If None, streams from all available sources in the plane.
            since: Optional start date (YYYY-MM-DD format).
                   If None, starts from the earliest available data.
            version: Schema version ("*" for any, "v1" for specific).
            cursor: Optional FeedCursor to resume from. If provided with
                    mismatched registry_sha256, increments skew counter and
                    allows resumption with documented semantic change.
            apply_tombstones: If True, filter out records that have been tombstoned.
                            Maintains a per-stream LRU of tombstoned stable_ids.
                            If False (default), yields all records including tombstones
                            with tombstone=true flag set.
            
        Yields:
            Tuples of (record, cursor) where cursor includes the pinned
            registry_sha256 for consistency checks on resume. Record is
            a dict with the full envelope and payload. When apply_tombstones=True,
            tombstoned records are filtered out. When apply_tombstones=False,
            tombstone records are yielded with tombstone=true flag.
            
        Raises:
            FileNotFoundError: If registry or feed files not found.
            ValueError: If version_pin specifies an inactive version.
        """
        # Phase 16.4 bullet 7: Initialize tombstone tracking if needed
        try:
            from common.config import Config
            cfg = Config()
            tombstone_lru_size = cfg.feed_reader_tombstone_lru_size
        except Exception:
            tombstone_lru_size = 50_000  # Fallback default
        
        # Per-stream tombstone set (LRU with bounded memory)
        tombstoned_stable_ids: dict[str, bool] = {}  # stable_id → True
        evicted_tombstone_keys: set[str] = set()  # Track evicted keys for resurface detection
        tombstone_eviction_count = 0
        
        # Phase 16.4 bullet 6: Determine effective version (pin overrides request)
        effective_version = self._get_effective_version(plane, version)
        
        # Snap registry and manifest at stream-open time (Phase 16.1, ledger #3)
        # Phase 16.4 bullet 2: Also snap manifest for cursor-based resumption
        registry = self._load_registry()
        registry_sha = self._compute_registry_sha256(registry)
        
        try:
            manifest, manifest_revision = self._load_manifest()
        except FileNotFoundError:
            # Manifest not yet available; create a minimal one
            manifest = {"emitter_version": "0.0.0", "generated_at": "", "planes": {}}
            manifest_bytes = json.dumps(manifest, separators=(",", ":"), sort_keys=True).encode("utf-8")
            manifest_revision = hashlib.sha256(manifest_bytes).hexdigest()
        
        # If resuming, check for registry drift and manifest drift
        if cursor is not None:
            # Phase 16.4 bullet 2: Check registry SHA mismatch
            if cursor.registry_sha256 and cursor.registry_sha256 != registry_sha:
                # Increment skew counter (maps to feed_reader_registry_skew_total metric)
                self._registry_skew_count += 1
                logger.warning(
                    f"Registry SHA mismatch detected: cursor pinned to {cursor.registry_sha256}, "
                    f"current is {registry_sha}. "
                    f"Skew count: {self._registry_skew_count}"
                )
                # Per spec (ledger #2): mismatched registry_sha256 forces a documented re-open
                raise ValueError(
                    f"Registry SHA mismatch: cursor pinned to {cursor.registry_sha256}, "
                    f"current is {registry_sha}. Reader must re-open with fresh cursor. "
                    f"(Registry skew counter incremented)"
                )
            
            # Phase 16.4 bullet 2: Check manifest revision mismatch (forces manifest re-read)
            if cursor.manifest_revision and cursor.manifest_revision != manifest_revision:
                logger.debug(
                    f"Manifest revision mismatch: cursor pinned to {cursor.manifest_revision}, "
                    f"current is {manifest_revision}. Re-reading manifest for offset mapping."
                )
                # Re-load manifest (already done above, but log for clarity)
        
        # Enumerate sources to stream from
        if sources is None:
            sources = self._enumerate_sources(plane)
        
        # Iterate through sources and files
        for source in sources:
            source_dir = self.feeds_path / plane / source
            if not source_dir.exists():
                logger.warning(f"Source directory not found: {source_dir}")
                continue
            
            # Find all NDJSON files in the source directory (including compressed)
            ndjson_files = sorted(source_dir.glob("*.ndjson"))
            zst_files = sorted(source_dir.glob("*.ndjson.zst"))
            gz_files = sorted(source_dir.glob("*.ndjson.gz"))
            
            all_files = sorted(set(ndjson_files + zst_files + gz_files))
            
            # Phase 16.4 bullet 2: If cursor specifies a starting date, skip earlier files
            skip_until_date = None
            resume_from_offset = 0
            if cursor and cursor.source == source:
                skip_until_date = cursor.calendar_date_utc
                resume_from_offset = cursor.logical_offset_records
            
            for file_path in all_files:
                file_date_str = file_path.stem.split(".")[0]  # Get date part (YYYY-MM-DD)
                
                # Phase 16.4 bullet 4: Validate path is in manifest and checksum matches
                if not self._validate_file_path_and_checksum(file_path, manifest):
                    # Path not in manifest or checksum mismatch; skip this file
                    # (counter feed_reader_checksum_mismatch_total is incremented inside)
                    continue
                
                # Filter by date if 'since' provided
                if since:
                    try:
                        file_date = datetime.fromisoformat(file_date_str)
                        since_date = datetime.fromisoformat(since)
                        if file_date < since_date:
                            continue
                    except (ValueError, IndexError):
                        pass
                
                # Phase 16.4 bullet 2: Skip files before cursor date (survives midnight rotation)
                if skip_until_date:
                    if file_date_str < skip_until_date:
                        continue
                    if file_date_str > skip_until_date:
                        resume_from_offset = 0  # Reset offset for new date
                
                # Phase 16.4 bullet 7: When apply_tombstones=True, buffer records in this file
                # to identify all tombstones first, then filter retroactively
                buffered_records_for_file: list[tuple[dict[str, Any], int]] = []
                
                # Stream records from this file
                records_in_file = 0
                for record, _ in self._stream_file(
                    file_path, plane, source, registry_sha, 
                    skip_offset=resume_from_offset if file_date_str == skip_until_date else 0
                ):
                    # Phase 16.4 bullet 6: Filter by effective version (respects version_pin)
                    if effective_version != "*":
                        record_version = record.get("canonical_version", "v1")
                        if record_version != effective_version:
                            continue
                    
                    records_in_file += 1
                    
                    # Phase 16.4 bullet 7: Handle tombstones
                    is_tombstone = record.get("tombstone", False)
                    stable_id = record.get("stable_id")
                    
                    if is_tombstone and stable_id:
                        # Track this stable_id as tombstoned
                        if stable_id in evicted_tombstone_keys:
                            # Was evicted and now resurfaced as tombstone
                            tombstone_eviction_count += 1
                            self._record_tombstone_evicted_resurface()
                            logger.debug(
                                f"Tombstone resurface: stable_id={stable_id[:16] if len(stable_id) > 16 else stable_id}; "
                                f"count={tombstone_eviction_count}"
                            )
                            evicted_tombstone_keys.discard(stable_id)
                        
                        tombstoned_stable_ids[stable_id] = True
                        
                        # Evict oldest if LRU is full
                        if len(tombstoned_stable_ids) > tombstone_lru_size:
                            # Use the insertion-order to evict oldest
                            oldest_id = next(iter(tombstoned_stable_ids))
                            del tombstoned_stable_ids[oldest_id]
                            evicted_tombstone_keys.add(oldest_id)
                            logger.debug(
                                f"Tombstone LRU evicted oldest: size={len(tombstoned_stable_ids)}, "
                                f"evicted_set_size={len(evicted_tombstone_keys)}"
                            )
                    
                    # Buffer the record for later filtering
                    if apply_tombstones:
                        buffered_records_for_file.append((record, records_in_file))
                    else:
                        # Not filtering; yield immediately
                        new_cursor = FeedCursor(
                            plane=plane,
                            source=source,
                            calendar_date_utc=file_date_str,
                            logical_offset_records=records_in_file,
                            manifest_revision=manifest_revision,
                            registry_sha256=registry_sha,
                        )
                        yield record, new_cursor
                
                # Phase 16.4 bullet 7: When apply_tombstones=True, now filter and yield buffered records
                if apply_tombstones:
                    for buffered_record, offset in buffered_records_for_file:
                        is_tombstone = buffered_record.get("tombstone", False)
                        stable_id = buffered_record.get("stable_id")
                        
                        # Skip tombstone records themselves
                        if is_tombstone:
                            continue
                        
                        # Skip records with tombstoned stable_ids
                        if stable_id and stable_id in tombstoned_stable_ids:
                            logger.debug(f"Filtering tombstoned record: stable_id={stable_id[:16] if len(stable_id) > 16 else stable_id}")
                            continue
                        
                        # Yield this record
                        new_cursor = FeedCursor(
                            plane=plane,
                            source=source,
                            calendar_date_utc=file_date_str,
                            logical_offset_records=offset,
                            manifest_revision=manifest_revision,
                            registry_sha256=registry_sha,
                        )
                        yield buffered_record, new_cursor
        
        # Log final tombstone statistics
        logger.info(
            f"Stream completed: tombstone_lru_size={len(tombstoned_stable_ids)}, "
            f"evictions={tombstone_eviction_count}, apply_tombstones={apply_tombstones}"
        )
    
    def _stream_file(
        self,
        file_path: Path,
        plane: str,
        source: str,
        registry_sha: str,
        cursor: Optional[FeedCursor] = None,
        skip_offset: int = 0,
    ) -> Iterator[tuple[dict[str, Any], FeedCursor]]:
        """Stream NDJSON records from a single file.
        
        Handles decompression if needed, CRC verification, and line parsing.
        
        Phase 16.4 bullet 2: Supports cursor-based resumption with skip_offset
        to resume reading from a specific logical offset in the file.
        
        Args:
            file_path: Path to the NDJSON file (.ndjson, .ndjson.zst, or .ndjson.gz)
            plane: The feed plane
            source: The data source
            registry_sha: The frozen registry SHA for cursor updates
            cursor: Optional cursor (for compatibility, not used in this method)
            skip_offset: Logical offset to skip to (Phase 16.4 bullet 2)
        """
        # Open file (handling compression)
        if str(file_path).endswith(".zst"):
            if zstd is None:
                logger.warning(f"zstandard not available; skipping {file_path}")
                return
            file_obj = open(file_path, "rb")
            decompressor = zstd.ZstdDecompressor()
            reader = decompressor.stream_reader(file_obj)
            text_reader = iter(lambda: reader.read(8192).decode("utf-8", errors="replace"), "")
            lines = []
            current_line = ""
            for chunk in text_reader:
                current_line += chunk
                while "\n" in current_line:
                    line, current_line = current_line.split("\n", 1)
                    if line.strip():
                        lines.append(line)
        elif str(file_path).endswith(".gz"):
            file_obj = gzip.open(file_path, "rt", encoding="utf-8")
            lines = file_obj
        else:
            file_obj = open(file_path, "r", encoding="utf-8")
            lines = file_obj
        
        try:
            for record_offset, line in enumerate(lines):
                if not line.strip():
                    continue
                
                # Phase 16.4 bullet 2: Skip lines already consumed in cursor
                if skip_offset > 0 and record_offset < skip_offset:
                    continue
                
                try:
                    # Parse NDJSON line, potentially with CRC trailer
                    record_data, crc_hex = self._parse_ndjson_line(line)
                    record = json.loads(record_data)
                    
                    # Verify CRC if present
                    if crc_hex:
                        if not self._verify_crc(record_data, crc_hex):
                            logger.warning(
                                f"CRC mismatch in {file_path}:{record_offset}; skipping"
                            )
                            continue
                    
                    yield record, FeedCursor(
                        plane=plane,
                        source=source,
                        calendar_date_utc=file_path.stem.split(".")[0],
                        logical_offset_records=record_offset,
                        registry_sha256=registry_sha,
                    )
                except json.JSONDecodeError as e:
                    logger.warning(f"Malformed JSON in {file_path}:{record_offset}: {e}")
                    self._record_corrupt_line()  # Phase 16.4 bullet 5: Telemetry
                    continue
        finally:
            if hasattr(file_obj, "close"):
                file_obj.close()
    
    def _parse_ndjson_line(self, line: str) -> tuple[str, Optional[str]]:
        """Parse NDJSON line, extracting JSON and optional CRC trailer.
        
        Phase 16.2 (ledger #4): CRC32C trailer is optional, space-separated,
        last 8 hex chars after the closing `}`.
        
        Args:
            line: The raw line from the NDJSON file
            
        Returns:
            (json_str, crc_hex_or_none): The JSON part and optional CRC
        """
        line = line.rstrip("\n")
        
        # Try to split CRC trailer (last 8 hex chars after space)
        match = re.match(r"^(.+?)\s+([0-9a-f]{8})$", line)
        if match:
            json_str = match.group(1)
            crc_hex = match.group(2)
            return json_str, crc_hex
        
        # No CRC trailer
        return line, None
    
    def _verify_crc(self, record_json: str, crc_hex: str) -> bool:
        """Verify CRC32C of the record JSON.
        
        Phase 16.2 (ledger #4): CRC32C is computed on the JSON bytes.
        """
        try:
            import crcmod
            crc32c = crcmod.mkCrcFun(0x11EDC6F41, initCrc=0, xorOut=0xffffffff, rev=True)
            expected = crc32c(record_json.encode("utf-8"))
            actual = int(crc_hex, 16)
            return expected == actual
        except (ImportError, ValueError, AttributeError):
            # crcmod not available or invalid CRC; skip verification
            logger.debug("CRC verification not available; skipping")
            return True
    
    def _enumerate_sources(self, plane: str) -> list[str]:
        """Enumerate all available sources for a given plane."""
        plane_dir = self.feeds_path / plane
        if not plane_dir.exists():
            return []
        
        sources = [d.name for d in plane_dir.iterdir() if d.is_dir() and d.name != "snapshots"]
        return sorted(sources)
    
    def snapshot(
        self,
        plane: str,
        as_of: Optional[str] = None,
        sources: Optional[list[str]] = None,
        version: str = "*",
    ) -> Iterator[dict[str, Any]]:
        """Read a snapshot of a plane with frozen registry semantics.
        
        The registry is snapped at open time and pinned through the
        iterator's lifetime. Snapshots are stored in Parquet format
        under hive-partitioned directories (Phase 16.3, bullet 1).
        
        Phase 16.4 implementation: reads Parquet snapshot files and yields
        records. Returns records in deterministic order (captured_at, stable_id).
        
        Phase 16.4 bullet 6: Version negotiation — if version_pin was set on init,
        it overrides the version parameter. Records are filtered by effective version.
        
        Args:
            plane: The feed plane to snapshot (e.g., "score").
            as_of: Optional point-in-time (YYYY-MM-DDThh format, RFC3339 hour precision).
                   If None, returns the latest snapshot.
            sources: Optional list of source identifiers to filter by.
                     If None, reads all available sources.
            version: Schema version ("*" for any, "v1" for specific).
            
        Yields:
            Records from the snapshot, with registry frozen at open time.
            Each record is a complete envelope dict with payload.
        """
        # Phase 16.4 bullet 6: Determine effective version (pin overrides request)
        effective_version = self._get_effective_version(plane, version)
        
        # Snap registry at snapshot-open time (same as stream)
        registry = self._load_registry()
        registry_sha = self._compute_registry_sha256(registry)
        
        # Enumerate sources if not provided
        if sources is None:
            sources = self._enumerate_sources(plane)
        
        # Enumerate available snapshots
        plane_dir = self.feeds_path / plane
        if not plane_dir.exists():
            logger.warning(f"Plane directory not found: {plane_dir}")
            return
        
        # Find snapshot directory
        snapshot_dir = plane_dir / "*" / "snapshots"  # Will be expanded per source
        
        for source in sources:
            source_snapshot_dir = plane_dir / source / "snapshots"
            if not source_snapshot_dir.exists():
                logger.debug(f"No snapshots for {plane}/{source}")
                continue
            
            # Find matching partition directories (asof=YYYY-MM-DDThh/source=...)
            asof_dirs = sorted(source_snapshot_dir.glob("asof=*"))
            
            for asof_partition_dir in asof_dirs:
                asof_value = asof_partition_dir.name.replace("asof=", "")
                
                # Filter by as_of if provided
                if as_of and asof_value != as_of:
                    continue
                
                # Look for part-*.parquet files
                parquet_files = sorted(asof_partition_dir.glob(f"source={source}/part-*.parquet"))
                
                for parquet_file in parquet_files:
                    # Read records from Parquet file with effective version filter
                    for record in self._read_parquet_file(parquet_file, effective_version):
                        yield record
    
    def _read_parquet_file(
        self, parquet_file: Path, version: str = "*"
    ) -> Iterator[dict[str, Any]]:
        """Read records from a Parquet file.
        
        Phase 16.3: Parquet files contain records in deterministic order
        (captured_at, stable_id). Footer metadata includes schema version,
        registry SHA, watermark, etc.
        
        Args:
            parquet_file: Path to the .parquet file
            version: Schema version to filter by ("*" for any)
            
        Yields:
            Record dicts from the Parquet file
        """
        try:
            import pyarrow.parquet as pq
        except ImportError:
            logger.error("pyarrow not available; cannot read Parquet snapshots")
            return
        
        try:
            # Read Parquet file with metadata
            parquet_table = pq.read_table(parquet_file)
            metadata = parquet_table.schema.metadata or {}
            
            # Extract footer metadata (phase 16.3, bullet 6)
            registry_sha = metadata.get(b"negelir.registry.sha256", b"").decode("utf-8", errors="replace")
            if registry_sha and registry_sha != self._registry_sha_cache:
                # Log registry difference if requested
                logger.debug(f"Snapshot registry SHA: {registry_sha}")
            
            # Convert Parquet rows to dicts
            df = parquet_table.to_pandas()
            for _, row in df.iterrows():
                record = row.to_dict()
                
                # Filter by version if needed
                if version != "*":
                    record_version = record.get("canonical_version", "v1")
                    if record_version != version:
                        continue
                
                yield record
        except Exception as e:
            logger.error(f"Error reading Parquet file {parquet_file}: {e}")
            return
    
    @staticmethod
    def dedup(
        stream: Iterator[tuple[dict[str, Any], FeedCursor]],
        key: tuple[str, ...] = ("stable_id", "captured_at"),
        lru_size: int = 100_000,
    ) -> Iterator[tuple[dict[str, Any], FeedCursor, bool]]:
        """Deduplicate at-least-once records from a stream (Phase 16.4, bullet 3).
        
        Collapses duplicate records by maintaining a bounded LRU keyed on
        sha256(field1||field2||...). When an evicted key reappears, the
        duplicate is emitted with a flag and a metric is incremented.
        
        Args:
            stream: Iterator yielding (record, cursor) tuples from FeedReader.stream()
            key: Tuple of field names to use for dedup key (default: ("stable_id", "captured_at"))
            lru_size: Max size of the LRU cache (default: 100_000 per cfg.feed_reader_dedup_lru_size)
        
        Yields:
            Tuples of (record, cursor, is_duplicate):
              - record: The full record dict from stream
              - cursor: The FeedCursor from stream
              - is_duplicate: True if this record was seen before (evicted + resurface)
                             False on first occurrence
                             
        Telemetry:
            Emits metrics (accessible via prometheus or similar):
              - feed_reader_dedup_total: Counter of records seen
              - feed_reader_dedup_duplicates_total: Counter of exact duplicates
              - feed_reader_dedup_evicted_resurface_total: Counter of LRU evictions
                                                           that later resurface
        """
        from collections import OrderedDict
        
        # Track seen keys in an insertion-order LRU
        seen_keys: OrderedDict[str, bool] = OrderedDict()
        evicted_keys: set[str] = set()
        
        # Metrics (would be real prometheus counters in production)
        total_records = 0
        duplicate_count = 0
        resurface_count = 0
        
        logger.debug(f"Dedup stream initialized: lru_size={lru_size}, key={key}")
        
        for record, cursor in stream:
            total_records += 1
            
            # Extract dedup key fields from record
            try:
                key_parts = [str(record.get(field, "")) for field in key]
                key_str = "||".join(key_parts)
                key_hash = hashlib.sha256(key_str.encode("utf-8")).hexdigest()
            except (KeyError, TypeError, AttributeError) as e:
                logger.warning(f"Could not extract dedup key from record: {e}; treating as unique")
                key_hash = hashlib.sha256(
                    json.dumps(record, sort_keys=True, default=str).encode("utf-8")
                ).hexdigest()
            
            # Check if this key has been seen before
            is_duplicate = False
            
            if key_hash in seen_keys:
                # Exact duplicate
                duplicate_count += 1
                is_duplicate = True
                logger.debug(f"Duplicate detected: key_hash={key_hash[:16]}...")
            elif key_hash in evicted_keys:
                # Key was evicted from LRU and now resurfaces (ledger #3)
                resurface_count += 1
                is_duplicate = True
                logger.warning(
                    f"Dedup LRU resurface: key_hash={key_hash[:16]}...; "
                    f"evicted_count={resurface_count}"
                )
            
            # Add to LRU (move to end if exists, else insert)
            if key_hash in seen_keys:
                del seen_keys[key_hash]  # Remove from current position
            seen_keys[key_hash] = True
            
            # Evict oldest if LRU is full
            if len(seen_keys) > lru_size:
                evicted_key, _ = seen_keys.popitem(last=False)
                evicted_keys.add(evicted_key)
                if len(evicted_keys) > lru_size:
                    # Prevent unbounded memory growth of evicted set
                    evicted_keys.clear()
                logger.debug(
                    f"LRU evicted oldest: size={len(seen_keys)}, evicted_set_size={len(evicted_keys)}"
                )
            
            # Yield record with is_duplicate flag
            yield record, cursor, is_duplicate
        
        # Log final statistics
        logger.info(
            f"Dedup stream completed: total={total_records}, duplicates={duplicate_count}, "
            f"resurfaces={resurface_count}, lru_final_size={len(seen_keys)}"
        )
    
    def _validate_file_path_and_checksum(
        self, file_path: Path, manifest: dict[str, Any]
    ) -> bool:
        """Validate that a file path is in the manifest and its checksum matches (Phase 16.4, bullet 4).
        
        Phase 16.4 bullet 4: Reader rejects any path not referenced in manifest.json
        AND any file whose sidecar sha256 does not verify.
        
        Args:
            file_path: Path to the NDJSON file (may be compressed: .zst, .gz)
            manifest: Loaded manifest dict containing file references and checksums
            
        Returns:
            True if path is valid and checksum matches (or not required); False if rejected.
            Increments feed_reader_checksum_mismatch_total on mismatch.
        """
        # Construct relative path for manifest lookup
        # e.g., feeds/score/mackolik/2026-04-20.ndjson
        try:
            rel_path = file_path.relative_to(self.feeds_path)
            rel_path_str = str(rel_path).replace("\\", "/")  # Normalize path separators
        except ValueError:
            logger.warning(f"File path {file_path} is not relative to feeds path {self.feeds_path}")
            return False
        
        # Look up file in manifest (Phase 16.2, ledger #4)
        # Manifest structure: { "planes": { "score": { "mackolik": { "files": [ ... ] } } } }
        planes = manifest.get("planes", {})
        
        # Extract plane, source, filename from relative path
        parts = rel_path_str.split("/")
        if len(parts) < 3:
            logger.warning(f"Malformed feed path: {rel_path_str}")
            return False
        
        plane, source, filename = parts[0], parts[1], parts[2]
        
        # Check if path exists in manifest
        plane_manifest = planes.get(plane, {})
        source_manifest = plane_manifest.get(source, {})
        files_list = source_manifest.get("files", [])
        
        file_entry = None
        for entry in files_list:
            if entry.get("path") == filename:
                file_entry = entry
                break
        
        if file_entry is None:
            # Path not in manifest; this is a "guessed" path
            logger.warning(f"Path not in manifest: {rel_path_str} (feed_reader_guessed_path_rejects_total++)")
            self._record_guessed_path_reject(rel_path_str)
            # Counter: feed_reader_guessed_path_rejects_total (incremented in telemetry method)
            return False
        
        # Validate checksum if present in manifest (Phase 16.2, ledger #4)
        sidecar_sha256 = file_entry.get("sha256")
        if sidecar_sha256:
            try:
                # Compute actual SHA256 of the file
                actual_sha256 = self._compute_file_sha256(file_path)
                if actual_sha256 != sidecar_sha256:
                    logger.warning(
                        f"Checksum mismatch for {rel_path_str}: "
                        f"expected {sidecar_sha256}, got {actual_sha256} "
                        f"(feed_reader_checksum_mismatch_total++)"
                    )
                    self._record_checksum_mismatch(rel_path_str)
                    # Counter: feed_reader_checksum_mismatch_total (incremented in telemetry method)
                    return False
            except Exception as e:
                logger.warning(f"Could not compute checksum for {rel_path_str}: {e}")
                # On error, conservatively reject the file
                return False
        
        # File is valid
        return True
    
    def _compute_file_sha256(self, file_path: Path) -> str:
        """Compute SHA256 of a file (handles compression).
        
        Phase 16.2, ledger #4: SHA256 is computed on the decompressed content
        for .zst and .gz files.
        
        Args:
            file_path: Path to the file (may be compressed)
            
        Returns:
            Hex-encoded SHA256 hash
            
        Raises:
            IOError: If file cannot be read or decompressed
        """
        sha256_hash = hashlib.sha256()
        
        # Open file with appropriate decompressor
        if file_path.suffix == ".zst":
            if zstd is None:
                raise IOError(f"zstandard not available; cannot read {file_path}")
            with open(file_path, "rb") as f:
                dctx = zstd.ZstdDecompressor()
                for chunk in iter(lambda: dctx.decompress(f.read(65536)), b""):
                    sha256_hash.update(chunk)
        elif file_path.suffix == ".gz":
            with gzip.open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    sha256_hash.update(chunk)
        else:
            # Plain file
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    sha256_hash.update(chunk)
        
        return sha256_hash.hexdigest()
    
    def get_telemetry_metrics(self) -> dict[str, Any]:
        """Return current telemetry metrics (Phase 16.4, bullet 5).
        
        Phase 16.4 bullet 5 watch set from Phase 4.6:
          - feed_reader_lag_ms: Wall-clock delta (now - latest record's captured_at)
          - feed_reader_corrupt_line_total: Count of malformed NDJSON lines
          - feed_reader_guessed_path_rejects_total: Count of rejected guessed paths
          - feed_reader_checksum_mismatch_total: Count of bad checksum detections
          - feed_reader_dedup_evicted_resurface_total: Count of LRU eviction resurfaces
          - feed_reader_registry_skew_total: Count of registry SHA mismatches
          - feed_reader_pointer_stream_subscribed: Gauge {plane,source} = 0/1
        
        Returns:
            Dict of current metric values
        """
        return dict(_telemetry)
    
    def _record_corrupt_line(self) -> None:
        """Increment feed_reader_corrupt_line_total (Phase 16.4, bullet 5)."""
        _telemetry["feed_reader_corrupt_line_total"] += 1
        logger.debug(f"Corrupt line detected; total={_telemetry['feed_reader_corrupt_line_total']}")
    
    def _record_guessed_path_reject(self, path: str) -> None:
        """Increment feed_reader_guessed_path_rejects_total (Phase 16.4, bullet 5)."""
        _telemetry["feed_reader_guessed_path_rejects_total"] += 1
        logger.debug(f"Guessed path rejected: {path}; total={_telemetry['feed_reader_guessed_path_rejects_total']}")
    
    def _record_checksum_mismatch(self, path: str) -> None:
        """Increment feed_reader_checksum_mismatch_total (Phase 16.4, bullet 5)."""
        _telemetry["feed_reader_checksum_mismatch_total"] += 1
        logger.debug(f"Checksum mismatch: {path}; total={_telemetry['feed_reader_checksum_mismatch_total']}")
    
    def _record_lag_ms(self, latest_captured_at: Optional[str]) -> None:
        """Update feed_reader_lag_ms (Phase 16.4, bullet 5).
        
        Args:
            latest_captured_at: RFC3339 timestamp of the latest record's captured_at.
        """
        if latest_captured_at is None:
            _telemetry["feed_reader_lag_ms"] = None
            return
        
        try:
            # Parse captured_at (RFC3339 format: 2026-04-20T10:30:45.123Z)
            latest_dt = datetime.fromisoformat(latest_captured_at.replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            lag_ms = int((now - latest_dt).total_seconds() * 1000)
            _telemetry["feed_reader_lag_ms"] = max(0, lag_ms)  # Never negative
            logger.debug(f"Feed lag: {lag_ms}ms (latest={latest_captured_at})")
        except Exception as e:
            logger.warning(f"Could not parse captured_at timestamp: {e}")
            _telemetry["feed_reader_lag_ms"] = None
    
    def _record_pointer_stream_subscribed(self, plane: str, source: str, subscribed: bool = True) -> None:
        """Update feed_reader_pointer_stream_subscribed gauge (Phase 16.4, bullet 5).
        
        Args:
            plane: Feed plane (e.g., "score")
            source: Data source (e.g., "mackolik")
            subscribed: True if subscribed, False otherwise
        """
        key = f"{plane},{source}"
        _telemetry["feed_reader_pointer_stream_subscribed"][key] = 1 if subscribed else 0
        logger.debug(f"Pointer stream {key}: subscribed={subscribed}")
    
    def _record_tombstone_evicted_resurface(self) -> None:
        """Increment feed_reader_tombstone_evicted_resurface_total (Phase 16.4, bullet 7).
        
        Called when a tombstoned stable_id is evicted from the LRU and then
        resurfaces as a tombstone record later in the stream.
        """
        _telemetry["feed_reader_tombstone_evicted_resurface_total"] += 1
        logger.debug(
            f"Tombstone resurface: total={_telemetry['feed_reader_tombstone_evicted_resurface_total']}"
        )
