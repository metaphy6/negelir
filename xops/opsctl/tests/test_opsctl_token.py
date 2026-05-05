"""Phase 8 §8.1 — typed-token derivation tests."""
from __future__ import annotations

import unittest

from xops.opsctl._token import TOKEN_LEN, derive_confirm_token


class TestTokenDerivation(unittest.TestCase):
    def test_length_is_pinned(self) -> None:
        tok = derive_confirm_token(subcommand="quarantine-erase", target="s-1")
        self.assertEqual(len(tok), TOKEN_LEN)
        self.assertEqual(TOKEN_LEN, 8)

    def test_deterministic(self) -> None:
        a = derive_confirm_token(subcommand="quarantine-erase", target="s-1")
        b = derive_confirm_token(subcommand="quarantine-erase", target="s-1")
        self.assertEqual(a, b)

    def test_different_targets_differ(self) -> None:
        a = derive_confirm_token(subcommand="quarantine-erase", target="s-1")
        b = derive_confirm_token(subcommand="quarantine-erase", target="s-2")
        self.assertNotEqual(a, b)

    def test_different_subcommands_differ(self) -> None:
        a = derive_confirm_token(subcommand="quarantine-erase", target="x")
        b = derive_confirm_token(subcommand="restore", target="x")
        self.assertNotEqual(a, b)

    def test_salient_args_included(self) -> None:
        a = derive_confirm_token(
            subcommand="scale", target="agent.v1", salient_args={"replicas": 0}
        )
        b = derive_confirm_token(
            subcommand="scale", target="agent.v1", salient_args={"replicas": 3}
        )
        self.assertNotEqual(a, b)

    def test_empty_args_collapse_to_bare(self) -> None:
        # None / "" salient values must drop from the preimage so
        # default-flag invocations match the bare-target token.
        a = derive_confirm_token(subcommand="quarantine-erase", target="x")
        b = derive_confirm_token(
            subcommand="quarantine-erase", target="x",
            salient_args={"reason": "", "client": None},
        )
        self.assertEqual(a, b)

    def test_arg_ordering_is_canonical(self) -> None:
        a = derive_confirm_token(
            subcommand="op", target="t",
            salient_args={"a": 1, "b": 2},
        )
        b = derive_confirm_token(
            subcommand="op", target="t",
            salient_args={"b": 2, "a": 1},
        )
        self.assertEqual(a, b)

    def test_bool_flips_token(self) -> None:
        a = derive_confirm_token(
            subcommand="dlq-replay", target="t",
            salient_args={"drop": True},
        )
        b = derive_confirm_token(
            subcommand="dlq-replay", target="t",
            salient_args={"drop": False},
        )
        self.assertNotEqual(a, b)


if __name__ == "__main__":
    unittest.main()
