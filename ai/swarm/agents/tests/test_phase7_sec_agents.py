"""Phase 7 — focused smoke tests for the three defense agents.

These exercise the bus contracts of ``sec.input.v1``, ``sec.scrape.v1``,
and ``sec.rate.v1`` with deterministic clocks and no I/O. The
broader open-enum / boundary-discipline tests cover wire-shape;
this file covers behaviour.
"""
from __future__ import annotations

import base64
import time
from typing import Iterator

import pytest

from swarm.agents.payloads import (
    DenylistEvent,
    MaintEvent,
    QaRequest,
    QaRequestV1,
    ScrapeRaw,
    SecAlert,
)
from swarm.agents.sec import SecInputAgent, SecRateAgent, SecScrapeAgent
from swarm.agents.sec._alert import SecAlertDebouncer
from swarm.agents.topics import (
    MAINT_EVENT,
    PROOF_FLAG,
    QA_REQUEST,
    QA_REQUEST_V1,
    SCRAPE_RAW,
    SEC_ALERT,
    SEC_DENYLIST,
    SEC_QUARANTINE,
)
from swarm.sdk.types import Message


# ── Test helpers ──────────────────────────────────────────────────


class _FakeClock:
    def __init__(self) -> None:
        self.t = 1000.0

    def mono(self) -> float:
        return self.t

    def iso(self) -> str:
        return "2025-01-01T00:00:00+00:00"

    def advance(self, dt: float) -> None:
        self.t += dt


def _ids() -> Iterator[str]:
    n = 0
    while True:
        n += 1
        yield f"id-{n:06d}"


def _next_id_factory():
    g = _ids()
    return lambda: next(g)


def _msg(topic: str, payload: dict, *, producer: str = "test") -> Message:
    return Message.new(topic, payload, producer=producer)


# ── SecAlertDebouncer ─────────────────────────────────────────────


def test_debouncer_collapses_duplicates_and_counts_suppressions() -> None:
    clock = _FakeClock()
    deb = SecAlertDebouncer(ttl_s=60, clock=clock.mono)
    d1 = deb.decide(kind="rate_burst", subject="ip:1", severity="warn", reason="x")
    d2 = deb.decide(kind="rate_burst", subject="ip:1", severity="warn", reason="x")
    d3 = deb.decide(kind="rate_burst", subject="ip:1", severity="warn", reason="x")
    assert d1.emit and not d2.emit and not d3.emit
    clock.advance(61.0)
    d4 = deb.decide(kind="rate_burst", subject="ip:1", severity="warn", reason="x")
    assert d4.emit
    # Suppressed count is recorded against the bucket that fired.
    assert d4.suppressed_count >= 2


def test_debouncer_critical_bypass_default_on() -> None:
    deb = SecAlertDebouncer(ttl_s=60, critical_bypass=True)
    a = deb.decide(kind="prompt_injection", subject="x", severity="critical", reason="r")
    b = deb.decide(kind="prompt_injection", subject="x", severity="critical", reason="r")
    assert a.emit and b.emit


def test_debouncer_zero_ttl_disables() -> None:
    deb = SecAlertDebouncer(ttl_s=0)
    for _ in range(5):
        assert deb.decide(kind="x", subject="s", severity="info", reason="r").emit


# ── SecInputAgent ─────────────────────────────────────────────────


def _input_agent(clock: _FakeClock) -> SecInputAgent:
    return SecInputAgent(
        debouncer=SecAlertDebouncer(ttl_s=60, clock=clock.mono),
        clock_iso=clock.iso,
        new_id=_next_id_factory(),
    )


def test_sec_input_pass_path_emits_qa_request_v1_and_warn_alert() -> None:
    clock = _FakeClock()
    agent = _input_agent(clock)
    req = QaRequest(
        request_id="r-1",
        raw_text="merhaba",
        ip="1.2.3.4",
        locale="tr",
        client_id="c-7",
    )
    out = list(agent.handle(_msg(QA_REQUEST, req.as_dict())))
    topics = [m.envelope.topic for m in out]
    # v1 fallback (no classifier on disk) -> degraded warn alert.
    assert QA_REQUEST_V1 in topics
    assert SEC_ALERT in topics
    v1 = next(m for m in out if m.envelope.topic == QA_REQUEST_V1)
    parsed = QaRequestV1.from_dict(v1.payload)
    assert parsed.sec_verdict == "sanitized"
    assert "nfc" in parsed.sec_steps_run


