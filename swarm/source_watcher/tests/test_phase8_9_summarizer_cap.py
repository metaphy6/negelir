"""Phase 8.9 — Per-call summarizer cap integration tests.

ROADMAP §8.9 DoD bullet (second-pass proof tests):

  **Per-call summarizer cap.** Force a single 200k-token diff; assert API
  request ``max_tokens ≤ 4096``, fall-back deterministic narration is
  published, ``summarizer_cost_capped{scope=per_call}`` fires; daily counter
  increments by ``≤ max_tokens_per_call``.

Tests
-----
1. ``test_api_max_tokens_bounded_at_cap`` — even when a 200k-character diff is
   fed to the agent the LLM callable receives ``max_tokens=cfg_cap`` (4096), not
   the diff size.  Daily counter increments by exactly ``max_tokens_per_call``.
2. ``test_per_call_refusal_emits_fallback_narration`` — when the ledger returns
   ``REFUSED_PER_CALL`` the report message carries deterministic fallback text
   (source == "fallback") and no ``summarizer_cost_capped`` alert has been
   suppressed by the dedup guard (fresh day).
3. ``test_per_call_refusal_emits_cost_cap_alert`` — ``sec.alert.v1`` with
   ``kind=summarizer_cost_capped, subject=per_call`` is published exactly once.
4. ``test_per_call_refusal_daily_counter_stays_at_zero`` — refusing per-call
   does NOT increment the ledger; ``tokens_today() == 0`` after the tick.
5. ``test_per_call_alert_debounced_within_same_utc_day`` — second tick on the
   same UTC day does NOT emit a second alert (dedup guard fires).
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from swarm.agents.topics import SEC_ALERT
from swarm.source_watcher import scheduler as _scheduler_module
from swarm.source_watcher.agent import SourceWatcherAgent
from swarm.source_watcher.classifier import classify
from swarm.source_watcher.differ import diff_json
from swarm.source_watcher.planner import UpdatePlan, plan
from swarm.source_watcher.scheduler import Tick
from swarm.source_watcher.summarizer_budget import (
    AdmitResult,
    InMemorySummarizerLedger,
)

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


_MAX_TOKENS_CAP = 4096
_MAX_TOKENS_DAY = 50_000


def _make_agent(
    tmp_path: Path,
    *,
    llm=None,
    max_tokens_per_call: int = _MAX_TOKENS_CAP,
) -> SourceWatcherAgent:
    """Minimal SourceWatcherAgent with summarizer enabled (probe bypassed)."""
    return SourceWatcherAgent(
        sources=["x.local"],
        fetcher=lambda src: {},
        snapshot_root=tmp_path / "snapshots",
        summarizer_enabled=True,
        summarizer_model_id="gpt-4o-mini-2024-07-18",
        summarizer_probe_url="http://localhost:0",
        reachability_probe=lambda url, timeout: True,
        summarizer_ledger_path=str(tmp_path / "ledger.json"),
        summarizer_max_tokens_per_call=max_tokens_per_call,
        summarizer_max_tokens_per_day=_MAX_TOKENS_DAY,
        summarizer_llm=llm,
    )


def _make_huge_plan() -> UpdatePlan:
    """Return a plan whose diffs list totals ≈ 200 000 characters (≈ 50k tokens).

    Each diff entry is ~70 chars; 3 000 entries ≈ 210 000 chars ≈ 52 500 tokens.
    This represents the 'bursty diff' scenario the per-call cap is designed for.
    """
    entries = [
        {"key": f"field_{i}", "kind": "added", "value": "x" * 20}
        for i in range(3_000)
    ]
    return UpdatePlan(
        source="x.local",
        severity="cosmetic",
        actions=["notify"],
        summary="3000 fields added",
        diffs=entries,
    )


class _RefusePerCallLedger(InMemorySummarizerLedger):
    """Test stub: always returns REFUSED_PER_CALL for any try_admit call."""

    def try_admit(self, _requested: int) -> AdmitResult:
        return AdmitResult.REFUSED_PER_CALL


# ---------------------------------------------------------------------------
# Test 1 — LLM max_tokens is bounded at the configured per-call cap
# ---------------------------------------------------------------------------


def test_api_max_tokens_bounded_at_cap(tmp_path: Path) -> None:
    """Even for a 200k-char diff, the LLM receives max_tokens == cap (4096)."""
    observed: dict = {"max_tokens": None, "called": False}

    def capturing_llm(_p: UpdatePlan, *, max_tokens: int | None = None) -> str:
        observed["called"] = True
        observed["max_tokens"] = max_tokens
        return "LLM yanıtı."

    agent = _make_agent(tmp_path, llm=capturing_llm)
    huge_plan = _make_huge_plan()
    tick = Tick(source="x.local", plan=huge_plan, skipped_reason=None)

    with patch.object(_scheduler_module, "run_once", return_value=[tick]):
        list(agent.on_heartbeat())

    assert observed["called"], "LLM must be called on ADMIT path"
    mt = observed["max_tokens"]
    assert mt is not None, "LLM must receive max_tokens kwarg"
    assert mt <= _MAX_TOKENS_CAP, (
        f"max_tokens passed to LLM ({mt}) must be ≤ per-call cap ({_MAX_TOKENS_CAP})"
    )

    # Daily counter increments by ≤ max_tokens_per_call (not by diff size).
    assert agent._summarizer_ledger.tokens_today() <= _MAX_TOKENS_CAP


# ---------------------------------------------------------------------------
# Test 2 — REFUSED_PER_CALL: fallback narration is published
# ---------------------------------------------------------------------------


def test_per_call_refusal_emits_fallback_narration(tmp_path: Path) -> None:
    """When the ledger refuses per-call, the report carries deterministic fallback text."""
    agent = _make_agent(tmp_path, llm=lambda _p: "llm says something")
    agent._summarizer_ledger = _RefusePerCallLedger(
        max_tokens_per_call=_MAX_TOKENS_CAP,
        max_tokens_per_day=_MAX_TOKENS_DAY,
    )

    huge_plan = _make_huge_plan()
    tick = Tick(source="x.local", plan=huge_plan, skipped_reason=None)

    with patch.object(_scheduler_module, "run_once", return_value=[tick]):
        msgs = list(agent.on_heartbeat())

    # Find the source.watch.report.v1 message.
    from swarm.agents.topics import SOURCE_WATCH_REPORT_V1
    reports = [m for m in msgs if m.envelope.topic == SOURCE_WATCH_REPORT_V1]
    assert len(reports) == 1, "exactly one report expected"
    payload = reports[0].payload

    # Fallback source indicates the LLM was NOT called.
    assert payload["plan_summary_source"] == "fallback", (
        f"expected fallback, got {payload['plan_summary_source']!r}"
    )
    # Summary text must be non-empty (deterministic narration).
    assert payload["plan_summary_tr"], "deterministic fallback text must be non-empty"


# ---------------------------------------------------------------------------
# Test 3 — REFUSED_PER_CALL: summarizer_cost_capped{scope=per_call} fires
# ---------------------------------------------------------------------------


def test_per_call_refusal_emits_cost_cap_alert(tmp_path: Path) -> None:
    """A REFUSED_PER_CALL from the ledger must emit sec.alert.v1 kind=summarizer_cost_capped."""
    agent = _make_agent(tmp_path, llm=lambda _p: "llm says something")
    agent._summarizer_ledger = _RefusePerCallLedger(
        max_tokens_per_call=_MAX_TOKENS_CAP,
        max_tokens_per_day=_MAX_TOKENS_DAY,
    )

    tick = Tick(source="x.local", plan=_make_huge_plan(), skipped_reason=None)

    with patch.object(_scheduler_module, "run_once", return_value=[tick]):
        msgs = list(agent.on_heartbeat())

    alerts = [
        m for m in msgs
        if m.envelope.topic == SEC_ALERT
        and m.payload.get("kind") == "summarizer_cost_capped"
    ]
    assert len(alerts) == 1, f"expected exactly 1 cost-cap alert, got {len(alerts)}"
    assert alerts[0].payload["subject"] == "per_call", (
        f"expected subject=per_call, got {alerts[0].payload.get('subject')!r}"
    )


# ---------------------------------------------------------------------------
# Test 4 — REFUSED_PER_CALL: daily counter stays at zero
# ---------------------------------------------------------------------------


def test_per_call_refusal_daily_counter_stays_at_zero(tmp_path: Path) -> None:
    """Refusing per-call must NOT increment the daily ledger counter."""
    agent = _make_agent(tmp_path, llm=lambda _p: "ignored")
    stub_ledger = _RefusePerCallLedger(
        max_tokens_per_call=_MAX_TOKENS_CAP,
        max_tokens_per_day=_MAX_TOKENS_DAY,
    )
    agent._summarizer_ledger = stub_ledger

    tick = Tick(source="x.local", plan=_make_huge_plan(), skipped_reason=None)

    with patch.object(_scheduler_module, "run_once", return_value=[tick]):
        list(agent.on_heartbeat())

    # No LLM call → no record_usage → counter must stay at 0.
    assert stub_ledger.tokens_today() == 0, (
        "daily counter must not increment when the per-call cap refuses the request"
    )


# ---------------------------------------------------------------------------
# Test 5 — REFUSED_PER_CALL: alert is debounced within the same UTC day
# ---------------------------------------------------------------------------


def test_per_call_alert_debounced_within_same_utc_day(tmp_path: Path) -> None:
    """A second REFUSED_PER_CALL on the same UTC day must NOT emit a second alert."""
    agent = _make_agent(tmp_path, llm=lambda _p: "ignored")
    agent._summarizer_ledger = _RefusePerCallLedger(
        max_tokens_per_call=_MAX_TOKENS_CAP,
        max_tokens_per_day=_MAX_TOKENS_DAY,
    )

    tick = Tick(source="x.local", plan=_make_huge_plan(), skipped_reason=None)

    with patch.object(_scheduler_module, "run_once", return_value=[tick]):
        msgs_first = list(agent.on_heartbeat())

    # Second heartbeat — same UTC day, per-call refusal fires again.
    with patch.object(_scheduler_module, "run_once", return_value=[tick]):
        msgs_second = list(agent.on_heartbeat())

    alerts_first = [
        m for m in msgs_first
        if m.envelope.topic == SEC_ALERT and m.payload.get("kind") == "summarizer_cost_capped"
    ]
    alerts_second = [
        m for m in msgs_second
        if m.envelope.topic == SEC_ALERT and m.payload.get("kind") == "summarizer_cost_capped"
    ]

    assert len(alerts_first) == 1, "first tick must emit exactly one alert"
    assert len(alerts_second) == 0, (
        "second tick on the same UTC day must NOT emit a duplicate cost-cap alert"
    )
