"""Phase 8 §8.4 — `source.watcher.v1` agent (SDK migration shim).

The Phase 2.8 `source_watcher` package shipped as a CLI-driven
scaffold. Phase 8 wraps it in an :class:`Agent` so it joins the
swarm and can publish on the bus. v1 is intentionally bus-quiet:
it only emits ``maint.event.v1{kind=schema_drift_detected}`` when
the differ flags a semantic change. Operator-driven re-snapshot
commands land with §8.4b.

The actual differ + classifier logic remains in
``swarm.source_watcher.{differ,classifier,planner}``; this module
is the agent surface only.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Callable, Iterable
from uuid import uuid4

from ..sdk.types import Envelope, Message, Topic
from ..agents.topics import MAINT_EVENT

_log = logging.getLogger("swarm.source_watcher.agent")


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _new_id() -> str:
    return uuid4().hex


class SourceWatcherAgent:
    """Phase 8 §8.4 SDK shim around the Phase 2.8 source watcher.

    Subscribes nothing in v1 — the watcher is timer-driven, not
    bus-driven. Publishes ``maint.event.v1`` notifications when
    the planner returns a non-empty action list.
    """

    name = "source.watcher.v1"
    subscribes: tuple[Topic, ...] = ()
    publishes: tuple[Topic, ...] = (MAINT_EVENT,)

    def __init__(
        self,
        *,
        clock_iso: Callable[[], str] | None = None,
        new_id: Callable[[], str] | None = None,
    ) -> None:
        self._clock_iso = clock_iso or _utc_iso
        self._new_id = new_id or _new_id

    def handle(self, msg: Message) -> Iterable[Message]:  # pragma: no cover
        return ()

    def tick(self, source: str, change_kind: str,
             *, severity: str = "info",
             details: dict | None = None) -> Message:
        """Publish a single ``schema_drift_detected`` notification.

        Wired into the existing ``run_once`` scheduler in §8.4b.
        Today this is the bus-emit shim the planner can call.
        """
        payload = {
            "kind": "schema_drift_detected",
            "target": source,
            "produced_at": self._clock_iso(),
            "detector": "source_watcher",
            "change_kind": change_kind,
            "severity": severity,
        }
        if details:
            payload["details"] = dict(details)
        env = Envelope(
            message_id=self._new_id(),
            trace_id=self._new_id(),
            topic=MAINT_EVENT,
            producer=self.name,
            created_at=self._clock_iso(),
            schema_version=1,
            attempt=1,
        )
        return Message(envelope=env, payload=payload)


__all__ = ["SourceWatcherAgent"]
