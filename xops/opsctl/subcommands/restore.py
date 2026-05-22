"""``ops.restore`` — Phase 8 §8.1 / §8.3 / §8.12 / §8.14.3.

Operator-driven restore from a stored backup. ALWAYS_DESTRUCTIVE
(see :data:`xops.opsctl._classify.ALWAYS_DESTRUCTIVE`): the
operator must pass the typed ``--confirm`` token so a stray
invocation cannot rewind production by accident.

`target` is the dump date in ``YYYY-MM-DD`` form — the consumer
(``maint.backup.v1``) resolves it to the on-disk artefact (or
pulls from the off-host replica when ``--from-offsite`` is set,
per §8.12).

Default behaviour (per ROADMAP §8.3 binding) is to restore into
an ephemeral target named ``negelir_restore_<dump_date>`` that
the operator then promotes manually — the live primary is NEVER
overwritten unless the operator passes BOTH ``--destination-conn``
pointing at it AND ``--confirm-overwrite-live``. The consumer
refuses with surface code ``live_overwrite_requires_confirm`` if
the second flag is missing.

§8.14.3 binding: at startup this subcommand checks that the
operator's local ``age`` binary matches
``cfg.maint_backup_age_binary_version``.  Mismatch →
``fail_safe_age_version_mismatch_local`` error + exit 1.
Mock profile (``cfg.profile == "mock"``) relaxes the assertion to
a ``severity=warn`` log line.
"""
from __future__ import annotations

import argparse
import logging
import re
import subprocess
import sys
from typing import Any, Optional

from .._runner import SubcommandSpec, add_common_publish_args, run_publish

NAME = "restore"
KIND = "restore"

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_log = logging.getLogger("xops.opsctl.restore")

_AGE_VERSION_RUNBOOK = (
    "https://github.com/FiloSottile/age/releases — "
    "install the version matching cfg.maint_backup_age_binary_version "
    "(default 1.2.0) and ensure it is on your PATH"
)


def _check_local_age_version() -> int:
    """Enforce §8.14.3 restore-side parity.

    Reads ``cfg.maint_backup_age_binary_version``, calls
    ``age --version``, and:

    * On mock profile: logs ``severity=warn`` and returns 0.
    * On any other profile with a version mismatch: prints
      ``fail_safe_age_version_mismatch_local`` to stderr and returns 1.
    * When ``age`` is not found on PATH: prints
      ``age_binary_not_found`` + runbook link and returns 1.
    """
    from common.config import cfg as _cfg  # pylint: disable=import-outside-toplevel

    expected = str(_cfg.maint_backup_age_binary_version)
    is_mock = str(_cfg.profile) == "mock"

    installed: str | None = None
    try:
        result = subprocess.run(  # noqa: S603
            ["age", "--version"],
            check=True,
            capture_output=True,
            text=True,
        )
        # age --version prints e.g. "age v1.2.0" or "1.2.0" on stdout/stderr.
        raw = (result.stdout or result.stderr or "").strip()
        # Extract bare semver from the output (strip leading "v", "age ", etc.)
        parts = raw.split()
        for part in parts:
            stripped = part.lstrip("v")
            if stripped and stripped[0].isdigit():
                installed = stripped
                break
        if installed is None:
            installed = raw
    except FileNotFoundError:
        if is_mock:
            _log.warning(
                "ops.restore: age binary not found (mock profile — warn only); "
                "install age to match cfg.maint_backup_age_binary_version=%r. "
                "Runbook: %s",
                expected,
                _AGE_VERSION_RUNBOOK,
            )
            return 0
        sys.stderr.write(
            f"ops.restore: age_binary_not_found — "
            f"the `age` binary is not on PATH.\n"
            f"Install the canonical version ({expected!r}) before restoring.\n"
            f"Runbook: {_AGE_VERSION_RUNBOOK}\n"
        )
        return 1
    except subprocess.CalledProcessError as exc:
        sys.stderr.write(
            f"ops.restore: age_binary_not_found — "
            f"`age --version` exited {exc.returncode}.\n"
            f"Runbook: {_AGE_VERSION_RUNBOOK}\n"
        )
        return 1

    if installed != expected:
        if is_mock:
            _log.warning(
                "ops.restore: fail_safe_age_version_mismatch_local "
                "(mock profile — warn only); installed=%r expected=%r. "
                "Runbook: %s",
                installed,
                expected,
                _AGE_VERSION_RUNBOOK,
            )
            return 0
        sys.stderr.write(
            f"ops.restore: fail_safe_age_version_mismatch_local — "
            f"installed age version {installed!r} != "
            f"cfg.maint_backup_age_binary_version={expected!r}.\n"
            f"Install the canonical version before restoring.\n"
            f"Runbook: {_AGE_VERSION_RUNBOOK}\n"
        )
        return 1

    return 0


