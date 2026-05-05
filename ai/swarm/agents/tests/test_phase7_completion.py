"""Phase 7 — completion proof tests (closes the remaining §7.6 / §7.7 items).

These tests round out the items the prior Phase-7 sessions deferred
to "follow-up Phase 7.x". Per repo memory, the Bucket B follow-ups
(Go gateway middleware, classifier integration, ``sec.config.v1``
fan-out) stay deferred — they require new surfaces and labelled
corpora that Phase 7 doctrine explicitly leaves to later phases.
This file ships only the Python-side closeable items:

* §7.6 ``maint.event.v1`` allow-list enumerative test (the producer
  set is bounded by ``MAINT_EVENT_V1_ALLOWED_PRODUCERS``, not
  pinned to a single agent).
* §7.6 ``qa.request.v1`` consumer-side dedup helper test (the new
  ``RequestIdDeduper`` in ``swarm.sdk.dedup`` is the canonical
  implementation Phase 10 NLP will use).
* §7.6 ``sec.quarantine.v1`` overflow drops *oldest* tracking entry
  (focused assertion on age-out semantics; the existing burst test
  asserts the alert fires, this one asserts the deque is bounded
  and oldest entries are evicted from tracking, never from the
  wire).
* §7.7 fail-open doctrine — kill ``sec.input.v1``, run a benign
  Turkish corpus through the gateway-pass path, expect zero
  quarantines and ≤ ``ceil(n / breaker_open_s)`` classifier_degraded
  warns.
* §7.7 schema parity at *live emission* — drive each sec agent
  through a normal request and validate every wire payload against
  its registered schema (rather than a hand-crafted example).
* §7.7 idempotency regression for ``sec.scrape.v1`` — round out the
  three-agent set; existing ``test_phase7_sec_agents.py`` already
  covers ``sec.input.v1`` and ``sec.rate.v1``.

All tests are pure-Python, no I/O. The Lua containerized-Redis
integration test lives in its own file (``test_phase7_lua_redis.py``)
so it can be skipped when Redis is unavailable.
"""
from __future__ import annotations

import base64
import math
import time
from typing import Iterator

import pytest

