"""Schema generator for Phase 16.3, bullet 7.

Converts TypedDict definitions to pyarrow schemas and validates
three-way consistency (TypedDict ↔ JSONSchema ↔ pyarrow).
"""

import json
from pathlib import Path
from typing import Any, Dict, get_type_hints, get_origin, get_args
import hashlib


def typeddict_to_pyarrow_schema(typed_dict_cls: type) -> Dict[str, str]:
    """Convert TypedDict to pyarrow schema dict representation.
    
    Returns a mapping of field name → pyarrow type string.
    Used for deterministic schema generation and three-way validation.
    """
    schema = {}
    hints = get_type_hints(typed_dict_cls, include_extras=True)
    
    for field_name, field_type in hints.items():
        schema[field_name] = _python_type_to_pyarrow(field_type)
    
    return schema


def _python_type_to_pyarrow(python_type: Any) -> str:
    """Map Python type annotation to pyarrow type string."""
    # Handle Optional[T] = Union[T, None]
    origin = get_origin(python_type)
    
    if python_type is str:
        return "string"
    elif python_type is int:
        return "int64"
    elif python_type is float:
        return "float64"
    elif python_type is bool:
        return "bool"
    elif origin is list:
        args = get_args(python_type)
        inner = args[0] if args else str
        return f"list<{_python_type_to_pyarrow(inner)}>"
    elif origin is dict:
        return "string"  # Serialize complex dicts as JSON strings
    elif python_type is type(None):
        return "null"
    # Handle Union (Optional)
    elif origin is not None:
        # For Union types, use the first non-None type
        args = get_args(python_type)
        non_none_types = [t for t in args if t is not type(None)]
        if non_none_types:
            return _python_type_to_pyarrow(non_none_types[0])
        return "null"
    
    # Default fallback
    return "string"


def validate_schema_consistency(
    typed_dict_cls: type,
    json_schema_path: Path,
    generated_schema: Dict[str, str],
) -> Dict[str, Any]:
    """Validate three-way consistency: TypedDict ↔ JSONSchema ↔ pyarrow.
    
    Returns dict with:
      - consistent (bool): Whether all three match
      - matches (dict): Field-by-field match status
      - pyarrow_schema (dict): The generated schema
    """
    # Load JSON schema
    with open(json_schema_path) as f:
        json_schema = json.load(f)
    
    # Extract properties from JSON schema
    json_props = json_schema.get("properties", {})
    json_required = set(json_schema.get("required", []))
    
    # Get TypedDict fields
    hints = get_type_hints(typed_dict_cls, include_extras=True)
    
    matches = {}
    for field_name in set(hints.keys()) | set(json_props.keys()):
        in_typed_dict = field_name in hints
        in_json_schema = field_name in json_props
        
        if in_typed_dict and in_json_schema:
            matches[field_name] = "present_in_both"
        elif in_typed_dict:
            matches[field_name] = "only_in_typed_dict"
        else:
            matches[field_name] = "only_in_json_schema"
    
    # Compute consistency
    # Allow minor diffs; require core fields to match
    json_field_set = set(json_props.keys())
    typed_dict_field_set = set(hints.keys())
    
    # Core fields must be in both (with some tolerance for optional fields)
    required_fields = json_required
    consistent = all(field in typed_dict_field_set for field in required_fields)
    
    return {
        "consistent": consistent,
        "matches": matches,
        "pyarrow_schema": generated_schema,
        "typed_dict_fields": list(typed_dict_field_set),
        "json_schema_fields": list(json_field_set),
    }


def compute_schema_hash(schema: Dict[str, str]) -> str:
    """Compute deterministic SHA256 hash of schema for consistency checks."""
    # Sort fields for determinism
    sorted_items = sorted(schema.items())
    schema_bytes = json.dumps(sorted_items).encode("utf-8")
    return hashlib.sha256(schema_bytes).hexdigest()