def test_sec_input_idempotent_on_redelivery() -> None:
    clock = _FakeClock()
    agent = _input_agent(clock)
    req = QaRequest(request_id="dup-1", raw_text="hi", ip="1.2.3.4")
    first = list(agent.handle(_msg(QA_REQUEST, req.as_dict())))
    second = list(agent.handle(_msg(QA_REQUEST, req.as_dict())))
    assert first  # first delivery emits
    assert second == []  # redelivery is a no-op


# ── SecScrapeAgent ────────────────────────────────────────────────


def _scrape_agent(clock: _FakeClock, *, warmup: int = 2) -> SecScrapeAgent:
    # Use very short warmup so tests don't need to push 50 samples.
    import common.config as _cfg_mod
    _cfg_mod.cfg.sec_scrape_warmup_samples = warmup
    return SecScrapeAgent(
        debouncer=SecAlertDebouncer(ttl_s=60, clock=clock.mono),
        clock_iso=clock.iso,
        new_id=_next_id_factory(),
    )


def _scrape_msg(body: bytes, *, source: str = "mackolik", status: int = 200, ctype: str = "text/html") -> Message:
    raw = ScrapeRaw(
        source=source,
        target=f"https://{source}.local/x",
        bytes_sha256="sha-" + str(hash(body))[-12:],
        http_status=status,
        content_type=ctype,
        bytes_b64=base64.b64encode(body).decode(),
    )
    return _msg(SCRAPE_RAW, raw.as_dict())


def test_sec_scrape_skips_non_200() -> None:
    clock = _FakeClock()
    agent = _scrape_agent(clock)
    out = list(agent.handle(_scrape_msg(b"<html></html>", status=503)))
    assert out == []


def test_sec_scrape_warmup_then_size_delta_alert() -> None:
    clock = _FakeClock()
    agent = _scrape_agent(clock, warmup=2)
    # Two warmup samples with distinct bytes so dedup doesn't drop
    # the second one.
    body1 = b"<html><body>" + b"<div class='m'>x</div>" * 50 + b"</body></html>"
    body2 = b"<html><body>" + b"<div class='m'>y</div>" * 50 + b"</body></html>"
    list(agent.handle(_scrape_msg(body1)))
    list(agent.handle(_scrape_msg(body2)))
    # Now warmed. A 100x larger body should trip dom_size_delta.
    big = b"<html><body>" + b"<div class='m'>z</div>" * 5000 + b"</body></html>"
    out3 = list(agent.handle(_scrape_msg(big)))
    kinds = [SecAlert.from_dict(m.payload).kind for m in out3 if m.envelope.topic == SEC_ALERT]
    assert "dom_size_delta" in kinds


def test_sec_scrape_baseline_reset_via_maint_event() -> None:
    clock = _FakeClock()
    agent = _scrape_agent(clock, warmup=1)
    list(agent.handle(_scrape_msg(b"<html></html>")))
    assert agent.baseline_size("mackolik") == 1
    event = MaintEvent(
        kind="baseline_reset",
        target="mackolik",
        reason="manual_override",
        produced_at=clock.iso(),
    )
    out = list(agent.handle(_msg(MAINT_EVENT, event.as_dict())))
    assert agent.baseline_size("mackolik") == 0
    kinds = [SecAlert.from_dict(m.payload).kind for m in out if m.envelope.topic == SEC_ALERT]
    assert "baseline_reset" in kinds


