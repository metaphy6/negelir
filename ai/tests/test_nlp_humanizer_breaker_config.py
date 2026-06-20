"""Phase 10 §10.21.4 — Humanizer breaker config validation tests."""
import unittest

from ai.common.config import Config


class TestHumanizerBreakerScopeValidation(unittest.TestCase):
    """Config validation for nlp_humanizer_breaker_scope enum."""

    def test_nlp_humanizer_breaker_scope_accepts_pod(self):
        """nlp_humanizer_breaker_scope='pod' passes validation."""
        cfg = Config()
        cfg.nlp_humanizer_breaker_scope = "pod"
        issues = cfg.validate(strict=True)
        self.assertEqual(issues, [], "scope='pod' should pass validation")

    def test_nlp_humanizer_breaker_scope_accepts_cluster(self):
        """nlp_humanizer_breaker_scope='cluster' passes validation."""
        cfg = Config()
        cfg.nlp_humanizer_breaker_scope = "cluster"
        issues = cfg.validate(strict=True)
        self.assertEqual(issues, [], "scope='cluster' should pass validation")

    def test_nlp_humanizer_breaker_scope_rejects_invalid(self):
        """nlp_humanizer_breaker_scope with invalid value fails validation."""
        cfg = Config()
        cfg.nlp_humanizer_breaker_scope = "invalid"
        issues = cfg.validate(strict=False)
        self.assertTrue(
            any("nlp_humanizer_breaker_scope" in issue for issue in issues),
            "validation should reject scope='invalid'",
        )
        self.assertTrue(
            any("must be 'pod' or 'cluster'" in issue for issue in issues),
            "validation error should mention allowed values",
        )


if __name__ == "__main__":
    unittest.main()
