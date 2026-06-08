"""Tests for device telemetry emission (Phase 11.1 bullet: Telemetry contract)."""

import math
import time
from unittest.mock import Mock, patch, MagicMock

import pytest

from model.device_telemetry import DeviceTelemetryEmitter, get_device_telemetry_emitter


class TestDeviceTelemetryEmitter:
    """Test device telemetry collection and emission."""

    def test_emitter_creation(self):
        """Test that emitter can be created without Redis."""
        emitter = DeviceTelemetryEmitter()
        assert emitter is not None

    def test_redis_connect_graceful_fail(self, monkeypatch):
        """Test that emitter handles Redis connection failure gracefully."""
        monkeypatch.setenv("REDIS_HOST", "unreachable.invalid")
        
        emitter = DeviceTelemetryEmitter()
        # Should not raise
        client = emitter._get_redis_client()
        assert client is None  # Failed to connect

    def test_collect_nvidia_metrics_with_missing_pynvml(self):
        """Test NVIDIA metrics collection when pynvml is unavailable."""
        emitter = DeviceTelemetryEmitter()
        
        # pynvml likely not installed in test env
        metrics = emitter._collect_nvidia_metrics("fake-uuid")
        
        # Should have NaN for all metrics (graceful fallback)
        assert math.isnan(metrics.get("temperature_c"))
        assert math.isnan(metrics.get("power_w"))
        assert math.isnan(metrics.get("power_limit_w"))

    def test_collect_cpu_metrics(self):
        """Test CPU metrics collection."""
        emitter = DeviceTelemetryEmitter()
        metrics = emitter._collect_cpu_metrics()
        
        # Should have the expected keys even if values are NaN
        assert "power_w" in metrics
        assert "power_limit_w" in metrics

    def test_emit_device_probe_without_redis(self):
        """Test that emit falls back gracefully without Redis."""
        emitter = DeviceTelemetryEmitter()
        
        device = {
            "device_kind": "cuda",
            "uuid": "test-uuid",
            "name": "test_device",
            "available": True,
        }
        
        # Should not raise
        emitter.emit_device_probe(
            agent="test_agent",
            host="test_host",
            probe_id="test-probe-id",
            host_compute_fingerprint="test-fingerprint",
            device=device,
            vram_total_mb=12000.0,
            vram_used_mb=4000.0,
            vram_largest_free_block_mb=8000.0,
        )

    def test_emit_device_probe_event_structure(self):
        """Test that emitted event has expected structure."""
        mock_redis = MagicMock()
        
        emitter = DeviceTelemetryEmitter()
        emitter._redis = mock_redis
        emitter._attempted_redis_connect = True  # Prevent reconnection
        
        device = {
            "device_kind": "cuda",
            "uuid": "test-uuid",
            "name": "tesla_a100",
            "available": True,
        }
        
        emitter.emit_device_probe(
            agent="predictor",
            host="gpu-host-1",
            probe_id="probe-2024-001",
            host_compute_fingerprint="abc123def456",
            device=device,
            vram_total_mb=40960.0,
            vram_used_mb=20480.0,
            vram_largest_free_block_mb=20480.0,
        )
        
        # Verify xadd was called
        assert mock_redis.xadd.called
        call_args = mock_redis.xadd.call_args
        
        # Check stream name
        assert call_args[0][0] == "negelir:device:probe"
        
        # Check event dict
        event = call_args[0][1]
        assert event["kind"] == "device_probe"
        assert event["agent"] == "predictor"
        assert event["host"] == "gpu-host-1"
        assert event["device"] == "tesla_a100"
        assert event["device_kind"] == "cuda"
        assert event["vram_total_mb"] == "40960"
        assert event["vram_used_mb"] == "20480"

    def test_emit_with_nan_values(self):
        """Test that NaN values are properly formatted."""
        mock_redis = MagicMock()
        
        emitter = DeviceTelemetryEmitter()
        emitter._redis = mock_redis
        emitter._attempted_redis_connect = True  # Prevent reconnection
        
        device = {
            "device_kind": "cpu",
            "uuid": "",
            "name": "cpu",
            "available": True,
        }
        
        emitter.emit_device_probe(
            agent="test_agent",
            host="cpu_host",
            probe_id="probe-cpu-001",
            host_compute_fingerprint="cpu-fingerprint",
            device=device,
            vram_total_mb=None,
            vram_used_mb=None,
        )
        
        call_args = mock_redis.xadd.call_args
        event = call_args[0][1]
        
        # NaN values should be represented as "NaN" string
        assert event["vram_total_mb"] == "NaN"
        assert event["vram_used_mb"] == "NaN"

    def test_module_level_emitter_singleton(self):
        """Test that get_device_telemetry_emitter returns singleton."""
        emitter1 = get_device_telemetry_emitter()
        emitter2 = get_device_telemetry_emitter()
        
        # Should be the same instance
        assert emitter1 is emitter2

    def test_emit_with_stream_maxlen(self):
        """Test that emit respects max stream length configuration."""
        mock_redis = MagicMock()
        
        emitter = DeviceTelemetryEmitter()
        emitter._redis = mock_redis
        emitter._attempted_redis_connect = True  # Prevent reconnection
        
        device = {
            "device_kind": "openvino",
            "uuid": "npu-uuid",
            "name": "npu0",
        }
        
        emitter.emit_device_probe(
            agent="categorizer",
            host="npu_host",
            probe_id="probe-npu-001",
            host_compute_fingerprint="npu-fingerprint",
            device=device,
        )
        
        call_args = mock_redis.xadd.call_args
        # Check that maxlen was passed
        assert "maxlen" in call_args[1]
        assert call_args[1]["approximate"] is True