def test_sec_scrape_dom_drift_emits_proof_flag() -> None:
    clock = _FakeClock()
    agent = _scrape_agent(clock, warmup=1)
    # Warm with a structurally-uniform page.
    warm = b"<html><body>" + b"<div class='a'></div>" * 30 + b"</body></html>"
    list(agent.handle(_scrape_msg(warm)))
    # A radically different DOM shape should trip the SimHash threshold.
    drift = b"<html><body>" + b"<span id='x'></span><a href='/y'></a><p></p>" * 30 + b"</body></html>"
    out = list(agent.handle(_scrape_msg(drift)))
    topics = [m.envelope.topic for m in out]
    assert PROOF_FLAG in topics


# ── SecRateAgent ──────────────────────────────────────────────────


def _rate_agent(clock: _FakeClock) -> SecRateAgent:
    import common.config as _cfg_mod
    _cfg_mod.cfg.sec_burst_threshold = 3
    _cfg_mod.cfg.sec_burst_window_ms = 60_000
    return SecRateAgent(
        debouncer=SecAlertDebouncer(ttl_s=60, clock=clock.mono),
        clock_iso=clock.iso,
        clock_mono=clock.mono,
        new_id=_next_id_factory(),
    )


def _alert_msg(*, alert_id: str, kind: str = "rate_throttled", subject: str = "ip:9.9.9.9") -> Message:
    a = SecAlert(
        alert_id=alert_id,
        kind=kind,
        severity="warn",
        source="sec.input.v1",
        reason="r",
        produced_at="2025-01-01T00:00:00+00:00",
        subject=subject,
    )
    return _msg(SEC_ALERT, a.as_dict())


def test_sec_rate_trips_after_threshold_and_emits_denylist_add() -> None:
    clock = _FakeClock()
    agent = _rate_agent(clock)
    # First two are below threshold (=3) → no denylist event.
    for i in range(2):
        out = list(agent.handle(_alert_msg(alert_id=f"a-{i}")))
        topics = [m.envelope.topic for m in out]
        assert SEC_DENYLIST not in topics
    # Third trip fires.
    out = list(agent.handle(_alert_msg(alert_id="a-2")))
    denylist = [m for m in out if m.envelope.topic == SEC_DENYLIST]
    assert len(denylist) == 1
    parsed = DenylistEvent.from_dict(denylist[0].payload)
    assert parsed.action == "add"
    assert parsed.subject == "ip:9.9.9.9"
    assert parsed.ttl_s > 0


def test_sec_rate_does_not_loop_on_own_alerts() -> None:
    clock = _FakeClock()
    agent = _rate_agent(clock)
    own = SecAlert(
        alert_id="own-1",
        kind="rate_burst",
        severity="error",
        source="sec.rate.v1",  # OWN source → must be ignored
        reason="r",
        produced_at="2025-01-01T00:00:00+00:00",
        subject="ip:1.1.1.1",
    )
    out = list(agent.handle(_msg(SEC_ALERT, own.as_dict())))
    assert out == []
    assert agent.subject_count() == 0


def test_sec_rate_dedup_on_redelivered_alerts() -> None:
    clock = _FakeClock()
    agent = _rate_agent(clock)
    # Same alert_id sent 5 times — should count exactly once.
    for _ in range(5):
        list(agent.handle(_alert_msg(alert_id="dup")))
    # Need 3 unique to trip; only one was unique.
    assert not agent.is_denylisted("ip:9.9.9.9")


def test_sec_rate_denylist_clear_emits_remove() -> None:
    clock = _FakeClock()
    agent = _rate_agent(clock)
    # Trip first.
    for i in range(3):
        list(agent.handle(_alert_msg(alert_id=f"a-{i}")))
    assert agent.is_denylisted("ip:9.9.9.9")
    event = MaintEvent(
        kind="denylist_clear",
        target="ip:9.9.9.9",
        reason="manual_override",
        produced_at=clock.iso(),
    )
    out = list(agent.handle(_msg(MAINT_EVENT, event.as_dict())))
    removes = [
        DenylistEvent.from_dict(m.payload)
        for m in out if m.envelope.topic == SEC_DENYLIST
    ]
    assert len(removes) == 1
    assert removes[0].action == "remove"
    assert removes[0].ttl_s == 0


