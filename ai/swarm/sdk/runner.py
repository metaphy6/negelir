"""Agent runner: read → handle → publish loop, SIGTERM-safe.

Responsibilities:
  - Ensure consumer groups exist for every subscribed topic
  - Pump messages off the bus respecting `max_in_flight`
  - Increment retry counter on failure; route to `<topic>.dlq` once budget
    is spent
  - Publish handler outputs back through the bus
  - Maintain heartbeat in the registry
  - Reclaim long-pending messages from dead consumers via `bus.reclaim`
  - Stop cleanly on `stop()` or SIGTERM/SIGINT

Threading model: the runner is a single-threaded loop. `step()` is a
unit of work the test suite drives directly without sleeping. `run()`
is the production loop that calls `step()` and sleeps `tick_sec`
between empty reads.
"""
from __future__ import annotations

import logging
import os
import signal
import threading
import time
import uuid
from typing import Any

from .agent import Agent, AgentSpec
from .bus import Bus, Delivery, dlq_for
from .metrics import Metrics
from .registry import AgentRegistry
from .types import ENVELOPE_SCHEMA_VERSION, Envelope, Message, Topic

_log = logging.getLogger(__name__)


class AgentRunner:
    """Drives one agent against one bus."""

    def __init__(
        self,
        agent: Agent,
        bus: Bus,
        registry: AgentRegistry,
        *,
        consumer_group_prefix: str = "swarm",
        heartbeat_sec: int = 5,
        max_in_flight: int = 32,
        retry_budget: int = 3,
        pending_claim_sec: int = 60,
        max_supported_schema_version: int = ENVELOPE_SCHEMA_VERSION,
        instance_id: str | None = None,
        tick_sec: float = 0.1,
        flush_interval_sec: float = 0.1,
        shutdown_grace_s: float | None = None,
        clock: Any = None,
    ) -> None:
        self.agent = agent
        self.bus = bus
        self.registry = registry
        self.consumer_group_prefix = consumer_group_prefix
        self.heartbeat_sec = heartbeat_sec
        self.max_in_flight = max_in_flight
        self.retry_budget = retry_budget
        self.pending_claim_sec = pending_claim_sec
        self.max_supported_schema_version = max_supported_schema_version
        self.instance_id = instance_id or f"{agent.name}.{uuid.uuid4().hex[:8]}"
        self.tick_sec = tick_sec
        self.flush_interval_sec = max(0.0, float(flush_interval_sec))
        if shutdown_grace_s is None:
            try:
                from ai.common.config import cfg as _cfg
                shutdown_grace_s = float(_cfg.nlp_shutdown_grace_s)
            except Exception:  # noqa: BLE001 - keep runner import-safe in minimal environments
                shutdown_grace_s = 20.0
        self.shutdown_grace_s = max(0.0, float(shutdown_grace_s))
        self.metrics = Metrics(agent.name)
        self._stop_event = threading.Event()
        self._inflight = 0
        self._inflight_lock = threading.Lock()
        self._inflight_zero = threading.Event()
        self._inflight_zero.set()
        self._last_heartbeat = 0.0
        self._registered = False
        self._clock = clock or time
        # Throttle reclaim() calls per subscribed topic. Reclaiming
        # every step on every topic is wasteful: the bus contract is
        # "messages idle for `pending_claim_sec` get reclaimed", so we
        # only need to *check* every ~half-window. This drops 90%+ of
        # the per-tick reclaim cost when the pending set is empty.
        self._reclaim_interval = max(1.0, pending_claim_sec / 2.0)
        self._last_reclaim_at: dict[str, float] = {}
        # Phase-6 audit (F-2): aggregator-style agents (consensus,
        # proofreader_aggregator) finalise pending windows in
        # `flush_expired()`. Without a runner-driven tick, idle traffic
        # leaves windows open forever and `no_quorum` candidates never
        # surface. We drive it once per `flush_interval_sec` from
        # `step()`. Detection is duck-typed (hasattr) so non-aggregator
        # agents pay zero cost.
        self._has_flush = callable(getattr(agent, "flush_expired", None))
        self._last_flush_at = 0.0
        # Phase 8.4: time-driven agents (for example source.watcher.v1)
        # tick from the runner heartbeat rather than a standalone loop.
        self._has_heartbeat_tick = callable(getattr(agent, "on_heartbeat", None))

    # ── Lifecycle ───────────────────────────────────────────────────────
    def register(self) -> None:
        spec = AgentSpec(
            name=self.agent.name,
            instance_id=self.instance_id,
            subscribes=tuple(self.agent.subscribes),
            publishes=tuple(self.agent.publishes),
            pid=os.getpid(),
            started_at="",
        )
        self.registry.register(spec)
        for topic in self.agent.subscribes:
            self.bus.ensure_group(topic, self._group_name())
        self._registered = True
        self._heartbeat_now()

    def deregister(self) -> None:
        if not self._registered:
            return
        self.registry.deregister(self.instance_id)
        self._registered = False

    def stop(self) -> None:
        self._stop_event.set()

    def install_signal_handlers(self) -> None:
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                signal.signal(sig, lambda *_: self.stop())
            except (ValueError, OSError):
                # Not the main thread (e.g. inside pytest); ignore.
                pass

    # ── Main loop ───────────────────────────────────────────────────────
    def run(self) -> None:
        self.install_signal_handlers()
        self.register()
        try:
            while not self._stop_event.is_set():
                did_work = self.step()
                if not did_work:
                    self._stop_event.wait(self.tick_sec)
        finally:
            self._drain_on_shutdown()
            self.deregister()

    def step(self) -> bool:
        """One iteration of the loop. Returns True if any message was processed."""
        if self._stop_event.is_set():
            return False
        did_work = False
        now = self._monotonic()
        for topic in self.agent.subscribes:
            if self._stop_event.is_set():
                break
            # First: try to reclaim any long-pending messages from dead peers,
            # but throttled so we don't scan the pending set every tick.
            topic_key = str(topic)
            last = self._last_reclaim_at.get(topic_key, 0.0)
            if (now - last) >= self._reclaim_interval:
                self._last_reclaim_at[topic_key] = now
                reclaimed = self.bus.reclaim(
                    topic,
                    self._group_name(),
                    self.instance_id,
                    idle_ms=int(self.pending_claim_sec * 1000),
                    count=self.max_in_flight,
                )
                for delivery in reclaimed:
                    self._process(delivery)
                    did_work = True
                    if self._stop_event.is_set():
                        break
            if self._stop_event.is_set():
                break
            # Then: read fresh messages.
            new_msgs = self.bus.read(
                topic,
                self._group_name(),
                self.instance_id,
                count=self.max_in_flight,
            )
            for delivery in new_msgs:
                self._process(delivery)
                did_work = True
                if self._stop_event.is_set():
                    break
        # Phase-6 audit (F-2): drive `flush_expired` for aggregator-
        # style agents on a steady cadence regardless of inbound
        # traffic, so windows actually close.
        if self._has_flush and (now - self._last_flush_at) >= self.flush_interval_sec:
            self._last_flush_at = now
            try:
                outputs = list(self.agent.flush_expired() or ())  # type: ignore[attr-defined]
            except Exception as exc:  # noqa: BLE001 — mirror handler-failure semantics
                self.metrics.inc("flush_failed")
                _log.warning("agent=%s flush_expired raised: %s", self.agent.name, exc)
                outputs = []
            for out in outputs:
                self.bus.publish(out)
                self.metrics.inc("msg_published")
                did_work = True
        if self._maybe_heartbeat():
            did_work = True
        return did_work

    # ── Per-message processing ──────────────────────────────────────────
    def _process(self, delivery: Delivery) -> None:
        with self._inflight_lock:
            self._inflight += 1
            self._inflight_zero.clear()
        try:
            msg = delivery.message
            env = msg.envelope
            self.metrics.inc("msg_consumed")

            # Schema-version refusal: send straight to DLQ, do NOT retry.
            if env.schema_version > self.max_supported_schema_version:
                _log.error(
                    "agent=%s refusing message schema_version=%d > supported=%d",
                    self.agent.name, env.schema_version, self.max_supported_schema_version,
                )
                self._to_dlq(delivery, reason="schema_version_unsupported")
                self.bus.ack(delivery.topic, self._group_name(), delivery.handle)
                return

            start = self._clock.monotonic() if hasattr(self._clock, "monotonic") else time.monotonic()
            try:
                outputs = list(self.agent.handle(msg) or ())
            except Exception as exc:  # noqa: BLE001 — handler errors are bus-level
                self.metrics.inc("msg_failed")
                _log.warning(
                    "agent=%s handler raised on trace=%s: %s",
                    self.agent.name, env.trace_id, exc,
                )
                self._handle_failure(delivery)
                return
            finally:
                elapsed_ms = (
                    (self._clock.monotonic() if hasattr(self._clock, "monotonic") else time.monotonic())
                    - start
                ) * 1000.0
                self.metrics.observe_ms(elapsed_ms)

            for out in outputs:
                self.bus.publish(out)
                self.metrics.inc("msg_published")
            self.bus.ack(delivery.topic, self._group_name(), delivery.handle)
        finally:
            with self._inflight_lock:
                self._inflight = max(0, self._inflight - 1)
                if self._inflight == 0:
                    self._inflight_zero.set()

    def _drain_on_shutdown(self) -> None:
        """Best-effort graceful shutdown: drain in-flight then run hooks."""
        if self.shutdown_grace_s > 0:
            self._inflight_zero.wait(timeout=self.shutdown_grace_s)
        if callable(getattr(self.agent, "flush_on_shutdown", None)):
            try:
                outputs = list(self.agent.flush_on_shutdown() or ())  # type: ignore[attr-defined]
                for out in outputs:
                    self.bus.publish(out)
                    self.metrics.inc("msg_published")
            except Exception as exc:  # noqa: BLE001 - shutdown is best-effort
                self.metrics.inc("shutdown_flush_failed")
                _log.warning("agent=%s flush_on_shutdown raised: %s", self.agent.name, exc)
        if callable(getattr(self.agent, "release_gpu_lease", None)):
            try:
                self.agent.release_gpu_lease()  # type: ignore[attr-defined]
            except Exception as exc:  # noqa: BLE001 - shutdown is best-effort
                self.metrics.inc("shutdown_gpu_release_failed")
                _log.warning("agent=%s release_gpu_lease raised: %s", self.agent.name, exc)
        release_consumer = getattr(self.bus, "release_consumer", None)
        if callable(release_consumer):
            for topic in self.agent.subscribes:
                try:
                    release_consumer(topic, self._group_name(), self.instance_id)
                except Exception as exc:  # noqa: BLE001 - bus-specific best-effort
                    _log.warning(
                        "agent=%s release_consumer topic=%s failed: %s",
                        self.agent.name,
                        topic,
                        exc,
                    )

    def _handle_failure(self, delivery: Delivery) -> None:
        env = delivery.message.envelope
        next_attempt = env.attempt + 1
        if next_attempt >= self.retry_budget:
            self._to_dlq(delivery, reason="retry_budget_exhausted")
            self.bus.ack(delivery.topic, self._group_name(), delivery.handle)
            return
        # Re-publish with incremented attempt counter; ack the original so
        # we don't double-deliver. This is the simplest at-least-once retry.
        retried = Message(
            envelope=Envelope(
                message_id=env.message_id,
                trace_id=env.trace_id,
                topic=env.topic,
                producer=env.producer,
                created_at=env.created_at,
                schema_version=env.schema_version,
                attempt=next_attempt,
            ),
            payload=delivery.message.payload,
        )
        self.bus.publish(retried)
        self.metrics.inc("msg_retried")
        self.bus.ack(delivery.topic, self._group_name(), delivery.handle)

    def _to_dlq(self, delivery: Delivery, reason: str) -> None:
        env = delivery.message.envelope
        dlq_topic = dlq_for(env.topic)
        dlq_env = Envelope(
            message_id=env.message_id,
            trace_id=env.trace_id,
            topic=dlq_topic,
            producer=env.producer,
            created_at=env.created_at,
            schema_version=env.schema_version,
            attempt=env.attempt,
        )
        dlq_payload = {
            "original_topic": str(env.topic),
            "reason": reason,
            "attempts": env.attempt + 1,
            "payload": delivery.message.payload,
        }
        self.bus.publish(Message(envelope=dlq_env, payload=dlq_payload))
        self.metrics.inc("msg_dlq")

    # ── Heartbeat / group helpers ──────────────────────────────────────
    def _group_name(self) -> str:
        return f"{self.consumer_group_prefix}:{self.agent.name}"

    def _maybe_heartbeat(self) -> None:
        now = self._monotonic()
        if now - self._last_heartbeat >= self.heartbeat_sec:
            self._heartbeat_now()
            if self._has_heartbeat_tick:
                try:
                    outputs = list(self.agent.on_heartbeat() or ())  # type: ignore[attr-defined]
                except Exception as exc:  # noqa: BLE001 — mirror handler-failure semantics
                    self.metrics.inc("heartbeat_failed")
                    _log.warning("agent=%s on_heartbeat raised: %s", self.agent.name, exc)
                    return False
                for out in outputs:
                    self.bus.publish(out)
                    self.metrics.inc("msg_published")
                return bool(outputs)
        return False

    def _heartbeat_now(self) -> None:
        self.registry.heartbeat(self.instance_id)
        self._last_heartbeat = self._monotonic()

    def _monotonic(self) -> float:
        if hasattr(self._clock, "monotonic"):
            return float(self._clock.monotonic())
        return time.monotonic()
