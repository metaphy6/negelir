"""
Negelir — Intent telemetry sink.
Per Gemini §4 Phase 3: persistent observability for TQU classifications
and QID intent distributions, backed by Redis streams.

Falls back to no-op if Redis is unavailable (non-blocking).
"""

import json
import time
from typing import Any

from common.config import Config
from common.logger import get_logger

log = get_logger("telemetry")


class TelemetrySink:
    """
    Async-safe telemetry writer.  Uses Redis XADD (streams) so entries
    are durable and support consumer-group replay for dashboards later.

    Streams created:
      negelir:tqu:classifications  — every classify() call
      negelir:qid:snapshots        — periodic QID distribution snapshots
    """

    _CLASSIFICATION_STREAM = "negelir:tqu:classifications"
    _QID_STREAM = "negelir:qid:snapshots"
    _DEFAULT_MAX_STREAM_LEN = 50_000  # auto-trim oldest entries

    def __init__(self, config: Config | None = None):
        self._redis = None
        cfg = config or Config()
        self._max_stream_len = getattr(cfg, "telemetry_max_stream_len", self._DEFAULT_MAX_STREAM_LEN)
        try:
            import redis
            self._redis = redis.Redis(
                host=cfg.redis_host,
                port=cfg.redis_port,
                decode_responses=True,
                socket_connect_timeout=getattr(cfg, "redis_socket_timeout", 2),
            )
            self._redis.ping()
            log.info("Telemetry sink connected to Redis %s:%s", cfg.redis_host, cfg.redis_port)
        except Exception as exc:  # noqa: BLE001
            log.warning("Redis unavailable (%s) — telemetry disabled", exc)
            self._redis = None

    @property
    def enabled(self) -> bool:
        return self._redis is not None

    # ── TQU classification events ────────────────────────

    def log_classification(
        self,
        raw_input: str,
        intent_id: str | None,
        confidence: float,
        success: bool,
    ) -> None:
        """Push one classification event to the stream."""
        if not self._redis:
            return
        entry: dict[str, Any] = {
            "ts": str(time.time()),
            "intent": intent_id or "none",
            "conf": str(round(confidence, 4)),
            "ok": str(int(success)),
            "input_len": str(len(raw_input)),
        }
        try:
            self._redis.xadd(
                self._CLASSIFICATION_STREAM,
                entry,
                maxlen=self._max_stream_len,
            )
        except Exception:  # noqa: BLE001
            pass  # non-blocking

    # ── QID snapshots ────────────────────────────────────

    def log_qid_snapshot(self, match_id: str, volume: int, distribution: dict[str, float]) -> None:
        """Push a QID distribution snapshot for one match."""
        if not self._redis:
            return
        entry: dict[str, str] = {
            "ts": str(time.time()),
            "match_id": match_id,
            "volume": str(volume),
            "dist": json.dumps(distribution),
        }
        try:
            self._redis.xadd(
                self._QID_STREAM,
                entry,
                maxlen=self._max_stream_len,
            )
        except Exception:  # noqa: BLE001
            pass

    # ── QID persistence (full dump / restore) ────────────

    def persist_qid_profiles(self, profiles: dict) -> int:
        """Persist full QID profiles dict to Redis hash for crash recovery.
        Returns count of matches persisted."""
        if not self._redis:
            return 0
        key = "negelir:qid:profiles"
        count = 0
        try:
            pipe = self._redis.pipeline()
            for match_id, profile_data in profiles.items():
                pipe.hset(key, match_id, json.dumps(profile_data))
                count += 1
            pipe.execute()
            log.debug("Persisted %d QID profiles to Redis", count)
        except Exception:  # noqa: BLE001
            count = 0
        return count

    def restore_qid_profiles(self) -> dict:
        """Restore QID profiles from Redis hash. Returns dict of match_id → profile_data."""
        if not self._redis:
            return {}
        key = "negelir:qid:profiles"
        try:
            raw = self._redis.hgetall(key)
            return {k: json.loads(v) for k, v in raw.items()}
        except Exception:  # noqa: BLE001
            return {}

    # ── Stats ────────────────────────────────────────────

    def stream_lengths(self) -> dict[str, int]:
        """Return current stream lengths for monitoring."""
        if not self._redis:
            return {}
        try:
            return {
                "classifications": self._redis.xlen(self._CLASSIFICATION_STREAM),
                "qid_snapshots": self._redis.xlen(self._QID_STREAM),
            }
        except Exception:  # noqa: BLE001
            return {}


# Module-level singleton — lazy init on first import
_sink: TelemetrySink | None = None


def get_sink() -> TelemetrySink:
    global _sink
    if _sink is None:
        _sink = TelemetrySink()
    return _sink
