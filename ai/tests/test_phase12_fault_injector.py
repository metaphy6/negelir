"""Phase 12 §12.4 + §12.9–§12.11 FaultInjector & chaos scenario tests.

Tests the deterministic corruption and injection utilities used by
§12.9–§12.11 chaos drills. Marked skip pending CI harness integration.

Usage:
  PYTHONPATH=ai pytest ai/tests/test_phase12_fault_injector.py -v
"""
from __future__ import annotations

import hashlib
import hmac
import json
import pytest
from xops.chaos.scenarios import FaultInjector, DataIntegrityMixin, SecurityChaosMixin, RecoveryDRMixin


class TestFaultInjector:
    """Tests for the FaultInjector utility class (§12.4 + §12.9)."""

    def test_corrupt_bytes_deterministic(self):
        """Verify FaultInjector corruption is deterministic given seed."""
        data = b"hello world"
        injector1 = FaultInjector(seed=42)
        injector2 = FaultInjector(seed=42)

        corrupted1 = injector1.corrupt_bytes(data, num_flips=1)
        corrupted2 = injector2.corrupt_bytes(data, num_flips=1)

        assert corrupted1 == corrupted2, "Same seed should produce same corruption"
        assert corrupted1 != data, "Corruption should change data"

    def test_corrupt_bytes_offset(self):
        """Verify FaultInjector can corrupt at a specific offset."""
        data = b"hello world"
        injector = FaultInjector(seed=42)

        corrupted = injector.corrupt_bytes(data, num_flips=1, offset=0)
        assert corrupted[0] != data[0], "Byte at offset 0 should be corrupted"
        assert corrupted[1:] == data[1:], "Other bytes should be unchanged"

    def test_mutate_hmac_key(self):
        """Verify HMAC key mutation produces different signatures."""
        message = b"test message"
        key = b"secret_key_1234567890"

        injector = FaultInjector(seed=43)
        original_hmac = hmac.new(key, message, hashlib.sha256).digest()
        mutated_key = injector.mutate_hmac_key(key, num_flips=1)
        mutated_hmac = hmac.new(mutated_key, message, hashlib.sha256).digest()

        assert original_hmac != mutated_hmac, "Mutated key should produce different HMAC"

    def test_mutate_message_signature_fails(self):
        """Verify mutating a message breaks signature verification."""
        message = b"test message"
        key = b"secret_key_1234567890"

        signature = hmac.new(key, message, hashlib.sha256).digest()

        injector = FaultInjector(seed=44)
        mutated_message = injector.mutate_message(message, num_flips=1)
        computed_hmac = hmac.new(key, mutated_message, hashlib.sha256).digest()

        assert computed_hmac != signature, "Mutated message should fail signature verification"

    def test_corrupt_json_field(self):
        """Verify JSON field corruption."""
        data = {
            "prediction": {
                "answer": {
                    "text": "hello"
                },
                "confidence": 0.95
            }
        }

        injector = FaultInjector(seed=45)
        corrupted = injector.corrupt_json_field(data, "prediction.answer.text")

        assert corrupted["prediction"]["answer"]["text"] != "hello"
        assert corrupted["prediction"]["confidence"] == 0.95
        assert data["prediction"]["answer"]["text"] == "hello", "Original not mutated"

    def test_corrupt_json_field_nonexistent(self):
        """Verify corrupting nonexistent field returns unchanged data."""
        data = {"a": 1}
        injector = FaultInjector(seed=46)
        result = injector.corrupt_json_field(data, "nonexistent.path")
        assert result == data


