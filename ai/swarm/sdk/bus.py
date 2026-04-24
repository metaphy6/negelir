"""Bus interface and two implementations.

`Bus` is the seam between agents and the underlying transport. Two impls:

  - `InMemoryBus` — in-process queues per topic + per consumer-group; used
    by every unit test and any single-process tool. Preserves the at-least-
    once contract: `read` claims, `ack` releases; `unacked_reclaim()`
    returns claimed-but-not-acked messages older than `claim_after_sec`.

  - `RedisStreamsBus` — wraps Redis Streams with `XADD` / `XREADGROUP` /
    `XACK` / `XAUTOCLAIM`. Lazy-imports `redis` so the module is importable
    in environments without redis-py.

Common contract for both:

  - `publish(msg)` is fire-and-forget; the message is durably enqueued
    before the call returns.
  - `read(group, consumer, count)` returns up to `count` messages, each
    of which the caller is now responsible for `ack`-ing or letting
    expire so another consumer reclaims.
  - DLQ writes go to `<topic>.dlq`; `dlq_for(topic)` is the canonical name.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any, Iterable, Protocol

from .codec import Codec, JsonCodec
from .types import Message, Topic

DLQ_SUFFIX = ".dlq"


def dlq_for(topic: Topic | str) -> Topic:
    """Canonical DLQ topic name for a given topic."""
    name = str(topic)
    if name.endswith(DLQ_SUFFIX):
        return Topic(name)
    return Topic(name + DLQ_SUFFIX)


@dataclass
class Delivery:
    """A claimed message + the bus-level handle needed to ack/nack it."""

    handle: str  # opaque to callers; e.g. Redis stream entry-id
    topic: Topic
    message: Message


class Bus(Protocol):
    name: str

    def ensure_group(self, topic: Topic | str, group: str) -> None: ...
    def publish(self, msg: Message) -> None: ...
    def read(
        self,
        topic: Topic | str,
        group: str,
        consumer: str,
        count: int,
        block_ms: int = 0,
    ) -> list[Delivery]: ...
    def ack(self, topic: Topic | str, group: str, handle: str) -> None: ...
    def reclaim(
        self,
        topic: Topic | str,
        group: str,
        consumer: str,
        idle_ms: int,
        count: int,
    ) -> list[Delivery]: ...
    def length(self, topic: Topic | str) -> int: ...
    def pending_count(self, topic: Topic | str, group: str) -> int: ...


# ──────────────────────────────────────────────────────────────────────────
#  InMemoryBus
# ──────────────────────────────────────────────────────────────────────────


@dataclass
class _PendingEntry:
    handle: str
    raw: bytes
    consumer: str
    delivered_at: float


class InMemoryBus:
    """Single-process bus with consumer-group + at-least-once semantics.

    Concurrency: thread-safe for typical agent + producer workloads (one
    `RLock`). Not async-aware — callers schedule `read()` on threads or
    use the runner's executor.
    """

    name = "memory"

    def __init__(self, codec: Codec | None = None) -> None:
        self._codec = codec or JsonCodec()
        self._lock = threading.RLock()
        self._streams: dict[Topic, deque[tuple[str, bytes]]] = defaultdict(deque)
        # group → topic → next-index pointer (offset of next un-delivered msg)
        self._group_offsets: dict[tuple[Topic, str], int] = {}
        # group → list of pending entries (claimed, not yet acked)
        self._pending: dict[tuple[Topic, str], list[_PendingEntry]] = defaultdict(list)
        # Monotonic id source for delivery handles
        self._next_id = 0

    # ── Bus protocol ────────────────────────────────────────────────────
    def ensure_group(self, topic: Topic | str, group: str) -> None:
        # New groups start at offset 0 — same as Redis XGROUP CREATE id=0
        # used by RedisStreamsBus. This ensures a publish-then-read flow
        # delivers every message regardless of whether the group existed
        # before the publish.
        key = (Topic(str(topic)), group)
        with self._lock:
            _ = self._streams[Topic(str(topic))]  # ensure deque exists
            self._group_offsets.setdefault(key, 0)
            self._pending.setdefault(key, [])

    def publish(self, msg: Message) -> None:
        raw = self._codec.encode(msg)
        with self._lock:
            self._next_id += 1
            handle = f"{int(time.time() * 1000)}-{self._next_id}"
            self._streams[msg.envelope.topic].append((handle, raw))

    def read(
        self,
        topic: Topic | str,
        group: str,
        consumer: str,
        count: int,
        block_ms: int = 0,  # noqa: ARG002 — accepted for parity with RedisBus
    ) -> list[Delivery]:
        topic_t = Topic(str(topic))
        key = (topic_t, group)
        out: list[Delivery] = []
        with self._lock:
            self.ensure_group(topic_t, group)
            stream = self._streams[topic_t]
            offset = self._group_offsets[key]
            available = list(stream)[offset:]
            now = time.monotonic()
            for handle, raw in available[:count]:
                self._pending[key].append(_PendingEntry(handle, raw, consumer, now))
                out.append(
                    Delivery(handle=handle, topic=topic_t, message=self._codec.decode(raw))
                )
            self._group_offsets[key] = offset + len(out)
        return out

    def ack(self, topic: Topic | str, group: str, handle: str) -> None:
        topic_t = Topic(str(topic))
        key = (topic_t, group)
        with self._lock:
            self._pending[key] = [p for p in self._pending[key] if p.handle != handle]

    def reclaim(
        self,
        topic: Topic | str,
        group: str,
        consumer: str,
        idle_ms: int,
        count: int,
    ) -> list[Delivery]:
        topic_t = Topic(str(topic))
        key = (topic_t, group)
        out: list[Delivery] = []
        cutoff = time.monotonic() - (idle_ms / 1000.0)
        with self._lock:
            self.ensure_group(topic_t, group)
            for entry in list(self._pending[key]):
                if entry.delivered_at <= cutoff and len(out) < count:
                    entry.consumer = consumer
                    entry.delivered_at = time.monotonic()
                    out.append(
                        Delivery(
                            handle=entry.handle,
                            topic=topic_t,
                            message=self._codec.decode(entry.raw),
                        )
                    )
        return out

    def length(self, topic: Topic | str) -> int:
        with self._lock:
            return len(self._streams[Topic(str(topic))])

    def pending_count(self, topic: Topic | str, group: str) -> int:
        with self._lock:
            return len(self._pending[(Topic(str(topic)), group)])

    # ── Test / debug helpers ────────────────────────────────────────────
    def topics(self) -> Iterable[Topic]:
        with self._lock:
            return list(self._streams.keys())

    def drain_topic(self, topic: Topic | str) -> list[Message]:
        """Pop everything off a topic without group bookkeeping (test only)."""
        topic_t = Topic(str(topic))
        with self._lock:
            entries = list(self._streams[topic_t])
            self._streams[topic_t].clear()
        return [self._codec.decode(raw) for _, raw in entries]


# ──────────────────────────────────────────────────────────────────────────
#  RedisStreamsBus  (lazy-imported redis)
# ──────────────────────────────────────────────────────────────────────────


class RedisStreamsBus:
    """Redis Streams implementation of `Bus`.

    Encoding: the bus stores `{"data": <json-bytes>}` as a single-field
    stream entry. This keeps the codec layer in our hands instead of
    Redis's per-field schema.

    Lazy-imports `redis` on construction so the SDK is importable in
    environments without redis-py (e.g. lint-only CI).
    """

    name = "redis"

    def __init__(
        self,
        host: str,
        port: int,
        codec: Codec | None = None,
        socket_timeout: float | None = None,
        dlq_max_len: int = 10_000,
        client: Any | None = None,
    ) -> None:
        self._codec = codec or JsonCodec()
        self._dlq_max_len = dlq_max_len
        if client is not None:
            self._client = client
        else:
            try:
                import redis  # noqa: PLC0415
            except ImportError as exc:
                raise RuntimeError(
                    "RedisStreamsBus requires the `redis` package; "
                    "install it or use InMemoryBus."
                ) from exc
            self._client = redis.Redis(
                host=host,
                port=port,
                socket_timeout=socket_timeout,
                decode_responses=False,
            )

    # ── Bus protocol ────────────────────────────────────────────────────
    def ensure_group(self, topic: Topic | str, group: str) -> None:
        try:
            self._client.xgroup_create(
                str(topic), group, id="0", mkstream=True
            )
        except Exception as exc:  # noqa: BLE001 — narrow by message
            # BUSYGROUP means the group already exists; that's fine.
            if "BUSYGROUP" not in str(exc):
                raise

    def publish(self, msg: Message) -> None:
        raw = self._codec.encode(msg)
        topic = str(msg.envelope.topic)
        maxlen = self._dlq_max_len if topic.endswith(DLQ_SUFFIX) else None
        if maxlen:
            self._client.xadd(topic, {b"data": raw}, maxlen=maxlen, approximate=True)
        else:
            self._client.xadd(topic, {b"data": raw})

    def read(
        self,
        topic: Topic | str,
        group: str,
        consumer: str,
        count: int,
        block_ms: int = 0,
    ) -> list[Delivery]:
        topic_s = str(topic)
        result = self._client.xreadgroup(
            group, consumer,
            streams={topic_s: ">"},
            count=count,
            block=block_ms or None,
        )
        out: list[Delivery] = []
        if not result:
            return out
        for _stream, entries in result:
            for entry_id, fields in entries:
                raw = fields.get(b"data")
                if raw is None:
                    continue
                msg = self._codec.decode(raw)
                handle = entry_id.decode() if isinstance(entry_id, bytes) else str(entry_id)
                out.append(Delivery(handle=handle, topic=Topic(topic_s), message=msg))
        return out

    def ack(self, topic: Topic | str, group: str, handle: str) -> None:
        self._client.xack(str(topic), group, handle)

    def reclaim(
        self,
        topic: Topic | str,
        group: str,
        consumer: str,
        idle_ms: int,
        count: int,
    ) -> list[Delivery]:
        topic_s = str(topic)
        try:
            _next, entries, _deleted = self._client.xautoclaim(
                topic_s, group, consumer, min_idle_time=idle_ms, count=count
            )
        except Exception:  # noqa: BLE001 — older redis-py returns 2-tuple
            return []
        out: list[Delivery] = []
        for entry_id, fields in entries:
            raw = fields.get(b"data")
            if raw is None:
                continue
            msg = self._codec.decode(raw)
            handle = entry_id.decode() if isinstance(entry_id, bytes) else str(entry_id)
            out.append(Delivery(handle=handle, topic=Topic(topic_s), message=msg))
        return out

    def length(self, topic: Topic | str) -> int:
        return int(self._client.xlen(str(topic)))

    def pending_count(self, topic: Topic | str, group: str) -> int:
        try:
            info = self._client.xpending(str(topic), group)
        except Exception:  # noqa: BLE001
            return 0
        # redis-py returns either a dict (newer) or a tuple (older)
        if isinstance(info, dict):
            return int(info.get("pending", 0))
        if isinstance(info, (list, tuple)) and info:
            return int(info[0])
        return 0
