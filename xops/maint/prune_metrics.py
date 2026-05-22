"""Phase 8 §8.16.3 — per-table prune metrics stubs.

Exposes two metric helpers per the §8.16.3 doctrine:

* ``maint_backup_prune_seconds{table, outcome}`` — histogram tracking
  how long each table's TTL-prune phase takes.
* ``maint_backup_prune_rows_total{table}`` — counter of rows deleted per
  table per prune tick.

Implementation uses the same pattern as :mod:`ai.common.telemetry`: the
helpers emit to Redis streams using XADD so entries are durable and can
be consumed by dashboards; they fall back to a no-op when Redis is
unavailable (non-blocking).
"""
from __future__ import annotations

import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from common.config import Config


class PruneMetrics:
    """Per-table prune telemetry sink.

    Mirrors the :class:`ai.common.telemetry.TelemetrySink` pattern:
    instantiate once per agent run and call the helpers around each
    per-table prune batch.

    Example::

        metrics = PruneMetrics(cfg)
        t0 = time.monotonic()
        # ... execute DELETE batch for table "opsctl_audit" ...
        metrics.record_prune_seconds(
            table="opsctl_audit",
            outcome="ok",
            elapsed_s=time.monotonic() - t0,
        )
        metrics.record_prune_rows(table="opsctl_audit", rows=42)
    """

    _PRUNE_SECONDS_STREAM = "negelir:maint:prune_seconds"
    _PRUNE_ROWS_STREAM = "negelir:maint:prune_rows_total"
    _DEFAULT_MAX_STREAM_LEN = 10_000

    def __init__(self, config: "Config | None" = None) -> None:
        self._redis = None
        max_len = self._DEFAULT_MAX_STREAM_LEN
        try:
            from common.config import Config as _Config
            cfg = config or _Config()
            max_len = getattr(cfg, "telemetry_max_stream_len", max_len)
            import redis as _redis_lib
            self._redis = _redis_lib.Redis(
                host=cfg.redis_host,
                port=cfg.redis_port,
                decode_responses=True,
                socket_connect_timeout=getattr(cfg, "redis_socket_timeout", 2),
            )
            self._redis.ping()
        except Exception:  # noqa: BLE001
            self._redis = None
        self._max_stream_len = max_len

    @property
    def enabled(self) -> bool:
        return self._redis is not None

    def record_prune_seconds(
        self,
        *,
        table: str,
        outcome: str,
        elapsed_s: float,
    ) -> None:
        """Emit ``maint_backup_prune_seconds{table, outcome}`` observation.

        ``outcome`` should be one of ``"ok"``, ``"error"``, ``"skipped"``.
        """
        if not self._redis:
            return
        entry = {
            "ts": str(time.time()),
            "table": table,
            "outcome": outcome,
            "elapsed_s": str(round(elapsed_s, 6)),
        }
        try:
            self._redis.xadd(
                self._PRUNE_SECONDS_STREAM,
                entry,
                maxlen=self._max_stream_len,
            )
        except Exception:  # noqa: BLE001
            pass  # non-blocking

    def record_prune_rows(self, *, table: str, rows: int) -> None:
        """Emit ``maint_backup_prune_rows_total{table}`` increment.

        ``rows`` is the number of rows deleted in this batch.
        """
        if not self._redis:
            return
        entry = {
            "ts": str(time.time()),
            "table": table,
            "rows": str(rows),
        }
        try:
            self._redis.xadd(
                self._PRUNE_ROWS_STREAM,
                entry,
                maxlen=self._max_stream_len,
            )
        except Exception:  # noqa: BLE001
            pass  # non-blocking


__all__ = ["PruneMetrics"]
