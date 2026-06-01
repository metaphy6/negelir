# Phase 11.12 — Training-time compute path (handoff to Phase 6)

> Extracted from `docs/planning/ROADMAP.md` §11.12
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/phase10/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 11.12 Training-time compute path (handoff to Phase 6)

- [ ] **Training is a separate compute class.** Phase 6 (training pipeline) declares `cfg.training_device` independent of inference; the GPU arbiter treats training as its own priority tier (`priority=training`, lower than `realtime` and `interactive`, equal to `batch`). Training never preempts realtime; realtime always preempts training.
- [ ] **XGB GPU training.** `tree_method=hist`, `device=cuda` when CUDA available; deterministic via fixed seed + `nthread=1` only for parity tests, otherwise governor budget.
- [ ] **Mixed-precision training (deep models, if any).** bf16 on Ampere+, fp16 + GradScaler on Turing/Volta, fp32 on CPU. Loss-scale and grad-overflow events emitted as `train.amp.v1`.
- [ ] **Checkpointing & resumption.** Every training run writes a checkpoint every `cfg.training_checkpoint_interval_s` so a GPU crash mid-train resumes within 1 checkpoint.
- [ ] **Distributed training out of scope** for Phase 11; Phase 14 + a future phase will introduce DDP if a deep predictor lands.
- [ ] **GradScaler skip-step accounting.** Mixed-precision training tracks `skipped_steps_total`; if > `cfg.training_amp_skip_pct` of steps in a window, the trainer demotes to fp32 automatically and alerts.
- [ ] **Gradient checkpointing.** Off by default; opt-in (`cfg.training_grad_checkpoint=true`) for VRAM-tight runs. Trades ~1.3× wall-time for ~3× memory headroom; recorded in the bundle audit so retraining reproduces.
- [ ] **Dataset-shuffle determinism.** Multi-worker loaders use `torch.Generator(device='cpu').manual_seed(global_seed + worker_id)`; tested via `test_training_dataloader_determinism`.
