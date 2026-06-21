"""Phase 10 §10.1 — Bounded latency tests.

Verifies that:
  1. The compute_p95 helper in xops/makefile/nlp.py is arithmetically
     correct (happy + edge + adversarial paths).
  2. The nlp.bench command returns exit-code 0 when the injected
     latencies are below the threshold, and 1 when above (mechanism
     test — no real I/O, fully deterministic).
  3. normalize_input on a max-length payload completes within a generous
     500 ms p95 bound (regression guard — catches infinite loops or
     catastrophic regressions; not the 5 ms CI gate itself).

Per AGENTS.md Rule 10: happy + adversarial + regression tests.
"""
from __future__ import annotations

import time
from typing import List
from unittest.mock import patch

import pytest

# xops is on sys.path via conftest.py (REPO_ROOT is inserted there).
from xops.makefile.nlp import _build_payload, cmd_nlp_bench, compute_p95


# ---------------------------------------------------------------------------
# compute_p95 unit tests
# ---------------------------------------------------------------------------
class TestComputeP95:
    def test_empty_list_returns_zero(self) -> None:
        assert compute_p95([]) == 0.0

    def test_single_element(self) -> None:
        assert compute_p95([7.0]) == 7.0

    def test_known_uniform_list(self) -> None:
        # All values equal → p95 == that value.
        assert compute_p95([3.0] * 100) == 3.0

    def test_ascending_ten_elements(self) -> None:
        # [1,2,...,10] sorted; idx = int(0.95*10) = 9 → value 10.
        vals = [float(x) for x in range(1, 11)]
        assert compute_p95(vals) == 10.0

    def test_ascending_twenty_elements(self) -> None:
        # [1..20]; idx = int(0.95*20) = 19 → value 20.
        vals = [float(x) for x in range(1, 21)]
        assert compute_p95(vals) == 20.0

    def test_adversarial_single_spike(self) -> None:
        # 950 fast + 50 slow; p95 must be one of the slow values (50).
        fast = [1.0] * 950
        slow = [50.0] * 50
        p95 = compute_p95(fast + slow)
        assert p95 == 50.0

    def test_adversarial_just_below_95pct(self) -> None:
        # 949 fast + 51 slow (51% spill past 95th index).
        # idx = int(0.95 * 1000) = 950 → the 951st element (0-based: index 950).
        # sorted: 949×1.0, 51×50.0 → index 950 is in the slow region.
        fast = [1.0] * 949
        slow = [50.0] * 51
        p95 = compute_p95(fast + slow)
        assert p95 == 50.0

    def test_order_independent(self) -> None:
        import random
        vals = [float(x) for x in range(100)]
        shuffled = vals[:]
        random.shuffle(shuffled)
        assert compute_p95(vals) == compute_p95(shuffled)


# ---------------------------------------------------------------------------
# build_payload unit tests
# ---------------------------------------------------------------------------
class TestBuildPayload:
    def test_length_exact(self) -> None:
        for n in (1, 50, 100, 512):
            payload = _build_payload(n)
            assert len(payload) == n, f"expected {n}, got {len(payload)}"

    def test_non_empty_phrase(self) -> None:
        assert len(_build_payload(512)) > 0


# ---------------------------------------------------------------------------
# cmd_nlp_bench mechanism tests (no real timing — injected latencies)
# ---------------------------------------------------------------------------
class TestCmdNlpBench:
    """Test exit codes under injected timing conditions."""

    def _run_with_fake_timings(
        self,
        keyboard_timings_ms: List[float],
        voice_timings_ms: list[float] | None = None,
    ) -> int:
        """Run cmd_nlp_bench with perf_counter mocked to emit timing pairs."""
        if voice_timings_ms is None:
            voice_timings_ms = keyboard_timings_ms
        if len(voice_timings_ms) != len(keyboard_timings_ms):
            raise ValueError("keyboard_timings_ms and voice_timings_ms must match length")

        times_s: List[float] = []
        accumulated = 0.0
        for keyboard_ms in keyboard_timings_ms:
            times_s.append(accumulated)          # keyboard t0
            accumulated += keyboard_ms / 1_000.0
            times_s.append(accumulated)          # keyboard t1
        for voice_ms in voice_timings_ms:
            times_s.append(accumulated)          # voice t0
            accumulated += voice_ms / 1_000.0
            times_s.append(accumulated)          # voice t1
        # Pad with zeros so repeated calls beyond our list don't raise.
        times_s.extend([accumulated] * 4)

        iter_count = len(keyboard_timings_ms)
        with patch("xops.makefile.nlp._ITERATIONS", iter_count):
            with patch("time.perf_counter", side_effect=times_s):
                return cmd_nlp_bench([])

    def test_all_fast_returns_0(self) -> None:
        # 100 iterations at 0.5 ms each → p95 == 0.5 ms < 5 ms threshold.
        timings = [0.5] * 100
        assert self._run_with_fake_timings(timings) == 0

    def test_all_slow_returns_1(self) -> None:
        # 100 iterations at 10 ms each → p95 == 10 ms > 5 ms threshold.
        timings = [10.0] * 100
        assert self._run_with_fake_timings(timings) == 1

    def test_tail_spike_returns_1(self) -> None:
        # 95 fast + 5 spike (6 ms): p95 lands on the spike.
        timings = [0.1] * 95 + [6.0] * 5
        assert self._run_with_fake_timings(timings) == 1

    def test_tail_spike_just_below_returns_0(self) -> None:
        # 96 fast + 4 at 4.9 ms (just under threshold): p95 < 5 ms.
        timings = [0.1] * 96 + [4.9] * 4
        assert self._run_with_fake_timings(timings) == 0

    def test_voice_overhead_allowed_returns_0(self) -> None:
        keyboard = [0.5] * 100
        voice = [2.0] * 100
        assert self._run_with_fake_timings(keyboard, voice) == 0

    def test_voice_overhead_exceeds_returns_1(self) -> None:
        keyboard = [0.5] * 100
        voice = [4.0] * 100
        assert self._run_with_fake_timings(keyboard, voice) == 1


# ---------------------------------------------------------------------------
# Regression guard — actual normalize_input latency (generous 500 ms p95)
# ---------------------------------------------------------------------------
class TestNormalizeInputLatencyRegression:
    """Catch catastrophic regressions (infinite loop, quadratic blowup).

    Uses 50 iterations and a p95 ≤ 500 ms bound (100× the CI gate) to stay
    green on slow CI runners without masking real regressions.
    """

    @pytest.mark.slow
    def test_p95_below_generous_bound(self) -> None:
        from common.config import cfg
        from nlp.normalize import normalize_input

        payload = _build_payload(cfg.nlp_input_max_codepoints)
        latencies_ms: List[float] = []
        for _ in range(50):
            t0 = time.perf_counter()
            normalize_input(payload, cfg=cfg)
            t1 = time.perf_counter()
            latencies_ms.append((t1 - t0) * 1_000.0)

        p95 = compute_p95(latencies_ms)
        assert p95 < 500.0, (
            f"normalize_input p95={p95:.1f} ms on "
            f"{cfg.nlp_input_max_codepoints}-codepoint payload "
            "exceeds 500 ms regression guard"
        )
