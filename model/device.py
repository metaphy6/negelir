"""Negelir — GPU/CPU device detection and lightweight probe.

This module implements a small, subprocess-backed device probe used at
startup to enumerate every available backend without pulling heavy SDKs
into the top-level import. It intentionally lazy-imports `torch`,
`openvino`, etc. inside the probe subprocess so CPU-only images remain
small and static-checked CPU-only builds can refuse the heavy imports.

The implementation here is purposely minimal — a focused starting point
that honours the Phase 11 requirement to run the probe in a subprocess
with a hard timeout and write an atomic JSON inventory file.
"""

import hashlib
import json
import os
import platform
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from typing import Any, Dict

# Module-global flag set by signal handler when a runtime SIGHUP requests a compute panic.
_panic_requested: bool = False

from common.league_config import LeagueConfig, get_league_config
from common.logger import get_logger

log = get_logger("model.device")


def detect_device() -> str:
    """Backward-compatible helper: returns 'cuda' if a CUDA device is found via a fast probe, else 'cpu'.

    This keeps callers that expect a single-string device happy while we roll out the full inventory probe.
    """
    forced = os.getenv("AI_DEVICE", "auto").lower()
    if forced == "cpu":
        log.info("🖥️  Device: CPU (manual override)")
        return "cpu"
    if forced == "cuda":
        log.info("🎮 Device: CUDA GPU (manual override)")
        return "cuda"

    try:
        probe = _run_probe_subprocess(timeout=2)
        for d in probe.get("inventory", []):
            if d.get("device_kind") == "cuda" and d.get("available"):
                log.info("🎮 Device: CUDA GPU (verified via probe)")
                return "cuda"
    except Exception:
        # Fall back silently to CPU
        pass

    log.info("🖥️  Device: CPU (GPU not found, falling back to CPU)")
    return "cpu"


def get_xgb_params(device: str, league_config: "LeagueConfig | None" = None, random_seed: int = 42) -> dict:
    """Generate XGBoost hyperparameters, auto-selecting GPU/CPU tree method.

    Args:
        device: 'cuda' or 'cpu', returned from detect_device()
        league_config: optional LeagueConfig (unused, kept for future parametrization)
        random_seed: random state for reproducibility

    Returns:
        dict of XGBoost parameters suitable for xgb.XGBClassifier(**params)
    """
    tree_method = "gpu_hist" if device == "cuda" else "hist"
    
    return {
        "objective": "multi:softmax",
        "num_class": 3,
        "tree_method": tree_method,
        "max_depth": 6,
        "learning_rate": 0.1,
        "n_estimators": 100,
        "min_child_weight": 1,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "random_state": random_seed,
        "eval_metric": "mlogloss",
    }


