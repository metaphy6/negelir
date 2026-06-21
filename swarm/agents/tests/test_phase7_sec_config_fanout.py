"""Phase 7 §7.1 — `sec.config.v1` cross-pod fan-out proof tests.

Security-first discipline: every event the agent reacts to must
have both a happy-path test (the announcement triggers the right
side-effect) and an adversarial test (malformed envelopes are
dropped without weakening the pattern engine, the disk file's
sha256 is the contract — not the bus event's claimed sha).
"""
from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Iterator

import pytest

from swarm.agents.payloads import SecConfigEvent
from swarm.agents.sec import SecInputAgent
from swarm.agents.sec._alert import SecAlertDebouncer
from swarm.agents.topics import SEC_ALERT, SEC_CONFIG, QA_REQUEST
from swarm.sdk.types import Message

from common.security import patterns as _patterns
from common.security.patterns import load_ruleset, reset_for_tests


# ── Helpers ───────────────────────────────────────────────────────
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


def _next_id():
    g = _ids()
    return lambda: next(g)


def _write_yaml(path: Path, version: int, *rules: tuple[str, str]) -> None:
    body = f"version: {version}\npatterns:\n"
    for rid, pat in rules:
        body += textwrap.dedent(
            f"""
            - id: {rid}
              pattern: "{pat}"
              severity: warn
              kind: prompt_injection
              reason: "{rid}"
            """
        )
    path.write_text(body)

def _agent(
    *,
    pattern_path: str,
) -> tuple[SecInputAgent, _FakeClock]:
    clock = _FakeClock()
    agent = SecInputAgent(
        debouncer=SecAlertDebouncer(ttl_s=60, clock=clock.mono),
        clock_iso=clock.iso,
        clock_mono=clock.mono,
        new_id=_next_id(),
        pattern_path=pattern_path,
    )
    return agent, clock


@pytest.fixture(autouse=True)
def _reset_pattern_singleton():
    reset_for_tests()
    yield
    reset_for_tests()


# ── Payload self-validation ──────────────────────────────────────
class TestSecConfigEvent:
    def test_round_trip(self) -> None:
        sha = "a" * 64
        ev = SecConfigEvent(
            config_name="injection_patterns",
            sha256=sha,
            mtime_ns=123,
            emitted_at="2025-01-01T00:00:00+00:00",
        )
        out = SecConfigEvent.from_dict(ev.as_dict())
        assert out == ev

    def test_rejects_unknown_config_name(self) -> None:
        with pytest.raises(ValueError, match="config_name"):
            SecConfigEvent(
                config_name="totally_made_up",
                sha256="a" * 64,
                mtime_ns=0,
                emitted_at="2025-01-01T00:00:00+00:00",
            )

    def test_rejects_short_sha(self) -> None:
        with pytest.raises(ValueError, match="sha256"):
            SecConfigEvent(
                config_name="injection_patterns",
                sha256="abc",
                mtime_ns=0,
                emitted_at="2025-01-01T00:00:00+00:00",
            )

    def test_rejects_negative_mtime(self) -> None:
        with pytest.raises(ValueError, match="mtime_ns"):
            SecConfigEvent(
                config_name="injection_patterns",
                sha256="a" * 64,
                mtime_ns=-1,
                emitted_at="2025-01-01T00:00:00+00:00",
            )


