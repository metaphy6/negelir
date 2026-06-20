"""Phase 21.17 — Schema Registry Integration tests."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai.common.schemas.records import RECORD_TYPES


class TestEnrichmentRecordTypesRegistration:
    """Test that all 10 enrichment record types are registered."""
    
    def test_record_types_includes_4_base_types(self):
        """Verify base planes are registered."""
        assert "score" in RECORD_TYPES
        assert "schedule" in RECORD_TYPES
        assert "market" in RECORD_TYPES
        assert "lineup" in RECORD_TYPES
    
    def test_record_types_includes_10_enrichment_types(self):
        """Verify all 10 enrichment planes are registered."""
        enrichment_types = {
            "transfer", "contract", "suspension", "injury", "availability",
            "referee_assignment", "referee_profile",
            "weather_forecast", "weather_actual", "pitch_condition",
        }
        for record_type in enrichment_types:
            assert record_type in RECORD_TYPES, f"Missing registration: {record_type}"
    
    def test_total_record_types_is_14(self):
        """Verify total count is 4 base + 10 enrichment = 14."""
        assert len(RECORD_TYPES) == 14, f"Expected 14 types, got {len(RECORD_TYPES)}"


class TestEnrichmentSchemaFilesExist:
    """Test that JSONSchema files exist for all enrichment types."""
    
    @pytest.fixture
    def schemas_dir(self):
        """Locate schemas/feeds directory."""
        p = Path(__file__).parent.parent / "common" / "schemas" / "feeds"
        assert p.exists(), f"Schema directory not found: {p}"
        return p
    
    @pytest.mark.parametrize("record_type", [
        "transfer", "contract", "suspension", "injury", "availability",
        "referee_assignment", "referee_profile",
        "weather_forecast", "weather_actual", "pitch_condition",
    ])
    def test_enrichment_schema_file_exists(self, schemas_dir, record_type):
        """Verify each enrichment type has a .v1.json schema file."""
        schema_path = schemas_dir / f"{record_type}.v1.json"
        assert schema_path.exists(), f"Schema file missing: {schema_path}"
        assert schema_path.is_file()
    
    def test_all_enrichment_schemas_are_valid_json(self, schemas_dir):
        """Verify all enrichment schema files are valid JSON."""
        enrichment_types = {
            "transfer", "contract", "suspension", "injury", "availability",
            "referee_assignment", "referee_profile",
            "weather_forecast", "weather_actual", "pitch_condition",
        }
        for record_type in enrichment_types:
            schema_path = schemas_dir / f"{record_type}.v1.json"
            with open(schema_path, "r") as f:
                schema_dict = json.load(f)
            assert isinstance(schema_dict, dict)
            assert "$schema" in schema_dict
            assert "title" in schema_dict
            assert "properties" in schema_dict


class TestEnrichmentSchemaStructure:
    """Test that enrichment schemas follow the correct structure."""
    
    @pytest.fixture
    def schemas_dir(self):
        """Locate schemas/feeds directory."""
        return Path(__file__).parent.parent / "common" / "schemas" / "feeds"
    
    def test_transfer_schema_has_required_fields(self, schemas_dir):
        """Verify transfer schema includes transfer_id, player_id, announced_at."""
        with open(schemas_dir / "transfer.v1.json") as f:
            schema = json.load(f)
        assert "transfer_id" in schema["required"]
        assert "player_id" in schema["required"]
        assert "announced_at" in schema["required"]
        assert "effective_at" in schema["required"]
    
    def test_injury_schema_has_enum_for_severity(self, schemas_dir):
        """Verify injury schema includes enum for severity."""
        with open(schemas_dir / "injury.v1.json") as f:
            schema = json.load(f)
        severity_schema = schema["properties"]["severity"]
        assert "enum" in severity_schema
        assert "minor" in severity_schema["enum"]
        assert "major" in severity_schema["enum"]
    
    def test_weather_forecast_has_numeric_wind_constraints(self, schemas_dir):
        """Verify weather schemas enforce wind_kph >= 0."""
        with open(schemas_dir / "weather_forecast.v1.json") as f:
            schema = json.load(f)
        wind_kph_schema = schema["properties"]["wind_kph"]
        assert "minimum" in wind_kph_schema
        assert wind_kph_schema["minimum"] == 0
    
    def test_pitch_condition_schema_defines_surface_enum(self, schemas_dir):
        """Verify pitch_condition surface enum includes natural_grass, artificial_turf, etc."""
        with open(schemas_dir / "pitch_condition.v1.json") as f:
            schema = json.load(f)
        surface_schema = schema["properties"]["surface"]
        assert "enum" in surface_schema
        assert "natural_grass" in surface_schema["enum"]
        assert "artificial_turf" in surface_schema["enum"]
        assert "hybrid" in surface_schema["enum"]
        assert "indoor" in surface_schema["enum"]


class TestRecordTypesTypeAnnotations:
    """Test that registered record types are valid TypedDicts."""
    
    def test_all_record_types_are_dict_compatible(self):
        """Verify all registered types can be instantiated as dicts."""
        # This is a smoke test; in real use, we would validate samples
        assert all(
            callable(t) or hasattr(t, '__annotations__')
            for t in RECORD_TYPES.values()
        )
    
    def test_transfer_type_has_expected_fields(self):
        """Verify TransferPayload has the expected TypedDict fields."""
        from ai.common.schemas.records import TransferPayload
        # TypedDict fields are accessible via __annotations__
        assert hasattr(TransferPayload, '__annotations__')
        annotations = TransferPayload.__annotations__
        assert "transfer_id" in annotations
        assert "player_id" in annotations
        assert "to_team_id" in annotations
        assert "announced_at" in annotations
