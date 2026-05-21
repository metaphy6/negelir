"""Phase 8 §8.1 — coverage for the seven new ops console subcommands
landed in the §8.1 close-out:

* ``ops.retrain-approve``     — non-destructive operator override
* ``ops.backup-now``          — non-destructive forced backup
* ``ops.backup-rotate-key``   — ALWAYS_DESTRUCTIVE
* ``ops.restore``             — ALWAYS_DESTRUCTIVE
* ``ops.allowlist-extend``    — non-destructive
* ``ops.allowlist-approve``   — non-destructive
* ``ops.allowlist-show``      — ALWAYS_SAFE (read-only)

Each subcommand is exercised through the standard ``run_publish``
flow at three points:

  1. dry-run: validates + prints envelope, no audit row, no publish
  2. local input validation: bad target / bad scope rejected with
     ``BAD_USAGE`` (64) BEFORE the runner tries to publish
  3. for destructive ones: missing ``--confirm`` is refused with
     ``BAD_USAGE`` even when the consumer set is empty
     (the token gate fires before the ``no_consumer_for_kind``
     gate — runbooks rely on this ordering)

Plus a boundary test enumerating the §8.1 doctrine destructive
set against :data:`xops.opsctl._classify.ALWAYS_DESTRUCTIVE` so a
future edit cannot silently demote ``restore`` /
``backup-rotate-key`` / ``quarantine-erase``.
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

from ai.swarm.sdk import InMemoryBus
from xops.opsctl._classify import ALWAYS_DESTRUCTIVE, ALWAYS_SAFE
from xops.opsctl._exit_codes import ExitCode
from xops.opsctl.subcommands import (
    allowlist_approve,
    allowlist_extend,
    allowlist_show,
    backup_now,
    backup_rotate_key,
    restore,
    retrain_approve,
)


class _Env:
    """Isolated audit / spool / lock dirs + short ack timeout."""

    def __init__(self, tmp: str) -> None:
        self.patches = {
            "NEGELIR_OPSCTL_AUDIT_PATH": str(Path(tmp) / "audit.csv"),
            "NEGELIR_OPSCTL_SPOOL_DIR": str(Path(tmp) / "spool"),
            "NEGELIR_OPSCTL_LOCK_DIR": str(Path(tmp) / "locks"),
            "NEGELIR_OPSCTL_ACK_TIMEOUT_MS": "200",
            "NEGELIR_OPSCTL_CRITICAL_AGENTS": "consensus.v1",
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


def _ns(**kw) -> argparse.Namespace:
    base = dict(
        client_id="opsctl-test",
        confirm="",
        dry_run=False,
        json=True,
    )
    base.update(kw)
    return argparse.Namespace(**base)


def _capture(module, args, *, bus=None) -> tuple[int, dict]:
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = module.run(args, bus=bus)
    text = buf.getvalue().strip()
    out: dict = {}
    if text:
        last = text.splitlines()[-1]
        try:
            out = json.loads(last)
        except json.JSONDecodeError:
            out = {"_raw": last}
    return rc, out


# ────────────────────────────────────────────────────────────────────
# retrain-approve
# ────────────────────────────────────────────────────────────────────


class TestRetrainApprove(unittest.TestCase):
    def test_dry_run_emits_envelope_and_drift_request_id(self) -> None:
        with TemporaryDirectory() as tmp, _Env(tmp):
            args = _ns(
                target="pred.elo.v1",
                drift_request_id="dr-123",
                note="approved 2026-05-05",
                dry_run=True,
            )
            rc, out = _capture(retrain_approve, args)
            self.assertEqual(rc, int(ExitCode.OK))
            self.assertEqual(out["op"], "retrain-approve")
            self.assertEqual(out["payload"]["details"]["drift_request_id"], "dr-123")
            self.assertEqual(out["payload"]["details"]["note"], "approved 2026-05-05")

    def test_dry_run_without_details_omits_field(self) -> None:
        with TemporaryDirectory() as tmp, _Env(tmp):
            args = _ns(
                target="pred.poisson.v1",
                drift_request_id="",
                note="",
                dry_run=True,
            )
            rc, out = _capture(retrain_approve, args)
            self.assertEqual(rc, int(ExitCode.OK))
            self.assertNotIn("details", out["payload"])


# ────────────────────────────────────────────────────────────────────
# backup-now
# ────────────────────────────────────────────────────────────────────


class TestBackupNow(unittest.TestCase):
    def test_dry_run_skip_prune_payload(self) -> None:
        with TemporaryDirectory() as tmp, _Env(tmp):
            args = _ns(
                target="pg",
                skip_prune=True,
                reason="pre-deploy",
                dry_run=True,
            )
            rc, out = _capture(backup_now, args)
            self.assertEqual(rc, int(ExitCode.OK))
            self.assertTrue(out["payload"]["skip_prune"])
            self.assertEqual(out["payload"]["reason"], "pre-deploy")

    def test_unknown_target_rejected_before_publish(self) -> None:
        with TemporaryDirectory() as tmp, _Env(tmp):
            args = _ns(target="redis", skip_prune=False, reason="", dry_run=False)
            rc, _ = _capture(backup_now, args)
            self.assertEqual(rc, 64)


# ────────────────────────────────────────────────────────────────────
# backup-rotate-key (DESTRUCTIVE)
# ────────────────────────────────────────────────────────────────────


class TestBackupRotateKey(unittest.TestCase):
    def test_dry_run_does_not_require_confirm(self) -> None:
        # Per §8.1 doctrine the token gate fires only at the real
        # publish path; dry-run is the safe-preview lane.
        with TemporaryDirectory() as tmp, _Env(tmp):
            args = _ns(
                target="dr-key-rev-7",
                scope="dr",
                add_recipient="age1abc",
                reason="scheduled rotation",
                dry_run=True,
            )
            rc, out = _capture(backup_rotate_key, args)
            self.assertEqual(rc, int(ExitCode.OK))
            self.assertEqual(out["payload"]["scope"], "dr")
            self.assertEqual(out["payload"]["add_recipient"], "age1abc")

    def test_real_publish_without_confirm_refused(self) -> None:
        with TemporaryDirectory() as tmp, _Env(tmp):
            args = _ns(
                target="verify-2026-Q3",
                scope="verify",
                add_recipient="",
                reason="",
                dry_run=False,
                confirm="",
            )
            rc, out = _capture(backup_rotate_key, args)
            self.assertEqual(rc, int(ExitCode.BAD_USAGE))
            self.assertEqual(out["action"], "refuse")
            self.assertIn("destructive", out["note"])

    def test_add_recipient_rejected_when_scope_verify(self) -> None:
        with TemporaryDirectory() as tmp, _Env(tmp):
            args = _ns(
                target="verify-2026",
                scope="verify",
                add_recipient="age1xyz",
                reason="",
                dry_run=False,
            )
            rc, _ = _capture(backup_rotate_key, args)
            self.assertEqual(rc, 64)


# ────────────────────────────────────────────────────────────────────
# restore (DESTRUCTIVE)
# ────────────────────────────────────────────────────────────────────


class TestRestore(unittest.TestCase):
    def test_bad_date_target_rejected_before_publish(self) -> None:
        with TemporaryDirectory() as tmp, _Env(tmp):
            args = _ns(
                target="yesterday",
                from_offsite=False,
                destination_conn="",
                reason="",
                dry_run=False,
            )
            rc, _ = _capture(restore, args)
            self.assertEqual(rc, 64)

    def test_real_publish_without_confirm_refused(self) -> None:
        with TemporaryDirectory() as tmp, _Env(tmp):
            args = _ns(
                target="2025-01-01",
                from_offsite=False,
                destination_conn="",
                reason="",
                dry_run=False,
                confirm="",
            )
            rc, out = _capture(restore, args)
            self.assertEqual(rc, int(ExitCode.BAD_USAGE))
            self.assertEqual(out["action"], "refuse")

    def test_dry_run_dr_drill_payload(self) -> None:
        with TemporaryDirectory() as tmp, _Env(tmp):
            args = _ns(
                target="2025-06-15",
                from_offsite=True,
                destination_conn="postgresql://drill@host/db",
                reason="DR drill",
                dry_run=True,
            )
            rc, out = _capture(restore, args)
            self.assertEqual(rc, int(ExitCode.OK))
            self.assertTrue(out["payload"]["from_offsite"])
            self.assertEqual(
                out["payload"]["destination_conn"],
                "postgresql://drill@host/db",
            )

    def test_dry_run_confirm_overwrite_live_in_payload(self) -> None:
        """ROADMAP §8.3 — `--confirm-overwrite-live` flows through the
        envelope payload AND is folded into the typed-token preimage so
        an operator cannot drop the flag and reuse a prior token."""
        with TemporaryDirectory() as tmp, _Env(tmp):
            args = _ns(
                target="2025-06-15",
                from_offsite=False,
                destination_conn="postgresql://app@live/negelir",
                confirm_overwrite_live=True,
                reason="emergency cutover",
                dry_run=True,
            )
            rc, out = _capture(restore, args)
            self.assertEqual(rc, int(ExitCode.OK))
            self.assertTrue(out["payload"]["confirm_overwrite_live"])
            # Token preimage changes when confirm_overwrite_live is set.
            token_with = out["expected_confirm_token"]
            args_no = _ns(
                target="2025-06-15",
                from_offsite=False,
                destination_conn="postgresql://app@live/negelir",
                confirm_overwrite_live=False,
                reason="emergency cutover",
                dry_run=True,
            )
            _, out_no = _capture(restore, args_no)
            token_without = out_no["expected_confirm_token"]
            self.assertNotEqual(token_with, token_without)


# ────────────────────────────────────────────────────────────────────
# allowlist-extend / -approve / -show
# ────────────────────────────────────────────────────────────────────


class TestAllowlistExtend(unittest.TestCase):
    def test_bad_target_rejected(self) -> None:
        with TemporaryDirectory() as tmp, _Env(tmp):
            args = _ns(target="not-a-tuple", ttl_s=0, reason="", dry_run=False)
            rc, _ = _capture(allowlist_extend, args)
            self.assertEqual(rc, 64)

    def test_ttl_outside_range_rejected(self) -> None:
        with TemporaryDirectory() as tmp, _Env(tmp):
            args = _ns(
                target="mackolik:rule_42",
                ttl_s=10_000_000,  # >90d
                reason="",
                dry_run=False,
            )
            rc, _ = _capture(allowlist_extend, args)
            self.assertEqual(rc, 64)

    def test_dry_run_payload(self) -> None:
        with TemporaryDirectory() as tmp, _Env(tmp):
            args = _ns(
                target="mackolik:rule_42",
                ttl_s=86400,
                reason="legit redesign",
                dry_run=True,
            )
            rc, out = _capture(allowlist_extend, args)
            self.assertEqual(rc, int(ExitCode.OK))
            self.assertEqual(out["payload"]["ttl_s"], 86400)


class TestAllowlistApprove(unittest.TestCase):
    def test_bad_target_rejected(self) -> None:
        with TemporaryDirectory() as tmp, _Env(tmp):
            args = _ns(target="bad target", reason="", dry_run=False)
            rc, _ = _capture(allowlist_approve, args)
            self.assertEqual(rc, 64)

    def test_dry_run_payload(self) -> None:
        with TemporaryDirectory() as tmp, _Env(tmp):
            args = _ns(
                target="nesine:rule_7",
                reason="manual review ok",
                dry_run=True,
            )
            rc, out = _capture(allowlist_approve, args)
            self.assertEqual(rc, int(ExitCode.OK))
            self.assertEqual(out["payload"]["target"], "nesine:rule_7")


class TestAllowlistShow(unittest.TestCase):
    def test_target_all_dry_run(self) -> None:
        with TemporaryDirectory() as tmp, _Env(tmp):
            args = _ns(target="all", include_expired=False, dry_run=True)
            rc, out = _capture(allowlist_show, args)
            self.assertEqual(rc, int(ExitCode.OK))
            self.assertEqual(out["payload"]["kind"], "allowlist_show")

    def test_include_expired_round_trips(self) -> None:
        with TemporaryDirectory() as tmp, _Env(tmp):
            args = _ns(
                target="mackolik",
                include_expired=True,
                dry_run=True,
            )
            rc, out = _capture(allowlist_show, args)
            self.assertEqual(rc, int(ExitCode.OK))
            self.assertTrue(out["payload"]["include_expired"])

    def test_bad_target_rejected(self) -> None:
        with TemporaryDirectory() as tmp, _Env(tmp):
            args = _ns(target="has spaces", include_expired=False, dry_run=False)
            rc, _ = _capture(allowlist_show, args)
            self.assertEqual(rc, 64)

    def test_live_run_exits_no_consumer_bus_empty(self) -> None:
        # §8.9 second-pass proof: ops.allowlist-show is ALWAYS_SAFE (no token
        # required) but its kind has no registered consumer yet.  The runner
        # must exit 5 (no_consumer_for_kind) BEFORE calling bus.publish — the
        # envelope must never appear on maint.event.v1.
        with TemporaryDirectory() as tmp, _Env(tmp):
            bus = InMemoryBus()
            args = _ns(target="all", include_expired=False, dry_run=False)
            rc, _ = _capture(allowlist_show, args, bus=bus)
            self.assertEqual(
                rc,
                int(ExitCode.NO_CONSUMER_FOR_KIND),
                msg="expected exit 5 (no_consumer_for_kind)",
            )
            self.assertEqual(
                bus.length("maint.event.v1"),
                0,
                msg="envelope must not be published to maint.event.v1 before ack set resolved",
            )


# ────────────────────────────────────────────────────────────────────
# Destructive-set boundary
# ────────────────────────────────────────────────────────────────────


class TestDestructiveSetBoundary(unittest.TestCase):
    """Per ROADMAP §8.1 doctrine, the destructive set is:

      ALWAYS_DESTRUCTIVE   = {quarantine-erase, restore, backup-rotate-key}
      flag-driven CONFIRM  = scale --replicas 0,
                             scale >50% reduction,
                             dlq-replay --drop,
                             dlq-replay --topic sec.* --confirm-pii
      critical-agent gate  = any subcommand whose --target is in
                             cfg.opsctl_critical_agents

    A future edit that demotes any of these without an explicit
    doctrine change must fail this test.
    """

    DOCTRINE_ALWAYS_DESTRUCTIVE = frozenset({
        "quarantine-erase",
        "restore",
        "backup-rotate-key",
    })

    DOCTRINE_ALWAYS_SAFE = frozenset({
        "liveness",
        "spool-show",
        "allowlist-show",
        "scale-unpin",
    })

    def test_always_destructive_matches_doctrine(self) -> None:
        # No silent additions: every classifier-destructive name
        # must be one the doctrine block explicitly names.
        # No silent removals: every doctrine name must be in the
        # classifier set.
        self.assertEqual(
            ALWAYS_DESTRUCTIVE,
            self.DOCTRINE_ALWAYS_DESTRUCTIVE,
            (
                "ALWAYS_DESTRUCTIVE drifted from ROADMAP §8.1 doctrine; "
                "any addition / removal needs an explicit doctrine bump "
                "and a tracker row before this test is updated."
            ),
        )

    def test_always_safe_matches_doctrine(self) -> None:
        self.assertEqual(
            ALWAYS_SAFE,
            self.DOCTRINE_ALWAYS_SAFE,
            (
                "ALWAYS_SAFE drifted from ROADMAP §8.1 doctrine; "
                "the operator runbook trusts this set."
            ),
        )


if __name__ == "__main__":
    unittest.main()