# ── Cross-pod fan-out behaviour ──────────────────────────────────
class TestSecInputAgentConfigEvent:
    def test_event_with_novel_sha_triggers_reload(self, tmp_path: Path) -> None:
        """Happy path: another replica announces a new sha → we
        re-read the file and pick up the new ruleset."""
        p = tmp_path / "patterns.yaml"
        _write_yaml(p, 1, ("rule_old", "old-token"))
        agent, _ = _agent(pattern_path=str(p))
        original_sha = agent.current_ruleset_sha()
        assert original_sha is not None

        # Operator updates the file out-of-band (e.g. ConfigMap rollout).
        _write_yaml(p, 2, ("rule_new", "new-token"))
        new_rs = load_ruleset(str(p))
        # Reset singleton so load_ruleset doesn't memoise.
        reset_for_tests()
        new_rs = load_ruleset(str(p))
        assert new_rs.sha256 != original_sha

        ev = SecConfigEvent(
            config_name="injection_patterns",
            sha256=new_rs.sha256,
            mtime_ns=new_rs.mtime_ns,
            emitted_at="2025-01-01T00:00:00+00:00",
        )
        msg = Message.new(SEC_CONFIG, ev.as_dict(), producer="sec.input.v1")
        out = list(agent.handle(msg))

        assert agent.current_ruleset_sha() == new_rs.sha256
        # An info alert should fire so operators see the swap.
        kinds = [m.payload.get("kind") for m in out if m.envelope.topic == SEC_ALERT]
        assert "pattern_reload" in kinds

    def test_event_with_matching_sha_is_noop(self, tmp_path: Path) -> None:
        """Idempotency: replay of an announcement carrying the sha
        we already hold MUST NOT touch the disk or emit a swap alert."""
        p = tmp_path / "patterns.yaml"
        _write_yaml(p, 1, ("rule_old", "old-token"))
        agent, _ = _agent(pattern_path=str(p))
        sha = agent.current_ruleset_sha()
        assert sha is not None

        ev = SecConfigEvent(
            config_name="injection_patterns",
            sha256=sha,
            mtime_ns=0,
            emitted_at="2025-01-01T00:00:00+00:00",
        )
        msg = Message.new(SEC_CONFIG, ev.as_dict(), producer="sec.input.v1")
        out = list(agent.handle(msg))
        assert out == []
        assert agent.current_ruleset_sha() == sha

    def test_endpoint_costs_event_is_silently_skipped(
        self, tmp_path: Path
    ) -> None:
        """The Python agent does not own the endpoint_costs file (Go
        gateway does); announcements for that name MUST NOT touch
        our pattern ruleset."""
        p = tmp_path / "patterns.yaml"
        _write_yaml(p, 1, ("rule_1", "evil"))
        agent, _ = _agent(pattern_path=str(p))
        sha_before = agent.current_ruleset_sha()

        ev = SecConfigEvent(
            config_name="endpoint_costs",
            sha256="b" * 64,
            mtime_ns=0,
            emitted_at="2025-01-01T00:00:00+00:00",
        )
        out = list(agent.handle(
            Message.new(SEC_CONFIG, ev.as_dict(), producer="sec.input.v1")
        ))
        assert out == []
        assert agent.current_ruleset_sha() == sha_before

    def test_malformed_envelope_dropped(self, tmp_path: Path) -> None:
        """Adversarial: a producer sends a payload with the wrong
        shape (missing required keys, wrong types). We MUST drop it,
        keep the current ruleset, and not raise."""
        p = tmp_path / "patterns.yaml"
        _write_yaml(p, 1, ("rule_1", "evil"))
        agent, _ = _agent(pattern_path=str(p))
        sha_before = agent.current_ruleset_sha()

        for bad in (
            {},                                 # empty
            {"config_name": "injection_patterns"},  # missing sha
            {"config_name": "injection_patterns", "sha256": "x" * 64,
             "emitted_at": "now"},              # invalid sha hex but well-shaped string
            {"config_name": 42, "sha256": "a" * 64, "emitted_at": "now"},
        ):
            msg = Message.new(SEC_CONFIG, bad, producer="sec.input.v1")
            # Must not raise — dropped silently.
            out = list(agent.handle(msg))
            assert out == []
        assert agent.current_ruleset_sha() == sha_before

    def test_announced_sha_with_unchanged_disk_does_not_swap(
        self, tmp_path: Path
    ) -> None:
        """Adversarial: a buggy / hostile producer announces a sha
        that differs from our ours — but the FILE on disk is still
        the old bytes. The contract is the disk file, so the swap
        must be a no-op (sha256 of the bytes we read back matches
        what we already have, so `_reload_now` short-circuits)."""
        p = tmp_path / "patterns.yaml"
        _write_yaml(p, 1, ("rule_1", "evil"))
        agent, _ = _agent(pattern_path=str(p))
        sha_before = agent.current_ruleset_sha()

        ev = SecConfigEvent(
            config_name="injection_patterns",
            sha256="f" * 64,  # totally different from disk
            mtime_ns=0,
            emitted_at="2025-01-01T00:00:00+00:00",
        )
        msg = Message.new(SEC_CONFIG, ev.as_dict(), producer="sec.input.v1")
        out = list(agent.handle(msg))
        # Disk bytes unchanged, so ruleset stays the same.
        assert agent.current_ruleset_sha() == sha_before
        # And no spurious info alert (the bytes did not change).
        kinds = [m.payload.get("kind") for m in out if m.envelope.topic == SEC_ALERT]
        assert "pattern_reload" not in [k for k in kinds if k != "pattern_reload" or False]
        # Stricter: zero info-level pattern_reload alerts.
        info = [
            m for m in out
            if m.envelope.topic == SEC_ALERT
            and m.payload.get("kind") == "pattern_reload"
            and m.payload.get("severity") == "info"
        ]
        assert info == []

    def test_qa_request_path_unchanged_after_config_event(
        self, tmp_path: Path
    ) -> None:
        """Regression guard: handling a SEC_CONFIG message must not
        alter the dedup / quarantine state used by QA_REQUEST."""
        p = tmp_path / "patterns.yaml"
        _write_yaml(p, 1, ("rule_1", "evil"))
        agent, _ = _agent(pattern_path=str(p))
        sha = agent.current_ruleset_sha()
        ev = SecConfigEvent(
            config_name="injection_patterns",
            sha256=sha,
            mtime_ns=0,
            emitted_at="2025-01-01T00:00:00+00:00",
        )
        list(agent.handle(
            Message.new(SEC_CONFIG, ev.as_dict(), producer="sec.input.v1")
        ))
        # Build a benign QA request and confirm the agent still
        # produces a downstream qa.request.v1.
        qa = {
            "request_id": "req-1",
            "raw_text": "merhaba dünya",
            "ip": "203.0.113.7",
            "locale": "tr",
            "client_id": "client-1",
            "received_at": "2025-01-01T00:00:00+00:00",
        }
        out = list(agent.handle(Message.new(QA_REQUEST, qa, producer="api")))
        topics = [m.envelope.topic for m in out]
        assert any(t == "qa.request.v1" for t in topics)
