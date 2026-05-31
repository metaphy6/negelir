"""Phase 10 §10.0 — Cross-phase contract boot validators.

Verifies the three inequality validators added to Config.validate():
  1. nlp_request_dedup_window_s >= qa_request_v1_dedup_window_s + 30
  2. api_request_timeout_ms >= nlp_pipeline_timeout_ms + nlp_dispatch_overhead_ms
  3. nlp_pipeline_timeout_ms >= consensus_window_ms + nlp_consensus_overhead_ms
     [+ nlp_humanizer_max_latency_ms when nlp_humanize=true]

Per AGENTS.md Rule 10: new validators → happy paths + adversarial (refuse-boot)
tests; regression tests that fail before the fix and pass after.
"""
from __future__ import annotations

import pytest


class TestNlpDedupWindowInequality:
    """nlp_request_dedup_window_s >= qa_request_v1_dedup_window_s + 30."""

    def test_defaults_satisfy_constraint(self) -> None:
        """Default config must pass the dedup-window inequality."""
        from common.config import Config

        issues = Config().validate()
        ineq = [i for i in issues if "nlp_request_dedup_window_s" in i and ">=" in i]
        assert ineq == [], f"Default config violates dedup window inequality: {ineq}"

    def test_refuses_boot_when_window_below_minimum(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Set nlp_request_dedup_window_s well below minimum (299 < 300 + 30)."""
        from common.config import Config

        monkeypatch.setenv("NEGELIR_NLP_REQUEST_DEDUP_WINDOW_S", "299")
        with pytest.raises(ValueError, match="nlp_request_dedup_window_s"):
            Config().validate(strict=True)

    def test_refuses_boot_at_minimum_minus_one(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """qa_request default=300 → minimum nlp=330; value 329 must be rejected."""
        from common.config import Config

        monkeypatch.setenv("NEGELIR_NLP_REQUEST_DEDUP_WINDOW_S", "329")
        with pytest.raises(ValueError, match="nlp_request_dedup_window_s"):
            Config().validate(strict=True)

    def test_accepts_at_exact_minimum(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Exactly qa(300) + 30 = 330 must be accepted."""
        from common.config import Config

        monkeypatch.setenv("NEGELIR_NLP_REQUEST_DEDUP_WINDOW_S", "330")
        issues = Config().validate()
        ineq = [i for i in issues if "nlp_request_dedup_window_s" in i and ">=" in i]
        assert ineq == [], f"Exact-minimum value 330 was rejected: {ineq}"


class TestNlpApiTimeoutChain:
    """api_request_timeout_ms >= nlp_pipeline_timeout_ms + nlp_dispatch_overhead_ms."""

    def test_defaults_satisfy_constraint(self) -> None:
        """Default config must satisfy the API timeout chain."""
        from common.config import Config

        issues = Config().validate()
        ineq = [
            i for i in issues
            if "api_request_timeout_ms" in i and "nlp_pipeline" in i
        ]
        assert ineq == [], f"Default config violates API timeout chain: {ineq}"

    def test_refuses_boot_when_api_too_short(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """pipeline(1800) + dispatch(200) = 2000; api=1999 must be rejected."""
        from common.config import Config

        monkeypatch.setenv("NEGELIR_API_REQUEST_TIMEOUT_MS", "1999")
        monkeypatch.setenv("NEGELIR_NLP_PIPELINE_TIMEOUT_MS", "1800")
        monkeypatch.setenv("NEGELIR_NLP_DISPATCH_OVERHEAD_MS", "200")
        with pytest.raises(ValueError, match="api_request_timeout_ms"):
            Config().validate(strict=True)

    def test_accepts_at_exact_minimum(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """pipeline(1800) + dispatch(200) = 2000; api=2000 must be accepted."""
        from common.config import Config

        monkeypatch.setenv("NEGELIR_API_REQUEST_TIMEOUT_MS", "2000")
        monkeypatch.setenv("NEGELIR_NLP_PIPELINE_TIMEOUT_MS", "1800")
        monkeypatch.setenv("NEGELIR_NLP_DISPATCH_OVERHEAD_MS", "200")
        issues = Config().validate()
        ineq = [
            i for i in issues
            if "api_request_timeout_ms" in i and "nlp_pipeline" in i
        ]
        assert ineq == [], f"Exact-minimum api timeout 2000 was rejected: {ineq}"


class TestNlpPipelineTimeoutChain:
    """nlp_pipeline_timeout_ms >= consensus_window_ms + overhead [+ humanizer]."""

    def test_defaults_without_humanize_satisfy_constraint(self) -> None:
        """Default config (nlp_humanize=false) must satisfy the pipeline chain."""
        from common.config import Config

        issues = Config().validate()
        ineq = [
            i for i in issues
            if "nlp_pipeline_timeout_ms" in i and ">=" in i
        ]
        assert ineq == [], f"Default config violates pipeline chain: {ineq}"

    def test_refuses_boot_pipeline_too_short_no_humanize(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """consensus(750) + overhead(100) = 850; pipeline=849 must be rejected."""
        from common.config import Config

        monkeypatch.setenv("NEGELIR_NLP_PIPELINE_TIMEOUT_MS", "849")
        monkeypatch.setenv("NEGELIR_NLP_HUMANIZE", "false")
        # api chain: 2500 >= 849 + 200 = 1049 — still satisfied
        with pytest.raises(ValueError, match="nlp_pipeline_timeout_ms"):
            Config().validate(strict=True)

    def test_refuses_boot_pipeline_too_short_with_humanize(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With humanize: consensus(750)+overhead(100)+humanizer(500)=1350; 1349 rejected."""
        from common.config import Config

        monkeypatch.setenv("NEGELIR_NLP_HUMANIZE", "true")
        monkeypatch.setenv("NEGELIR_NLP_PIPELINE_TIMEOUT_MS", "1349")
        # api chain: 2500 >= 1349 + 200 = 1549 — still satisfied
        with pytest.raises(ValueError, match="nlp_pipeline_timeout_ms"):
            Config().validate(strict=True)

    def test_humanize_true_accepted_at_exact_minimum(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With humanize: consensus(750)+overhead(100)+humanizer(500)=1350; 1350 accepted."""
        from common.config import Config

        monkeypatch.setenv("NEGELIR_NLP_HUMANIZE", "true")
        monkeypatch.setenv("NEGELIR_NLP_PIPELINE_TIMEOUT_MS", "1350")
        monkeypatch.setenv("NEGELIR_NLP_CONSENSUS_OVERHEAD_MS", "100")
        monkeypatch.setenv("NEGELIR_NLP_HUMANIZER_MAX_LATENCY_MS", "500")
        # Widen api timeout so that chain 2 is satisfied
        monkeypatch.setenv("NEGELIR_API_REQUEST_TIMEOUT_MS", "5000")
        issues = Config().validate()
        ineq = [
            i for i in issues
            if "nlp_pipeline_timeout_ms" in i and ">=" in i
        ]
        assert ineq == [], f"Exact-minimum pipeline timeout (humanize=true) rejected: {ineq}"

    def test_humanize_false_ignores_humanizer_latency(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With humanize=false a pipeline of exactly consensus+overhead is accepted."""
        from common.config import Config

        # sum without humanizer = 750 + 100 = 850
        monkeypatch.setenv("NEGELIR_NLP_HUMANIZE", "false")
        monkeypatch.setenv("NEGELIR_NLP_PIPELINE_TIMEOUT_MS", "850")
        monkeypatch.setenv("NEGELIR_NLP_CONSENSUS_OVERHEAD_MS", "100")
        # api chain: 2500 >= 850 + 200 = 1050 — satisfied
        issues = Config().validate()
        ineq = [
            i for i in issues
            if "nlp_pipeline_timeout_ms" in i and ">=" in i
        ]
        assert ineq == [], f"Pipeline=850 with humanize=false was rejected: {ineq}"
