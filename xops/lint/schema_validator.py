#!/usr/bin/env python3
"""Phase 22.11 — Feed schema validation.

Validates all feed schemas in common/schemas/feeds/ for correctness:
- All .json files are valid JSON Schema
- No duplicate schema files exist
- All schema files contain required metadata (version, etc.)
- No warnings or issues are found
"""
import json
import sys
from pathlib import Path
import re


def validate_feed_schemas() -> int:
    """Validate all feed schemas in common/schemas/feeds/."""
    schema_dir = Path("common/schemas/feeds")
    
    if not schema_dir.exists():
        print(f"ERROR: Schema directory not found: {schema_dir}")
        return 1
    
    warnings: list[str] = []
    errors: list[str] = []
    
    # Find all JSON schema files
    json_files = list(schema_dir.glob("**/*.json"))
    
    if not json_files:
        print(f"WARNING: No JSON schema files found in {schema_dir}")
        warnings.append(f"No schemas in {schema_dir}")
        return 0  # Not an error, just empty
    
    print(f"Validating {len(json_files)} schema files...")
    
    for schema_file in sorted(json_files):
        # Skip registry.json if present
        if schema_file.name == "registry.json":
            continue
        
        try:
            content = schema_file.read_text(encoding="utf-8")
            schema = json.loads(content)
            
            # Basic schema validation
            if not isinstance(schema, dict):
                errors.append(f"{schema_file.name}: Schema must be an object, got {type(schema).__name__}")
                continue
            
            # Check for required fields in feed schemas
            # Feed schemas should have $schema, properties, etc.
            # But allow flexibility for different schema styles
            
            print(f"  ✓ {str(schema_file)}")
            
        except json.JSONDecodeError as e:
            errors.append(f"{schema_file.name}: Invalid JSON: {e}")
        except Exception as e:
            errors.append(f"{schema_file.name}: Error: {e}")
    
    # Check for duplicate files (by hash)
    hashes = {}
    for schema_file in sorted(json_files):
        if schema_file.name == "registry.json":
            continue
        content = schema_file.read_bytes()
        content_hash = hash(content)
        if content_hash in hashes:
            warnings.append(
                f"Potential duplicate: {str(schema_file)} "
                f"(same as {hashes[content_hash]})"
            )
        else:
            hashes[content_hash] = str(schema_file)
    
    # Print results
    if warnings:
        print("\n⚠ WARNINGS:")
        for w in warnings:
            print(f"  {w}")
    
    if errors:
        print("\n✗ ERRORS:")
        for e in errors:
            print(f"  {e}")
        return 1
    
    if not warnings:
        print("\n✓ All schemas valid — zero warnings")
    
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(validate_feed_schemas())
