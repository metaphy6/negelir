"""Tests for Phase 10 §10.4 Drift guard.

Covers:
    1. Config key nlp_intent_accuracy_floor exists with default 0.92.
    2. Config key nlp_intent_drift_window exists with default 1000.
    3. Both env-overridable.
    4. Config validation: accuracy_floor bounded in (0, 1).
    5. Config validation: drift_window >= 1.
    6. IntentDriftGuard construction validates window >= 1 and floor in (0,1).
    7. is_degraded is False until the window is full.
    8. rolling_accuracy is None until the window is full.
    9. After window samples: all-correct → not degraded.
   10. After window samples: all-wrong → degraded.
   11. Accuracy exactly at floor → NOT degraded (floor is a strict lower bound).
   12. Accuracy just below floor → degraded.
   13. record() returns True exactly on a degraded-state transition.
   14. record() returns False when state is unchanged.
   15. Window slides: pushing correct samples after degraded flips recovery.
   16. sample_count and window properties accessible.
   17. IntentClassifier.is_degraded is False when no drift guard attached.
   18. IntentClassifier.is_degraded reflects the attached guard's state.
   19. Adversarial: window=1, one wrong sample triggers degraded.
   20. Adversarial: floor=0.01 — almost never degraded.
"""
from __future__ import annotations

import importlib
from pathlib import Path
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_guard(window: int = 5, floor: float = 0.8):
    from nlp.intent import IntentDriftGuard
    return IntentDriftGuard(window=window, floor=floor)


def _make_clf(tmp_path: Path, drift_guard=None):
    from nlp.intent import IntentClassifier
    return IntentClassifier(
        _model=MagicMock(),
        model_path=tmp_path / "intent.tr.bin",
        _drift_guard=drift_guard,
    )


# ---------------------------------------------------------------------------
# 1–3: Config keys
# ---------------------------------------------------------------------------

class TestDriftGuardConfig:
    def test_accuracy_floor_exists(self):
        from ai.common.config import Config
        cfg = Config()
        assert hasattr(cfg, "nlp_intent_accuracy_floor")

    def test_accuracy_floor_default(self):
        from ai.common.config import Config
        cfg = Config()
        assert cfg.nlp_intent_accuracy_floor == pytest.approx(0.92)

    def test_drift_window_exists(self):
        from ai.common.config import Config
        cfg = Config()
        assert hasattr(cfg, "nlp_intent_drift_window")

    def test_drift_window_default(self):
        from ai.common.config import Config
        cfg = Config()
        assert cfg.nlp_intent_drift_window == 1000

    def test_accuracy_floor_env_override(self, monkeypatch):
        monkeypatch.setenv("NEGELIR_NLP_INTENT_ACCURACY_FLOOR", "0.85")
        from common import config as _cm
        importlib.reload(_cm)
        cfg = _cm.Config()
        assert cfg.nlp_intent_accuracy_floor == pytest.approx(0.85)
        importlib.reload(_cm)

    def test_drift_window_env_override(self, monkeypatch):
        monkeypatch.setenv("NEGELIR_NLP_INTENT_DRIFT_WINDOW", "500")
        from common import config as _cm
        importlib.reload(_cm)
        cfg = _cm.Config()
        assert cfg.nlp_intent_drift_window == 500
        importlib.reload(_cm)


# ---------------------------------------------------------------------------
# 4–5: Config validation
# ---------------------------------------------------------------------------

class TestDriftGuardConfigValidation:
    def test_accuracy_floor_below_zero_invalid(self):
        from ai.common.config import Config
        cfg = Config()
        object.__setattr__(cfg, "nlp_intent_accuracy_floor", -0.1)
        with pytest.raises(ValueError):
            cfg.validate(strict=True)

    def test_accuracy_floor_zero_invalid(self):
        from ai.common.config import Config
        cfg = Config()
        object.__setattr__(cfg, "nlp_intent_accuracy_floor", 0.0)
        with pytest.raises(ValueError):
            cfg.validate(strict=True)

    def test_accuracy_floor_one_invalid(self):
        from ai.common.config import Config
        cfg = Config()
        object.__setattr__(cfg, "nlp_intent_accuracy_floor", 1.0)
        with pytest.raises(ValueError):
            cfg.validate(strict=True)

    def test_drift_window_zero_invalid(self):
        from ai.common.config import Config
        cfg = Config()
        object.__setattr__(cfg, "nlp_intent_drift_window", 0)
        with pytest.raises(ValueError):
            cfg.validate(strict=True)

    def test_drift_window_negative_invalid(self):
        from ai.common.config import Config
        cfg = Config()
        object.__setattr__(cfg, "nlp_intent_drift_window", -5)
        with pytest.raises(ValueError):
            cfg.validate(strict=True)


