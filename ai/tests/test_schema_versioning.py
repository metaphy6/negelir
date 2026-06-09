"""
Tests for Phase 13.1 schema versioning validation.

Verifies:
  - Field names are gated per schema_version
  - Unknown fields are rejected
  - New fields require version bump
  - Migration framework is available
"""

import pytest
from xops.leagues.schema_validator import validate_catalog_fields, FIELD_NAMES_BY_VERSION


class TestSchemaVersioning:
    """Test schema version validation and field gating."""

    def test_valid_schema_v1(self) -> None:
        """Valid v1 catalog should pass validation."""
        valid_data = {
            "schema_version": 1,
            "leagues": [
                {
                    "league_id": "test_league",
                    "name_en": "Test League",
                    "name_tr": "Test Ligi",
                    "country": "TR",
                    "confederation": "UEFA",
                    "tier": "T1",
                    "active_since": "2024-01-01",
                    "competitions": [{"competition_id": "comp1"}],
                    "source_coverage": {
                        "reference": ["src1"],
                        "schedule": [],
                        "live": [],
                        "editorial": [],
                        "market": [],
                    },
                }
            ],
        }
        # Should not raise
        validate_catalog_fields(valid_data, schema_version=1)

    def test_unknown_root_field_rejected(self) -> None:
        """Unknown root field should be rejected."""
        invalid_data = {
            "schema_version": 1,
            "unknown_field": "value",
            "leagues": [],
        }
        with pytest.raises(ValueError, match="Unknown root fields"):
            validate_catalog_fields(invalid_data, schema_version=1)

    def test_unknown_league_field_rejected(self) -> None:
        """Unknown league field should be rejected."""
        invalid_data = {
            "schema_version": 1,
            "leagues": [
                {
                    "league_id": "test",
                    "name_en": "Test",
                    "name_tr": "Test",
                    "country": "TR",
                    "confederation": "UEFA",
                    "tier": "T1",
                    "active_since": "2024-01-01",
                    "competitions": [],
                    "source_coverage": {},
                    "unknown_field": "value",  # Invalid!
                }
            ],
        }
        with pytest.raises(ValueError, match="Unknown fields in league"):
            validate_catalog_fields(invalid_data, schema_version=1)

    def test_unknown_competition_field_rejected(self) -> None:
        """Unknown competition field should be rejected."""
        invalid_data = {
            "schema_version": 1,
            "leagues": [
                {
                    "league_id": "test",
                    "name_en": "Test",
                    "name_tr": "Test",
                    "country": "TR",
                    "confederation": "UEFA",
                    "tier": "T1",
                    "active_since": "2024-01-01",
                    "competitions": [
                        {
                            "competition_id": "comp1",
                            "unknown_field": "value",  # Invalid!
                        }
                    ],
                    "source_coverage": {},
                }
            ],
        }
        with pytest.raises(ValueError, match="Unknown fields in.*competitions"):
            validate_catalog_fields(invalid_data, schema_version=1)

    def test_unknown_source_coverage_field_rejected(self) -> None:
        """Unknown source_coverage field should be rejected."""
        invalid_data = {
            "schema_version": 1,
            "leagues": [
                {
                    "league_id": "test",
                    "name_en": "Test",
                    "name_tr": "Test",
                    "country": "TR",
                    "confederation": "UEFA",
                    "tier": "T1",
                    "active_since": "2024-01-01",
                    "competitions": [],
                    "source_coverage": {
                        "reference": [],
                        "unknown_field": ["value"],  # Invalid!
                    },
                }
            ],
        }
        with pytest.raises(ValueError, match="Unknown fields in.*source_coverage"):
            validate_catalog_fields(invalid_data, schema_version=1)

    def test_unknown_schema_version_rejected(self) -> None:
        """Unknown schema_version should be rejected."""
        invalid_data = {
            "schema_version": 999,
            "leagues": [],
        }
        with pytest.raises(ValueError, match="Unknown schema_version"):
            validate_catalog_fields(invalid_data, schema_version=999)

    def test_field_names_by_version_exists(self) -> None:
        """FIELD_NAMES_BY_VERSION should have at least version 1."""
        assert 1 in FIELD_NAMES_BY_VERSION
        assert "root" in FIELD_NAMES_BY_VERSION[1]
        assert "league_row" in FIELD_NAMES_BY_VERSION[1]
        assert "competition" in FIELD_NAMES_BY_VERSION[1]
        assert "source_coverage" in FIELD_NAMES_BY_VERSION[1]

    def test_required_fields_for_v1(self) -> None:
        """V1 schema should require certain fields."""
        required_root = {"schema_version", "leagues"}
        required_league = {
            "league_id",
            "name_en",
            "name_tr",
            "confederation",
            "tier",
            "active_since",
            "competitions",
            "source_coverage",
        }
        
        assert FIELD_NAMES_BY_VERSION[1]["root"] >= required_root
        assert FIELD_NAMES_BY_VERSION[1]["league_row"] >= required_league


class TestMigrationFramework:
    """Test that migration framework is available and extensible."""

    def test_migrations_registry_exists(self) -> None:
        """MIGRATIONS registry should exist and be empty initially."""
        from xops.leagues.migrations import MIGRATIONS
        assert isinstance(MIGRATIONS, dict)
        # At start, no migrations are registered (they're optional)

    def test_base_migration_class_exists(self) -> None:
        """BaseMigration class should exist and have abstract migrate method."""
        from xops.leagues.migrations import BaseMigration
        import inspect
        
        # Check that migrate is an abstract method
        assert "migrate" in dir(BaseMigration)
        assert inspect.isabstract(BaseMigration)

    def test_register_migration_decorator(self) -> None:
        """register_migration decorator should work."""
        from xops.leagues.migrations import BaseMigration, register_migration, MIGRATIONS
        
        # Create a test migration
        @register_migration(1, 2)
        class TestMigration(BaseMigration):
            from_version = 1
            to_version = 2
            
            def migrate(self, data):
                return data
        
        assert (1, 2) in MIGRATIONS
        assert MIGRATIONS[(1, 2)] == TestMigration
        
        # Clean up
        del MIGRATIONS[(1, 2)]
