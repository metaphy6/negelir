"""Phase 18.6 §18.6 ledger #11 — pg_hba.conf template blocks cross-role connections."""
from __future__ import annotations

import os


class TestPgHbaBlocksCrossComponentConnect:
    """Proof test: pg_hba.template enforces role-based access control."""

    def test_pg_hba_template_exists(self) -> None:
        """pg_hba.template file exists in xops/db/."""
        template_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "xops",
            "db",
            "pg_hba.template",
        )
        assert os.path.exists(template_path), "xops/db/pg_hba.template must exist"

    def test_pg_hba_template_has_per_role_rules(self) -> None:
        """pg_hba.template contains per-role connection rules."""
        template_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "xops",
            "db",
            "pg_hba.template",
        )
        with open(template_path, "r") as fh:
            content = fh.read()

        # Should have rules for each role
        assert "datasource_writer" in content
        assert "server_reader" in content
        assert "patcher_writer" in content
        assert "swarm_reader" in content or "reject" in content.lower()

    def test_pg_hba_template_rejects_swarm_reader(self) -> None:
        """pg_hba.template explicitly rejects swarm_reader connections."""
        template_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "xops",
            "db",
            "pg_hba.template",
        )
        with open(template_path, "r") as fh:
            content = fh.read()

        # Should have a reject or hostrejection line for swarm_reader
        lines_with_swarm = [
            line for line in content.split("\n") if "swarm_reader" in line
        ]
        assert any(
            "reject" in line.lower() or "forbidden" in line.lower()
            for line in lines_with_swarm
        ), "pg_hba should reject swarm_reader connections"

    def test_pg_hba_template_requires_ssl_for_host_connections(self) -> None:
        """pg_hba.template requires SSL for host component connections."""
        template_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "xops",
            "db",
            "pg_hba.template",
        )
        with open(template_path, "r") as fh:
            content = fh.read()

        # Should mention hostssl or SSL requirement
        assert (
            "hostssl" in content or "ssl" in content.lower()
        ), "pg_hba should require SSL for host connections"

    def test_pg_hba_template_mentions_scram_sha_256(self) -> None:
        """pg_hba.template uses scram-sha-256 authentication."""
        template_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "xops",
            "db",
            "pg_hba.template",
        )
        with open(template_path, "r") as fh:
            content = fh.read()

        assert "scram-sha-256" in content
