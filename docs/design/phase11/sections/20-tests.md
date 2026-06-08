# Phase 11.20 — Tests (`ai/tests/test_compute_*.py`, `ai/swarm/tests/test_gpu_arbiter.py`, `ai/swarm/tests/test_cpu_governor.py`)

> Extracted from `docs/planning/ROADMAP.md` §11.20
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/phase10/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 11.20 Tests (`ai/tests/test_compute_*.py`, `ai/swarm/tests/test_gpu_arbiter.py`, `ai/swarm/tests/test_cpu_governor.py`)

**Probe + selection:**
- [x] `test_device_probe_enumerates_all_backends` — every present backend appears in `device.json`; absent ones are recorded as `unavailable` with a structured `reason`. (Replaces the old "priority order" test — there is no global priority anymore; routing is per-workload, §11.13.)
- [x] `test_device_probe_subprocess_timeout` — wedged probe times out in 5 s; affected device recorded as `unavailable, reason=probe_timeout`; other backends still enumerated.
- [x] `test_device_probe_no_top_level_torch_import` — importing the probe module on a CPU-only image does not pull `torch`.
- [x] `test_device_probe_hotplug_rerun` — synthetic udev event re-runs the probe; topology delta event emitted.
- [x] `test_device_legacy_env_var_warns` — `AI_DEVICE=cuda` resolves to CUDA but emits a `cfg.deprecated` warning; both knobs land in the same effective value.
- [x] `test_device_panic_kill_switch` — `NEGELIR_DISABLE_GPU=1` drains every agent to CPU within `compute_panic_drain_s` and zero requests are dropped.
- [x] `test_device_disable_single_uuid` — `NEGELIR_DISABLE_DEVICE=<uuid>` removes one GPU; peers still serve.
- [x] `test_runtime_matrix_lint` — `requirements.txt` pins agree with `xops/compute/runtime_matrix.json`.
- [x] `test_runtime_guard_missing_gpu_mount` — CUDA selected but `/dev/nvidia*` absent → device dropped + alert.
- [x] `test_cpu_fingerprint_simd_gating` — AVX-512 wheel refuses to load on an AVX2-only fingerprint.
- [x] `test_quirks_blocked_tuple_refused` — a synthetic `(driver, runtime)` matching a `severity=block` quirk is dropped from the inventory.

**Determinism + parity:**
- [x] `test_predictor_cpu_parity_matrix` — every must-status predictor agrees with CPU within the §11.4 published tolerance across `cuda, rocm, npu` (skipped where backend absent; never xfail).
- [x] `test_predictor_cross_run_determinism` — same input, same seed, same device → byte-identical PMF.
- [x] `test_seed_propagation` — `cfg.global_seed` reaches NumPy / torch / cuRAND.
- [x] `test_npu_int8_acc_drop_within_budget` — INT8 IR's recorded `acc_drop_pct` is ≤ `cfg.npu_max_acc_drop_pct`; a synthetic over-budget IR is rejected at build.

**Arbiter + governor:**
- [x] `test_gpu_arbiter_mutual_exclusion` — concurrent humanizer + coder leases serialize.
- [x] `test_gpu_arbiter_preemption_realtime_over_batch` — sec.input lease evicts coder within grace; in-flight coder requests are drained to CPU, none dropped.
- [x] `test_gpu_arbiter_anti_flap_cooldown` — preempted agent cannot re-claim before cooldown.
- [x] `test_gpu_arbiter_orphan_lease_recovered` — killed leaseholder's slot is reclaimed within TTL.
- [x] `test_gpu_arbiter_least_loaded_placement` — on a 2-GPU host, placement picks the GPU with most free VRAM (and lowest temperature on tie).
- [x] `test_gpu_arbiter_audit_log_appends` — every lease decision lands in the audit stream.
- [x] `test_cpu_governor_thread_budget_enforced` — three predictor replicas don't collectively exceed `cores_physical`; oversubscribe attempt is refused.
- [x] `test_cpu_governor_numa_pin` — agent's threads stay on its assigned NUMA node (verified via `/proc/<pid>/status`).
- [x] `test_cpu_governor_powersave_warning` — `powersave` cpufreq emits a startup warning.

