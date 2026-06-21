"""Tests for Phase 10 §10.11 AlertDebouncer (extracted from SecAlertDebouncer).

Per AGENTS.md Rule 10: new abstraction → functional + boundary tests.
"""
from __future__ import annotations

import pytest

from swarm.sdk import AlertDebouncer, DebounceDecision


class _FakeClock:
    """Monotonic-seconds fake for testing debounce TTLs."""

    def __init__(self, start: float = 1000.0) -> None:
        self._now = start

    def __call__(self) -> float:
        return self._now

    def advance(self, delta: float) -> None:
        self._now += delta


def test_alert_debouncer_first_emit():
    """First occurrence of (kind, subject) always emits."""
    clock = _FakeClock()
    d = AlertDebouncer(ttl_s=60, clock=clock)
    decision = d.decide("lexicon_unreadable", "teams.tr.yaml", "error", "Parse failed")
    assert decision.emit is True
    assert decision.reason == "Parse failed"
    assert decision.suppressed_count == 0


def test_alert_debouncer_within_ttl_suppresses():
    """Repeated alert within TTL suppresses."""
    clock = _FakeClock()
    d = AlertDebouncer(ttl_s=60, clock=clock)
    d.decide("lexicon_unreadable", "teams.tr.yaml", "error", "Parse failed")
    clock.advance(30)  # Half TTL
    decision = d.decide("lexicon_unreadable", "teams.tr.yaml", "error", "Parse failed")
    assert decision.emit is False
    assert decision.suppressed_count == 1


def test_alert_debouncer_after_ttl_emits_with_count():
    """After TTL expires, alert emits with suppression count."""
    clock = _FakeClock()
    d = AlertDebouncer(ttl_s=60, clock=clock)
    d.decide("lexicon_unreadable", "teams.tr.yaml", "error", "Parse failed")
    clock.advance(30)
    d.decide("lexicon_unreadable", "teams.tr.yaml", "error", "Parse failed")
    clock.advance(35)  # Total 65s > 60s TTL
    decision = d.decide("lexicon_unreadable", "teams.tr.yaml", "error", "Parse failed")
    assert decision.emit is True
    assert "suppressed: 1" in decision.reason
    assert decision.suppressed_count == 1


def test_alert_debouncer_multiple_suppressions():
    """Multiple suppressions within TTL accumulate."""
    clock = _FakeClock()
    d = AlertDebouncer(ttl_s=60, clock=clock)
    d.decide("lexicon_unreadable", "teams.tr.yaml", "error", "Parse failed")
    for i in range(5):
        clock.advance(10)
        decision = d.decide("lexicon_unreadable", "teams.tr.yaml", "error", "Parse failed")
        assert decision.emit is False
        assert decision.suppressed_count == i + 1
    clock.advance(15)  # Total 65s
    decision = d.decide("lexicon_unreadable", "teams.tr.yaml", "error", "Parse failed")
    assert decision.emit is True
    assert "suppressed: 5" in decision.reason


def test_alert_debouncer_critical_bypasses_by_default():
    """Severity=critical bypasses debounce by default."""
    clock = _FakeClock()
    d = AlertDebouncer(ttl_s=60, clock=clock)
    decision1 = d.decide("nlp_bus_down", None, "critical", "Bus unreachable")
    assert decision1.emit is True
    clock.advance(1)
    decision2 = d.decide("nlp_bus_down", None, "critical", "Bus unreachable")
    assert decision2.emit is True  # No suppression


def test_alert_debouncer_critical_bypass_can_be_disabled():
    """critical_bypass=False debounces even critical alerts."""
    clock = _FakeClock()
    d = AlertDebouncer(ttl_s=60, critical_bypass=False, clock=clock)
    d.decide("nlp_bus_down", None, "critical", "Bus unreachable")
    clock.advance(30)
    decision = d.decide("nlp_bus_down", None, "critical", "Bus unreachable")
    assert decision.emit is False


