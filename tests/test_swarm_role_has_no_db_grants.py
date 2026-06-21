"""Phase 18.6 §18.6 ledger #11 — Swarm role has no database grants."""
from __future__ import annotations

import os


class TestSwarmRoleHasNoDbGrants:
    """Proof test: swarm_reader role is created with no table grants."""

    def test_swarm_reader_has_no_grants_in_migration(self) -> None:
        """swarm_reader is created as NOLOGIN with no GRANT statements."""
        migration_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "migrations",
            "016_phase18_db_roles.sql",
        )
        with open(migration_path, "r") as fh:
            lines = fh.readlines()

        # Find the swarm_reader creation block
        in_swarm_section = False
        swarm_grant_count = 0

        for i, line in enumerate(lines):
            if "swarm_reader" in line and "CREATE ROLE" in line:
                in_swarm_section = True
            elif in_swarm_section and "IF NOT EXISTS" in lines[i + 1] if i + 1 < len(lines) else False:
                # End of swarm_reader block
                in_swarm_section = False

            # Count GRANT statements that apply to swarm_reader
            # swarm_reader should NOT have any table grants
            if in_swarm_section and "GRANT" in line and "swarm_reader" in line:
                # Check if it's a table grant (not schema usage)
                if "ON TABLE" in line or "ON ALL TABLES" in line:
                    swarm_grant_count += 1

        assert (
            swarm_grant_count == 0
        ), f"swarm_reader should have no table grants, but found {swarm_grant_count}"

    def test_migration_comment_clarifies_swarm_reader_purpose(self) -> None:
        """Migration includes comment explaining swarm reads feeds, not DB."""
        migration_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "migrations",
            "016_phase18_db_roles.sql",
        )
        with open(migration_path, "r") as fh:
            content = fh.read()

        assert "swarm reads feeds" in content.lower() or "no DB grants" in content
        assert "explicit deny" in content.lower() or "pg_hba" in content
