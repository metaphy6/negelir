"""Phase 10 §10.27.6 — coordinated NLP abuse detector tests."""
from __future__ import annotations

from common.config import cfg
from pathlib import Path

from swarm.agents.nlp.abuse import NlpAbuseAgent
from swarm.agents.topics import NLP_ALERT_V1, NLP_SHADOW_V1
from swarm.sdk.types import Message


def _shadow_message(payload: dict[str, object]) -> Message:
    return Message.new(topic=NLP_SHADOW_V1, payload=payload, producer="nlp.intent.v1")


class TestNlpAbuseDetector:
    def test_nlp_abuse_agent_subscribes_only_to_nlp_shadow_and_publishes_nlp_alert(self) -> None:
        agent = NlpAbuseAgent()

        assert tuple(agent.subscribes) == (NLP_SHADOW_V1,)
        assert tuple(agent.publishes) == (NLP_ALERT_V1,)

    def test_nlp_abuse_detector_does_not_branch_tier_ast(self) -> None:
        src = Path(__file__).resolve().parents[1] / "swarm" / "agents" / "nlp" / "abuse.py"
        text = src.read_text(encoding="utf-8")
        assert "tier" not in text, "abuse detector must not branch on tier or tier_id"

    def test_nlp_abuse_detector_emits_did_you_mean_anomaly(self) -> None:
        old_threshold = cfg.nlp_abuse_dym_acceptance_anomaly_ratio
        cfg.nlp_abuse_dym_acceptance_anomaly_ratio = 0.8
        try:
            clock = 0.0
            agent = NlpAbuseAgent(monotonic=lambda: clock)

            payload = {
                "offered_intent": "predict.match_outcome",
                "accepted_intent": "predict.score_grid",
            }

            events = []
            for _ in range(6):
                events.extend(agent.handle(_shadow_message(payload)))
                clock += 1.0

            assert any(event.envelope.topic == NLP_ALERT_V1 for event in events)
            kinds = {event.payload["kind"] for event in events}
            assert "nlp_abuse_did_you_mean_anomaly" in kinds
        finally:
            cfg.nlp_abuse_dym_acceptance_anomaly_ratio = old_threshold

    def test_nlp_abuse_detector_emits_account_farm_error(self) -> None:
        clock = 0.0
        agent = NlpAbuseAgent(monotonic=lambda: clock)
        payload = {
            "client_fingerprint_hash": "fp-123",
            "account_id_h": "acct-1",
            "subject_key_sha8_prefix_2": "ab",
        }

        emitted = False
        for i in range(101):
            payload["account_id_h"] = f"acct-{i}"
            events = agent.handle(_shadow_message(payload))
            if any(event.payload["kind"] == "nlp_abuse_account_farm" for event in events):
                emitted = True
                break
            clock += 1.0

        assert emitted, "Expected nlp_abuse_account_farm alert to be emitted"
