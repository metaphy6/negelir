# 🎮 Compute Devices — GPU / CPU / NPU

> Companion to Phase 11 of [`../planning/ROADMAP.md`](../planning/ROADMAP.md).

## 🥇 Selection priority

```
CUDA GPU  →  ROCm GPU  →  Intel NPU (OpenVINO)  →  AMD NPU  →  CPU
```

Override with `NEGELIR_DEVICE=auto|cuda|rocm|npu|cpu`.

## 🎯 Targets

| Host | Device | Used for |
|---|---|---|
| Dev: RTX 4080 mobile, 12 GB | CUDA | Training (XGBoost, LightGBM, TabNet, fine-tuning), inference for security classifier + Turkish humanizer |
| Dev fallback | 12-core CPU + Intel NPU | Categorizer, sec.input classifier (NPU); everything else CPU |
| Single-VM prod | 8 vCPU / 32 GB | CPU only, every agent lighter; no LLM humanizer (`cfg.tqu_humanize=false`) |
| Cloud GPU (future) | NVIDIA A10 / L4 | Training jobs; serving stays mostly CPU for cost |

## 📐 Memory budget (4080m, 12 GB)

| Component | VRAM | Notes |
|---|---|---|
| OS / driver overhead | ~0.8 GB | |
| 1 × XGBoost training | ~1.5 GB peak | not always resident |
| `sec.input.v1` classifier (60 MB model + buffers) | ~0.6 GB | |
| Turkish humanizer (≤ 1 B params, q4) | ~1.2 GB | only when `tqu_humanize=true` |
| Coder LLM (Phase 8.3, opt-in) | ~3.5 GB | mutually exclusive with humanizer |
| Slack / fragmentation | ~1 GB | |
| **Total typical** | **~5–6 GB** | leaves room for one more model |

A tiny in-process **GPU scheduler** (`ai/swarm/sdk/gpu_arbiter.py`) round-robins
LLM-class loads so we don't double-load.

## 🔁 CPU fallback contract

- Every agent must pass its tests under `pytest -m cpu_only`.
- The device probe writes `device.json` to a shared tmpfs so all agents agree on the choice.
- Predictor backends self-select per-call: `xgb_model.predict(data, device=cfg.device)`.

## 🧮 NPU details

- **Intel** (Meteor Lake / Lunar Lake / Arrow Lake): OpenVINO 2025+. We target `categorizer.v1` and `sec.input.v1` because they fit comfortably in NPU memory and benefit from low-power sustained inference.
- **AMD XDNA**: stretch goal; behind `NEGELIR_NPU_VENDOR=amd`. Tooling is younger; no agent depends on it as primary.
- **NPU absent?** Agents run on CPU automatically. No code change.

## 🧊 Image strategy

Two ML-image flavors built from a common base:

- `ai-base:<digest>` — Python, system libs, OpenVINO runtime.
- `ai-cpu:<digest>` — adds `xgboost`, `lightgbm`, `torch` CPU wheels.
- `ai-gpu:<digest>` — adds CUDA wheels, `torch+cu*`, `xgboost-gpu`.

`docker-compose.yml` picks via `AI_IMAGE_FLAVOR=cpu|gpu` (default `gpu` on dev,
`cpu` in `compose.prod.yml` unless explicitly switched).

## 🪟 Platform-specific notes

### WSL2 / Windows GPU

**CUDA on WSL2 requires the host NVIDIA driver only** — do **not** install the CUDA toolkit or drivers inside the container.

#### Setup

1. **Host driver** (Windows only): Install NVIDIA driver for Windows (e.g., Game Ready Driver ≥ 530).
   The driver automatically exposes `/dev/dxg` inside WSL2 containers.

2. **Container setup**: `docker-compose.yml` must bind `/dev/dxg`:
   ```yaml
   services:
     ai:
       devices:
         - /dev/dxg:/dev/dxg
       environment:
         CUDA_VISIBLE_DEVICES: "0"  # optional; auto-detected if not set
   ```

3. **Verify**: Inside the container, run `nvidia-smi -L`. If `/dev/dxg` is missing or `nvidia-smi` fails, WSL2 GPU acceleration is unavailable.

#### Constraints

- **WSL2 GPU is best-effort**: Performance is lower than native Linux or Windows CUDA due to inter-layer overhead. Use for dev/test only; do not pin production workloads to WSL2.
- **Older WSL2 kernels** may not expose `/dev/dxg`. Update WSL2: `wsl --update`.
- **Multi-GPU on WSL2**: Limited or unavailable. Single GPU workloads only.
- The device probe (§11.1) checks for `/dev/dxg` presence when `NEGELIR_DEVICE=auto`. If absent, it falls back to CPU.

#### Troubleshooting

| Problem | Cause | Fix |
|---|---|---|
| `nvidia-smi: not found` | CUDA toolkit not installed on host | Install NVIDIA driver (not toolkit) on Windows host |
| `CUDA_ERROR_UNKNOWN` during probe | `/dev/dxg` missing in container | Add `devices: [/dev/dxg:/dev/dxg]` to docker-compose.yml |
| Device shows as `available=false` with reason `runtime_missing` | Container lacks `/dev/dxg` mount | Re-run `wsl --update` and rebuild compose stack |

### Apple Silicon (MPS)

**Apple MPS support is development-only** (`cfg.allow_mps=false` by default, production never selects MPS).

- Requires `torch ≥ 2.0` with MPS backend enabled.
- Known limitation: **no fp64 support**. Predictors that require fp64 anywhere in the graph fall back to CPU automatically.
- The device probe marks MPS unavailable (`available=false`) if `torch.backends.mps.is_available()` returns false.
- Nightly parity tests (maintainer-run, optional) catch MPS divergence early. Failure does not block CI.