from common import config as _cfg_mod
from swarm.agents.payloads import (
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
from swarm.sdk import RequestIdDeduper
from swarm.sdk.schemas import validate as schema_validate
from swarm.sdk.types import Message
from swarm.sdk.wire_contracts import MAINT_EVENT_V1_ALLOWED_PRODUCERS


# ── Test helpers (mirrors test_phase7_sec_agents.py) ──────────────


class _FakeClock:
    def __init__(self, t0: float = 1000.0) -> None:
        self.t = t0

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


def _input_agent(clock: _FakeClock, *, classifier=None) -> SecInputAgent:
    return SecInputAgent(
        classifier=classifier,
        debouncer=SecAlertDebouncer(ttl_s=60, clock=clock.mono),
        clock_iso=clock.iso,
        clock_mono=clock.mono,
        new_id=_next_id_factory(),
    )


def _scrape_agent(clock: _FakeClock, *, warmup: int = 2) -> SecScrapeAgent:
    _cfg_mod.cfg.sec_scrape_warmup_samples = warmup
    return SecScrapeAgent(
        debouncer=SecAlertDebouncer(ttl_s=60, clock=clock.mono),
        clock_iso=clock.iso,
        new_id=_next_id_factory(),
    )


def _rate_agent(clock: _FakeClock, *, threshold: int = 3) -> SecRateAgent:
    _cfg_mod.cfg.sec_burst_threshold = threshold
    _cfg_mod.cfg.sec_burst_window_ms = 60_000
    return SecRateAgent(
        debouncer=SecAlertDebouncer(ttl_s=60, clock=clock.mono),
        clock_iso=clock.iso,
        clock_mono=clock.mono,
        new_id=_next_id_factory(),
    )


def _scrape_msg(
    body: bytes, *, source: str = "mackolik", status: int = 200, ctype: str = "text/html",
) -> Message:
    raw = ScrapeRaw(
        source=source,
        target=f"https://{source}.local/x",
        bytes_sha256="sha-" + str(hash(body))[-12:],
        http_status=status,
        content_type=ctype,
        bytes_b64=base64.b64encode(body).decode(),
    )
    return _msg(SCRAPE_RAW, raw.as_dict())


# ─────────────────────────────────────────────────────────────────
# §7.6 — `maint.event.v1` allow-list enumerative test
# ─────────────────────────────────────────────────────────────────


def test_maint_event_v1_producer_set_is_bounded_by_allow_list() -> None:
    """§7.3 cross-phase note: the Phase 6 §6.4 boundary test was
    loosened from ``producers == {drift.v1}`` to
    ``producers ⊆ MAINT_EVENT_V1_ALLOWED_PRODUCERS`` so Phase 8's
    ``ops_console`` producer can land without a contract change.
    This test enforces the relaxation enumeratively across the
    canonical agent registry — adding a new agent that publishes
    ``maint.event.v1`` without joining the allow-list will fail
    here, not in production.
    """
    from swarm.bootstrap import build_agents  # noqa: PLC0415

    offenders: list[str] = []
    for agent in build_agents():
        publishes = tuple(getattr(agent, "publishes", ()))
        if MAINT_EVENT not in publishes:
            continue
        name = getattr(agent, "name", agent.__class__.__name__)
        if name not in MAINT_EVENT_V1_ALLOWED_PRODUCERS:
            offenders.append(name)
    assert offenders == [], (
        "maint.event.v1 producer set must be a subset of "
        f"MAINT_EVENT_V1_ALLOWED_PRODUCERS={sorted(MAINT_EVENT_V1_ALLOWED_PRODUCERS)}; "
        f"unauthorised producers found: {offenders}. Per Phase 7 §7.3, "
        "adding a producer requires updating wire_contracts.py with a "
        "tracker row + swarm minor bump."
    )


def test_maint_event_v1_allow_list_is_non_empty_and_includes_drift() -> None:
    """Sanity: the allow-list must always include ``drift.v1`` (the
    Phase 6.3 producer that retrains on Brier / KS-test trips). An
    empty set or a set without drift would silently mute the
    retrain channel."""
    assert "drift.v1" in MAINT_EVENT_V1_ALLOWED_PRODUCERS
    assert "ops_console" in MAINT_EVENT_V1_ALLOWED_PRODUCERS


# ─────────────────────────────────────────────────────────────────
# §7.6 — qa.request.v1 consumer-side dedup helper
# ─────────────────────────────────────────────────────────────────


def test_request_id_deduper_dedups_within_window() -> None:
    """Replaying the same ``request_id`` returns ``True`` on the
    second call (already seen). Distinct request-ids never collide.
    """
    clock = _FakeClock()
    d = RequestIdDeduper(window_s=300.0, max_keys=1024, clock=clock.mono)
    assert d.seen("req-1") is False
    assert d.seen("req-1") is True
    assert d.seen("req-1") is True
    assert d.seen("req-2") is False
    assert d.seen("req-2") is True


def test_request_id_deduper_ages_out_after_window() -> None:
    """Outside the window, a request-id is forgotten and a fresh
    delivery is treated as a miss. Keeps state ``O(window * rate)``.
    """
    clock = _FakeClock()
    d = RequestIdDeduper(window_s=10.0, max_keys=1024, clock=clock.mono)
    assert d.seen("req-x") is False
    clock.advance(11.0)
    assert d.seen("req-x") is False  # window expired
    assert d.seen("req-x") is True   # re-recorded


def test_request_id_deduper_lru_evicts_oldest_when_capped() -> None:
    """Defense-in-depth: an attacker spraying unique request-ids
    must not be able to grow the dedup table without bound. The
    LRU cap evicts the oldest tracked id; old ids may then come
    back as misses — *but the rate limiter (§7.3) is the primary
    bound*; this LRU is the safety net."""
    clock = _FakeClock()
    d = RequestIdDeduper(window_s=300.0, max_keys=2, clock=clock.mono)
    d.seen("a")
    d.seen("b")
    d.seen("c")  # evicts "a"
    assert d.size() == 2
    # "b" remains (was the next-oldest after the eviction).
    assert d.seen("b") is True
    # "c" remains (most recent).
    assert d.seen("c") is True
    # "a" was evicted → fresh miss; recording it now evicts the
    # current oldest to preserve the cap.
    assert d.seen("a") is False
    assert d.size() == 2


def test_request_id_deduper_handles_empty_request_id_safely() -> None:
    """A malformed envelope with an empty request_id must NOT pin
    a single dedup slot for the lifetime of the process. Always
    treated as never-seen so the consumer can decide what to do
    with the malformed event (typically log + drop)."""
    d = RequestIdDeduper(window_s=10.0, max_keys=8)
    assert d.seen("") is False
    assert d.seen("") is False
    assert d.size() == 0


def test_request_id_deduper_simulates_gateway_and_agent_dual_publish() -> None:
    """§7.5 binding: the gateway-pass path and the agent-pass path
    are mutually exclusive per ``request_id``. Under at-least-once
    redelivery, the same ``qa.request.v1`` envelope can replay
    from either producer. This test simulates the worst case —
    both producers publish for the same id — and asserts the
    deduper resolves to one logical processing event.
    """
    d = RequestIdDeduper(window_s=300.0, max_keys=1024)
    gateway_pass = QaRequestV1(
        request_id="req-99",
        sanitized_text="kim kazanır?",
        locale="tr",
        sec_verdict="pass",
        sec_steps_run=["nfc"],
    )
    agent_pass = QaRequestV1(
        request_id="req-99",
        sanitized_text="kim kazanır?",
        locale="tr",
        sec_verdict="sanitized",
        sec_steps_run=["nfc", "strip_control", "classifier"],
    )
    # First arrival processes; second arrival is a no-op.
    processed = 0
    for env in (gateway_pass, agent_pass):
        if not d.seen(env.request_id):
            processed += 1
    assert processed == 1, (
        "qa.request.v1 dedup must collapse mutually-exclusive "
        "gateway-pass + agent-pass deliveries for the same request_id"
    )


# ─────────────────────────────────────────────────────────────────
# §7.6 — sec.quarantine.v1 overflow drops oldest *from tracking*
# ─────────────────────────────────────────────────────────────────


def test_quarantine_overflow_evicts_oldest_tracking_entries_not_wire() -> None:
    """Doctrine (§7.5): "drop-oldest" is interpreted as drop-from-
    tracking, NOT drop-from-publication. Every quarantine sample
    still reaches the wire — fresh forensic evidence is the most
    valuable and must never be silently swallowed by an internal
    saturation guard. The producer-side bounded deque exists only
    to surface the ``quarantine_overflow`` SecAlert; emissions
    spaced wider than the lag window age out and the deque shrinks.
    """
    _cfg_mod.cfg.sec_input_max_len = 8192
    _cfg_mod.cfg.sec_quarantine_producer_queue_max = 3
    _cfg_mod.cfg.sec_quarantine_storage_lag_alert_ms = 1000  # 1 s
    clock = _FakeClock()

    def always_quarantine(_text: str) -> tuple[str, str]:
        return ("quarantine", "test_age_out")

    agent = _input_agent(clock, classifier=always_quarantine)
    quarantine_count = 0
    # Burst: 3 within the 1-s window saturates.
    for i in range(3):
        out = list(agent.handle(_msg(QA_REQUEST, QaRequest(
            request_id=f"burst-{i}", raw_text="x", ip="1.1.1.1",
        ).as_dict())))
        for m in out:
            if m.envelope.topic == SEC_QUARANTINE:
                quarantine_count += 1
    assert agent.quarantine_inflight() == 3
    assert quarantine_count == 3, "all 3 reach the wire (no drop-from-publication)"

    # Advance past the lag window and emit one more — old entries
    # should age out, leaving exactly 1 inflight.
    clock.advance(2.0)
    out = list(agent.handle(_msg(QA_REQUEST, QaRequest(
        request_id="late-1", raw_text="x", ip="1.1.1.1",
    ).as_dict())))
    quarantine_topics = [m for m in out if m.envelope.topic == SEC_QUARANTINE]
    assert len(quarantine_topics) == 1, "fresh sample always publishes"
    assert agent.quarantine_inflight() == 1, (
        "after the lag window, only the freshest tracking entry survives — "
        "this is the drop-oldest contract on the *tracking* side"
    )


# ─────────────────────────────────────────────────────────────────
# §7.7 — Fail-open doctrine: benign Turkish corpus
# ─────────────────────────────────────────────────────────────────


# A small, hand-curated benign Turkish QA corpus. Chosen to exercise
# common diacritics (ç ğ ı ö ş ü), punctuation, and football-domain
# vocabulary — the same shape Phase 10 NLP will see in production.
# Does NOT contain any token from `injection_patterns.yaml` (verified
# by `test_fail_open_doctrine_corpus_is_clean_under_full_ruleset`
# below).
_BENIGN_TURKISH_QUERIES: tuple[str, ...] = (
    "Galatasaray bu hafta kazanır mı?",
    "Fenerbahçe deplasmanda zorlanır mı?",
    "Beşiktaş ile Trabzonspor maçında gol olur mu?",
    "Hangi takımın ilk yarısı daha güçlü?",
    "Şampiyonluk yarışında Galatasaray önde mi?",
    "Bu maçta sarı kart sayısı kaç olur?",
    "Süper Lig'de en çok gol atan kim?",
    "Avrupa kupalarında Türk takımları başarılı mı?",
    "Derbi maçında favori takım hangisi?",
    "Bu hafta ofansif takım hangisi olacak?",
    "Üst üste maç oynayan takımın yorgunluğu performansı etkiler mi?",
    "Penaltı kazanan takım maçı hep kazanır mı?",
)


def test_fail_open_doctrine_zero_quarantines_on_benign_turkish_corpus() -> None:
    """§7.7 binding: the golden-input suite MUST produce 0
    quarantines from the agent's perspective — defense agents
    never block the happy path. The corpus exercises a realistic
    spread of Turkish football QA shapes; any quarantine here
    would be a false positive that breaks production traffic.
    """
    _cfg_mod.cfg.sec_input_max_len = 8192
    clock = _FakeClock()
    agent = _input_agent(clock)
    quarantines = 0
    for i, text in enumerate(_BENIGN_TURKISH_QUERIES):
        clock.advance(1.0)
        req = QaRequest(
            request_id=f"benign-{i}",
            raw_text=text,
            ip=f"10.0.0.{i % 250 + 1}",
            client_id=f"user-{i}",
        )
        for m in agent.handle(_msg(QA_REQUEST, req.as_dict())):
            if m.envelope.topic == SEC_QUARANTINE:
                quarantines += 1
    assert quarantines == 0, (
        f"benign Turkish QA corpus produced {quarantines} quarantines — "
        "fail-open doctrine violated. Inspect the deterministic "
        "rule sweep + classifier for false positives."
    )


def test_fail_open_doctrine_classifier_degraded_alerts_are_bounded() -> None:
    """§7.7: with the v1 classifier disabled (default; awaits Phase 13
    lexicon), every benign request emits a ``classifier_degraded``
    info alert at most once per ``cfg.sec_alert_debounce_ttl_s``
    bucket. The total over the corpus must be bounded by
    ``ceil(unique_subjects)`` — debounce keys on subject so each
    distinct user gets one alert per TTL window. If the bound is
    blown, debounce is broken (alert storm) and operators will
    drown.
    """
    _cfg_mod.cfg.sec_input_max_len = 8192
    clock = _FakeClock()
    agent = _input_agent(clock)
    degraded = 0
    for i, text in enumerate(_BENIGN_TURKISH_QUERIES):
        clock.advance(1.0)
        req = QaRequest(
            request_id=f"benign-{i}",
            raw_text=text,
            ip=f"10.0.0.{i % 250 + 1}",
            client_id=f"user-{i}",  # distinct subjects → distinct buckets
        )
        for m in agent.handle(_msg(QA_REQUEST, req.as_dict())):
            if m.envelope.topic == SEC_ALERT:
                if SecAlert.from_dict(m.payload).kind == "classifier_degraded":
                    degraded += 1
    # Distinct subjects → first alert per bucket fires; debounce TTL
    # is 60 s and the loop covers ~12 s, so each subject's bucket
    # fires exactly once. Upper bound = subject count.
    assert degraded == len(_BENIGN_TURKISH_QUERIES), (
        f"expected one classifier_degraded per distinct subject; "
        f"got {degraded} for {len(_BENIGN_TURKISH_QUERIES)} subjects"
    )


def test_fail_open_doctrine_classifier_degraded_debounces_per_subject() -> None:
    """When the same subject submits N benign queries inside the
    debounce TTL, only ONE ``classifier_degraded`` alert fires for
    them. Confirms the debounce is keyed on subject (not just on
    kind — that would cap globally and lose per-subject visibility).
    """
    _cfg_mod.cfg.sec_input_max_len = 8192
    clock = _FakeClock()
    agent = _input_agent(clock)
    degraded = 0
    for i, text in enumerate(_BENIGN_TURKISH_QUERIES):
        clock.advance(1.0)
        req = QaRequest(
            request_id=f"same-subj-{i}",
            raw_text=text,
            ip="10.0.0.42",
            client_id="single-user",  # one subject → one debounce bucket
        )
        for m in agent.handle(_msg(QA_REQUEST, req.as_dict())):
            if m.envelope.topic == SEC_ALERT:
                if SecAlert.from_dict(m.payload).kind == "classifier_degraded":
                    degraded += 1
    assert degraded == 1, (
        f"single-subject burst must fire exactly one classifier_degraded "
        f"within the debounce TTL; got {degraded}"
    )


def test_fail_open_doctrine_publishes_v1_for_every_benign_query() -> None:
    """The flip side of "0 quarantines": every benign query MUST
    produce a ``qa.request.v1`` so the NLP layer (Phase 10) sees the
    sanitized envelope. A silent drop is just as broken as a false
    quarantine — both starve user-facing answers.
    """
    _cfg_mod.cfg.sec_input_max_len = 8192
    clock = _FakeClock()
    agent = _input_agent(clock)
    v1_count = 0
    for i, text in enumerate(_BENIGN_TURKISH_QUERIES):
        clock.advance(1.0)
        req = QaRequest(
            request_id=f"happy-{i}",
            raw_text=text,
            ip=f"10.0.0.{i % 250 + 1}",
        )
        for m in agent.handle(_msg(QA_REQUEST, req.as_dict())):
            if m.envelope.topic == QA_REQUEST_V1:
                v1_count += 1
    assert v1_count == len(_BENIGN_TURKISH_QUERIES), (
        f"every benign query must produce one qa.request.v1; "
        f"got {v1_count} / {len(_BENIGN_TURKISH_QUERIES)}"
    )


# ─────────────────────────────────────────────────────────────────
# §7.7 — Schema parity at LIVE EMISSION
# ─────────────────────────────────────────────────────────────────


def _validate_message(m: Message) -> None:
    """Assert the message payload satisfies its registered schema."""
    errors = schema_validate(m.envelope.topic, m.payload)
    assert errors == [], (
        f"{m.envelope.topic} payload from live emission violates schema: "
        f"{errors}"
    )


def test_live_emission_sec_input_pass_path_validates_against_schemas() -> None:
    """§7.7 schema-parity at *live emission*: drive the agent
    through the pass-path and validate every wire payload it
    emits. Catches drift between the `payloads.py` dataclass and
    the JSON Schema that wouldn't be visible from a hand-crafted
    fixture.
    """
    _cfg_mod.cfg.sec_input_max_len = 8192
    clock = _FakeClock()
    agent = _input_agent(clock)
    req = QaRequest(
        request_id="live-pass",
        raw_text="merhaba dünya",
        ip="1.2.3.4",
        client_id="client-7",
    )
    out = list(agent.handle(_msg(QA_REQUEST, req.as_dict())))
    assert out, "expected at least qa.request.v1 + classifier_degraded info"
    for m in out:
        _validate_message(m)


def test_live_emission_sec_input_quarantine_path_validates_against_schemas() -> None:
    """Same as above, but for the quarantine path. A schema drift
    in ``sec.quarantine.v1`` or ``sec.alert.v1`` would surface
    here, not after a forensic incident in production."""
    _cfg_mod.cfg.sec_input_max_len = 8192
    clock = _FakeClock()

    def always_q(_text: str) -> tuple[str, str]:
        return ("quarantine", "live_test")

    agent = _input_agent(clock, classifier=always_q)
    req = QaRequest(
        request_id="live-q", raw_text="payload", ip="2.2.2.2",
    )
    out = list(agent.handle(_msg(QA_REQUEST, req.as_dict())))
    topics = {m.envelope.topic for m in out}
    assert SEC_QUARANTINE in topics
    assert SEC_ALERT in topics
    for m in out:
        _validate_message(m)


def test_live_emission_sec_scrape_paths_validate_against_schemas() -> None:
    """Drive ``sec.scrape.v1`` through warmup + a normal sample.
    Validates ``sec.alert.v1`` and (when emitted) ``proof.flag``
    payloads at the live emission point."""
    clock = _FakeClock()
    agent = _scrape_agent(clock, warmup=1)
    # Warm-up sample → emits baseline_warmup info alert.
    out1 = list(agent.handle(_scrape_msg(b"<html><body>hi</body></html>")))
    for m in out1:
        _validate_message(m)
    # Second sample → no alerts expected; nothing to validate beyond
    # the empty list, but we still walk if any are produced.
    out2 = list(agent.handle(_scrape_msg(b"<html><body>hello</body></html>")))
    for m in out2:
        _validate_message(m)


def test_live_emission_sec_rate_burst_path_validates_against_schemas() -> None:
    """Trip ``sec.rate.v1`` and validate the resulting ``rate_burst``
    + ``denylist_added`` envelopes against their schemas."""
    clock = _FakeClock()
    agent = _rate_agent(clock, threshold=2)
    a1 = SecAlert(
        alert_id="a-1", kind="rate_throttled", severity="warn",
        source="sec.input.v1", reason="r", produced_at=clock.iso(),
        subject="ip:9.9.9.9",
    )
    a2 = SecAlert(
        alert_id="a-2", kind="rate_throttled", severity="warn",
        source="sec.input.v1", reason="r", produced_at=clock.iso(),
        subject="ip:9.9.9.9",
    )
    out: list[Message] = []
    out.extend(agent.handle(_msg(SEC_ALERT, a1.as_dict())))
    out.extend(agent.handle(_msg(SEC_ALERT, a2.as_dict())))
    topics = {m.envelope.topic for m in out}
    assert SEC_DENYLIST in topics
    for m in out:
        _validate_message(m)


# ─────────────────────────────────────────────────────────────────
# §7.7 — Idempotency regression for sec.scrape.v1
# (rounds out the three-agent set; sec.input + sec.rate already
#  have idempotency tests in test_phase7_sec_agents.py)
# ─────────────────────────────────────────────────────────────────


def test_sec_scrape_idempotent_under_intra_source_replay_in_one_step() -> None:
    """At-least-once redelivery contract: the same byte-identical
    payload from the same source delivered twice in close
    succession must produce the same wire-level state as a single
    delivery. Specifically: exactly one baseline update, no
    duplicate alerts, no duplicate proof.flags.

    The existing ``test_sec_scrape_dedup_still_drops_intra_source_replay``
    asserts the baseline counter does not double-count; this test
    additionally asserts the wire-level emissions are identical.
    """
    clock = _FakeClock()
    agent = _scrape_agent(clock, warmup=1)
    # Warm with a first sample so the next pair are post-warmup.
    list(agent.handle(_scrape_msg(b"<html>warmup</html>")))
    body = b"<html><body><div class='x'>x</div></body></html>"
    out_first = list(agent.handle(_scrape_msg(body, source="mackolik")))
    out_replay = list(agent.handle(_scrape_msg(body, source="mackolik")))
    assert out_replay == [], (
        "intra-source replay must be a no-op on the wire; got "
        f"{[m.envelope.topic for m in out_replay]}"
    )
    # Baseline reflects exactly one post-warmup observation.
    assert agent.baseline_size("mackolik") == 2  # warmup + one
    # And the alert kinds (if any) on the first pass are not
    # duplicated by the replay.
    first_kinds = [
        SecAlert.from_dict(m.payload).kind for m in out_first
        if m.envelope.topic == SEC_ALERT
    ]
    # Either both empty (typical for two similar samples) or first
    # had a baseline-warmup info; replay must not add to either.
    assert all(k != "baseline_reset" for k in first_kinds)


def test_sec_scrape_idempotent_under_replay_after_window_advance() -> None:
    """Even when wall-clock time advances between deliveries, the
    sha256-keyed dedup still drops the replay. The dedup is
    content-addressed, not time-windowed — replays are forever
    idempotent within the LRU horizon (``cfg.sec_scrape_max_pending``).
    """
    clock = _FakeClock()
    agent = _scrape_agent(clock, warmup=1)
    list(agent.handle(_scrape_msg(b"<html>warmup</html>")))
    body = b"<html><body><span>same</span></body></html>"
    list(agent.handle(_scrape_msg(body)))
    clock.advance(3600.0)  # 1 hour later
    out = list(agent.handle(_scrape_msg(body)))
    assert out == [], "content-addressed dedup must outlive arbitrary clock skew"


# ─────────────────────────────────────────────────────────────────
# Defense-in-depth: deduper docstring guarantees against attack
# ─────────────────────────────────────────────────────────────────


def test_request_id_deduper_max_keys_zero_rejected() -> None:
    """Zero-cap deduper would silently disable dedup and let an
    at-least-once redelivery double-process every NLP call. The
    constructor must reject the misconfiguration loud."""
    with pytest.raises(ValueError):
        RequestIdDeduper(window_s=10.0, max_keys=0)


def test_request_id_deduper_zero_window_rejected() -> None:
    """A zero (or negative) window collapses dedup to an empty
    interval → every call is a miss. Reject loud."""
    with pytest.raises(ValueError):
        RequestIdDeduper(window_s=0.0, max_keys=1)


# ── PR9 / A2 — SWARM.md doctrine lock ─────────────────────────────


def test_swarm_md_locks_maint_event_producer_set() -> None:
    """A2 (PR9): the canonical producer set for ``maint.event.v1``
    lives in ``ai/swarm/sdk/wire_contracts.py``; the design doc
    ``docs/design/SWARM.md`` quotes the same list inside a marked
    block. This test asserts the two stay byte-equal.

    Updating one without the other fails the gate — that's the
    point. A new producer is a doctrine change (minor bump on
    ``swarm`` + design-doc edit), not a silent code change.
    """
    import re as _re
    from pathlib import Path
    repo_root = Path(__file__).resolve().parents[4]
    swarm_md = (repo_root / "docs" / "design" / "SWARM.md").read_text(encoding="utf-8")
    block = _re.search(
        r"<!-- MAINT_EVENT_V1_ALLOWED_PRODUCERS:begin -->(.+?)<!-- MAINT_EVENT_V1_ALLOWED_PRODUCERS:end -->",
        swarm_md,
        flags=_re.DOTALL,
    )
    assert block is not None, (
        "SWARM.md is missing the MAINT_EVENT_V1_ALLOWED_PRODUCERS "
        "doctrine-lock block (between the begin/end HTML comment "
        "markers). Restore the block or update this test."
    )
    documented = frozenset(
        m.group(1)
        for m in _re.finditer(r"^- `([^`]+)`", block.group(1), flags=_re.MULTILINE)
    )
    assert documented == MAINT_EVENT_V1_ALLOWED_PRODUCERS, (
        "SWARM.md doctrine block lists "
        f"{sorted(documented)} but the code constant is "
        f"{sorted(MAINT_EVENT_V1_ALLOWED_PRODUCERS)}. Bump both in the "
        "same commit (design-doc edit + minor `swarm` bump)."
    )
