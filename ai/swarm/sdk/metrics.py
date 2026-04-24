"""In-process metrics with a Prometheus text-format exposition.

Phase 3 deliberately keeps this stdlib-only. We collect counters and a
small reservoir for latency p50/p95/p99. A real Prometheus client lib
can replace this in Phase 11/12 without changing call sites — agents
only ever call `inc()` / `observe_ms()`.

Optional `MetricsServer` exposes the rendered text on
`cfg.swarm_metrics_port` via stdlib `http.server`. Scraping by an
actual Prometheus instance is out of scope for Phase 3 (deferred to
Phase 11/12); this just opens the door.
"""
from __future__ import annotations

import threading
from collections import defaultdict, deque
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Callable, Iterable

# Bound the latency sample to keep memory predictable. p99 over the last
# 1024 messages is good enough for an agent dashboard.
_LATENCY_RESERVOIR_SIZE = 1024


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = max(0, min(len(s) - 1, int(round((pct / 100.0) * (len(s) - 1)))))
    return s[k]


class Metrics:
    """Per-agent counter + latency tracker."""

    def __init__(self, agent_name: str) -> None:
        self.agent_name = agent_name
        self._lock = threading.Lock()
        self._counters: dict[str, int] = defaultdict(int)
        self._latencies: deque[float] = deque(maxlen=_LATENCY_RESERVOIR_SIZE)

    def inc(self, name: str, by: int = 1) -> None:
        with self._lock:
            self._counters[name] += by

    def observe_ms(self, latency_ms: float) -> None:
        with self._lock:
            self._latencies.append(float(latency_ms))

    def snapshot(self) -> dict[str, float]:
        with self._lock:
            counters = dict(self._counters)
            lat = list(self._latencies)
        snap: dict[str, float] = {f"counter.{k}": float(v) for k, v in counters.items()}
        snap["gauge.latency_ms_p50"] = _percentile(lat, 50)
        snap["gauge.latency_ms_p95"] = _percentile(lat, 95)
        snap["gauge.latency_ms_p99"] = _percentile(lat, 99)
        snap["gauge.latency_ms_count"] = float(len(lat))
        return snap

    def render_prometheus(self) -> str:
        """Render the snapshot as Prometheus text exposition."""
        snap = self.snapshot()
        lines: list[str] = []
        agent = self.agent_name
        for k, v in sorted(snap.items()):
            kind, name = k.split(".", 1)
            metric_name = f"swarm_{name}"
            prom_type = "counter" if kind == "counter" else "gauge"
            lines.append(f"# HELP {metric_name} swarm SDK {kind}: {name}")
            lines.append(f"# TYPE {metric_name} {prom_type}")
            lines.append(f'{metric_name}{{agent="{agent}"}} {v:g}')
        return "\n".join(lines) + "\n"


def merge_render(metrics: Iterable[Metrics]) -> str:
    """Render multiple Metrics into one exposition (multi-agent process)."""
    return "".join(m.render_prometheus() for m in metrics)


class MetricsServer:
    """Thin HTTP server exposing `/metrics` in Prometheus text format.

    Runs on a daemon thread. Phase 3 ships the surface; actual
    Prometheus scraping is deferred to Phase 11/12 per scope discipline.
    """

    def __init__(self, render: Callable[[], str], host: str = "0.0.0.0", port: int = 9100) -> None:
        self._render = render
        self._host = host
        self._port = port
        self._httpd: HTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._httpd is not None:
            return
        render = self._render

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 — stdlib API
                if self.path != "/metrics":
                    self.send_response(404)
                    self.end_headers()
                    return
                body = render().encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args, **_kwargs) -> None:
                pass  # silence default access-log spam

        self._httpd = HTTPServer((self._host, self._port), Handler)
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._httpd is None:
            return
        self._httpd.shutdown()
        self._httpd.server_close()
        self._httpd = None
        self._thread = None

    @property
    def address(self) -> tuple[str, int]:
        if self._httpd is None:
            return (self._host, self._port)
        return self._httpd.server_address[:2]  # type: ignore[return-value]
