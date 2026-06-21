from __future__ import annotations

from swarm.sdk import BusHealthTracker, Metrics


class FakeClock:
    def __init__(self, start: float = 0.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now


def test_bus_health_tracker_transitions_green_yellow_red() -> None:
    clock = FakeClock(0.0)
    tracker = BusHealthTracker(clock=clock)

    tracker.record_read_success("data.request.v1")
    assert tracker.topic_health("data.request.v1") == "green"

    clock.now = 60.0
    assert tracker.topic_health("data.request.v1") == "yellow"

    clock.now = 301.0
    assert tracker.topic_health("data.request.v1") == "red"


def test_bus_health_tracker_red_on_consecutive_errors() -> None:
    clock = FakeClock(0.0)
    tracker = BusHealthTracker(clock=clock)

    tracker.record_publish_success("predict.request.v1")
    for _ in range(5):
        tracker.record_publish_error("predict.request.v1")

    assert tracker.topic_health("predict.request.v1") == "red"


def test_bus_health_tracker_emits_prometheus_gauges() -> None:
    clock = FakeClock(0.0)
    metrics = Metrics("agent.v1")
    tracker = BusHealthTracker(clock=clock, metrics=metrics)

    tracker.record_read_success("data.request.v1")
    out = metrics.render_prometheus()

    assert 'swarm_bus_health{' in out
    assert 'topic="data.request.v1"' in out
    assert 'state="green"' in out
    assert 'agent="agent.v1"' in out
    assert ' 1' in out
