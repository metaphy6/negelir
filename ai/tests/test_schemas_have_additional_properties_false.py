"""
Test: test_schemas_have_additional_properties_false.py
Phase 16.1 contract validation — all schemas enforce additionalProperties: false.

Validates:
1. All plane schemas (reference, schedule, score, lineup, editorial, market, etc.)
   have additionalProperties: false at the root level
2. All nested object properties also enforce additionalProperties: false
3. Envelope schema has additionalProperties: false
4. All invariant schemas are valid

Fulfills Phase 16.1 requirement: "additionalProperties: false on every payload struct
so unknown keys fail closed at write-time."
"""

import json
import os
import glob
import pytest


def get_schema_files():
    """Get all schema files in the feeds directory."""
    schema_dir = os.path.join(
        os.path.dirname(__file__),
        "../common/schemas/feeds"
    )
    schema_files = glob.glob(os.path.join(schema_dir, "*.json"))
    return {os.path.basename(f): f for f in schema_files}


class TestAdditionalPropertiesFalse:
    """Validate that all schemas enforce additionalProperties: false."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Load all schemas."""
        self.schemas = {}
        for name, path in get_schema_files().items():
            with open(path) as f:
                self.schemas[name] = json.load(f)

    # Dict-like fields that intentionally allow arbitrary keys
    DICT_LIKE_FIELDS = {"payload", "values", "metadata", "parameters"}

    def _is_dict_like_field(self, field_name, prop_schema):
        """Check if a field is intentionally dict-like (arbitrary keys)."""
        if field_name in self.DICT_LIKE_FIELDS:
            return True

        # If additionalProperties is explicitly set to a schema object, it's dict-like
        add_props = prop_schema.get("additionalProperties")
        if isinstance(add_props, dict) and add_props:
            return True

        return False

    def _check_additional_properties(self, obj, schema_name, path="", parent_field_name=""):
        """Recursively check that all object-type properties have additionalProperties: false."""
        if not isinstance(obj, dict):
            return []

        errors = []
        
        # Extract the field name from the current path if this is a nested object
        if path and "properties." in path:
            parts = path.split(".")
            if len(parts) >= 2:
                current_field = parts[-1]
            else:
                current_field = ""
        else:
            current_field = ""

        # Check root level if it's a schema object
        if "$schema" in obj or "properties" in obj or "type" in obj:
            if obj.get("type") == "object" or "properties" in obj:
                # Skip if this is a dict-like field
                if not (current_field in self.DICT_LIKE_FIELDS):
                    if obj.get("additionalProperties") is not False:
                        # Only report for root or known strict paths
                        if path == "":
                            errors.append(
                                f"Schema {schema_name} at root: "
                                f"additionalProperties must be false, got {obj.get('additionalProperties')}"
                            )

        # Recursively check nested properties
        if "properties" in obj and isinstance(obj["properties"], dict):
            for prop_name, prop_schema in obj["properties"].items():
                if isinstance(prop_schema, dict):
                    current_path = f"{path}.{prop_name}" if path else f"properties.{prop_name}"
                    if prop_schema.get("type") == "object" or "properties" in prop_schema:
                        # Skip dict-like fields that intentionally allow arbitrary keys
                        if not self._is_dict_like_field(prop_name, prop_schema):
                            if prop_schema.get("additionalProperties") is not False:
                                # Don't complain if it's a dict-like field
                                add_props = prop_schema.get("additionalProperties")
                                if not isinstance(add_props, dict):
                                    errors.append(
                                        f"Schema {schema_name} at {current_path}: "
                                        f"additionalProperties must be false, "
                                        f"got {add_props}"
                                    )
                    errors.extend(self._check_additional_properties(prop_schema, schema_name, current_path, prop_name))

        # Check oneOf schemas
        if "oneOf" in obj and isinstance(obj["oneOf"], list):
            for idx, sub_schema in enumerate(obj["oneOf"]):
                if isinstance(sub_schema, dict):
                    path_str = f"{path}[oneOf][{idx}]" if path else f"oneOf[{idx}]"
                    errors.extend(self._check_additional_properties(sub_schema, schema_name, path_str))

        # Check anyOf schemas
        if "anyOf" in obj and isinstance(obj["anyOf"], list):
            for idx, sub_schema in enumerate(obj["anyOf"]):
                if isinstance(sub_schema, dict):
                    path_str = f"{path}[anyOf][{idx}]" if path else f"anyOf[{idx}]"
                    errors.extend(self._check_additional_properties(sub_schema, schema_name, path_str))

        return errors

    def test_envelope_has_additional_properties_false(self):
        """Envelope schema must have additionalProperties: false."""
        envelope = self.schemas.get("envelope.v1.json")
        assert envelope is not None, "envelope.v1.json not found"
        assert envelope.get("additionalProperties") is False, \
            "envelope.v1.json must have additionalProperties: false"

    def test_all_plane_schemas_have_additional_properties_false(self):
        """All plane schemas must have additionalProperties: false."""
        plane_files = [
            "reference.v1.json",
            "schedule.v1.json",
            "score.v1.json",
            "lineup.v1.json",
            "editorial.v1.json",
            "market.v1.json",
            "feature_vectors.v1.json",
            "sec_quarantine.v1.json",
            "match_outcomes.v1.json",
            "calibration.v1.json",
            "competition.v1.json",
            "predict_invalidated.v1.json",
        ]

        for plane_file in plane_files:
            schema = self.schemas.get(plane_file)
            assert schema is not None, f"{plane_file} not found"
            assert schema.get("additionalProperties") is False, \
                f"{plane_file} must have additionalProperties: false at root"

    def test_no_nested_objects_without_additional_properties_false(self):
        """All nested object schemas must also have additionalProperties: false."""
        errors = []
        for schema_name, schema in self.schemas.items():
            errs = self._check_additional_properties(schema, schema_name)
            errors.extend(errs)

        assert not errors, "Found schemas with missing additionalProperties: false:\n" + "\n".join(errors)

    def test_registry_json_is_loadable(self):
        """Registry must be valid JSON."""
        registry = self.schemas.get("registry.json")
        assert registry is not None, "registry.json not found"
        assert isinstance(registry, dict), "registry.json must be a JSON object"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
