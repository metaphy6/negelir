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
