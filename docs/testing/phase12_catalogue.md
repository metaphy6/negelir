# Phase 12 — Adversarial & Chaos Catalogue (cross-phase single-source registry)

> **Status:** Stub registry. This file is the **single source of
> truth** for every chaos / adversarial stub in the system, per
> [`../design/phase12/sections/05-chaos-catalogue-single-source-registry.md`](../design/phase12/sections/05-chaos-catalogue-single-source-registry.md)
> (§12.5). It was seeded from Phase 7 stubs and is being promoted to
> the cross-phase registry: sister phases register a stable ID + a
> property + the owning agent *as they design the resilience surface*;
> Phase 12 fills in the body (the proof test) *as it hardens*. Bodies
> marked `TBD — implementation pending Phase 12` are unimplemented
> stubs.
>
> **ID scheme (§12.5.1).** `P12-<phase>-<seq>`. IDs are **append-only**:
> once allocated, never re-numbered (test names reference them) and
> never re-used after retirement. The owning phase is encoded in the
> ID. Historical note: `P12-8-AM … P12-8-AT` describe **NLP** surfaces
> (owning phase 10, §10.27/§10.28); they keep their 8-prefixed IDs for
> stability but their `owning_phase` is 10.
>
> **Target naming (§12.0 A2, §12.5.1).** The **canonical** make-target
> form is **dot-style** (`chaos.redis-flap`). The hyphen forms
> (`chaos-fill-dlq`) in the §8 maint rows below are historical aliases:
> `chaos-<x> ≡ chaos.<x>`. The full mechanical normalisation of every
> row to dot-style lands with the implementation PR that wires the
> `make chaos.*` targets (tracked by §12.5.4) — IDs are unchanged by
> that rename.
>
> **Lifecycle (§12.5.3).** `status ∈ {stub, implemented, retired}`. A
> stub does not count toward the §12.17 rollup until its owning phase
> ships; a shipped phase may not go green while it has a `stub` row for
> a surface it has already shipped (§12.5.5).

The IDs are stable (Phase 12 fuzzers reference them in their
test names) and match the `kind` enum in `KNOWN_SEC_ALERT_KINDS`
(`ai/swarm/agents/payloads.py`) wherever the property fires the
matching `sec.alert.v1` envelope.

