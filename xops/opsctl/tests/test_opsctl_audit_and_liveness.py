"""Phase 8 §8.1 — audit CSV + liveness subcommand smoke tests."""
from __future__ import annotations

import argparse
import csv
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from common.config import Config

from xops.opsctl._audit import AUDIT_HEADER, append_audit_row, make_row
from xops.opsctl._exit_codes import ExitCode
from xops.opsctl.subcommands import liveness


class TestAuditCSV(unittest.TestCase):
    def test_creates_file_with_header_then_appends(self) -> None:
        with TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "nested" / "audit.csv")
            row1 = make_row(
                op="liveness",
                target="-",
                request_id="-",
                exit_code=int(ExitCode.OK),
                expected_acks=0,
                received_acks=0,
                note="first",
            )
            row2 = make_row(
                op="denylist-clear",
                target="203.0.113.0/24",
                request_id="abc",
                exit_code=int(ExitCode.HARD_TIMEOUT),
                expected_acks=1,
                received_acks=0,
                note="second",
            )
            append_audit_row(path, row1)
            append_audit_row(path, row2)

            with open(path, newline="", encoding="utf-8") as fh:
                rows = list(csv.reader(fh))
            self.assertEqual(tuple(rows[0]), AUDIT_HEADER)
            self.assertEqual(rows[1][2], "liveness")
            self.assertEqual(rows[2][2], "denylist-clear")
            mode = os.stat(path).st_mode & 0o777
            self.assertEqual(mode, 0o600)


class TestLivenessSubcommand(unittest.TestCase):
    def test_run_returns_ok_and_writes_audit(self) -> None:
        with TemporaryDirectory() as tmp:
            os.environ["NEGELIR_OPSCTL_AUDIT_PATH"] = str(Path(tmp) / "audit.csv")
            os.environ["NEGELIR_OPSCTL_SPOOL_DIR"] = str(Path(tmp) / "spool")
            try:
                args = argparse.Namespace(json=True)
                rc = liveness.run(args)
                self.assertEqual(rc, int(ExitCode.OK))
                cfg = Config()
                self.assertTrue(Path(cfg.opsctl_audit_path_resolved).exists())
                self.assertTrue(Path(cfg.opsctl_spool_dir_resolved).exists())
            finally:
                os.environ.pop("NEGELIR_OPSCTL_AUDIT_PATH", None)
                os.environ.pop("NEGELIR_OPSCTL_SPOOL_DIR", None)


if __name__ == "__main__":
    unittest.main()
