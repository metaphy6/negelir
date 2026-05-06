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


def test_sec_scrape_simhash_ring_tolerates_legit_ab_test() -> None:
    """F7.4 (P4): a site that legitimately A/B-tests two distinct
    DOM layouts must NOT spam ``proof.flag`` on every flip after
    both layouts are in the ring.

    Pre-F7.4 the SimHash drift check compared each sample to the
    most-recent fingerprint only — so an A,B,A,B,A,B sequence with
    Hamming(A,B) > threshold would emit a flag on every transition.

    Post-fix: the per-source ring (default size 8) holds recent
    fingerprints. With warmup=2, samples 1+2 (A, B) seed the ring;
    samples 3-8 land at min Hamming distance 0 to a ring member
    → zero flags during steady-state oscillation.
    """
    clock = _FakeClock()
    agent = _scrape_agent(clock, warmup=2)
    a_layout = b"<html><body>" + b"<div class='a'></div>" * 30 + b"</body></html>"
    b_layout = b"<html><body>" + b"<span id='x'></span><a href='/y'></a><p></p>" * 30 + b"</body></html>"
    # Sanity: the two layouts are far apart, so naive adjacent-pair
    # would have tripped on every flip.
    sequence = [a_layout, b_layout, a_layout, b_layout, a_layout, b_layout, a_layout, b_layout]
    flag_count = 0
    for body in sequence:
        out = list(agent.handle(_scrape_msg(body)))
        flag_count += sum(1 for m in out if m.envelope.topic == PROOF_FLAG)
    assert flag_count == 0, (
        f"Got {flag_count} proof.flag emissions during legitimate A/B "
        "oscillation; expected 0 with the F7.4 SimHash ring. Did "
        "the drift check regress to adjacent-pair-only?"
    )


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


def test_sec_rate_denylist_clear_idempotent_already_cleared_reason() -> None:
    """Phase 8 §8.1 idempotency guard. Re-running ``denylist_clear``
    on a subject that was never denylisted (or already cleared)
    surfaces ``reason=already_cleared`` in the info-severity
    ``denylist_removed`` alert; running it on an actively denylisted
    subject surfaces ``reason=removed``. Both paths still emit the
    SEC_DENYLIST remove (Redis SREM is idempotent and the audit
    stream benefits from one-event-per-decision).
    """
    clock = _FakeClock()

    # (a) never-seen subject -> already_cleared
    agent_a = _rate_agent(clock)
    event = MaintEvent(
        kind="denylist_clear",
        target="ip:8.8.8.8",
        reason="manual_override",
        produced_at=clock.iso(),
    )
    out = list(agent_a.handle(_msg(MAINT_EVENT, event.as_dict())))
    removes = [m for m in out if m.envelope.topic == SEC_DENYLIST]
    alerts = [SecAlert.from_dict(m.payload) for m in out if m.envelope.topic == SEC_ALERT]
    assert len(removes) == 1, "audit-stream remove must always fire"
    assert len(alerts) == 1
    assert alerts[0].kind == "denylist_removed"
    assert "already_cleared" in alerts[0].reason

    # (b) actively denylisted subject -> removed
    agent_b = _rate_agent(clock)
    for i in range(3):
        list(agent_b.handle(_alert_msg(alert_id=f"b-{i}")))
    assert agent_b.is_denylisted("ip:9.9.9.9")
    event_b = MaintEvent(
        kind="denylist_clear",
        target="ip:9.9.9.9",
        reason="manual_override",
        produced_at=clock.iso(),
    )
    out_b = list(agent_b.handle(_msg(MAINT_EVENT, event_b.as_dict())))
    alerts_b = [SecAlert.from_dict(m.payload) for m in out_b if m.envelope.topic == SEC_ALERT]
    assert len(alerts_b) == 1
    assert "; removed" in alerts_b[0].reason
    assert "already_cleared" not in alerts_b[0].reason


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


