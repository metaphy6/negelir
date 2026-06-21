"""Phase 8 §8.1 — wire-level cap helper tests for ``maint.ack.v1``.

Covers :func:`ai.swarm.sdk.maint_ack.build_capped_maint_ack` against
the doctrine in :mod:`ai.swarm.sdk.maint_ack`:

* Under-cap payloads round-trip with no notice.
* Over-cap details are dropped, ``reason`` rewritten to
  ``truncated:<N>``, notice signals the original size.
* An operator-supplied ``reason`` prefix is preserved across the
  truncation (forensic context not lost).
* The capped payload is guaranteed under
  ``cfg.maint_ack_payload_max_bytes`` — no second over-cap path.
* ``reason`` itself is independently capped at
  ``cfg.maint_ack_reason_max_bytes``; over-cap reason strings are
  clipped with an ``…`` ellipsis suffix (defends against a
  consumer dodging the details cap by stuffing the reason).
* The notice carries ``accepted_by`` so the caller's debounce key
  can fire one alert per chronically-oversize consumer.
"""
from __future__ import annotations

import json
import os
import unittest

from swarm.sdk.maint_ack import build_capped_maint_ack


class _Env:
    def __init__(self, **patches: str) -> None:
        self.patches = patches
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


def _payload_bytes(ack) -> int:
    return len(json.dumps(ack.as_dict(), sort_keys=True, ensure_ascii=False).encode("utf-8"))


class TestUnderCapRoundTrip(unittest.TestCase):
    def test_small_ack_no_notice(self) -> None:
        ack, notice = build_capped_maint_ack(
            request_id="req-1",
            accepted=True,
            accepted_by="maint.scaler.v1",
            processed_at="2025-01-01T00:00:00Z",
            details={"replicas": 3},
        )
        self.assertIsNone(notice)
        self.assertEqual(ack.details, {"replicas": 3})
        self.assertEqual(ack.reason, "")


class TestOversizeTruncation(unittest.TestCase):
    def test_oversize_details_dropped_and_notice_emitted(self) -> None:
        # Tight 256-byte cap so we can build a payload that overflows
        # without burning huge fixtures.
        with _Env(NEGELIR_MAINT_ACK_PAYLOAD_MAX_BYTES="256"):
            big_details = {"blob": "x" * 4096}
            ack, notice = build_capped_maint_ack(
                request_id="req-2",
                accepted=True,
                accepted_by="maint.dlq.v1",
                processed_at="2025-01-01T00:00:00Z",
                details=big_details,
            )
        self.assertIsNotNone(notice)
        assert notice is not None  # for type-checker
        self.assertIsNone(ack.details)
        self.assertTrue(ack.reason.startswith("truncated:"))
        self.assertEqual(notice.accepted_by, "maint.dlq.v1")
        self.assertEqual(notice.request_id, "req-2")
        self.assertGreater(notice.original_details_bytes, 256)

    def test_capped_payload_fits_within_cap(self) -> None:
        with _Env(NEGELIR_MAINT_ACK_PAYLOAD_MAX_BYTES="256"):
            ack, notice = build_capped_maint_ack(
                request_id="req-3",
                accepted=False,
                accepted_by="maint.sec.v1",
                processed_at="2025-01-01T00:00:00Z",
                reason="legit operator note",
                details={"blob": "y" * 8192},
            )
            self.assertIsNotNone(notice)
            self.assertLessEqual(_payload_bytes(ack), 256)

    def test_operator_reason_prefix_preserved(self) -> None:
        with _Env(NEGELIR_MAINT_ACK_PAYLOAD_MAX_BYTES="256"):
            ack, notice = build_capped_maint_ack(
                request_id="req-4",
                accepted=False,
                accepted_by="maint.scaler.v1",
                processed_at="2025-01-01T00:00:00Z",
                reason="initial_state_unknown",
                details={"blob": "z" * 4096},
            )
        self.assertIsNotNone(notice)
        # Doctrine: prefix is kept so forensic context is not lost.
        self.assertTrue(ack.reason.startswith("initial_state_unknown"))
        self.assertIn("truncated:", ack.reason)


class TestReasonCap(unittest.TestCase):
    def test_oversize_reason_clipped_with_ellipsis(self) -> None:
        with _Env(NEGELIR_MAINT_ACK_REASON_MAX_BYTES="64"):
            ack, _ = build_capped_maint_ack(
                request_id="req-5",
                accepted=False,
                accepted_by="maint.scaler.v1",
                processed_at="2025-01-01T00:00:00Z",
                reason="x" * 4096,
            )
        self.assertTrue(ack.reason.endswith("…"))
        self.assertLessEqual(len(ack.reason.encode("utf-8")), 64)

    def test_under_cap_reason_unchanged(self) -> None:
        ack, _ = build_capped_maint_ack(
            request_id="req-6",
            accepted=True,
            accepted_by="maint.scaler.v1",
            processed_at="2025-01-01T00:00:00Z",
            reason="ok",
        )
        self.assertEqual(ack.reason, "ok")


class TestOversizeKindRegistered(unittest.TestCase):
    """The notice exists so the caller can publish a debounced
    ``sec.alert.v1{kind=maint_ack_oversize}``. Confirm that kind is
    in the v1 known-kinds set so the producer-side test does not
    flag it as an unknown emission."""

    def test_kind_in_known_set(self) -> None:
        from swarm.agents.payloads import KNOWN_SEC_ALERT_KINDS
        self.assertIn("maint_ack_oversize", KNOWN_SEC_ALERT_KINDS)


if __name__ == "__main__":
    unittest.main()