class TestFaultInjectorProductionSafety:
    """Tests for §12.4.1 Production-safety guarantees."""

    def test_fault_injector_is_noop_in_prod(self):
        """Test that FaultInjector is a no-op when cfg.fault_injection_enabled=false (§12.4.1).

        This test verifies the production-safety contract: when fault injection
        is disabled, the FaultInjector must act as a perfect pass-through with
        zero side effects or performance impact.
        """
        from common.config import cfg
        from xops.chaos.scenarios import FaultInjector, FaultSchedule, FaultEvent, FaultOp

        # Save original state
        original_enabled = cfg.fault_injection_enabled

        try:
            # Verify in production (disabled) mode
            cfg.fault_injection_enabled = False

            schedule = FaultSchedule(
                name="P12-4-A",
                seed=42,
                faults=(
                    FaultEvent(target="redis_get", op=FaultOp.DELAY, after_n_calls=0),
                    FaultEvent(target="postgres_write", op=FaultOp.DROP, after_n_calls=0),
                ),
            )

            injector = FaultInjector(schedule)

            # Test 1: should_fault should always return False in prod mode
            assert not injector.should_fault("redis_get"), \
                "FaultInjector should not fault when fault_injection_enabled=False"
            assert not injector.should_fault("postgres_write"), \
                "FaultInjector should not fault any target in prod mode"

            # Test 2: fault_before_op should always return None in prod mode
            assert injector.fault_before_op("redis_get") is None, \
                "fault_before_op must return None (no fault applied) in prod mode"
            assert injector.fault_before_op("postgres_write") is None, \
                "fault_before_op must return None for all targets in prod mode"

            # Test 3: Call many times - should never fault
            for i in range(100):
                result = injector.fault_before_op("any_target")
                assert result is None, f"Iteration {i}: Expected None in prod mode"

            # Test 4: Stats show no faults applied
            stats = injector.stats()
            assert stats["enabled"] is False, "Stats should show fault injection disabled"
            assert len(stats["faults_applied"]) == 0, \
                "No faults should be recorded as applied in prod mode"

        finally:
            # Restore original state
            cfg.fault_injection_enabled = original_enabled


class TestChaosInfrastructure:
    """Tests for §12.4 chaos infrastructure (Toxiproxy, Pumba, teardown)."""

    def test_chaos_teardown_is_clean(self):
        """Test that make chaos.down leaves the system in a clean, pre-chaos state (§12.4.3).

        Verifies the idempotent-teardown property: after a chaos drill (with
        faults and corruptions), the teardown process (make chaos.down) must
        remove all injected faults, orphaned containers, and chaos namespaces,
        leaving the system byte-identical to the pre-chaos state.

        Note: This is a proof-of-concept test that verifies the *existence* and
        *structure* of the cleanup harness. Full end-to-end cleanup is tested
        in the integration suite (§12.13).
        """
        from pathlib import Path
        import docker

        # Test 1: Verify docker-compose.chaos.yml exists and has valid structure
        repo_root = Path(__file__).resolve().parents[2]
        chaos_compose = repo_root / "docker-compose.chaos.yml"
        
        assert chaos_compose.exists(), \
            f"docker-compose.chaos.yml must exist for chaos teardown (§12.4.2), missing at {chaos_compose}"

        with open(chaos_compose) as f:
            content = f.read()
            
        # Verify minimal structure for cleanup
        assert "services:" in content or "version:" in content, \
            "docker-compose.chaos.yml must be valid YAML with services"
        assert "toxiproxy" in content.lower() or "pumba" in content.lower(), \
            "docker-compose.chaos.yml must reference toxiproxy and/or pumba for chaos injection"

        # Test 2: Verify chaos profile isolation
        assert "COMPOSE_PROFILE" in content or "profiles:" in content, \
            "docker-compose.chaos.yml must use profile gating to prevent accidental chaos on default profile"

        # Test 3: Verify cleanup targets exist in Makefile
        makefile = repo_root / "Makefile"
        with open(makefile) as f:
            makefile_content = f.read()

        assert "chaos.down" in makefile_content, \
            "make chaos.down target must exist for idempotent cleanup"
        assert "chaos.up" in makefile_content, \
            "make chaos.up target must exist to bring up chaos profile"

        # Test 4: Verify xops/chaos module has cleanup infrastructure
        chaos_module = repo_root / "xops" / "chaos"
        assert chaos_module.exists(), \
            "xops/chaos must exist to house chaos harness (§12.4)"
        
        cleanup_files = list(chaos_module.glob("*.py"))
        assert len(cleanup_files) > 0, \
            "xops/chaos must have Python modules for cleanup (scenarios.py, etc.)"


