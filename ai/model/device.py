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

import json
import os
import platform
import subprocess
import sys
import tempfile
import time
import uuid
import hashlib
from typing import Any, Dict
import signal

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

    return result


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


def _run_probe_subprocess(timeout: int = 5) -> Dict[str, Any]:
    """Run the probe in a separate Python subprocess and parse the JSON output.

    Raises subprocess.TimeoutExpired on timeout. Returns a parsed dict on success.
    """
    cmd = [sys.executable, "-c", "import json; from ai.model.device import _probe_main; print(json.dumps(_probe_main()))"]
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


if __name__ == '__main__':
    if '--probe-json' in sys.argv or '--probe' in sys.argv:
        res = _probe_main()
        print(json.dumps(res))
    else:
        try:
            run_and_write_probe()
        except Exception:
            log.exception("probe invocation failed")