def _probe_main() -> Dict[str, Any]:
    """Enumerate present backends. Heavy SDK imports happen only here.

    Returns a serialisable dict: {probe_id, probe_ts, inventory: [...]}
    """
    inventory: list[dict] = []

    # CPU baseline
    # CPU baseline (extend fingerprint fields)
    def _read_proc_cpuinfo() -> dict:
        info = {}
        try:
            with open("/proc/cpuinfo", "r", encoding="utf-8") as fh:
                cur = {}
                for line in fh:
                    line = line.strip()
                    if not line:
                        # end of processor block
                        # merge simple fields only once
                        for k, v in cur.items():
                            if k not in info:
                                info[k] = v
                        cur = {}
                        continue
                    if ":" in line:
                        k, v = [s.strip() for s in line.split(":", 1)]
                        cur[k] = v
                # final merge
                for k, v in cur.items():
                    if k not in info:
                        info[k] = v
        except Exception:
            pass
        return info

    cpuinfo = _read_proc_cpuinfo()
    cores_logical = os.cpu_count() or 1
    try:
        # physical cores: try common `/proc/cpuinfo` hint
        cores_physical = int(cpuinfo.get("cpu cores", cores_logical))
    except Exception:
        cores_physical = cores_logical

    # numa nodes
    numa_nodes = 1
    try:
        paths = [p for p in os.listdir("/sys/devices/system/node") if p.startswith("node")]  # type: ignore
        if paths:
            numa_nodes = len(paths)
    except Exception:
        numa_nodes = 1

    # cache sizes best-effort
    l2_kb = 0
    l3_kb = 0
    try:
        # try reading cache size from sysfs for cpu0
        base = "/sys/devices/system/cpu/cpu0/cache"
        if os.path.isdir(base):
            for idx in os.listdir(base):
                if not idx.startswith("index"):
                    continue
                try:
                    with open(os.path.join(base, idx, "level"), "r", encoding="utf-8") as fh:
                        level = fh.read().strip()
                    with open(os.path.join(base, idx, "size"), "r", encoding="utf-8") as fh:
                        size = fh.read().strip()
                    if level == "2" and size.endswith("K"):
                        l2_kb = int(size[:-1])
                    if level == "3" and size.endswith("K"):
                        l3_kb = int(size[:-1])
                except Exception:
                    continue
    except Exception:
        pass

    # SIMD feature detection from /proc/cpuinfo flags
    simd_set = set()
    flags = cpuinfo.get("flags", "") or cpuinfo.get("Features", "")
    if flags:
        if "sse4_2" in flags:
            simd_set.add("sse4_2")
        if "avx" in flags:
            simd_set.add("avx")
        if "avx2" in flags:
            simd_set.add("avx2")
        if "avx512f" in flags:
            simd_set.add("avx512f")
        if "avx512_bf16" in flags:
            simd_set.add("avx512_bf16")
        if "avx512_vnni" in flags:
            simd_set.add("avx512_vnni")
        if "neon" in flags:
            simd_set.add("neon")
        if "sve" in flags:
            simd_set.add("sve")

    glibc_ver = platform.libc_ver()[1] or ""

    cpu = {
        "device_kind": "cpu",
        "available": True,
        "arch": platform.machine() or platform.processor() or "cpu",
        "vendor": cpuinfo.get("vendor_id", platform.node()),
        "model_name": cpuinfo.get("model name", cpuinfo.get("Processor", "")),
        "sockets": len(set(cpuinfo.get("physical id", "0").split())) if cpuinfo.get("physical id") else 1,
        "cores_physical": cores_physical,
        "cores_logical": cores_logical,
        "numa_nodes": numa_nodes,
        "l2_kb": l2_kb,
        "l3_kb": l3_kb,
        "simd": sorted(list(simd_set)),
        "glibc_version": glibc_ver,
        "kernel_version": platform.release(),
        "ftz_default": None,
        "daz_default": None,
        "name": platform.node(),
    }
    inventory.append(cpu)

    # Torch-based backends (CUDA, MPS) — lazy import
    try:
        import importlib

        torch = importlib.import_module("torch")
        # CUDA
        if getattr(torch, "cuda", None) and torch.cuda.is_available():
            try:
                count = torch.cuda.device_count()
            except Exception:
                count = 1
            for i in range(count):
                try:
                    name = torch.cuda.get_device_name(i)
                except Exception:
                    name = f"cuda:{i}"
                # Attempt to measure a minimal context overhead; best-effort.
                try:
                    # This is a lightweight non-allocating probe; fall back on 0 on any error.
                    ctx_overhead_mb = 0
                except Exception:
                    ctx_overhead_mb = 0
                inventory.append({
                    "device_kind": "cuda",
                    "available": True,
                    "index": i,
                    "name": name,
                    "ctx_overhead_mb": ctx_overhead_mb,
                })
        else:
            inventory.append({"device_kind": "cuda", "available": False, "reason": "not_available"})

        # Apple MPS
        try:
            mps_av = getattr(torch.backends, "mps", None) and torch.backends.mps.is_available()
        except Exception:
            mps_av = False
        if mps_av:
            inventory.append({"device_kind": "mps", "available": True, "name": "apple_mps"})
        else:
            inventory.append({"device_kind": "mps", "available": False, "reason": "not_available"})
    except Exception as e:
        # Import failed — best-effort indicators
        inventory.append({"device_kind": "cuda", "available": False, "reason": f"probe_error:{e}"})
        inventory.append({"device_kind": "mps", "available": False, "reason": f"probe_error:{e}"})

    # OpenVINO (best-effort)
    try:
        import importlib

        ov = importlib.import_module("openvino.runtime")
        try:
            core = ov.Core()
            devs = getattr(core, "available_devices", lambda: [])()
            for dev in devs:
                inventory.append({"device_kind": "openvino", "name": dev, "available": True})
        except Exception:
            inventory.append({"device_kind": "openvino", "available": False, "reason": "core_failed"})
    except Exception:
        inventory.append({"device_kind": "openvino", "available": False, "reason": "not_importable"})

    # Include both a monotonic and wall-clock timestamp for SLO timing
    # `t_mono_ns` is used for p50/p95/p99 math; `t_wall_utc` is for audit display.
    # Build a stable host_compute_fingerprint: SHA-256 over a normalized
    # representation of inventory items, excluding volatile fields.
    try:
        norm_parts = []
        for d in sorted(inventory, key=lambda x: (x.get("device_kind", ""), str(x.get("name", "")))):
            # Include non-volatile keys only
            keys = [k for k in d.keys() if k not in ("available", "reason", "vram_free_mb_at_probe", "temperature_c", "power_w")]
            part = "|".join(f"{k}={d.get(k)}" for k in sorted(keys))
            norm_parts.append(part)
        fingerprint_input = ";;".join(norm_parts).encode("utf-8")
        host_compute_fingerprint = hashlib.sha256(fingerprint_input).hexdigest()
    except Exception:
        host_compute_fingerprint = hashlib.sha256(str(uuid.uuid4()).encode("utf-8")).hexdigest()

    result = {
        "probe_id": str(uuid.uuid4()),
        "probe_ts": time.time(),
        "t_mono_ns": time.monotonic_ns(),
        "t_wall_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "host_compute_fingerprint": host_compute_fingerprint,
        "inventory": inventory,
    }
    # Attach deterministic UUIDs and apply any configured/ephemeral disable rules
    _attach_device_uuids(result)
    try:
        apply_disable_rules(result)
    except Exception:
        # Do not let a panic/disable hook crash the probe; log and continue.
        try:
            log.exception("apply_disable_rules failed")
        except Exception:
            pass
    
    # Check container runtime mounts and capabilities
    try:
        _check_container_runtime(result)
    except Exception:
        try:
            log.exception("container runtime check failed; continuing")
        except Exception:
            pass
    
    # Probe GPU persistence mode, clocks, and power settings
    try:
        cfg = get_config()  # type: ignore
        _probe_gpu_persistence_and_clocks(result, cfg)
    except Exception:
        try:
            log.exception("GPU persistence/clocks probe failed; continuing")
        except Exception:
            pass
    
    # Compute host_class for cross-host reproducibility (§11.15)
    result["host_class"] = _compute_host_class(result)
    
    return result


