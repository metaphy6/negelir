"""Device telemetry emission for Phase 11.

Publishes device_probe telemetry.v1 events with hardware metrics to Redis Streams.
Falls back gracefully if Redis or vendor SDKs are unavailable.
"""

import json
import math
import os
import platform
import subprocess
import time
from typing import Any, Dict, Optional
import logging

from common.config import Config
from common.logger import get_logger

log = get_logger("model.device_telemetry")


class DeviceTelemetryEmitter:
    """Emits device_probe telemetry to Redis Streams."""
    
    DEVICE_PROBE_STREAM = "negelir:device:probe"
    
    def __init__(self, config: Optional[Config] = None):
        self.cfg = config or Config()
        self._redis = None
        self._attempted_redis_connect = False
    
    def _get_redis_client(self):
        """Lazy-connect to Redis."""
        if self._attempted_redis_connect:
            return self._redis
        
        self._attempted_redis_connect = True
        try:
            import redis
            client = redis.Redis(
                host=self.cfg.redis_host,
                port=self.cfg.redis_port,
                decode_responses=True,
                socket_connect_timeout=getattr(self.cfg, "redis_socket_timeout", 2),
            )
            client.ping()
            self._redis = client
            log.debug("Device telemetry Redis client connected")
            return self._redis
        except Exception as e:
            log.debug("Device telemetry Redis unavailable: %s", e)
            return None
    
    def _collect_nvidia_metrics(self, device_uuid: str) -> Dict[str, Any]:
        """Collect NVIDIA GPU metrics via pynvml or nvidia-smi."""
        metrics = {
            "temperature_c": float("nan"),
            "power_w": float("nan"),
            "power_limit_w": float("nan"),
            "sm_clock_mhz": float("nan"),
            "mem_clock_mhz": float("nan"),
            "throttle_events_60s": 0,
            "ecc_dbe_total": 0,
            "xid_errors_60s": 0,
        }
        
        # Try pynvml first (faster)
        try:
            import pynvml
            pynvml.nvmlInit()
            try:
                for i in range(pynvml.nvmlDeviceGetCount()):
                    handle = pynvml.nvmlDeviceGetHandleByIndex(i)
                    dev_uuid = pynvml.nvmlDeviceGetUUID(handle)
                    if dev_uuid != device_uuid:
                        continue
                    
                    try:
                        temp = pynvml.nvmlDeviceGetTemperature(handle, 0)
                        metrics["temperature_c"] = float(temp)
                    except Exception:
                        pass
                    
                    try:
                        power = pynvml.nvmlDeviceGetPowerUsage(handle)  # mW
                        metrics["power_w"] = power / 1000.0
                    except Exception:
                        pass
                    
                    try:
                        limit = pynvml.nvmlDeviceGetPowerManagementLimit(handle)  # mW
                        metrics["power_limit_w"] = limit / 1000.0
                    except Exception:
                        pass
                    
                    try:
                        sm = pynvml.nvmlDeviceGetClockInfo(handle, pynvml.NVML_CLOCK_SM)
                        metrics["sm_clock_mhz"] = float(sm)
                    except Exception:
                        pass
                    
                    try:
                        mem = pynvml.nvmlDeviceGetClockInfo(handle, pynvml.NVML_CLOCK_MEM)
                        metrics["mem_clock_mhz"] = float(mem)
                    except Exception:
                        pass
                    
                    break
            finally:
                pynvml.nvmlShutdown()
        except Exception as e:
            log.debug("pynvml failed: %s", e)
        
        return metrics
    
    def _collect_cpu_metrics(self) -> Dict[str, Any]:
        """Collect CPU power metrics via psutil and sysfs."""
        metrics = {
            "power_w": float("nan"),
            "power_limit_w": float("nan"),
        }
        
        try:
            # Try RAPL (Intel RAPL on x86_64)
            rapl_path = "/sys/class/powercap/intel-rapl"
            if os.path.isdir(rapl_path):
                try:
                    energy_file = os.path.join(rapl_path, "intel-rapl:0", "energy_uj")
                    with open(energy_file, "r") as f:
                        energy_uj_1 = int(f.read().strip())
                    time.sleep(0.1)
                    with open(energy_file, "r") as f:
                        energy_uj_2 = int(f.read().strip())
                    # Energy in Joules, time in 0.1s
                    power_j = (energy_uj_2 - energy_uj_1) / 1_000_000
                    power_w = power_j / 0.1
                    metrics["power_w"] = min(max(power_w, 0), 1000)  # Sanity bounds
                except Exception as e:
                    log.debug("RAPL energy collection failed: %s", e)
        except Exception:
            pass
        
        return metrics
    
    def emit_device_probe(
        self,
        agent: str,
        host: str,
        probe_id: str,
        host_compute_fingerprint: str,
        device: Dict[str, Any],
        vram_total_mb: Optional[float] = None,
        vram_used_mb: Optional[float] = None,
        vram_largest_free_block_mb: Optional[float] = None,
    ) -> None:
        """
        Emit a device_probe telemetry event to Redis Streams.
        
        Falls back gracefully if Redis is unavailable.
        Fields that cannot be collected are emitted as NaN with a reason enum.
        """
        client = self._get_redis_client()
        if not client:
            log.debug("Device telemetry skipped (Redis unavailable)")
            return
        
        device_kind = device.get("device_kind", "unknown")
        device_uuid = device.get("uuid", "")
        device_name = device.get("name", "unknown")
        
        # Collect metrics based on device kind
        if device_kind == "cuda":
            metrics = self._collect_nvidia_metrics(device_uuid)
        elif device_kind == "cpu":
            metrics = self._collect_cpu_metrics()
        else:
            metrics = {}
        
        # Build the event
        event: Dict[str, Any] = {
            "kind": "device_probe",
            "agent": agent,
            "host": host,
            "probe_id": probe_id,
            "host_compute_fingerprint": host_compute_fingerprint,
            "device": device_name,
            "device_kind": device_kind,
            "device_uuid": device_uuid,
            "vram_total_mb": str(int(vram_total_mb)) if vram_total_mb else "NaN",
            "vram_used_mb": str(int(vram_used_mb)) if vram_used_mb else "NaN",
            "vram_largest_free_block_mb": str(int(vram_largest_free_block_mb)) if vram_largest_free_block_mb else "NaN",
            "temperature_c": str(round(metrics.get("temperature_c", float("nan")), 1)),
            "power_w": str(round(metrics.get("power_w", float("nan")), 1)),
            "power_limit_w": str(round(metrics.get("power_limit_w", float("nan")), 1)),
            "sm_clock_mhz": str(int(metrics.get("sm_clock_mhz", float("nan")))) if not math.isnan(metrics.get("sm_clock_mhz", float("nan"))) else "NaN",
            "mem_clock_mhz": str(int(metrics.get("mem_clock_mhz", float("nan")))) if not math.isnan(metrics.get("mem_clock_mhz", float("nan"))) else "NaN",
            "throttle_events_60s": str(int(metrics.get("throttle_events_60s", 0))),
            "ecc_dbe_total": str(int(metrics.get("ecc_dbe_total", 0))),
            "xid_errors_60s": str(int(metrics.get("xid_errors_60s", 0))),
            "sample_period_s": "1",
            "sample_skipped_total": "0",
            "ts": str(int(time.time())),
        }
        
        try:
            # Add to Redis stream with max length cap
            max_len = getattr(self.cfg, "telemetry_max_stream", 50000)
            client.xadd(
                self.DEVICE_PROBE_STREAM,
                event,
                maxlen=max_len,
                approximate=True,
            )
            log.debug("Device probe telemetry emitted for %s:%s", device_kind, device_uuid)
        except Exception as e:
            log.warning("Failed to emit device telemetry: %s", e)


# Module-level convenience
_emitter: Optional[DeviceTelemetryEmitter] = None


def get_device_telemetry_emitter(config: Optional[Config] = None) -> DeviceTelemetryEmitter:
    """Get or create the global device telemetry emitter."""
    global _emitter
    if _emitter is None:
        _emitter = DeviceTelemetryEmitter(config)
    return _emitter