def test_sec_rate_re_trips_after_denylist_ttl_elapses() -> None:
    """Defense-in-depth regression (§7.3): once the in-process
    ``denylisted_at`` flag is set on a subject, it must expire after
    ``cfg.sec_denylist_ttl_s`` so the agent can re-add the subject to
    the Redis denylist on a fresh burst. Without this expiry the
    in-process flag silently outlives the Redis TTL — the gateway
    happily allows the resumed user, then never re-denylists them
    when they burst again. That's a real defense-in-depth
    weakening, not a benign optimisation.
    """
    import common.config as _cfg_mod
    _cfg_mod.cfg.sec_burst_threshold = 3
    _cfg_mod.cfg.sec_burst_window_ms = 60_000
    _cfg_mod.cfg.sec_denylist_ttl_s = 100
    clock = _FakeClock()
    agent = _rate_agent(clock)

    # First burst trips the threshold and emits one denylist add.
    for i in range(3):
        list(agent.handle(_alert_msg(alert_id=f"first-{i}")))
    assert agent.is_denylisted("ip:9.9.9.9")

    # A subsequent alert WHILE still listed must NOT emit another
    # denylist add (existing behaviour — the in-process flag suppresses
    # noise on the bus while the Redis TTL is doing the real work).
    out = list(agent.handle(_alert_msg(alert_id="while-listed")))
    assert SEC_DENYLIST not in [m.envelope.topic for m in out]

    # Advance past the Redis TTL. The next alert must trigger a fresh
    # window and a fresh denylist add — the gateway's authoritative
    # Redis entry has expired, so the agent must be willing to re-list.
    clock.advance(150.0)
    out_pre = list(agent.handle(_alert_msg(alert_id="post-ttl-1")))
    out_pre += list(agent.handle(_alert_msg(alert_id="post-ttl-2")))
    out_trip = list(agent.handle(_alert_msg(alert_id="post-ttl-3")))
    denylists = [m for m in (out_pre + out_trip) if m.envelope.topic == SEC_DENYLIST]
    assert len(denylists) == 1, (
        "agent must re-emit denylist add after the Redis TTL elapses; "
        "in-process `denylisted_at` flag would otherwise silently "
        "weaken defense-in-depth"
    )
    parsed = DenylistEvent.from_dict(denylists[0].payload)
    assert parsed.action == "add"
    assert parsed.subject == "ip:9.9.9.9"


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


def test_sec_scrape_baseline_consistency_under_concurrent_inspection() -> None:
    """F7.1 (P1): the writer (``_handle_scrape``) and the inspector
    helpers (``baseline_snapshot`` / ``baseline_size`` /
    ``baseline_simhash``) must serialize on the same lock so an
    out-of-band reader (telemetry tail, ``swarmctl``, the future
    Phase-14 multi-replica fan-out) can never observe a torn Welford
    state.

    The contract checked here:
      ``snapshot.samples_seen == snapshot.body_size_n`` for every
      atomic snapshot, regardless of how many writers / readers
      interleave. This invariant is established by the writer
      incrementing ``samples_seen`` *inside* the same locked region
      that calls ``body_size.update()`` (which sets ``n``); the
      snapshot helper takes the same lock. Without F7.1, the writer
      runs lock-free and a reader can catch the writer between
      ``body_size.update()`` (which sets ``n=k+1``) and
      ``samples_seen += 1`` (still at ``k``) — the assertion would
      fail. With F7.1, it cannot.
    """
    import threading

    clock = _FakeClock()
    agent = _scrape_agent(clock, warmup=1)

    n_writes = 500
    stop = threading.Event()
    inspector_violations: list[tuple[int, int]] = []
    inspector_iterations = [0]

    def inspect() -> None:
        while not stop.is_set():
            snap = agent.baseline_snapshot("mackolik")
            inspector_iterations[0] += 1
            if snap is None:
                continue
            samples_seen, body_n, _mean = snap
            if samples_seen != body_n:
                inspector_violations.append((samples_seen, body_n))

    t = threading.Thread(target=inspect, daemon=True)
    t.start()
    try:
        for i in range(n_writes):
            body = b"<html><body>" + (f"<div>{i}</div>".encode() * 10) + b"</body></html>"
            list(agent.handle(_scrape_msg(body, source="mackolik")))
    finally:
        stop.set()
        t.join(timeout=5.0)

    # The inspector must have run at least once (otherwise the test
    # is silently skipping its own probe).
    assert inspector_iterations[0] > 0, "inspector thread never ran"
    # Atomic snapshots must always satisfy samples_seen == body_size.n.
    assert inspector_violations == [], (
        f"observed {len(inspector_violations)} torn Welford snapshots "
        f"(first 3: {inspector_violations[:3]}); F7.1 lock discipline "
        "regressed"
    )
    # Final state sanity check.
    final = agent.baseline_snapshot("mackolik")
    assert final is not None
    assert final[0] == n_writes
    assert final[1] == n_writes


