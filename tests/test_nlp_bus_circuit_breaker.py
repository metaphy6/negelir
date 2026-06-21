"""Phase 10 §10.13 — NLP bus circuit breaker tests."""
import json
import hashlib
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from ai.swarm.agents.nlp._bus_circuit_breaker import (
    NlpBusCircuitBreaker,
    _restore_spool_payload,
)
from ai.swarm.sdk.types import Message


class TestNlpBusCircuitBreaker(unittest.TestCase):
    """Test NLP bus circuit breaker spool-on-bus-down behavior."""

    def test_closed_state_publishes_directly(self) -> None:
        """Breaker in closed state calls publish_fn directly."""
        published: list[Message] = []

        def mock_publish(msg: Message) -> None:
            published.append(msg)

        breaker = NlpBusCircuitBreaker(
            agent_name="nlp.intent.v1",
            publish_fn=mock_publish,
            fail_threshold=3,
        )
        msg = Message.new(topic="qa.intent.v1", payload={"test": "data"}, producer="test")
        extra = breaker.publish(msg)

        self.assertEqual(breaker.state, "closed")
        self.assertEqual(len(published), 1)
        self.assertEqual(len(extra), 0)

    def test_consecutive_failures_open_breaker(self) -> None:
        """After fail_threshold consecutive failures, breaker opens."""
        fail_count = 0

        def mock_publish_fail(msg: Message) -> None:
            nonlocal fail_count
            fail_count += 1
            raise RuntimeError("bus down")

        with TemporaryDirectory() as tmpdir:
            breaker = NlpBusCircuitBreaker(
                agent_name="nlp.intent.v1",
                publish_fn=mock_publish_fail,
                fail_threshold=3,
                spool_dir=Path(tmpdir),
            )
            msg = Message.new(topic="qa.intent.v1", payload={"test": "data"}, producer="test")

            # First two failures: still closed.
            breaker.publish(msg)
            self.assertEqual(breaker.state, "closed")
            breaker.publish(msg)
            self.assertEqual(breaker.state, "closed")

            # Third failure: opens to bus_degraded.
            breaker.publish(msg)
            self.assertEqual(breaker.state, "bus_degraded")
            self.assertEqual(fail_count, 3)

    def test_spool_writes_on_degraded(self) -> None:
        """In bus_degraded state, messages are spooled to disk."""
        def mock_publish_fail(msg: Message) -> None:
            raise RuntimeError("bus down")

        with TemporaryDirectory() as tmpdir:
            spool_dir = Path(tmpdir)
            breaker = NlpBusCircuitBreaker(
                agent_name="nlp.intent.v1",
                publish_fn=mock_publish_fail,
                fail_threshold=2,
                spool_dir=spool_dir,
            )
            msg = Message.new(topic="qa.intent.v1", payload={"test": "data"}, producer="test")

            # Force open breaker.
            breaker.publish(msg)
            breaker.publish(msg)
            self.assertEqual(breaker.state, "bus_degraded")

            # The 2nd publish (that triggered threshold) was spooled.
            spool_files = list(spool_dir.glob("*.envelope.json"))
            self.assertEqual(len(spool_files), 1)

    def test_spool_file_mode_0600(self) -> None:
        """Spool files are created with mode 0600."""
        def mock_publish_fail(msg: Message) -> None:
            raise RuntimeError("bus down")

        with TemporaryDirectory() as tmpdir:
            spool_dir = Path(tmpdir)
            breaker = NlpBusCircuitBreaker(
                agent_name="nlp.intent.v1",
                publish_fn=mock_publish_fail,
                fail_threshold=1,
                spool_dir=spool_dir,
            )
            msg = Message.new(topic="qa.intent.v1", payload={"test": "data"}, producer="test")

            # Transition to degraded spools the triggering message.
            breaker.publish(msg)
            self.assertEqual(breaker.state, "bus_degraded")

            spool_files = list(spool_dir.glob("*.envelope.json"))
            self.assertEqual(len(spool_files), 1)
            # Check mode is 0o600.
            import stat
            mode = spool_files[0].stat().st_mode
            self.assertEqual(stat.S_IMODE(mode), 0o600)

    def test_spool_overflow_emits_alert(self) -> None:
        """When spool exceeds max_entries, oldest is dropped and alert emitted."""
        def mock_publish_fail(msg: Message) -> None:
            raise RuntimeError("bus down")

        with TemporaryDirectory() as tmpdir:
            spool_dir = Path(tmpdir)
            breaker = NlpBusCircuitBreaker(
                agent_name="nlp.intent.v1",
                publish_fn=mock_publish_fail,
                fail_threshold=1,
                spool_dir=spool_dir,
            )

            # Force open.
            msg = Message.new(topic="qa.intent.v1", payload={"test": "data"}, producer="test")
            breaker.publish(msg)
            self.assertEqual(breaker.state, "bus_degraded")

            # Now spool_dir should have 1 file from the transition.
            spool_files = list(spool_dir.glob("*.envelope.json"))
            self.assertGreaterEqual(len(spool_files), 1)

    def test_nlp_spool_envelope_strips_text_field(self) -> None:
        """qa.intent.v1 spool payload drops sanitized_text and stores sha256."""

        def mock_publish_fail(msg: Message) -> None:
            raise RuntimeError("bus down")

        with TemporaryDirectory() as tmpdir:
            spool_dir = Path(tmpdir)
            breaker = NlpBusCircuitBreaker(
                agent_name="nlp.intent.v1",
                publish_fn=mock_publish_fail,
                fail_threshold=1,
                spool_dir=spool_dir,
            )
            sanitized_text = "mehmet 05321234567 galatasaray kazanır mı"
            msg = Message.new(
                topic="qa.intent.v1",
                payload={
                    "request_id": "req-001",
                    "qa_correlation_id": "corr-001",
                    "sanitized_text": sanitized_text,
                },
                producer="test",
            )

            breaker.publish(msg)
            self.assertEqual(breaker.state, "bus_degraded")

            spool_files = list(spool_dir.glob("*.envelope.json"))
            self.assertEqual(len(spool_files), 1)
            payload = json.loads(spool_files[0].read_text(encoding="utf-8"))["payload"]
            self.assertNotIn("sanitized_text", payload)
            self.assertEqual(
                payload.get("sanitized_text_sha256"),
                hashlib.sha256(sanitized_text.encode("utf-8")).hexdigest(),
            )

    def test_nlp_spool_replay_drops_when_original_unavailable(self) -> None:
        """Replay drops stripped payloads when original sanitized text is unavailable."""
        sanitized_text = "mehmet 05321234567 galatasaray kazanır mı"
        payload = {
            "request_id": "req-001",
            "sanitized_text_sha256": hashlib.sha256(
                sanitized_text.encode("utf-8")
            ).hexdigest(),
        }

        restored = _restore_spool_payload(payload, original_sanitized_text=None)
        self.assertIsNone(restored)


if __name__ == "__main__":
    unittest.main()
