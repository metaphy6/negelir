#!/usr/bin/env python3
"""`make ops.*` — Phase 8 §8.1 ops console dispatcher.

Thin wrapper that shells out to ``python3 -m xops.opsctl <subcommand>``
so the Makefile stays one-line per target. Operator-supplied args
flow through the standard Make convention:

    make ops.denylist-clear TARGET=203.0.113.0/24

Adding a new subcommand is two edits: register a new ``cmd_*``
here AND add the ``ops.<name>`` Make target. The opsctl CLI itself
is the source of truth for argument shape.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import List

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from xops.makefile._common import dispatch, err  # noqa: E402

PYTHON = sys.executable or "python3"


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _run_opsctl(args: List[str]) -> int:
    """Invoke ``python -m xops.opsctl`` with the given argv tail."""
    cmd = [PYTHON, "-m", "xops.opsctl", *args]
    proc = subprocess.run(cmd, cwd=str(REPO_ROOT), check=False)
    return proc.returncode


def cmd_liveness(_argv: List[str]) -> int:
    """`make ops.liveness` — read-only smoke check (no bus publish)."""
    extra: List[str] = []
    if _env("JSON", "0") == "1":
        extra.append("--json")
    return _run_opsctl(["liveness", *extra])


def cmd_denylist_clear(_argv: List[str]) -> int:
    """`make ops.denylist-clear TARGET=<subject> [CLIENT_ID=<id>]`."""
    target = _env("TARGET")
    if not target:
        err("ops.denylist-clear: TARGET=<subject> is required")
        return 64
    args = ["denylist-clear", "--target", target]
    cid = _env("CLIENT_ID")
    if cid:
        args.extend(["--client-id", cid])
    if _env("DRY_RUN", "0") == "1":
        args.append("--dry-run")
    if _env("JSON", "0") == "1":
        args.append("--json")
    return _run_opsctl(args)


def cmd_quarantine_erase(_argv: List[str]) -> int:
    """`make ops.quarantine-erase TARGET=<sample_id> CONFIRM=<token>`."""
    target = _env("TARGET")
    if not target:
        err("ops.quarantine-erase: TARGET=<sample_id> is required")
        return 64
    args = ["quarantine-erase", "--target", target]
    confirm = _env("CONFIRM")
    if confirm:
        args.extend(["--confirm", confirm])
    cid = _env("CLIENT_ID")
    if cid:
        args.extend(["--client-id", cid])
    if _env("DRY_RUN", "0") == "1":
        args.append("--dry-run")
    if _env("JSON", "0") == "1":
        args.append("--json")
    return _run_opsctl(args)


def cmd_baseline_reset(_argv: List[str]) -> int:
    """`make ops.baseline-reset TARGET=<source_id>`."""
    target = _env("TARGET")
    if not target:
        err("ops.baseline-reset: TARGET=<source_id> is required")
        return 64
    args = ["baseline-reset", "--target", target]
    cid = _env("CLIENT_ID")
    if cid:
        args.extend(["--client-id", cid])
    if _env("DRY_RUN", "0") == "1":
        args.append("--dry-run")
    if _env("JSON", "0") == "1":
        args.append("--json")
    return _run_opsctl(args)


def cmd_quarantine_clear(_argv: List[str]) -> int:
    """`make ops.quarantine-clear TARGET=<sample_id>` (§8.7 consumer pending)."""
    target = _env("TARGET")
    if not target:
        err("ops.quarantine-clear: TARGET=<sample_id> is required")
        return 64
    args = ["quarantine-clear", "--target", target]
    cid = _env("CLIENT_ID")
    if cid:
        args.extend(["--client-id", cid])
    if _env("DRY_RUN", "0") == "1":
        args.append("--dry-run")
    if _env("JSON", "0") == "1":
        args.append("--json")
    return _run_opsctl(args)


def cmd_spool_flush(_argv: List[str]) -> int:
    """`make ops.spool-flush [MAX_ENTRIES=<n>]` — drain the bus-down spool."""
    args = ["spool-flush"]
    n = _env("MAX_ENTRIES")
    if n:
        args.extend(["--max-entries", n])
    if _env("DRY_RUN", "0") == "1":
        args.append("--dry-run")
    if _env("JSON", "0") == "1":
        args.append("--json")
    return _run_opsctl(args)


def _append_common_flags(args: List[str]) -> None:
    cid = _env("CLIENT_ID")
    if cid:
        args.extend(["--client-id", cid])
    confirm = _env("CONFIRM")
    if confirm:
        args.extend(["--confirm", confirm])
    reason = _env("REASON")
    if reason:
        args.extend(["--reason", reason])
    if _env("DRY_RUN", "0") == "1":
        args.append("--dry-run")
    if _env("JSON", "0") == "1":
        args.append("--json")


def cmd_maint_pause(_argv: List[str]) -> int:
    """`make ops.maint-pause TARGET=<agent|all> [TTL_S=<s>]` — §8.10."""
    target = _env("TARGET")
    if not target:
        err("ops.maint-pause: TARGET=<agent|all> is required")
        return 64
    args = ["maint-pause", "--target", target]
    ttl = _env("TTL_S")
    if ttl:
        args.extend(["--ttl-s", ttl])
    _append_common_flags(args)
    return _run_opsctl(args)


def cmd_maint_resume(_argv: List[str]) -> int:
    """`make ops.maint-resume TARGET=<agent|all>` — §8.10."""
    target = _env("TARGET")
    if not target:
        err("ops.maint-resume: TARGET=<agent|all> is required")
        return 64
    args = ["maint-resume", "--target", target]
    _append_common_flags(args)
    return _run_opsctl(args)


def cmd_scale(_argv: List[str]) -> int:
    """`make ops.scale TARGET=<agent> REPLICAS=<n> [TTL_S=<s>] [CURRENT=<n>]`."""
    target = _env("TARGET")
    replicas = _env("REPLICAS")
    if not target or not replicas:
        err("ops.scale: TARGET=<agent> and REPLICAS=<n> are required")
        return 64
    args = ["scale", "--target", target, "--replicas", replicas]
    ttl = _env("TTL_S")
    if ttl:
        args.extend(["--ttl-s", ttl])
    current = _env("CURRENT")
    if current:
        args.extend(["--current", current])
    _append_common_flags(args)
    return _run_opsctl(args)


def cmd_dlq_replay(_argv: List[str]) -> int:
    """`make ops.dlq-replay TARGET=<topic.dlq> [MAX_MSGS=<n>] [DROP=1] [CONFIRM_PII=1]`."""
    target = _env("TARGET")
    if not target:
        err("ops.dlq-replay: TARGET=<topic.dlq> is required")
        return 64
    args = ["dlq-replay", "--target", target]
    n = _env("MAX_MSGS")
    if n:
        args.extend(["--max-msgs", n])
    if _env("DROP", "0") == "1":
        args.append("--drop")
    if _env("CONFIRM_PII", "0") == "1":
        args.append("--confirm-pii")
    _append_common_flags(args)
    return _run_opsctl(args)


def cmd_dlq_unfreeze(_argv: List[str]) -> int:
    """`make ops.dlq-unfreeze TARGET=<topic.dlq>` — §8.5 C2."""
    target = _env("TARGET")
    if not target:
        err("ops.dlq-unfreeze: TARGET=<topic.dlq> is required")
        return 64
    args = ["dlq-unfreeze", "--target", target]
    _append_common_flags(args)
    return _run_opsctl(args)


def cmd_denylist_decimate_now(_argv: List[str]) -> int:
    """`make ops.denylist-decimate-now [TARGET=all]` — §8.8."""
    target = _env("TARGET", "all")
    args = ["denylist-decimate-now", "--target", target]
    _append_common_flags(args)
    return _run_opsctl(args)


def cmd_scale_pin(_argv: List[str]) -> int:
    """`make ops.scale-pin TARGET=<agent> REPLICAS=<n> [TTL_S=<s>]`."""
    target = _env("TARGET")
    replicas = _env("REPLICAS")
    if not target or not replicas:
        err("ops.scale-pin: TARGET=<agent> and REPLICAS=<n> are required")
        return 64
    args = ["scale-pin", "--target", target, "--replicas", replicas]
    ttl = _env("TTL_S")
    if ttl:
        args.extend(["--ttl-s", ttl])
    current = _env("CURRENT")
    if current:
        args.extend(["--current", current])
    _append_common_flags(args)
    return _run_opsctl(args)


def cmd_scale_unpin(_argv: List[str]) -> int:
    """`make ops.scale-unpin TARGET=<agent>` — cancel pin, resume autonomous."""
    target = _env("TARGET")
    if not target:
        err("ops.scale-unpin: TARGET=<agent> is required")
        return 64
    args = ["scale-unpin", "--target", target]
    _append_common_flags(args)
    return _run_opsctl(args)


def cmd_spool_show(_argv: List[str]) -> int:
    """`make ops.spool-show [LIMIT=<n>] [JSON=1]` — read-only spool listing."""
    args = ["spool-show"]
    limit = _env("LIMIT")
    if limit:
        args.extend(["--limit", limit])
    if _env("JSON", "0") == "1":
        args.append("--json")
    return _run_opsctl(args)


def cmd_spool_reconcile(_argv: List[str]) -> int:
    """`make ops.spool-reconcile [HORIZON_H=<h>] [JSON=1]` — §8.16.2."""
    import subprocess
    cmd = [sys.executable, "-m", "xops.opsctl.spool_reconciler"]
    h = _env("HORIZON_H")
    if h:
        cmd.extend(["--horizon-h", h])
    if _env("JSON", "0") == "1":
        cmd.append("--json")
    return subprocess.call(cmd)


def cmd_retrain_approve(_argv: List[str]) -> int:
    """`make ops.retrain-approve TARGET=<predictor> [DRIFT_REQUEST_ID=<uuid>] [NOTE=<text>]`."""
    target = _env("TARGET")
    if not target:
        err("ops.retrain-approve: TARGET=<predictor> is required")
        return 64
    args = ["retrain-approve", "--target", target]
    drift = _env("DRIFT_REQUEST_ID")
    if drift:
        args.extend(["--drift-request-id", drift])
    note = _env("NOTE")
    if note:
        args.extend(["--note", note])
    _append_common_flags(args)
    return _run_opsctl(args)


def cmd_backup_now(_argv: List[str]) -> int:
    """`make ops.backup-now TARGET=pg [SKIP_PRUNE=1] [REASON=<text>]`."""
    target = _env("TARGET", "pg")
    args = ["backup-now", "--target", target]
    if _env("SKIP_PRUNE", "0") == "1":
        args.append("--skip-prune")
    reason = _env("REASON")
    if reason:
        args.extend(["--reason", reason])
    _append_common_flags(args)
    return _run_opsctl(args)


def cmd_backup_rotate_key(_argv: List[str]) -> int:
    """`make ops.backup-rotate-key TARGET=<label> SCOPE=verify|dr [ADD_RECIPIENT=<age>] CONFIRM=<token>`."""
    target = _env("TARGET")
    scope = _env("SCOPE")
    if not target or not scope:
        err("ops.backup-rotate-key: TARGET=<label> and SCOPE=verify|dr are required")
        return 64
    args = ["backup-rotate-key", "--target", target, "--scope", scope]
    add_recipient = _env("ADD_RECIPIENT")
    if add_recipient:
        args.extend(["--add-recipient", add_recipient])
    reason = _env("REASON")
    if reason:
        args.extend(["--reason", reason])
    _append_common_flags(args)
    return _run_opsctl(args)


def cmd_restore(_argv: List[str]) -> int:
    """`make ops.restore TARGET=YYYY-MM-DD [FROM_OFFSITE=1] [DESTINATION_CONN=<dsn>] CONFIRM=<token>`."""
    target = _env("TARGET")
    if not target:
        err("ops.restore: TARGET=YYYY-MM-DD is required")
        return 64
    args = ["restore", "--target", target]
    if _env("FROM_OFFSITE", "0") == "1":
        args.append("--from-offsite")
    dest = _env("DESTINATION_CONN")
    if dest:
        args.extend(["--destination-conn", dest])
    reason = _env("REASON")
    if reason:
        args.extend(["--reason", reason])
    _append_common_flags(args)
    return _run_opsctl(args)


def cmd_allowlist_extend(_argv: List[str]) -> int:
    """`make ops.allowlist-extend TARGET=<source>:<rule> [TTL_S=<s>] [REASON=<text>]`."""
    target = _env("TARGET")
    if not target:
        err("ops.allowlist-extend: TARGET=<source>:<rule_id> is required")
        return 64
    args = ["allowlist-extend", "--target", target]
    ttl = _env("TTL_S")
    if ttl:
        args.extend(["--ttl-s", ttl])
    reason = _env("REASON")
    if reason:
        args.extend(["--reason", reason])
    _append_common_flags(args)
    return _run_opsctl(args)


def cmd_allowlist_approve(_argv: List[str]) -> int:
    """`make ops.allowlist-approve TARGET=<source>:<rule> [REASON=<text>]`."""
    target = _env("TARGET")
    if not target:
        err("ops.allowlist-approve: TARGET=<source>:<rule_id> is required")
        return 64
    args = ["allowlist-approve", "--target", target]
    reason = _env("REASON")
    if reason:
        args.extend(["--reason", reason])
    _append_common_flags(args)
    return _run_opsctl(args)


def cmd_allowlist_show(_argv: List[str]) -> int:
    """`make ops.allowlist-show TARGET=all|<source>|<source>:<rule> [INCLUDE_EXPIRED=1]`."""
    target = _env("TARGET", "all")
    args = ["allowlist-show", "--target", target]
    if _env("INCLUDE_EXPIRED", "0") == "1":
        args.append("--include-expired")
    _append_common_flags(args)
    return _run_opsctl(args)


COMMANDS = {
    "liveness": cmd_liveness,
    "denylist-clear": cmd_denylist_clear,
    "baseline-reset": cmd_baseline_reset,
    "quarantine-clear": cmd_quarantine_clear,
    "quarantine-erase": cmd_quarantine_erase,
    "spool-flush": cmd_spool_flush,
    "spool-show": cmd_spool_show,
    "spool-reconcile": cmd_spool_reconcile,
    "maint-pause": cmd_maint_pause,
    "maint-resume": cmd_maint_resume,
    "scale": cmd_scale,
    "scale-pin": cmd_scale_pin,
    "scale-unpin": cmd_scale_unpin,
    "dlq-replay": cmd_dlq_replay,
    "dlq-unfreeze": cmd_dlq_unfreeze,
    "denylist-decimate-now": cmd_denylist_decimate_now,
    "retrain-approve": cmd_retrain_approve,
    "backup-now": cmd_backup_now,
    "backup-rotate-key": cmd_backup_rotate_key,
    "restore": cmd_restore,
    "allowlist-extend": cmd_allowlist_extend,
    "allowlist-approve": cmd_allowlist_approve,
    "allowlist-show": cmd_allowlist_show,
}


if __name__ == "__main__":
    sys.exit(dispatch(sys.argv[1:], COMMANDS, "opsctl"))
