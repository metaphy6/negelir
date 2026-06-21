"""Tests for schema generator three-way consistency (Phase 16.3, bullet 7)."""

import json
import pytest
from pathlib import Path
from ai.common.schemas.records import Score, Schedule, Market, Lineup, RECORD_TYPES
from ai.common.feeds.schema_generator import (
    typeddict_to_pyarrow_schema,
    validate_schema_consistency,
    compute_schema_hash,
)


SCHEMAS_DIR = Path(__file__).parent.parent / "common" / "schemas"
FEEDS_DIR = SCHEMAS_DIR / "feeds"


class TestSchemaGenerator:
    """Tests for TypedDict to pyarrow schema conversion."""
    
    def test_score_schema_generation(self):
        """Generate pyarrow schema from Score TypedDict."""
        schema = typeddict_to_pyarrow_schema(Score)
        
        # Check required fields are present
        assert "match_stable_id" in schema
        assert "minute" in schema
        assert "status" in schema
        assert "home" in schema
        assert "away" in schema
        
        # Check types
        assert schema["match_stable_id"] == "string"
        assert schema["minute"] == "int64"
        assert schema["status"] == "string"
    
    def test_schedule_schema_generation(self):
        """Generate pyarrow schema from Schedule TypedDict."""
        schema = typeddict_to_pyarrow_schema(Schedule)
        
        assert "match_stable_id" in schema
        assert "kickoff_utc" in schema
        assert "competition" in schema
        assert "home" in schema
        assert "away" in schema
        assert schema["match_stable_id"] == "string"
    
    def test_market_schema_generation(self):
        """Generate pyarrow schema from Market TypedDict."""
        schema = typeddict_to_pyarrow_schema(Market)
        
        assert "match_stable_id" in schema
        assert "market_name" in schema
        assert "updated_at" in schema
        assert schema["match_stable_id"] == "string"
    
    def test_lineup_schema_generation(self):
        """Generate pyarrow schema from Lineup TypedDict."""
        schema = typeddict_to_pyarrow_schema(Lineup)
        
        assert "match_stable_id" in schema
        assert "team_id" in schema
        assert "confirmed_at" in schema
        assert "players" in schema
        assert "list" in schema["players"]  # Should be a list type
    
    def test_schema_determinism(self):
        """Generated schemas are deterministic (same input → same output)."""
        schema1 = typeddict_to_pyarrow_schema(Score)
        schema2 = typeddict_to_pyarrow_schema(Score)
        
        assert schema1 == schema2
    
    def test_schema_hash_determinism(self):
        """Schema hashes are deterministic."""
        schema = typeddict_to_pyarrow_schema(Score)
        hash1 = compute_schema_hash(schema)
        hash2 = compute_schema_hash(schema)
        
        assert hash1 == hash2
        assert len(hash1) == 64  # SHA256 hex digest


class TestThreeWayConsistency:
    """Tests for three-way schema consistency validation."""
    
    def test_score_three_way_consistency(self):
        """Score schema: TypedDict ↔ JSONSchema ↔ pyarrow."""
        schema = typeddict_to_pyarrow_schema(Score)
        json_schema_path = FEEDS_DIR / "score.v1.json"
        
        if not json_schema_path.exists():
            pytest.skip("score.v1.json not found")
        
        result = validate_schema_consistency(Score, json_schema_path, schema)
        
        # Required fields from JSON schema should be in TypedDict
        assert result["consistent"] is True
        assert "match_stable_id" in result["typed_dict_fields"]
        assert "minute" in result["typed_dict_fields"]
        assert "status" in result["typed_dict_fields"]
    
    def test_schedule_three_way_consistency(self):
        """Schedule schema: TypedDict ↔ JSONSchema ↔ pyarrow."""
        schema = typeddict_to_pyarrow_schema(Schedule)
        json_schema_path = FEEDS_DIR / "schedule.v1.json"
        
        if not json_schema_path.exists():
            pytest.skip("schedule.v1.json not found")
        
        result = validate_schema_consistency(Schedule, json_schema_path, schema)
        
        assert result["consistent"] is True
        assert "match_stable_id" in result["typed_dict_fields"]
    
    def test_consistency_result_structure(self):
        """Consistency check returns expected structure."""
        schema = typeddict_to_pyarrow_schema(Market)
        json_schema_path = FEEDS_DIR / "market.v1.json"
        
        if not json_schema_path.exists():
            pytest.skip("market.v1.json not found")
        
        result = validate_schema_consistency(Market, json_schema_path, schema)
        
        # Verify result structure
        assert "consistent" in result
        assert "matches" in result
        assert "pyarrow_schema" in result
        assert "typed_dict_fields" in result
        assert "json_schema_fields" in result
        
        # Result schema should match input
        assert result["pyarrow_schema"] == schema
    
    def test_record_types_registry(self):
        """RECORD_TYPES registry contains all major feed types."""
        assert "score" in RECORD_TYPES
        assert "schedule" in RECORD_TYPES
        assert "market" in RECORD_TYPES
        assert "lineup" in RECORD_TYPES
        
        # Each should generate a valid schema
        for name, typed_dict_cls in RECORD_TYPES.items():
            schema = typeddict_to_pyarrow_schema(typed_dict_cls)
            assert isinstance(schema, dict)
            assert len(schema) > 0


class TestSchemaIntegration:
    """Integration tests for schema consistency workflow."""
    
    def test_all_schemas_generate_deterministically(self):
        """All RECORD_TYPES schemas are deterministic."""
        schemas_run1 = {
            name: typeddict_to_pyarrow_schema(cls)
            for name, cls in RECORD_TYPES.items()
        }
        schemas_run2 = {
            name: typeddict_to_pyarrow_schema(cls)
            for name, cls in RECORD_TYPES.items()
        }
        
        assert schemas_run1 == schemas_run2
    
    def test_all_schemas_have_unique_hashes(self):
        """Different schemas produce different hashes."""
        score_schema = typeddict_to_pyarrow_schema(Score)
        market_schema = typeddict_to_pyarrow_schema(Market)
        
        score_hash = compute_schema_hash(score_schema)
        market_hash = compute_schema_hash(market_schema)
        
        assert score_hash != market_hash
    
    def test_schema_hash_stable_across_runs(self):
        """Schema hash for a given TypedDict is stable."""
        score_schema = typeddict_to_pyarrow_schema(Score)
        hash1 = compute_schema_hash(score_schema)
        
        # Regenerate and check hash is stable
        score_schema_again = typeddict_to_pyarrow_schema(Score)
        hash2 = compute_schema_hash(score_schema_again)
        
        assert hash1 == hash2
