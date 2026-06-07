"""Bus health tracker contract for Phase 10 partial-bus graceful degradation."""
from __future__ import annotations

import time
from typing import Callable

from .metrics import Metrics


_DEFAULT_GREEN_WINDOW_S = 30
_DEFAULT_YELLOW_WINDOW_S = 300
_DEFAULT_ERROR_LIMIT = 5


class BusHealthTracker:
    """Bus topic reachability tracker used by Phase 10 partial-bus logic."""

    def __init__(
        self,
        health_map: dict[str, str] | None = None,
        clock: Callable[[], float] | None = None,
        metrics: Metrics | None = None,
    ) -> None:
        self._health_map = health_map or {}
        self._clock = clock or time.time
        self._metrics = metrics
        self._last_read_at: dict[str, float] = {}
        self._last_publish_at: dict[str, float] = {}
        self._consecutive_errors: dict[str, int] = {}
        self._topic_state: dict[str, str] = {}

    def record_read_success(self, topic: str) -> None:
        self._consecutive_errors.pop(topic, None)
        self._last_read_at[topic] = self._clock()
        self._set_topic_health_gauge(topic)

    def record_publish_success(self, topic: str) -> None:
        self._consecutive_errors.pop(topic, None)
        self._last_publish_at[topic] = self._clock()
        self._set_topic_health_gauge(topic)

    def record_read_error(self, topic: str) -> None:
        self._consecutive_errors[topic] = self._consecutive_errors.get(topic, 0) + 1
        self._set_topic_health_gauge(topic)

    def record_publish_error(self, topic: str) -> None:
        self._consecutive_errors[topic] = self._consecutive_errors.get(topic, 0) + 1
        self._set_topic_health_gauge(topic)

    def topic_health(self, topic: str) -> str:
        if topic in self._health_map:
            state = self._health_map[topic]
            self._set_topic_health_gauge(topic, state)
            return state

        state = self._compute_state(topic)
        self._set_topic_health_gauge(topic, state)
        return state

    def _compute_state(self, topic: str) -> str:
        if self._consecutive_errors.get(topic, 0) >= _DEFAULT_ERROR_LIMIT:
            return "red"

        read_at = self._last_read_at.get(topic)
        publish_at = self._last_publish_at.get(topic)
        if read_at is None and publish_at is None:
            return "red"
        last_success = max(val for val in (read_at, publish_at) if val is not None)
        age = self._clock() - last_success
        if age <= _DEFAULT_GREEN_WINDOW_S:
            return "green"
        if age <= _DEFAULT_YELLOW_WINDOW_S:
            return "yellow"
        return "red"

    def _set_topic_health_gauge(self, topic: str, state: str | None = None) -> None:
        if self._metrics is None:
            return
        if state is None:
            state = self._compute_state(topic)

        previous = self._topic_state.get(topic)
        if previous == state:
            return
        if previous is not None:
            self._metrics.set_gauge("bus_health", {"topic": topic, "state": previous}, 0.0)
        self._metrics.set_gauge("bus_health", {"topic": topic, "state": state}, 1.0)
        self._topic_state[topic] = state
