"""Phase 10 §10.5 — EntityExtractor bounded-latency tests.

Verifies that:
  1. The cmd_nlp_entity_bench command returns exit-code 0 when the injected
     latencies are below the threshold, and 1 when above (mechanism test —
     no real I/O, fully deterministic).
  2. EntityExtractor.extract on a max-length token list completes within a
     generous 800 ms p95 bound (regression guard — catches infinite loops or
     catastrophic regressions; not the 8 ms CI gate itself).

Per AGENTS.md Rule 10: happy + adversarial + regression tests.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import List
from unittest.mock import patch

import pytest

# xops is on sys.path via conftest.py (REPO_ROOT is inserted there).
from xops.makefile.nlp import _build_payload, cmd_nlp_entity_bench, compute_p95


# ---------------------------------------------------------------------------
# cmd_nlp_entity_bench mechanism tests (no real timing — injected latencies)
# ---------------------------------------------------------------------------
class TestCmdNlpEntityBench:
    """Test exit codes under injected timing conditions."""

    def _run_with_fake_timings(self, timings_ms: List[float]) -> int:
        """Run cmd_nlp_entity_bench with perf_counter mocked to emit *timings_ms*.

        The actual EntityExtractor.extract still executes (real lexicons on
        disk) but the wall-clock measurements come from the injected values,
        so the test is deterministic regardless of host speed.
        """
        times_s: List[float] = []
        accumulated = 0.0
        for t_ms in timings_ms:
            times_s.append(accumulated)           # t0
            accumulated += t_ms / 1_000.0
            times_s.append(accumulated)           # t1
        # Pad so repeated calls beyond our list don't raise.
        times_s.extend([accumulated] * 4)

        iter_count = len(timings_ms)
        with patch("xops.makefile.nlp._ITERATIONS", iter_count):
            with patch("time.perf_counter", side_effect=times_s):
                return cmd_nlp_entity_bench([])

    def test_all_fast_returns_0(self) -> None:
        # 100 iterations at 0.5 ms each → p95 == 0.5 ms < 8 ms threshold.
        timings = [0.5] * 100
        assert self._run_with_fake_timings(timings) == 0

    def test_all_slow_returns_1(self) -> None:
        # 100 iterations at 20 ms each → p95 == 20 ms > 8 ms threshold.
        timings = [20.0] * 100
        assert self._run_with_fake_timings(timings) == 1

    def test_tail_spike_returns_1(self) -> None:
        # 95 fast + 5 spike (10 ms): p95 lands on the spike.
        timings = [0.1] * 95 + [10.0] * 5
        assert self._run_with_fake_timings(timings) == 1

    def test_tail_spike_just_below_returns_0(self) -> None:
        # 96 fast + 4 at 7.9 ms (just under threshold): p95 < 8 ms.
        timings = [0.1] * 96 + [7.9] * 4
        assert self._run_with_fake_timings(timings) == 0


# ---------------------------------------------------------------------------
# Regression guard — actual EntityExtractor.extract latency (generous bound)
# ---------------------------------------------------------------------------
class TestEntityExtractLatencyRegression:
    """Catch catastrophic regressions (infinite loop, quadratic blowup).

    Uses 50 iterations and a p95 ≤ 800 ms bound (100× the CI gate) to stay
    green on slow CI runners without masking real regressions.
    """

    @pytest.mark.slow
    def test_p95_below_generous_bound(self) -> None:
        from ai.common.config import cfg
        from nlp.entity import EntityExtractor
        from nlp.lexicon_loader import LexiconStore

        lexicon_dir = Path(__file__).resolve().parents[2] / "ai" / "nlp" / "lexicon"
        store = LexiconStore(lexicon_dir)
        store.maybe_reload()
        extractor = EntityExtractor(store=store)

        payload = _build_payload(cfg.nlp_input_max_codepoints)
        tokens = payload.split()

        latencies_ms: List[float] = []
        for _ in range(50):
            t0 = time.perf_counter()
            extractor.extract(tokens)
            t1 = time.perf_counter()
            latencies_ms.append((t1 - t0) * 1_000.0)

        p95 = compute_p95(latencies_ms)
        assert p95 < 800.0, (
            f"EntityExtractor.extract p95={p95:.1f} ms on "
            f"{len(tokens)}-token payload exceeds 800 ms regression guard"
        )