def test_sec_rate_rejects_wildcard_denylist_clear() -> None:
    clock = _FakeClock()
    agent = _rate_agent(clock)
    event = MaintEvent(
        kind="denylist_clear",
        target="*",
        reason="manual_override",
        produced_at=clock.iso(),
    )
    out = list(agent.handle(_msg(MAINT_EVENT, event.as_dict())))
    assert out == []  # no audit event for a rejected wildcard


# ── Audit pass (post-implementation) regression tests ─────────────


def test_sec_input_oversize_payload_is_quarantined_not_passed() -> None:
    """Defense-in-depth: the Go gateway enforces `sec_input_max_len`
    on the request boundary, but the agent must independently reject
    oversize payloads. A bypass (misbehaving internal client publishing
    directly to `qa.request`) must NOT silently feed an oversized
    body to the classifier — that would widen the attack surface.
    Oversize → quarantine with kind=`payload_oversize`, never `pass`.
    """
    import common.config as _cfg_mod
    _cfg_mod.cfg.sec_input_max_len = 16
    clock = _FakeClock()
    agent = _input_agent(clock)
    # 17 bytes when UTF-8 encoded — one over the cap.
    req = QaRequest(request_id="big-1", raw_text="x" * 17, ip="1.2.3.4")
    out = list(agent.handle(_msg(QA_REQUEST, req.as_dict())))
    topics = [m.envelope.topic for m in out]
    assert SEC_QUARANTINE in topics, (
        "oversize payload must produce a quarantine envelope; "
        "the pass path is forbidden defense-in-depth"
    )
    assert QA_REQUEST_V1 not in topics, (
        "oversize payload must NOT reach NLP via qa.request.v1"
    )
    alerts = [SecAlert.from_dict(m.payload) for m in out if m.envelope.topic == SEC_ALERT]
    kinds = [a.kind for a in alerts]
    assert "payload_oversize" in kinds


def test_sec_input_oversize_uses_byte_length_not_codepoint_count() -> None:
    """§7.1 byte-semantics binding: the cap is bytes after UTF-8
    encoding, not codepoints. A 5-codepoint Turkish string with
    multibyte glyphs ("ğüşıö" = 10 bytes) trips a cap of 8."""
    import common.config as _cfg_mod
    _cfg_mod.cfg.sec_input_max_len = 8
    clock = _FakeClock()
    agent = _input_agent(clock)
    req = QaRequest(request_id="utf-1", raw_text="ğüşıö", ip="1.2.3.4")
    assert len("ğüşıö".encode("utf-8")) == 10  # sanity
    out = list(agent.handle(_msg(QA_REQUEST, req.as_dict())))
    topics = [m.envelope.topic for m in out]
    assert SEC_QUARANTINE in topics
    assert QA_REQUEST_V1 not in topics


def test_sec_scrape_dedup_is_per_source_not_global() -> None:
    """Audit fix: byte-identical content from two distinct sources
    (mocksrv replays the same seed across vhosts; openfootball mirrors
    tff fixtures) must each update its own per-source baseline.
    Globally-keyed dedup would silently drop the second source's
    samples and starve its baseline."""
    clock = _FakeClock()
    agent = _scrape_agent(clock, warmup=1)
    same_body = b"<html><body><div>identical</div></body></html>"
    list(agent.handle(_scrape_msg(same_body, source="mackolik")))
    list(agent.handle(_scrape_msg(same_body, source="nesine")))
    # Both sources must have observed exactly one sample.
    assert agent.baseline_size("mackolik") == 1
    assert agent.baseline_size("nesine") == 1


def test_sec_scrape_dedup_still_drops_intra_source_replay() -> None:
    """The dedup fix must not weaken intra-source dedup — replaying
    the same payload through the same source still counts once."""
    clock = _FakeClock()
    agent = _scrape_agent(clock, warmup=1)
    body = b"<html><body><span>x</span></body></html>"
    list(agent.handle(_scrape_msg(body, source="mackolik")))
    list(agent.handle(_scrape_msg(body, source="mackolik")))  # replay
    assert agent.baseline_size("mackolik") == 1
