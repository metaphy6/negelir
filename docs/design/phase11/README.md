# `docs/design/phase11/` — Phase 11 detail

> **Why this folder exists.** Phase 11 (GPU/CPU/NPU Compute Strategy) grew
> past ROADMAP's review threshold and was carved out into one file
> per sub-section, mirroring the Phase 10 pattern at
> [`../phase10/sections/`](../phase10/sections/). Content here is **binding**
> — the ROADMAP §11 stub is now a pointer that delegates to this
> folder.
>
> **Editing rules.**
> 1. Every `[ ]` / `[x]` checkbox flip lives in **this** folder, in
>    the per-section file that owns the item. The ROADMAP §11
>    stub carries only the phase-rollup checkbox.
> 2. Any non-trivial edit triggers `make version.bump COMPONENT=docs
>    LEVEL=minor NOTE="..."` in the same commit (per AGENTS.md §6.1).
> 3. Cross-phase references are authoritative against
>    [`../../planning/ROADMAP.md`](../../planning/ROADMAP.md) and the
>    matching `docs/design/*.md` anchors. Fix this folder if a claim
>    drifts — never silently re-plan a sister phase.
> 4. No rename of these files without explicit human request (URL
>    stability); no deletion of a binding `[ ]` item; no weakening
>    of a Definition-of-Done gate.

## Layout