def test_sec_alert_debouncer_uses_dedicated_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    """F7.2 (P2): the per-agent ``SecAlertDebouncer`` LRU cap must
    be sized by ``cfg.sec_alert_debouncer_max_buckets`` \u2014 NOT by
    ``cfg.sec_rate_max_subjects``. Sharing the rate-agent's knob
    used to mean an operator lowering ``sec_rate_max_subjects``
    during incident response would simultaneously truncate the
    debouncer cap on the input + scrape agents, causing
    debounce-bucket churn and an alert storm at the worst possible
    moment.

    This test pins the wiring: monkeypatch the rate-subject knob
    to 1 and confirm every agent's debouncer is still sized by the
    dedicated knob (default 4096).
    """
    import common.config as _cfg_mod
    monkeypatch.setattr(_cfg_mod.cfg, "sec_rate_max_subjects", 1, raising=True)
    monkeypatch.setattr(_cfg_mod.cfg, "sec_alert_debouncer_max_buckets", 4096, raising=True)

    clock = _FakeClock()
    input_agent = SecInputAgent(clock_iso=clock.iso, new_id=_next_id_factory())
    scrape_agent = SecScrapeAgent(clock_iso=clock.iso, new_id=_next_id_factory())
    rate_agent = SecRateAgent(clock_iso=clock.iso, new_id=_next_id_factory(), clock_mono=clock.mono)

    for name, agent in (("input", input_agent), ("scrape", scrape_agent), ("rate", rate_agent)):
        cap = agent._debouncer._max_buckets  # type: ignore[attr-defined]
        assert cap == 4096, (
            f"{name} agent debouncer max_buckets={cap}; expected 4096 "
            "(the dedicated sec_alert_debouncer_max_buckets knob). "
            "Did F7.2 wiring regress to sec_rate_max_subjects?"
        )


def test_sec_scrape_dedup_and_pending_use_distinct_caps(monkeypatch: pytest.MonkeyPatch) -> None:
    """F7.3 (P3): the SecScrapeAgent's content-addressed dedup map
    and its (future-async) pending-classification queue must be
    sized by *independent* config knobs.

    Pre-F7.3 both used ``cfg.sec_scrape_max_pending``, so an
    operator scaling backpressure capacity would silently shrink
    the dedup window (and vice versa). Post-fix:
    ``sec_scrape_dedup_window`` (the new knob) sizes ``_dedup_max``;
    ``sec_scrape_max_pending`` continues to size ``_max_pending``.
    """
    import common.config as _cfg_mod
    monkeypatch.setattr(_cfg_mod.cfg, "sec_scrape_max_pending", 7, raising=True)
    monkeypatch.setattr(_cfg_mod.cfg, "sec_scrape_dedup_window", 13, raising=True)

    clock = _FakeClock()
    agent = _scrape_agent(clock, warmup=1)

    # Re-construct so the test isn't sensitive to import-time defaults
    # bleeding through `_scrape_agent`'s implicit cfg.read.
    fresh = SecScrapeAgent(
        debouncer=SecAlertDebouncer(ttl_s=60, clock=clock.mono),
        clock_iso=clock.iso,
        new_id=_next_id_factory(),
    )
    assert fresh._max_pending == 7, (
        f"_max_pending={fresh._max_pending}; expected 7 from sec_scrape_max_pending"
    )
    assert fresh._dedup_max == 13, (
        f"_dedup_max={fresh._dedup_max}; expected 13 from sec_scrape_dedup_window. "
        "F7.3 wiring regressed if these still share a knob."
    )
    # The two knobs must be independently tunable: changing one MUST
    # NOT change the other on a fresh construction.
    assert fresh._max_pending != fresh._dedup_max
    # Reference the warmup-bound `agent` to keep the helper used and
    # to silence the unused-local lint when this file is run standalone.
    del agent


