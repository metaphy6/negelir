"""Phase 18.6 §18.6 ledger #11 — Per-component DB roles exist."""
from __future__ import annotations

import os
import pytest


class TestPerComponentDbRolesExist:
    """Proof test: All four per-component Postgres roles exist in migrations."""

    def test_migration_016_defines_datasource_writer_role(self) -> None:
        """Migration 016 creates datasource_writer role."""
        migration_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "migrations",
            "016_phase18_db_roles.sql",
        )
        with open(migration_path, "r") as fh:
            content = fh.read()
        assert "datasource_writer" in content
        assert "CREATE ROLE datasource_writer" in content

    def test_migration_016_defines_swarm_reader_role(self) -> None:
        """Migration 016 creates swarm_reader role."""
        migration_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "migrations",
            "016_phase18_db_roles.sql",
        )
        with open(migration_path, "r") as fh:
            content = fh.read()
        assert "swarm_reader" in content
        assert "CREATE ROLE swarm_reader" in content

    def test_migration_016_defines_server_reader_role(self) -> None:
        """Migration 016 creates server_reader role."""
        migration_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "migrations",
            "016_phase18_db_roles.sql",
        )
        with open(migration_path, "r") as fh:
            content = fh.read()
        assert "server_reader" in content
        assert "CREATE ROLE server_reader" in content

    def test_migration_016_defines_patcher_writer_role(self) -> None:
        """Migration 016 creates patcher_writer role."""
        migration_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "migrations",
            "016_phase18_db_roles.sql",
        )
        with open(migration_path, "r") as fh:
            content = fh.read()
        assert "patcher_writer" in content
        assert "CREATE ROLE patcher_writer" in content

    def test_all_roles_are_nologin(self) -> None:
        """All component roles are NOLOGIN by default."""
        migration_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "migrations",
            "016_phase18_db_roles.sql",
        )
        with open(migration_path, "r") as fh:
            content = fh.read()
        # Each role creation should include NOLOGIN
        for role in [
            "datasource_writer",
            "swarm_reader",
            "server_reader",
            "patcher_writer",
        ]:
            # Verify the role exists and NOLOGIN is mentioned
            assert f"CREATE ROLE {role} NOLOGIN" in content

    def test_config_provides_per_role_dsn_methods(self) -> None:
        """Config class provides DSN methods for each role."""
        from common.config import cfg

        # Each role should have its own DSN method
        assert hasattr(cfg, "pg_dsn_datasource_writer")
        assert hasattr(cfg, "pg_dsn_swarm_reader")
        assert hasattr(cfg, "pg_dsn_server_reader")
        assert hasattr(cfg, "pg_dsn_patcher_writer")

    def test_config_per_role_dsn_contains_role_name(self) -> None:
        """Per-role DSN methods include the correct role name."""
        from common.config import cfg

        assert "datasource_writer" in cfg.pg_dsn_datasource_writer
        assert "swarm_reader" in cfg.pg_dsn_swarm_reader
        assert "server_reader" in cfg.pg_dsn_server_reader
        assert "patcher_writer" in cfg.pg_dsn_patcher_writer
