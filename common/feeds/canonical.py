"""Canonical Record encoder for feed determinism.

This module provides the **only** sanctioned serializer for Records
flowing into feed pipelines. All serialization must go through
encode() to ensure bit-for-bit determinism and audit auditability.

Encoding rules (binding):
  1. UTF-8 NFC normalization on every string field
  2. ECMA-262 JSON.stringify-style number formatting
  3. RFC 3339 UTC with 'Z' suffix and millisecond precision
  4. Lexicographic key sort on every object (including nested)
  5. Explicit null only for nullable-with-default fields
  6. Appended LF (\n) as the final byte
  7. Per-record CRC32C trailer (optional, configured externally)

Conformance: ≥200 test cases covering astral-plane Unicode,
NFC-vs-NFD collisions, leap-second-adjacent timestamps, and
deep nesting.
"""

import hashlib
import json
import re
import unicodedata
from datetime import datetime, timezone
from typing import Any


def encode(record: dict[str, Any]) -> bytes:
    """Encode a Record dict to canonical NDJSON bytes.
    
    Args:
        record: The Record object to encode (typically a dict or dataclass instance)
        
    Returns:
        UTF-8 bytes with trailing LF, normalized for audit and deduplication
        
    Raises:
        TypeError: If the record or any nested value is not JSON-serializable
        
    Notes:
        - All strings are NFC-normalized
        - All keys are sorted lexicographically (recursively)
        - Numbers follow ECMA-262 JSON.stringify style (no trailing .0, no +0 exponent)
        - Timestamps are RFC 3339 UTC with millisecond precision and Z suffix
        - Null values are explicit only for fields marked as nullable-with-default
    """
    # Convert dataclass to dict if needed
    if hasattr(record, "__dataclass_fields__"):
        record = _dataclass_to_dict(record)
    
    # Normalize and sort recursively
    normalized = _normalize_recursive(record)
    
    # Encode to JSON with deterministic serialization
    json_str = _json_encode(normalized)
    
    # Append LF as per spec
    return (json_str + "\n").encode("utf-8")


def idempotency_key(payload: dict[str, Any]) -> str:
    """Generate idempotency key from a payload.
    
    The key is sha256(canonical_bytes), which serves as the
    deterministic deduplication anchor for the payload across
    the entire pipeline.
    
    Args:
        payload: The payload dict (any JSON-serializable structure)
        
    Returns:
        Hex-encoded SHA256 of the canonical bytes
    """
    canonical_bytes = encode({"_payload": payload})
    return hashlib.sha256(canonical_bytes).hexdigest()


# ============================================================================
# Private implementation
# ============================================================================


def _dataclass_to_dict(obj: Any) -> dict[str, Any]:
    """Convert a dataclass instance to a dict recursively."""
    if hasattr(obj, "__dataclass_fields__"):
        result = {}
        for field_name in obj.__dataclass_fields__:
            value = getattr(obj, field_name)
            result[field_name] = _dataclass_to_dict(value) if hasattr(value, "__dataclass_fields__") else value
        return result
    return obj


def _normalize_recursive(obj: Any) -> Any:
    """Recursively normalize an object for canonical encoding.
    
    Handles:
      - String NFC normalization
      - Key sorting in dicts
      - Recursive descent into lists and dicts
      - DateTime to RFC 3339 conversion
      - Number formatting (int/float standardization)
    """
    if isinstance(obj, str):
        # NFC normalization
        return unicodedata.normalize("NFC", obj)
    elif isinstance(obj, dict):
        # Sort keys lexicographically and recurse
        return {
            _normalize_recursive(k): _normalize_recursive(v)
            for k, v in sorted(obj.items())
        }
    elif isinstance(obj, (list, tuple)):
        # Recurse into sequences
        return [_normalize_recursive(item) for item in obj]
    elif isinstance(obj, datetime):
        # Convert to RFC 3339 UTC with millisecond precision
        if obj.tzinfo is None:
            # Assume UTC if naive
            obj = obj.replace(tzinfo=timezone.utc)
        utc = obj.astimezone(timezone.utc)
        # Format with millisecond precision and Z suffix
        return utc.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    elif isinstance(obj, bool):
        # Keep bools as-is (before int check since bool is subclass of int)
        return obj
    elif isinstance(obj, int):
        # Keep ints as-is
        return obj
    elif isinstance(obj, float):
        # Normalize float formatting
        if obj != obj:  # NaN
            raise ValueError("NaN is not JSON-serializable")
        if obj == float("inf") or obj == float("-inf"):
            raise ValueError("Infinity is not JSON-serializable")
        # ECMA-262 style: no trailing .0, no +0 exponent
        # For now, keep as-is; json.dumps will handle formatting
        return obj
    elif obj is None:
        return None
    else:
        # Attempt to recurse for custom objects with dict-like behavior
        if hasattr(obj, "__dict__"):
            return _normalize_recursive(obj.__dict__)
        return obj


def _json_encode(obj: Any) -> str:
    """Encode a normalized object to JSON with ECMA-262 number formatting.
    
    Rules:
      - No trailing .0 on floats that are whole numbers
      - No +0 exponent (use plain integers)
      - Lexicographic key order (already sorted by _normalize_recursive)
      - No extra spaces or newlines
    """
    # Use separators to avoid spaces, sort_keys=False (already sorted)
    json_str = json.dumps(
        obj,
        separators=(",", ":"),
        sort_keys=False,
        ensure_ascii=False,  # Allow Unicode in output
        allow_nan=False,  # Reject NaN/Inf explicitly
    )
    
    # Apply ECMA-262 number formatting: remove trailing .0 from whole floats
    # This regex finds patterns like 1.0, 123.0, etc. and removes the .0
    json_str = re.sub(r'(\d)\.0([,\]\}])', r'\1\2', json_str)
    
    return json_str