# \u2500\u2500 Defense-in-depth sanitization (audit fix) \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500


def test_sec_input_sanitizer_strips_rtl_override_and_zero_width() -> None:
    """Audit fix: a `qa.request` containing an RTL override or
    zero-width joiner — the kind of byte the Go gateway's middleware
    is supposed to strip — must be neutralised by the agent itself
    before it reaches `qa.request.v1`. Without this, a gateway
    bypass / regression would silently widen the attack surface
    (the NLP layer trusts `sec_verdict=sanitized`).
    """
    from swarm.agents.sec.input import sanitize_text
    # Mix RLO (U+202E), ZWNJ (U+200C), BOM (U+FEFF), and a NUL.
    raw = "kim\u202Eşampiyon\u200colacak?\uFEFF\u0000"
    clean, steps, mutated = sanitize_text(raw)
    assert mutated is True
    # All attack-class characters stripped.
    for ch in ("\u202E", "\u200c", "\uFEFF", "\u0000"):
        assert ch not in clean, f"sanitizer left {ch!r} on the wire"
    assert "kim" in clean and "şampiyon" in clean and "olacak?" in clean
    assert steps == ["nfc", "strip_control"]
    # Idempotent.
    clean2, _, mutated2 = sanitize_text(clean)
    assert mutated2 is False
    assert clean2 == clean


def test_sec_input_pass_path_emits_charset_anomaly_when_sanitizer_mutates() -> None:
    """When the agent's defense-in-depth sanitizer actually mutates
    bytes (i.e. the gateway didn't), it MUST publish a debounced
    `charset_anomaly` info alert so operators see the bypass rate.
    The wire `qa.request.v1.sanitized_text` field carries the cleaned
    bytes, NOT the original."""
    import common.config as _cfg_mod
    _cfg_mod.cfg.sec_input_max_len = 8192  # restore from prior tests
    clock = _FakeClock()
    agent = _input_agent(clock)
    # RLO override embedded in an otherwise benign Turkish query.
    raw = "kim\u202Ekazanır?"
    req = QaRequest(request_id="r-rtl", raw_text=raw, ip="1.2.3.4", client_id="c-9")
    out = list(agent.handle(_msg(QA_REQUEST, req.as_dict())))
    topics = [m.envelope.topic for m in out]
    assert QA_REQUEST_V1 in topics
    v1 = next(m for m in out if m.envelope.topic == QA_REQUEST_V1)
    parsed = QaRequestV1.from_dict(v1.payload)
    # Defense-in-depth proof: the RLO is GONE from the wire.
    assert "\u202E" not in parsed.sanitized_text
    assert parsed.sanitized_text == "kimkazanır?"
    # Loud-on-mutation alert fired (debounced).
    alerts = [m for m in out if m.envelope.topic == SEC_ALERT]
    assert any(SecAlert.from_dict(m.payload).kind == "charset_anomaly" for m in alerts), (
        "sanitizer mutation must emit charset_anomaly info alert"
    )


def test_sec_input_pass_path_no_charset_alert_when_input_already_clean() -> None:
    """No spurious `charset_anomaly` alerts when the gateway already
    did its job. Idempotent contract: clean-in → clean-out, no extra
    alert noise."""
    import common.config as _cfg_mod
    _cfg_mod.cfg.sec_input_max_len = 8192
    clock = _FakeClock()
    agent = _input_agent(clock)
    req = QaRequest(request_id="r-clean", raw_text="kim kazanır?", ip="1.2.3.4")
    out = list(agent.handle(_msg(QA_REQUEST, req.as_dict())))
    alerts = [m for m in out if m.envelope.topic == SEC_ALERT]
    kinds = {SecAlert.from_dict(m.payload).kind for m in alerts}
    assert "charset_anomaly" not in kinds


