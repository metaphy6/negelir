# Phase 11.3 — CPU compute governor (peer of the GPU arbiter)

> Extracted from `docs/planning/ROADMAP.md` §11.3
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/phase10/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 11.3 CPU compute governor (peer of the GPU arbiter)

> **Why this exists.** The original Phase 11 silently assumed CPU is
> "always available, no governance needed". In practice, three predictor
> replicas + the humanizer + the coder all spawning their own BLAS
> thread pools at `nproc` size each is the #1 cause of CPU-tier latency
> regressions. This sub-phase is binding for the CPU baseline.

- [ ] **Single thread-budget owner.** A per-host CPU governor (`ai/swarm/sdk/cpu_governor.py`) owns `OMP_NUM_THREADS`, `MKL_NUM_THREADS`, `OPENBLAS_NUM_THREADS`, `TORCH_NUM_THREADS`, `XGBOOST_NUM_THREADS`, `RAYON_NUM_THREADS`, `TOKENIZERS_PARALLELISM` for every agent on the host. Default policy: each agent gets `max(1, floor(cores_physical / active_agents))` and never exceeds it. Co-resident agents must claim a thread budget before loading a model; oversubscription is refused.
- [ ] **NUMA & affinity.** On multi-socket hosts the governor pins each agent to a single NUMA node via `taskset` / `sched_setaffinity` and binds memory with `numactl --membind`. Cross-node memory traffic is reported in telemetry (`negelir_cpu_numa_remote_pct`).
- [ ] **CPU governor mode.** Probe-side check that `cpufreq` is `performance` (or `schedutil` with boost) on prod hosts; warn loudly if `powersave` (common default on cloud VPS images) — that one knob is worth ~30 % p95 latency.
- [ ] **SIMD gating.** Wheels compiled with AVX-512 / SVE are loaded only when the §11.1 CPU fingerprint advertises support; otherwise the AVX2 / NEON wheel is selected. Mismatch → loader refuses + `device.alert.v1{kind=simd_mismatch}`.
- [ ] **cgroup / container limits.** The governor reads `cgroup` CPU quota (`/sys/fs/cgroup/cpu.max`) so it doesn't claim cores it isn't allowed to use under K8s requests/limits. Required for Phase 14.
- [ ] **CPU LLM backend.** When an LLM-class agent runs on CPU it uses `llama.cpp` (or the project's pinned fork) with `n_threads = governor budget`, `mmap = true`, and a quantization picked by §11.4; never raw `transformers` on CPU.
- [ ] **Denormal handling (FTZ/DAZ).** The governor sets flush-to-zero / denormals-are-zero (`_MM_SET_FLUSH_ZERO_MODE`, `_MM_SET_DENORMALS_ZERO_MODE` on x86; `FPCR.FZ` on ARM) **explicitly** at thread-pool init — both knobs leak from the host glibc / OpenMP startup and silently change numerics. The chosen mode is recorded in the bundle-load audit so a parity miss can be tracked back to a denormal-flag mismatch.
- [ ] **AMX / VNNI gating (Sapphire Rapids+).** When the §11.1 fingerprint advertises `amx_bf16` / `amx_int8` or `avx512_vnni`, INT8 / bf16 GEMM kernels (oneDNN, llama.cpp) are enabled; otherwise the AVX2 path is selected. Selection is logged so a "why is bf16 LLM slow on this box" answer is one log line away.
- [ ] **Hyperthreading policy.** `cfg.cpu_governor_use_smt=false` by default for predictor / inference workloads (SMT siblings contend for the same FPU and hurt p99 more than they help median); the governor counts physical cores only. Operators may flip on per-host for batch training jobs.
- [ ] **No fork+CUDA.** The governor refuses to spawn a worker via `fork()` after CUDA has been initialised in the parent; only `spawn` / `forkserver` is allowed. (CUDA contexts do not survive `fork`; the resulting silent corruption is a known footgun.)
