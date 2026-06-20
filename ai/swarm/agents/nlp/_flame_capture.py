from __future__ import annotations

import json
import os
import time
import tracemalloc
from pathlib import Path
from typing import Any, Callable, Optional

from ai.common.config import Config
from ai.common.logger import get_logger
from ai.common.telemetry import NLP_FLAME_CAPTURE_ARMED_COUNT
from ...sdk.types import Message
from ..topics import MAINT_EVENT

log = get_logger("swarm.agents.nlp.flame_capture")


class _NlpFlameCaptureStage:
    def __init__(self, stage_name: str) -> None:
        self.stage_name = stage_name
        self.start_snapshot = tracemalloc.take_snapshot()
        self.start_ns = time.monotonic_ns()

    def close(self, ruleset_version: str) -> dict[str, object]:
        end_snapshot = tracemalloc.take_snapshot()
        end_ns = time.monotonic_ns()
        allocated_bytes = 0
        for stat in end_snapshot.compare_to(self.start_snapshot, "lineno"):
            if stat.size_diff > 0:
                allocated_bytes += stat.size_diff
        return {
            "stage_name": self.stage_name,
            "monotonic_ns_in": self.start_ns,
            "monotonic_ns_out": end_ns,
            "allocated_bytes": allocated_bytes,
            "ruleset_version": ruleset_version,
        }


class _NlpFlameCaptureSession:
    def __init__(
        self,
        request_id: str,
        qa_correlation_id: str,
        payload: dict[str, object],
        config: Config,
    ) -> None:
        self.request_id = request_id
        self.qa_correlation_id = qa_correlation_id
        self.operator_id_h = str(payload.get("operator_id_h") or "")
        self.reason = str(payload.get("reason") or "")
        self._config = config
        self._current_stage: _NlpFlameCaptureStage | None = None
        self.stages: list[dict[str, object]] = []

    def start_stage(self, stage_name: str) -> None:
        if not stage_name:
            return
        if self._current_stage is not None and self._current_stage.stage_name == stage_name:
            return
        self._end_current_stage()
        self._current_stage = _NlpFlameCaptureStage(stage_name)

    def _end_current_stage(self) -> None:
        if self._current_stage is None:
            return
        self.stages.append(self._current_stage.close(str(self._config.nlp_pipeline_version)))
        self._current_stage = None

    def finalize(self) -> dict[str, object]:
        self._end_current_stage()
        return {
            "captured_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "request_id": self.request_id,
            "qa_correlation_id": self.qa_correlation_id,
            "operator_id_h": self.operator_id_h,
            "reason": self.reason,
            "stages": self.stages,
        }


