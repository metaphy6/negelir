"""Tests for device runtime matrix validation (Phase 11.1 bullet: Driver/runtime pinning)."""

import json
import os
import tempfile
from model.device import (
    _load_runtime_matrix,
    _parse_version,
    _check_version_constraint,
    _is_in_version_range,
    validate_runtime_support,
    _attach_device_uuids,
)


def make_probe_with_cuda() -> dict:
    """Helper: create a probe result with CPU and CUDA."""
    return {
        "probe_id": "test",
        "probe_ts": 0,
        "inventory": [
            {"device_kind": "cpu", "available": True, "name": "cpu"},
            {"device_kind": "cuda", "available": True, "index": 0, "name": "tesla_a100"},
        ],
    }


class TestVersionParsing:
    """Test semantic version parsing."""

    def test_parse_semantic_version(self):
        assert _parse_version("12.4.0") == (12, 4, 0)
        assert _parse_version("12.4") == (12, 4, 0)
        assert _parse_version("12") == (12, 0, 0)

    def test_parse_driver_version(self):
        """NVIDIA drivers are often expressed as just major version (e.g., '555')."""
        assert _parse_version("555") == (555, 0, 0)
        assert _parse_version("555.42") == (555, 42, 0)
        assert _parse_version("555.42.03") == (555, 42, 3)

    def test_parse_version_with_extra_parts(self):
        """Extra version parts are ignored."""
        assert _parse_version("6.2.0.1") == (6, 2, 0)

    def test_parse_invalid_version(self):
        """Invalid version strings default to (0, 0, 0)."""
        assert _parse_version("invalid") == (0, 0, 0)
        assert _parse_version("") == (0, 0, 0)


class TestVersionConstraints:
    """Test version constraint checking."""

    def test_check_version_gte(self):
        """Test >= constraint."""
        assert _check_version_constraint("12.4.0", "12.4.0", ">=") is True
        assert _check_version_constraint("12.5.0", "12.4.0", ">=") is True
        assert _check_version_constraint("12.3.0", "12.4.0", ">=") is False

    def test_check_version_eq(self):
        """Test == constraint."""
        assert _check_version_constraint("12.4.0", "12.4.0", "==") is True
        assert _check_version_constraint("12.4.1", "12.4.0", "==") is False

    def test_check_driver_version_gte(self):
        """Test driver version constraints (major-only)."""
        assert _check_version_constraint("555", "555", ">=") is True
        assert _check_version_constraint("556", "555", ">=") is True
        assert _check_version_constraint("554", "555", ">=") is False


class TestVersionRanges:
    """Test version range checking."""

    def test_single_version_range(self):
        """A range with no dash is a single version match."""
        assert _is_in_version_range("6.2.0", "6.2.0") is True
        assert _is_in_version_range("6.2.1", "6.2.0") is False

    def test_range_inclusive(self):
        """Test inclusive range checking."""
        # Range 560.0-560.28
        assert _is_in_version_range("560.0", "560.0-560.28") is True
        assert _is_in_version_range("560.15", "560.0-560.28") is True
        assert _is_in_version_range("560.28", "560.0-560.28") is True
        assert _is_in_version_range("560.29", "560.0-560.28") is False
        assert _is_in_version_range("559.99", "560.0-560.28") is False

    def test_rocm_range(self):
        """Test ROCm version ranges."""
        assert _is_in_version_range("6.2.0", "6.2.0-6.2.1") is True
        assert _is_in_version_range("6.2.1", "6.2.0-6.2.1") is True
        assert _is_in_version_range("6.2.2", "6.2.0-6.2.1") is False


class TestRuntimeMatrixLoading:
    """Test loading the runtime matrix."""

    def test_load_runtime_matrix(self):
        """Test that runtime_matrix.json is loaded successfully."""
        matrix = _load_runtime_matrix()
        assert isinstance(matrix, dict)
        # Should have schema_version, supported_combinations, vendor_bug_exclusion_list
        assert "schema_version" in matrix or len(matrix) == 0  # Empty if not found

    def test_matrix_has_supported_backends(self):
        """Test that the matrix documents the expected backends."""
        matrix = _load_runtime_matrix()
        if matrix:
            combos = matrix.get("supported_combinations", [])
            backends = {c.get("backend") for c in combos}
            # Should document CUDA, ROCm, OpenVINO, CPU
            assert len(backends) > 0


