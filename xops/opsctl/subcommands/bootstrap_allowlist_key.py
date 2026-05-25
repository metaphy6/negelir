"""ops.bootstrap-allowlist-key - Phase 8 S8.16.10.

Generate the allowlist HMAC key file used by sec.input.v1 at
cfg.sec_input_allowlist_hmac_key_path. The key is 32 random bytes,
mode 0400, and created once (idempotent if the file exists).
"""
from __future__ import annotations

import argparse
import os
import secrets
import stat
import sys
from pathlib import Path
from typing import Optional

from .._exit_codes import ExitCode

NAME = "bootstrap-allowlist-key"
_KEY_LEN = 32


def add_parser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help="Generate allowlist HMAC key file (mode 0400).",
    )
    parser.set_defaults(func=run)
    return parser


def run(args: argparse.Namespace, *, bus: Optional[object] = None) -> int:
    from ai.common.config import Config  # noqa: PLC0415

    cfg = Config()
    key_path = Path(str(cfg.sec_input_allowlist_hmac_key_path)).expanduser()
    try:
        if key_path.exists():
            mode = stat.S_IMODE(key_path.stat().st_mode)
            sys.stdout.write(
                f"opsctl {NAME}: key already exists at {key_path} (mode={oct(mode)})\n"
            )
            return int(ExitCode.OK)

        key_path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        fd = os.open(
            str(key_path),
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o400,
        )
        try:
            os.write(fd, secrets.token_bytes(_KEY_LEN))
        finally:
            os.close(fd)

        sys.stdout.write(
            f"opsctl {NAME}: generated {key_path} (mode=0o400)\n"
        )
        return int(ExitCode.OK)
    except OSError as exc:
        sys.stderr.write(f"opsctl {NAME}: {exc}\n")
        return int(ExitCode.GENERIC_FAILURE)
