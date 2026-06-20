"""Phase 8 §8.4 — `source.watcher.v1` agent.

The Phase 2.8 source watcher stays deterministic and time-driven, but
its scheduler now ticks from :class:`swarm.sdk.runner.AgentRunner`
heartbeats instead of a standalone loop. Each heartbeat emits a
``source.watch.report.v1`` envelope carrying the same classification
payload the legacy scheduler path produced.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Optional, Sequence
from uuid import uuid4

from ai.common.config import cfg

from ..agents.payloads import MaintEvent, SecAlert
from ..agents.topics import MAINT_EVENT, PROOF_FLAG, SEC_ALERT, SOURCE_WATCH_REPORT_V1
from ..sdk.agent import Agent
from ..sdk.types import Message, Topic
from . import scheduler, snapshot_store
from .summarizer_budget import AdmitResult, FileSummarizerLedger
from .summarizer import LLMCallable, model_id_is_pinned, probe_endpoint_reachable, summarize

_log = logging.getLogger("swarm.source_watcher.agent")


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _new_id() -> str:
    return uuid4().hex


class SourceWatcherAgent(Agent):
    """Time-driven source watcher running on SDK heartbeats."""

    name = "source.watcher.v1"
    subscribes: tuple[Topic, ...] = ()
    publishes: tuple[Topic, ...] = (SOURCE_WATCH_REPORT_V1, MAINT_EVENT, PROOF_FLAG, SEC_ALERT)

    def __init__(
        self,
        *,
        sources: Sequence[str],
        fetcher: scheduler.Fetcher,
        snapshot_root: Path | str = snapshot_store.HISTORY_ROOT,
        clock_iso: Callable[[], str] | None = None,
        new_id: Callable[[], str] | None = None,
        summarizer_enabled: Optional[bool] = None,
        summarizer_model_id: Optional[str] = None,
        summarizer_probe_url: Optional[str] = None,
        summarizer_probe_timeout_sec: Optional[float] = None,
        summarizer_max_tokens_per_call: Optional[int] = None,
        summarizer_max_tokens_per_day: Optional[int] = None,
        summarizer_ledger_path: Optional[str] = None,
        summarizer_llm: Optional[LLMCallable] = None,
        reachability_probe: Optional[Callable[[str, float], bool]] = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._sources = tuple(sources)
        self._fetcher = fetcher
        self._snapshot_root = snapshot_root
        self._clock_iso = clock_iso or _utc_iso
        self._new_id = new_id or _new_id
        self._log = logger or _log
        requested_enabled = (
            cfg.source_watcher_summarizer_enabled
            if summarizer_enabled is None
            else bool(summarizer_enabled)
        )
        self._summarizer_model_id = (
            cfg.source_watcher_summarizer_model_id
            if summarizer_model_id is None
            else str(summarizer_model_id)
        )
        self._summarizer_probe_url = (
            cfg.source_watcher_summarizer_probe_url
            if summarizer_probe_url is None
            else str(summarizer_probe_url)
        )
        self._summarizer_probe_timeout_sec = (
            cfg.source_watcher_summarizer_probe_timeout_sec
            if summarizer_probe_timeout_sec is None
            else float(summarizer_probe_timeout_sec)
        )
        self._summarizer_max_tokens_per_call = (
            cfg.source_watcher_summarizer_max_tokens_per_call
            if summarizer_max_tokens_per_call is None
            else int(summarizer_max_tokens_per_call)
        )
        self._summarizer_max_tokens_per_day = (
            cfg.source_watcher_summarizer_max_tokens_per_day
            if summarizer_max_tokens_per_day is None
            else int(summarizer_max_tokens_per_day)
        )
        self._summarizer_ledger_path = (
            cfg.source_watcher_summarizer_ledger_path
            if summarizer_ledger_path is None
            else str(summarizer_ledger_path)
        )
        self._summarizer_llm = summarizer_llm
        self._reachability_probe = reachability_probe or (
            lambda url, timeout: probe_endpoint_reachable(url, timeout_sec=timeout)
        )
        self._summarizer_unreachable_alert_pending = False
        self._summarizer_cost_cap_alert_day_by_scope: dict[str, str] = {}
        self._summarizer_ledger = FileSummarizerLedger(
            max_tokens_per_call=self._summarizer_max_tokens_per_call,
            max_tokens_per_day=self._summarizer_max_tokens_per_day,
            ledger_path=self._summarizer_ledger_path,
        )
        ledger_warning = self._summarizer_ledger.load_warning()
        if ledger_warning:
            self._log.warning("%s", ledger_warning)
        self._summarizer_enabled = self._resolve_summarizer_enabled(requested_enabled)

    def _resolve_summarizer_enabled(self, requested_enabled: bool) -> bool:
        if not requested_enabled:
            return False
        if not model_id_is_pinned(self._summarizer_model_id):
            self._log.warning(
                "source watcher summarizer disabled: model id must be pinned; got=%r",
                self._summarizer_model_id,
            )
            return False
        reachable = self._reachability_probe(
            self._summarizer_probe_url,
            float(self._summarizer_probe_timeout_sec),
        )
        if reachable:
            return True
        self._summarizer_unreachable_alert_pending = True
        self._log.warning(
            "source watcher summarizer disabled: probe failed url=%r timeout=%.3fs",
            self._summarizer_probe_url,
            self._summarizer_probe_timeout_sec,
        )
        return False

    def handle(self, msg: Message) -> Iterable[Message]:  # pragma: no cover
        return ()

    def on_heartbeat(self) -> Iterable[Message]:
        out: list[Message] = []
        if self._summarizer_unreachable_alert_pending:
            out.append(self.summarizer_unreachable_alert())
            self._summarizer_unreachable_alert_pending = False
        ticks = scheduler.run_once(
            list(self._sources),
            fetcher=self._fetcher,
            snapshot_root=self._snapshot_root,
        )
        for tick in ticks:
            out.extend(self._report_messages(tick))
            if tick.plan is not None and tick.plan.severity == "schema_breaking":
                out.append(self.schema_drift_event(tick.source, tick.plan.summary))
        return out

    def _should_emit_cost_cap_alert(self, scope: str) -> bool:
        day_utc = datetime.now(timezone.utc).date().isoformat()
        last_day = self._summarizer_cost_cap_alert_day_by_scope.get(scope)
        if last_day == day_utc:
            return False
        self._summarizer_cost_cap_alert_day_by_scope[scope] = day_utc
        return True

    def summarizer_cost_capped_alert(self, scope: str) -> Message:
        alert = SecAlert(
            alert_id=self._new_id(),
            kind="summarizer_cost_capped",
            severity="warn",
            source=self.name,
            reason="source_watcher_summarizer_cost_capped",
            subject=scope,
            produced_at=self._clock_iso(),
        )
        return Message.new(SEC_ALERT, alert.as_dict(), producer=self.name)

    def summarizer_unreachable_alert(self) -> Message:
        alert = SecAlert(
            alert_id=self._new_id(),
            kind="summarizer_unreachable",
            severity="warn",
            source=self.name,
            reason="source_watcher_summarizer_probe_failed",
            subject=self._summarizer_probe_url or None,
            produced_at=self._clock_iso(),
        )
        return Message.new(SEC_ALERT, alert.as_dict(), producer=self.name)

    def schema_drift_event(self, source: str, summary: str) -> Message:
        event = MaintEvent(
            kind="baseline_reset",
            target=source,
            reason="source_watcher_schema_drift",
            produced_at=self._clock_iso(),
        )
        payload = event.as_dict()
        payload["summary"] = summary
        payload["detector"] = "source_watcher"
        return Message.new(MAINT_EVENT, payload, producer=self.name)

    def proof_flag(self, source: str, detail: str, *, kind: str = "parser_exception") -> Message:
        return Message.new(
            PROOF_FLAG,
            {
                "kind": kind,
                "agent": self.name,
                "source": source,
                "detail": detail,
            },
            producer=self.name,
        )

    def _report_messages(self, tick: scheduler.Tick) -> list[Message]:
        summary_text: Optional[str] = None
        summary_source = "disabled"
        out: list[Message] = []
        if tick.plan is not None and tick.plan.diffs:
            if self._summarizer_enabled:
                decision = self._summarizer_ledger.try_admit(
                    self._summarizer_max_tokens_per_call
                )
                if decision is AdmitResult.ADMIT:
                    summary = summarize(
                        tick.plan,
                        enabled=True,
                        llm=self._summarizer_llm,
                        max_tokens=self._summarizer_max_tokens_per_call,
                    )
                    if summary.source == "llm":
                        self._summarizer_ledger.record_usage(
                            self._summarizer_max_tokens_per_call
                        )
                else:
                    summary = summarize(tick.plan, enabled=True, llm=None)
                    scope = "per_call" if decision is AdmitResult.REFUSED_PER_CALL else "per_day"
                    if self._should_emit_cost_cap_alert(scope):
                        out.append(self.summarizer_cost_capped_alert(scope))
            else:
                summary = summarize(tick.plan, enabled=False, llm=self._summarizer_llm)
            summary_text = summary.text
            summary_source = summary.source
        out.append(
            Message.new(
                SOURCE_WATCH_REPORT_V1,
                {
                    "source": tick.source,
                    "produced_at": self._clock_iso(),
                    "classification": list(tick.plan.diffs) if tick.plan is not None else [],
                    "plan": tick.plan.to_dict() if tick.plan is not None else None,
                    "plan_summary_tr": summary_text,
                    "plan_summary_source": summary_source,
                    "skipped_reason": tick.skipped_reason,
                },
                producer=self.name,
                trace_id=self._new_id(),
            )
        )
        return out


__all__ = ["SourceWatcherAgent"]
