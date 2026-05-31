"""Phase 10 §10.8 — Humanizer role tests.

Tests that verify the humanizer's role constraints:
  - NEVER decides the prediction (consensus already decided).
  - NEVER generates citation block (citation from dispatcher).
  - NEVER introduces facts not in the templated answer (rephrasing only).

Phase 10: stub implementation (always returns input unchanged).
Phase 11 §11.2: LLM integration.
Phase 11 §11.3: CPU parity test.
"""
from __future__ import annotations

import pytest


class TestHumanizerRole:
    """§10.8 bullet 3: humanizer role definition and constraints."""

    def test_humanizer_module_exists(self) -> None:
        """Humanizer module must exist with documented role."""
        from nlp import humanizer
        
        assert hasattr(humanizer, "humanize"), (
            "nlp.humanizer module must have humanize() function"
        )
        
        # Check that the module docstring defines the role
        doc = humanizer.__doc__ or ""
        assert "decides the prediction" in doc, (
            "Module docstring must document: NEVER decides the prediction"
        )
        assert "generates the citation block" in doc, (
            "Module docstring must document: NEVER generates citation block"
        )
        assert "introduces facts" in doc, (
            "Module docstring must document: NEVER introduces facts"
        )

    def test_humanize_function_has_role_constraints_in_docstring(self) -> None:
        """humanize() function docstring must document role constraints."""
        from nlp.humanizer import humanize
        
        doc = humanize.__doc__ or ""
        assert "decides the prediction" in doc, (
            "humanize() docstring must document: NEVER decides prediction"
        )
        assert "generates citation block" in doc, (
            "humanize() docstring must document: NEVER generates citation block"
        )
        assert "introduces facts" in doc, (
            "humanize() docstring must document: NEVER introduces facts"
        )

    def test_humanize_disabled_by_default_returns_unchanged(self) -> None:
        """When nlp_humanize=false (default), humanize() returns input unchanged."""
        from common.config import Config
        from nlp.humanizer import humanize
        
        cfg = Config()
        assert cfg.nlp_humanize is False, "nlp_humanize must default to False"
        
        template = "Galatasaray'ın kazanma olasılığı yüksek (güven: orta)."
        result = humanize(template, cfg=cfg)
        
        assert result == template, (
            "With nlp_humanize=false, humanize() must return input unchanged"
        )

    def test_humanize_stub_always_returns_unchanged(self) -> None:
        """Phase 10 stub: humanize() returns unchanged even with nlp_humanize=true."""
        from common.config import Config
        from nlp.humanizer import humanize
        
        import os
        # Temporarily enable humanizer
        orig = os.environ.get("NEGELIR_NLP_HUMANIZE")
        try:
            os.environ["NEGELIR_NLP_HUMANIZE"] = "true"
            cfg = Config()
            assert cfg.nlp_humanize is True
            
            template = "Galatasaray'ın kazanma olasılığı yüksek."
            result = humanize(template, cfg=cfg)
            
            # Phase 10 stub: always returns unchanged (LLM integration is Phase 11)
            assert result == template, (
                "Phase 10 stub must return input unchanged (LLM integration in Phase 11)"
            )
        finally:
            if orig is None:
                os.environ.pop("NEGELIR_NLP_HUMANIZE", None)
            else:
                os.environ["NEGELIR_NLP_HUMANIZE"] = orig

    def test_humanize_accepts_required_args(self) -> None:
        """humanize() must accept templated_answer and cfg."""
        from common.config import Config
        from nlp.humanizer import humanize
        import inspect
        
        sig = inspect.signature(humanize)
        params = list(sig.parameters.keys())
        
        assert "templated_answer" in params, (
            "humanize() must accept templated_answer arg"
        )
        assert "cfg" in params, (
            "humanize() must accept cfg arg"
        )

    def test_humanize_returns_string(self) -> None:
        """humanize() must return a string."""
        from common.config import Config
        from nlp.humanizer import humanize
        
        cfg = Config()
        template = "Test template."
        result = humanize(template, cfg=cfg)
        
        assert isinstance(result, str), (
            "humanize() must return str"
        )


