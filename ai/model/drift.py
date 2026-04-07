"""
Negelir — Model drift detector.
Phase 6: Rolling accuracy check triggers retrain when performance degrades.
"""

from dataclasses import dataclass

from common.logger import get_logger

log = get_logger("model.drift")


@dataclass
class DriftReport:
    """Result of a drift check."""
    needs_retrain: bool
    current_accuracy: float
    window_size: int
    floor: float


class DriftDetector:
    """
    Rolling accuracy check. Returns True if retrain needed
    when accuracy drops below ACCURACY_FLOOR over WINDOW outcomes.
    """

    WINDOW = 30
    ACCURACY_FLOOR = 0.35

    def __init__(self, window: int | None = None, floor: float | None = None):
        self._window = window or self.WINDOW
        self._floor = floor or self.ACCURACY_FLOOR

    def check(self, outcomes: list) -> DriftReport:
        """
        Check if model is drifting.

        Args:
            outcomes: list of Outcome objects with .correct property

        Returns:
            DriftReport with needs_retrain flag
        """
        recent = outcomes[-self._window:]
        if len(recent) < self._window:
            return DriftReport(
                needs_retrain=False,
                current_accuracy=0.0,
                window_size=len(recent),
                floor=self._floor,
            )

        accuracy = sum(1 for o in recent if o.correct) / len(recent)

        needs_retrain = accuracy < self._floor
        if needs_retrain:
            log.warning(f"Drift detected: accuracy={accuracy:.2%} < floor={self._floor:.2%} "
                        f"over last {self._window} outcomes")

        return DriftReport(
            needs_retrain=needs_retrain,
            current_accuracy=accuracy,
            window_size=len(recent),
            floor=self._floor,
        )