def test_sec_input_classifier_sees_sanitized_text_not_raw() -> None:
    """Defense-in-depth: the classifier must see the sanitized
    bytes so an attacker cannot blind it with zero-widths / RTL
    overrides while smuggling a payload past it. Without this, an
    attacker could embed e.g. `Ga\u200Blatasaray ma\u200Cç tahmini` and
    the classifier would tokenise it differently than what the NLP
    layer eventually consumes.

    The raw payload deliberately uses benign Turkish text so the
    pre-classifier deterministic injection-rule sweep does NOT
    quarantine it; we want to assert the classifier hop runs at all
    and on the cleaned bytes.
    """
    import common.config as _cfg_mod
    _cfg_mod.cfg.sec_input_max_len = 8192
    seen: list[str] = []

    def classifier(text: str) -> tuple[str, str]:
        seen.append(text)
        return ("pass", "ok")

    clock = _FakeClock()
    agent = SecInputAgent(
        classifier=classifier,
        debouncer=SecAlertDebouncer(ttl_s=60, clock=clock.mono),
        clock_iso=clock.iso,
        new_id=_next_id_factory(),
    )
    raw = "Ga\u200Blatasaray ma\u200Cç tahmini"
    req = QaRequest(request_id="r-cls", raw_text=raw, ip="1.2.3.4")
    list(agent.handle(_msg(QA_REQUEST, req.as_dict())))
    assert len(seen) == 1
    assert "\u200B" not in seen[0] and "\u200C" not in seen[0], (
        "classifier must run on sanitized text — zero-widths still present"
    )
    assert seen[0] == "Galatasaray maç tahmini"


# ── Producer-side quarantine overflow guard (§7.5) ───────────────


def test_sec_input_quarantine_overflow_alert_fires_when_producer_saturates() -> None:
    """§7.5 binding: when storage.v1 is falling behind under a
    quarantine burst, the producer-side bounded queue saturates and
    a debounced `quarantine_overflow` SecAlert (severity=error)
    fires. The freshest sample is still published — drop-oldest
    means drop-from-tracking, not drop-from-publication (the
    fresher forensic evidence is more valuable)."""
    import common.config as _cfg_mod
    _cfg_mod.cfg.sec_input_max_len = 8192
    _cfg_mod.cfg.sec_quarantine_producer_queue_max = 3
    _cfg_mod.cfg.sec_quarantine_storage_lag_alert_ms = 5000
    clock = _FakeClock()

    def always_quarantine(_text: str) -> tuple[str, str]:
        return ("quarantine", "test_burst")

    agent = SecInputAgent(
        classifier=always_quarantine,
        debouncer=SecAlertDebouncer(ttl_s=60, clock=clock.mono),
        clock_iso=clock.iso,
        clock_mono=clock.mono,
        new_id=_next_id_factory(),
    )
    out_topics_per_call: list[list[str]] = []
    for i in range(5):
        req = QaRequest(request_id=f"burst-{i}", raw_text="payload", ip=f"10.0.0.{i}")
        msgs = list(agent.handle(_msg(QA_REQUEST, req.as_dict())))
        out_topics_per_call.append([m.envelope.topic for m in msgs])

    # Every call still publishes the quarantine sample (fresh-evidence
    # doctrine — no drop-from-publication on the InMemoryBus path).
    assert all(SEC_QUARANTINE in t for t in out_topics_per_call), (
        "fresh quarantine evidence must always reach the wire"
    )
    # Calls 1-2 (1-indexed: 1st & 2nd) have inflight count 1, 2 — under cap.
    # Call 3 hits cap exactly → first overflow alert fires.
    # Calls 4 & 5 also saturated but debounced → no extra overflow alert.
    overflow_kinds: list[str] = []
    for msgs in out_topics_per_call:
        # Walk the per-call topic stream, count overflow alerts.
        pass
    # Re-walk with payloads to collect alert kinds.
    all_alert_kinds: list[str] = []
    for i in range(5):
        # Re-issue dedicated alert collection inline above by iterating msgs again.
        pass
    overflow_count = 0
    burst_kind_count = 0
    # Use a fresh agent and re-run to collect per-message alert kinds cleanly.
    clock2 = _FakeClock()
    agent2 = SecInputAgent(
        classifier=always_quarantine,
        debouncer=SecAlertDebouncer(ttl_s=60, clock=clock2.mono),
        clock_iso=clock2.iso,
        clock_mono=clock2.mono,
        new_id=_next_id_factory(),
    )
    for i in range(5):
        req = QaRequest(request_id=f"burst2-{i}", raw_text="payload", ip=f"10.0.0.{i}")
        for m in agent2.handle(_msg(QA_REQUEST, req.as_dict())):
            if m.envelope.topic == SEC_ALERT:
                kind = SecAlert.from_dict(m.payload).kind
                if kind == "quarantine_overflow":
                    overflow_count += 1
                elif kind == "prompt_injection":
                    burst_kind_count += 1
    assert overflow_count == 1, (
        f"expected exactly 1 debounced quarantine_overflow alert; got {overflow_count}"
    )
    assert burst_kind_count >= 5, (
        "every quarantine still emits its own kind-specific alert (different debounce subject)"
    )
    # Inflight counter reflects the saturated state (all 5 within window).
    assert agent2.quarantine_inflight() == 5