| Source | File | Theme |
|---|---|---|
| §11.1 | [`sections/01-device-probe-registry.md`](sections/01-device-probe-registry.md) | Device probe & registry (`ai/model/device.py` + `ai/common/devices/`) |
| §11.2 | [`sections/02-gpu-arbiter.md`](sections/02-gpu-arbiter.md) | GPU arbiter (`ai/swarm/sdk/gpu_arbiter.py`) |
| §11.3 | [`sections/03-cpu-compute-governor.md`](sections/03-cpu-compute-governor.md) | CPU compute governor (peer of the GPU arbiter) |
| §11.4 | [`sections/04-determinism-numerical-parity-and-quantization.md`](sections/04-determinism-numerical-parity-and-quantization.md) | Determinism, numerical parity, and quantization (binding for Phase 5) |
| §11.5 | [`sections/05-npu-support.md`](sections/05-npu-support.md) | NPU support (Intel OpenVINO + AMD XDNA + Apple MPS) |
| §11.6 | [`sections/06-cross-stack-support-matrix.md`](sections/06-cross-stack-support-matrix.md) | Cross-stack support matrix (CUDA / ROCm / NPU / CPU / MPS) |
| §11.7 | [`sections/07-image-strategy-compiled-artifact-cache.md`](sections/07-image-strategy-compiled-artifact-cache.md) | Image strategy (cpu / gpu / npu flavors) + compiled-artifact cache |
| §11.8 | [`sections/08-cloud-parity-k8s.md`](sections/08-cloud-parity-k8s.md) | Cloud parity & K8s |
| §11.9 | [`sections/09-observability-benchmarking-and-energy-cost-accounting.md`](sections/09-observability-benchmarking-and-energy-cost-accounting.md) | Observability, benchmarking, and energy/cost accounting |
| §11.10 | [`sections/10-failure-modes-graceful-degradation.md`](sections/10-failure-modes-graceful-degradation.md) | Failure modes & graceful degradation (binding for Phase 12 chaos) |
| §11.11 | [`sections/11-security-supply-chain.md`](sections/11-security-supply-chain.md) | Security & supply chain |
| §11.12 | [`sections/12-training-time-compute-path.md`](sections/12-training-time-compute-path.md) | Training-time compute path (handoff to Phase 6) |
| §11.13 | [`sections/13-heterogeneous-concurrent-routing.md`](sections/13-heterogeneous-concurrent-routing.md) | Heterogeneous concurrent routing (`ai/swarm/sdk/compute_router.py`) |
| §11.14 | [`sections/14-llm-class-serving-primitives.md`](sections/14-llm-class-serving-primitives.md) | LLM-class serving primitives |
| §11.15 | [`sections/15-bundle-storage-hot-swap-and-inference-replay.md`](sections/15-bundle-storage-hot-swap-and-inference-replay.md) | Bundle storage, hot-swap, and inference replay |
| §11.16 | [`sections/16-vendor-bug-registry-runtime-quirks.md`](sections/16-vendor-bug-registry-runtime-quirks.md) | Vendor-bug registry & runtime quirks |
| §11.17 | [`sections/17-per-tenant-compute-accounting.md`](sections/17-per-tenant-compute-accounting.md) | Per-tenant compute accounting (Phase 20 hook, dormant by default) |
| §11.18 | [`sections/18-driver-runtime-upgrade-choreography-live-migration.md`](sections/18-driver-runtime-upgrade-choreography-live-migration.md) | Driver / runtime upgrade choreography & live migration |
| §11.19 | [`sections/19-heat-soak-long-duration-reliability.md`](sections/19-heat-soak-long-duration-reliability.md) | Heat-soak & long-duration reliability |
| §11.20 | [`sections/20-tests.md`](sections/20-tests.md) | Tests (`ai/tests/test_compute_*.py`, `ai/swarm/tests/test_gpu_arbiter.py`, `ai/swarm/tests/test_cpu_governor.py`) |
| §11.21 | [`sections/21-inference-engine-matrix-per-engine-tuning.md`](sections/21-inference-engine-matrix-per-engine-tuning.md) | Inference engine matrix & per-engine tuning |
| §11.22 | [`sections/22-continuous-batching-prefix-caching-disaggregated-prefill-decode.md`](sections/22-continuous-batching-prefix-caching-disaggregated-prefill-decode.md) | Continuous batching, prefix caching & disaggregated prefill/decode (LLM-class) |
| §11.23 | [`sections/23-cloud-spot-preemptible-cost-aware-carbon-aware-scheduling.md`](sections/23-cloud-spot-preemptible-cost-aware-carbon-aware-scheduling.md) | Cloud spot/preemptible, cost-aware & carbon-aware scheduling |
| §11.24 | [`sections/24-arm-graviton-ampere-altra-apple-silicon-cpu-baseline.md`](sections/24-arm-graviton-ampere-altra-apple-silicon-cpu-baseline.md) | ARM / Graviton / Ampere Altra / Apple Silicon CPU baseline |
| §11.25 | [`sections/25-multi-host-fabric.md`](sections/25-multi-host-fabric.md) | Multi-host fabric (NCCL / RDMA / GPUDirect — Phase 14 contract) |
| §11.26 | [`sections/26-shadow-inference-dark-launch.md`](sections/26-shadow-inference-dark-launch.md) | Shadow inference & dark-launch (binding for Phase 6 retrain promotion) |
| §11.27 | [`sections/27-idle-power-management-elastic-warm-pool.md`](sections/27-idle-power-management-elastic-warm-pool.md) | Idle power management & elastic warm-pool |
| §11.28 | [`sections/28-opentelemetry-tracing-on-demand-profiling-flamegraph-hook.md`](sections/28-opentelemetry-tracing-on-demand-profiling-flamegraph-hook.md) | OpenTelemetry tracing, on-demand profiling & flamegraph hook |
| §11.29 | [`sections/29-hot-reload-of-routing-workload-matrices.md`](sections/29-hot-reload-of-routing-workload-matrices.md) | Hot-reload of routing & workload matrices |
| §11.30 | [`sections/30-backpressure-http-semantics.md`](sections/30-backpressure-http-semantics.md) | Backpressure HTTP semantics (binding for Phase 9 API) |
| §11.31 | [`sections/31-backend-fallback-chain-engine-retirement.md`](sections/31-backend-fallback-chain-engine-retirement.md) | Backend fallback chain & engine retirement |
| §11.32 | [`sections/32-request-deadline-cancellation-propagation.md`](sections/32-request-deadline-cancellation-propagation.md) | Request-deadline & cancellation propagation (binding for Phase 9 API) |
| §11.33 | [`sections/33-adapter-hot-load-per-request-swap.md`](sections/33-adapter-hot-load-per-request-swap.md) | Adapter (LoRA / IA³) hot-load & per-request swap |
| §11.34 | [`sections/34-capacity-admission-for-new-agents-workloads.md`](sections/34-capacity-admission-for-new-agents-workloads.md) | Capacity admission for new agents & workloads |
| §11.35 | [`sections/35-hard-reservations-brownout-and-guaranteed-qos.md`](sections/35-hard-reservations-brownout-and-guaranteed-qos.md) | Hard reservations, brownout, and guaranteed QoS |
| §11.36 | [`sections/36-schema-versioning-of-compute-contracts.md`](sections/36-schema-versioning-of-compute-contracts.md) | Schema versioning of compute contracts |
| §11.37 | [`sections/37-multi-arch-image-dispatch.md`](sections/37-multi-arch-image-dispatch.md) | Multi-arch image dispatch (`linux/amd64` + `linux/arm64`) |
| §11.38 | [`sections/38-process-thread-coroutine-concurrency-invariants.md`](sections/38-process-thread-coroutine-concurrency-invariants.md) | Process / thread / coroutine concurrency invariants |
| §11.39 | [`sections/39-privacy-data-class-labels-for-autopsy-tail-capture-profiling.md`](sections/39-privacy-data-class-labels-for-autopsy-tail-capture-profiling.md) | Privacy data-class labels for autopsy / tail-capture / profiling |
| §11.40 | [`sections/40-phase-16-17-cpu-governor-binding.md`](sections/40-phase-16-17-cpu-governor-binding.md) | Phase 16 / 17 CPU governor binding (closing the cross-phase gap) |
| §11.42 | [`sections/42-cluster-arbiter-cross-host-coordination.md`](sections/42-cluster-arbiter-cross-host-coordination.md) | Cluster arbiter & cross-host coordination (Phase 14 hook) |
| §11.43 | [`sections/43-embedding-vector-inference-workload-class.md`](sections/43-embedding-vector-inference-workload-class.md) | Embedding & vector-inference workload class (Phase 21 enrichment hook) |
| §11.44 | [`sections/44-compute-side-healthz-k8s-probe-contract.md`](sections/44-compute-side-healthz-k8s-probe-contract.md) | Compute-side `/healthz` & K8s probe contract (binding for Phase 9 + Phase 14) |
| §11.45 | [`sections/45-model-weight-encryption-at-rest-secure-unseal.md`](sections/45-model-weight-encryption-at-rest-secure-unseal.md) | Model weight encryption-at-rest & secure unseal |
| §11.46 | [`sections/46-phase-11-cross-phase-coupling-matrix.md`](sections/46-phase-11-cross-phase-coupling-matrix.md) | Phase 11 cross-phase coupling matrix (closing audit) |
| §11.41 | [`sections/41-definition-of-done.md`](sections/41-definition-of-done.md) | Definition of Done (Phase 11) |

## Reading order

1. The ROADMAP §11 stub (`docs/planning/ROADMAP.md`) — goal,
   dependencies, and rollup checkbox.
2. The earliest section file relevant to the area you're modifying.
   Later sub-sections often assume earlier ones are in force; if a
   later file's `Depends on` clause names another sub-section,
   re-read it first.
3. The Definition-of-Done sub-section (the one whose title contains
   *Definition of Done* or matching `DoD` rollup) — this is the
   gate that flips the rollup checkbox in ROADMAP.
