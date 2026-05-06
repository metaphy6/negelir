"""Phase 8 §8.1 — --dry-run smoke tests across publishing subcommands.

Dry-run MUST validate inputs, compute the expected ack set, and
print the envelope, but MUST NOT publish, MUST NOT acquire the
re-entrancy lock, and MUST NOT mutate the audit CSV.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

from ai.common.config import Config

from xops.opsctl._exit_codes import ExitCode
from xops.opsctl.subcommands import (
    baseline_reset,
    denylist_clear,
    quarantine_clear,
    quarantine_erase,
    spool_flush,
)


class _Env:
    """Pin per-test env so each subcommand resolves a fresh tmp dir."""

    def __init__(self, tmp: str) -> None:
        self.patches = {
            "NEGELIR_OPSCTL_AUDIT_PATH": str(Path(tmp) / "audit.csv"),
            "NEGELIR_OPSCTL_SPOOL_DIR": str(Path(tmp) / "spool"),
            "NEGELIR_OPSCTL_LOCK_DIR": str(Path(tmp) / "locks"),
            "NEGELIR_OPSCTL_ACK_TIMEOUT_MS": "1000",
        }
        self.old: dict[str, str | None] = {}

    def __enter__(self) -> "_Env":
        for k, v in self.patches.items():
            self.old[k] = os.environ.get(k)
            os.environ[k] = v
        return self

    def __exit__(self, *exc) -> None:
        for k, prev in self.old.items():
            if prev is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = prev


class TestDryRunNoSideEffects(unittest.TestCase):
    def _run_dry(self, module, target: str) -> dict:
        args = argparse.Namespace(
            target=target, client_id="opsctl-test",
            confirm="", dry_run=True, json=True,
        )
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = module.run(args, bus=None)
        self.assertEqual(rc, int(ExitCode.OK))
        out = json.loads(buf.getvalue().strip().splitlines()[-1])
        return out

    def test_denylist_clear_dry_run(self) -> None:
        with TemporaryDirectory() as tmp, _Env(tmp):
            out = self._run_dry(denylist_clear, "203.0.113.0/24")
            self.assertEqual(out["op"], "denylist-clear")
            self.assertEqual(out["expected_acks"], ["sec.rate.v1"])
            self.assertIn("expected_confirm_token", out)
            cfg = Config()
            self.assertFalse(Path(cfg.opsctl_audit_path_resolved).exists())
            # Lock dir may not exist (we never acquired); if it does
            # exist (e.g. created by a prior test in the same proc),
            # it must have no leftover lockfiles for our (kind,target).
            lock_dir = Path(cfg.opsctl_lock_dir_resolved)
            if lock_dir.exists():
                self.assertEqual(list(lock_dir.glob("*.lock")), [])

    def test_baseline_reset_dry_run_routes_to_sec_scrape(self) -> None:
        with TemporaryDirectory() as tmp, _Env(tmp):
            out = self._run_dry(baseline_reset, "mackolik")
            self.assertEqual(out["op"], "baseline-reset")
            self.assertEqual(out["expected_acks"], ["sec.scrape.v1"])

    def test_quarantine_erase_dry_run_destructive_still_runs(self) -> None:
        # Dry-run is the safe-validation path: it must succeed even
        # without --confirm so an operator can preview the envelope
        # before paying the destructive-token tax.
        with TemporaryDirectory() as tmp, _Env(tmp):
            out = self._run_dry(quarantine_erase, "sample-1")
            self.assertEqual(out["op"], "quarantine-erase")
            self.assertEqual(out["expected_acks"], ["maint.backup.v1"])
            cfg = Config()
            self.assertFalse(Path(cfg.opsctl_audit_path_resolved).exists())

    def test_quarantine_clear_dry_run_routes_to_maint_sec(self) -> None:
        with TemporaryDirectory() as tmp, _Env(tmp):
            out = self._run_dry(quarantine_clear, "sample-2")
            self.assertEqual(out["op"], "quarantine-clear")
            # §8.7 consumer landed: maint.sec.v1 owns the FP loop.
            self.assertEqual(out["expected_acks"], ["maint.sec.v1"])

    def test_spool_flush_dry_run_lists_entries(self) -> None:
        with TemporaryDirectory() as tmp, _Env(tmp):
            args = argparse.Namespace(json=True, dry_run=True, max_entries=0)
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = spool_flush.run(args, bus=None)
            self.assertEqual(rc, int(ExitCode.OK))
            out = json.loads(buf.getvalue().strip().splitlines()[-1])
            self.assertEqual(out["op"], "spool-flush")
            self.assertEqual(out["count"], 0)


if __name__ == "__main__":
    unittest.main()