> **Cross-phase coverage at a glance.** The §7/§8/§10 families are
> rowed in full below. The remaining families (Phase 5 / 9 / 11 / 13 /
> 16) are indexed at the end of this file under
> [Cross-phase families (indexed)](#cross-phase-families-indexed), each
> citing the owning design section that authored the `chaos.*`
> reference, so this catalogue is the complete single source §12.5
> requires.

---

## §7.1 — `sec.input.v1` (QA prompt-injection / homoglyph defense)

| ID | Property | Body |
|----|----------|------|
| P12-7.1-A | Length cap is enforced in **bytes**, not codepoints — a 4-byte UTF-8 grapheme cannot bypass the cap by being counted as one char. | TBD — implementation pending Phase 12 |
| P12-7.1-B | NFC + control-strip + RTL/zero-width strip is **idempotent**: running `sec_steps_run=["nfc","strip_control","strip_rtl"]` twice produces the same `sanitized_text`. | TBD — implementation pending Phase 12 |
| P12-7.1-C | Homoglyph fold maps ASCII-confusable Cyrillic / Greek runs to ASCII before the classifier sees them — `"раy раl"` (Cyrillic а) and `"pay pal"` produce the same classifier input. | TBD — implementation pending Phase 12 |
| P12-7.1-D | Classifier circuit-breaker opens after `cfg.sec_input_breaker_open_s` of consecutive timeouts and falls back to deterministic-rule verdict (`pass` or `quarantine`, never silent drop). | TBD — implementation pending Phase 12 |
| P12-7.1-E | Quarantine producer sheds load: when `cfg.sec_quarantine_producer_queue_max` is exceeded, the agent emits a `sec.alert.v1` (`kind=quarantine_backpressure_shed`) instead of growing memory unbounded. | TBD — implementation pending Phase 12 |
| P12-7.1-F | `qa.request.v1` dedup window: NLP receives at most one envelope per `request_id` over `cfg.qa_request_v1_dedup_window_s` even when both producers (gateway + sec.input.v1 post-classifier `pass`) emit. | TBD — implementation pending Phase 12 |
| P12-7.1-G | Right-to-erasure: setting `quarantine_samples.erased_at` MUST replace `raw_bytes` with the 1-byte tombstone (migration 007 invariant). The `pii_redacted=true` producer flag is **independent** — it does not imply `erased_at`. | TBD — implementation pending Phase 12 |

## §7.2 — `sec.scrape.v1` (HTML / DOM anomaly defense)

| ID | Property | Body |
|----|----------|------|
| P12-7.2-A | Streaming statistics (Welford + P²) are numerically stable: a sequence of 10⁶ samples produces the same mean / variance as the offline NumPy computation to ≤ 1e-9 relative error. | TBD — implementation pending Phase 12 |
| P12-7.2-B | Warmup gate is honoured: `sample_count < cfg.sec_scrape_warmup_samples` cannot trip a `size_delta_pct` alert — eliminates false positives on cold start. | TBD — implementation pending Phase 12 |
| P12-7.2-C | Compression-bomb detector trips when `inflated_bytes / wire_bytes > cfg.sec_scrape_inflate_ratio_max` BEFORE the inflate buffer reaches `cfg.sec_quarantine_payload_max_bytes` — backpressure must precede memory pressure. | TBD — implementation pending Phase 12 |
| P12-7.2-D | SimHash distance over the DOM skeleton (tag + class only, content stripped) detects a fixture-page swap to a different upstream layout at distance ≥ `cfg.sec_scrape_simhash_max_distance` (12 bits ≈ structural rewrite). | TBD — implementation pending Phase 12 |
| P12-7.2-E | DOM node cap (`cfg.sec_scrape_dom_fingerprint_max_nodes`) bounds parser memory: a malicious 10⁵-deep nested HTML cannot exhaust the heap; the agent emits `sec.alert.v1` (`kind=scrape_dom_overflow`) and quarantines. | TBD — implementation pending Phase 12 |
| P12-7.2-F | Fingerprint persistence (migration 008): the `last_flush_at` watchdog catches a stalled flush within `2 × sec_scrape_baseline_flush_s` and fires `kind=scrape_fingerprint_stale`. | TBD — implementation pending Phase 12 |
| P12-7.2-G | `sec.scrape.v1` is a single-instance agent (will be added to `bootstrap.SINGLE_INSTANCE_AGENTS` when the agent ships): the §7.5 single-writer invariant on `source_fingerprints` rows is held. | TBD — implementation pending Phase 12 |

## §7.3 — `sec.rate.v1` (rate-limit / burst / denylist)

| ID | Property | Body |
|----|----------|------|
| P12-7.3-A | Pre-auth caps protect `/v1/auth/*` against credential stuffing: `cfg.sec_rate_pre_auth_capacity` tokens / `cfg.sec_rate_pre_auth_refill_per_s` cap a single subject at < 30 attempts/min on cold start. | TBD — implementation pending Phase 12 |
| P12-7.3-B | IPv6 prefix bucketing (`cfg.sec_rate_ipv6_prefix=64`) prevents a single end-site allocation (2⁶⁴ addresses) from spraying unique buckets. The shape of `subject` is opaque — bucketing is a Redis-key concern, not a payload concern. | TBD — implementation pending Phase 12 |
| P12-7.3-C | Trusted-proxy header trust: `cfg.sec_rate_trusted_proxies` empty ⇒ headers ignored; only when the immediate-peer IP is inside a configured CIDR may `X-Forwarded-For` override the bucket key. Spoofed `X-Forwarded-For` from an untrusted peer is rejected. | TBD — implementation pending Phase 12 |
| P12-7.3-D | Bucket-store cap (`cfg.sec_rate_max_subjects`) plus idle-TTL eviction (`cfg.sec_rate_bucket_idle_ttl_s`) bounds memory; eviction-rate monitor (`cfg.sec_rate_eviction_rate_alert_per_s` over `cfg.sec_rate_eviction_rate_window_s`) emits `kind=rate_eviction_spike` when capacity is being thrashed. | TBD — implementation pending Phase 12 |
| P12-7.3-E | Burst detector uses `time.monotonic()`-based windows (immune to wall-clock skew per the M2 audit). A single subject sustaining > `cfg.sec_burst_threshold` requests in `cfg.sec_burst_window_ms` triggers `kind=rate_burst` alert. | TBD — implementation pending Phase 12 |
| P12-7.3-F | Denylist is the SOLE control-plane: `sec.rate.v1` is the only producer of `sec.denylist.v1`; the gateway cache and Redis hash converge within ≤ 1 bus tick. Manual ops-console adds also flow through the topic (no out-of-band Redis writes). | TBD — implementation pending Phase 12 |
| P12-7.3-G | Denylist TTL escalation: repeated trips within `cfg.sec_denylist_ttl_s` extend the entry by `× cfg.sec_denylist_escalation_factor` (capped). `cfg.sec_denylist_max_entries` bounds Redis memory. | TBD — implementation pending Phase 12 |
| P12-7.3-H | Redis-timeout fail-open: if Redis is unreachable for > `cfg.sec_rate_redis_timeout_ms`, the limiter drops to per-process secondary buckets (`cfg.sec_rate_secondary_capacity`) and emits `kind=rate_redis_unreachable` (severity `error`). The system never silently bypasses rate-limits. | TBD — implementation pending Phase 12 |

## §7.4 — `sec.alert.v1` envelope properties

| ID | Property | Body |
|----|----------|------|
| P12-7.4-A | `kind` open-enum invariant: producers emit only `KNOWN_SEC_ALERT_KINDS`; consumers tolerate unknown kinds (asserted by `test_phase7_open_enum.py::test_consumer_accepts_unknown_sec_alert_kind_round_trip`). | Foundation: `ai/swarm/agents/tests/test_phase7_open_enum.py` |
| P12-7.4-B | `evidence_ref` is content-addressed (sha256), never inlined bytes — alerts cannot become a log-injection or cardinality vector. The join `sec.alert.v1.evidence_ref → sec.quarantine.v1.bytes_sha256` is the only retrieval path. | TBD — implementation pending Phase 12 |
| P12-7.4-C | Generalized debounce (`cfg.sec_alert_debounce_ttl_s`) suppresses storm of identical (kind, subject) tuples; `cfg.sec_alert_critical_debounce_enabled=false` keeps `severity=critical` fast-path on by default. | TBD — implementation pending Phase 12 |
| P12-7.4-D | `reason` is capped at 1024 chars by producers (mirrors `proof.flag.detail` cap from the M-audit); large evidence goes in `evidence_ref`. | Schema-enforced: `sec.alert.v1.json` `reason.maxLength: 1024` |

---

## §8 — Maint-plane chaos scenarios (§8.2 / §8.3 / §8.5 / §8.7 / §8.8)

> Surfaces owned by Phase 8; assertions owned by Phase 12. Stub IDs are stable and
> referenced by `make chaos-*` target names.

| ID | Chaos target | Property | Body |
|----|-------------|----------|------|
| P12-8-A | `chaos-fill-dlq` | Fill `predict.vote.dlq` to `N=5000`; §8.5 DLQ supervisor drains within `cfg.maint_dlq_drain_window_ms` OR fires `sec.alert.v1{kind=dlq_escalated, severity=error}`; in-memory state map does not grow beyond `cfg.maint_dlq_state_max`. | TBD — implementation pending Phase 12 |
| P12-8-B | `chaos-flap-replicas` | Rapid replica flaps on `AGENT=consensus.v1`; §8.2 scaler hysteresis ensures no back-to-back `scale_decision` events within `cfg.maint_scaler_min_decision_interval_s`; `scale_throttled` events emitted instead. | TBD — implementation pending Phase 12 |
| P12-8-C | `chaos-corrupt-dump` | Corrupt the `pg_dump` TOC mid-write; §8.3 agent detects via checksum mismatch on next cron tick, renames dump dir to `<date>.failed/`, does NOT skip the day, and `maint_backup_age_hours` gauge continues to report from last verified dump. | TBD — implementation pending Phase 12 |
| P12-8-D | `chaos-disk-pressure-backup` | Reduce free disk below `max(2× last_dump_bytes, cfg.maint_backup_min_free_gb)`; backup refuses to start and emits `kind=backup_disk_pressure`; no partial dump is written. | TBD — implementation pending Phase 12 |
| P12-8-E | `chaos-stale-vram-probes` | Force all VRAM telemetry probes past their freshness TTL; §8.2 scaler refuses scale-up with `reason=vram_telemetry_stale`; CPU-only path bypasses VRAM checks and proceeds normally (three-scenario triangle). | TBD — implementation pending Phase 12 |
| P12-8-F | `chaos-poison-quarantine-dlq` | Inject poisoned payloads into `sec.quarantine.v1.dlq`; auto-replay path must reject the topic entirely (in `cfg.maint_dlq_replay_excluded_topics` allow-list); only operator-invoked `--confirm-pii` path may replay; no `qa.request.v1` emission without explicit PII consent. | TBD — implementation pending Phase 12 |
| P12-8-G | `chaos-bus-partition-opsctl` | Partition bus during `ops.denylist-clear` publish round-trip; opsctl spools the envelope and retries on reconnect; spool drains in arrival order; `severity=critical` alert during outage either succeeds on retry or triggers `maint_self_isolated` — never silently lost. | TBD — implementation pending Phase 12 |
| P12-8-H | `chaos-leader-split-brain` | Block `coordination.k8s.io/v1` API with 503 during scaler operation; losing pod transitions to observer within `lease_duration + 5s` BEFORE any publish attempt; on API restore exactly one leader resumes; no duplicate `scale_decision` for the overlap window. | TBD — implementation pending Phase 12 |
| P12-8-I | `chaos-maint-plane-lag` | Inject 6s consumer lag on `maint.event.v1` → tier-1 shedding + exactly 1 alert; ramp to 70s → tier-3 observer-mode + exactly 1 alert; clear → exactly 1 recovery event; at most 1 event per tier transition (no per-tick re-emission). | TBD — implementation pending Phase 12 |
| P12-8-J | `chaos-bus-circuit-breaker` | Kill bus during scaler emit; 3 consecutive failures flip the agent to `bus_degraded`; subsequent emits land in `data/maint/agent_spool/maint.scaler.v1/`; on bus restore spool drains in arrival order; `severity=critical` alert is never silently spooled. | TBD — implementation pending Phase 12 |
| P12-8-K | `chaos-pvc-mid-restore-verify` | Kill §8.3 backup agent mid `pg_restore` (`kill -9`); on next agent boot orphaned K8s Job + ephemeral PVC under `negelir-maint-verify` are deleted within `cfg.maint_backup_verify_orphan_ttl_h`; `kind=backup_verify_orphan_swept` is published exactly once. | TBD — implementation pending Phase 12 |
| P12-8-L | `chaos-clock-step-back` | Restart §8.2 scaler mid decision-window; post-restart `pod_instance_id` differs from pre-restart; post-restart `scale_decision` events do not collide with pre-restart ledger entries on `(agent, decision_window_id)`; no double-publish on the bus. | TBD — implementation pending Phase 12 |
| P12-8-M | `chaos-offsite-target-down` | Take the offsite backup target offline during an active transfer; §8.3 agent retries up to `cfg.maint_backup_offsite_retry_max`, emits `kind=backup_offsite_unreachable`, and marks the job `status=offsite_failed` without corrupting the local verified dump. | TBD — implementation pending Phase 12 |
| P12-8-N | `chaos-bit-rot-old-dump` | Flip a bit in the most recent backup archive after fsync; §8.3 agent detects via pre-restore checksum verification; `maint_backup_age_hours` gauge reports age from the last **verified** dump, not the bit-rotten file; `kind=backup_checksum_mismatch` alert fires. | TBD — implementation pending Phase 12 |
| P12-8-O | `chaos-pg-conn-pool-starve` | Exhaust the PG connection pool (set `max_connections=1` via config); §8.3 backup agent queues until `cfg.maint_backup_pg_acquire_timeout_ms` then emits `kind=backup_pg_pool_starved` and exits without a partial dump; next cron tick retries cleanly. | TBD — implementation pending Phase 12 |
| P12-8-P | `chaos-model-lineage-missing` | Remove all lineage sidecars from `data/models/`; §8.3 backup agent detects no `*.lineage.json` alongside any model artifact within `cfg.maint_backup_model_reproducibility_window_h`, emits `sec.alert.v1{kind=backup_model_lineage_missing, severity=warn}` (debounced per `cfg.sec_alert_debounce_ttl_s` — storm of missing files produces exactly 1 alert per debounce window). Suppress: drop a valid sidecar for any one model artifact → debounce resets, alert stops firing on next scan tick. | TBD — implementation pending Phase 12 |
| P12-8-Q | `chaos-maint-storage-fill` | Grow `data/maint/` to occupy 80 % of `cfg.maint_storage_total_max_mb`; warden emits `sec.alert.v1{kind=maint_storage_pressure, severity=warn}`. Continue filling past 100 % of the cap; warden transitions to observer mode AND emits `sec.alert.v1{kind=maint_storage_pressure, severity=error}`; no new spool writes are accepted while in observer mode. Recover: free space below 80 % threshold → observer mode exits, spool writes resume. | TBD — implementation pending Phase 12 |
| P12-8-R | `chaos-spool-retired-kind` | Inject a spool entry whose `kind` field appears in the retired-kinds registry; §8.7 spool-flush iterator must NOT replay the envelope — it moves the file to `<spool-dir>/.retired/<kind>/` and writes a sidecar `<file>.retired.json` recording `{kind, reason: "retired", moved_at}`; emits `sec.alert.v1{kind=spool_entry_retired_kind, severity=warn}` (one alert per distinct retired kind per flush run, not per file). Recovery path: operator runs `ops.spool-flush --force-retired --kind=<kind>` to explicitly replay retired entries after a kind has been un-retired in the registry. | TBD — implementation pending Phase 12 |
| P12-8-S | `chaos-restore-version-skew` | Offer a dump whose internal `max_version` metadata is `N` while the in-tree schema migration high-water mark is `N+6` (gap > `cfg.maint_backup_max_version_gap`, default 5); `ops.restore` must refuse with exit non-zero and `kind=backup_dump_too_old{dump_version: N, schema_version: N+6, gap: 6}`. Two valid recovery paths: (a) wait for a newer dump where `gap ≤ cfg.maint_backup_max_version_gap`, or (b) check out the historical commit whose migration high-water was `N` and run restore there. The agent must never produce a partial restore state when refusing. | TBD — implementation pending Phase 12 |
| P12-8-T | `chaos-audit-prune-storm` | Seed the `maint_audit_log` table with 10 M rows spread across 3 monthly partitions; invoke `ops.prune-audit --months=1` under a 10 QPS write storm on the same partition; the DETACH + DROP of the oldest partition must complete within 1 s (Postgres DDL lock hold-time bound); running DMLs must not block after the lock is released; `kind=maint_audit_partition_missing` must NOT fire during the prune (partition exists); afterward assert no orphan partition names remain under `pg_inherits`. | TBD — implementation pending Phase 12 |
| P12-8-U | `chaos-dump-file-bitflip-pre-tar` | Flip a single byte in one SQL file inside the pg_dump directory **before** the tar+age pipeline runs; `maint.backup.v1` must detect the SHA-256 mismatch via the per-file manifest (`negelir.files.sha256.txt`), emit `sec.alert.v1{kind=backup_dump_file_corrupted, severity=critical}`, rename the dump dir to `<date>.failed/`, and abort — no tarball or age-encrypted archive is written for the corrupted dump. The outer tarball checksum gate must not be reached (per-file check fires first). | TBD — implementation pending Phase 12 |
| P12-8-V | `chaos-age-binary-tampered` | Replace the `age` binary on disk with an unsigned substitute whose output matches the expected version string but whose SHA-256 differs from `cfg.maint_backup_age_binary_sha256` (future knob); alternatively, set `cfg.maint_backup_age_binary_version` to a value that does not match the installed binary's self-reported version; `maint.backup.v1` must refuse to start, emit `sec.alert.v1{kind=fail_safe_age_version_mismatch_local, severity=critical}`, and exit non-zero — no backup or restore proceeds until the binary is corrected. | TBD — implementation pending Phase 12 |
| P12-8-W | `chaos-opsctl-signature-forged` | Craft an opsctl envelope with a valid structure but an HMAC signature computed from a different (rotated-away) key; inject it directly into the `maint.event.v1` bus topic; the consumer-side gate must reject the envelope, emit `sec.alert.v1{kind=opsctl_signature_invalid, severity=critical}`, increment `opsctl_rejected_total` counter, and NOT process the command; the spool directory must remain unmodified; no ack is published for the rejected envelope. | TBD — implementation pending Phase 12 |
| P12-8-X | `chaos-spool-flush-concurrent` | Spawn two parallel `ops.spool-flush` invocations against a 50-entry spool directory with `cfg.opsctl_spool_flush_max_per_run=50`; exactly one invocation must win the `fcntl.flock` on `.flush.lock` and drain all 50 entries; the other must exit with code 8 (`spool_flush_already_running`) without publishing any envelopes; total bus publish count must equal exactly 50; no envelope must be published twice; `spool_flush_partial` event must NOT be emitted (spool fully drained in one run). | TBD — implementation pending Phase 12 |
| P12-8-Y | `chaos-container-suspend-window` | Suspend the container for a window that crosses the §8.15.1 clock-source probe interval. Verify `MonotonicClock.boot_utc` is still valid on resume and the scaler emits `maint.event.v1{kind=maint_clock_source_changed, action=suspend_detected}` on the first heartbeat tick after the gap. Assert `maint_clock_suspend_alert_s` threshold is respected — a gap shorter than the threshold must NOT fire the event. | TBD — implementation pending Phase 12 |
| P12-8-Z | `chaos-revoked-key-replay` | Revoke an operator key mid-session via `make ops.revoke-key OPERATOR=<email>`. Replay a captured signed envelope using the just-revoked key within `cfg.opsctl_key_revocation_grace_s` (default 3600 s). Verify the consumer accepts with `accepted=true` (grace period). Replay the same envelope after the grace window expires. Verify consumer rejects with `accepted=false, reason=key_revoked` and emits `sec.alert.v1{kind=opsctl_signature_invalid, severity=critical}`. Exit code from the opsctl runner must be 9 (`OPSCTL_KEY_REVOKED`). | TBD — implementation pending Phase 12 |
| P12-8-AA | `chaos-audit-truncate-attack` | Inject truncated rows (remove the last 3 bytes from a random row's CSV fields) directly into `data/maint/opsctl_audit.csv`. Verify the §8.15.7 hash-chain break detection fires `sec.alert.v1{kind=audit_log_integrity_break, severity=critical}` on the next hourly verify cron or on agent restart (whichever comes first). Assert `first_break_row` in the alert payload correctly identifies the tampered row. | TBD — implementation pending Phase 12 |
| P12-8-AB | `chaos-leader-handover-mid-shed` | Elevate the shed tier to `tier=2` on the current leader. Transfer leadership while shed is elevated (kill the leader pod; wait for the standby to win election). Verify `ShedStateStore` persistence: the new leader reads the elevated tier from Redis within 2 s of winning election; no scale decisions fire during the shed elevation; the `kind=shed_tier_elevated` audit event carries `inherited=true` on the new leader. | TBD — implementation pending Phase 12 |
| P12-8-AC | `chaos-noise-window-emergency-override` | Configure `cfg.maint_scaler_noise_windows` so the current time falls inside the window (e.g. `"* * * * *"`). Inject a `vram_budget_exceeded` signal. Verify the scaler fires the scale decision despite the noise window (emergency override). Also inject a `lag_high` signal in the same window and verify it is suppressed with `kind=scale_throttled, reason=noise_window_active`. Confirm exactly one `sec.alert.v1{kind=scaler_noise_window_active}` fires at the window-entry edge. | TBD — implementation pending Phase 12 |
| P12-8-AD | `chaos-verify-concurrency-deadlock` | Force two concurrent restore-verify processes (`maint.backup.v1` nightly + cold-verify) to attempt acquisition of `LOCK_MAINT_BACKUP_RESTORE_VERIFY` within 100 ms of each other. Verify `RestoreVerifyConcurrencyLock` serialises them: exactly one acquires first; the other waits up to `cfg.maint_backup_verify_lock_timeout_s` seconds, then yields with `kind=verify_concurrency_blocked, scope=cold` audit and `sec.alert.v1{kind=verify_concurrency_blocked, severity=warn}` (debounced). Cold-verify MUST yield to nightly per the policy; assert yield policy is correct direction. | TBD — implementation pending Phase 12 |
| P12-8-AE | `chaos-scaler-unconfigured-agent` | Register a brand-new agent class without widening `cfg.maint_scaler_max_replicas`; §8.16.1 fallback policy must apply `cfg.maint_scaler_default_max_replicas` (default 2) instead of refusing to start; exactly one `sec.alert.v1{kind=maint_scaler_unconfigured_agent, severity=warn, subject=<agent>}` fires per process lifetime; exactly one `maint.event.v1{kind=maint_scaler_default_applied, target=<agent>, applied=N}` audit row is emitted; `cfg.maint_scaler_global_max_replicas` hard cap is honoured (defaults cannot exceed it); no second alert fires on the next tick. | TBD — implementation pending Phase 12 |
| P12-8-AF | `chaos-spool-flush-ack-vacuum` | Publish 10 envelopes via `ops.spool-flush` while bus is unavailable; spool entries are written to `data/maint/agent_spool/`; restore bus connectivity; spool drains in arrival order; acks for the flushed envelopes land with no waiting foreground process (ack-in-vacuum); §8.16.2 DLQ-supervisor reconciler detects the open `flush_invocation_id` row and back-fills `ack_received_count` as each ack lands; once all expected acks land `kind=spool_flush_acks_reconciled` event is emitted exactly once; force one envelope to never produce an ack and wait past `cfg.opsctl_spool_ack_max_wait_h`; assert `sec.alert.v1{kind=spool_flush_acks_incomplete, severity=warn, missing_count=1}` fires (debounced per `flush_invocation_id`); running the reconciler twice in one tick must produce no duplicate `spool_flush_acks_reconciled` events. | TBD — implementation pending Phase 12 |
| P12-8-AG | `chaos-prune-fk-violation` | Synthesize a schema with an FK violating `xops/maint/prune_order.py::PRUNE_ORDER` (e.g. `opsctl_audit` referencing `maint_audit_log`); assert §8.16.3 boot validation refuses with `fail_safe_prune_order_invalid` + critical alert + non-zero exit; verify `maint.backup.v1` state machine enforces `dump → restore-verify → prune` order — simulated dump failure prevents prune phase from entering and emits `prune_skipped, reason=dump_failed`; assert `--prune-only` invocation is rejected with exit code 10 (`prune_only_forbidden`); per-table prune metrics (`maint_backup_prune_seconds{table,outcome}`, `maint_backup_prune_rows_total{table}`) must be emitted for each table processed. | TBD — implementation pending Phase 12 |
| P12-8-AH | `chaos-s3-multipart-id-expired` | Persist a `.offsite_state.json` referencing a multipart upload_id; stub `ListParts` to return `NoSuchUpload` (simulating bucket lifecycle abort after `DaysAfterInitiation`); §8.16.5 resume-flow must emit `maint.event.v1{kind=backup_offsite_upload_id_expired, dump_date, original_upload_id, age_h}`, delete `.offsite_state.json`, and restart the upload from scratch within `cfg.maint_backup_offsite_upload_timeout_h`; separately age the state file past `cfg.maint_backup_offsite_state_max_age_h` and assert restart-from-scratch triggers without probing `ListParts`; stub bucket lifecycle to `DaysAfterInitiation=1` (< `cfg.maint_backup_offsite_lifecycle_min_days`) and assert `sec.alert.v1{kind=backup_offsite_lifecycle_too_aggressive, severity=warn}` fires (debounced daily). | TBD — implementation pending Phase 12 |
| P12-8-AI | `chaos-object-lock-permission-loss` | Configure MinIO with Object-Lock enabled but IAM policy missing `s3:PutObjectRetention`; §8.16.6 `S3CompatibleTarget.preflight()` probe uploads 1KB sentinel and calls `GetObjectRetention`; mismatch between intended and actual retention metadata triggers refuse with `fail_safe_offsite_retention_not_applied`; also simulate credential rotation mid-day that drops `s3:PutObjectRetention` after a previously-successful preflight; assert the recurring probe (`cfg.maint_backup_offsite_preflight_interval_h`) detects the loss, flips the agent to spool-mode, and emits `sec.alert.v1{kind=backup_offsite_preflight_failed, severity=critical}` with the specific failure reason; assert spool-mode blocks new offsite upload attempts until the next successful preflight. | TBD — implementation pending Phase 12 |
| P12-8-AJ | `chaos-sec-plane-flood` | Inject `sec.alert.v1` at a rate that pushes consumer lag past `cfg.sec_plane_lag_alert_ms` (default 5000ms) sustained over `cfg.sec_plane_lag_alert_window_s` (default 60s); §8.16.11 tier-1 shedding must activate with exactly 1 `sec.alert.v1{kind=sec_plane_lag_high}` alert at the tier-transition boundary (no per-tick re-emission); ramp lag to tier-3 threshold; assert `maint.sec.v1` decimater agent STILL executes its Lua decimate call (emergency-override path) despite tier-3 shed; assert other §8.x sec-plane consumers (`maint.scaler.v1`, `maint.dlq.v1`) shed normally; clear lag and assert exactly 1 recovery event; assert maint-plane shed state is unaffected (independent state machines). | TBD — implementation pending Phase 12 |
| P12-8-AK | `chaos-allowlist-fingerprint-collision` | Use a precomputed test vector of two distinct substrings whose plain-SHA-256-truncated-to-128-bits collide; assert §8.16.10 HMAC-SHA256 fingerprints differ (keyed secret prevents bypass); insert 100 legacy `s`-algorithm rows and run `make ops.allowlist-rehash`; assert exactly 100 new HMAC `h`-rows written + 100 legacy rows marked `state='e'` + exactly one `maint.event.v1{kind=pattern_allowlist_legacy_hit}` audit event per row (debounced); on eval-path match of a legacy `s`-row via either algorithm, assert `kind=pattern_allowlist_legacy_hit` fires; rotate HMAC key via `make ops.rotate-allowlist-key`; assert active-row count unchanged, new fingerprints match the new key, old fingerprints no longer match; key older than `cfg.sec_input_allowlist_hmac_key_max_age_days` must trigger `sec.alert.v1{kind=allowlist_hmac_key_rotation_overdue, severity=warn}` daily. | TBD — implementation pending Phase 12 |
| P12-8-AL | `chaos-min-compatible-version-violation` | Synthesize `xops/versioning/chart.json` with `"swarm": {"min_compatible_with": {"ai": "9.99.0"}}` (unachievable floor); boot §8.13.1 `RegistryAuditor` against this chart; assert `xops/versioning/version.py::validate_compatibility()` raises and agent refuses to start with `fail_safe_lineage_writer_missing`; boot with a chart meeting the version floor; assert successful boot + legacy backfill path emits `kind=backup_model_lineage_legacy` for pre-existing artifacts (no warn alerts); assert `make version.compatibility-check` exits non-zero on the violating chart and zero on the conforming chart; assert round-trip test `test_chart_is_canonical` passes after adding the `compatibility` block. | TBD — implementation pending Phase 12 |
| P12-8-AM | `chaos.fixture-state-flap` | Assert dispatcher routes by observed fixture state, not assumed state. Flip a match from `scheduled` to `in_play_first_half` during an in-flight predict request; the system must decline the prediction and emit `meta.live_match_unsupported` instead of allowing `predict.final` to proceed. | TBD — implementation pending Phase 12 |
| P12-8-AN | `chaos.kill-pattern-mass-arm` | Arm more than `cfg.nlp_kill_pattern_arm_max_concurrent` kill patterns concurrently; NLP must cap the active arms at the configured limit, emit `kind=nlp_kill_pattern_arm_limit_reached`, and not silently arm extra patterns. | TBD — implementation pending Phase 12 |
| P12-8-AQ | `chaos.tr-pii-flood` | Flood the TR-PII detector with 200 RPS of PII-bearing input and verify p99 latency stays below `nlp_tr_pii_p99_max_ms=15` while still emitting `sec.alert.v1{kind=tr_pii_flood, severity=warn}` on overload. | TBD — implementation pending Phase 12 |
| P12-8-AR | `chaos.compound-flood` | Deliver 1000 RPS of synthetic concatenated tokens to the compound splitter and assert it does not exceed the shared lookup budget; failures must degrade gracefully with `kind=compound_splitter_budget_exceeded` instead of crashing. | TBD — implementation pending Phase 12 |
| P12-8-AS | `chaos.lexicon-rebuild-storm` | Trigger six simultaneous lexicon rebuilds while also driving 200 RPS of lookup traffic; assert zero false-positive `cpu_budget_exceeded` alerts per §10.28.12 grace and no pod OOMs. | TBD — implementation pending Phase 12 |
| P12-8-AT | `chaos.runaway-normalize` | Feed a synthetic Symspell-pathological corpus to the normalize stage and assert the CPU budget gate catches 100% of malformed inputs without any pod OOMs. | TBD — implementation pending Phase 12 |
| P12-8-AO | `chaos.lexicon-swap-staggered-pods` | Simultaneously update lexicon files on multiple pods; the cluster-wide swap window must remain under 1 s and no pod may serve answers with mixed lexicon versions. | TBD — implementation pending Phase 12 |
| P12-8-AP | `chaos.client-pinned-old-schema-flood` | Flood the gateway with clients pinned to an old schema version; NLP must still honour downgrade negotiation and not crash or reject unpinned clients while serving the pinned ones at the negotiated compatibility level. | TBD — implementation pending Phase 12 |

---

## Cross-phase families (indexed)

> These families are owned by sister phases that registered `chaos.*`
> references in their own design docs. They are indexed here (with the
> authoring §section) so this catalogue is the complete single source
> §12.5 requires; the full per-row bodies land as each owning phase
> ships its surface and Phase 12 promotes the stub to `implemented`.
> IDs follow the `P12-<phase>-<seq>` scheme; representative IDs are
> reserved below and extended in row form when implemented.

### §5 — Predictor swarm & consensus (`P12-5-*`)

| ID | Target | Property | Owning § |
|----|--------|----------|----------|
| P12-5-A | `chaos.kill-predictor` | Kill ≥ 50 % of predictors mid-request; consensus still publishes with `degraded=true` + `degraded_reason` and `consensus_min_voters` honoured. | ROADMAP §5.2 / §5.5 |
| P12-5-B | `chaos.predict-approved-degraded-flood` | Flood `predict.approved.v1` with `degraded=true`; NLP surfaces a documented degraded answer, never a 5xx. | design/phase10 §10.0 |
| P12-5-C | `chaos.citation-forgery` | Forge a `predict.approved.v1` citation HMAC with the wrong key; consumer drops it + `citation_signature_verify_failed`. | design/phase10 §10.21.8 |
| P12-5-D | `chaos.consensus-quorum-empty` | All predictors silent; consensus emits the quorum-empty fallback flag, never a fabricated prediction. | ROADMAP §5.2 |

### §9 — Go API gateway & identity (`P12-9-*`)

| ID | Target | Property | Owning § |
|----|--------|----------|----------|
| P12-9-A | `chaos.api-breaker-trip` | Trip each upstream breaker (pg / redis / swarm-rpc); gateway sheds with the documented RFC 7807 status, no unhandled 5xx. | design/phase9 §9.17.4 |
| P12-9-B | `chaos.api-hedge-budget` | Drive hedged predict requests; hedge budget is capped, dedup strips `:h1` at consensus. | design/phase9 §9.17.4 |
| P12-9-C | `chaos.api-shed-burst` | 5xx rate > 2 % for 30 s engages adaptive shedding; lifts cleanly on recovery. | design/phase9 §9.17.9 |
| P12-9-D | `chaos.api-cursor-timing` | Encrypted-cursor timing-oracle probe finds no observable difference. | design/phase9 §9.14 |
| P12-9-E | `chaos.jwt-confusion` | `alg=none` / HS256-pubkey-confusion / kid-path-traversal all rejected. | design/phase9 §9.14 |

### §10 — Turkish NLP (`P12-10-*`, plus historical `P12-8-AM…AT`)

| ID | Target | Property | Owning § |
|----|--------|----------|----------|
| P12-10-A | `chaos.kill-humanizer` | Kill the humanizer subprocess mid-render; answer falls back to the proofread template, GPU lease released, breaker opens. | design/phase10 §10.0 / §10.25.11 |
| P12-10-B | `chaos.lexicon-corrupt` | Corrupt a lexicon file; atomic swap reverts (all-or-nothing), prior generation keeps serving. | design/phase10 §10.21.3 |
| P12-10-C | `chaos.intent-classifier-flap` | Flap the intent model; abstention floor + did-you-mean hold, no silent misroute. | design/phase10 §10.0 |
| P12-10-D | `chaos.tr-normalize-spec-drift` | Mutate one byte of `tr_normalize_spec.json`; both Python + Go impls **refuse boot**. | design/phase10 §10.29.11 |
| P12-10-E | `chaos.l0-cache-collision-injection` | Force an L0 subject-key collision; full-SHA verify drops + re-RPCs, no cross-answer leak. | design/phase10 §10.30.12 |
| P12-10-F | `chaos.outbound-checksum-mutation-injection` | Mutate the answer body post-sign; outbound checksum gate blocks ship. | design/phase10 §10.31.11 |
| P12-10-G | `chaos.inbound-checksum-mutation` | Flip a byte after the gateway inbound checksum; NLP drops + 504 + `inbound_checksum_mismatch`. | design/phase10 §10.34.4 |
| P12-10-H | `chaos.lexicon-state-divergence-injection` | Corrupt one pod's lexicon set; gossip divergence detector quarantines within 5 min. | design/phase10 §10.32.12 |
| — | *(historical)* `P12-8-AM…AT` | NLP fixture-state / kill-pattern / pii-flood / compound-flood / rebuild-storm / runaway-normalize / lexicon-swap / pinned-schema (IDs frozen). | §10.27 / §10.28 |

### §11 — Compute (GPU/CPU/NPU) (`P12-11-*`)

| ID | Target | Property | Owning § |
|----|--------|----------|----------|
| P12-11-A | `chaos.gpu.pull` | Driver removed mid-serve; agent drains to a peer / CPU baseline, no dropped request. | design/phase11 §11.10 |
| P12-11-B | `chaos.gpu.thermal` / `chaos.gpu.oom` / `chaos.gpu.xid` | Thermal throttle / OOM / faked Xid each degrade within the documented budget. | design/phase11 §11.10 |
| P12-11-C | `chaos.gpu.frag` / `chaos.gpu.ecc.retire` | VRAM fragmentation + ECC retired-page deltas; arbiter refuses paper-only placement. | design/phase11 §11.10 |
| P12-11-D | `chaos.cpu.oversubscribe` | Spawn N > budget threads; governor bounds concurrency, predictor p95 SLO holds. | design/phase11 §11.10 |
| P12-11-E | `chaos.inference.nan` | Adversarial input → NaN logit; guard catches it, no NaN reaches the user. | design/phase11 §11.10 |
| P12-11-F | `chaos.compute.driver_upgrade` / `chaos.compute.hotremove` | Live drain + udev hot-remove; zero loss via §11.18 migration. | design/phase11 §11.10 / §11.18 |

### §13 — League & competition catalog (`P12-13-*`)

| ID | Target | Property | Owning § |
|----|--------|----------|----------|
| P12-13-A | `chaos.predictions.tamper` | Mutate a stored prediction envelope; audit detects within `cfg.predictions_tamper_detection_max_s`. | design/phase13 §13.54 |
| P12-13-B | `chaos.storage.deny` | Deny DB/Redis at the network layer; replica cold-starts to `/livez=OK`, serves `503 storage_unavailable`. | design/phase13 §13.49 |
| P12-13-C | `chaos.catalog.region-drift` | Diverge multi-region catalog; cross-region shaping refused while drift open. | design/phase13 §13.50 |
| P12-13-D | `chaos.rolling.catalog` | Half v_{N-1} / half v_N replicas serve the full window with zero crashes. | design/phase13 §13.60 |
| P12-13-E | `chaos.league.quarantine` | Force one league into quarantine; other leagues' SLOs unaffected. | design/phase13 §13.15 |
| P12-13-F | `chaos.bracket.violate` | Inject a bracket-invariant violation; federation correction clears the gate within budget. | design/phase13 §13.57 |

### §16 — Emitter & feed contract (`P12-16-*`)

| ID | Target | Property | Owning § |
|----|--------|----------|----------|
| P12-16-A | `feeds.chaos.run TEST=…` | The emitter's own chaos harness (feed signing / parity / snapshot rebuild) runs each registered feed scenario. | design/phase16 §25 |
| P12-16-B | `chaos.feed-signature-forge` | Forge a feed payload signature; consumer rejects swap + `lexicon_feed_signature_invalid`. | design/phase10 §10.22.12 / phase16 |