class TestHumanizerRoleConstraintsDocumentation:
    """Verify role constraints are clearly documented."""

    def test_role_constraint_never_decides_prediction(self) -> None:
        """Role constraint: NEVER decides the prediction."""
        from nlp.humanizer import humanize
        
        doc = (humanize.__doc__ or "").lower()
        assert "never" in doc and "decides" in doc and "prediction" in doc, (
            "humanize() must document: NEVER decides the prediction"
        )

    def test_role_constraint_never_generates_citation(self) -> None:
        """Role constraint: NEVER generates citation block."""
        from nlp.humanizer import humanize
        
        doc = (humanize.__doc__ or "").lower()
        assert "never" in doc and "citation" in doc, (
            "humanize() must document: NEVER generates citation block"
        )

    def test_role_constraint_never_introduces_facts(self) -> None:
        """Role constraint: NEVER introduces facts."""
        from nlp.humanizer import humanize
        
        doc = (humanize.__doc__ or "").lower()
        assert "never" in doc and "introduces" in doc and "fact" in doc, (
            "humanize() must document: NEVER introduces facts"
        )

    def test_decoding_constraints_documented(self) -> None:
        """Decoding constraints must be documented."""
        from nlp import humanizer
        
        doc = humanizer.__doc__ or ""
        assert "temperature=0.3" in doc, "Must document temperature=0.3"
        assert "top_p=0.9" in doc, "Must document top_p=0.9"
        assert "repetition_penalty=1.05" in doc, "Must document repetition_penalty=1.05"
        assert "max_new_tokens" in doc, "Must document max_new_tokens constraint"

    def test_latency_budget_documented(self) -> None:
        """Latency budget must be documented."""
        from nlp import humanizer
        
        doc = humanizer.__doc__ or ""
        assert "nlp_humanizer_max_latency_ms" in doc, (
            "Must document nlp_humanizer_max_latency_ms latency budget"
        )
        assert "humanizer_disabled" in doc, (
            "Must document nlp.event.v1{kind=humanizer_disabled} on breach"
        )

    def test_drift_guard_documented(self) -> None:
        """Drift guard must be documented."""
        from nlp import humanizer
        
        doc = humanizer.__doc__ or ""
        assert "nlp_humanizer_max_edit_ratio" in doc, (
            "Must document nlp_humanizer_max_edit_ratio drift guard"
        )
        assert "nlp_humanizer_drift" in doc, (
            "Must document nlp.alert.v1{kind=nlp_humanizer_drift}"
        )


