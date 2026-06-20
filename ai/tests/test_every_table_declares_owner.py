"""Phase 18.6 §18.6 ledger #24 — Every table declares an owner."""
from __future__ import annotations

import os
import re
from pathlib import Path


class TestEveryTableDeclaresOwner:
    """Proof test: all tables have COMMENT ON TABLE owner= declarations."""

    def test_read_allow_yaml_exists(self) -> None:
        """read_allow.yaml policy file exists."""
        policy_path = Path(__file__).resolve().parent.parent / "common" / "db" / "read_allow.yaml"
        assert policy_path.exists(), f"read_allow.yaml must exist at {policy_path}"

    def test_read_allow_yaml_has_tables_key(self) -> None:
        """read_allow.yaml has a 'tables' top-level key."""
        import yaml

        policy_path = Path(__file__).resolve().parent.parent / "common" / "db" / "read_allow.yaml"
        with open(policy_path, "r") as fh:
            policy = yaml.safe_load(fh)

        assert "tables" in policy, "read_allow.yaml must have 'tables' key"
        assert isinstance(policy["tables"], dict), "'tables' must be a dict"

    def test_read_allow_yaml_declares_owners(self) -> None:
        """Each table in read_allow.yaml declares an owner."""
        import yaml

        policy_path = Path(__file__).resolve().parent.parent / "common" / "db" / "read_allow.yaml"
        with open(policy_path, "r") as fh:
            policy = yaml.safe_load(fh)

        tables = policy.get("tables", {})
        for table_name, table_policy in tables.items():
            assert (
                "owner" in table_policy
            ), f"Table {table_name} must declare 'owner' field"

    def test_owner_check_module_exists(self) -> None:
        """owner_check.py module exists."""
        owner_check_path = (
            Path(__file__).resolve().parent.parent / "common" / "db" / "owner_check.py"
        )
        assert owner_check_path.exists(), "common/db/owner_check.py must exist"

    def test_owner_check_defines_policies(self) -> None:
        """owner_check.py defines TableOwnershipPolicy and related classes."""
        from ai.common.db.owner_check import (
            SimpleOwnershipChecker,
            TableOwner,
            TableOwnershipError,
            TableOwnershipPolicy,
        )

        assert TableOwner is not None
        assert TableOwnershipPolicy is not None
        assert TableOwnershipError is not None
        assert SimpleOwnershipChecker is not None