**Memory + cache:**
- [x] `test_vram_cap_rejects_oversized_bundle` — bundle over `predictor_max_vram_mb` is refused at load.
- [x] `test_oom_recovers_on_cpu` — synthetic OOM is caught, retried on CPU, and counted; cooldown blocks immediate re-load on GPU.
- [x] `test_thermal_throttle_demotes_to_cpu` — NVML stub at 92 °C blocks new GPU leases; existing leases drain by 95 °C.
- [x] `test_xid_error_marks_gpu_unavailable` — fake Xid event removes the GPU from the rotation and triggers autopsy dump.
- [x] `test_compiled_blob_cache_hit_on_warm_restart` — second startup uses cached blob; cold-start budget met.
- [x] `test_compiled_blob_cache_invalidated_on_fingerprint_change` — different `host_compute_fingerprint` recompiles.
- [x] `test_compiled_blob_hmac_tamper_refused` — flipped byte in cached blob refuses to load and alerts.
- [x] `test_no_double_residency` — same `(model_uri, dtype, device)` resolves to one handle.
- [x] `test_gpu_memory_zeroed_between_tenants` — marker pattern in evicted buffer is not visible to the next tenant.
- [x] `test_vram_leak_soak` — 10⁵ inferences leave NVML-PID VRAM within tolerance of the warm baseline.

**Security:**
- [x] `test_model_integrity_sha_mismatch_refused` — tampered bundle refuses to load.
- [x] `test_model_signature_mismatch_refused` — bundle with broken cosign signature refuses to load.
- [x] `test_compute_isolation` — `cfg.compute_class=cpu_only` containers (Phase 9 API, Phase 16 emitter, Phase 17 patcher) refuse to import any CUDA / OpenVINO symbol; build-tag enforced.
- [x] `test_gpu_container_no_egress` — outbound socket from a GPU container is refused in prod profile.

**Bench + observability:**
- [x] `test_bench_regression_gate_noise_aware` — a regression within the prior 95 % CI is **not** failed; one outside it is.
- [x] `test_bench_regression_gate_hard_floor` — a fabricated 30 % regression fails CI even when noisy.
- [x] `test_bench_clocks_locked_when_supported` — when available, GPU clocks are locked during the run.
- [x] `test_metrics_emitted_for_every_required_name` — all metric names listed in §11.9 appear in the Prometheus scrape on a smoke run.
- [x] `test_telemetry_nan_when_source_unavailable` — RAPL absent → `negelir_compute_energy_joules_*` is `NaN` with `reason=rapl_unavailable`, not `0`.

**Router + LLM serving + hot-swap:**
- [x] `test_router_concurrent_devices` — predictor on CPU + classifier on NPU + humanizer on dGPU serve in parallel from one agent process.
- [x] `test_router_admission_rejects_when_saturated` — saturated devices return `service_busy` with `Retry-After`; no silent queueing.
- [x] `test_router_sticky_session` — same session keeps device until SLO-bound break.
- [x] `test_router_decision_audited` — non-trivial route emits `route.decision.v1` (sampled).
- [x] `test_llm_cuda_graph_bucket_cache_capped` — variable-length traffic does not exceed `cuda_graph_bucket_max`; older buckets evicted LRU.
- [x] `test_llm_kv_cache_no_evict_mid_decode` — pressure cannot evict an in-progress decode; eviction targets idle sessions.
- [x] `test_llm_streaming_cancel` — client disconnect cancels decode within `llm_cancel_grace_ms`.
- [x] `test_llm_sampler_replay` — same `(input, sampler_tuple, provenance)` reproduces the same tokens.
- [x] `test_bundle_lazy_load_verifies_signature` — bundle pulled from object store with broken signature is quarantined; load refused.
- [x] `test_bundle_hot_swap_zero_drop` — concurrent inference stream during `v→v+1` swap shows zero failed requests; predictions are correctly tagged with their bundle SHA.
- [x] `test_bundle_rollback_within_window` — explicit rollback restores `v` cleanly.
- [x] `test_inference_replay_byte_equal` — replay of a stored `prediction.v1` on a matching-fingerprint host is byte-equal (predictors) / token-equal (LLMs with sampler tuple).