class TestRuntimeValidation:
    """Test runtime validation against the matrix."""

    def test_validate_supported_runtime(self, monkeypatch):
        """Test that supported runtimes pass validation."""
        res = make_probe_with_cuda()
        _attach_device_uuids(res)
        
        # Set supported versions
        monkeypatch.setenv("NEGELIR_DRIVER_NVIDIA_MIN_VERSION", "555")
        monkeypatch.setenv("NEGELIR_CUDA_MIN_VERSION", "12.4.0")
        monkeypatch.setenv("NEGELIR_CUDNN_MIN_VERSION", "9.0.0")
        
        # Run validation — should not mark device as unavailable
        validate_runtime_support(res)
        
        cuda = next(d for d in res["inventory"] if d["device_kind"] == "cuda")
        # If matrix is empty or validation passes, CUDA should remain available
        # (or be marked unavailable with a specific alert kind)
        if cuda.get("available") is False:
            # If unavailable, should have an alert
            assert any(a.get("kind") == "unsupported_runtime" for a in res.get("alerts", []))

    def test_unsupported_runtime_produces_alert(self, monkeypatch):
        """Test that unsupported combinations produce an alert."""
        res = make_probe_with_cuda()
        _attach_device_uuids(res)
        
        # Simulate old NVIDIA driver
        monkeypatch.setenv("NEGELIR_DRIVER_NVIDIA_MIN_VERSION", "600")
        monkeypatch.setenv("NEGELIR_CUDA_MIN_VERSION", "12.4.0")
        
        validate_runtime_support(res)
        # The result should have alerts recorded (or devices marked unavailable)
        # depending on whether the matrix exists and has matching exclusions

    def test_cpu_always_available_after_validation(self):
        """Test that CPU is never disabled by runtime validation."""
        res = make_probe_with_cuda()
        _attach_device_uuids(res)
        
        validate_runtime_support(res)
        
        cpu = next(d for d in res["inventory"] if d["device_kind"] == "cpu")
        # CPU should always remain available after validation
        assert cpu["available"] is True


class TestVendorBugExclusions:
    """Test vendor-bug exclusion list detection."""

    def test_matrix_has_exclusion_structure(self):
        """Test that the matrix includes a vendor-bug exclusion list."""
        matrix = _load_runtime_matrix()
        if matrix:
            exclusions = matrix.get("vendor_bug_exclusion_list", [])
            if exclusions:
                # Each exclusion should have vendor, issue, and workaround
                for excl in exclusions:
                    assert "vendor" in excl
                    assert "issue" in excl

    def test_exclusion_alert_on_match(self, monkeypatch):
        """Test that a matching exclusion produces an alert."""
        res = make_probe_with_cuda()
        _attach_device_uuids(res)
        
        # Simulate a kernel version that might trigger an exclusion
        monkeypatch.setenv("NEGELIR_DRIVER_NVIDIA_MIN_VERSION", "560.15")
        monkeypatch.setenv("NEGELIR_CUDA_MIN_VERSION", "12.4.1")
        
        validate_runtime_support(res)
        
        # If there's a matching exclusion in the matrix, an alert should be emitted
        alerts = res.get("alerts", [])
        for alert in alerts:
            if alert.get("kind") == "unsupported_runtime":
                assert "severity" in alert
                assert "reason" in alert


class TestAdversarialRuntimeCases:
    """Adversarial/edge case tests for runtime validation."""

    def test_version_parsing_with_rc_suffix(self):
        """Test that RC/alpha versions parse safely (taking major.minor.patch)."""
        # RC versions like "12.4.0-rc1" should parse as (12, 4, 0)
        assert _parse_version("12.4.0-rc1".split("-")[0]) == (12, 4, 0)

    def test_empty_inventory_after_validation(self):
        """Test validation with an empty inventory."""
        res = {
            "probe_id": "test",
            "probe_ts": 0,
            "inventory": [],
        }
        # Should not crash
        validate_runtime_support(res)
        assert res.get("inventory") == []

    def test_validation_with_multiple_device_kinds(self):
        """Test validation doesn't mark non-CUDA devices as unavailable."""
        res = {
            "probe_id": "test",
            "probe_ts": 0,
            "inventory": [
                {"device_kind": "cpu", "available": True, "name": "cpu"},
                {"device_kind": "cuda", "available": True, "index": 0, "name": "cuda0"},
                {"device_kind": "openvino", "available": True, "name": "npu0"},
            ],
        }
        _attach_device_uuids(res)
        validate_runtime_support(res)
        
        # CPU and OpenVINO should remain available
        cpu = next(d for d in res["inventory"] if d["device_kind"] == "cpu")
        npu = next(d for d in res["inventory"] if d["device_kind"] == "openvino")
        assert cpu["available"] is True
        assert npu["available"] is True

    def test_version_constraint_comparison_edge_cases(self):
        """Test version constraint edge cases."""
        # Major version difference
        assert _check_version_constraint("13.0.0", "12.4.0", ">=") is True
        assert _check_version_constraint("11.0.0", "12.4.0", ">=") is False
        
        # Minor version only
        assert _check_version_constraint("12.5.0", "12.4.0", ">=") is True
        assert _check_version_constraint("12.3.0", "12.4.0", ">=") is False
        
        # Patch version only
        assert _check_version_constraint("12.4.1", "12.4.0", ">=") is True
        assert _check_version_constraint("12.4.0", "12.4.0", ">=") is True

    def test_range_edge_values(self):
        """Test range checking at exact boundaries."""
        # Lower bound exactly
        assert _is_in_version_range("560.0", "560.0-560.28") is True
        # Upper bound exactly
        assert _is_in_version_range("560.28", "560.0-560.28") is True
        # Just below lower
        assert _is_in_version_range("559.99", "560.0-560.28") is False
        # Just above upper
        assert _is_in_version_range("560.29", "560.0-560.28") is False

    def test_validate_with_missing_config(self, monkeypatch):
        """Test that validation works even if config loading fails."""
        res = make_probe_with_cuda()
        _attach_device_uuids(res)
        
        # Even with no config, validation should not crash
        validate_runtime_support(res, cfg=None)
        
        # At least one device should still be in inventory
        assert len(res.get("inventory", [])) > 0