class NlpFlameCapture:
    """Sticky per-request NLP flame capture arm / capture lifecycle."""

    _ARMED_REQUEST_PREFIX = "nlp:flame:request:"
    _ARMED_QA_PREFIX = "nlp:flame:qa:"
    _ARMED_COUNT_PREFIX = "nlp:flame:armed_count:"
    _current_session: _NlpFlameCaptureSession | None = None

    def __init__(
        self,
        config: Optional[Config] = None,
        redis_client: Optional[Any] = None,
        base_data_dir: Optional[Path] = None,
    ) -> None:
        self._config = config or Config()
        self._redis = redis_client
        self._base_data_dir = (
            base_data_dir
            if base_data_dir is not None
            else Path(__file__).resolve().parents[4] / "data"
        )

    def _redis_client(self) -> Any:
        if self._redis is None:
            import redis

            self._redis = redis.Redis(
                host=self._config.redis_host,
                port=self._config.redis_port,
                socket_timeout=1.0,
                decode_responses=True,
            )
        return self._redis

    def _arm_key(self, request_id: str, qa_correlation_id: str) -> str:
        if request_id:
            return f"{self._ARMED_REQUEST_PREFIX}{request_id}"
        return f"{self._ARMED_QA_PREFIX}{qa_correlation_id}"

    def _count_key(self) -> str:
        now = time.gmtime()
        return f"{self._ARMED_COUNT_PREFIX}{now.tm_year:04d}{now.tm_mon:02d}{now.tm_mday:02d}{now.tm_hour:02d}"

    def arm(
        self,
        request_id: str,
        qa_correlation_id: str,
        ttl_h: int,
        operator_id_h: str,
        reason: str,
    ) -> None:
        if not request_id and not qa_correlation_id:
            raise ValueError("either request_id or qa_correlation_id is required")
        if ttl_h <= 0:
            raise ValueError("ttl_h must be positive")

        client = self._redis_client()
        count_key = self._count_key()
        count = client.incr(count_key)
        if count == 1:
            client.expire(count_key, 3600)
        if count > int(self._config.opsctl_flame_capture_max_armed_per_h):
            client.decr(count_key)
            raise ValueError("flame capture arm quota exceeded")

        armed_key = self._arm_key(request_id, qa_correlation_id)
        value = json.dumps(
            {
                "operator_id_h": operator_id_h,
                "reason": reason,
                "request_id": request_id,
                "qa_correlation_id": qa_correlation_id,
            }
        )
        client.set(armed_key, value, ex=ttl_h * 3600)
        if NLP_FLAME_CAPTURE_ARMED_COUNT is not None:
            try:
                NLP_FLAME_CAPTURE_ARMED_COUNT.inc()
            except Exception:
                pass

    def _getdel(self, key: str) -> Optional[str]:
        client = self._redis_client()
        try:
            if hasattr(client, "getdel"):
                return client.getdel(key)
            pipe = client.pipeline()
            pipe.get(key)
            pipe.delete(key)
            result = pipe.execute()
            return result[0]
        except Exception as exc:
            log.warning("Flame capture Redis unavailable, skipping arm check: %s", exc)
            return None

    def _capture_file_path(self, request_id: str) -> Path:
        directory = self._base_data_dir / "nlp" / "flame_captures"
        directory.mkdir(parents=True, exist_ok=True)
        return directory / f"{request_id}.flame.json"

    def record_stage(self, stage_name: str) -> None:
        if self._current_session is None:
            return
        self._current_session.start_stage(stage_name)

    def capture_if_armed(
        self,
        request_id: str,
        qa_correlation_id: str,
        work: Callable[[], list[Message]],
    ) -> list[Message]:
        armed_request_key = self._arm_key(request_id, "") if request_id else ""
        armed_qa_key = self._arm_key("", qa_correlation_id) if qa_correlation_id else ""
        armed_payload = None
        armed_key = ""
        if armed_request_key:
            armed_payload = self._getdel(armed_request_key)
            armed_key = armed_request_key
        if not armed_payload and armed_qa_key:
            armed_payload = self._getdel(armed_qa_key)
            armed_key = armed_qa_key

        if not armed_payload:
            return work()

        started_tracemalloc = False
        if not tracemalloc.is_tracing():
            tracemalloc.start()
            started_tracemalloc = True

        capture_payload = json.loads(armed_payload)
        session = _NlpFlameCaptureSession(
            request_id=request_id,
            qa_correlation_id=qa_correlation_id,
            payload=capture_payload,
            config=self._config,
        )
        self._current_session = session
        session.start_stage("10.31.8_request_entry")

        try:
            output = work()
            return [
                *output,
                Message.new(
                    topic=MAINT_EVENT,
                    payload={
                        "kind": "nlp_flame_captured",
                        "kind_schema_version": 1,
                        "target": "nlp.flame_capture",
                        "request_id": request_id,
                        "qa_correlation_id": qa_correlation_id,
                        "produced_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    },
                    producer="nlp.dispatcher.v1",
                ),
            ]
        finally:
            if self._current_session is not None:
                capture_file = self._capture_file_path(request_id or qa_correlation_id)
                capture_file.write_text(
                    json.dumps(
                        self._current_session.finalize(),
                        indent=2,
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
                self._current_session = None
            if NLP_FLAME_CAPTURE_ARMED_COUNT is not None:
                try:
                    NLP_FLAME_CAPTURE_ARMED_COUNT.dec()
                except Exception:
                    pass
            if started_tracemalloc:
                tracemalloc.stop()


__all__ = ["NlpFlameCapture"]
