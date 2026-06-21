"""Phase 18.6 §18.6 ledger #24 — Runtime table ownership enforcement.

Every Postgres table declares an owner component via COMMENT ON TABLE.
This module refuses writes from connections whose role doesn't match the table owner.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol


class TableOwnershipError(Exception):
    """Raised when a write is attempted by a role that doesn't own the table."""

    pass


class TableOwner(Enum):
    """Canonical table owner components."""

    DATASOURCE = "datasource"
    SWARM = "swarm"
    SERVER = "server"
    PATCHER = "patcher"
    COMMON = "common"


@dataclass(frozen=True)
class TableOwnershipPolicy:
    """Immutable policy for a single table."""

    table_name: str
    owner_component: TableOwner
    allow_readonly_from: frozenset[str] = frozenset()  # roles that can SELECT


class OwnershipChecker(Protocol):
    """Protocol for checking table ownership at runtime."""

    def check_write_allowed(
        self, table_name: str, current_role: str
    ) -> None:
        """Verify the current role is allowed to write to the table.

        Args:
            table_name: The table being written to.
            current_role: The Postgres role of the connection (user).

        Raises:
            TableOwnershipError: If the role does not own the table.
        """
        ...

    def check_read_allowed(self, table_name: str, current_role: str) -> None:
        """Verify the current role is allowed to read from the table.

        Args:
            table_name: The table being read from.
            current_role: The Postgres role of the connection (user).

        Raises:
            TableOwnershipError: If the role is not on the read-allow list.
        """
        ...


class SimpleOwnershipChecker:
    """Concrete ownership checker backed by a policy dict.

    In production, this would load from the read_allow.yaml policy and
    query table comments at boot time. For now, it's a minimal stub
    that can be extended.
    """

    def __init__(self, policies: dict[str, TableOwnershipPolicy] | None = None):
        """Initialize with an optional policy dict (table_name -> policy)."""
        self.policies = policies or {}

    def check_write_allowed(
        self, table_name: str, current_role: str
    ) -> None:
        """Enforce: only the owner role can write."""
        if table_name not in self.policies:
            # Table not tracked; allow (for backward compat during transition)
            return

        policy = self.policies[table_name]
        owner_role = f"{policy.owner_component.value}_writer"
        if current_role != owner_role:
            raise TableOwnershipError(
                f"Role {current_role} cannot write to {table_name} "
                f"(owner: {policy.owner_component.value})"
            )

    def check_read_allowed(self, table_name: str, current_role: str) -> None:
        """Enforce: only owner or approved readers can read."""
        if table_name not in self.policies:
            # Table not tracked; allow
            return

        policy = self.policies[table_name]
        owner_role = f"{policy.owner_component.value}_writer"
        if current_role != owner_role and current_role not in policy.allow_readonly_from:
            raise TableOwnershipError(
                f"Role {current_role} cannot read from {table_name} "
                f"(owner: {policy.owner_component.value})"
            )
