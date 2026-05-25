# Phase 11.6 — Cross-stack support matrix (CUDA / ROCm / NPU / CPU / MPS)

> Extracted from `docs/planning/ROADMAP.md` §11.6
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/nlp/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 11.6 Cross-stack support matrix (CUDA / ROCm / NPU / CPU / MPS)

| Backend | Vendor | Status (Phase 11) | Validated workloads | Parity bound to CPU? |
|---|---|---|---|---|
| `torch+cu124` | NVIDIA | **primary** | predictors, humanizer, coder, sec.input | yes (§11.4) |
| `xgboost-gpu` (CUDA) | NVIDIA | **primary** | XGB training + inference | yes |
| `tensorrt` (optional layer) | NVIDIA | opt-in | predictors (engine cache) | yes (FP32 engine only) |
| `torch+rocm6` | AMD | secondary | predictors, humanizer (no coder) | yes |
| `xgboost` (ROCm) | AMD | secondary | XGB training (CPU inference for parity) | n/a (training) |
| OpenVINO 2025+ | Intel | NPU + CPU | categorizer, sec.input | calibrated (`acc_drop_pct`) |
| XDNA / XRT | AMD | stretch | sec.input (opt-in) | calibrated |
| `torch+mps` | Apple | dev-only | parity testing on macOS | best-effort |
| CPU (`xgboost-cpu`, `torch-cpu`, `llama.cpp`) | any | **baseline** | every workload, every test | reference |

- [ ] One row per backend lands with a smoke test (`make test.compute BACKEND=<name>`) that exercises a tiny model end-to-end and asserts parity vs. CPU within the §11.4 tolerance. Skipped (not xfail) when the backend is absent on the runner; a skipped row is rendered amber in the bench report.
