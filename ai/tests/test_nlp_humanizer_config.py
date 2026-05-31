"""Phase 10 §10.8 — Humanizer LLM configuration tests.

Verifies the opt-in humanizer config contract:
  1. cfg.nlp_humanize defaults to False (humanizer OFF by default).
  2. Can be toggled via NEGELIR_NLP_HUMANIZE env var.
  3. When nlp_humanize=true, nlp_humanizer_max_latency_ms is added to the
     pipeline timeout inequality (cross-phase contract with Phase 9).
  4. The default config (nlp_humanize=false) satisfies all boot validators.
  5. The humanizer model is pinned by exact version in chart.json (NEVER *-latest).

Per AGENTS.md Rule 4: smallest model that works. The humanizer is opt-in polish,
never a decision-maker. Default=OFF ensures zero-LLM mode is the baseline.
Per CLAUDE.md forbidden patterns: NEVER use *-latest model IDs.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


class TestHumanizerDefaultOff:
    """§10.8 bullet 1: cfg.nlp_humanize=false by default."""

    def test_default_config_has_humanize_false(self) -> None:
        """Fresh Config() must have nlp_humanize=False (humanizer OFF)."""
        from common.config import Config

        cfg = Config()
        assert cfg.nlp_humanize is False, (
            "nlp_humanize must default to False per §10.8 bullet 1"
        )

    def test_can_toggle_humanize_via_env_var(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """NEGELIR_NLP_HUMANIZE=true must enable the humanizer."""
        from common.config import Config

        monkeypatch.setenv("NEGELIR_NLP_HUMANIZE", "true")
        cfg = Config()
        assert cfg.nlp_humanize is True, (
            "Setting NEGELIR_NLP_HUMANIZE=true must enable humanizer"
        )

    def test_humanize_accepts_various_truthy_values(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Humanize=true should accept '1', 'yes', 'true' (case-insensitive)."""
        from common.config import Config

        for val in ("true", "True", "TRUE", "1", "yes", "YES", "Yes"):
            monkeypatch.setenv("NEGELIR_NLP_HUMANIZE", val)
            cfg = Config()
            assert cfg.nlp_humanize is True, (
                f"NEGELIR_NLP_HUMANIZE={val!r} should be truthy"
            )

    def test_humanize_rejects_falsy_values(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Humanize=false should stay False for '', '0', 'no', 'false'."""
        from common.config import Config

        for val in ("false", "False", "FALSE", "0", "no", "NO", ""):
            monkeypatch.setenv("NEGELIR_NLP_HUMANIZE", val)
            cfg = Config()
            assert cfg.nlp_humanize is False, (
                f"NEGELIR_NLP_HUMANIZE={val!r} should be falsy"
            )


class TestHumanizerInPipelineInequality:
    """Humanizer budget added to pipeline timeout only when nlp_humanize=true."""

    def test_humanizer_off_excludes_latency_from_pipeline(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When nlp_humanize=false, pipeline constraint ignores humanizer budget."""
        from common.config import Config

        monkeypatch.setenv("NEGELIR_NLP_HUMANIZE", "false")
        monkeypatch.setenv("NEGELIR_NLP_PIPELINE_TIMEOUT_MS", "850")
        monkeypatch.setenv("NEGELIR_SWARM_CONSENSUS_WINDOW_MS", "750")
        monkeypatch.setenv("NEGELIR_NLP_CONSENSUS_OVERHEAD_MS", "100")
        # 850 >= 750 + 100 = 850 (exact minimum; humanizer=500 not counted)
        cfg = Config()
        issues = cfg.validate()
        ineq = [i for i in issues if "nlp_pipeline_timeout_ms" in i and ">=" in i]
        assert ineq == [], (
            f"Pipeline timeout=850 should satisfy constraint when humanize=false, "
            f"but got: {ineq}"
        )

    def test_humanizer_on_includes_latency_in_pipeline(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When nlp_humanize=true, pipeline must include humanizer budget."""
        from common.config import Config

        monkeypatch.setenv("NEGELIR_NLP_HUMANIZE", "true")
        monkeypatch.setenv("NEGELIR_NLP_PIPELINE_TIMEOUT_MS", "850")
        monkeypatch.setenv("NEGELIR_SWARM_CONSENSUS_WINDOW_MS", "750")
        monkeypatch.setenv("NEGELIR_NLP_CONSENSUS_OVERHEAD_MS", "100")
        monkeypatch.setenv("NEGELIR_NLP_HUMANIZER_MAX_LATENCY_MS", "500")
        # 850 < 750 + 100 + 500 = 1350 (violation)
        with pytest.raises(ValueError, match="nlp_pipeline_timeout_ms"):
            Config().validate(strict=True)

    def test_humanizer_on_with_sufficient_pipeline_budget(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When nlp_humanize=true and pipeline budget is sufficient, accept."""
        from common.config import Config

        monkeypatch.setenv("NEGELIR_NLP_HUMANIZE", "true")
        monkeypatch.setenv("NEGELIR_NLP_PIPELINE_TIMEOUT_MS", "1350")
        monkeypatch.setenv("NEGELIR_SWARM_CONSENSUS_WINDOW_MS", "750")
        monkeypatch.setenv("NEGELIR_NLP_CONSENSUS_OVERHEAD_MS", "100")
        monkeypatch.setenv("NEGELIR_NLP_HUMANIZER_MAX_LATENCY_MS", "500")
        # 1350 >= 750 + 100 + 500 = 1350 (exact minimum)
        cfg = Config()
        issues = cfg.validate()
        ineq = [i for i in issues if "nlp_pipeline_timeout_ms" in i and ">=" in i]
        assert ineq == [], (
            f"Pipeline timeout=1350 should satisfy constraint when humanize=true, "
            f"but got: {ineq}"
        )


class TestHumanizerMaxLatencyBounds:
    """nlp_humanizer_max_latency_ms must be bounded (§10.8 latency budget)."""

    def test_humanizer_latency_has_upper_bound(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """nlp_humanizer_max_latency_ms over 300s (300_000ms) must be rejected."""
        from common.config import Config

        monkeypatch.setenv("NEGELIR_NLP_HUMANIZER_MAX_LATENCY_MS", "300001")
        with pytest.raises(ValueError, match="nlp_humanizer_max_latency_ms"):
            Config().validate(strict=True)

    def test_humanizer_latency_has_lower_bound(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """nlp_humanizer_max_latency_ms below 1ms must be rejected."""
        from common.config import Config

        monkeypatch.setenv("NEGELIR_NLP_HUMANIZER_MAX_LATENCY_MS", "0")
        with pytest.raises(ValueError, match="nlp_humanizer_max_latency_ms"):
            Config().validate(strict=True)

    def test_default_humanizer_latency_is_reasonable(self) -> None:
        """Default nlp_humanizer_max_latency_ms should be in [100, 1000]ms range."""
        from common.config import Config

        cfg = Config()
        assert 100 <= cfg.nlp_humanizer_max_latency_ms <= 1000, (
            f"Default nlp_humanizer_max_latency_ms={cfg.nlp_humanizer_max_latency_ms} "
            f"should be in [100, 1000]ms range per §10.8 latency budget"
        )


class TestHumanizerCircuitBreaker:
    """nlp_humanizer_breaker_open_s must be bounded (§10.8 latency budget)."""

    def test_breaker_open_has_upper_bound(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """nlp_humanizer_breaker_open_s over 86_400s (1 day) must be rejected."""
        from common.config import Config

        monkeypatch.setenv("NEGELIR_NLP_HUMANIZER_BREAKER_OPEN_S", "86401")
        with pytest.raises(ValueError, match="nlp_humanizer_breaker_open_s"):
            Config().validate(strict=True)

    def test_breaker_open_has_lower_bound(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """nlp_humanizer_breaker_open_s below 1s must be rejected."""
        from common.config import Config

        monkeypatch.setenv("NEGELIR_NLP_HUMANIZER_BREAKER_OPEN_S", "0")
        with pytest.raises(ValueError, match="nlp_humanizer_breaker_open_s"):
            Config().validate(strict=True)

    def test_default_breaker_open_is_60_seconds(self) -> None:
        """Default nlp_humanizer_breaker_open_s should be 60s per §10.8."""
        from common.config import Config

        cfg = Config()
        assert cfg.nlp_humanizer_breaker_open_s == 60, (
            f"Default nlp_humanizer_breaker_open_s={cfg.nlp_humanizer_breaker_open_s} "
            f"must be 60 per §10.8 latency budget circuit breaker"
        )

    def test_breaker_open_accepts_valid_value(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """nlp_humanizer_breaker_open_s accepts values in [1, 86_400]."""
        from common.config import Config

        monkeypatch.setenv("NEGELIR_NLP_HUMANIZER_BREAKER_OPEN_S", "120")
        cfg = Config()
        cfg.validate(strict=True)
        assert cfg.nlp_humanizer_breaker_open_s == 120


class TestHumanizerModelPinning:
    """§10.8 bullet 2: humanizer model must be pinned by exact version in chart.json.

    Per CLAUDE.md forbidden patterns: NEVER use *-latest model IDs.
    The model must be pinned by exact version with SHA256 checksum.
    """

    def test_humanizer_model_is_pinned_in_chart(self) -> None:
        """Humanizer LLM must be pinned in xops/versioning/chart.json compatibility block."""
        chart_path = Path(__file__).parents[2] / "xops" / "versioning" / "chart.json"
        assert chart_path.exists(), f"chart.json not found at {chart_path}"

        chart = json.loads(chart_path.read_text())
        data_files = chart.get("compatibility", {}).get("data_files", {})
        
        assert "humanizer_llm" in data_files, (
            "humanizer_llm entry must exist in compatibility.data_files per §10.8"
        )

    def test_humanizer_model_never_uses_latest(self) -> None:
        """Humanizer model_id and version must never contain '*-latest'."""
        chart_path = Path(__file__).parents[2] / "xops" / "versioning" / "chart.json"
        chart = json.loads(chart_path.read_text())
        humanizer = chart["compatibility"]["data_files"]["humanizer_llm"]

        model_id = humanizer.get("model_id", "")
        version = humanizer.get("version", "")

        assert "-latest" not in model_id.lower(), (
            f"humanizer_llm.model_id={model_id!r} must NOT contain '*-latest' "
            f"per CLAUDE.md forbidden patterns"
        )
        assert "latest" not in version.lower(), (
            f"humanizer_llm.version={version!r} must NOT contain 'latest' "
            f"per CLAUDE.md forbidden patterns"
        )

    def test_humanizer_model_has_sha256_checksum(self) -> None:
        """Humanizer LLM entry must include SHA256 for integrity verification."""
        chart_path = Path(__file__).parents[2] / "xops" / "versioning" / "chart.json"
        chart = json.loads(chart_path.read_text())
        humanizer = chart["compatibility"]["data_files"]["humanizer_llm"]

        assert "sha256" in humanizer, (
            "humanizer_llm must have sha256 field per §10.8 model pinning"
        )
        sha256 = humanizer["sha256"]
        assert isinstance(sha256, str), "sha256 must be a string"
        assert len(sha256) == 64, (
            f"sha256 must be 64 hex chars, got {len(sha256)}"
        )

    def test_humanizer_model_has_both_cpu_and_gpu_formats(self) -> None:
        """Humanizer must support both CPU (GGUF) and GPU (bf16) formats per §10.8."""
        chart_path = Path(__file__).parents[2] / "xops" / "versioning" / "chart.json"
        chart = json.loads(chart_path.read_text())
        humanizer = chart["compatibility"]["data_files"]["humanizer_llm"]

        assert "formats" in humanizer, (
            "humanizer_llm must have formats dict per §10.8"
        )
        formats = humanizer["formats"]
        assert "cpu" in formats, (
            "humanizer_llm.formats must include 'cpu' (GGUF quantized) per §10.8"
        )
        assert "gpu" in formats, (
            "humanizer_llm.formats must include 'gpu' (bf16) per §10.8"
        )

    def test_humanizer_model_is_1b_params_or_smaller(self) -> None:
        """Humanizer must be <= 1B params per §10.8 'smallest model that works'."""
        chart_path = Path(__file__).parents[2] / "xops" / "versioning" / "chart.json"
        chart = json.loads(chart_path.read_text())
        humanizer = chart["compatibility"]["data_files"]["humanizer_llm"]

        params = humanizer.get("params", "")
        assert "1B" in params or "1b" in params, (
            f"humanizer_llm.params={params!r} must specify <= 1B params per §10.8"
        )


class TestHumanizerDecodingConstraints:
    """§10.8 bullet 4: decoding constraints (temperature, top_p, etc.)."""

    def test_max_new_tokens_defaults_to_120(self) -> None:
        """nlp_humanizer_max_new_tokens must default to 120 per §10.8."""
        from common.config import Config

        cfg = Config()
        assert cfg.nlp_humanizer_max_new_tokens == 120, (
            "nlp_humanizer_max_new_tokens must default to 120"
        )

    def test_temperature_defaults_to_03(self) -> None:
        """nlp_humanizer_temperature must default to 0.3 per §10.8."""
        from common.config import Config

        cfg = Config()
        assert cfg.nlp_humanizer_temperature == 0.3, (
            "nlp_humanizer_temperature must default to 0.3"
        )

    def test_top_p_defaults_to_09(self) -> None:
        """nlp_humanizer_top_p must default to 0.9 per §10.8."""
        from common.config import Config

        cfg = Config()
        assert cfg.nlp_humanizer_top_p == 0.9, (
            "nlp_humanizer_top_p must default to 0.9"
        )

    def test_repetition_penalty_defaults_to_105(self) -> None:
        """nlp_humanizer_repetition_penalty must default to 1.05 per §10.8."""
        from common.config import Config

        cfg = Config()
        assert cfg.nlp_humanizer_repetition_penalty == 1.05, (
            "nlp_humanizer_repetition_penalty must default to 1.05"
        )

    def test_max_new_tokens_bounded_above(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """nlp_humanizer_max_new_tokens over 1024 must be rejected."""
        from common.config import Config

        monkeypatch.setenv("NEGELIR_NLP_HUMANIZER_MAX_NEW_TOKENS", "2000")
        with pytest.raises(ValueError, match="nlp_humanizer_max_new_tokens"):
            Config().validate(strict=True)

    def test_max_new_tokens_bounded_below(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """nlp_humanizer_max_new_tokens below 1 must be rejected."""
        from common.config import Config

        monkeypatch.setenv("NEGELIR_NLP_HUMANIZER_MAX_NEW_TOKENS", "0")
        with pytest.raises(ValueError, match="nlp_humanizer_max_new_tokens"):
            Config().validate(strict=True)

    def test_temperature_bounded_above(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """nlp_humanizer_temperature over 2.0 must be rejected."""
        from common.config import Config

        monkeypatch.setenv("NEGELIR_NLP_HUMANIZER_TEMPERATURE", "2.5")
        with pytest.raises(ValueError, match="nlp_humanizer_temperature"):
            Config().validate(strict=True)

    def test_temperature_bounded_below(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """nlp_humanizer_temperature below 0.0 must be rejected."""
        from common.config import Config

        monkeypatch.setenv("NEGELIR_NLP_HUMANIZER_TEMPERATURE", "-0.1")
        with pytest.raises(ValueError, match="nlp_humanizer_temperature"):
            Config().validate(strict=True)

    def test_top_p_bounded_above(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """nlp_humanizer_top_p over 1.0 must be rejected."""
        from common.config import Config

        monkeypatch.setenv("NEGELIR_NLP_HUMANIZER_TOP_P", "1.1")
        with pytest.raises(ValueError, match="nlp_humanizer_top_p"):
            Config().validate(strict=True)

    def test_top_p_bounded_below(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """nlp_humanizer_top_p below 0.0 must be rejected."""
        from common.config import Config

        monkeypatch.setenv("NEGELIR_NLP_HUMANIZER_TOP_P", "-0.1")
        with pytest.raises(ValueError, match="nlp_humanizer_top_p"):
            Config().validate(strict=True)

    def test_repetition_penalty_bounded_above(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """nlp_humanizer_repetition_penalty over 2.0 must be rejected."""
        from common.config import Config

        monkeypatch.setenv("NEGELIR_NLP_HUMANIZER_REPETITION_PENALTY", "2.5")
        with pytest.raises(ValueError, match="nlp_humanizer_repetition_penalty"):
            Config().validate(strict=True)

    def test_repetition_penalty_bounded_below(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """nlp_humanizer_repetition_penalty below 1.0 must be rejected."""
        from common.config import Config

        monkeypatch.setenv("NEGELIR_NLP_HUMANIZER_REPETITION_PENALTY", "0.9")
        with pytest.raises(ValueError, match="nlp_humanizer_repetition_penalty"):
            Config().validate(strict=True)

    def test_all_decoding_params_readable_via_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """All decoding constraint params must be configurable via env vars."""
        from common.config import Config

        monkeypatch.setenv("NEGELIR_NLP_HUMANIZER_MAX_NEW_TOKENS", "100")
        monkeypatch.setenv("NEGELIR_NLP_HUMANIZER_TEMPERATURE", "0.5")
        monkeypatch.setenv("NEGELIR_NLP_HUMANIZER_TOP_P", "0.85")
        monkeypatch.setenv("NEGELIR_NLP_HUMANIZER_REPETITION_PENALTY", "1.10")

        cfg = Config()
        assert cfg.nlp_humanizer_max_new_tokens == 100
        assert cfg.nlp_humanizer_temperature == 0.5
        assert cfg.nlp_humanizer_top_p == 0.85
        assert cfg.nlp_humanizer_repetition_penalty == 1.10


class TestEnglishWordBlocklist:
    """§10.8 bullet 4: English word blocklist exists."""

    def test_blocklist_file_exists(self) -> None:
        """ai/nlp/data/en_word_blocklist.txt must exist per §10.8."""
        blocklist_path = Path(__file__).parents[1] / "nlp" / "data" / "en_word_blocklist.txt"
        assert blocklist_path.exists(), (
            "ai/nlp/data/en_word_blocklist.txt must exist per §10.8 logit bias"
        )

    def test_blocklist_is_nonempty(self) -> None:
        """Blocklist must contain at least some common English words."""
        blocklist_path = Path(__file__).parents[1] / "nlp" / "data" / "en_word_blocklist.txt"
        content = blocklist_path.read_text()
        lines = [line.strip() for line in content.splitlines() if line.strip() and not line.strip().startswith("#")]
        assert len(lines) > 20, (
            f"Blocklist should have > 20 words (found {len(lines)})"
        )

    def test_blocklist_contains_common_english_words(self) -> None:
        """Blocklist must include common English words per §10.8."""
        blocklist_path = Path(__file__).parents[1] / "nlp" / "data" / "en_word_blocklist.txt"
        content = blocklist_path.read_text().lower()
        # Check a few representative words from different categories
        required = ["the", "and", "will", "goal", "team"]
        for word in required:
            assert word in content, (
                f"Blocklist must contain '{word}' (common English word)"
            )
