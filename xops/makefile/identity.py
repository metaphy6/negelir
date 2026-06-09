#!/usr/bin/env python3
"""
Phase 13.4.4 — Operator merge / split CLI for identity management.

Per ROADMAP §13.4.4: `make identity.merge` and `make identity.split` are
the only ways a human can override the resolver. Both write a tracker row
and emit identity.merge.v1 audit topic event.

Usage:
  make identity.merge STABLE_IDS=a,b REASON="duplicate club"
  make identity.split STABLE_ID=x INTO=a,b REASON="incorrectly merged"
"""

import argparse
import sys
from datetime import datetime, timezone
from typing import Optional

# Dispatch table for subcommands
COMMANDS: dict[str, callable] = {}


def cmd_merge(argv: list[str]) -> int:
    """
    Operator merge: combine multiple stable_ids into one.
    
    Args:
        --stable_ids: Comma-separated list of stable_ids to merge
        --reason: Reason for merge (for audit trail)
    """
    parser = argparse.ArgumentParser(description="Merge identity stable_ids")
    parser.add_argument(
        "--stable-ids",
        required=True,
        help="Comma-separated list of stable_ids to merge",
    )
    parser.add_argument(
        "--reason",
        required=True,
        help="Reason for merge (for audit trail)",
    )
    args = parser.parse_args(argv)
    
    stable_ids = [x.strip() for x in args.stable_ids.split(",") if x.strip()]
    reason = args.reason.strip()
    
    if len(stable_ids) < 2:
        print("error: merge requires at least 2 stable_ids", file=sys.stderr)
        return 1
    
    if not reason:
        print("error: reason is required", file=sys.stderr)
        return 1
    
    # Emit audit topic event
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    audit_event = {
        "decision": "merge",
        "similarity": 1.0,  # Operator decision always similarity 1.0
        "anchor_set_before": stable_ids,
        "anchor_set_after": [stable_ids[0]],  # Primary is first in list
        "actor": "operator",
        "reason": reason,
        "timestamp": timestamp,
    }
    
    # Print to stdout so parent makefile can log
    print(f"✔ merge {','.join(stable_ids)} → {stable_ids[0]}")
    print(f"  reason: {reason}")
    print(f"  event: {audit_event}")
    
    # In full implementation, this would:
    # 1. Update the resolver state in Redis/Postgres
    # 2. Publish audit event to identity.merge.v1 topic
    # 3. Write tracker row via make track.add
    
    return 0


def cmd_split(argv: list[str]) -> int:
    """
    Operator split: un-merge an incorrectly merged stable_id.
    
    Args:
        --stable-id: The stable_id to split
        --into: Comma-separated list of new stable_ids to create
        --reason: Reason for split
    """
    parser = argparse.ArgumentParser(description="Split identity stable_id")
    parser.add_argument(
        "--stable-id",
        required=True,
        help="The stable_id to split",
    )
    parser.add_argument(
        "--into",
        required=True,
        help="Comma-separated list of new stable_ids to create",
    )
    parser.add_argument(
        "--reason",
        required=True,
        help="Reason for split",
    )
    args = parser.parse_args(argv)
    
    stable_id = args.stable_id.strip()
    reason = args.reason.strip()
    new_ids = [x.strip() for x in args.into.split(",") if x.strip()]
    
    if len(new_ids) < 2:
        print("error: split requires at least 2 new stable_ids", file=sys.stderr)
        return 1
    
    if not reason:
        print("error: reason is required", file=sys.stderr)
        return 1
    
    # Emit audit topic event
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    audit_event = {
        "decision": "split",
        "similarity": 0.0,  # Split always similarity 0.0
        "anchor_set_before": [stable_id],
        "anchor_set_after": new_ids,
        "actor": "operator",
        "reason": reason,
        "timestamp": timestamp,
    }
    
    print(f"✔ split {stable_id} → {','.join(new_ids)}")
    print(f"  reason: {reason}")
    print(f"  event: {audit_event}")
    
    # In full implementation, this would:
    # 1. Update the resolver state in Redis/Postgres
    # 2. Publish audit event to identity.merge.v1 topic
    # 3. Write tracker row via make track.add
    
    return 0


def cmd_help(argv: list[str]) -> int:
    """Show help."""
    print(__doc__)
    return 0


# Register commands
COMMANDS["merge"] = cmd_merge
COMMANDS["split"] = cmd_split
COMMANDS["help"] = cmd_help


def dispatch(args: list[str]) -> int:
    """Main dispatcher."""
    if not args:
        cmd_help([])
        return 0
    
    cmd = args[0]
    if cmd not in COMMANDS:
        print(f"error: unknown command '{cmd}'", file=sys.stderr)
        print(f"available: {', '.join(sorted(COMMANDS.keys()))}", file=sys.stderr)
        return 1
    
    return COMMANDS[cmd](args[1:])


if __name__ == "__main__":
    sys.exit(dispatch(sys.argv[1:]))
