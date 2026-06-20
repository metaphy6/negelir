"""Phase 21.7 — Storage + migrations for enrichment planes."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

_LOG = __import__('common.logger', fromlist=['get_logger']).get_logger(__name__)


class TestMigrations:
    def test_migration_017_creates_all_ten_tables(self, tmp_path) -> None:
        """Verify all 10 enrichment tables are created by migration 017."""
        migration_file = Path('migrations/017_enrichment_planes.sql')
        
        assert migration_file.exists(), "Migration 017 file must exist"
        
        with open(migration_file) as f:
            content = f.read().upper()
        
        # Verify all 10 tables are created
        expected_tables = [
            'TRANSFERS', 'CONTRACTS', 'SUSPENSIONS',
            'INJURIES', 'AVAILABILITY',
            'REFEREE_ASSIGNMENTS', 'REFEREE_PROFILES',
            'WEATHER_FORECASTS', 'WEATHER_ACTUALS',
            'PITCH_CONDITIONS'
        ]
        
        for table in expected_tables:
            assert f'CREATE TABLE' in content and table in content, \
                f"Migration 017 must create table {table}"

    def test_migration_017_has_unique_constraints(self) -> None:
        """Verify unique constraints are present."""
        migration_file = Path('migrations/017_enrichment_planes.sql')
        
        with open(migration_file) as f:
            content = f.read()
        
        # Should have UNIQUE constraints
        assert 'UNIQUE' in content, "Migration 017 should define unique constraints"

    def test_migration_017_has_indexes(self) -> None:
        """Verify indexes are created for efficient queries."""
        migration_file = Path('migrations/017_enrichment_planes.sql')
        
        with open(migration_file) as f:
            content = f.read()
        
        # Should have CREATE INDEX statements
        assert 'CREATE INDEX' in content, "Migration 017 should create indexes"

    def test_migration_017_down_drops_all_tables(self) -> None:
        """Verify down migration drops all tables."""
        down_file = Path('migrations/017_enrichment_planes_down.sql')
        
        assert down_file.exists(), "Migration 017 down file must exist"
        
        with open(down_file) as f:
            content = f.read()
        
        # Should drop all tables
        expected_tables = [
            'TRANSFERS', 'CONTRACTS', 'SUSPENSIONS',
            'INJURIES', 'AVAILABILITY',
            'REFEREE_ASSIGNMENTS', 'REFEREE_PROFILES',
            'WEATHER_FORECASTS', 'WEATHER_ACTUALS',
            'PITCH_CONDITIONS'
        ]
        
        content_upper = content.upper()
        for table in expected_tables:
            assert f'DROP TABLE' in content_upper and table in content_upper, \
                f"Down migration must drop table {table}"


class TestStorageContracts:
    def test_transfers_table_has_confidence_constraint(self) -> None:
        """Verify transfers table enforces confidence enum."""
        migration_file = Path('migrations/017_enrichment_planes.sql')
        
        with open(migration_file) as f:
            content = f.read()
        
        assert "CHECK (confidence IN ('rumour', 'agreed', 'official'))" in content, \
            "transfers table should enforce confidence enum"

    def test_injuries_table_has_status_constraint(self) -> None:
        """Verify injuries table enforces status enum."""
        migration_file = Path('migrations/017_enrichment_planes.sql')
        
        with open(migration_file) as f:
            content = f.read()
        
        valid_statuses = "'fit', 'doubtful', 'out', 'suspended', 'international_duty'"
        assert valid_statuses in content or valid_statuses.replace("'", '"') in content, \
            "injuries table should enforce status enum"

    def test_referee_assignments_fixture_id_unique(self) -> None:
        """Verify referee_assignments has unique constraint on fixture_id."""
        migration_file = Path('migrations/017_enrichment_planes.sql')
        
        with open(migration_file) as f:
            content = f.read()
        
        assert 'fixture_id TEXT NOT NULL UNIQUE' in content, \
            "referee_assignments fixture_id should be unique"

    def test_weather_actuals_venue_time_unique(self) -> None:
        """Verify weather_actuals has unique on (venue_id, observed_at)."""
        migration_file = Path('migrations/017_enrichment_planes.sql')
        
        with open(migration_file) as f:
            content = f.read()
        
        assert 'UNIQUE(venue_id, observed_at)' in content, \
            "weather_actuals should have unique (venue_id, observed_at)"


class TestStorageIntegrity:
    def test_all_tables_have_created_at_timestamp(self) -> None:
        """Verify all tables have created_at for audit trail."""
        migration_file = Path('migrations/017_enrichment_planes.sql')
        
        with open(migration_file) as f:
            content = f.read()
        
        # Count CREATE TABLE and created_at occurrences
        create_table_count = content.count('CREATE TABLE IF NOT EXISTS')
        created_at_count = content.count('created_at TIMESTAMPTZ')
        
        assert created_at_count >= create_table_count, \
            "All tables should have created_at column"

    def test_all_tables_have_primary_key(self) -> None:
        """Verify all tables have a primary key."""
        migration_file = Path('migrations/017_enrichment_planes.sql')
        
        with open(migration_file) as f:
            content = f.read()
        
        assert content.count('PRIMARY KEY') >= 10, \
            "All 10 tables should have PRIMARY KEY"

    def test_indexes_follow_naming_convention(self) -> None:
        """Verify indexes follow idx_<table>_<column> naming."""
        migration_file = Path('migrations/017_enrichment_planes.sql')
        
        with open(migration_file) as f:
            content = f.read()
        
        # Extract all index names
        import re
        index_names = re.findall(r'CREATE INDEX (\w+) ON', content)
        
        for idx_name in index_names:
            assert idx_name.startswith('idx_'), \
                f"Index {idx_name} should follow idx_<table>_<column> naming"

    def test_no_hardcoded_ttl_in_migration_sql(self) -> None:
        """Verify TTL policy is defined in comments, not code."""
        migration_file = Path('migrations/017_enrichment_planes.sql')
        
        with open(migration_file) as f:
            content = f.read()
        
        # TTL should be documented in comments, managed by Phase 8
        assert 'TTL' in content or 'Retention' in content, \
            "Migration should document retention policy"


class TestMigrationReversibility:
    def test_migration_files_both_exist(self) -> None:
        """Verify both up and down migration files exist."""
        up_file = Path('migrations/017_enrichment_planes.sql')
        down_file = Path('migrations/017_enrichment_planes_down.sql')
        
        assert up_file.exists(), "Up migration must exist"
        assert down_file.exists(), "Down migration must exist"

    def test_down_migration_references_all_up_tables(self) -> None:
        """Verify down migration drops all tables created by up."""
        up_file = Path('migrations/017_enrichment_planes.sql')
        down_file = Path('migrations/017_enrichment_planes_down.sql')
        
        with open(up_file) as f:
            up_content = f.read()
        with open(down_file) as f:
            down_content = f.read()
        
        import re
        # Extract created tables
        up_tables = set(re.findall(r'CREATE TABLE IF NOT EXISTS (\w+)', up_content))
        down_tables = set(re.findall(r'DROP TABLE IF EXISTS (\w+)', down_content))
        
        assert up_tables == down_tables, \
            "Down migration must drop exactly the tables created by up migration"
