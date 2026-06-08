"""
Phase 11.4 — Parity tolerances and numerical contracts for predictions.

Published tolerances for inference reproducibility across CPU/GPU/NPU.
Each predictor type has its own tolerance based on numerical properties.
"""

from dataclasses import dataclass
from typing import Dict


@dataclass
class PredictorParityTolerance:
    """Parity tolerance for a specific predictor backend."""
    name: str  # "elo", "dixon_coles", "xgb_form", "xgb_xg", "torch_deep", etc.
    epsilon_fp32_cpu_cpu: float  # tolerance for CPU↔CPU comparison at fp32
    epsilon_fp32_cpu_cuda: float  # tolerance for CPU↔CUDA comparison at fp32
    epsilon_bf16: float = None  # tolerance for bf16 (None if not applicable)
    epsilon_fp16: float = None  # tolerance for fp16 (None if not applicable)
    epsilon_int8: float = None  # tolerance for int8 (None if not applicable)


# Phase 11.4 bullet 1: Published parity tolerances
PARITY_TOLERANCES: Dict[str, PredictorParityTolerance] = {
    "elo_pure_python": PredictorParityTolerance(
        name="elo_pure_python",
        epsilon_fp32_cpu_cpu=1e-12,
        epsilon_fp32_cpu_cuda=1e-12,
        description="Pure-Python predictors (Elo, Dixon-Coles closed-form) are parity-bound across CPU/GPU/NPU",
    ),
    "xgb_form": PredictorParityTolerance(
        name="xgb_form",
        epsilon_fp32_cpu_cpu=1e-9,
        epsilon_fp32_cpu_cuda=1e-9,
        description="XGB-form / XGB-xG at fp32; 1e-6 with CUDA hist-method",
    ),
    "torch_deep": PredictorParityTolerance(
        name="torch_deep",
        epsilon_fp32_cpu_cpu=1e-6,
        epsilon_fp32_cpu_cuda=1e-6,
        epsilon_bf16=None,  # bf16/fp16/int8 paths not parity-bound to CPU
        description="Torch deep predictors; bf16/fp16/int8 must carry own tolerances",
    ),
}


@dataclass
class ComputeProvenance:
    """Inference compute provenance stamp (§11.4 bullet 10, §11.15 replay contract)."""
    device: str  # "cuda", "cpu", "npu", "mps"
    gpu_uuid: str = None  # UUID if device is GPU
    dtype: str = None  # "fp32", "bf16", "fp16", "int8", "int4"
    backend: str = None  # "torch", "xgboost", "sklearn", "llama.cpp"
    backend_version: str = None  # e.g., "2.5.0"
    runtime_version: str = None  # CUDA version, OpenVINO version, etc.
    driver_version: str = None  # GPU driver version
    allocator_conf: str = None  # PYTORCH_CUDA_ALLOC_CONF string
    host_compute_fingerprint: str = None  # SHA256 over normalized device records (§11.1)
    bundle_sha256: str = None  # Model bundle hash for replay
    seed: int = None  # global_seed used
    deterministic_flags: Dict[str, bool] = None  # {"use_deterministic_algorithms": true, ...}
    allow_tf32: bool = False  # Whether TF32 was permitted
    engine_sha: str = None  # Compiled engine hash (if applicable)
