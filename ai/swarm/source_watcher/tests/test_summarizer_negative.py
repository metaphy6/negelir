"""Negative tests for the optional LLM summarizer.

Guarantees from AGENTS.md §5 + ROADMAP §2.8.3 / §2.8.4:
  * Summarizer is opt-in (``enabled=False`` by default).
  * A failing LLM callable NEVER raises out of ``summarize``.
  * The plan's ``severity`` and ``actions`` are identical with or
    without the summarizer — it can only *narrate*.
"""

from __future__ import annotations

import pytest

from ai.swarm.source_watcher.classifier import SCHEMA_BREAKING, classify
from ai.swarm.source_watcher.differ import diff_json
from ai.swarm.source_watcher.planner import plan
from ai.swarm.source_watcher.summarizer import summarize


def _make_breaking_plan():
    before = {"a": 1, "b": 2}
    after = {"a": "1"}              # type flip + 'b' removed
    classified = classify(diff_json(before, after))
    return plan("x.local", classified), classified


def test_summarize_disabled_returns_fallback_text() -> None:
    up, _ = _make_breaking_plan()
    result = summarize(up, enabled=False)
    assert result.source == "disabled"
    assert "x.local" in result.text
    assert any(a in result.text for a in up.actions)


def test_summarize_enabled_without_llm_uses_fallback() -> None:
    up, _ = _make_breaking_plan()
    result = summarize(up, enabled=True, llm=None)
    assert result.source == "fallback"
    assert result.text


def test_summarize_llm_network_error_does_not_propagate() -> None:
    up, _ = _make_breaking_plan()

    def broken_llm(plan_in):
        raise ConnectionError("endpoint unreachable")

    result = summarize(up, enabled=True, llm=broken_llm)
    assert result.source == "fallback", (
        "LLM failures must degrade to deterministic fallback, never raise"
    )
    assert result.text


def test_summarize_llm_timeout_does_not_propagate() -> None:
    up, _ = _make_breaking_plan()

    def slow_llm(plan_in):
        raise TimeoutError("gateway timeout")

    result = summarize(up, enabled=True, llm=slow_llm)
    assert result.source == "fallback"


def test_summarize_never_mutates_plan() -> None:
    """Contract: LLM narration cannot change severity or actions."""
    up, _ = _make_breaking_plan()
    severity_before = up.severity
    actions_before = list(up.actions)

    def naughty_llm(plan_in):
        # Even if the LLM were to return garbage claiming different actions,
        # summarize() must only produce a text string — the plan object
        # itself is immutable and still decides the actions.
        return "LLM claims: just skip it"

    result = summarize(up, enabled=True, llm=naughty_llm)
    assert result.source == "llm"
    assert result.text == "LLM claims: just skip it"
    # Plan unchanged.
    assert up.severity == severity_before == SCHEMA_BREAKING
    assert list(up.actions) == actions_before


def test_summarize_empty_llm_response_falls_back() -> None:
    up, _ = _make_breaking_plan()
    result = summarize(up, enabled=True, llm=lambda p: "")
    assert result.source == "fallback"
    assert result.text


def test_summarize_passes_max_tokens_when_llm_accepts_keyword() -> None:
    up, _ = _make_breaking_plan()
    observed = {"max_tokens": None}

    def capped_llm(_plan, *, max_tokens=None):
        observed["max_tokens"] = max_tokens
        return "Özet hazır"

    result = summarize(up, enabled=True, llm=capped_llm, max_tokens=321)
    assert result.source == "llm"
    assert observed["max_tokens"] == 321