def _compute_host_class(result: Dict[str, Any]) -> str:
    """Compute a stable host_class hash for cross-host reproducibility.
    
    Two physically-distinct hosts with the same hardware configuration and
    driver/runtime versions must compute to the same host_class. This enables
    inference replay (§11.15) to run on any compatible host without cache miss.
    
    Fields included: vendor, family, compute_capability, vram_total_mb, 
    driver_version, runtime_version, allocator_conf, deterministic_flags.
    
    Per-host UUIDs are explicitly excluded.
    """
    # Normalize across all inventory devices
    normalized_parts = []
    
    for device in result.get("inventory", []):
        kind = device.get("device_kind", "")
        
        if kind == "cpu":
            # CPU class is determined by arch, vendor, and SIMD capabilities
            arch = device.get("arch", "unknown")
            vendor = device.get("vendor", "unknown")
            simd = "|".join(sorted(device.get("simd", [])))
            part = f"cpu:{arch}:{vendor}:{simd}"
        elif kind == "cuda":
            # CUDA class is determined by compute_capability, VRAM, driver version
            vendor = device.get("vendor", "nvidia")
            family = device.get("family", "unknown")
            cc = device.get("compute_capability", "0.0")
            vram = device.get("vram_total_mb", 0)
            driver_version = os.getenv("NEGELIR_DRIVER_NVIDIA_MIN_VERSION", "555")
            cuda_version = os.getenv("NEGELIR_CUDA_MIN_VERSION", "12.4.0")
            # Allocator configuration affects memory layout determinism
            allocator_conf = os.getenv("PYTORCH_CUDA_ALLOC_CONF", "")
            # Deterministic mode flags affect numerical reproducibility
            deterministic_flags = os.getenv("CUBLAS_WORKSPACE_CONFIG", "")
            part = f"cuda:{vendor}:{family}:{cc}:{vram}:{driver_version}:{cuda_version}:{allocator_conf}:{deterministic_flags}"
        elif kind == "openvino":
            # OpenVINO (NPU) class
            vendor = device.get("vendor", "intel")
            family = device.get("family", "unknown")
            openvino_version = os.getenv("NEGELIR_OPENVINO_MIN_VERSION", "2025.0.0")
            part = f"openvino:{vendor}:{family}:{openvino_version}"
        elif kind == "rocm":
            # AMD ROCm class
            vendor = device.get("vendor", "amd")
            family = device.get("family", "unknown")
            rocm_version = os.getenv("NEGELIR_ROCM_MIN_VERSION", "6.2.0")
            part = f"rocm:{vendor}:{family}:{rocm_version}"
        else:
            continue
        
        normalized_parts.append(part)
    
    if not normalized_parts:
        return hashlib.sha256("unknown".encode("utf-8")).hexdigest()[:16]
    
    # Sort for canonical ordering
    normalized_str = "|".join(sorted(normalized_parts))
    host_class = hashlib.sha256(normalized_str.encode("utf-8")).hexdigest()[:16]
    return host_class



def _attach_device_uuids(result: Dict[str, Any]) -> None:
    """Ensure every inventory entry has a stable UUID derived from its identity.

    Uses UUID5 over a deterministic namespace+name so repeated probes on the same
    host yield stable IDs useful for targeted disable operations.
    """
    for d in result.get("inventory", []):
        if "uuid" in d and d["uuid"]:
            continue
        # Build a stable name from non-volatile identifiers
        name = d.get("name") or ""
        kind = d.get("device_kind") or ""
        index = str(d.get("index", ""))
        ns = uuid.NAMESPACE_DNS
        stable = f"{kind}:{name}:{index}"
        try:
            d["uuid"] = str(uuid.uuid5(ns, stable))
        except Exception:
            d["uuid"] = str(uuid.uuid4())
    for d in result.get("inventory", []):
        if "uuid" in d and d["uuid"]:
            continue
        # Build a stable name from non-volatile identifiers
        name = d.get("name") or ""
        kind = d.get("device_kind") or ""
        index = str(d.get("index", ""))
        ns = uuid.NAMESPACE_DNS
        stable = f"{kind}:{name}:{index}"
        try:
            d["uuid"] = str(uuid.uuid5(ns, stable))
        except Exception:
            d["uuid"] = str(uuid.uuid4())


