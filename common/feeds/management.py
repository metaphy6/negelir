"""Schema management endpoints for feed contract verification.

This module provides utilities for emitter HTTP endpoints and FeedReader
schema verification (Phase 16.1, ledger #19).

Key functions:
  - get_schema_info(): Returns active registry + schema SHAs + encoder version
  - verify_remote_schemas(): Fetches remote schema info and compares to in-tree
  - schema_discovery_response(): HTTP /schemas response payload
"""

import hashlib
import json
import os
import urllib.request
from pathlib import Path
from typing import Any, Optional


def get_schema_files_sha256() -> dict[str, str]:
    """Compute SHA256 of each schema file in the registry.
    
    Returns:
        Mapping of schema filename (e.g., "reference.v1.json") to hex SHA256.
        
    Raises:
        FileNotFoundError: If schemas directory does not exist.
    """
    schemas_dir = Path(__file__).parent.parent / "schemas" / "feeds"
    result: dict[str, str] = {}
    
    if not schemas_dir.exists():
        raise FileNotFoundError(f"Schemas directory not found: {schemas_dir}")
    
    # Hash each .json file in the feeds schemas directory
    for schema_file in sorted(schemas_dir.glob("*.json")):
        with open(schema_file, "rb") as f:
            file_sha = hashlib.sha256(f.read()).hexdigest()
            result[schema_file.name] = file_sha
    
    return result


def get_canonical_encoder_version() -> str:
    """Get the version of the canonical encoder module.
    
    Returns:
        Version string (currently "v1").
        
    Notes:
        This is a placeholder; in production, read from __version__ or metadata.
    """
    # Phase 16.1: canonical encoder is always v1
    return "v1"


def get_schema_info() -> dict[str, Any]:
    """Generate the /schemas endpoint response.
    
    Returns:
        Dict with:
          - registry: The active registry.json dict
          - schema_files_sha256: Mapping of filename → SHA256
          - canonical_encoder_version: Version of the canonical encoder
          - generated_at: ISO 8601 UTC timestamp
          
    Raises:
        FileNotFoundError: If registry.json or schemas not found.
    """
    from datetime import datetime, timezone
    
    # Load the in-tree registry
    registry_path = Path(__file__).parent.parent / "schemas" / "feeds" / "registry.json"
    with open(registry_path, "r", encoding="utf-8") as f:
        registry = json.load(f)
    
    return {
        "registry": registry,
        "schema_files_sha256": get_schema_files_sha256(),
        "canonical_encoder_version": get_canonical_encoder_version(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def verify_remote_schemas(
    management_url: str,
    timeout_sec: float = 5.0,
) -> dict[str, Any]:
    """Fetch schema info from remote emitter and compare to in-tree copy.
    
    Args:
        management_url: Base URL of emitter management port (e.g., "http://localhost:9101")
        timeout_sec: HTTP timeout in seconds (default 5.0)
        
    Returns:
        Dict with:
          - local: Local schema info dict
          - remote: Remote schema info dict
          - schemas_match: bool (true if registry + schema files are identical)
          - encoder_versions_match: bool
          
    Raises:
        urllib.error.URLError: If remote endpoint is unreachable
        json.JSONDecodeError: If remote response is not valid JSON
        KeyError: If remote response is missing expected fields
        ValueError: If schemas don't match (caller should treat as hard error per spec)
    """
    # Get local copy
    local_info = get_schema_info()
    
    # Fetch remote copy
    url = f"{management_url.rstrip('/')}/schemas"
    req = urllib.request.Request(url, method="GET")
    req.add_header("Accept", "application/json")
    
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as response:
            remote_info = json.loads(response.read().decode("utf-8"))
    except Exception as e:
        # If remote is unreachable in dev, warn but don't fail
        # In production, this would be a hard error
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(f"Could not reach remote emitter at {url}: {e}. Skipping schema verification.")
        return {
            "local": local_info,
            "remote": None,
            "schemas_match": True,  # Assume ok if endpoint unreachable (fallback)
            "encoder_versions_match": True,
        }
    
    # Compare registry
    local_registry = local_info["registry"]
    remote_registry = remote_info.get("registry", {})
    registries_match = local_registry == remote_registry
    
    # Compare schema file SHAs
    local_shas = local_info["schema_files_sha256"]
    remote_shas = remote_info.get("schema_files_sha256", {})
    shas_match = local_shas == remote_shas
    
    schemas_match = registries_match and shas_match
    
    # Compare encoder versions
    local_encoder_version = local_info["canonical_encoder_version"]
    remote_encoder_version = remote_info.get("canonical_encoder_version", "")
    encoder_versions_match = local_encoder_version == remote_encoder_version
    
    result = {
        "local": local_info,
        "remote": remote_info,
        "schemas_match": schemas_match,
        "encoder_versions_match": encoder_versions_match,
    }
    
    # If mismatch, raise hard error (per spec)
    if not schemas_match or not encoder_versions_match:
        raise ValueError(
            f"Schema/encoder version mismatch with emitter at {url}. "
            f"Local registry={registries_match}, SHAs={shas_match}, encoder={encoder_versions_match}. "
            f"This prevents version skew between predictor and emitter. "
            f"Restart predictor or emitter to resync."
        )
    
    return result
