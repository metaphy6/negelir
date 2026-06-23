"""Phase 22.11 — Proof test for schema validation with zero warnings.

Verifies that all feed schemas in common/schemas/feeds/ are valid
and contain no duplicate files or warning conditions.
"""
from pathlib import Path
import json
import subprocess
import sys


def test_22_11_schema_validate_command_passes() -> None:
    """Phase 22.11 bullet 3: Verify make schema.validate passes with zero warnings."""
    result = subprocess.run(
        ["make", "schema.validate"],
        capture_output=True,
        text=True,
        cwd=Path.cwd()
    )
    
    assert result.returncode == 0, (
        f"make schema.validate failed:\n{result.stdout}\n{result.stderr}"
    )
    
    # Verify the output indicates zero warnings
    assert "zero warnings" in result.stdout.lower() or "✓ All schemas valid" in result.stdout, (
        f"Expected 'zero warnings' or success message in output:\n{result.stdout}"
    )


def test_22_11_no_duplicate_schema_files() -> None:
    """Phase 22.11 bullet 3: Verify no duplicate schema files from merge."""
    schema_dir = Path("common/schemas/feeds")
    assert schema_dir.exists(), f"Schema directory not found: {schema_dir}"
    
    # Find all JSON schema files
    json_files = list(schema_dir.glob("**/*.json"))
    
    # Check for duplicates by hash
    hashes = {}
    duplicates = []
    
    for schema_file in json_files:
        if schema_file.name == "registry.json":
            continue
        
        content_hash = hash(schema_file.read_bytes())
        if content_hash in hashes:
            duplicates.append((str(schema_file), str(hashes[content_hash])))
        else:
            hashes[content_hash] = str(schema_file)
    
    assert not duplicates, f"Duplicate schema files found: {duplicates}"


def test_22_11_all_feed_schemas_valid_json() -> None:
    """Phase 22.11 bullet 3: Verify all feed schemas are valid JSON."""
    schema_dir = Path("common/schemas/feeds")
    json_files = list(schema_dir.glob("**/*.json"))
    
    for schema_file in json_files:
        if schema_file.name == "registry.json":
            continue
        
        try:
            schema_file.read_text(encoding="utf-8")
            json.loads(schema_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise AssertionError(f"{schema_file}: Invalid JSON: {e}")
        except Exception as e:
            raise AssertionError(f"{schema_file}: Error: {e}")