**Quirks + tenant accounting + driver upgrade:**
- [x] `test_quirk_workaround_applied` — a `severity=warn` quirk is detected and the documented workaround is applied at probe time.
- [x] `test_quirk_entry_requires_regression_test` — lint refuses a quirk entry without an `ai/tests/quirks/test_*.py` companion.
- [x] `test_tenant_quota_dormant_logs_only` — `cfg.tenant_quota_enabled=false`: counters increment, decisions log "would-deny" but never block.
- [x] `test_tenant_quota_active_blocks_over` — flipped on: over-quota request returns `quota_exceeded`.
- [x] `test_tenant_fairness_no_starvation` — N concurrent tenants share GPU time per weights; min-share never falls below `weight_min_pct`.
- [x] `test_driver_upgrade_drain_no_loss` — synthetic upgrade on host A: in-flight requests migrate / restart on peers; zero dropped.
- [x] `test_driver_upgrade_canary_halts_on_regression` — synthetic post-upgrade bench regression > hard floor halts the rollout and re-quarantines the host.

**Soak + heat-cycle:**
- [x] `test_soak_short_smoke` — 10-minute soak smoke runs in CI; full 24 h soak runs on the self-hosted runner nightly with results posted.
- [x] `test_soak_thermal_no_oscillation` — 2 h thermal-ramp shows clock state machine converges within `soak_clock_oscillation_max_per_min`.

**Proof tests (the "missing-proofs" inventory called out in the user directive):**
- [x] `proof_tf32_disabled_for_predictors` — Ampere host: enabling TF32 globally then running the predictor PMF parity suite **fails**; with the §11.4 explicit-disable, it **passes**. Both directions are asserted so a future commit re-enabling TF32 cannot pass.
- [x] `proof_ftz_daz_explicit` — denormals path: with FTZ/DAZ off the denormal-rich input path produces output X; with the §11.3 explicit FTZ/DAZ on it produces output Y; the gap is documented and the chosen mode is what runs.
- [x] `proof_no_fork_after_cuda` — a worker spawned via `fork()` after CUDA init raises; `spawn` works.
- [x] `proof_vram_fragmentation_refused` — synthetic alloc-free pattern fragments VRAM; arbiter refuses placement that would only fit on paper, schedules defrag, then succeeds.
- [x] `proof_nan_inf_quarantined_and_retried` — adversarial input drives a kernel to NaN; the finite-check rejects, the input is quarantined, the request retries on CPU and succeeds.
- [x] `proof_pcie_topology_locality` — multi-GPU bundle co-locates on NVLink-linked pair when present.
- [x] `proof_compute_provenance_round_trip` — every `prediction.v1` carries a complete provenance block; replay tool succeeds end-to-end on a matching host.
- [x] `proof_concurrent_multi_accel` — Meteor-Lake-class CI host runs predictor on CPU + classifier on NPU + humanizer on iGPU concurrently; all three devices show non-zero utilisation in the same scrape window.
- [x] `proof_zero_dropped_under_kill_switch` — synthetic load (R req/s, p95 < SLO) sustained while `NEGELIR_DISABLE_GPU=1` is asserted: drain completes within `compute_panic_drain_s`; **zero** requests fail closed; p95 stays inside the CPU-only SLO.
- [x] `proof_zero_dropped_under_hot_swap` — same load shape during a `v→v+1` hot-swap: zero failed requests; bundle SHAs on emitted predictions transition cleanly at the swap point.
- [x] `proof_no_cross_tenant_vram_leak` — marker pattern test (extends `test_gpu_memory_zeroed_between_tenants`) plus statistical sweep over many evictions with random markers; never observed on the next tenant.
- [x] `proof_clock_skew_tail_bounded` — induced clock skew across multi-GPU host: tail latency stays within budget thanks to routing demotion of the slow GPU.
- [x] `proof_image_signing_admission` — unsigned image is refused by the prod compose / K8s admission webhook; signed image is admitted.
- [x] `proof_compute_isolation_runtime_and_static` — Phase 9 / 16 / 17 binaries cannot import any GPU/NPU SDK at runtime **and** their image manifests show no GPU runtime layers.
- [x] `proof_warmup_corpus_pinned` — the warm-up corpus `ai/tests/fixtures/warmup/` is content-addressed; its SHA appears in the bundle audit; a tampered corpus refuses to warm.

