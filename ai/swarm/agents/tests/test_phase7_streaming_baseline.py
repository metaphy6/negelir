"""Phase 7 §7.2 — direct proof tests for the streaming-statistic
baseline primitives.

The end-to-end ``test_phase7_sec_agents.py`` exercises ``_Welford``
and ``_simhash64`` indirectly through ``SecScrapeAgent``. These
tests pin the math directly so a regression in the primitives
(numerical drift, SimHash non-determinism, memory creep) fires
loud at the unit boundary instead of cascading into agent-level
test noise.

Doctrine (ROADMAP §7.2): the baseline is a **streaming statistic,
not a capped LRU**. Memory must stay ``O(constant per source)``
regardless of sample count; Welford must agree with the textbook
two-pass population variance to within float epsilon; SimHash
must be deterministic across process restarts so fingerprints
can be persisted to ``source_fingerprints`` (Phase 8 migration).
"""
from __future__ import annotations

import random
import statistics
import sys

import pytest

from swarm.agents.sec.scrape import _hamming, _simhash64, _Welford


# ── Welford parity vs textbook two-pass variance ──────────────────


def _two_pass_population_variance(xs: list[float]) -> tuple[float, float]:
    """Reference: textbook two-pass mean / population variance.
    Used as ground truth against the streaming Welford updates.
    """
    n = len(xs)
    assert n > 0
    mean = sum(xs) / n
    var = sum((x - mean) ** 2 for x in xs) / n
    return mean, var


@pytest.mark.parametrize(
    "corpus",
    [
        [1.0, 2.0, 3.0, 4.0, 5.0],
        [1e9, 1e9 + 1, 1e9 + 2, 1e9 + 3, 1e9 + 4],  # large-mean stability
        [1e-9, 2e-9, 3e-9, 4e-9, 5e-9],             # small-mean stability
        [42.0] * 1000,                              # zero-variance constant stream
    ],
)
def test_welford_matches_two_pass_population_variance(corpus: list[float]) -> None:
    w = _Welford()
    for x in corpus:
        w.update(x)
    expected_mean, expected_var = _two_pass_population_variance(corpus)
    # Float epsilon ample for these scales; the large-mean case is
    # the one a naive sum-of-squares implementation would blow up
    # on (catastrophic cancellation). Welford's recurrence avoids
    # that by working with deltas.
    assert w.mean == pytest.approx(expected_mean, rel=1e-12, abs=1e-12)
    assert w.variance == pytest.approx(expected_var, rel=1e-9, abs=1e-12)
    assert w.n == len(corpus)


def test_welford_streaming_matches_two_pass_on_large_random_corpus() -> None:
    """10k samples — the workload size where a sample-LRU baseline
    would have evicted older points and disagreed with two-pass."""
    rng = random.Random(1337)
    corpus = [rng.gauss(mu=8192.0, sigma=1024.0) for _ in range(10_000)]
    w = _Welford()
    for x in corpus:
        w.update(x)
    assert w.n == 10_000
    assert w.mean == pytest.approx(statistics.fmean(corpus), rel=1e-9)
    assert w.variance == pytest.approx(statistics.pvariance(corpus), rel=1e-9)


def test_welford_empty_stats_are_well_defined() -> None:
    w = _Welford()
    assert w.n == 0
    assert w.mean == 0.0
    assert w.variance == 0.0
    assert w.stddev == 0.0


def test_welford_memory_footprint_is_constant_in_n() -> None:
    """The streaming-statistic doctrine demands ``O(constant per
    source)`` regardless of sample count. A capped-LRU baseline
    would grow with n until the cap; Welford carries 3 numeric
    fields and nothing else.
    """
    w_small = _Welford()
    for x in range(100):
        w_small.update(float(x))
    w_large = _Welford()
    for x in range(1_000_000):
        w_large.update(float(x))
    # Same dataclass, same slots — sizeof is identical regardless
    # of sample count.
    assert sys.getsizeof(w_small) == sys.getsizeof(w_large)
    # Defense-in-depth: assert the field set hasn't silently grown.
    assert set(vars(w_large).keys()) == {"n", "mean", "m2"}


# ── SimHash determinism + Hamming distance bounds ─────────────────


def test_simhash_is_deterministic_across_calls() -> None:
    triples = [b"div.match-row#m1", b"span.score", b"a.team-link"]
    h1 = _simhash64(triples)
    h2 = _simhash64(triples)
    assert h1 == h2
    # 64-bit output, fits in unsigned 64.
    assert 0 <= h1 < (1 << 64)


def test_simhash_identical_input_zero_hamming() -> None:
    triples = [b"div.x", b"span.y", b"p.z"]
    assert _hamming(_simhash64(triples), _simhash64(triples)) == 0


def test_simhash_radically_different_dom_has_large_hamming_distance() -> None:
    """A DOM redesign should produce a fingerprint that is many
    bits away — well above the default ``sec_scrape_simhash_max_distance=12``.
    """
    a = [f"div.match.row{i}".encode() for i in range(50)]
    b = [f"section.card{i}.v2".encode() for i in range(50)]
    distance = _hamming(_simhash64(a), _simhash64(b))
    assert distance > 12, f"expected DOM-redesign distance >12, got {distance}"


def test_simhash_empty_iterable_returns_sentinel_zero() -> None:
    """Per the docstring contract: empty iterator → 0; the Hamming
    distance from any real fingerprint will be the popcount of the
    other side. This keeps the agent's first-sample path well-defined
    (cold-start warm-up handles the alerting suppression)."""
    assert _simhash64(iter([])) == 0


def test_hamming_is_symmetric_and_self_zero() -> None:
    a = 0xDEADBEEFCAFEBABE
    b = 0x0123456789ABCDEF
    assert _hamming(a, b) == _hamming(b, a)
    assert _hamming(a, a) == 0
    # Bound: cannot exceed 64 bits.
    assert _hamming(a, b) <= 64