def test_alert_debouncer_ttl_zero_disables_debouncing():
    """ttl_s=0 escape hatch always emits."""
    clock = _FakeClock()
    d = AlertDebouncer(ttl_s=0, clock=clock)
    d.decide("test_kind", "subj", "warn", "msg")
    decision = d.decide("test_kind", "subj", "warn", "msg")
    assert decision.emit is True


def test_alert_debouncer_different_kinds_independent():
    """Different (kind, subject) pairs are independent."""
    clock = _FakeClock()
    d = AlertDebouncer(ttl_s=60, clock=clock)
    d.decide("kind_a", "subj", "warn", "msg")
    clock.advance(10)
    decision_b = d.decide("kind_b", "subj", "warn", "msg")
    assert decision_b.emit is True  # Different kind


def test_alert_debouncer_different_subjects_independent():
    """Different subjects for same kind are independent."""
    clock = _FakeClock()
    d = AlertDebouncer(ttl_s=60, clock=clock)
    d.decide("lexicon_unreadable", "teams.tr.yaml", "error", "msg")
    clock.advance(10)
    decision = d.decide("lexicon_unreadable", "players.tr.yaml", "error", "msg")
    assert decision.emit is True  # Different subject


def test_alert_debouncer_subject_none_collapses_to_empty():
    """subject=None collapses to empty string for bucket key."""
    clock = _FakeClock()
    d = AlertDebouncer(ttl_s=60, clock=clock)
    d.decide("pattern_reload", None, "info", "msg")
    clock.advance(10)
    decision = d.decide("pattern_reload", None, "info", "msg")
    assert decision.emit is False  # Same bucket


def test_alert_debouncer_lru_eviction():
    """max_buckets cap triggers LRU eviction."""
    clock = _FakeClock()
    d = AlertDebouncer(ttl_s=60, max_buckets=2, clock=clock)
    d.decide("kind_a", "subj", "warn", "msg")
    d.decide("kind_b", "subj", "warn", "msg")
    d.decide("kind_c", "subj", "warn", "msg")  # Evicts kind_a
    clock.advance(10)
    decision_a = d.decide("kind_a", "subj", "warn", "msg")
    assert decision_a.emit is True  # Evicted, so treated as first occurrence


def test_alert_debouncer_reset_clears_state():
    """reset() drops all suppression state."""
    clock = _FakeClock()
    d = AlertDebouncer(ttl_s=60, clock=clock)
    d.decide("kind_a", "subj", "warn", "msg")
    clock.advance(10)
    d.decide("kind_a", "subj", "warn", "msg")
    assert len(d) == 1
    d.reset()
    assert len(d) == 0
    decision = d.decide("kind_a", "subj", "warn", "msg")
    assert decision.emit is True  # Fresh start


def test_alert_debouncer_constructor_validates_max_buckets():
    """max_buckets < 1 raises ValueError."""
    with pytest.raises(ValueError, match="max_buckets must be >= 1"):
        AlertDebouncer(ttl_s=60, max_buckets=0)


def test_alert_debouncer_constructor_validates_ttl_s():
    """ttl_s < 0 raises ValueError."""
    with pytest.raises(ValueError, match="ttl_s must be >= 0"):
        AlertDebouncer(ttl_s=-1)


def test_sec_alert_debouncer_still_works():
    """Backward compatibility: SecAlertDebouncer inherits from _BaseAlertDebouncer."""
    from swarm.agents.sec._alert import SecAlertDebouncer

    clock = _FakeClock()
    d = SecAlertDebouncer(ttl_s=60, clock=clock)
    decision = d.decide("injection_blocked", "192.0.2.1", "warn", "SQL injection")
    assert decision.emit is True
    clock.advance(10)
    decision = d.decide("injection_blocked", "192.0.2.1", "warn", "SQL injection")
    assert decision.emit is False