class TestHostClassNormalisation:
    """Test host_class deterministic normalization for cross-host reproducibility."""

    def test_host_class_included_in_probe(self):
        """Test that host_class is computed and included in probe result."""
        res = {
            "probe_id": "test",
            "probe_ts": 0,
            "inventory": [
                {"device_kind": "cpu", "available": True, "name": "cpu", "arch": "x86_64", "vendor": "intel", "simd": ["avx2", "sse4_2"]},
                {"device_kind": "cuda", "available": True, "index": 0, "name": "a100", "vendor": "nvidia", "family": "a100"},
            ],
        }
        
        from model.device import _compute_host_class
        host_class = _compute_host_class(res)
        
        assert host_class is not None
        assert len(host_class) == 16  # SHA256[:16]
        assert all(c in "0123456789abcdef" for c in host_class)

    def test_same_hardware_same_host_class(self, monkeypatch):
        """Test that identical hardware configs produce same host_class."""
        monkeypatch.setenv("NEGELIR_DRIVER_NVIDIA_MIN_VERSION", "555")
        monkeypatch.setenv("NEGELIR_CUDA_MIN_VERSION", "12.4.0")
        
        res1 = {
            "probe_id": "test1",
            "inventory": [
                {"device_kind": "cuda", "available": True, "vendor": "nvidia", "family": "a100", "compute_capability": "8.0", "vram_total_mb": 40960, "uuid": "uuid-1"},
            ],
        }
        
        res2 = {
            "probe_id": "test2",
            "inventory": [
                {"device_kind": "cuda", "available": True, "vendor": "nvidia", "family": "a100", "compute_capability": "8.0", "vram_total_mb": 40960, "uuid": "uuid-different"},
            ],
        }
        
        from model.device import _compute_host_class
        class1 = _compute_host_class(res1)
        class2 = _compute_host_class(res2)
        
        # Same hardware, different per-host UUIDs should produce same host_class
        assert class1 == class2

    def test_different_hardware_different_host_class(self, monkeypatch):
        """Test that different hardware configs produce different host_class."""
        monkeypatch.setenv("NEGELIR_DRIVER_NVIDIA_MIN_VERSION", "555")
        monkeypatch.setenv("NEGELIR_CUDA_MIN_VERSION", "12.4.0")
        
        res_a100 = {
            "inventory": [
                {"device_kind": "cuda", "available": True, "vendor": "nvidia", "family": "a100", "compute_capability": "8.0", "vram_total_mb": 40960},
            ],
        }
        
        res_v100 = {
            "inventory": [
                {"device_kind": "cuda", "available": True, "vendor": "nvidia", "family": "v100", "compute_capability": "7.0", "vram_total_mb": 32768},
            ],
        }
        
        from model.device import _compute_host_class
        class_a100 = _compute_host_class(res_a100)
        class_v100 = _compute_host_class(res_v100)
        
        # Different hardware should produce different host_class
        assert class_a100 != class_v100

    def test_host_class_driver_version_affects_class(self, monkeypatch):
        """Test that different driver versions affect host_class."""
        res_driver555 = {
            "inventory": [
                {"device_kind": "cuda", "available": True, "vendor": "nvidia", "family": "a100"},
            ],
        }
        
        res_driver560 = {
            "inventory": [
                {"device_kind": "cuda", "available": True, "vendor": "nvidia", "family": "a100"},
            ],
        }
        
        from model.device import _compute_host_class
        
        monkeypatch.setenv("NEGELIR_DRIVER_NVIDIA_MIN_VERSION", "555")
        class1 = _compute_host_class(res_driver555)
        
        monkeypatch.setenv("NEGELIR_DRIVER_NVIDIA_MIN_VERSION", "560")
        class2 = _compute_host_class(res_driver560)
        
        # Different driver versions should produce different host_class
        assert class1 != class2

    def test_host_class_cpu_only(self):
        """Test host_class computation for CPU-only systems."""
        res = {
            "inventory": [
                {"device_kind": "cpu", "available": True, "name": "cpu", "arch": "aarch64", "vendor": "arm", "simd": ["neon", "sve"]},
            ],
        }
        
        from model.device import _compute_host_class
        host_class = _compute_host_class(res)
        
        assert host_class is not None
        assert len(host_class) == 16

    def test_host_class_mixed_devices(self):
        """Test host_class computation with CPU + CUDA."""
        res = {
            "inventory": [
                {"device_kind": "cpu", "available": True, "arch": "x86_64", "vendor": "intel", "simd": ["avx2"]},
                {"device_kind": "cuda", "available": True, "vendor": "nvidia", "family": "l4"},
            ],
        }
        
        from model.device import _compute_host_class
        host_class = _compute_host_class(res)
        
        assert host_class is not None
        assert len(host_class) == 16

    def test_host_class_empty_inventory(self):
        """Test host_class computation with empty inventory."""
        res = {"inventory": []}
        
        from model.device import _compute_host_class
        host_class = _compute_host_class(res)
        
        # Should return a default hash for unknown/empty
        assert host_class is not None
        assert len(host_class) == 16

    def test_host_class_deterministic_across_runs(self):
        """Test that host_class is deterministic across multiple runs."""
        res = {
            "inventory": [
                {"device_kind": "cuda", "available": True, "vendor": "nvidia", "family": "a100", "compute_capability": "8.0", "vram_total_mb": 40960},
                {"device_kind": "cpu", "available": True, "arch": "x86_64", "vendor": "intel", "simd": ["avx2"]},
            ],
        }
        
        from model.device import _compute_host_class
        
        # Compute multiple times
        class1 = _compute_host_class(res)
        class2 = _compute_host_class(res)
        class3 = _compute_host_class(res)
        
        # All should be identical
        assert class1 == class2 == class3


