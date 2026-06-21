"""``ops.liveness`` — Phase 8 §8.10 read-only smoke check.

Confirms the operator's environment can:

  * import :mod:`ai.common.config` and resolve a Config snapshot;
  * resolve the audit + spool paths (and create their parents);
  * read the kind→consumer map from
    :mod:`ai.swarm.agents.maint._ack_routing` (the binding wire
    authority for §8.1).

**Compose-mode heartbeat poll (§8.10):** when Redis is reachable, the
subcommand also reads the :class:`~ai.swarm.sdk.registry.AgentRegistry`
and checks every registered §8.x agent's last heartbeat timestamp.  An
agent is considered stale when ``now − last_heartbeat > 3 ×
cfg.swarm_heartbeat_sec`` (the ``DEAD_BEAT_MULTIPLIER = 3`` rule).  The
exit code is :attr:`ExitCode.LIVENESS_STALE` (75) when one or more stale
agents are found; :attr:`ExitCode.OK` otherwise.

When Redis is unreachable the heartbeat check is skipped and the
subcommand exits :attr:`ExitCode.OK` (env smoke-check still passes).
Pass ``--skip-bus`` to force-skip the bus poll regardless of Redis state.

Output is JSON when ``--json`` is set, plain text otherwise.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from common.config import Config
from swarm.agents.maint._ack_routing import (
    KINDS_PENDING_CONSUMER_LANDING,
    KNOWN_MAINT_EVENT_KINDS,
)
from swarm.sdk.registry import DEAD_BEAT_MULTIPLIER, poll_heartbeats_from_host

from .._audit import append_audit_row, make_row
from .._exit_codes import ExitCode

NAME = "liveness"

# Exit code used when ≥1 §8.x agent heartbeats are stale.
# Reuses ExitCode.LIVENESS_STALE if it exists, else uses 75.
_STALE_EXIT: int = getattr(ExitCode, "LIVENESS_STALE", 75)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _poll_registry_heartbeats(cfg: Config) -> dict[str, Any]:
    """Try to connect to Redis and return heartbeat status for all agents.

    Returns a dict with keys:
      * ``available``   — bool: Redis was reachable
      * ``agents``      — list of per-agent dicts (empty when unavailable)
      * ``stale_names`` — list of instance_ids that are stale
    """
    result: dict[str, Any] = {
        "available": False,
        "agents": [],
        "stale_names": [],
    }
    available, beats = poll_heartbeats_from_host(
        host=cfg.redis_host,
        port=cfg.redis_port,
        timeout=2.0,
    )
    if not available:
        return result

    result["available"] = True
    threshold_sec = int(cfg.swarm_heartbeat_sec) * DEAD_BEAT_MULTIPLIER
    now = _utc_now()

    for iid, ts_str in beats.items():
        stale = True
        age_s: float = -1.0
        try:
            last = datetime.fromisoformat(ts_str)
            age_s = (now - last).total_seconds()
            stale = age_s > threshold_sec
        except ValueError:
            pass

        entry = {
            "instance_id": iid,
            "last_heartbeat": ts_str,
            "age_s": round(age_s, 1),
            "stale": stale,
        }
        result["agents"].append(entry)
        if stale:
            result["stale_names"].append(iid)

    return result


def add_parser(subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]") -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help="Read-only smoke check (no bus publish).",
        description=(
            "Validate the operator environment (config, paths, maint kind "
            "routing) and — when Redis is reachable — poll each registered "
            "§8.x agent's heartbeat for staleness."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit a single JSON object on stdout (deterministic).",
    )
    parser.add_argument(
        "--skip-bus",
        action="store_true",
        help="Skip the Redis heartbeat poll even when Redis is reachable.",
    )
    parser.set_defaults(func=run)
    return parser


def run(args: argparse.Namespace, *, bus: Optional[Any] = None) -> int:
    del bus  # liveness does not publish
    cfg = Config()
    audit_path = cfg.opsctl_audit_path_resolved
    spool_dir = cfg.opsctl_spool_dir_resolved
    Path(audit_path).parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    Path(spool_dir).mkdir(parents=True, mode=0o700, exist_ok=True)

    # §8.10 compose-mode heartbeat poll.
    skip_bus = getattr(args, "skip_bus", False)
    hb: dict[str, Any] = (
        {"available": False, "agents": [], "stale_names": []}
        if skip_bus
        else _poll_registry_heartbeats(cfg)
    )

    stale = hb["stale_names"]
    overall_ok = len(stale) == 0

    summary: dict[str, Any] = {
        "ok": overall_ok,
        "audit_path": audit_path,
        "spool_dir": spool_dir,
        "ack_timeout_ms": cfg.opsctl_ack_timeout_ms,
        "spool_max_entries": cfg.opsctl_spool_max_entries,
        "critical_agents": sorted(cfg.opsctl_critical_agents_set),
        "known_kinds": sorted(KNOWN_MAINT_EVENT_KINDS),
        "pending_consumer_landings": dict(sorted(KINDS_PENDING_CONSUMER_LANDING.items())),
        "bus_available": hb["available"],
        "agents": hb["agents"],
        "stale_agents": stale,
    }

    json_out = getattr(args, "json", False)
    if json_out:
        sys.stdout.write(json.dumps(summary, sort_keys=True, ensure_ascii=False))
        sys.stdout.write("\n")
    else:
        status = "OK" if overall_ok else "STALE"
        bus_note = (
            f"  bus=offline"
            if not hb["available"]
            else f"  agents={len(hb['agents'])}  stale={len(stale)}"
        )
        sys.stdout.write(
            f"opsctl liveness {status}  audit={audit_path}  spool={spool_dir}"
            f"  kinds={len(KNOWN_MAINT_EVENT_KINDS)}{bus_note}\n"
        )
        if stale:
            for iid in stale:
                sys.stderr.write(f"  STALE agent: {iid}\n")

    append_audit_row(
        audit_path,
        make_row(
            op=NAME,
            target="-",
            request_id="-",
            exit_code=int(ExitCode.OK) if overall_ok else _STALE_EXIT,
            expected_acks=0,
            received_acks=0,
            note="liveness ok" if overall_ok else f"stale: {','.join(stale)}",
            host=os.uname().nodename,
        ),
    )
    return int(ExitCode.OK) if overall_ok else _STALE_EXIT


__all__ = ["NAME", "add_parser", "run"]