**Engine, batching, cloud, ARM, fabric, shadow, idle, OTel, hot-reload, backpressure (§11.21–§11.30):**
- [x] `proof_engine_determinism_lint` — a predictor declared with an engine whose `deterministic_when` does not cover its parity tolerance is refused at PR time by `xops/lint/predictor_engine_determinism.py`.
- [x] `proof_engine_cache_invalidates_on_allocator_conf` — flipping `PYTORCH_CUDA_ALLOC_CONF` changes the cache key; engine recompiles; old artifact remains in cache LRU.
- [x] `proof_continuous_batch_admits_midstream` — under sustained LLM load, a request arriving mid-decode joins the in-flight batch within `cfg.llm_batch_admit_p95_ms`; static-batch baseline is reported alongside for delta visibility.
- [x] `proof_prefix_cache_hit_rate` — synthetic shared-prompt corpus drives prefix-cache hit-rate above `cfg.llm_prefix_cache_warm_threshold`; the tightened cold-start budget is met.
- [x] `proof_chunked_prefill_tail_bounded` — bursty 8 k-token prompts arriving alongside small-batch traffic do not push small-batch p99 above SLO.
- [x] `proof_continuous_batch_cancel_no_peer_flush` — cancelling one in-flight request inside a continuous batch does not invalidate peers' KV-cache.
- [x] `proof_spot_eviction_drain_within_grace` — synthetic spot-eviction signal triggers §11.18 drain; ack lands within `cfg.spot_eviction_ack_max_s`; zero in-flight loss.
- [x] `proof_cost_table_tiebreaks_router` — two equally-suitable devices, distinct cost: router prefers cheaper at equal latency-headroom; the decision rationale is in the audit.
- [x] `proof_carbon_window_defers_training_only` — a training job inside a high-carbon window is deferred; a realtime request in the same window is served immediately.
- [x] `proof_arm64_predictor_parity` — predictor PMF parity (§11.4 tolerance) holds between an x86_64 and an aarch64 host on every must-status predictor.
- [x] `proof_arm_simd_baseline_alert` — a Neoverse-N1 host (no SVE) emits the documented `arm_simd_baseline` alert and selects the NEON wheel — never the SVE wheel.
- [x] `proof_nccl_set_lease_atomic` — synthetic two-GPU bundle: the arbiter either grants both GPUs or refuses entirely; partial acquisition is impossible.
- [x] `proof_shadow_diff_blocks_bad_promotion` — a deliberately-perturbed shadow bundle fails the §11.26 promotion gate; promotion is refused; on-call alert fires.
- [x] `proof_shadow_traffic_bounded` — shadow traffic never exceeds `cfg.shadow_traffic_pct` of live, even under burst.
- [x] `proof_idle_power_cap_applied_and_restored` — an idle GPU drops to `gpu_idle_power_limit_w`; first lease restores the default cap before serving; wake-cost is included in the first request's latency budget.
- [x] `proof_warm_pool_membership_reacts_to_demand` — synthetic shifting demand reshuffles the warm-pool; membership transitions respect `min_hold_ms` (no flapping).
- [x] `proof_coldstart_storm_jittered` — a synthetic 100-pod restart does not exceed `cfg.compute_bundle_concurrent_pulls_max` against the bundle store.
- [x] `proof_otel_inference_span_complete` — every served inference produces an `compute.inference` span with the documented attributes; missing attribute fails the test.
- [x] `proof_tail_capture_token_bucketed` — sustained tail-latency events emit ≤ `cfg.compute_tail_capture_per_min` captures; never a thundering herd.
- [x] `proof_router_matrix_hot_reload_atomic` — corrupt `workload_matrix.json` is refused; prior matrix continues to serve; alert fires.
- [x] `proof_backpressure_status_matrix` — each row of the §11.30 status matrix is exercised end-to-end and the exact `(status, Retry-After, X-Compute-Reason)` triple is asserted; lint refuses an ad-hoc `X-Compute-Reason`.
- [x] `proof_sbom_runtime_verify` — a container started from an image whose layer digests don't match its build-manifest SBOM exits with `sec.alert.v1{kind=sbom_mismatch}` before serving.
- [x] `proof_pcie_link_degradation_demoted` — NVML stub reports `pci.link.gen.current=1` on a Gen4-capable GPU; routing demotes that device, alert fires, no request fails closed.
- [x] `proof_disk_full_on_artifact_cache_refuses_load` — synthetic ENOSPC on the artifact-cache volume refuses new bundle loads with a structured error; never serves stale.
- [x] `proof_tokenizer_crash_does_not_tear_batch` — a malformed input that crashes the tokenizer is dropped + quarantined; peers in the same continuous batch finish normally.
- [x] `proof_deadline_admission_refuses_unreachable` — request with `remaining_ms < expected_wait + p95_compute` is refused with `504` + `X-Compute-Reason: deadline_unreachable` *before* GPU work starts.
- [x] `proof_deadline_inflight_cancel_no_peer_impact` — request whose deadline expires mid-decode is cancelled within `llm_cancel_grace_ms`; KV-cache reclaimed; peers in the same continuous batch are byte-identical to a control run with no expiry.
- [x] `proof_short_deadline_does_not_jump_queue` — a 50-ms-deadline request arriving behind a 5-s-deadline request does not preempt; admission decides, priority does not flip.
- [x] `proof_adapter_swap_atomic` — concurrent requests for adapters A and B share the resident base; per-sequence tokens never reflect a half-merged adapter.
- [x] `proof_adapter_cache_lru_evicts_oldest` — `compute_adapter_cache_max_count + 1` distinct adapters evict the LRU entry, not a hot one.
- [x] `proof_adapter_provenance_includes_both_shas` — `prediction.v1.compute_provenance` carries `base_sha256` and `adapter_sha256`; replay reproduces.
- [x] `proof_capacity_preflight_refuses_overcommit` — adding a fourth replica that would exceed `vram + ctx_overhead` returns a structured refusal with `alternates`; no half-started agent.
- [x] `proof_capacity_preflight_reservation_expires` — unredeemed reservation frees the slot at `cfg.compute_preflight_reservation_ttl_s + 1 s`.
- [x] `proof_reservation_floor_honoured_under_burst` — sustained `batch` burst cannot drive `realtime` below its declared floor; weighted-fair-share alone fails this test, reservations pass it.
- [x] `proof_brownout_shed_batch_preserves_realtime` — `shed_batch` mode under load: `realtime` SLO held; `batch` returns `503 X-Compute-Reason: brownout_shed_batch`.
- [x] `proof_schema_version_unknown_major_refused` — `workload_matrix.json` with `schema_version: 99.0` is refused at load; prior matrix continues to serve; alert fires.
- [x] `proof_schema_migration_minor_applies` — `device.json` written at `1.2` is read by a loader at `1.5` via the migration chain without operator action.
- [x] `proof_schema_lint_blocks_silent_mutation` — a PR that changes `engines.json` keys without bumping `schema_version` or adding a migration is refused by `xops/lint/compute_schema_versions.py`.
- [x] `proof_arch_mismatch_refused_before_import` — an `amd64` image started on `arm64` exits with `arch_mismatch` *before* any `torch`/`numpy` import attempt (no segfault).
- [x] `proof_arbiter_concurrent_calls` — 1000 concurrent coroutine + thread arbiter calls produce no double-grant, no lost release.
- [x] `proof_router_p99_overhead_bounded` — router score loop p99 ≤ `cfg.compute_router_p99_overhead_us` under synthetic 10 k-rps mix; regression gated.
- [x] `proof_no_fork_after_any_gpu_import` — fork after `import openvino` / `import xgboost` (with GPU build) raises like CUDA does.
- [x] `proof_capture_class_mismatch_refused` — a `pii`-class request whose tail-capture is misrouted to the default sink refuses to write and emits `capture_class_mismatch`.
- [x] `proof_capture_class_public_captured_verbatim` — a `public`-class request's tail capture includes the input verbatim (debuggability is preserved by the class system).
- [x] `proof_ctx_overhead_in_placement` — placing N processes on a GPU with `(vram_total − N × ctx_overhead) < required` is refused, even though `vram_free ≥ required` reads green.
- [x] `proof_psu_envelope_refused` — concurrent placement that would exceed `host_psu_capacity_w × cfg.host_psu_safety_factor` is refused with `host_psu_envelope`; counter increments.
- [x] `proof_clock_step_alert_emitted` — synthetic NTP step > `cfg.clock_step_alert_ms` emits `clock_step` alert; no histogram bucket goes negative.
- [x] `proof_host_class_replay_invariance` — same `prediction.v1` replays byte-equal across two distinct hosts that share the same `host_class` (different `host_compute_fingerprint`).
- [x] `proof_emitter_patcher_thread_budget` — Phase 16 emitter and Phase 17 patcher each respect their `cfg.<component>_thread_budget`; over-spawn is refused by the §11.3 governor.

