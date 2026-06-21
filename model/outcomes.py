"""
Negelir — Outcome collector + retrain trigger.
Phase 6: Buffers validated match outcomes and triggers retraining
when enough new data accumulates.
"""

import time
from dataclasses import dataclass, field

import numpy as np

from common.logger import get_logger

log = get_logger("model.outcomes")


@dataclass
class Outcome:
    """A single validated match outcome."""
    match_id: int
    features: np.ndarray
    actual_result: int       # 0=home, 1=draw, 2=away
    predicted_result: int | None = None
    confidence: float = 0.0
    validated_at: float = field(default_factory=time.time)

    @property
    def correct(self) -> bool:
        return self.predicted_result == self.actual_result


class OutcomeCollector:
    """
    Buffers validated outcomes and triggers retrain at threshold.
    """

    RETRAIN_THRESHOLD = 20

    def __init__(self, retrain_callback=None):
        self._buffer: list[Outcome] = []
        self._all_outcomes: list[Outcome] = []
        self._retrain_callback = retrain_callback
        self._retrain_count = 0

    def on_match_completed(self, match_id: int, features: np.ndarray,
                           actual_result: int, predicted_result: int | None = None,
                           confidence: float = 0.0):
        """
        Buffer a validated outcome. Trigger retrain at threshold.
        """
        outcome = Outcome(
            match_id=match_id,
            features=features,
            actual_result=actual_result,
            predicted_result=predicted_result,
            confidence=confidence,
        )
        self._buffer.append(outcome)
        self._all_outcomes.append(outcome)
        log.info(f"Outcome recorded: match={match_id}, actual={actual_result}, "
                 f"buffer={len(self._buffer)}/{self.RETRAIN_THRESHOLD}")

        if len(self._buffer) >= self.RETRAIN_THRESHOLD:
            self._trigger_retrain()

    def _trigger_retrain(self):
        """Flush buffer and trigger retraining."""
        log.info(f"Retrain threshold reached ({len(self._buffer)} outcomes)")
        if self._retrain_callback:
            self._retrain_callback(self._buffer)
        self._retrain_count += 1
        self._buffer = []

    @property
    def buffer_size(self) -> int:
        return len(self._buffer)

    @property
    def total_outcomes(self) -> int:
        return len(self._all_outcomes)

    @property
    def retrain_count(self) -> int:
        return self._retrain_count

    def accuracy(self, window: int | None = None) -> float:
        """Calculate accuracy over recent outcomes."""
        outcomes = self._all_outcomes[-window:] if window else self._all_outcomes
        outcomes = [o for o in outcomes if o.predicted_result is not None]
        if not outcomes:
            return 0.0
        return sum(1 for o in outcomes if o.correct) / len(outcomes)

    def get_training_data(self) -> tuple[np.ndarray, np.ndarray]:
        """Return all collected outcomes as (X, y) arrays for training."""
        if not self._all_outcomes:
            return np.array([]), np.array([])
        X = np.vstack([o.features for o in self._all_outcomes])
        y = np.array([o.actual_result for o in self._all_outcomes])
        return X, y
