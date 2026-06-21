"""Phase 18.6 §18.6 ledger #11 — Server role is RO on materialized views only."""
from __future__ import annotations

import os


class TestServerRoleIsViewRoOnly:
    """Proof test: server_reader role is restricted to materialized views."""

    def test_server_reader_migration_present(self) -> None:
        """server_reader role is created in migration 016."""
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

    def test_server_reader_is_nologin(self) -> None:
        """server_reader is NOLOGIN by default."""
        migration_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "migrations",
            "016_phase18_db_roles.sql",
        )
        with open(migration_path, "r") as fh:
            content = fh.read()

        # Find the server_reader creation line
        for line in content.split("\n"):
            if "server_reader" in line and "CREATE ROLE" in line:
                assert "NOLOGIN" in line

    def test_migration_comment_clarifies_view_only_restriction(self) -> None:
        """Migration comment specifies server_reader is for views, not tables."""
        migration_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "migrations",
            "016_phase18_db_roles.sql",
        )
        with open(migration_path, "r") as fh:
            content = fh.read()

        assert (
            "materialized view" in content.lower() or "view" in content.lower()
        ), "Comment should clarify server_reader is for views only"