**Backend fallback chain (§11.31):**
- [x] `proof_fallback_chain_walks_to_cpu_baseline` — synthetic `engine.error.v1` from the preferred engine routes the request to the next engine, then to CPU baseline if the second also fails; the request **succeeds** and `compute_provenance.fallback_path` records every step.
- [x] `proof_fallback_chain_bounded_by_deadline` — chain walk is cut off when `compute_fallback_max_wall_ms` is reached; request returns the documented `(503, X-Compute-Reason: fallback_exhausted)` triple.
- [x] `proof_engine_quarantine_after_threshold` — N synthetic `engine.error.v1` events on the same `(engine, device)` pair within the window quarantine that pair; the next request skips it without trying.
- [x] `proof_engine_quarantine_per_host` — quarantine on host A does not pre-emptively quarantine host B with the same `host_class` until the §11.42 cluster signal fires.
- [x] `proof_engine_quarantine_re_quarantine_backoff` — re-quarantine within the grace doubles the cooldown; tested up to the 24 h cap.
- [x] `proof_fallback_predictor_parity_preserved` — every engine in a predictor's chain meets the §11.4 published tolerance vs. CPU; lint blocks a PR that violates this.
- [x] `proof_fallback_no_silent_output_shape_change` — an engine missing a required output head is refused at admission, not at runtime.
- [x] `proof_fallback_audit_complete` — every walk emits `compute.fallback.v1` with the full `chain` and `terminal_step`; missing field fails the test.
- [x] `proof_engine_cache_invalidates_on_cudnn_minor_bump` — a cuDNN minor version bump produces a different engine cache key; the prior cached engine remains in LRU but is not re-used; recompile happens.
- [x] `proof_engine_cache_hmac_includes_host_class` — same engine bytes on a different `host_class` are refused; the HMAC tag binds the host envelope.

