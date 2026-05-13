"""SDK-harness tests for the periodic source-watcher scheduler."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from ai.swarm.agents.topics import MAINT_EVENT, SEC_ALERT, SOURCE_WATCH_REPORT_V1
from ai.swarm.sdk.bus import InMemoryBus
from ai.swarm.sdk.registry import AgentRegistry
from ai.swarm.sdk.runner import AgentRunner
from ai.swarm.source_watcher import scheduler
from ai.swarm.source_watcher.agent import SourceWatcherAgent


FIXTURES = Path(__file__).parent / "fixtures"


class FakeClock:
    def __init__(self, start: float = 0.0) -> None:
        self.now = start

    def monotonic(self) -> float:
        return self.now


@pytest.fixture
def history_root(tmp_path: Path) -> Path:
    return tmp_path / "history"


def _make_runner(
    history_root: Path,
    *,
    sources: List[str],
    fetcher,
    clock: FakeClock | None = None,
    agent_kwargs: Dict[str, Any] | None = None,
) -> tuple[InMemoryBus, AgentRunner]:
    bus = InMemoryBus()
    kwargs: Dict[str, Any] = dict(agent_kwargs or {})
    runner = AgentRunner(
        agent=SourceWatcherAgent(
            sources=sources,
            fetcher=fetcher,
            snapshot_root=history_root,
            **kwargs,
        ),
        bus=bus,
        registry=AgentRegistry(),
        heartbeat_sec=0,
        pending_claim_sec=3600,
        clock=clock or FakeClock(),
    )
    runner.register()
    return bus, runner


def _drain_reports(bus: InMemoryBus) -> List[Dict[str, Any]]:
    return [msg.payload for msg in bus.drain_topic(SOURCE_WATCH_REPORT_V1)]


def test_run_once_first_pass_skips_with_first_snapshot_reason(history_root: Path) -> None:
    bus, runner = _make_runner(
        history_root,
        sources=["mackolik"],
        fetcher=lambda src: {"v": 1},
    )

    assert runner.step() is True

    reports = _drain_reports(bus)
    assert len(reports) == 1
    assert reports[0]["plan"] is None
    assert reports[0]["skipped_reason"] == "first_snapshot"


def test_run_once_unchanged_skips(history_root: Path) -> None:
    bus, runner = _make_runner(
        history_root,
        sources=["nesine"],
        fetcher=lambda src: {"v": 1},
    )

    runner.step()
    _drain_reports(bus)

    assert runner.step() is True
    reports = _drain_reports(bus)
    assert reports[0]["skipped_reason"] == "unchanged"
    assert reports[0]["plan"] is None


def test_run_once_changed_produces_plan(history_root: Path) -> None:
    state: Dict[str, Any] = {"v": 1}
    bus, runner = _make_runner(
        history_root,
        sources=["tff"],
        fetcher=lambda src: dict(state),
    )

    runner.step()
    _drain_reports(bus)
    state["v"] = 2  # mutate; differ should fire
    assert runner.step() is True

    reports = _drain_reports(bus)
    assert reports[0]["plan"] is not None
    assert reports[0]["plan"]["source"] == "tff"
    assert reports[0]["plan"]["severity"] == "semantic"


def test_loop_runs_n_iterations_and_uses_fake_sleep(history_root: Path) -> None:
    sleeps: List[float] = []
    counter = {"n": 0}

    def fetcher(_src: str) -> Dict[str, int]:
        counter["n"] += 1
        return {"v": counter["n"]}

    history = scheduler.loop(
        ["x"],
        fetcher=fetcher,
        interval_s=5.0,
        iterations=3,
        sleep=sleeps.append,
        snapshot_root=history_root,
    )
    assert len(history) == 3
    # Three iterations → at most two sleeps between them (last one skipped).
    assert sleeps == [5.0, 5.0]


def test_loop_rejects_zero_interval(history_root: Path) -> None:
    with pytest.raises(ValueError):
        scheduler.loop(
            ["a"],
            fetcher=lambda s: {},
            interval_s=0.0,
            iterations=1,
            sleep=lambda _s: None,
            snapshot_root=history_root,
        )


def test_loop_invokes_on_tick_callback(history_root: Path) -> None:
    received: List[int] = []
    scheduler.loop(
        ["a"],
        fetcher=lambda s: {},
        interval_s=1.0,
        iterations=2,
        sleep=lambda _s: None,
        snapshot_root=history_root,
        on_tick=lambda ticks: received.append(len(ticks)),
    )
    assert received == [1, 1]


def test_runner_heartbeat_emits_schema_drift_event_for_breaking_plan(history_root: Path) -> None:
    baseline = {
        "teams": ["A", "B"],
        "score": {"ft": [1, 0]},
    }
    state = {"payload": baseline}
    bus, runner = _make_runner(
        history_root,
        sources=["openfootball.local"],
        fetcher=lambda src: json.loads(json.dumps(state["payload"])),
    )

    runner.step()
    _drain_reports(bus)
    bus.drain_topic(MAINT_EVENT)

    state["payload"] = {
        "score": {"ft": "1-0"},
    }
    assert runner.step() is True

    reports = _drain_reports(bus)
    maint = bus.drain_topic(MAINT_EVENT)
    assert reports[0]["plan"]["severity"] == "schema_breaking"
    assert len(maint) == 1
    assert maint[0].payload["kind"] == "baseline_reset"
    assert maint[0].payload["target"] == "openfootball.local"


def test_classification_is_byte_identical_pre_and_post_sdk_migration(history_root: Path) -> None:
    golden_bytes = (FIXTURES / "sdk_migration_golden_classification.json").read_text(encoding="utf-8")
    baseline = {
        "name": "Turkish Süper Lig 2024-25",
        "rounds": [
            {
                "matchday": 1,
                "matches": [
                    {"home": "Galatasaray", "away": "Fenerbahçe", "score": {"ft": [2, 1]}},
                ],
            },
        ],
        "teams": [{"id": "GS", "name": "Galatasaray"}],
    }
    mutated = {
        "name": "Turkish Süper Lig 2024-25",
        "rounds": [
            {
                "matchday": 1,
                "matches": [
                    {"home": "Galatasaray", "away": "Fenerbahçe", "score": {"ft": "2-1"}},
                ],
            },
        ],
    }
    state = {"payload": baseline}
    bus, runner = _make_runner(
        history_root,
        sources=["openfootball.local"],
        fetcher=lambda src: json.loads(json.dumps(state["payload"])),
    )

    runner.step()
    _drain_reports(bus)

    state["payload"] = mutated
    runner.step()
    sdk_report = _drain_reports(bus)[0]

    pre_ticks = scheduler.run_once(
        ["legacy.local"],
        fetcher=lambda src: baseline,
        snapshot_root=history_root / "legacy",
    )
    assert pre_ticks[0].skipped_reason == "first_snapshot"
    legacy_ticks = scheduler.run_once(
        ["legacy.local"],
        fetcher=lambda src: mutated,
        snapshot_root=history_root / "legacy",
    )
    legacy_plan = legacy_ticks[0].plan
    assert legacy_plan is not None

    legacy_bytes = json.dumps(legacy_plan.diffs, sort_keys=True, indent=2, ensure_ascii=True)
    sdk_bytes = json.dumps(sdk_report["classification"], sort_keys=True, indent=2, ensure_ascii=True)
    assert legacy_bytes == golden_bytes
    assert sdk_bytes == golden_bytes


def test_summarizer_probe_failure_disables_runtime_and_emits_warn_alert(history_root: Path) -> None:
    state: Dict[str, Any] = {"v": 1}
    bus, runner = _make_runner(
        history_root,
        sources=["mackolik"],
        fetcher=lambda src: dict(state),
        agent_kwargs={
            "summarizer_enabled": True,
            "summarizer_model_id": "gpt-4.1-mini-2026-04-14",
            "summarizer_probe_url": "https://summarizer.local/health",
            "summarizer_probe_timeout_sec": 0.25,
            "reachability_probe": lambda _u, _t: False,
            "summarizer_llm": lambda _p: "LLM cevap",
        },
    )

    # First heartbeat creates baseline and emits one startup warning.
    assert runner.step() is True
    alerts = bus.drain_topic(SEC_ALERT)
    _drain_reports(bus)
    assert len(alerts) == 1
    assert alerts[0].payload["kind"] == "summarizer_unreachable"
    assert alerts[0].payload["severity"] == "warn"

    # Non-empty plan on next heartbeat should stay fallback (runtime override).
    state["v"] = 2
    assert runner.step() is True
    reports = _drain_reports(bus)
    assert reports[0]["plan"] is not None
    assert reports[0]["plan_summary_source"] == "disabled"
    assert reports[0]["plan_summary_tr"]


def test_summarizer_runs_only_for_non_empty_plans(history_root: Path) -> None:
    state: Dict[str, Any] = {"v": 1}

    def llm(_plan):
        return "Özet hazır"

    bus, runner = _make_runner(
        history_root,
        sources=["tff"],
        fetcher=lambda src: dict(state),
        agent_kwargs={
            "summarizer_enabled": True,
            "summarizer_model_id": "gpt-4.1-mini-2026-04-14",
            "summarizer_probe_url": "https://summarizer.local/health",
            "reachability_probe": lambda _u, _t: True,
            "summarizer_llm": llm,
        },
    )

    # First snapshot -> no plan and no narration.
    assert runner.step() is True
    first = _drain_reports(bus)[0]
    assert first["plan"] is None
    assert first["plan_summary_tr"] is None
    assert first["plan_summary_source"] == "disabled"

    # Unchanged -> still no plan and no narration call path.
    assert runner.step() is True
    second = _drain_reports(bus)[0]
    assert second["plan"] is None
    assert second["plan_summary_tr"] is None
    assert second["plan_summary_source"] == "disabled"

    # Changed payload -> non-empty UpdatePlan, narration allowed.
    state["v"] = 3
    assert runner.step() is True
    third = _drain_reports(bus)[0]
    assert third["plan"] is not None
    assert third["classification"]
    assert third["plan_summary_source"] == "llm"
    assert third["plan_summary_tr"] == "Özet hazır"


def test_summarizer_daily_cost_cap_falls_back_and_debounces_alert(history_root: Path) -> None:
    state: Dict[str, Any] = {"v": 1}
    ledger_path = history_root / "maint" / "summarizer_ledger.json"

    def llm(_plan, *, max_tokens=None):
        return f"Özet hazır ({max_tokens})"

    bus, runner = _make_runner(
        history_root,
        sources=["tff"],
        fetcher=lambda src: dict(state),
        agent_kwargs={
            "summarizer_enabled": True,
            "summarizer_model_id": "gpt-4.1-mini-2026-04-14",
            "summarizer_probe_url": "https://summarizer.local/health",
            "reachability_probe": lambda _u, _t: True,
            "summarizer_llm": llm,
            "summarizer_max_tokens_per_call": 1000,
            "summarizer_max_tokens_per_day": 1500,
            "summarizer_ledger_path": str(ledger_path),
        },
    )

    # Baseline snapshot.
    assert runner.step() is True
    _drain_reports(bus)
    assert bus.drain_topic(SEC_ALERT) == []

    # First non-empty plan consumes 1000 tokens and uses llm narration.
    state["v"] = 2
    assert runner.step() is True
    first = _drain_reports(bus)[0]
    assert first["plan_summary_source"] == "llm"
    assert bus.drain_topic(SEC_ALERT) == []

    # Second plan would exceed the day cap (1000 + 1000 > 1500).
    state["v"] = 3
    assert runner.step() is True
    second = _drain_reports(bus)[0]
    alerts = bus.drain_topic(SEC_ALERT)
    assert second["plan_summary_source"] == "fallback"
    assert len(alerts) == 1
    assert alerts[0].payload["kind"] == "summarizer_cost_capped"
    assert alerts[0].payload["subject"] == "per_day"

    # Repeated cap hit in the same UTC day does not spam alerts.
    state["v"] = 4
    assert runner.step() is True
    third = _drain_reports(bus)[0]
    assert third["plan_summary_source"] == "fallback"
    assert bus.drain_topic(SEC_ALERT) == []
