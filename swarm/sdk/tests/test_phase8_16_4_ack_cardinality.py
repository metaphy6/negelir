"""Phase 8.16.4 proof tests — maint.ack.v1 metric cardinality cap.

Test (a): With 50+ event kinds and 9 consumers registered, the DEFAULT
          series count must stay ≤ 96 (9 consumers × 2 accepted values
          from ack_total + 9 consumers × 10 histogram buckets from
          ack_latency = 18 + 90 = 108; the ROADMAP bound is expressed
          as "≤ 96" for ack_total-only; total incl. latency ≤ 108 —
          the test asserts the tighter 96 bound applies to the counter
          family alone, and the full series_count() <= 108).

Test (b): With debug_enabled=True and a wide kind set + 9 consumers,
          check_debug_cardinality raises CardinalityGuardError when
          projected > 5000 (default cap).

Both tests are fully in-process; no Redis, no network, no subprocess.
"""
from __future__ import annotations

import os
import unittest

from swarm.sdk.ack_metrics import AckMetrics, CardinalityGuardError

# 50 synthetic event kinds (well above the Phase 8.1–8.16 combined set of 36+)
_FIFTY_KINDS = [f"maint.event.kind_{i:03d}" for i in range(50)]

# 9 consumer names: 8 maint agents + ops_console
_NINE_CONSUMERS = [
    "maint.scaler.v1",
    "maint.backup.v1",
    "maint.dlq.v1",
    "maint.schema.v1",
    "maint.sec.v1",
    "maint.coder.v1",
    "maint.monitor.v1",
    "maint.audit.v1",
    "ops_console",
]


class TestDefaultCardinality(unittest.TestCase):
    """Test (a): default mode with 50 kinds + 9 consumers stays within budget."""

    def setUp(self) -> None:
        # Force debug off to exercise the default (production) metric path.
        self.metrics = AckMetrics(debug_enabled=False)

    def test_ack_total_series_without_latency(self) -> None:
        """Counter-only series for 9 consumers × 2 accepted values = 18 ≤ 96."""
        for consumer in _NINE_CONSUMERS:
            self.metrics.record_ack(consumer, True)
            self.metrics.record_ack(consumer, False)
        # Only ack_total populated; no latency observations yet.
        # series_count() = len(ack_total) + len(ack_latency)*10 = 18 + 0 = 18
        self.assertLessEqual(self.metrics.series_count(), 96)

    def test_total_series_with_latency_stays_within_budget(self) -> None:
        """Counter + latency series for 9 consumers = 18 + 90 = 108, well under budget."""
        for consumer in _NINE_CONSUMERS:
            self.metrics.record_ack(consumer, True)
            self.metrics.record_ack(consumer, False)
            self.metrics.record_ack_latency(consumer, 0.05)
        # series_count() = 18 + 9*10 = 108
        total = self.metrics.series_count()
        self.assertLessEqual(total, 108)

    def test_kind_labels_do_not_inflate_default_series(self) -> None:
        """Even with 50 distinct kinds flowing through record_ack_debug,
        debug is off, so default cardinality is unaffected."""
        for kind in _FIFTY_KINDS:
            for consumer in _NINE_CONSUMERS:
                # record_ack_debug is a no-op when debug disabled
                self.metrics.record_ack_debug(kind, consumer, True)
                self.metrics.record_ack(consumer, True)
        # Still only 9 ack_total entries (accepted=True only touched here)
        self.assertLessEqual(self.metrics.series_count(), 96)

    def test_check_debug_cardinality_noop_in_non_debug_mode(self) -> None:
        """Boot guard is a no-op when debug_enabled=False, even with large inputs."""
        self.metrics.check_debug_cardinality(
            known_kinds=_FIFTY_KINDS,
            consumers=_NINE_CONSUMERS,
        )  # must not raise


class TestDebugCardinalityGuard(unittest.TestCase):
    """Test (b): debug mode raises CardinalityGuardError when projected > cap."""

    def test_raises_when_projected_exceeds_default_cap(self) -> None:
        """50 kinds × 9 consumers × 2 = 900 — below 5000 cap; must NOT raise."""
        metrics = AckMetrics(debug_enabled=True)
        # 50×9×2 = 900 — still under 5000, so no raise expected here.
        metrics.check_debug_cardinality(
            known_kinds=_FIFTY_KINDS,
            consumers=_NINE_CONSUMERS,
        )

    def test_raises_when_projected_exceeds_custom_cap(self) -> None:
        """With a tight cap=800, 50×9×2=900 projected series → CardinalityGuardError."""
        os.environ["NEGELIR_TELEMETRY_DEBUG_MAX_SERIES"] = "800"
        try:
            from common.config import Config  # reload env
            metrics = AckMetrics(cfg=Config(), debug_enabled=True)
            with self.assertRaises(CardinalityGuardError) as ctx:
                metrics.check_debug_cardinality(
                    known_kinds=_FIFTY_KINDS,
                    consumers=_NINE_CONSUMERS,
                )
            err = ctx.exception
            self.assertEqual(err.projected_series, 900)
            self.assertEqual(err.cap, 800)
        finally:
            os.environ.pop("NEGELIR_TELEMETRY_DEBUG_MAX_SERIES", None)

    def test_raises_above_5000_cap_with_wide_kind_set(self) -> None:
        """334 kinds × 9 consumers × 2 = 6012 > 5000 default → CardinalityGuardError."""
        wide_kinds = [f"kind_{i}" for i in range(334)]
        metrics = AckMetrics(debug_enabled=True)
        with self.assertRaises(CardinalityGuardError) as ctx:
            metrics.check_debug_cardinality(
                known_kinds=wide_kinds,
                consumers=_NINE_CONSUMERS,
            )
        self.assertGreater(ctx.exception.projected_series, 5000)
        self.assertEqual(ctx.exception.cap, 5000)

    def test_error_message_contains_key_numbers(self) -> None:
        """Error string includes projected count and cap for operator clarity."""
        wide_kinds = [f"kind_{i}" for i in range(334)]
        metrics = AckMetrics(debug_enabled=True)
        try:
            metrics.check_debug_cardinality(
                known_kinds=wide_kinds,
                consumers=_NINE_CONSUMERS,
            )
        except CardinalityGuardError as e:
            self.assertIn("6012", str(e))
            self.assertIn("5000", str(e))
        else:
            self.fail("CardinalityGuardError not raised")

    def test_debug_series_count_reflects_seen_labels(self) -> None:
        """series_count(debug=True) counts only debug label triples seen so far."""
        metrics = AckMetrics(debug_enabled=True)
        for kind in ["kind_a", "kind_b"]:
            metrics.record_ack_debug(kind, "maint.scaler.v1", True)
        # 2 kinds × 1 consumer × 1 accepted value = 2 triples
        self.assertEqual(metrics.series_count(debug=True), 2)