class TestDataIntegrityScenarios:
    """Tests for §12.9 Data-Integrity scenarios."""

    @pytest.mark.skip(reason="harness implementation deferred (Phase 12 §12.4), owner=phase-12-lead, P12-chaos")
    def test_chaos_tamper_hmac(self):
        """Test P12-9-A: tamper with HMAC and assert detection."""
        # TODO: Implement full scenario test
        pass

    @pytest.mark.skip(reason="harness implementation deferred (Phase 12 §12.4), owner=phase-12-lead, P12-chaos")
    def test_chaos_checksum_mismatch(self):
        """Test P12-9-B: checksum mismatch detection."""
        # TODO: Implement full scenario test
        pass

    @pytest.mark.skip(reason="harness implementation deferred (Phase 12 §12.4), owner=phase-12-lead, P12-chaos")
    def test_chaos_audit_chain_break(self):
        """Test P12-9-C: audit hash-chain break detection."""
        # TODO: Implement full scenario test
        pass

    @pytest.mark.skip(reason="harness implementation deferred (Phase 12 §12.4), owner=phase-12-lead, P12-chaos")
    def test_chaos_replay_storm(self):
        """Test P12-9-D: 5× replay of envelope stream through idempotent consumers."""
        # TODO: Implement full scenario test
        pass

    @pytest.mark.skip(reason="harness implementation deferred (Phase 12 §12.4), owner=phase-12-lead, P12-chaos")
    def test_chaos_split_write(self):
        """Test P12-9-E: mid-write kill and clean recovery."""
        # TODO: Implement full scenario test
        pass

    @pytest.mark.skip(reason="harness implementation deferred (Phase 12 §12.4), owner=phase-12-lead, P12-chaos")
    def test_chaos_erasure_under_chaos(self):
        """Test P12-9-F: GDPR erasure during bus flap."""
        # TODO: Implement full scenario test
        pass

    @pytest.mark.skip(reason="harness implementation deferred (Phase 12 §12.4), owner=phase-12-lead, P12-chaos")
    def test_chaos_audit_pii_scan(self):
        """Test P12-9-G: residual PII scan after chaos run."""
        # TODO: Implement full scenario test
        pass