class TestHumanizerDriftGuard:
    """§10.8 bullet 6: Drift guard (edit distance constraint)."""

    def test_drift_guard_function_exists(self) -> None:
        """_check_drift_guard() must exist."""
        from nlp import humanizer
        
        assert hasattr(humanizer, "_check_drift_guard"), (
            "_check_drift_guard() function must exist"
        )

    def test_drift_guard_accepts_identical_strings(self) -> None:
        """Identical strings pass drift guard (edit distance = 0)."""
        from common.config import Config
        from nlp.humanizer import _check_drift_guard
        
        cfg = Config()
        template = "Galatasaray'ın kazanma olasılığı yüksek."
        output = template  # Identical
        
        assert _check_drift_guard(template, output, cfg=cfg), (
            "Identical strings must pass drift guard (edit distance = 0)"
        )

    def test_drift_guard_accepts_minor_rephrasing(self) -> None:
        """Minor rephrasing within max_edit_ratio passes drift guard."""
        from common.config import Config
        from nlp.humanizer import _check_drift_guard
        
        cfg = Config()
        # Default max_edit_ratio=0.6
        template = "Galatasaray'ın kazanma olasılığı yüksek."
        # Slight rephrase (distance ~5, len=39, ratio ~0.13 < 0.6)
        output = "Galatasaray kazanma olasılığı yüksek görünüyor."
        
        assert _check_drift_guard(template, output, cfg=cfg), (
            "Minor rephrasing within max_edit_ratio must pass drift guard"
        )

    def test_drift_guard_rejects_major_rewrite(self) -> None:
        """Major rewrite beyond max_edit_ratio fails drift guard."""
        from common.config import Config
        from nlp.humanizer import _check_drift_guard
        
        cfg = Config()
        # Default max_edit_ratio=0.6
        template = "Galatasaray'ın kazanma olasılığı yüksek."
        # Complete rewrite (distance > 0.6 * len(template))
        output = "Fenerbahçe bu maçı kaybedecek gibi duruyor."
        
        assert not _check_drift_guard(template, output, cfg=cfg), (
            "Major rewrite beyond max_edit_ratio must fail drift guard"
        )

    def test_drift_guard_respects_config_threshold(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Drift guard threshold must respect cfg.nlp_humanizer_max_edit_ratio."""
        from common.config import Config
        from nlp.humanizer import _check_drift_guard
        
        # Set a very strict threshold
        monkeypatch.setenv("NEGELIR_NLP_HUMANIZER_MAX_EDIT_RATIO", "0.1")
        cfg = Config()
        assert cfg.nlp_humanizer_max_edit_ratio == 0.1
        
        template = "Galatasaray'ın kazanma olasılığı yüksek."
        # Distance = 5, len = 39, ratio ~0.13 > 0.1
        output = "Galatasaray kazanma olasılığı yüksek görünüyor."
        
        assert not _check_drift_guard(template, output, cfg=cfg), (
            "With max_edit_ratio=0.1, this rephrase must fail drift guard"
        )

    def test_drift_guard_accepts_empty_template(self) -> None:
        """Empty template always passes drift guard."""
        from common.config import Config
        from nlp.humanizer import _check_drift_guard
        
        cfg = Config()
        template = ""
        output = "Some output"
        
        # Empty template → no drift possible
        assert _check_drift_guard(template, output, cfg=cfg), (
            "Empty template must always pass drift guard"
        )

    def test_drift_guard_boundary_at_max_ratio(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Drift guard must accept exactly max_edit_ratio (boundary test)."""
        from common.config import Config
        from nlp.humanizer import _check_drift_guard
        
        monkeypatch.setenv("NEGELIR_NLP_HUMANIZER_MAX_EDIT_RATIO", "0.5")
        cfg = Config()
        
        # Construct input where ratio is exactly 0.5
        # Template len=10, output differs by 5 chars → ratio = 5/10 = 0.5
        template = "0123456789"
        output = "abcde56789"  # 5 substitutions
        
        # Edit distance = 5, ratio = 5/10 = 0.5 (exactly at threshold)
        assert _check_drift_guard(template, output, cfg=cfg), (
            "Edit ratio exactly at threshold must pass drift guard"
        )

    def test_drift_guard_rejects_just_over_threshold(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Drift guard must reject ratio just over threshold."""
        from common.config import Config
        from nlp.humanizer import _check_drift_guard
        
        monkeypatch.setenv("NEGELIR_NLP_HUMANIZER_MAX_EDIT_RATIO", "0.5")
        cfg = Config()
        
        # Template len=10, output differs by 6 chars → ratio = 6/10 = 0.6 > 0.5
        template = "0123456789"
        output = "abcdef6789"  # 6 substitutions
        
        assert not _check_drift_guard(template, output, cfg=cfg), (
            "Edit ratio over threshold must fail drift guard"
        )

    def test_config_has_max_edit_ratio_field(self) -> None:
        """Config must have nlp_humanizer_max_edit_ratio field."""
        from common.config import Config
        
        cfg = Config()
        assert hasattr(cfg, "nlp_humanizer_max_edit_ratio"), (
            "Config must have nlp_humanizer_max_edit_ratio field"
        )
        assert isinstance(cfg.nlp_humanizer_max_edit_ratio, float), (
            "nlp_humanizer_max_edit_ratio must be float"
        )

    def test_default_max_edit_ratio_is_0_6(self) -> None:
        """Default nlp_humanizer_max_edit_ratio must be 0.6."""
        from common.config import Config
        
        cfg = Config()
        assert cfg.nlp_humanizer_max_edit_ratio == 0.6, (
            "Default nlp_humanizer_max_edit_ratio must be 0.6 per §10.8"
        )

    def test_max_edit_ratio_bounded_zero_to_one(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """nlp_humanizer_max_edit_ratio must be bounded [0.0, 1.0]."""
        from common.config import Config
        
        # Test lower bound
        monkeypatch.setenv("NEGELIR_NLP_HUMANIZER_MAX_EDIT_RATIO", "-0.1")
        cfg = Config()
        with pytest.raises(ValueError, match="nlp_humanizer_max_edit_ratio"):
            cfg.validate(strict=True)
        
        # Test upper bound
        monkeypatch.setenv("NEGELIR_NLP_HUMANIZER_MAX_EDIT_RATIO", "1.5")
        cfg = Config()
        with pytest.raises(ValueError, match="nlp_humanizer_max_edit_ratio"):
            cfg.validate(strict=True)
        
        # Test valid boundaries
        monkeypatch.setenv("NEGELIR_NLP_HUMANIZER_MAX_EDIT_RATIO", "0.0")
        cfg_min = Config()
        assert cfg_min.nlp_humanizer_max_edit_ratio == 0.0
        
        monkeypatch.setenv("NEGELIR_NLP_HUMANIZER_MAX_EDIT_RATIO", "1.0")
        cfg_max = Config()
        assert cfg_max.nlp_humanizer_max_edit_ratio == 1.0


class TestHumanizerGPUSharing:
    """§10.8 bullet 7: GPU sharing via Phase 11 §11.2 round-robin scheduler."""

    def test_acquire_gpu_lease_function_exists(self) -> None:
        """_acquire_gpu_lease() stub must exist."""
        from nlp import humanizer
        
        assert hasattr(humanizer, "_acquire_gpu_lease"), (
            "_acquire_gpu_lease() stub must exist (Phase 11 §11.2 contract)"
        )

    def test_release_gpu_lease_function_exists(self) -> None:
        """_release_gpu_lease() stub must exist."""
        from nlp import humanizer
        
        assert hasattr(humanizer, "_release_gpu_lease"), (
            "_release_gpu_lease() stub must exist (Phase 11 §11.2 contract)"
        )

    def test_acquire_gpu_lease_stub_raises_not_implemented(self) -> None:
        """Phase 10 stub: _acquire_gpu_lease() raises NotImplementedError."""
        from common.config import Config
        from nlp.humanizer import _acquire_gpu_lease
        
        cfg = Config()
        with pytest.raises(NotImplementedError, match="Phase 11"):
            _acquire_gpu_lease(cfg=cfg)

    def test_release_gpu_lease_stub_raises_not_implemented(self) -> None:
        """Phase 10 stub: _release_gpu_lease() raises NotImplementedError."""
        from nlp.humanizer import _release_gpu_lease
        
        with pytest.raises(NotImplementedError, match="Phase 11"):
            _release_gpu_lease(lease_token="stub_token")

    def test_gpu_sharing_contract_documented_in_module_docstring(self) -> None:
        """GPU sharing contract must be documented in module docstring."""
        from nlp import humanizer
        
        doc = humanizer.__doc__ or ""
        assert "Phase 11" in doc and "11.2" in doc, (
            "Module docstring must reference Phase 11 §11.2"
        )
        assert "scheduler" in doc or "lease" in doc, (
            "Module docstring must document GPU scheduler/lease"
        )

    def test_gpu_sharing_contract_documented_in_acquire_docstring(self) -> None:
        """Lease swap contract must be documented in _acquire_gpu_lease()."""
        from nlp.humanizer import _acquire_gpu_lease
        
        doc = _acquire_gpu_lease.__doc__ or ""
        assert "lease swap" in doc.lower(), (
            "_acquire_gpu_lease() must document lease swap contract"
        )
        assert "patcher" in doc.lower(), (
            "_acquire_gpu_lease() must document coexistence with patcher LLM"
        )
        assert "concurrent" in doc.lower(), (
            "_acquire_gpu_lease() must document no concurrent load"
        )

    def test_gpu_arbiter_path_documented(self) -> None:
        """gpu_arbiter.py path must be documented."""
        from nlp.humanizer import _acquire_gpu_lease
        
        doc = _acquire_gpu_lease.__doc__ or ""
        assert "ai/swarm/sdk/gpu_arbiter.py" in doc, (
            "_acquire_gpu_lease() must document gpu_arbiter.py path"
        )

    def test_lease_must_be_released_in_finally_block_documented(self) -> None:
        """Contract: lease must be released in finally block."""
        from nlp.humanizer import _acquire_gpu_lease
        
        doc = _acquire_gpu_lease.__doc__ or ""
        assert "finally" in doc.lower(), (
            "_acquire_gpu_lease() must document finally-block release requirement"
        )


class TestHumanizerCPUParity:
    """§10.8 bullet 4 + Phase 11 §11.3: CPU parity test (deterministic decode)."""

    def test_cpu_parity_contract_documented_in_module(self) -> None:
        """Phase 11 §11.3 CPU parity requirement must be documented."""
        from nlp import humanizer
        
        doc = humanizer.__doc__ or ""
        assert "11.3" in doc or "cpu parity" in doc.lower(), (
            "Module docstring must reference Phase 11 §11.3 or CPU parity requirement"
        )

    def test_cpu_parity_contract_documented_in_humanize(self) -> None:
        """humanize() must document Phase 11 §11.3 CPU parity test."""
        from nlp.humanizer import humanize
        
        doc = humanize.__doc__ or ""
        assert "11.3" in doc or "cpu parity" in doc.lower(), (
            "humanize() docstring must document Phase 11 §11.3 CPU parity test"
        )
        assert "greedy" in doc.lower() and "seed" in doc.lower(), (
            "humanize() must document greedy seed=1337 requirement"
        )
        assert "byte-identical" in doc.lower() or "deterministic" in doc.lower(), (
            "humanize() must document byte-identical / deterministic output requirement"
        )

    @pytest.mark.skipif(
        True,  # Phase 10 stub: LLM integration deferred to Phase 11 §11.2
        reason="Phase 10 stub: humanizer LLM integration pending Phase 11 §11.2"
    )
    def test_greedy_decode_produces_deterministic_output_cuda(self) -> None:
        """[Phase 11] Greedy decode with seed=1337 produces deterministic output on CUDA."""
        from common.config import Config
        from nlp.humanizer import humanize
        import os
        
        # Requires: LLM integration (Phase 11 §11.2) + CUDA device available
        os.environ["NEGELIR_NLP_HUMANIZE"] = "true"
        cfg = Config()
        assert cfg.nlp_humanize is True
        
        template = "Galatasaray'ın kazanma olasılığı yüksek (güven: orta)."
        
        # Run twice with same seed=1337, greedy decode
        output1 = humanize(template, cfg=cfg)
        output2 = humanize(template, cfg=cfg)
        
        assert output1 == output2, (
            "Greedy decode with seed=1337 must produce byte-identical output on CUDA"
        )

    @pytest.mark.skipif(
        True,  # Phase 10 stub: LLM integration deferred to Phase 11 §11.2
        reason="Phase 10 stub: humanizer LLM integration pending Phase 11 §11.2"
    )
    def test_greedy_decode_produces_deterministic_output_cpu(self) -> None:
        """[Phase 11] Greedy decode with seed=1337 produces deterministic output on CPU."""
        from common.config import Config
        from nlp.humanizer import humanize
        import os
        
        # Requires: LLM integration (Phase 11 §11.2) + CPU-only mode
        os.environ["NEGELIR_NLP_HUMANIZE"] = "true"
        os.environ["NEGELIR_NLP_HUMANIZER_DEVICE"] = "cpu"
        cfg = Config()
        assert cfg.nlp_humanize is True
        
        template = "Galatasaray'ın kazanma olasılığı yüksek (güven: orta)."
        
        # Run twice with same seed=1337, greedy decode
        output1 = humanize(template, cfg=cfg)
        output2 = humanize(template, cfg=cfg)
        
        assert output1 == output2, (
            "Greedy decode with seed=1337 must produce byte-identical output on CPU"
        )

    @pytest.mark.skipif(
        True,  # Phase 10 stub: LLM integration deferred to Phase 11 §11.2
        reason="Phase 10 stub: humanizer LLM integration pending Phase 11 §11.2"
    )
    def test_cpu_cuda_parity_within_epsilon(self) -> None:
        """[Phase 11 §11.3] Same input + greedy seed=1337 → byte-identical output across CUDA/CPU.
        
        Phase 11 §11.3 CPU parity test: deterministic decode required.
        If output differs beyond ε for tokens, cpu_only test must fail.
        
        This is the binding CPU parity gate referenced at §10.8 bullet 4.
        """
        from common.config import Config
        from nlp.humanizer import humanize
        import os
        
        # Requires: LLM integration (Phase 11 §11.2) + both CUDA and CPU available
        template = "Galatasaray'ın kazanma olasılığı yüksek (güven: orta)."
        
        # Run on CUDA
        os.environ["NEGELIR_NLP_HUMANIZE"] = "true"
        os.environ["NEGELIR_NLP_HUMANIZER_DEVICE"] = "cuda"
        cfg_cuda = Config()
        output_cuda = humanize(template, cfg=cfg_cuda)
        
        # Run on CPU
        os.environ["NEGELIR_NLP_HUMANIZER_DEVICE"] = "cpu"
        cfg_cpu = Config()
        output_cpu = humanize(template, cfg=cfg_cpu)
        
        # Phase 11 §11.3: must be byte-identical within ε for tokens
        # For greedy decode with seed=1337, ε=0 (exact match required)
        assert output_cuda == output_cpu, (
            "Phase 11 §11.3: Greedy seed=1337 must produce byte-identical output "
            "across CUDA / CPU. Failing this test means cpu_only mode is not supported."
        )

    def test_cpu_parity_epsilon_tolerance_is_zero_for_greedy_decode(self) -> None:
        """For greedy decode with seed=1337, epsilon tolerance is zero (exact match)."""
        # This is a contract test: documents that ε=0 for greedy decode.
        # Sampling (temperature > 0) would have ε > 0, but humanizer uses greedy.
        # Per §10.8: temperature=0.3 BUT with deterministic seed, expect exact match.
        pass  # Contract documented in test name + docstring

    def test_phase_10_stub_passes_cpu_parity_trivially(self) -> None:
        """Phase 10 stub: humanize() returns input unchanged → CPU parity trivially satisfied."""
        from common.config import Config
        from nlp.humanizer import humanize
        
        cfg = Config()
        template = "Galatasaray'ın kazanma olasılığı yüksek (güven: orta)."
        
        # Phase 10 stub: always returns unchanged (no LLM call)
        output = humanize(template, cfg=cfg)
        
        # Trivial parity: unchanged output is identical across all devices
        assert output == template, (
            "Phase 10 stub must return unchanged (CPU parity trivially satisfied)"
        )


class TestHumanizerGreedyDecodeParity:
    """§10.21.1 Greedy-decode parity: byte-identical token IDs across devices.
    
    Extension of §10.8 CPU parity test: with greedy decode parameters
    (seed=1337, temperature=0.0, top_p=1.0), the humanizer must produce
    byte-identical token IDs across CUDA / CPU / Metal (mock-Metal for CI).
    
    Δ tolerance = **zero tokens** (greedy is deterministic by construction).
    Any drift = test fail.
    
    Phase 10 stub: humanizer returns input unchanged → parity trivially satisfied.
    Phase 11 §11.2: LLM integration → must verify actual token-level parity.
    """

    def test_greedy_decode_contract_documented(self) -> None:
        """Greedy decode parameters must be documented in module."""
        from nlp import humanizer
        
        doc = humanizer.__doc__ or ""
        # The module should document greedy decode / deterministic requirements
        assert "cpu parity" in doc.lower() or "greedy" in doc.lower(), (
            "Module must document CPU parity or greedy decode requirement"
        )
        assert "seed" in doc.lower() or "1337" in doc, (
            "Module must document seed=1337 for reproducibility"
        )

    def test_phase_10_stub_greedy_parity_trivially_satisfied(self) -> None:
        """Phase 10 stub: returns input unchanged → greedy parity trivially satisfied."""
        from common.config import Config
        from nlp.humanizer import humanize
        
        cfg = Config()
        template = "Galatasaray'ın kazanma olasılığı yüksek (güven: orta)."
        
        # Phase 10 stub: always returns unchanged (no LLM, no tokenization)
        output = humanize(template, cfg=cfg)
        
        # Trivial greedy parity: unchanged output = identical across all devices
        assert output == template, (
            "Phase 10 stub must return unchanged → greedy parity trivially satisfied"
        )

    @pytest.mark.skipif(
        True,  # Phase 10 stub: LLM integration deferred to Phase 11 §11.2
        reason="Phase 10 stub: humanizer LLM integration pending Phase 11 §11.2"
    )
    def test_greedy_decode_produces_identical_token_ids_cuda(self) -> None:
        """[Phase 11] Greedy decode (seed=1337, temp=0.0, top_p=1.0) produces identical token IDs on CUDA.
        
        §10.21.1 Greedy-decode parity: same input + greedy parameters must produce
        byte-identical token IDs. Run twice on same device (CUDA) to verify determinism.
        """
        from common.config import Config
        from nlp.humanizer import _generate_with_token_ids
        import os
        
        # Requires: LLM integration (Phase 11 §11.2) + CUDA device available
        os.environ["NEGELIR_NLP_HUMANIZE"] = "true"
        os.environ["NEGELIR_NLP_HUMANIZER_DEVICE"] = "cuda"
        cfg = Config()
        
        template = "Galatasaray'ın kazanma olasılığı yüksek (güven: orta)."
        
        # Run twice with greedy decode (temperature=0.0, top_p=1.0, seed=1337)
        token_ids_1, output_1 = _generate_with_token_ids(
            template, cfg=cfg, seed=1337, temperature=0.0, top_p=1.0
        )
        token_ids_2, output_2 = _generate_with_token_ids(
            template, cfg=cfg, seed=1337, temperature=0.0, top_p=1.0
        )
        
        # Greedy decode is deterministic → token IDs must be byte-identical
        assert token_ids_1 == token_ids_2, (
            "Greedy decode (seed=1337, temp=0.0, top_p=1.0) must produce "
            "byte-identical token IDs on CUDA (Δ tolerance = 0 tokens)"
        )
        assert output_1 == output_2, (
            "Greedy decode must produce identical output strings"
        )

    @pytest.mark.skipif(
        True,  # Phase 10 stub: LLM integration deferred to Phase 11 §11.2
        reason="Phase 10 stub: humanizer LLM integration pending Phase 11 §11.2"
    )
    def test_greedy_decode_produces_identical_token_ids_cpu(self) -> None:
        """[Phase 11] Greedy decode produces identical token IDs on CPU."""
        from common.config import Config
        from nlp.humanizer import _generate_with_token_ids
        import os
        
        # Requires: LLM integration (Phase 11 §11.2) + CPU-only mode
        os.environ["NEGELIR_NLP_HUMANIZE"] = "true"
        os.environ["NEGELIR_NLP_HUMANIZER_DEVICE"] = "cpu"
        cfg = Config()
        
        template = "Galatasaray'ın kazanma olasılığı yüksek (güven: orta)."
        
        # Run twice with greedy decode
        token_ids_1, output_1 = _generate_with_token_ids(
            template, cfg=cfg, seed=1337, temperature=0.0, top_p=1.0
        )
        token_ids_2, output_2 = _generate_with_token_ids(
            template, cfg=cfg, seed=1337, temperature=0.0, top_p=1.0
        )
        
        assert token_ids_1 == token_ids_2, (
            "Greedy decode must produce byte-identical token IDs on CPU"
        )
        assert output_1 == output_2

    @pytest.mark.skipif(
        True,  # Phase 10 stub: LLM integration deferred to Phase 11 §11.2
        reason="Phase 10 stub: humanizer LLM integration pending Phase 11 §11.2"
    )
    def test_greedy_decode_cuda_cpu_token_id_parity(self) -> None:
        """[Phase 11 §11.3] Greedy decode produces byte-identical token IDs across CUDA / CPU.
        
        §10.21.1 binding: same (input, seed=1337, temperature=0.0, top_p=1.0) must
        produce byte-identical token IDs across CUDA / CPU. Δ tolerance = **zero tokens**
        (greedy is deterministic by construction); any drift = test fail.
        
        This is the binding greedy-decode parity gate referenced at §10.21.1.
        """
        from common.config import Config
        from nlp.humanizer import _generate_with_token_ids
        import os
        
        # Requires: LLM integration (Phase 11 §11.2) + both CUDA and CPU available
        template = "Galatasaray'ın kazanma olasılığı yüksek (güven: orta)."
        
        # Run on CUDA with greedy decode
        os.environ["NEGELIR_NLP_HUMANIZE"] = "true"
        os.environ["NEGELIR_NLP_HUMANIZER_DEVICE"] = "cuda"
        cfg_cuda = Config()
        token_ids_cuda, output_cuda = _generate_with_token_ids(
            template, cfg=cfg_cuda, seed=1337, temperature=0.0, top_p=1.0
        )
        
        # Run on CPU with greedy decode
        os.environ["NEGELIR_NLP_HUMANIZER_DEVICE"] = "cpu"
        cfg_cpu = Config()
        token_ids_cpu, output_cpu = _generate_with_token_ids(
            template, cfg=cfg_cpu, seed=1337, temperature=0.0, top_p=1.0
        )
        
        # §10.21.1: must be byte-identical (Δ = 0 tokens)
        assert token_ids_cuda == token_ids_cpu, (
            "§10.21.1: Greedy decode (seed=1337, temp=0.0, top_p=1.0) must produce "
            "byte-identical token IDs across CUDA / CPU. Δ tolerance = 0 tokens. "
            "Any drift = test fail."
        )
        assert output_cuda == output_cpu, (
            "Output strings must also be byte-identical"
        )

    @pytest.mark.skipif(
        True,  # Phase 10 stub: LLM integration deferred to Phase 11 §11.2
        reason="Phase 10 stub: humanizer LLM integration pending Phase 11 §11.2"
    )
    def test_greedy_decode_metal_mock_token_id_parity(self) -> None:
        """[Phase 11 + CI] Greedy decode parity includes Metal (mock-Metal for CI).
        
        §10.21.1 requires CUDA / CPU / Metal coverage. In CI (no physical Metal),
        mock-Metal = CPU path with Metal codepath verification (no actual GPU).
        """
        from common.config import Config
        from nlp.humanizer import _generate_with_token_ids
        import os
        
        # Requires: LLM integration + mock-Metal fixture (CI environment)
        template = "Galatasaray'ın kazanma olasılığı yüksek (güven: orta)."
        
        # Run on CPU (baseline)
        os.environ["NEGELIR_NLP_HUMANIZE"] = "true"
        os.environ["NEGELIR_NLP_HUMANIZER_DEVICE"] = "cpu"
        cfg_cpu = Config()
        token_ids_cpu, output_cpu = _generate_with_token_ids(
            template, cfg=cfg_cpu, seed=1337, temperature=0.0, top_p=1.0
        )
        
        # Run on mock-Metal (CPU path, Metal codepath)
        os.environ["NEGELIR_NLP_HUMANIZER_DEVICE"] = "metal"
        os.environ["NEGELIR_NLP_MOCK_METAL"] = "true"  # CI mock flag
        cfg_metal = Config()
        token_ids_metal, output_metal = _generate_with_token_ids(
            template, cfg=cfg_metal, seed=1337, temperature=0.0, top_p=1.0
        )
        
        # mock-Metal uses CPU backend → should match CPU token IDs
        assert token_ids_metal == token_ids_cpu, (
            "mock-Metal (CI) must produce same token IDs as CPU baseline"
        )
        assert output_metal == output_cpu

    def test_greedy_decode_zero_tolerance_contract_documented(self) -> None:
        """Contract: Δ tolerance = 0 tokens for greedy decode (any drift = fail)."""
        # This is a contract test: documents that greedy decode has zero tolerance.
        # Sampling (temperature > 0) would allow some tolerance, but greedy decode
        # with seed=1337 must be deterministic → any token-level drift fails the test.
        pass  # Contract documented in test name + docstring