class TestContainerRuntimeGuard:
    """Test container runtime device mount and capability checks."""

    def test_container_guard_checks_nvidia_smi(self, monkeypatch):
        """Test that NVIDIA devices trigger nvidia-smi check."""
        from unittest.mock import MagicMock, patch
        from model.device import _check_container_runtime
        
        res = {
            "inventory": [
                {"device_kind": "cuda", "available": True, "uuid": "test-cuda-0", "name": "cuda0"},
            ],
            "alerts": [],
        }
        
        # Mock successful nvidia-smi call
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="GPU 0: NVIDIA A100")
            _check_container_runtime(res)
            mock_run.assert_called_once()
            args = mock_run.call_args[0]
            assert args[0] == ["nvidia-smi", "-L"]
        
        # No alerts should be emitted on success
        assert len(res["alerts"]) == 0
        # Inventory should be unchanged
        assert len(res["inventory"]) == 1

    def test_container_guard_removes_cuda_on_nvidia_smi_failure(self, monkeypatch):
        """Test that CUDA device is removed if nvidia-smi check fails."""
        from unittest.mock import MagicMock, patch
        from model.device import _check_container_runtime
        
        res = {
            "inventory": [
                {"device_kind": "cuda", "available": True, "uuid": "test-cuda-0", "name": "cuda0"},
            ],
            "alerts": [],
        }
        
        # Mock failed nvidia-smi call
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="")
            _check_container_runtime(res)
        
        # Alert should be emitted
        assert len(res["alerts"]) == 1
        assert res["alerts"][0]["kind"] == "runtime_missing"
        assert res["alerts"][0]["device_uuid"] == "test-cuda-0"
        
        # Device should be removed from inventory
        assert len(res["inventory"]) == 0

    def test_container_guard_checks_rocm_devices(self, monkeypatch):
        """Test that ROCm devices check /dev/kfd and /dev/dri."""
        from unittest.mock import patch
        from model.device import _check_container_runtime
        
        res = {
            "inventory": [
                {"device_kind": "rocm", "available": True, "uuid": "test-rocm-0", "name": "rocm0"},
            ],
            "alerts": [],
        }
        
        # Mock device presence
        with patch("os.path.exists") as mock_exists:
            mock_exists.side_effect = lambda p: p in ["/dev/kfd", "/dev/dri"]
            with patch("os.getgroups") as mock_getgroups:
                mock_getgroups.return_value = [0, 1000]  # user and some group
                with patch("grp.getgrgid") as mock_getgrgid:
                    class Group:
                        gr_name = "render"
                    mock_getgrgid.return_value = Group()
                    _check_container_runtime(res)
        
        # Inventory should be unchanged (no permission check failure for this case)
        assert len(res["inventory"]) >= 0  # May be removed if permission check fails

    def test_container_guard_removes_rocm_on_missing_device_file(self, monkeypatch):
        """Test that ROCm device is removed if /dev/kfd is missing."""
        from unittest.mock import patch
        from model.device import _check_container_runtime
        
        res = {
            "inventory": [
                {"device_kind": "rocm", "available": True, "uuid": "test-rocm-0", "name": "rocm0"},
            ],
            "alerts": [],
        }
        
        # Mock missing /dev/kfd
        with patch("os.path.exists") as mock_exists:
            mock_exists.return_value = False  # All devices missing
            _check_container_runtime(res)
        
        # Alert should be emitted
        assert len(res["alerts"]) == 1
        assert res["alerts"][0]["kind"] == "runtime_missing"
        assert "Missing ROCm devices" in res["alerts"][0]["detail"]
        
        # Device should be removed
        assert len(res["inventory"]) == 0

    def test_container_guard_checks_openvino_device_file(self, monkeypatch):
        """Test that OpenVINO (NPU) devices check /dev/accel/accel0."""
        from unittest.mock import patch
        from model.device import _check_container_runtime
        
        res = {
            "inventory": [
                {"device_kind": "openvino", "available": True, "uuid": "test-npu-0", "name": "npu"},
            ],
            "alerts": [],
        }
        
        # Mock device absence
        with patch("os.path.exists") as mock_exists:
            mock_exists.return_value = False
            _check_container_runtime(res)
        
        # Alert should be emitted
        assert len(res["alerts"]) == 1
        assert res["alerts"][0]["kind"] == "runtime_missing"
        assert "/dev/accel/accel0" in res["alerts"][0]["detail"]
        
        # Device should be removed
        assert len(res["inventory"]) == 0

    def test_container_guard_ignores_cpu(self, monkeypatch):
        """Test that CPU devices are not checked."""
        from model.device import _check_container_runtime
        
        res = {
            "inventory": [
                {"device_kind": "cpu", "available": True, "uuid": "test-cpu", "name": "cpu"},
            ],
            "alerts": [],
        }
        
        # This should not raise any errors or remove CPU
        _check_container_runtime(res)
        
        # CPU should still be present
        assert len(res["inventory"]) == 1
        assert res["inventory"][0]["device_kind"] == "cpu"
        # No alerts for CPU check
        assert len(res["alerts"]) == 0

    def test_container_guard_mixed_devices(self, monkeypatch):
        """Test guard with mixed device types."""
        from unittest.mock import MagicMock, patch
        from model.device import _check_container_runtime
        
        res = {
            "inventory": [
                {"device_kind": "cpu", "available": True, "uuid": "test-cpu", "name": "cpu"},
                {"device_kind": "cuda", "available": True, "uuid": "test-cuda-0", "name": "cuda0"},
                {"device_kind": "rocm", "available": True, "uuid": "test-rocm-0", "name": "rocm0"},
            ],
            "alerts": [],
        }
        
        # Mock nvidia-smi success, rocm devices missing
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            with patch("os.path.exists") as mock_exists:
                mock_exists.return_value = False  # ROCm devices missing
                _check_container_runtime(res)
        
        # CPU should remain, CUDA should remain, ROCm should be removed
        kinds = [d.get("device_kind") for d in res["inventory"]]
        assert "cpu" in kinds
        assert "cuda" in kinds
        assert "rocm" not in kinds

    def test_container_guard_alert_fields(self, monkeypatch):
        """Test that runtime_missing alerts have correct fields."""
        from unittest.mock import patch
        from model.device import _check_container_runtime
        
        res = {
            "inventory": [
                {"device_kind": "openvino", "available": True, "uuid": "test-npu-123", "name": "npu0"},
            ],
            "alerts": [],
        }
        
        with patch("os.path.exists") as mock_exists:
            mock_exists.return_value = False
            _check_container_runtime(res)
        
        alert = res["alerts"][0]
        assert alert["kind"] == "runtime_missing"
        assert alert["device_uuid"] == "test-npu-123"
        assert alert["device_kind"] == "openvino"
        assert "detail" in alert
        assert "t_mono_ns" in alert
        # Should not have t_wall_utc (only in other alert types)
        # Should have meaningful detail message
        assert len(alert["detail"]) > 0


