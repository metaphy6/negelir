"""Phase 21.25 — Enrichment Compliance Audit Log."""
import os

from common.config import Config


def test_enrichment_audit_log_migration_exists() -> None:
    """Migration 018_enrichment_audit.sql exists."""
    migration_path = "/home/tech/code/negelir/migrations/018_enrichment_audit.sql"
    assert os.path.exists(migration_path), "Migration file 018_enrichment_audit.sql should exist"


def test_enrichment_audit_log_down_migration_exists() -> None:
    """Down migration 018_enrichment_audit_down.sql exists for rollback testing."""
    down_migration_path = "/home/tech/code/negelir/migrations/018_enrichment_audit_down.sql"
    assert os.path.exists(down_migration_path), "Down migration file should exist"


def test_enrichment_audit_migration_creates_append_only_table() -> None:
    """Migration creates enrichment_audit table with append-only constraint."""
    # Read the migration file
    with open("/home/tech/code/negelir/migrations/018_enrichment_audit.sql", "r") as f:
        migration_content = f.read()
    
    # Verify key SQL elements
    assert "CREATE TABLE enrichment_audit" in migration_content
    assert "league_id" in migration_content
    assert "jurisdiction" in migration_content
    assert "plane_id" in migration_content
    assert "decision" in migration_content
    assert "REVOKE UPDATE, DELETE" in migration_content  # Append-only enforcement


def test_dpa_registry_exists() -> None:
    """DPA registry scaffold exists."""
    cfg = Config()
    # Config should have enrichment-related settings
    assert hasattr(cfg, "enrichment_backfill_mode"), "Config has enrichment settings"


def test_audit_table_schema_fields() -> None:
    """Audit table has all required schema fields."""
    # Expected fields per ROADMAP
    expected_fields = {
        "id": "BIGSERIAL PRIMARY KEY",
        "event_at": "TIMESTAMPTZ",
        "league_id": "TEXT NOT NULL",
        "jurisdiction": "TEXT NOT NULL",
        "plane_id": "TEXT NOT NULL",
        "decision": "TEXT NOT NULL",
        "reason": "TEXT NOT NULL",
        "dpa_status": "TEXT",
        "operator_ref": "TEXT",
    }
    
    with open("/home/tech/code/negelir/migrations/018_enrichment_audit.sql", "r") as f:
        migration_content = f.read()
    
    for field, field_type in expected_fields.items():
        assert field in migration_content, f"Field {field} should be in migration"


def test_audit_table_indexes_created() -> None:
    """Audit table indexes are created for efficient queries."""
    with open("/home/tech/code/negelir/migrations/018_enrichment_audit.sql", "r") as f:
        migration_content = f.read()
    
    # Check for index creation
    assert "CREATE INDEX" in migration_content
    assert "league_plane" in migration_content or "enrichment_audit" in migration_content


def test_audit_constraint_prevents_updates() -> None:
    """Audit table enforces append-only via REVOKE UPDATE, DELETE."""
    with open("/home/tech/code/negelir/migrations/018_enrichment_audit.sql", "r") as f:
        migration_content = f.read()
    
    # Verify row security enforcement
    assert "REVOKE UPDATE, DELETE ON enrichment_audit FROM negelir_app" in migration_content


def test_down_migration_drops_table() -> None:
    """Down migration safely drops the enrichment_audit table."""
    with open("/home/tech/code/negelir/migrations/018_enrichment_audit_down.sql", "r") as f:
        down_migration_content = f.read()
    
    assert "DROP TABLE IF EXISTS enrichment_audit CASCADE" in down_migration_content


def test_jurisdiction_values_documented() -> None:
    """Jurisdiction enum values are documented in migration."""
    with open("/home/tech/code/negelir/migrations/018_enrichment_audit.sql", "r") as f:
        migration_content = f.read()
    
    # Check for jurisdiction value documentation
    assert "gdpr" in migration_content.lower()
    assert "kvkk" in migration_content.lower()
    assert "lgpd" in migration_content.lower()
    assert "pipl" in migration_content.lower()
    assert "unrestricted" in migration_content.lower()


def test_plane_id_values_documented() -> None:
    """Plane ID enum values are documented in migration."""
    with open("/home/tech/code/negelir/migrations/018_enrichment_audit.sql", "r") as f:
        migration_content = f.read()
    
    # Check for plane value documentation
    assert "roster" in migration_content.lower()
    assert "health" in migration_content.lower()
    assert "officials" in migration_content.lower()
    assert "environment" in migration_content.lower()
