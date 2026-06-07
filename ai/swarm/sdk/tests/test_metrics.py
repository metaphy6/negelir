"""Metrics counter + percentile + Prometheus rendering."""
from __future__ import annotations

import urllib.request

from swarm.sdk.metrics import Metrics, MetricsServer


def test_inc_increments_counter() -> None:
    m = Metrics("agent.v1")
    m.inc("msg_consumed")
    m.inc("msg_consumed", by=4)
    snap = m.snapshot()
    assert snap["counter.msg_consumed"] == 5


def test_observe_ms_drives_percentiles() -> None:
    m = Metrics("agent.v1")
    for v in range(1, 101):
        m.observe_ms(v)
    snap = m.snapshot()
    # 50th percentile ≈ 50.5; 95th ≈ 95
    assert 49 <= snap["gauge.latency_ms_p50"] <= 51
    assert 94 <= snap["gauge.latency_ms_p95"] <= 96
    assert snap["gauge.latency_ms_count"] == 100


def test_render_prometheus_includes_agent_label() -> None:
    m = Metrics("echo.v1")
    m.inc("msg_consumed")
    out = m.render_prometheus()
    assert 'swarm_msg_consumed{agent="echo.v1"} 1' in out
    assert "# HELP swarm_msg_consumed" in out
    assert "# TYPE swarm_msg_consumed counter" in out


def test_set_gauge_renders_labels() -> None:
    m = Metrics("echo.v1")
    m.set_gauge("bus_health", {"topic": "data.request.v1", "state": "yellow"}, 1.0)
    out = m.render_prometheus()
    assert "swarm_bus_health{" in out
    assert 'topic="data.request.v1"' in out
    assert 'state="yellow"' in out
    assert 'agent="echo.v1"' in out
    assert "# TYPE swarm_bus_health gauge" in out


def test_empty_metrics_render_safely() -> None:
    out = Metrics("a").render_prometheus()
    # At minimum the latency gauges always appear.
    assert "swarm_latency_ms_count" in out


def test_metrics_server_serves_text_exposition() -> None:
    m = Metrics("served.v1")
    m.inc("msg_consumed", by=3)
    server = MetricsServer(render=m.render_prometheus, host="127.0.0.1", port=0)
    server.start()
    try:
        host, port = server.address
        with urllib.request.urlopen(f"http://{host}:{port}/metrics", timeout=2) as resp:
            assert resp.status == 200
            body = resp.read().decode("utf-8")
        assert 'swarm_msg_consumed{agent="served.v1"} 3' in body
        assert resp.headers.get("Content-Type", "").startswith("text/plain")
    finally:
        server.stop()


def test_metrics_server_404s_other_paths() -> None:
    server = MetricsServer(render=lambda: "", host="127.0.0.1", port=0)
    server.start()
    try:
        host, port = server.address
        try:
            urllib.request.urlopen(f"http://{host}:{port}/other", timeout=2)
        except urllib.request.HTTPError as e:
            assert e.code == 404
        else:
            raise AssertionError("expected 404")
    finally:
        server.stop()
