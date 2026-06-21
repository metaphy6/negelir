"""Phase 7 §7.3 — `denylist_growth_anomaly` cardinality-cap escalation.

The Lua script `infra/redis/lua/sec_denylist_mutate.lua` is the
authoritative server-side cap. When it returns `rejected_capped`,
the Go gateway / write-path notifies `sec.rate.v1` via the public
`note_denylist_capped` hook so a critical alert flows on the bus.

Security-first discipline: critical alerts default to bypassing the
debouncer (every page matters); when an operator opts in to debounce
during a sustained outage, the standard TTL applies.
"""
from __future__ import annotations

from typing import Iterator

import pytest

from common.config import cfg as _cfg
from swarm.agents.payloads import SecAlert
from swarm.agents.sec import SecRateAgent
from swarm.agents.sec._alert import SecAlertDebouncer
from swarm.agents.topics import SEC_ALERT


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
        yield f"a-{n:04d}"


def _next_id():
    g = _ids()
    return lambda: next(g)


def _agent(*, debounce_critical: bool = False) -> tuple[SecRateAgent, _FakeClock]:
    clock = _FakeClock()
    deb = SecAlertDebouncer(
        ttl_s=60,
        clock=clock.mono,
        critical_bypass=not debounce_critical,
    )
    agent = SecRateAgent(
        debouncer=deb,
        clock_iso=clock.iso,
        clock_mono=clock.mono,
        new_id=_next_id(),
    )
    return agent, clock


class TestNoteDenylistCapped:
    def test_emits_critical_alert(self) -> None:
        agent, _ = _agent()
        msgs = list(agent.note_denylist_capped(
            subject="203.0.113.7/32",
            current_count=int(_cfg.sec_denylist_max_entries),
        ))
        assert len(msgs) == 1
        m = msgs[0]
        assert m.envelope.topic == SEC_ALERT
        payload = m.payload
        assert payload["kind"] == "denylist_growth_anomaly"
        assert payload["severity"] == "critical"
        assert payload["subject"] == "203.0.113.7/32"
        assert "cap" in payload["reason"].lower() or "cardinality" in payload["reason"].lower()
        # Producer + source identification.
        assert payload["source"] == "sec.rate.v1"

    def test_critical_bypasses_debounce_by_default(self) -> None:
        """Default config: critical alerts bypass the debouncer so
        repeated cap-hits page on every occurrence."""
        agent, _ = _agent()
        out1 = list(agent.note_denylist_capped(subject="a", current_count=999_999))
        out2 = list(agent.note_denylist_capped(subject="a", current_count=999_999))
        assert len(out1) == 1
        assert len(out2) == 1

    def test_debounce_collapses_when_operator_opts_in(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Operator override: when sec_alert_critical_debounce_enabled
        is True, the standard debouncer TTL applies — useful during
        a sustained outage to damp the page noise."""
        monkeypatch.setattr(_cfg, "sec_alert_critical_debounce_enabled", True)
        agent, clock = _agent(debounce_critical=True)

        out1 = list(agent.note_denylist_capped(subject="b", current_count=999_999))
        out2 = list(agent.note_denylist_capped(subject="b", current_count=999_999))
        assert len(out1) == 1
        assert len(out2) == 0  # collapsed by debouncer
        # After the TTL expires, a new alert is allowed.
        clock.advance(120)
        out3 = list(agent.note_denylist_capped(subject="b", current_count=999_999))
        assert len(out3) == 1

    def test_distinct_subjects_each_get_their_own_alert(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Even with debounce on, distinct subjects must each page —
        different attackers / subnets are distinct incidents."""
        monkeypatch.setattr(_cfg, "sec_alert_critical_debounce_enabled", True)
        agent, _ = _agent(debounce_critical=True)
        out_a = list(agent.note_denylist_capped(subject="x", current_count=999_999))
        out_b = list(agent.note_denylist_capped(subject="y", current_count=999_999))
        assert len(out_a) == 1
        assert len(out_b) == 1

    def test_payload_round_trips_through_secalert_dataclass(self) -> None:
        """The emitted dict must validate as a real SecAlert (no
        sneaky extra fields, no missing required fields)."""
        agent, _ = _agent()
        msg = next(iter(agent.note_denylist_capped(
            subject="z", current_count=999_999,
        )))
        ev = SecAlert.from_dict(msg.payload)
        assert ev.kind == "denylist_growth_anomaly"
        assert ev.severity == "critical"
        assert ev.source == "sec.rate.v1"
