from __future__ import annotations

import json
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from typing import Any

from common.config import cfg


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ConversationStore:
    """Redis-backed conversation context store with a local L0 cache."""

    def __init__(self) -> None:
        self._cache: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._meta_cache: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._max_entries = 1024

    def _redis_client(self):
        try:
            import redis
        except Exception:
            raise

        return redis.Redis(
            host=cfg.redis_host,
            port=cfg.redis_port,
            password=cfg.redis_password if cfg.redis_password else None,
            db=0,
            socket_timeout=0.1,
            socket_connect_timeout=0.1,
            decode_responses=True,
        )

    def _redis_key(self, conversation_id: str) -> str:
        return f"{cfg.nlp_conversation_redis_key_prefix}{conversation_id}"

    def _insert_local(self, conversation_id: str, payload: dict[str, Any]) -> None:
        if conversation_id in self._cache:
            self._cache.move_to_end(conversation_id)
        self._cache[conversation_id] = payload
        while len(self._cache) > self._max_entries:
            self._cache.popitem(last=False)

    def _insert_local_meta(self, conversation_id: str, payload: dict[str, Any]) -> None:
        if conversation_id in self._meta_cache:
            self._meta_cache.move_to_end(conversation_id)
        self._meta_cache[conversation_id] = payload
        while len(self._meta_cache) > self._max_entries:
            self._meta_cache.popitem(last=False)

    def _redis_meta_key(self, conversation_id: str) -> str:
        return f"{self._redis_key(conversation_id)}:meta"

    def _parse_expires_at(self, expires_at: str) -> datetime | None:
        try:
            return datetime.fromisoformat(expires_at)
        except ValueError:
            return None

    def _is_expired(self, payload: dict[str, Any]) -> bool:
        expires_at = payload.get("expires_at_utc")
        if not isinstance(expires_at, str):
            return True
        expires = self._parse_expires_at(expires_at)
        if expires is None:
            return True
        return datetime.now(timezone.utc) >= expires

    def load(self, conversation_id: str) -> dict[str, Any] | None:
        if not conversation_id:
            return None

        payload = self._cache.get(conversation_id)
        if payload is not None:
            if self._is_expired(payload):
                self._cache.pop(conversation_id, None)
                payload = None
            else:
                self._cache.move_to_end(conversation_id)
                return payload

        try:
            client = self._redis_client()
            raw = client.get(self._redis_key(conversation_id))
            if not raw:
                return None
            payload = json.loads(raw)
            if self._is_expired(payload):
                try:
                    client.delete(self._redis_key(conversation_id))
                except Exception:
                    pass
                return None
            self._insert_local(conversation_id, payload)
            return payload
        except Exception:
            return payload

    def load_metadata(self, conversation_id: str) -> dict[str, Any] | None:
        if not conversation_id:
            return None

        payload = self._meta_cache.get(conversation_id)
        if payload is not None:
            return payload

        try:
            client = self._redis_client()
            raw = client.get(self._redis_meta_key(conversation_id))
            if not raw:
                return None
            payload = json.loads(raw)
            self._insert_local_meta(conversation_id, payload)
            return payload
        except Exception:
            return payload

    def save_metadata(self, conversation_id: str, payload: dict[str, Any]) -> None:
        if not conversation_id:
            return

        stored = dict(payload)
        ttl = int(cfg.nlp_conversation_idle_ttl_s)
        self._insert_local_meta(conversation_id, stored)
        try:
            client = self._redis_client()
            client.setex(self._redis_meta_key(conversation_id), ttl, json.dumps(stored))
        except Exception:
            pass

    def save(self, payload: dict[str, Any]) -> None:
        conversation_id = str(payload.get("conversation_id", ""))
        if not conversation_id:
            return

        stored = dict(payload)
        ttl = int(cfg.nlp_conversation_idle_ttl_s)
        stored["expires_at_utc"] = (
            datetime.now(timezone.utc) + timedelta(seconds=ttl)
        ).isoformat(timespec="seconds")
        self._insert_local(conversation_id, stored)
        try:
            client = self._redis_client()
            client.setex(self._redis_key(conversation_id), ttl, json.dumps(stored))
        except Exception:
            pass

    def clear(self, conversation_id: str) -> None:
        if not conversation_id:
            return
        self._cache.pop(conversation_id, None)
        self._meta_cache.pop(conversation_id, None)
        try:
            client = self._redis_client()
            client.delete(self._redis_key(conversation_id))
            client.delete(self._redis_meta_key(conversation_id))
        except Exception:
            pass