class TestSecurityChaosSencarios:
    """Tests for §12.10 Security Chaos scenarios."""

    @pytest.mark.skip(reason="harness implementation deferred (Phase 12 §12.4), owner=phase-12-lead, P12-chaos")
    def test_chaos_prompt_injection(self):
        """Test P12-10-A: prompt injection corpus replay."""
        # TODO: Implement full scenario test
        pass

    @pytest.mark.skip(reason="harness implementation deferred (Phase 12 §12.4), owner=phase-12-lead, P12-chaos")
    def test_chaos_homoglyph_rtl_flood(self):
        """Test P12-10-B: confusable character + RTL + zero-width."""
        # TODO: Implement full scenario test
        pass

    @pytest.mark.skip(reason="harness implementation deferred (Phase 12 §12.4), owner=phase-12-lead, P12-chaos")
    def test_chaos_oversize_zerowidth(self):
        """Test P12-10-C: oversized + zero-width-padded queries."""
        # TODO: Implement full scenario test
        pass

    @pytest.mark.skip(reason="harness implementation deferred (Phase 12 §12.4), owner=phase-12-lead, P12-chaos")
    def test_chaos_slur_obfuscation(self):
        """Test P12-10-D: obfuscated-slur corpus replay."""
        # TODO: Implement full scenario test
        pass

    @pytest.mark.skip(reason="harness implementation deferred (Phase 12 §12.4), owner=phase-12-lead, P12-chaos")
    def test_chaos_credential_stuffing(self):
        """Test P12-10-E: burst auth attacks."""
        # TODO: Implement full scenario test
        pass

    @pytest.mark.skip(reason="harness implementation deferred (Phase 12 §12.4), owner=phase-12-lead, P12-chaos")
    def test_chaos_xff_spoof(self):
        """Test P12-10-E: X-Forwarded-For spoofing."""
        # TODO: Implement full scenario test
        pass

    @pytest.mark.skip(reason="harness implementation deferred (Phase 12 §12.4), owner=phase-12-lead, P12-chaos")
    def test_chaos_redis_fail_open(self):
        """Test P12-10-F: Redis failure with rate-limit fallback."""
        # TODO: Implement full scenario test
        pass

    @pytest.mark.skip(reason="harness implementation deferred (Phase 12 §12.4), owner=phase-12-lead, P12-chaos")
    def test_chaos_token_replay(self):
        """Test P12-10-G: token replay detection."""
        # TODO: Implement full scenario test
        pass

    @pytest.mark.skip(reason="harness implementation deferred (Phase 12 §12.4), owner=phase-12-lead, P12-chaos")
    def test_chaos_cert_expiry(self):
        """Test P12-10-H: expired certificate handling."""
        # TODO: Implement full scenario test
        pass

    @pytest.mark.skip(reason="harness implementation deferred (Phase 12 §12.4), owner=phase-12-lead, P12-chaos")
    def test_chaos_key_rotation_midflight(self):
        """Test P12-10-I: key rotation during flight."""
        # TODO: Implement full scenario test
        pass

    @pytest.mark.skip(reason="harness implementation deferred (Phase 12 §12.4), owner=phase-12-lead, P12-chaos")
    def test_chaos_secret_unreadable(self):
        """Test P12-10-I-alt: key file permission failures."""
        # TODO: Implement full scenario test
        pass

    @pytest.mark.skip(reason="harness implementation deferred (Phase 12 §12.4), owner=phase-12-lead, P12-chaos")
    def test_chaos_tampered_binary(self):
        """Test P12-10-J: binary integrity gates."""
        # TODO: Implement full scenario test
        pass

    @pytest.mark.skip(reason="harness implementation deferred (Phase 12 §12.4), owner=phase-12-lead, P12-chaos")
    def test_chaos_cve_injection(self):
        """Test P12-10-K: CVE scan gate."""
        # TODO: Implement full scenario test
        pass


class TestRecoveryDRScenarios:
    """Tests for §12.11 Recovery & DR scenarios."""

    @pytest.mark.skip(reason="harness implementation deferred (Phase 12 §12.4), owner=phase-12-lead, P12-chaos")
    def test_chaos_restore_drill(self):
        """Test P12-11-A: backup→restore→verify cycle."""
        # TODO: Implement full scenario test
        pass

    @pytest.mark.skip(reason="harness implementation deferred (Phase 12 §12.4), owner=phase-12-lead, P12-chaos")
    def test_chaos_cold_start_under_outage(self):
        """Test P12-11-B: cold boot with storage denied."""
        # TODO: Implement full scenario test
        pass

    @pytest.mark.skip(reason="harness implementation deferred (Phase 12 §12.4), owner=phase-12-lead, P12-chaos")
    def test_chaos_spool_drain(self):
        """Test P12-11-C: spool drainage after bus heal."""
        # TODO: Implement full scenario test
        pass

    @pytest.mark.skip(reason="harness implementation deferred (Phase 12 §12.4), owner=phase-12-lead, P12-chaos")
    def test_chaos_leader_handover(self):
        """Test P12-11-D: leader kill + standby election."""
        # TODO: Implement full scenario test
        pass

    @pytest.mark.skip(reason="harness implementation deferred (Phase 12 §12.4), owner=phase-12-lead, P12-chaos")
    def test_chaos_dr_safe_mode(self):
        """Test P12-11-E: lexicon failure → safe mode."""
        # TODO: Implement full scenario test
        pass

    @pytest.mark.skip(reason="harness implementation deferred (Phase 12 §12.4), owner=phase-12-lead, P12-chaos")
    def test_chaos_rolling_deploy(self):
        """Test P12-11-F: mixed-version deployment."""
        # TODO: Implement full scenario test
        pass