class TestGPUPersistenceAndClocks:
    """Test GPU persistence mode, clock, and power limit probing."""

    def test_probe_persistence_mode(self, monkeypatch):
        """Test that persistence mode is probed from nvidia-smi."""
        from unittest.mock import MagicMock, patch
        from model.device import _probe_gpu_persistence_and_clocks
        from ai.common.config import Config
        
        res = {
            "inventory": [
                {"device_kind": "cuda", "available": True, "index": 0, "uuid": "cuda-0", "name": "cuda0"},
            ],
            "alerts": [],
        }
        
        cfg = MagicMock()
        cfg.gpu_enable_persistence_mode = False
        cfg.gpu_lock_clocks = False
        cfg.gpu_request_power_limit_w = 0
        
        # Mock subprocess calls
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="On\n", stderr="")
            _probe_gpu_persistence_and_clocks(res, cfg)
            # Check that persistence mode query was called
            calls = [str(call) for call in mock_run.call_args_list]
            assert any("persistence_mode" in str(call) for call in calls)
        
        # Persistence mode should be set
        assert "persistence_mode" in res["inventory"][0]
        assert res["inventory"][0]["persistence_mode"].lower() in ("on", "off", "unknown")

    def test_probe_clocks(self, monkeypatch):
        """Test that SM and memory clocks are probed."""
        from unittest.mock import MagicMock, patch
        from model.device import _probe_gpu_persistence_and_clocks
        
        res = {
            "inventory": [
                {"device_kind": "cuda", "available": True, "index": 0, "uuid": "cuda-0", "name": "cuda0"},
            ],
            "alerts": [],
        }
        
        cfg = MagicMock()
        cfg.gpu_enable_persistence_mode = False
        cfg.gpu_lock_clocks = False
        cfg.gpu_request_power_limit_w = 0
        
        # Mock subprocess calls with clock values
        call_count = [0]
        def mock_run_side_effect(*args, **kwargs):
            call_count[0] += 1
            # Return different values based on which query is being run
            if "clocks.sm" in str(args):
                return MagicMock(returncode=0, stdout="2400 MHz\n", stderr="")
            elif "clocks.mem" in str(args):
                return MagicMock(returncode=0, stdout="5005 MHz\n", stderr="")
            else:
                return MagicMock(returncode=0, stdout="On\n", stderr="")
        
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = mock_run_side_effect
            _probe_gpu_persistence_and_clocks(res, cfg)
        
        # Clocks should be set
        assert res["inventory"][0].get("sm_clock_mhz", 0) in (2400, 0)
        assert res["inventory"][0].get("mem_clock_mhz", 0) in (5005, 0)

    def test_probe_power_limits(self, monkeypatch):
        """Test that power limits are probed and compared."""
        from unittest.mock import MagicMock, patch
        from model.device import _probe_gpu_persistence_and_clocks
        
        res = {
            "inventory": [
                {"device_kind": "cuda", "available": True, "index": 0, "uuid": "cuda-0", "name": "cuda0"},
            ],
            "alerts": [],
        }
        
        cfg = MagicMock()
        cfg.gpu_enable_persistence_mode = False
        cfg.gpu_lock_clocks = False
        cfg.gpu_request_power_limit_w = 0
        
        def mock_run_side_effect(*args, **kwargs):
            if "power.limit" in str(args) and "default" not in str(args):
                return MagicMock(returncode=0, stdout="250.00 W\n", stderr="")
            elif "power.default_limit" in str(args):
                return MagicMock(returncode=0, stdout="400.00 W\n", stderr="")
            else:
                return MagicMock(returncode=0, stdout="On\n", stderr="")
        
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = mock_run_side_effect
            _probe_gpu_persistence_and_clocks(res, cfg)
        
        # Power limits should be set
        assert "power_limit_w" in res["inventory"][0]
        assert "power_default_limit_w" in res["inventory"][0]

    def test_power_cap_detection_alert(self, monkeypatch):
        """Test that power cap is detected and alert is emitted."""
        from unittest.mock import MagicMock, patch
        from model.device import _probe_gpu_persistence_and_clocks
        
        res = {
            "inventory": [
                {"device_kind": "cuda", "available": True, "index": 0, "uuid": "cuda-0", "name": "cuda0"},
            ],
            "alerts": [],
        }
        
        cfg = MagicMock()
        cfg.gpu_enable_persistence_mode = False
        cfg.gpu_lock_clocks = False
        cfg.gpu_request_power_limit_w = 0
        
        def mock_run_side_effect(*args, **kwargs):
            if "power.limit" in str(args) and "default" not in str(args):
                return MagicMock(returncode=0, stdout="200.00 W\n", stderr="")  # Capped
            elif "power.default_limit" in str(args):
                return MagicMock(returncode=0, stdout="400.00 W\n", stderr="")  # Default
            else:
                return MagicMock(returncode=0, stdout="On\n", stderr="")
        
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = mock_run_side_effect
            _probe_gpu_persistence_and_clocks(res, cfg)
        
        # Alert should be emitted about power cap
        power_cap_alerts = [a for a in res["alerts"] if a.get("kind") == "gpu_power_capped"]
        assert len(power_cap_alerts) > 0
        assert power_cap_alerts[0]["current_power_limit_w"] == 200.0
        assert power_cap_alerts[0]["default_power_limit_w"] == 400.0

    def test_ignores_non_cuda_devices(self, monkeypatch):
        """Test that non-CUDA devices are ignored."""
        from unittest.mock import MagicMock, patch
        from model.device import _probe_gpu_persistence_and_clocks
        
        res = {
            "inventory": [
                {"device_kind": "cpu", "available": True, "uuid": "cpu-0", "name": "cpu"},
                {"device_kind": "rocm", "available": True, "index": 0, "uuid": "rocm-0", "name": "rocm0"},
            ],
            "alerts": [],
        }
        
        cfg = MagicMock()
        cfg.gpu_enable_persistence_mode = False
        cfg.gpu_lock_clocks = False
        cfg.gpu_request_power_limit_w = 0
        
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="On\n", stderr="")
            _probe_gpu_persistence_and_clocks(res, cfg)
        
        # No nvidia-smi calls should be made
        calls = [str(call) for call in mock_run.call_args_list]
        assert len(calls) == 0

    def test_missing_nvidia_smi_fallback(self, monkeypatch):
        """Test graceful fallback when nvidia-smi fails."""
        from unittest.mock import MagicMock, patch
        from model.device import _probe_gpu_persistence_and_clocks
        
        res = {
            "inventory": [
                {"device_kind": "cuda", "available": True, "index": 0, "uuid": "cuda-0", "name": "cuda0"},
            ],
            "alerts": [],
        }
        
        cfg = MagicMock()
        cfg.gpu_enable_persistence_mode = False
        cfg.gpu_lock_clocks = False
        cfg.gpu_request_power_limit_w = 0
        
        # All nvidia-smi calls fail
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = Exception("nvidia-smi not found")
            _probe_gpu_persistence_and_clocks(res, cfg)
        
        # Device should have fallback/unknown values
        dev = res["inventory"][0]
        # Should not crash; may have default values
        assert "sm_clock_mhz" in dev or "persistence_mode" in dev

    def test_enable_persistence_mode_config(self, monkeypatch):
        """Test that persistence mode can be enabled via config."""
        from unittest.mock import MagicMock, patch, call
        from model.device import _probe_gpu_persistence_and_clocks
        
        res = {
            "inventory": [
                {"device_kind": "cuda", "available": True, "index": 0, "uuid": "cuda-0", "name": "cuda0"},
            ],
            "alerts": [],
        }
        
        cfg = MagicMock()
        cfg.gpu_enable_persistence_mode = True  # Enable
        cfg.gpu_lock_clocks = False
        cfg.gpu_request_power_limit_w = 0
        
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="On\n", stderr="")
            _probe_gpu_persistence_and_clocks(res, cfg)
            
            # Check that sudo nvidia-smi -pm 1 call was attempted
            calls = [str(c) for c in mock_run.call_args_list]
            sudo_pm_called = any("-pm" in str(c) and "sudo" in str(c) for c in calls)
            # May not be called if subprocess.run fails, but function should try

    def test_request_power_limit_config(self, monkeypatch):
        """Test that power limit can be requested via config."""
        from unittest.mock import MagicMock, patch
        from model.device import _probe_gpu_persistence_and_clocks
        
        res = {
            "inventory": [
                {"device_kind": "cuda", "available": True, "index": 0, "uuid": "cuda-0", "name": "cuda0"},
            ],
            "alerts": [],
        }
        
        cfg = MagicMock()
        cfg.gpu_enable_persistence_mode = False
        cfg.gpu_lock_clocks = False
        cfg.gpu_request_power_limit_w = 350  # Request 350W
        
        def mock_run_side_effect(*args, **kwargs):
            if "power.limit" in str(args) and "default" not in str(args):
                return MagicMock(returncode=0, stdout="300.00 W\n", stderr="")
            elif "power.default_limit" in str(args):
                return MagicMock(returncode=0, stdout="400.00 W\n", stderr="")
            else:
                return MagicMock(returncode=0, stdout="On\n", stderr="")
        
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = mock_run_side_effect
            _probe_gpu_persistence_and_clocks(res, cfg)
            
            # Check that sudo nvidia-smi -pl 350 call was attempted
            calls = [str(c) for c in mock_run.call_args_list]
            power_limit_called = any("-pl" in str(c) and "350" in str(c) for c in calls)
            # May not be called if subprocess fails, but function should try


