"""Phase 4.5 + Phase 6 — Cache agent.

Subscribes:
  * ``match.stored`` (Phase 4.5) — caches normalized record keys with
    ``cfg.cache_record_ttl_sec``.
  * ``predict.approved.v1`` (Phase 6, Wave A.1) — caches
    proofreader-approved predictions with
    ``cfg.cache_prediction_ttl_sec``.
  * ``qa.answer.v1`` (Phase 10 §10.12 L1 answer cache) — caches
    structured NLP answers with intent-class-based TTL
    (``cfg.nlp_answer_cache_ttl_data_s`` for ``data.*`` intents,
    ``cfg.nlp_answer_cache_ttl_predict_s`` for ``predict.*`` intents).

The cache **must not** subscribe to ``predict.final`` directly:
that topic carries CANDIDATE consensus output that has not yet
passed proofreader quorum (ROADMAP §736). The boundary test in
``test_boundary_discipline.py`` enforces this rule.

The Redis-backed implementation lives at ``RedisCacheBackend``; tests
use the ``InMemoryCacheBackend``.

Key shapes are intentionally flat:

    record:<source>:<source_match_id>:<record_type>
    prediction:<match_id>:<market>:<prediction_id>
    answer:<qa_correlation_id_stable_hash>

so the API can do a single GET. TTLs are config-driven via
``cfg.cache_record_ttl_sec``, ``cfg.cache_prediction_ttl_sec``,
``cfg.nlp_answer_cache_ttl_data_s``, and
``cfg.nlp_answer_cache_ttl_predict_s``.

A ``Cache.invalidate(key)`` hook is exposed so the future gRPC
``Invalidate(key)`` server (Phase 9 API surface) can call directly
without going through the bus.
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from typing import Callable, Iterable, Protocol

from common.config import cfg

from ..sdk.types import Message
from .payloads import MatchStored, PredictApproved
from .topics import MATCH_STORED, PREDICT_APPROVED, QA_ANSWER_V1

_log = logging.getLogger(__name__)


class CacheBackend(Protocol):
    def set(self, key: str, value: str, *, ttl_sec: int) -> None: ...
    def get(self, key: str) -> str | None: ...
    def invalidate(self, key: str) -> None: ...


class InMemoryCacheBackend:
    """Thread-safe in-memory backend for tests + swarm.demo."""

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._lock = threading.Lock()
        self._data: dict[str, tuple[str, float]] = {}
        self._clock = clock

    def set(self, key: str, value: str, *, ttl_sec: int) -> None:
        with self._lock:
            self._data[key] = (value, self._clock() + ttl_sec)

    def get(self, key: str) -> str | None:
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return None
            value, exp = entry
            if exp < self._clock():
                self._data.pop(key, None)
                return None
            return value

    def invalidate(self, key: str) -> None:
        with self._lock:
            self._data.pop(key, None)

    def __len__(self) -> int:  # convenience for tests
        with self._lock:
            return len(self._data)


def make_record_key(source: str, key_id: str, record_type: str) -> str:
    """Build the canonical cache key for a normalized record.

    ``key_id`` is the deterministic identifier the API uses to look
    the record up — today the storage agent passes ``stable_id``
    (sha1 of source + source_match_id, truncated). The parameter is
    deliberately *not* called ``source_match_id`` to make the contract
    explicit: callers may pass any stable, deterministic id, but it
    must agree with what the API resolver expects.
    """
    return f"record:{source}:{key_id}:{record_type}"


def make_prediction_key(match_id: str, market: str, prediction_id: str) -> str:
    """Build the canonical cache key for a proofreader-approved prediction.

    Phase 6 (Wave A.1): the cache subscribes to ``predict.approved.v1``
    only. ``prediction_id`` is the deterministic id stamped by
    consensus (sha256 of ``match_id|market|request_id|calibration_version``)
    — making the key unique per request lets the API serve a stable
    response even when the same ``(match_id, market)`` is re-predicted.
    """
    return f"prediction:{match_id}:{market}:{prediction_id}"


def make_answer_key(
    intent: str,
    entity_hash: str,
    fixture_window_bucket: str,
    model_versions_hash: str,
    calibration_version: str,
) -> str:
    """Build the canonical cache key for an L1 NLP answer (Phase 10 §10.12).

    Key = ``sha256(intent|entity_hash|fixture_window_bucket|model_versions_hash|calibration_version)``.

    The stable hash ensures that two requests with identical intent +
    entities + fixture window + model versions + calibration produce the
    same cache key, enabling efficient hit rate on repeated queries.

    Returns:
        Prefixed cache key string: ``answer:<64-hex-sha256>``.
    """
    components = "|".join([
        intent,
        entity_hash,
        fixture_window_bucket,
        model_versions_hash,
        calibration_version,
    ])
    stable_hash = hashlib.sha256(components.encode("utf-8")).hexdigest()
    return f"answer:{stable_hash}"


class CacheAgent:
    name = "cache.v1"
    subscribes: tuple[str, ...] = (MATCH_STORED, PREDICT_APPROVED, QA_ANSWER_V1)
    publishes: tuple[str, ...] = ()  # cache writes are side-effects, not bus events

    def __init__(self, backend: CacheBackend | None = None) -> None:
        # Explicit None check — backends with __len__ (the in-memory one)
        # are falsy when empty, so `backend or default()` would silently
        # discard a freshly-constructed user-supplied backend.
        self.backend = InMemoryCacheBackend() if backend is None else backend

    def handle(self, msg: Message) -> Iterable[Message]:
        topic = msg.envelope.topic
        if topic == MATCH_STORED:
            return self._handle_stored(msg)
        if topic == PREDICT_APPROVED:
            return self._handle_approved(msg)
        if topic == QA_ANSWER_V1:
            return self._handle_answer(msg)
        # The bus dispatcher should never deliver an unsubscribed topic;
        # log loudly and ignore (don't raise — a single bad message must
        # not kill the agent loop).
        _log.warning("%s: unsubscribed topic %r delivered", self.name, topic)
        return ()

    def _handle_stored(self, msg: Message) -> Iterable[Message]:
        try:
            stored = MatchStored.from_dict(msg.payload)
        except (KeyError, TypeError, ValueError) as exc:
            _log.warning("%s: malformed match.stored: %s", self.name, exc)
            return ()

        if stored.change_kind == "unchanged":
            return ()  # nothing to invalidate, nothing to refresh

        key = make_record_key(stored.source, stored.stable_id, stored.record_type)
        # We store a small marker; the API resolves the row by id.
        # Bigger payloads belong in the gRPC cache server, not in-bus.
        # Read directly from cfg — no `getattr` fallback. The triangle
        # (config.py + defaults.yaml + .env.example) guarantees the
        # field exists; a fallback literal here would silently mask
        # field-rename drift instead of failing loudly.
        ttl = int(cfg.cache_record_ttl_sec)
        self.backend.set(
            key,
            f"id={stored.record_id}",
            ttl_sec=ttl,
        )
        return ()

    def _handle_approved(self, msg: Message) -> Iterable[Message]:
        try:
            approved = PredictApproved.from_dict(msg.payload)
        except (KeyError, TypeError, ValueError) as exc:
            _log.warning("%s: malformed predict.approved.v1: %s", self.name, exc)
            return ()

        key = make_prediction_key(
            approved.match_id, approved.market, approved.prediction_id
        )
        # Store the full predict.final payload (already carried verbatim
        # under `final` in the approval envelope) so the API can serve it
        # without a join. JSON-encoded so the in-memory + Redis backends
        # share the same value contract.
        ttl = int(cfg.cache_prediction_ttl_sec)
        self.backend.set(
            key,
            json.dumps(approved.final, separators=(",", ":"), sort_keys=True),
            ttl_sec=ttl,
        )
        return ()

    def _handle_answer(self, msg: Message) -> Iterable[Message]:
        """Cache qa.answer.v1 per Phase 10 §10.12 L1 answer cache.

        Key = sha256(intent|entity_hash|fixture_window_bucket|model_versions_hash|calibration_version).
        TTL is intent-class-based:
          - 120s for `data.*` intents
          - 60s for `predict.*` intents

        Missing or malformed required fields → log warning and skip cache write
        (gracefully degrade; never block answer delivery on cache failure).
        """
        payload = msg.payload
        try:
            intent = str(payload["intent"])
            # Entity hash, fixture window bucket, model versions hash, and
            # calibration version are all expected to be present in the
            # payload per §10.12 spec. If any are missing, skip cache write.
            entity_hash = str(payload.get("entity_hash", ""))
            fixture_window_bucket = str(payload.get("fixture_window_bucket", ""))
            model_versions_hash = str(payload.get("model_versions_hash", ""))
            calibration_version = str(payload.get("calibration_version", ""))
        except (KeyError, TypeError, ValueError) as exc:
            _log.warning("%s: malformed qa.answer.v1 cache fields: %s", self.name, exc)
            return ()

        # Determine TTL based on intent class (data.* vs predict.*)
        if intent.startswith("data."):
            ttl = int(cfg.nlp_answer_cache_ttl_data_s)
        elif intent.startswith("predict."):
            ttl = int(cfg.nlp_answer_cache_ttl_predict_s)
        else:
            # Meta intents and others: use data TTL as default
            ttl = int(cfg.nlp_answer_cache_ttl_data_s)

        key = make_answer_key(
            intent,
            entity_hash,
            fixture_window_bucket,
            model_versions_hash,
            calibration_version,
        )

        if (
            isinstance(payload.get("streaming_chunks"), list)
            and isinstance(payload.get("final_answer"), str)
        ):
            assembled_payload = dict(payload)
            assembled_payload.pop("streaming_chunks", None)
            assembled_payload.pop("final_answer", None)
            # Ensure cache hits can be served as one-shot answers instead
            # of replaying a previously-streamed chunk sequence.
            if "answer_text" in assembled_payload:
                assembled_payload["answer_text"] = payload["final_answer"]
            else:
                assembled_payload["answer_text"] = payload["final_answer"]

            cache_value = {
                "streamed": True,
                "chunks": payload["streaming_chunks"],
                "final": payload["final_answer"],
                "payload": assembled_payload,
            }
        else:
            cache_value = {
                "streamed": False,
                "payload": payload,
            }

        self.backend.set(
            key,
            json.dumps(cache_value, separators=(",", ":"), sort_keys=True),
            ttl_sec=ttl,
        )
        return ()


__all__ = [
    "CacheAgent",
    "CacheBackend",
    "InMemoryCacheBackend",
    "make_answer_key",
    "make_prediction_key",
    "make_record_key",
]