def test_sec_input_quarantine_overflow_ages_out_after_window() -> None:
    """When emissions are spaced wider than the storage-lag window,
    the producer-side deque drains naturally and overflow does NOT
    fire. Bounded state is `O(constant)` regardless of total
    emissions over time."""
    import common.config as _cfg_mod
    _cfg_mod.cfg.sec_input_max_len = 8192
    _cfg_mod.cfg.sec_quarantine_producer_queue_max = 3
    _cfg_mod.cfg.sec_quarantine_storage_lag_alert_ms = 1000  # 1 s window
    clock = _FakeClock()

    def always_quarantine(_text: str) -> tuple[str, str]:
        return ("quarantine", "test_drain")

    agent = SecInputAgent(
        classifier=always_quarantine,
        debouncer=SecAlertDebouncer(ttl_s=60, clock=clock.mono),
        clock_iso=clock.iso,
        clock_mono=clock.mono,
        new_id=_next_id_factory(),
    )
    overflow_count = 0
    for i in range(10):
        clock.advance(0.6)  # 600ms apart, window=1000ms → at most 2 inflight
        req = QaRequest(request_id=f"slow-{i}", raw_text="payload", ip="1.1.1.1")
        for m in agent.handle(_msg(QA_REQUEST, req.as_dict())):
            if m.envelope.topic == SEC_ALERT:
                if SecAlert.from_dict(m.payload).kind == "quarantine_overflow":
                    overflow_count += 1
    assert overflow_count == 0, (
        f"spaced emissions must not trip overflow guard; got {overflow_count}"
    )
    # Window is 1s, last emit at t+5s; only the final 1s (≤2 entries) survives.
    assert agent.quarantine_inflight() <= 2


# ── Generalized debounce: critical bypass cfg knob ───────────────


def test_debouncer_critical_alerts_are_debounced_when_bypass_disabled() -> None:
    """§7.4 binding: `cfg.sec_alert_critical_debounce_enabled=True`
    flips `critical_bypass=False` at agent construction time.
    Critical alerts then DO get suppressed within TTL — escape hatch
    for noisy-environment debugging. Default cfg keeps critical
    bypass ON so paging events always page."""
    clock = _FakeClock()
    deb = SecAlertDebouncer(ttl_s=60, critical_bypass=False, clock=clock.mono)
    a = deb.decide(kind="seed_drift", subject="src1", severity="critical", reason="r")
    b = deb.decide(kind="seed_drift", subject="src1", severity="critical", reason="r")
    c = deb.decide(kind="seed_drift", subject="src1", severity="critical", reason="r")
    assert a.emit, "first critical fire must always emit"
    assert not b.emit and not c.emit, (
        "with bypass disabled, critical alerts within TTL must be suppressed"
    )
    clock.advance(61.0)
    d = deb.decide(kind="seed_drift", subject="src1", severity="critical", reason="r")
    assert d.emit and d.suppressed_count == 2

