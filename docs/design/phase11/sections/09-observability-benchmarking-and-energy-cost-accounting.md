# Phase 11.9 — Observability, benchmarking, and energy/cost accounting

> Extracted from `docs/planning/ROADMAP.md` §11.9
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/phase10/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 11.9 Observability, benchmarking, and energy/cost accounting

- [ ] **Prometheus metrics** (exported by every agent that touches a device, names per `COMPUTE_DEVICES.md` §Metrics):
  - `negelir_device_vram_total_bytes{agent,device,gpu_uuid}` gauge
  - `negelir_device_vram_used_bytes{agent,device,gpu_uuid}` gauge
  - `negelir_device_vram_used_bytes_nvml{gpu_uuid,pid}` gauge — *NVML-PID source of truth, used to detect leaks the torch allocator hides*
  - `negelir_device_temperature_celsius{device,gpu_uuid}` gauge
  - `negelir_device_power_watts{device,gpu_uuid}` gauge
  - `negelir_device_throttle_events_total{device,gpu_uuid,reason}` counter (`reason ∈ thermal|power|sw_slowdown|hw_slowdown`)
  - `negelir_device_xid_errors_total{gpu_uuid,xid}` counter
  - `negelir_device_oom_total{agent,device}` counter
  - `negelir_inference_duration_seconds{agent,device,batch_size_bucket}` histogram
  - `negelir_inference_batch_size{agent}` histogram
  - `negelir_inference_queue_depth{agent}` gauge
  - `negelir_gpu_arbiter_lease_wait_seconds{agent,gpu_uuid}` histogram
  - `negelir_gpu_arbiter_preemptions_total{victim,winner}` counter
  - `negelir_gpu_arbiter_anti_flap_blocked_total{agent}` counter
  - `negelir_model_cold_start_seconds{agent,device,cache=hit|miss}` histogram
  - `negelir_compiled_blob_cache_misses_total{kind,device}` counter
  - `negelir_cpu_thread_budget{agent}` gauge (governor-assigned)
  - `negelir_cpu_oversubscription_total{agent}` counter
  - `negelir_cpu_numa_remote_pct{agent}` gauge
  - `negelir_compute_energy_joules_per_inference{agent,device}` gauge (NVML for GPU, RAPL via `/sys/class/powercap/intel-rapl` for CPU; NaN where unavailable)
  - `negelir_compute_cost_usd_per_million_inferences{agent,device}` gauge (computed from `cfg.compute_cost_table_<device>`; emitted only when configured — never fabricated)
- [ ] **Benchmark harness** (`make bench.compute`) runs a fixed corpus through every model on every available device and writes `docs/reports/bench/<date>.md` with throughput (records/s), latency p50/p95/p99, peak VRAM, energy J/inference, and (where configured) $/million-inferences. Each metric is reported as `mean ± stdev (n=runs)` with a 95 % CI; **the regression gate fires only when the new value is outside the prior CI** (so noise alone can't fail CI). A configurable hard floor `cfg.bench_regression_pct` (default 15 %) catches gross regressions even within noise. Bench runs lock GPU clocks (§11.1) when available.
- [ ] **Cold-start budget (cache-aware).** Model load + first inference ≤ `cfg.compute_cold_start_max_ms` per agent **with a warm artifact cache**: predictors 500 ms, sec.input 1500 ms, humanizer 8000 ms, coder 15 000 ms. Cold-cache budgets are 3× these numbers and tracked separately (`cache=miss` label). A model that exceeds the warm-cache budget gets a CUDA Graphs / `torch.compile` warmup step at boot **using a frozen warmup corpus** (`ai/tests/fixtures/warmup/`) — never live data; if still over budget after warmup, the arbiter pre-loads it on the GPU at supervisor start.
- [ ] **Inference batching.** Agents that serve a stream (predictor swarm, sec.input) run a tiny request batcher (`cfg.<agent>_batch_max_records`, `cfg.<agent>_batch_max_wait_ms`) to amortise GPU launch overhead. Batcher is bypassable (`cfg.<agent>_batch=off`) for a clean latency comparison and is itself benchmarked.
- [ ] **Memory-leak detector.** A nightly soak job runs N=10⁵ inferences per agent and asserts `vram_used_bytes_nvml{pid}` returns to within `cfg.compute_leak_tolerance_mb` (default 64 MB) of the warm-baseline; same for RSS. Leak → fails the soak gate.
- [ ] **Crash autopsy.** On `Xid` error or driver hang, the supervisor dumps `nvidia-smi -q`, the last 100 inputs (sanitised), the model registry state, and the arbiter audit tail to `/var/log/negelir/autopsy/<ts>/`; size-capped and rotated.
- [ ] **Adaptive NVML sampling.** NVML poll period is **not** a fixed constant: a closed-loop controller targets `cfg.nvml_poll_self_load_pct` (default 1 %) — high-frequency NVML on a busy GPU can itself add tail latency. Period stays in `[cfg.nvml_poll_s_min, cfg.nvml_poll_s_max]` (default `[1, 30]`); current period is exported as `negelir_nvml_sample_period_seconds` and `sample_skipped_total` counts adaptive-skip events.
