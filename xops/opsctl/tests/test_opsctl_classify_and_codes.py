"""Phase 8 §8.1 — exit-code stability + classifier shape tests."""
from __future__ import annotations

import unittest

from xops.opsctl._classify import (
    Action,
    ALWAYS_DESTRUCTIVE,
    ALWAYS_SAFE,
    ClassifyRequest,
    classify,
)
from xops.opsctl._exit_codes import ExitCode


class TestExitCodes(unittest.TestCase):
    """Pin the integer values: runbooks branch on these."""

    def test_pinned_values(self) -> None:
        # Adding a code is fine; renumbering an existing one breaks
        # operator scripts and the dead-mans-switch alerter.
        self.assertEqual(int(ExitCode.OK), 0)
        self.assertEqual(int(ExitCode.GENERIC_FAILURE), 1)
        self.assertEqual(int(ExitCode.HARD_TIMEOUT), 2)
        self.assertEqual(int(ExitCode.PARTIAL_ACK_TIMEOUT), 3)
        self.assertEqual(int(ExitCode.BUS_DOWN_SPOOLED), 4)
        self.assertEqual(int(ExitCode.NO_CONSUMER_FOR_KIND), 5)
        self.assertEqual(int(ExitCode.UNKNOWN_KIND), 6)
        self.assertEqual(int(ExitCode.REQUIRES_RESUME_FIRST), 7)
        self.assertEqual(int(ExitCode.SPOOL_FLUSH_ALREADY_RUNNING), 8)
        self.assertEqual(int(ExitCode.OPSCTL_KEY_REVOKED), 9)
        self.assertEqual(int(ExitCode.PRUNE_ONLY_FORBIDDEN), 10)
        self.assertEqual(int(ExitCode.MAINT_STORAGE_FULL), 11)
        self.assertEqual(int(ExitCode.BAD_USAGE), 64)


class TestClassify(unittest.TestCase):
    def test_always_safe(self) -> None:
        for name in ALWAYS_SAFE:
            self.assertEqual(
                classify(ClassifyRequest(subcommand=name)),
                Action.SAFE,
                msg=f"{name} expected SAFE",
            )

    def test_always_destructive(self) -> None:
        for name in ALWAYS_DESTRUCTIVE:
            self.assertEqual(
                classify(ClassifyRequest(subcommand=name)),
                Action.CONFIRM,
                msg=f"{name} expected CONFIRM",
            )

    def test_critical_agent_bumps_to_confirm(self) -> None:
        # An otherwise-safe operation against a critical agent target
        # must be promoted to CONFIRM.
        decision = classify(ClassifyRequest(
            subcommand="some-agent-op",
            target_agent="consensus.v1",
            critical_agents=frozenset({"consensus.v1"}),
        ))
        self.assertEqual(decision, Action.CONFIRM)

    def test_dlq_replay_sec_topic_without_pii_confirm_refused(self) -> None:
        decision = classify(ClassifyRequest(
            subcommand="dlq-replay",
            flags=frozenset({"topic_sec"}),
        ))
        self.assertEqual(decision, Action.REFUSE)

    def test_dlq_replay_sec_topic_with_pii_confirm_ok(self) -> None:
        decision = classify(ClassifyRequest(
            subcommand="dlq-replay",
            flags=frozenset({"topic_sec", "confirm_pii"}),
        ))
        self.assertEqual(decision, Action.SAFE)

    def test_dlq_replay_drop_is_destructive(self) -> None:
        decision = classify(ClassifyRequest(
            subcommand="dlq-replay",
            flags=frozenset({"drop"}),
        ))
        self.assertEqual(decision, Action.CONFIRM)


if __name__ == "__main__":
    unittest.main()