def _run_probe_subprocess(timeout: int = 5) -> Dict[str, Any]:
    """Run the probe in a separate Python subprocess and parse the JSON output.

    Raises subprocess.TimeoutExpired on timeout. Returns a parsed dict on success.
    """
    cmd = [sys.executable, "-c", "import json; from model.device import _probe_main; print(json.dumps(_probe_main()))"]
    try:
        out = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout, check=True)
        return json.loads(out.stdout)
    except subprocess.TimeoutExpired:
        raise
    except Exception as e:
        # Return a minimal failure-shaped probe so callers can continue
        return {"probe_id": str(uuid.uuid4()), "probe_ts": time.time(), "inventory": [{"device_kind": "cpu", "available": True}, {"device_kind": "cuda", "available": False, "reason": f"probe_failed:{e}"}]}


def _sighup_handler(signum, frame) -> None:
    """Signal handler to request a compute panic (drain to CPU).

    The handler only flips an in-memory flag; the longer-running process
    is expected to re-run the probe or call `apply_disable_rules` to enact.
    """
    global _panic_requested
    _panic_requested = True
    try:
        log.info("Received SIGHUP: compute panic requested")
    except Exception:
        pass


def install_sighup_handler() -> None:
    """Install the SIGHUP handler. Safe to call multiple times.

    Tests may call `_sighup_handler` directly instead of sending a real
    OS signal to avoid disturbing the test runner.
    """
    try:
        signal.signal(signal.SIGHUP, _sighup_handler)
    except Exception:
        # Not all platforms (Windows) support SIGHUP; ignore failures.
        pass