# ---------------------------------------------------------------------------
# 6: IntentDriftGuard construction validation
# ---------------------------------------------------------------------------

class TestIntentDriftGuardConstruction:
    def test_valid_construction(self):
        guard = _make_guard(window=10, floor=0.9)
        assert guard.window == 10
        assert guard.floor == pytest.approx(0.9)

    def test_window_zero_raises(self):
        from nlp.intent import IntentDriftGuard
        with pytest.raises(ValueError, match="window must be >= 1"):
            IntentDriftGuard(window=0, floor=0.9)

    def test_window_negative_raises(self):
        from nlp.intent import IntentDriftGuard
        with pytest.raises(ValueError, match="window must be >= 1"):
            IntentDriftGuard(window=-1, floor=0.9)

    def test_floor_zero_raises(self):
        from nlp.intent import IntentDriftGuard
        with pytest.raises(ValueError, match="floor must be in"):
            IntentDriftGuard(window=10, floor=0.0)

    def test_floor_one_raises(self):
        from nlp.intent import IntentDriftGuard
        with pytest.raises(ValueError, match="floor must be in"):
            IntentDriftGuard(window=10, floor=1.0)


# ---------------------------------------------------------------------------
# 7–8: Not degraded before window full
# ---------------------------------------------------------------------------

class TestDriftGuardPreWindow:
    def test_is_degraded_false_before_window_full(self):
        guard = _make_guard(window=5, floor=0.8)
        for _ in range(4):
            guard.record(correct=False)  # 4 wrongs — not enough data yet
        assert guard.is_degraded is False

    def test_rolling_accuracy_none_before_window_full(self):
        guard = _make_guard(window=5, floor=0.8)
        for _ in range(4):
            guard.record(correct=True)
        assert guard.rolling_accuracy is None

    def test_sample_count_increments(self):
        guard = _make_guard(window=5, floor=0.8)
        guard.record(correct=True)
        guard.record(correct=False)
        assert guard.sample_count == 2


# ---------------------------------------------------------------------------
# 9–12: Degraded logic after window full
# ---------------------------------------------------------------------------

class TestDriftGuardAfterWindowFull:
    def test_all_correct_not_degraded(self):
        guard = _make_guard(window=5, floor=0.8)
        for _ in range(5):
            guard.record(correct=True)
        assert guard.is_degraded is False
        assert guard.rolling_accuracy == pytest.approx(1.0)

    def test_all_wrong_degraded(self):
        guard = _make_guard(window=5, floor=0.8)
        for _ in range(5):
            guard.record(correct=False)
        assert guard.is_degraded is True
        assert guard.rolling_accuracy == pytest.approx(0.0)

    def test_accuracy_exactly_at_floor_not_degraded(self):
        # floor = 0.8; exactly 4/5 correct → accuracy = 0.8 → NOT degraded
        guard = _make_guard(window=5, floor=0.8)
        for i in range(5):
            guard.record(correct=(i != 4))  # 4 correct, 1 wrong
        assert guard.rolling_accuracy == pytest.approx(0.8)
        assert guard.is_degraded is False  # strictly less than floor triggers

    def test_accuracy_just_below_floor_degraded(self):
        # floor = 0.8; 3/5 correct → accuracy = 0.6 < 0.8 → degraded
        guard = _make_guard(window=5, floor=0.8)
        for i in range(5):
            guard.record(correct=(i < 3))  # 3 correct, 2 wrong
        assert guard.rolling_accuracy == pytest.approx(0.6)
        assert guard.is_degraded is True


# ---------------------------------------------------------------------------
# 13–14: Transition detection via return value
# ---------------------------------------------------------------------------