def add_parser(
    subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]",
) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help="Restore PG from a stored backup (DESTRUCTIVE — replaces live data).",
        description=(
            "Publishes maint.event.v1{kind=restore}. Destructive — "
            "passes through ALWAYS_DESTRUCTIVE token gate. "
            "Pass --destination-conn for non-destructive DR drills "
            "into a fresh PG instance (still requires --confirm)."
        ),
    )
    add_common_publish_args(
        parser,
        target_help="Dump date in YYYY-MM-DD form.",
    )
    parser.add_argument(
        "--from-offsite",
        action="store_true",
        help="Pull dump from the off-host replica (§8.12) instead of on-host PVC.",
    )
    parser.add_argument(
        "--destination-conn",
        default="",
        help=(
            "Override DSN — restore into a specific Postgres instance "
            "instead of the default ephemeral target "
            "`negelir_restore_<dump_date>` (per §8.3 binding). When "
            "this DSN matches the live primary, --confirm-overwrite-live "
            "is also required."
        ),
    )
    parser.add_argument(
        "--confirm-overwrite-live",
        action="store_true",
        help=(
            "Operator opt-in to overwrite the live application Postgres "
            "(when --destination-conn resolves to the live DSN). Without "
            "this flag the consumer refuses with surface code "
            "`live_overwrite_requires_confirm`."
        ),
    )
    parser.add_argument(
        "--reason",
        default="",
        help="Operator narration for the audit trail.",
    )
    parser.set_defaults(func=run)
    return parser


def run(args: argparse.Namespace, *, bus: Optional[Any] = None) -> int:
    # §8.14.3 restore-side parity: enforce local age version before
    # publishing the restore event so an operator with the wrong binary
    # cannot even enqueue the request.
    age_rc = _check_local_age_version()
    if age_rc != 0:
        return age_rc

    target = str(args.target)
    if not _DATE_RE.match(target):
        import sys
        sys.stderr.write(
            f"opsctl {NAME}: --target must be YYYY-MM-DD; got {target!r}\n"
        )
        return 64

    from_offsite = bool(getattr(args, "from_offsite", False))
    destination_conn = str(getattr(args, "destination_conn", "") or "")
    confirm_overwrite_live = bool(
        getattr(args, "confirm_overwrite_live", False)
    )
    reason = str(getattr(args, "reason", "") or "")

    extra_payload: dict[str, Any] = {}
    if from_offsite:
        extra_payload["from_offsite"] = True
    if destination_conn:
        extra_payload["destination_conn"] = destination_conn
    if confirm_overwrite_live:
        extra_payload["confirm_overwrite_live"] = True
    if reason:
        extra_payload["reason"] = reason

    salient: dict[str, Any] = {}
    if from_offsite:
        salient["from_offsite"] = True
    if destination_conn:
        # Folded into the typed-token preimage so the operator
        # cannot accidentally promote a DR-drill confirmation
        # into a production restore by dropping the flag.
        salient["destination_conn"] = destination_conn
    if confirm_overwrite_live:
        # Same rationale: a live-overwrite confirmation must NOT be
        # reusable against a different destination after dropping the
        # flag from the next invocation.
        salient["confirm_overwrite_live"] = True

    spec = SubcommandSpec(
        name=NAME,
        kind=KIND,
        target=target,
        client_id=str(args.client_id),
        salient_args=salient,
        extra_payload=extra_payload,
        json_output=bool(getattr(args, "json", False)),
        dry_run=bool(getattr(args, "dry_run", False)),
        confirm=str(getattr(args, "confirm", "") or ""),
    )
    return run_publish(spec, bus=bus)


__all__ = ["KIND", "NAME", "add_parser", "run"]