**Cluster arbiter (§11.42):**
- [x] `proof_cluster_brownout_fans_out` — operator engages brownout once on the cluster arbiter; every per-host arbiter applies §11.35 within `compute_cluster_brownout_propagation_s`; histogram populated.
- [x] `proof_cluster_arbiter_unreachable_local_authority` — partitioned cluster service: hosts continue serving under last-cached state; alert fires; data path never blocks on the cluster service.
- [x] `proof_cluster_bundle_pull_lease_caps_concurrency` — synthetic 100-pod redeploy: cluster lease caps fleet-wide concurrent pulls of the same SHA at `compute_bundle_cluster_pull_max_concurrent`; no extra 503s from the bundle store.
- [x] `proof_cluster_engine_quarantine_skips_matching_hosts` — `cluster.engine_quarantine` for a `host_class` causes every matching host to skip that engine; non-matching hosts unaffected.
- [x] `proof_cluster_region_drain_no_dropped_requests` — synthetic region drain: in-flight requests migrate to peers; zero failed requests within the cloud's grace window.
- [x] `proof_cluster_arbiter_split_brain_refuses_writes` — induced split-brain: minority partition refuses writes with `cluster_split_brain` alert; per-host arbiters fall back gracefully.
- [x] `proof_cluster_decision_idempotent_under_fencing_token` — replayed cluster command with stale fencing token is refused; with current token is a no-op (idempotent).

