# Phase 11.10 — Failure modes & graceful degradation (binding for Phase 12 chaos)

> Extracted from `docs/planning/ROADMAP.md` §11.10
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/nlp/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 11.10 Failure modes & graceful degradation (binding for Phase 12 chaos)

| # | Failure | Detection | Response | SLO |
|---|---|---|---|---|
| 1 | Driver crash / Xid error | NVML poll every `cfg.nvml_poll_s` (default 5 s); missing `device.json` heartbeat | Mark device `unavailable`, restart agent on CPU, alert `device.alert.v1{kind=driver_crash, severity=critical}`, dump autopsy | All requests served on CPU within 10 s |
| 2 | GPU thermal throttle (>`cfg.gpu_thermal_max_c`, default 85 °C) | NVML `temperature.gpu` | Warn at 80, halve preempt-grace above 85, refuse new GPU leases above 90, drain at 95 | Latency p95 stays within budget by demoting to CPU |
| 3 | OOM | §11.3 / vendor exception | Retry on CPU; bundle re-load blocked for `cfg.oom_cooldown_s`; persistent OOM (3+ in 5 min) → scale-down trigger | No request fails closed |
| 4 | Container missing GPU mount | §11.1 runtime guard | Fall through to CPU; alert | Visible to operator |
| 5 | NPU SDK runtime mismatch | §11.1 runtime pinning | Skip NPU tier; fall through | Visible to operator |
| 6 | GPU arbiter lease orphaned (process killed) | TTL expiry | Next request reclaims | ≤ `lease_ttl_s` |
| 7 | Compiled-artifact cache miss in prod | `cache=miss` metric > 0 after warm-up | Re-warm in background; alert if rate > threshold | Cold-start budget honoured by warmup pre-load |
| 8 | CPU oversubscription (governor reports `assigned > budget`) | §11.3 | Refuse new agent placement on host; alert | p95 latency stays within CPU budget |
| 9 | Compiled-blob signature mismatch | §11.11 | Refuse to use cache; recompile; alert `sec.alert.v1{kind=compiled_blob_tampered}` | Cache treated as cold |
| 10 | Energy / power cap exceeded (NVML `power.draw > tdp × 0.95` for 60 s) | NVML | Refuse new leases; demote `batch` priority agents | Stays within power envelope |
| 11 | ECC double-bit error | NVML `ecc.errors.uncorrected.aggregate` rising | Mark GPU `degraded`, drain, alert critical, page on-call | GPU removed from rotation in ≤ 30 s |
| 12 | `NEGELIR_DISABLE_GPU=1` panic | §11.1 | All agents drain to CPU within `compute_panic_drain_s` | ≤ 30 s drain, zero dropped requests |
| 13 | VRAM fragmentation (largest free block < required, total free ≥ required) | §11.2 placement | Refuse new placement on that GPU; schedule defrag window (drain → fresh CUDA context → re-issue leases) | No request fails closed; defrag completes within `cfg.gpu_defrag_max_window_s` |
| 14 | NaN / Inf / out-of-range PMF | §11.4 finite-check | Reject output, quarantine input, retry on CPU baseline; alert if rate > `cfg.compute_invalid_alert_rate` | Bad request observable, not silent |
| 15 | ECC retired-page count rising | NVML `ecc.errors.aggregate.retired_pages` delta | Mark device `aging`, prefer alternates in routing, alert non-critical; `degraded` at threshold | Visible to operator; smooth transition |
| 16 | Driver / runtime upgrade pending | §11.18 choreographer | Set arbiter `drain` on host, migrate or restart agents on peers, perform upgrade, re-probe, undrain | Zero in-flight loss; bounded blast radius |
| 17 | Power cap enforced (datacentre OOB) | NVML `power.limit` delta vs. last probe | Refuse new leases, demote `batch`/`training`, re-bench at new cap, update routing weights | Stays within new envelope without dropped requests |
| 18 | Clock-skew across multi-GPU host | NVML `sm_clock` variance > threshold | Lock clocks for parity workloads if allowed; otherwise quarantine the slow GPU from latency-critical routing | Tail latency stays bounded |
| 19 | Hot-swap removal of a device | §11.1 hot-plug | Drain that device, re-emit topology, remove from routing | No surfaced error |
| 20 | Inference-replay drift (re-run of a prior `prediction.v1` differs beyond tolerance) | §11.15 replay smoke | Page on-call; freeze affected bundle; trigger root-cause runbook | Detected within one nightly cycle |
| 21 | Spot / preemptible cloud GPU eviction notice | Cloud metadata-service signal (§11.23) | Set host `drain`, migrate or restart agents on peers, ack within `cfg.spot_eviction_ack_max_s` (default 25 s on AWS, 30 s on GCP) | Zero in-flight loss within the cloud's grace window |
| 22 | PCIe link degradation (Gen4 → Gen1 silent re-train) | NVML `pci.link.gen.current` < `pci.link.gen.max` | Mark device `degraded`, prefer alternates in routing, alert non-critical | Tail latency stays bounded |
| 23 | Out-of-disk on bundle / artifact cache volume | LRU eviction fails | Refuse new bundle pulls; alert; emergency LRU widens to `cfg.compute_artifact_cache_emergency_purge_pct` | No silent serving of stale bundle |
| 24 | Tokenizer / pre-processor crash mid-batch (LLM) | Sub-batch exception | Drop the offending request, continue the batch, quarantine input; never tear down the batched-decode loop | Other in-flight requests untouched |
| 25 | NCCL collective hang (multi-GPU bundle, future) | Watchdog timeout `cfg.nccl_watchdog_s` | Abort collective, drain bundle, mark device pair `degraded`, alert critical | Detected ≤ watchdog; no zombie process |
| 26 | Cloud control-plane throttling on bundle pull | S3 / GCS 503/429 burst | Exponential backoff with jitter; cap at `cfg.compute_bundle_pull_max_retries`; refuse load with `service_unavailable` instead of partial bundle | No partial / corrupt bundle ever served |

- [ ] Every row above has a chaos test landing with Phase 12. Make targets: `make chaos.gpu.pull` (driver removal), `make chaos.gpu.thermal` (NVML stub), `make chaos.gpu.oom` (synthetic), `make chaos.gpu.xid` (faked Xid), `make chaos.cpu.oversubscribe` (spawn N>budget threads), `make chaos.cache.purge`, `make chaos.compute.panic` (kill-switch), `make chaos.gpu.frag` (allocate-then-free pattern that fragments VRAM), `make chaos.gpu.ecc.retire` (NVML stub injecting retired-page deltas), `make chaos.compute.driver_upgrade` (orchestrate §11.18 drain on a synthetic host), `make chaos.compute.power_cap` (NVML `power.limit` reduction), `make chaos.compute.hotremove` (udev event simulation), `make chaos.inference.nan` (adversarial input → NaN logit).
- [ ] **Per-failure runbooks** live under `docs/reports/runbooks/compute/<failure-id>.md`; each row references its runbook.
