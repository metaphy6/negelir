from __future__ import annotations

from pathlib import Path
import json
import pytest

from ai.common.config import cfg
from common.security.patterns import detect_pii
from nlp.streaming import build_guarded_streaming_plan
from ai.swarm.agents.nlp import NlpAnswerAgent
from ai.swarm.agents.topics import PREDICT_CANCEL_V1
from ai.swarm.sdk.types import Message


def test_guarded_streaming_plan_skeleton_then_polish_includes_citation_only_at_end(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cfg, "nlp_answer_streaming", "guarded")
    answer_text = "Bu bir taslaktır.\n---\nKaynak bilgisi"

    plan = build_guarded_streaming_plan(
        answer_text,
        cfg=cfg,
        humanizer=lambda body, cfg: body + " POLISHED",
        cancel_token=lambda: False,
        write_chunk=lambda chunk: None,
    )

    assert plan.citation_block == "Kaynak bilgisi"
    assert all("Kaynak bilgisi" not in chunk for chunk in plan.skeleton_chunks)
    assert plan.final_answer.endswith("---\nKaynak bilgisi")
    assert plan.humanizer_used
    assert not plan.canceled
    assert not plan.write_timed_out


def test_guarded_streaming_plan_citation_never_in_streaming_chunk(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cfg, "nlp_answer_streaming", "guarded")
    answer_text = "İçerik burada.\n---\nKaynak"

    plan = build_guarded_streaming_plan(
        answer_text,
        cfg=cfg,
        humanizer=lambda body, cfg: body,
        cancel_token=lambda: False,
        write_chunk=lambda chunk: None,
    )

    assert any(chunk for chunk in plan.skeleton_chunks)
    assert plan.citation_block == "Kaynak"
    assert all("---" not in chunk for chunk in plan.skeleton_chunks)
    assert all("Kaynak" not in chunk for chunk in plan.skeleton_chunks)


def test_nlp_streaming_chunk_blocked_on_pii(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cfg, "nlp_answer_streaming", "guarded")
    answer_text = "Bu bir taslak 0555 123 4567.\n---\nKaynak"

    def chunk_proofread_fn(chunk: str) -> str | None:
        return "pii_redacted" if detect_pii(chunk) else None

    plan = build_guarded_streaming_plan(
        answer_text,
        cfg=cfg,
        humanizer=lambda body, cfg: body + " POLISHED",
        cancel_token=lambda: False,
        write_chunk=lambda chunk: None,
        chunk_proofread_fn=chunk_proofread_fn,
    )

    assert plan.chunk_blocked_reason == "pii_redacted"
    assert not plan.humanizer_used
    assert plan.final_answer == "Bu bir taslak 0555 123 4567.\n---\nKaynak"


def test_guarded_streaming_plan_backpressure_falls_back_to_skeleton(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cfg, "nlp_answer_streaming", "guarded")
    answer_text = "Streamed içerik.\n---\nKaynak"

    def slow_write(chunk: str) -> None:
        raise TimeoutError("write blocked")

    plan = build_guarded_streaming_plan(
        answer_text,
        cfg=cfg,
        humanizer=lambda body, cfg: body + " POLISHED",
        cancel_token=lambda: False,
        write_chunk=slow_write,
    )

    assert not plan.humanizer_used
    assert plan.write_timed_out
    assert plan.final_answer == "Streamed içerik." + "\n---\nKaynak"


def test_guarded_streaming_plan_cancel_before_polish_returns_skeleton_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cfg, "nlp_answer_streaming", "guarded")
    answer_text = "Streamed içerik.\n---\nKaynak"
    cancelled = True

    plan = build_guarded_streaming_plan(
        answer_text,
        cfg=cfg,
        humanizer=lambda body, cfg: body + " POLISHED",
        cancel_token=lambda: cancelled,
        write_chunk=lambda chunk: None,
    )

    assert not plan.humanizer_used
    assert plan.canceled
    assert plan.final_answer == "Streamed içerik." + "\n---\nKaynak"


def test_nlp_streaming_disabled_mode_falls_through_to_oneshot() -> None:
    answer_text = "İçerik burada.\n---\nKaynak"

    plan = build_guarded_streaming_plan(
        answer_text,
        cfg=cfg,
        humanizer=lambda body, cfg: body + " POLISHED",
        cancel_token=lambda: False,
        write_chunk=lambda chunk: None,
    )

    assert not plan.humanizer_used
    assert plan.final_answer == answer_text


def test_nlp_cached_answer_never_re_streamed() -> None:
    root = Path(__file__).resolve().parents[1] / "swarm" / "agents"
    allowed = {root / "cache.py"}

    for path in sorted(root.rglob("*.py")):
        if path in allowed:
            continue
        source = path.read_text(encoding="utf-8")
        assert "streaming_chunks" not in source, (
            f"Unexpected streaming_chunks reference in {path}. Cached answers must be served one-shot."
        )


def test_nlp_streaming_honors_predict_cancel() -> None:
    agent = NlpAnswerAgent()
    msg = Message.new(
        topic=PREDICT_CANCEL_V1,
        payload={"request_id": "req-cancel"},
        producer="api.gateway.v1",
    )

    result = list(agent.handle(msg))

    assert result == []
    assert agent.is_request_cancelled("req-cancel")