**Embedding & vector inference (§11.43):**
- [x] `proof_embedding_no_kv_alloc` — embedding agent's bundle declares `kv_cache_required=false`; loader allocates zero KV-cache bytes.
- [x] `proof_embedding_online_batches_to_max` — synthetic 32-rps stream coalesces into batches up to `embedding_online_batch_max` within `embedding_online_batch_max_wait_ms`; smaller bypasses the wait.
- [x] `proof_embedding_offline_yields_to_realtime` — `embedding_offline` job in flight: arriving `realtime` request preempts within §11.2 grace; offline resumes after.
- [x] `proof_embedding_replay_cosine_within_threshold` — replay of a stored embedding emits a vector with cosine ≥ `embedding_replay_cos_min` to the original.
- [x] `proof_embedding_router_does_not_mis_batch_with_pmf` — concurrent `predictor_micro` PMF stream + `embedding_online` stream: the batcher keeps them in distinct batches; PMF p99 is unchanged vs. PMF-only baseline.

**Compute `/healthz` (§11.44):**
- [x] `proof_readyz_false_until_warmup_inference` — pod started with bundle pulled but warmup inference not yet executed: `/readyz` returns `false` with `kind=warmup_pending`; flips to `true` after the warmup completes.
- [x] `proof_readyz_false_during_drain` — agent in §11.18 drain returns `/readyz=false` with `kind=drain` *before* refusing requests; K8s removes from endpoints; in-flight requests finish.
- [x] `proof_readyz_no_secrets_in_response` — probe response JSON contains no inputs / outputs / tokens / tenant IDs; lint refuses an extension that adds a sensitive field.
- [x] `proof_startupz_distinct_from_livez` — long bundle pull keeps `/startupz=false` for `> liveness_initial_delay`; `/livez` stays `true` so K8s does not restart the pod.
- [x] `proof_readyz_respects_cluster_drain` — `cluster.region_drain` fired: every agent in the region returns `/readyz=false` within `compute_cluster_brownout_propagation_s`.
- [x] `proof_readyz_chaos_simulator_covers_all_kinds` — `make compute.probe.simulate KIND=*` exercises every documented `not_ready` reason and asserts JSON shape.

**Weight encryption-at-rest (§11.45):**
- [x] `proof_no_plaintext_bundle_on_disk` — restricted bundle: cache directory snapshot during steady-state serving contains zero plaintext weight bytes; `tmpfs` unseal file is `unlink`'d before first inference.
- [x] `proof_swap_enabled_refuses_restricted_load` — host swap on + `compute_bundle_unseal_require_no_swap=true`: agent refuses to start; `/readyz` reason `kind=swap_violates_restricted_unseal`.
- [x] `proof_kek_rotation_no_rebuild` — `make compute.kek.rotate`: every restricted bundle is re-wrapped under the new KEK without a bundle rebuild; old caches re-fetch on next load; serving uninterrupted.
- [x] `proof_autopsy_redacts_restricted_weights` — synthetic Xid on a restricted-bundle agent: autopsy contains metadata only; no `mmap`'d weight pages dumped.
- [x] `proof_unseal_audit_emitted` — every `bundle_unseal` event emits `sec.audit.v1` with documented fields; missing field fails the test.

**Cross-phase regression (§11.46):**
- [x] `proof_phase11_coupling_table_complete` — lint reads `xops/lint/phase11_couplings.py` and refuses a PR that touches a referenced sub-section without updating the §11.46 table.
