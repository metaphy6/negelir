"""Phase 10 §10.21.4 — Humanizer breaker scope (pod vs cluster) proof-tests."""
import time
import unittest
from unittest.mock import MagicMock, patch

from ai.common.config import Config
from nlp._humanizer_breaker import HumanizerCircuitBreaker


class TestHumanizerBreakerPerPodIsolated(unittest.TestCase):
    """Per-pod breaker instances are isolated (in-memory, no cross-pod state)."""

    def test_nlp_humanizer_breaker_per_pod_isolated(self):
        """Two per-pod breaker instances do NOT share state."""
        cfg = Config()
        cfg.nlp_humanizer_breaker_scope = "pod"
        cfg.nlp_humanizer_breaker_open_s = 1  # short window for test

        breaker1 = HumanizerCircuitBreaker(cfg=cfg)
        breaker2 = HumanizerCircuitBreaker(cfg=cfg)

        # Both start closed
        self.assertFalse(breaker1.is_open())
        self.assertFalse(breaker2.is_open())

        # Open breaker1 via failure
        breaker1.record_failure()
        self.assertTrue(breaker1.is_open(), "breaker1 should be open after failure")
        self.assertFalse(breaker2.is_open(), "breaker2 should remain closed (isolated)")

        # Wait for auto-heal
        time.sleep(1.2)
        self.assertFalse(breaker1.is_open(), "breaker1 should auto-heal after timeout")
        self.assertFalse(breaker2.is_open(), "breaker2 should still be closed")

    def test_nlp_humanizer_breaker_auto_heal_per_pod(self):
        """Per-pod breaker auto-heals after cfg.nlp_humanizer_breaker_open_s."""
        cfg = Config()
        cfg.nlp_humanizer_breaker_scope = "pod"
        cfg.nlp_humanizer_breaker_open_s = 1  # 1 second for test

        breaker = HumanizerCircuitBreaker(cfg=cfg)
        self.assertFalse(breaker.is_open())

        # Trigger failure → breaker opens
        breaker.record_failure()
        self.assertTrue(breaker.is_open())

        # Wait less than breaker_open_s → still open
        time.sleep(0.5)
        self.assertTrue(breaker.is_open(), "breaker should remain open after 0.5s")

        # Wait for full duration → auto-heal to closed
        time.sleep(0.7)  # total ~1.2s
        self.assertFalse(breaker.is_open(), "breaker should auto-heal after 1s")


class TestHumanizerBreakerClusterScopeRedisPath(unittest.TestCase):
    """Cluster-scope breaker uses Redis (AST scan + integration test if Redis available)."""

    def setUp(self):
        """Check if redis module is available (skip tests if not)."""
        try:
            import redis  # noqa: F401
            self.redis_available = True
        except ImportError:
            self.redis_available = False

    def test_nlp_humanizer_breaker_cluster_scope_uses_redis_setex(self):
        """Cluster-scope breaker._record_failure_cluster calls Redis SETEX."""
        if not self.redis_available:
            self.skipTest("redis module not installed")

        cfg = Config()
        cfg.nlp_humanizer_breaker_scope = "cluster"
        cfg.nlp_humanizer_breaker_open_s = 60
        cfg.redis_host = "localhost"
        cfg.redis_port = 6379
        cfg.redis_password = ""

        breaker = HumanizerCircuitBreaker(cfg=cfg)

        # Mock redis.Redis to verify SETEX is called
        with patch("redis.Redis") as mock_redis_cls:
            mock_r = MagicMock()
            mock_redis_cls.return_value = mock_r

            breaker.record_failure()

            # Verify SETEX was called with correct key and TTL
            mock_r.setex.assert_called_once_with(
                "nlp:humanizer:breaker:open",
                60,  # breaker_open_s
                "1",
            )

    def test_nlp_humanizer_breaker_cluster_scope_uses_redis_exists(self):
        """Cluster-scope breaker.is_open() calls Redis EXISTS."""
        if not self.redis_available:
            self.skipTest("redis module not installed")

        cfg = Config()
        cfg.nlp_humanizer_breaker_scope = "cluster"
        cfg.redis_host = "localhost"
        cfg.redis_port = 6379
        cfg.redis_password = ""

        breaker = HumanizerCircuitBreaker(cfg=cfg)

        # Mock redis.Redis to verify EXISTS is called
        with patch("redis.Redis") as mock_redis_cls:
            mock_r = MagicMock()
            mock_redis_cls.return_value = mock_r
            mock_r.exists.return_value = 1  # key exists → breaker is open

            result = breaker.is_open()

            self.assertTrue(result, "is_open should return True when Redis key exists")
            mock_r.exists.assert_called_once_with("nlp:humanizer:breaker:open")

    @unittest.skipIf(
        True,  # Skip by default; run manually with Redis available
        "Requires Redis running on localhost:6379 (run manually when needed)",
    )
    def test_nlp_humanizer_breaker_cluster_scope_redis_integration(self):
        """Integration test: cluster-scope breaker coordinates via real Redis."""
        import redis

        cfg = Config()
        cfg.nlp_humanizer_breaker_scope = "cluster"
        cfg.nlp_humanizer_breaker_open_s = 2  # short window for test
        cfg.redis_host = "localhost"
        cfg.redis_port = 6379
        cfg.redis_password = ""

        # Clean up Redis key before test
        r = redis.Redis(host="localhost", port=6379, db=0)
        r.delete("nlp:humanizer:breaker:open")

        breaker1 = HumanizerCircuitBreaker(cfg=cfg)
        breaker2 = HumanizerCircuitBreaker(cfg=cfg)

        # Both start closed
        self.assertFalse(breaker1.is_open())
        self.assertFalse(breaker2.is_open())

        # Open breaker1 via failure → breaker2 should also see it as open (shared state)
        breaker1.record_failure()
        self.assertTrue(breaker1.is_open())
        self.assertTrue(breaker2.is_open(), "breaker2 should see cluster-wide open state")

        # Wait for Redis TTL to expire (auto-heal)
        time.sleep(2.5)
        self.assertFalse(breaker1.is_open(), "breaker1 should auto-heal after TTL")
        self.assertFalse(breaker2.is_open(), "breaker2 should also see closed state")

        # Clean up
        r.delete("nlp:humanizer:breaker:open")

    def test_nlp_humanizer_breaker_cluster_scope_degrades_gracefully_on_redis_failure(self):
        """Cluster-scope breaker fails open (allows humanize) if Redis is unavailable."""
        if not self.redis_available:
            self.skipTest("redis module not installed")

        cfg = Config()
        cfg.nlp_humanizer_breaker_scope = "cluster"
        cfg.redis_host = "unreachable.invalid"  # bogus host
        cfg.redis_port = 6379

        breaker = HumanizerCircuitBreaker(cfg=cfg)

        # is_open() should return False (fail-open) when Redis is unreachable
        self.assertFalse(
            breaker.is_open(),
            "is_open should fail-open (return False) when Redis is unreachable",
        )

        # record_failure() should not crash (gracefully degrade)
        try:
            breaker.record_failure()
        except Exception as e:
            self.fail(f"record_failure should not raise when Redis fails: {e}")


if __name__ == "__main__":
    unittest.main()
