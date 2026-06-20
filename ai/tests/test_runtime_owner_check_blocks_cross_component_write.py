"""Phase 18.6 §18.6 ledger #24 — Runtime owner check blocks cross-component writes."""
from __future__ import annotations

import pytest

from ai.common.db.owner_check import (
    SimpleOwnershipChecker,
    TableOwner,
    TableOwnershipError,
    TableOwnershipPolicy,
)


class TestRuntimeOwnerCheckBlocksCrossComponentWrite:
    """Proof test: runtime check refuses writes from non-owner roles."""

    def test_owner_check_accepts_owner_role_write(self) -> None:
        """Owner role can write to its table."""
        policy = TableOwnershipPolicy(
            table_name="matches", owner_component=TableOwner.DATASOURCE
        )
        checker = SimpleOwnershipChecker(policies={"matches": policy})

        # datasource_writer is the owner, should be allowed
        checker.check_write_allowed("matches", "datasource_writer")

    def test_owner_check_rejects_non_owner_role_write(self) -> None:
        """Non-owner role cannot write to table."""
        policy = TableOwnershipPolicy(
            table_name="matches", owner_component=TableOwner.DATASOURCE
        )
        checker = SimpleOwnershipChecker(policies={"matches": policy})

        # server_reader is not the owner, should be rejected
        with pytest.raises(TableOwnershipError):
            checker.check_write_allowed("matches", "server_reader")

    def test_owner_check_rejects_swarm_reader_write(self) -> None:
        """Swarm cannot write to datasource tables."""
        policy = TableOwnershipPolicy(
            table_name="players", owner_component=TableOwner.DATASOURCE
        )
        checker = SimpleOwnershipChecker(policies={"players": policy})

        # swarm_reader should not be able to write
        with pytest.raises(TableOwnershipError):
            checker.check_write_allowed("players", "swarm_reader")

    def test_owner_check_patcher_table_isolation(self) -> None:
        """Only patcher_writer can write to patcher_* tables."""
        patcher_policy = TableOwnershipPolicy(
            table_name="patcher_status", owner_component=TableOwner.PATCHER
        )
        checker = SimpleOwnershipChecker(policies={"patcher_status": patcher_policy})

        # Only patcher_writer is allowed
        checker.check_write_allowed("patcher_status", "patcher_writer")

        # datasource_writer is not allowed
        with pytest.raises(TableOwnershipError):
            checker.check_write_allowed("patcher_status", "datasource_writer")

    def test_owner_check_read_allows_multiple_roles(self) -> None:
        """Read check allows owner and approved readers."""
        policy = TableOwnershipPolicy(
            table_name="matches",
            owner_component=TableOwner.DATASOURCE,
            allow_readonly_from=frozenset(["server_reader"]),
        )
        checker = SimpleOwnershipChecker(policies={"matches": policy})

        # Owner can read
        checker.check_read_allowed("matches", "datasource_writer")

        # Approved reader can read
        checker.check_read_allowed("matches", "server_reader")

        # Unapproved reader cannot read
        with pytest.raises(TableOwnershipError):
            checker.check_read_allowed("matches", "swarm_reader")

    def test_error_message_includes_table_and_role(self) -> None:
        """Error message includes table name and role for debugging."""
        policy = TableOwnershipPolicy(
            table_name="matches", owner_component=TableOwner.DATASOURCE
        )
        checker = SimpleOwnershipChecker(policies={"matches": policy})

        with pytest.raises(TableOwnershipError) as exc_info:
            checker.check_write_allowed("matches", "swarm_reader")

        error_msg = str(exc_info.value)
        assert "matches" in error_msg
        assert "swarm_reader" in error_msg