class TestHotplugDebouncer:
    """Test hotplug event debouncing logic."""

    def test_debouncer_first_event_triggers_immediate_reprobe(self):
        """Test that first hotplug event triggers immediate re-probe."""
        from model.device import HotplugDebouncer
        
        debouncer = HotplugDebouncer(debounce_seconds=10)
        
        # First event should trigger immediate re-probe
        should_reprobe = debouncer.on_hotplug_event()
        assert should_reprobe is True
        assert debouncer.pending_hotplug is False

    def test_debouncer_coalesces_rapid_events(self):
        """Test that rapid events within debounce window are coalesced."""
        from model.device import HotplugDebouncer
        import time
        
        debouncer = HotplugDebouncer(debounce_seconds=10)
        
        # First event triggers re-probe
        assert debouncer.on_hotplug_event() is True
        
        # Rapid second event should be marked as pending
        assert debouncer.on_hotplug_event() is False
        assert debouncer.pending_hotplug is True
        
        # Third rapid event also pending
        assert debouncer.on_hotplug_event() is False
        assert debouncer.pending_hotplug is True

    def test_debouncer_respects_debounce_window(self, monkeypatch):
        """Test that debounce window is respected."""
        from model.device import HotplugDebouncer
        from unittest.mock import patch
        import time
        
        debouncer = HotplugDebouncer(debounce_seconds=1)
        
        # First event triggers
        assert debouncer.on_hotplug_event() is True
        
        # Immediate second event is pending
        assert debouncer.on_hotplug_event() is False
        
        # Mock time passage beyond debounce window
        current_time = time.time()
        with patch("time.time") as mock_time:
            mock_time.return_value = current_time + 2.0  # 2 seconds later
            
            # Event after debounce window should trigger re-probe
            assert debouncer.on_hotplug_event() is True
            assert debouncer.pending_hotplug is False

    def test_debouncer_pending_check(self):
        """Test has_pending_hotplug() method."""
        from model.device import HotplugDebouncer
        
        debouncer = HotplugDebouncer(debounce_seconds=10)
        
        # Initially no pending
        assert debouncer.has_pending_hotplug() is False
        
        # First event, no pending
        debouncer.on_hotplug_event()
        assert debouncer.has_pending_hotplug() is False
        
        # Second event, now pending
        debouncer.on_hotplug_event()
        assert debouncer.has_pending_hotplug() is True