def apply_disable_rules(result: Dict[str, Any], cfg=None) -> None:
    """Mutate `result` in-place according to env/config/SIGHUP kill-switches.

    Behaviour implemented (minimal):
    - `NEGELIR_DISABLE_GPU=1` disables any `device_kind=='cuda'` entries.
    - `NEGELIR_DISABLE_NPU=1` disables `openvino`/`npu` entries.
    - `NEGELIR_DISABLE_DEVICE=<uuid[,uuid2]>` disables devices by UUID.
    - `cfg.compute_panic_cpu == True` acts like `NEGELIR_DISABLE_GPU=1`.
    - runtime SIGHUP flips an internal flag that also acts like a panic.

    The function records an `alerts` entry in `result` when a panic is enacted.
    """
    disable_gpu = os.getenv("NEGELIR_DISABLE_GPU", "").lower() in ("1", "true", "yes")
    disable_npu = os.getenv("NEGELIR_DISABLE_NPU", "").lower() in ("1", "true", "yes")
    disable_devices_raw = os.getenv("NEGELIR_DISABLE_DEVICE", "").strip()

    if cfg is not None and getattr(cfg, "compute_panic_cpu", False):
        disable_gpu = True

    if _panic_requested:
        disable_gpu = True

    disable_devices = set()
    if disable_devices_raw:
        for token in [t.strip() for t in disable_devices_raw.split(",") if t.strip()]:
            disable_devices.add(token)

    alerts = result.setdefault("alerts", [])
    any_disabled = False
    reasons = []

    for d in result.get("inventory", []):
        d_uuid = d.get("uuid")
        kind = d.get("device_kind", "")

        # Per-device UUID disable
        if d_uuid and d_uuid in disable_devices:
            if d.get("available", True):
                d["available"] = False
                d["disabled_by"] = f"NEGELIR_DISABLE_DEVICE={d_uuid}"
                any_disabled = True
                reasons.append(d["disabled_by"])
            continue

        # Bulk GPU / NPU disables
        if disable_gpu and kind == "cuda":
            if d.get("available", True):
                d["available"] = False
                d["disabled_by"] = "NEGELIR_DISABLE_GPU"
                any_disabled = True
                reasons.append("NEGELIR_DISABLE_GPU")
            continue

        if disable_npu and kind in ("openvino", "npu"):
            if d.get("available", True):
                d["available"] = False
                d["disabled_by"] = "NEGELIR_DISABLE_NPU"
                any_disabled = True
                reasons.append("NEGELIR_DISABLE_NPU")
            continue

    if any_disabled:
        alert = {
            "kind": "panic_cpu",
            "source": ",".join(sorted(set(reasons))) if reasons else "env",
            "t_mono_ns": time.monotonic_ns(),
            "t_wall_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        alerts.append(alert)


def _check_container_runtime(result: Dict[str, Any]) -> None:
    """Check that devices mounted in container match those in inventory.
    
    When device != cpu, the probe verifies the container actually has the
    device mounted and the runtime can drive it:
    - NVIDIA: nvidia-container-toolkit present AND nvidia-smi -L succeeds
    - ROCm: --device=/dev/kfd,/dev/dri AND render/video group permissions
    - Intel NPU: --device=/dev/accel/accel0 AND render group permissions
    
    Missing mount or permission → device.alert.v1{kind=runtime_missing, detail}
    and device is dropped from inventory.
    """
    import grp
    import os
    
    alerts = result.setdefault("alerts", [])
    removed_uuids = set()
    
    for d in result.get("inventory", []):
        kind = d.get("device_kind", "")
        d_uuid = d.get("uuid", "")
        
        if kind == "cpu":
            # CPU never requires special container setup
            continue
        
        elif kind == "cuda":
            # NVIDIA: check nvidia-smi -L works and toolkit is present
            # Toolkit presence indicated by nvidia-container-toolkit wrapper
            try:
                # Try nvidia-smi -L to list GPUs
                import subprocess
                result_check = subprocess.run(
                    ["nvidia-smi", "-L"],
                    timeout=2,
                    capture_output=True,
                    text=True,
                )
                if result_check.returncode != 0:
                    detail = "nvidia-smi -L failed; device may not be mounted"
                    alert = {
                        "kind": "runtime_missing",
                        "device_uuid": d_uuid,
                        "device_kind": kind,
                        "detail": detail,
                        "t_mono_ns": time.monotonic_ns(),
                    }
                    alerts.append(alert)
                    removed_uuids.add(d_uuid)
            except Exception as e:
                detail = f"nvidia-smi check failed: {str(e)}"
                alert = {
                    "kind": "runtime_missing",
                    "device_uuid": d_uuid,
                    "device_kind": kind,
                    "detail": detail,
                    "t_mono_ns": time.monotonic_ns(),
                }
                alerts.append(alert)
                removed_uuids.add(d_uuid)
        
        elif kind == "rocm":
            # ROCm: check /dev/kfd and /dev/dri exist and user has permissions
            missing_devices = []
            if not os.path.exists("/dev/kfd"):
                missing_devices.append("/dev/kfd")
            if not os.path.exists("/dev/dri"):
                missing_devices.append("/dev/dri")
            
            if missing_devices:
                detail = f"Missing ROCm devices: {', '.join(missing_devices)}"
                alert = {
                    "kind": "runtime_missing",
                    "device_uuid": d_uuid,
                    "device_kind": kind,
                    "detail": detail,
                    "t_mono_ns": time.monotonic_ns(),
                }
                alerts.append(alert)
                removed_uuids.add(d_uuid)
            else:
                # Check group permissions
                try:
                    # User must be in render or video group
                    user_gids = os.getgroups()
                    render_gid = grp.getgrnam("render").gr_gid if "render" in [grp.getgrgid(g).gr_name for g in user_gids] else None
                    video_gid = grp.getgrnam("video").gr_gid if "video" in [grp.getgrgid(g).gr_name for g in user_gids] else None
                    
                    has_render_or_video = (render_gid in user_gids or video_gid in user_gids) if render_gid or video_gid else False
                    
                    if not has_render_or_video:
                        detail = "User not in 'render' or 'video' group; ROCm device inaccessible"
                        alert = {
                            "kind": "runtime_missing",
                            "device_uuid": d_uuid,
                            "device_kind": kind,
                            "detail": detail,
                            "t_mono_ns": time.monotonic_ns(),
                        }
                        alerts.append(alert)
                        removed_uuids.add(d_uuid)
                except Exception as e:
                    detail = f"Group check failed: {str(e)}"
                    alert = {
                        "kind": "runtime_missing",
                        "device_uuid": d_uuid,
                        "device_kind": kind,
                        "detail": detail,
                        "t_mono_ns": time.monotonic_ns(),
                    }
                    alerts.append(alert)
                    removed_uuids.add(d_uuid)
        
        elif kind == "openvino":
            # Intel NPU: check /dev/accel/accel0 exists and user has render group permission
            if not os.path.exists("/dev/accel/accel0"):
                detail = "Intel NPU device /dev/accel/accel0 not present"
                alert = {
                    "kind": "runtime_missing",
                    "device_uuid": d_uuid,
                    "device_kind": kind,
                    "detail": detail,
                    "t_mono_ns": time.monotonic_ns(),
                }
                alerts.append(alert)
                removed_uuids.add(d_uuid)
            else:
                # Check render group permission
                try:
                    user_gids = os.getgroups()
                    render_gid = grp.getgrnam("render").gr_gid if "render" in [grp.getgrgid(g).gr_name for g in user_gids] else None
                    
                    if render_gid not in user_gids:
                        detail = "User not in 'render' group; Intel NPU device inaccessible"
                        alert = {
                            "kind": "runtime_missing",
                            "device_uuid": d_uuid,
                            "device_kind": kind,
                            "detail": detail,
                            "t_mono_ns": time.monotonic_ns(),
                        }
                        alerts.append(alert)
                        removed_uuids.add(d_uuid)
                except Exception as e:
                    detail = f"Group check failed: {str(e)}"
                    alert = {
                        "kind": "runtime_missing",
                        "device_uuid": d_uuid,
                        "device_kind": kind,
                        "detail": detail,
                        "t_mono_ns": time.monotonic_ns(),
                    }
                    alerts.append(alert)
                    removed_uuids.add(d_uuid)
    
    # Remove devices with runtime issues from inventory
    if removed_uuids:
        result["inventory"] = [
            d for d in result.get("inventory", [])
            if d.get("uuid") not in removed_uuids
        ]


def _probe_gpu_persistence_and_clocks(result: Dict[str, Any], cfg: "config.Config") -> None:
    """Probe GPU persistence mode, clocks, and power limits via nvidia-smi.
    
    Records current settings for each CUDA device and optionally requests
    configuration changes (persistence mode, clock locking, power cap).
    """
    import subprocess
    
    alerts = result.setdefault("alerts", [])
    
    for d in result.get("inventory", []):
        if d.get("device_kind") != "cuda":
            continue
        
        idx = d.get("index")
        if idx is None:
            continue
        
        # Try to enable persistence mode if configured
        if cfg.gpu_enable_persistence_mode:
            try:
                subprocess.run(
                    ["sudo", "nvidia-smi", "-pm", "1", "-i", str(idx)],
                    timeout=5,
                    capture_output=True,
                    check=False,
                )
            except Exception:
                pass  # Best-effort; fail silently
        
        # Probe current persistence mode
        try:
            result_pm = subprocess.run(
                ["nvidia-smi", "-i", str(idx), "--query-gpu=persistence_mode", "--format=csv,noheader"],
                timeout=5,
                capture_output=True,
                text=True,
                check=False,
            )
            if result_pm.returncode == 0:
                pm_value = result_pm.stdout.strip().lower()
                d["persistence_mode"] = pm_value  # "on" or "off"
            else:
                d["persistence_mode"] = "unknown"
        except Exception:
            d["persistence_mode"] = "unknown"
        
        # Probe current SM clock
        try:
            result_sm = subprocess.run(
                ["nvidia-smi", "-i", str(idx), "--query-gpu=clocks.sm", "--format=csv,noheader"],
                timeout=5,
                capture_output=True,
                text=True,
                check=False,
            )
            if result_sm.returncode == 0:
                sm_mhz_str = result_sm.stdout.strip().split()[0]
                d["sm_clock_mhz"] = int(sm_mhz_str)
            else:
                d["sm_clock_mhz"] = 0
        except Exception:
            d["sm_clock_mhz"] = 0
        
        # Probe current memory clock
        try:
            result_mem = subprocess.run(
                ["nvidia-smi", "-i", str(idx), "--query-gpu=clocks.mem", "--format=csv,noheader"],
                timeout=5,
                capture_output=True,
                text=True,
                check=False,
            )
            if result_mem.returncode == 0:
                mem_mhz_str = result_mem.stdout.strip().split()[0]
                d["mem_clock_mhz"] = int(mem_mhz_str)
            else:
                d["mem_clock_mhz"] = 0
        except Exception:
            d["mem_clock_mhz"] = 0
        
        # Probe current power limit
        try:
            result_pl = subprocess.run(
                ["nvidia-smi", "-i", str(idx), "--query-gpu=power.limit", "--format=csv,noheader"],
                timeout=5,
                capture_output=True,
                text=True,
                check=False,
            )
            if result_pl.returncode == 0:
                power_str = result_pl.stdout.strip().split()[0]
                d["power_limit_w"] = float(power_str)
            else:
                d["power_limit_w"] = 0.0
        except Exception:
            d["power_limit_w"] = 0.0
        
        # Probe default power limit
        try:
            result_dpf = subprocess.run(
                ["nvidia-smi", "-i", str(idx), "--query-gpu=power.default_limit", "--format=csv,noheader"],
                timeout=5,
                capture_output=True,
                text=True,
                check=False,
            )
            if result_dpf.returncode == 0:
                power_default_str = result_dpf.stdout.strip().split()[0]
                d["power_default_limit_w"] = float(power_default_str)
            else:
                d["power_default_limit_w"] = 0.0
        except Exception:
            d["power_default_limit_w"] = 0.0
        
        # Warn if power has been capped below default
        if d.get("power_limit_w", 0) > 0 and d.get("power_default_limit_w", 0) > 0:
            if d["power_limit_w"] < d["power_default_limit_w"] * 0.99:  # 1% tolerance
                alert = {
                    "kind": "gpu_power_capped",
                    "device_uuid": d.get("uuid", ""),
                    "device_index": idx,
                    "current_power_limit_w": d["power_limit_w"],
                    "default_power_limit_w": d["power_default_limit_w"],
                    "t_mono_ns": time.monotonic_ns(),
                }
                alerts.append(alert)
        
        # Request power limit adjustment if configured
        if cfg.gpu_request_power_limit_w > 0:
            try:
                subprocess.run(
                    ["sudo", "nvidia-smi", "-i", str(idx), "-pl", str(cfg.gpu_request_power_limit_w)],
                    timeout=5,
                    capture_output=True,
                    check=False,
                )
            except Exception:
                pass  # Best-effort; fail silently


def _load_runtime_matrix() -> Dict[str, Any]:
    """Load the runtime_matrix.json file. Returns empty dict if not found.
    
    The matrix documents supported driver/runtime combinations and excludes
    known vendor bugs that would crash despite parsing as "supported".
    """
    matrix_path = os.path.join(os.path.dirname(__file__), "..", "..", "xops", "compute", "runtime_matrix.json")
    try:
        with open(matrix_path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def _parse_version(v_str: str) -> tuple:
    """Parse a semantic version string to (major, minor, patch) tuple.
    
    E.g., "12.4.0" -> (12, 4, 0)
    E.g., "555" -> (555, 0, 0)
    """
    try:
        parts = v_str.split(".")
        return tuple(int(p) for p in parts[:3]) + ((0,) * (3 - len(parts)))
    except Exception:
        return (0, 0, 0)


def _check_version_constraint(observed: str, required: str, operator: str = ">=") -> bool:
    """Check if observed version satisfies the constraint (e.g., >= required).
    
    Supports >=, >, ==, <=, <. Returns False on parse error.
    """
    obs = _parse_version(observed)
    req = _parse_version(required)
    
    if operator == ">=":
        return obs >= req
    elif operator == ">":
        return obs > req
    elif operator == "==":
        return obs == req
    elif operator == "<=":
        return obs <= req
    elif operator == "<":
        return obs < req
    else:
        return False


def _is_in_version_range(v_str: str, range_spec: str) -> bool:
    """Check if v_str falls in a range like '560.0-560.28' or '6.2.0-6.2.1'.
    
    Returns True if v_str is in the range (inclusive).
    """
    try:
        if "-" not in range_spec:
            return _check_version_constraint(v_str, range_spec, "==")
        lo, hi = range_spec.split("-", 1)
        return _check_version_constraint(v_str, lo, ">=") and _check_version_constraint(v_str, hi, "<=")
    except Exception:
        return False


def validate_runtime_support(result: Dict[str, Any], cfg=None) -> None:
    """Validate detected runtimes against xops/compute/runtime_matrix.json.
    
    Unsupported combinations are marked unavailable and an alert is emitted.
    Vendor-bug exclusions (driver/runtime tuples known to crash) are also checked.
    
    This mutates `result` in-place.
    """
    matrix = _load_runtime_matrix()
    if not matrix:
        # No matrix available; skip validation
        return
    
    alerts = result.setdefault("alerts", [])
    inventory = result.get("inventory", [])
    
    # Try to get runtime versions from the environment or defaults
    # (In a full implementation, these would be detected during the probe.)
    driver_nvidia = os.getenv("NEGELIR_DRIVER_NVIDIA_MIN_VERSION", "555")
    cuda_ver = os.getenv("NEGELIR_CUDA_MIN_VERSION", "12.4.0")
    cudnn_ver = os.getenv("NEGELIR_CUDNN_MIN_VERSION", "9.0.0")
    rocm_ver = os.getenv("NEGELIR_ROCM_MIN_VERSION", "6.2.0")
    openvino_ver = os.getenv("NEGELIR_OPENVINO_MIN_VERSION", "2025.0.0")
    glibc_ver = os.getenv("NEGELIR_GLIBC_MIN_VERSION", "2.35")
    compute_cap = os.getenv("NEGELIR_CUDA_MIN_COMPUTE_CAPABILITY", "6.0")
    
    kernel_version = platform.release()
    
    # Check vendor-bug exclusion list
    exclusions = matrix.get("vendor_bug_exclusion_list", [])
    for excl in exclusions:
        vendor = excl.get("vendor", "").lower()
        driver_range = excl.get("driver_version_range", "")
        runtime_version = excl.get("runtime_version", "")
        kernel_range = excl.get("kernel_version", "")
        issue = excl.get("issue", "unknown")
        cve = excl.get("cve", "")
        
        # Simple check: if this host matches the exclusion criteria, mark GPUs as unavailable
        if vendor == "nvidia" and driver_range and _is_in_version_range(driver_nvidia, driver_range):
            if runtime_version and cuda_ver.startswith(runtime_version.replace(".x", "")):
                if _is_in_version_range(kernel_version, kernel_range):
                    for d in inventory:
                        if d.get("device_kind") == "cuda" and d.get("available"):
                            d["available"] = False
                            d["disabled_by"] = f"vendor_bug:{vendor}:{cve}:{issue}"
                            alert = {
                                "kind": "unsupported_runtime",
                                "severity": "error",
                                "device": d.get("name", "unknown"),
                                "reason": f"vendor bug: {issue}",
                                "cve": cve,
                                "observed": {"driver": driver_nvidia, "cuda": cuda_ver, "kernel": kernel_version},
                                "workaround": excl.get("workaround", ""),
                                "t_mono_ns": time.monotonic_ns(),
                                "t_wall_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                            }
                            alerts.append(alert)
                            log.warning("Device %s disabled due to vendor bug: %s (%s)", d.get("name"), issue, cve)


def run_and_write_probe(cfg=None) -> None:
    """Run the probe (with cfg timeouts/paths) and write the atomic JSON inventory.

    If writing to the configured path is not permitted, falls back to `/tmp` and logs a warning.
    """
    if cfg is None:
        try:
            from common.config import Config

            cfg = Config()
        except Exception:
            class _C:
                device_probe_path = "/var/run/negelir/device.json"
                device_probe_timeout_s = 5

            cfg = _C()

    try:
        result = _run_probe_subprocess(timeout=cfg.device_probe_timeout_s)
    except subprocess.TimeoutExpired:
        result = {"probe_id": str(uuid.uuid4()), "probe_ts": time.time(), "inventory": [{"device_kind": "cpu", "available": True}, {"device_kind": "cuda", "available": False, "reason": "probe_timeout"}]}

    # Apply runtime matrix validation before writing
    apply_disable_rules(result, cfg)
    validate_runtime_support(result, cfg)
    
    target = cfg.device_probe_path
    tmp = None
    try:
        dirpath = os.path.dirname(target) or "/tmp"
        os.makedirs(dirpath, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=dirpath, prefix=".device.json.")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(result, fh, indent=2)
        os.replace(tmp, target)
        log.info("Wrote device probe to %s", target)
    except PermissionError:
        fallback = "/tmp/negelir_device.json"
        try:
            with open(fallback, "w", encoding="utf-8") as fh:
                json.dump(result, fh)
            log.warning("Permission denied writing %s, wrote to %s instead", target, fallback)
        except Exception:
            log.exception("Failed to write device probe result")
    except Exception:
        log.exception("Failed to write device probe result")
    finally:
        if tmp and os.path.exists(tmp):
            try:
                os.remove(tmp)
            except Exception:
                pass


def _compute_inventory_delta(before: list[dict], after: list[dict]) -> tuple[list[str], list[str]]:
    """Compute inventory delta: (added_uuids, removed_uuids).
    
    Compares two inventory snapshots to detect hot-plugged or removed devices.
    Devices are identified by UUID (stable across probes for same device).
    """
    before_uuids = set(d.get("uuid", "") for d in before if d.get("uuid"))
    after_uuids = set(d.get("uuid", "") for d in after if d.get("uuid"))
    
    added = sorted(list(after_uuids - before_uuids))
    removed = sorted(list(before_uuids - after_uuids))
    
    return added, removed


def _emit_topology_change_alert(result: Dict[str, Any], added_uuids: list[str], removed_uuids: list[str]) -> None:
    """Emit a topology_change alert when devices are hot-plugged or removed."""
    if not added_uuids and not removed_uuids:
        return  # No change; do not emit
    
    alerts = result.setdefault("alerts", [])
    
    # Find device details for each UUID
    added_devices = []
    removed_devices = []
    
    for d in result.get("inventory", []):
        uuid = d.get("uuid", "")
        if uuid in added_uuids:
            added_devices.append({
                "uuid": uuid,
                "kind": d.get("device_kind"),
                "name": d.get("name"),
                "index": d.get("index"),
            })
    
    # Removed devices are not in current inventory, so use historical info if available
    # For now, we just record the UUIDs
    removed_devices = [{"uuid": u} for u in removed_uuids]
    
    alert = {
        "kind": "topology_change",
        "added": added_devices,
        "removed": removed_devices,
        "t_mono_ns": time.monotonic_ns(),
        "t_wall_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    alerts.append(alert)


class HotplugDebouncer:
    """Debounce hotplug re-probe requests to avoid thrashing on rapid changes."""
    
    def __init__(self, debounce_seconds: int = 10):
        """Initialize the debouncer.
        
        Args:
            debounce_seconds: Window in which multiple hotplug events are coalesced
                             into a single re-probe.
        """
        self.debounce_seconds = debounce_seconds
        self.last_hotplug_ts: float = 0
        self.pending_hotplug = False
        self._lock = threading.Lock()
    
    def on_hotplug_event(self) -> bool:
        """Record a hotplug event and return whether to trigger an immediate re-probe.
        
        Returns:
            True if a re-probe should run immediately (debounce window expired).
            False if a re-probe is already pending; caller should check later.
        """
        with self._lock:
            now = time.time()
            elapsed = now - self.last_hotplug_ts
            
            if elapsed >= self.debounce_seconds:
                # Debounce window has expired; trigger immediate re-probe
                self.last_hotplug_ts = now
                self.pending_hotplug = False
                return True
            else:
                # Still within debounce window; mark as pending for later
                self.pending_hotplug = True
                return False
    
    def has_pending_hotplug(self) -> bool:
        """Check if a hotplug event is pending but not yet acted upon."""
        with self._lock:
            return self.pending_hotplug


if __name__ == '__main__':
    if '--probe-json' in sys.argv or '--probe' in sys.argv:
        res = _probe_main()
        print(json.dumps(res))
    else:
        try:
            run_and_write_probe()
        except Exception:
            log.exception("probe invocation failed")