class TestAdversarialTelemetryCases:
    """Adversarial tests for telemetry emission."""

    def test_emit_with_invalid_metrics(self):
        """Test that invalid metrics are handled gracefully."""
        mock_redis = MagicMock()
        
        emitter = DeviceTelemetryEmitter()
        emitter._redis = mock_redis
        
        device = {
            "device_kind": "unknown",
            "uuid": None,
            "name": None,
        }
        
        # Should not raise
        emitter.emit_device_probe(
            agent="test",
            host="test_host",
            probe_id="test",
            host_compute_fingerprint="test",
            device=device,
            vram_total_mb=-1,  # Invalid
        )

    def test_emit_redis_exception_handling(self):
        """Test that Redis exceptions are logged but don't crash."""
        mock_redis = MagicMock()
        mock_redis.xadd.side_effect = Exception("Redis connection lost")
        
        emitter = DeviceTelemetryEmitter()
        emitter._redis = mock_redis
        
        device = {"device_kind": "cuda", "uuid": "test", "name": "cuda0"}
        
        # Should not raise
        emitter.emit_device_probe(
            agent="test",
            host="test",
            probe_id="test",
            host_compute_fingerprint="test",
            device=device,
        )

    def test_temperature_metric_formatting(self):
        """Test that temperature values are properly rounded."""
        mock_redis = MagicMock()
        
        emitter = DeviceTelemetryEmitter()
        emitter._redis = mock_redis
        emitter._attempted_redis_connect = True  # Prevent reconnection
        # Inject custom metrics
        emitter._collect_nvidia_metrics = lambda x: {
            "temperature_c": 65.789,
            "power_w": 150.234,
            "power_limit_w": 250.0,
            "sm_clock_mhz": 2400,
            "mem_clock_mhz": 5005,
            "throttle_events_60s": 2,
            "ecc_dbe_total": 0,
            "xid_errors_60s": 0,
        }
        
        device = {"device_kind": "cuda", "uuid": "test", "name": "cuda0"}
        
        emitter.emit_device_probe(
            agent="test",
            host="test",
            probe_id="test",
            host_compute_fingerprint="test",
            device=device,
        )
        
        call_args = mock_redis.xadd.call_args
        event = call_args[0][1]
        
        # Temperature should be rounded to 1 decimal
        assert event["temperature_c"] == "65.8"
        # Power should be rounded to 1 decimal
        assert event["power_w"] == "150.2"
        # Clocks should be integers
        assert event["sm_clock_mhz"] == "2400"
        assert event["mem_clock_mhz"] == "5005"