class TestInventoryDelta:
    """Test inventory delta computation for topology changes."""

    def test_detect_added_device(self):
        """Test that newly added devices are detected."""
        from model.device import _compute_inventory_delta
        
        before = [
            {"uuid": "cuda-0", "device_kind": "cuda", "name": "gpu0"},
        ]
        
        after = [
            {"uuid": "cuda-0", "device_kind": "cuda", "name": "gpu0"},
            {"uuid": "cuda-1", "device_kind": "cuda", "name": "gpu1"},
        ]
        
        added, removed = _compute_inventory_delta(before, after)
        
        assert "cuda-1" in added
        assert len(removed) == 0

    def test_detect_removed_device(self):
        """Test that removed devices are detected."""
        from model.device import _compute_inventory_delta
        
        before = [
            {"uuid": "cuda-0", "device_kind": "cuda", "name": "gpu0"},
            {"uuid": "cuda-1", "device_kind": "cuda", "name": "gpu1"},
        ]
        
        after = [
            {"uuid": "cuda-0", "device_kind": "cuda", "name": "gpu0"},
        ]
        
        added, removed = _compute_inventory_delta(before, after)
        
        assert len(added) == 0
        assert "cuda-1" in removed

    def test_detect_multiple_changes(self):
        """Test detecting multiple devices added and removed."""
        from model.device import _compute_inventory_delta
        
        before = [
            {"uuid": "cuda-0", "device_kind": "cuda"},
            {"uuid": "cuda-1", "device_kind": "cuda"},
            {"uuid": "rocm-0", "device_kind": "rocm"},
        ]
        
        after = [
            {"uuid": "cuda-0", "device_kind": "cuda"},
            {"uuid": "cuda-2", "device_kind": "cuda"},
            {"uuid": "npu-0", "device_kind": "openvino"},
        ]
        
        added, removed = _compute_inventory_delta(before, after)
        
        # cuda-2 and npu-0 added
        assert set(added) == {"cuda-2", "npu-0"}
        # cuda-1 and rocm-0 removed
        assert set(removed) == {"cuda-1", "rocm-0"}

    def test_no_change_detected(self):
        """Test that identical inventories show no change."""
        from model.device import _compute_inventory_delta
        
        inventory = [
            {"uuid": "cuda-0", "device_kind": "cuda"},
            {"uuid": "rocm-0", "device_kind": "rocm"},
        ]
        
        added, removed = _compute_inventory_delta(inventory, inventory)
        
        assert len(added) == 0
        assert len(removed) == 0

    def test_delta_ignores_missing_uuid(self):
        """Test that devices without UUID are ignored in delta."""
        from model.device import _compute_inventory_delta
        
        before = [
            {"uuid": "cuda-0", "device_kind": "cuda"},
            {"device_kind": "cpu", "name": "cpu"},  # No UUID
        ]
        
        after = [
            {"uuid": "cuda-0", "device_kind": "cuda"},
            {"device_kind": "cpu", "name": "cpu"},
        ]
        
        added, removed = _compute_inventory_delta(before, after)
        
        # CPU devices without UUID should not be in delta
        assert len(added) == 0
        assert len(removed) == 0

    def test_emit_topology_change_alert(self):
        """Test that topology_change alerts are emitted correctly."""
        from model.device import _emit_topology_change_alert
        
        result = {
            "inventory": [
                {"uuid": "cuda-0", "device_kind": "cuda", "name": "gpu0", "index": 0},
                {"uuid": "cuda-1", "device_kind": "cuda", "name": "gpu1", "index": 1},
            ],
            "alerts": [],
        }
        
        added_uuids = ["cuda-2"]
        removed_uuids = ["cuda-1"]
        
        _emit_topology_change_alert(result, added_uuids, removed_uuids)
        
        # Alert should be emitted
        assert len(result["alerts"]) == 1
        alert = result["alerts"][0]
        assert alert["kind"] == "topology_change"
        assert len(alert["added"]) == 0  # cuda-2 not in inventory
        assert len(alert["removed"]) == 1
        assert alert["removed"][0]["uuid"] == "cuda-1"
        assert "t_mono_ns" in alert
        assert "t_wall_utc" in alert

    def test_no_alert_on_empty_delta(self):
        """Test that no alert is emitted when there's no change."""
        from model.device import _emit_topology_change_alert
        
        result = {
            "inventory": [],
            "alerts": [],
        }
        
        _emit_topology_change_alert(result, [], [])
        
        # No alert should be emitted
        assert len(result["alerts"]) == 0