class TestDriftGuardTransitions:
    def test_record_returns_true_on_first_degraded_transition(self):
        guard = _make_guard(window=3, floor=0.9)
        # Fill with 2 corrects (not full yet — no transition)
        r1 = guard.record(correct=True)
        r2 = guard.record(correct=True)
        assert r1 is False
        assert r2 is False
        # 3rd sample: 2 correct + 1 wrong = 0.666 < 0.9 → transition to degraded
        r3 = guard.record(correct=False)
        assert r3 is True  # just flipped
        assert guard.is_degraded is True

    def test_record_returns_false_when_state_unchanged(self):
        guard = _make_guard(window=3, floor=0.5)
        guard.record(correct=True)
        guard.record(correct=True)
        r = guard.record(correct=True)  # 1.0 > 0.5 → still not degraded
        assert r is False  # no transition

    def test_record_returns_true_on_recovery(self):
        guard = _make_guard(window=3, floor=0.9)
        # Degrade
        for _ in range(3):
            guard.record(correct=False)
        assert guard.is_degraded is True
        # Push 3 corrects to recover
        r1 = guard.record(correct=True)
        r2 = guard.record(correct=True)
        r3 = guard.record(correct=True)
        assert guard.is_degraded is False
        # Exactly one of the last three should have flipped back
        assert (r1 or r2 or r3)


# ---------------------------------------------------------------------------
# 15: Sliding window recovery
# ---------------------------------------------------------------------------

class TestDriftGuardSlidingWindow:
    def test_sliding_window_recovery_after_degraded(self):
        guard = _make_guard(window=5, floor=0.8)
        # Degrade with all-wrong
        for _ in range(5):
            guard.record(correct=False)
        assert guard.is_degraded is True
        # Push 5 corrects — oldest wrongs slide out
        for _ in range(5):
            guard.record(correct=True)
        assert guard.is_degraded is False
        assert guard.rolling_accuracy == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# 16: Properties
# ---------------------------------------------------------------------------

class TestDriftGuardProperties:
    def test_window_property(self):
        guard = _make_guard(window=42, floor=0.5)
        assert guard.window == 42

    def test_floor_property(self):
        guard = _make_guard(window=10, floor=0.75)
        assert guard.floor == pytest.approx(0.75)

    def test_sample_count_caps_at_window(self):
        guard = _make_guard(window=3, floor=0.5)
        for _ in range(10):
            guard.record(correct=True)
        assert guard.sample_count == 3  # deque maxlen caps it


# ---------------------------------------------------------------------------
# 17–18: IntentClassifier integration
# ---------------------------------------------------------------------------

class TestIntentClassifierDriftGuardIntegration:
    def test_is_degraded_false_without_guard(self, tmp_path):
        clf = _make_clf(tmp_path, drift_guard=None)
        assert clf.is_degraded is False

    def test_is_degraded_reflects_guard_state(self, tmp_path):
        guard = _make_guard(window=3, floor=0.9)
        clf = _make_clf(tmp_path, drift_guard=guard)
        assert clf.is_degraded is False
        # Degrade the guard
        for _ in range(3):
            guard.record(correct=False)
        assert guard.is_degraded is True
        assert clf.is_degraded is True

    def test_is_degraded_recovers_when_guard_recovers(self, tmp_path):
        guard = _make_guard(window=3, floor=0.9)
        clf = _make_clf(tmp_path, drift_guard=guard)
        for _ in range(3):
            guard.record(correct=False)
        assert clf.is_degraded is True
        for _ in range(3):
            guard.record(correct=True)
        assert clf.is_degraded is False


# ---------------------------------------------------------------------------
# 19–20: Adversarial edge cases
# ---------------------------------------------------------------------------

class TestDriftGuardAdversarial:
    def test_window_one_wrong_triggers_degraded(self):
        from nlp.intent import IntentDriftGuard
        guard = IntentDriftGuard(window=1, floor=0.5)
        flipped = guard.record(correct=False)
        assert guard.is_degraded is True
        assert flipped is True

    def test_window_one_correct_not_degraded(self):
        from nlp.intent import IntentDriftGuard
        guard = IntentDriftGuard(window=1, floor=0.5)
        flipped = guard.record(correct=True)
        assert guard.is_degraded is False
        assert flipped is False

    def test_very_low_floor_almost_never_degraded(self):
        from nlp.intent import IntentDriftGuard
        guard = IntentDriftGuard(window=5, floor=0.01)
        for _ in range(5):
            guard.record(correct=False)
        # 0/5 = 0.0 < 0.01 → degraded even with very low floor
        assert guard.is_degraded is True

    def test_very_high_floor_almost_always_degraded(self):
        from nlp.intent import IntentDriftGuard
        guard = IntentDriftGuard(window=5, floor=0.999)
        for i in range(5):
            # 4 correct, 1 wrong → 0.8 < 0.999
            guard.record(correct=(i < 4))
        assert guard.is_degraded is True
