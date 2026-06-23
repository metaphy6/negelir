# 🔧 Centralized Configuration

> Companion to Phase 1 of [`../planning/ROADMAP.md`](../planning/ROADMAP.md).
> **Doctrine:** *one place per language, env-driven, validated, sync-tested.*

## 📐 Layout

```
xops/env/.env.example             # canonical env-var documentation
ai/common/
├── config.py                     # Python @dataclass Config, the only Python config
└── defaults.yaml                 # generated from config.py for human readers
server/internal/config/
├── config.go                     # Go Config struct, the only Go config
└── sync_test.go                  # parity test against xops/env/.env.example
ai/tests/test_config_sync.py      # parity test for the Python side
xops/lint/no_magic.py             # lint that forbids magic numbers
```

## 🎛️ Naming conventions

| Prefix | Owner | Example |
|---|---|---|
| `NEGELIR_` | shared (Python + Go) | `NEGELIR_COMMON_DEFAULT_LEAGUE_ID` |
| `SCRAPE_` | scrapers | `SCRAPE_RATE_LIMIT_SECONDS` |
| `AI_` | AI image / runtime hints | `AI_DEVICE`, `AI_IMAGE_FLAVOR` |
| `SERVER_` | Go API / mock server | `SERVER_PORT`, `SERVER_MODE` |
| `POSTGRES_` / `REDIS_` | infra connection | standard |
| `SEC_` | security agents | `SEC_INPUT_MAX_LEN`, `SEC_BURST_THRESHOLD` |
| `SWARM_` | bus / agents platform | `SWARM_HEARTBEAT_SEC`, `SWARM_BUS_KIND` |

A single key may not be owned by both Python and Go unless `xops/env/.env.example`
marks it `# shared`. The meta-test enforces this.

## ✅ Validation rules

- Every key in `xops/env/.env.example` is read by at least one config layer.
- Every config field has a sane default; validation rejects out-of-range values on startup.
- Strict mode (`NEGELIR_COMMON_STRICT=1`) refuses unknown keys with our prefixes — catches typos and stale configs.
- Tuple-range fields (e.g. `feature_ranges`) check `lo < hi`.
- Day-of-week fields check valid weekday names.
- URL fields check scheme.

## 🚫 Forbidden patterns

(enforced by `xops/lint/no_magic.py` in CI)

- Numeric literal in non-test code unless inside a `Config` field default.
- `localhost:<port>` outside test fixtures.
- `time.sleep(<int>)` in production code.
- `requests.get("https://...")` with a hardcoded URL.
- Float thresholds (`> 0.5`, `< 0.7`, …) — must be named.

## 🔄 Bidirectional sync

The `test_config_sync.py` and `sync_test.go` tests assert:

1. Every key documented in `xops/env/.env.example` is consumed by at least one config layer.
2. Every key consumed by a config layer is documented in `xops/env/.env.example`.
3. Defaults in `xops/env/.env.example` match defaults in code.
4. Pickle round-trip succeeds for the Python `Config` (config-as-data).
5. No Phase-2 synthetic-data env keys leak back in.
6. **Every `NEGELIR_*` / `SCRAPE_*` example cited in this document still exists in `xops/env/.env.example`** — catches stale doc examples after renames or removals.

> **This document is doctrine, not a registry.** The exhaustive list of
> tunables lives in [`xops/env/.env.example`](../../xops/env/.env.example)
> with one `NEGELIR_/SCRAPE_*=<default>` line per knob. Read that file
> when you need to know *what is configurable*; read this one when you
> need to know *how configuration is structured and enforced*.
>
> **Planned (Phase R6):** collapse the `defaults.yaml` ↔ `.env.example`
> redundancy by generating `.env.example` from `defaults.yaml` + `Config`
> field metadata. See ROADMAP §R6.

## 🌍 Same config, three deployments

Local compose, prod compose, and K8s all set the same env vars. The `Config`
layer doesn't care where they came from — `os.getenv` for Python, `env:` tags
for Go. K8s Secrets / ConfigMaps just project the same names.

---

## 🔧 Maintenance (Phase 8)

All knobs below are `NEGELIR_*` env vars, consumed by `ai/common/config.py`, and
validated at startup. Ranges shown are the `_bounded()` contract; out-of-range
values abort boot with a descriptive error.

> **Registry note:** canonical defaults live in `ai/common/defaults.yaml` and
> `xops/env/.env.example`. The table below is the human-readable summary;
> `test_config_sync.py` fails if this doc cites a key that no longer exists.

### Ops console (`opsctl`)

| Key | Default | Range / values | Safety note |
|---|---|---|---|
| `opsctl_ack_timeout_ms` | `5000` | > 0 | Timeout (ms) waiting for consumer acks in `run_publish`. |
| `opsctl_spool_max_entries` | `1024` | ≥ 1 | Cap on bus-down spool files; oldest entry dropped when exceeded. |
| `opsctl_critical_agents` | `consensus.v1,sec.rate.v1,maint.backup.v1` | CSV | Agents requiring `--confirm-destructive` for any destructive command. |
| `opsctl_audit_path` | `""` | file path | Path to opsctl audit log CSV; empty disables the audit file. |
| `opsctl_spool_dir` | `""` | dir path | Spool directory; empty uses a temp path. |
| `opsctl_lock_dir` | `""` | dir path | Lock directory for re-entrancy guards; empty uses a temp path. |
| `opsctl_lock_stale_factor` | `2` | ≥ 1 | `ack_timeout_ms × factor` before a held lock is considered stale. |
| `opsctl_spool_ack_max_wait_h` | `24` | > 0 h | Max hours to wait for ack before a spooled entry expires. |

### Ack payload sizing

| Key | Default | Range | Safety note |
|---|---|---|---|
| `maint_ack_payload_max_bytes` | `4096` | ≥ 1 | Total ack envelope size cap; truncated + `maint_ack_oversize` alert if exceeded. |
| `maint_ack_reason_max_bytes` | `512` | ≥ 1 | `reason` field cap within an ack. |
| `maint_ack_details_max_bytes` | `2048` | ≥ 1 | `details` field cap within an ack. |

### Auto-scaler (`maint.scaler.v1`)

| Key | Default | Range / values | Safety note |
|---|---|---|---|
| `maint_runtime` | `none` | `none\|compose\|k8s` | Runtime adapter for replica mutations. `none` disables all scale calls (dry-run equivalent). |
| `maint_scaler_decision_window_ms` | `30000` | > 0 ms | Decision window length; drives `decision_window_id`. |
| `maint_scaler_clock_source` | `auto` | `auto\|monotonic\|wall` | Clock for window boundaries; `auto` picks monotonic where available. |
| `maint_scaler_max_targets` | `256` | ≥ 1 | Max agent targets tracked in-memory. |
| `maint_scaler_max_replicas` | `16` | ≥ 1 | Per-agent replica cap (default; see `maint_scaler_max_replicas_overrides_csv`). |
| `maint_scaler_default_max_replicas` | `0` | ≥ 0 | `0` = fall back to `maint_scaler_max_replicas` for unconfigured agents. Non-zero overrides globally. |
| `maint_scaler_min_replicas` | `1` | ≥ 1 | Replica floor; scale-down never goes below this. |
| `maint_scaler_global_max_replicas` | `64` | ≥ 1 | Hard cap across all agents combined; trumps per-agent overrides. |
| `maint_scaler_max_replicas_overrides_csv` | `""` | CSV `agent=N` | Per-agent replica caps; entries trump `maint_scaler_max_replicas`. |
| `maint_scaler_scale_up_queue_depth` | `50` | ≥ 1 | Queue depth threshold to trigger a scale-up decision. |
| `maint_scaler_scale_down_queue_depth` | `5` | ≥ 1 | Queue depth threshold to allow a scale-down decision. |
| `maint_scaler_scale_up_head_age_s` | `30` | ≥ 0 s | Head-of-queue age (s) as secondary scale-up trigger. |
| `maint_scaler_hysteresis_windows` | `3` | ≥ 1 | Consecutive decision windows the signal must hold before acting. |
| `maint_scaler_hysteresis_grace` | `1` | ≥ 0 | Grace windows before a scale-down is permitted after a scale-up. |
| `maint_scaler_max_changes_per_window` | `4` | ≥ 1 | Max replica mutations within a single window. |
| `maint_scaler_min_decision_interval_s` | `90` | ≥ 0 s | Min seconds between consecutive decisions for the same agent (hysteresis). |
| `maint_scaler_signal_window_samples` | `5` | ≥ 0 | Sliding-window samples for signal smoothing; `0` disables smoothing. |
| `maint_scaler_scale_down_grace_windows` | `3` | ≥ 0 | Extra windows of grace before scale-down after any scale-up. |
| `maint_scaler_target_load_per_replica` | `25` | ≥ 1 | Target queue depth per replica used to compute desired replica count. |
| `maint_scaler_max_step_per_window` | `2` | ≥ 1 | Max replica delta per single decision window. |
| `maint_scaler_manual_pin_ttl_s` | `1800` | ≥ 1 s | Default TTL for `ops.scale --pin`; auto-scaler emits `scale_throttled` during pin. |
| `maint_scaler_warmup_replicas` | `1` | ≥ 1 | Replica count set on first boot before signal history is available. |
| `maint_scaler_history_max` | `1024` | ≥ 1 | Max LRU entries in per-agent decision history (insertion-order eviction). |
| `maint_scaler_vram_headroom_mb` | `1024` | ≥ 0 MB | Free VRAM (MB) to preserve; scale-up refused if projected exceedance (`reason=vram_budget_exceeded`). |
| `maint_scaler_runtime_timeout_s` | `30` | > 0 s | Wall-clock timeout for runtime (compose/k8s) API calls. |
| `maint_scaler_compose_file` | `docker-compose.yml` | file path | Compose file used when `maint_runtime=compose`. |
| `maint_scaler_runtime_histogram_buckets` | `0.005,…,10.0` | CSV floats | Prometheus histogram bucket boundaries for runtime-call latency. |

### Leader lease

| Key | Default | Range | Safety note |
|---|---|---|---|
| `maint_leader_lease_duration_s` | `15` | ≥ 1 s | K8s coordination lease duration; losing pod transitions to observer after this, strictly before `lease_duration + 5s`. |

### DLQ supervisor (`maint.dlq.v1`)

| Key | Default | Range | Safety note |
|---|---|---|---|
| `maint_dlq_max_replays_per_tick` | `50` | ≥ 1 | Total replays per heartbeat tick; fairly distributed across topics. |
| `maint_dlq_per_topic_max_per_min` | `60` | ≥ 1 | Per-topic replay rate cap (entries/min). |
| `maint_dlq_replay_rps` | `10` | ≥ 1 | Per-topic replay rate (entries/s); `sec.quarantine.v1.dlq`, `sec.alert.v1.dlq`, `qa.request.v1.dlq` excluded from auto-replay. |
| `maint_dlq_replay_topics_allow_csv` | `""` | CSV topics | Auto-replay allow-list; empty = all non-blocked topics eligible. |
| `maint_dlq_per_topic_quota` | `100` | ≥ 1 | In-memory entry cap per topic before backpressure alert. |
| `maint_dlq_state_max` | `100000` | ≥ 1 | Max in-memory DLQ state entries; cap-pressure alert fires when fill rate outpaces backoff. |
| `maint_dlq_backlog_alert` | `1000` | ≥ 1 | Total DLQ depth threshold for `dlq_backlog_alert`. |
| `maint_dlq_visit_max` | `2` | ≥ 1 | Max replay visits per entry before escalation to `predict.vote → predict.final` path. |
| `maint_dlq_visit_lru` | `4096` | ≥ 1 | LRU size for per-entry visit tracking. |
| `maint_dlq_replay_backoff_s` | `60` | ≥ 1 s | Initial backoff between replay attempts for a given entry. |
| `maint_dlq_backoff_factor` | `2` | ≥ 1 | Exponential backoff multiplier per visit. |
| `maint_dlq_backoff_lru` | `1024` | ≥ 1 | LRU cache size for per-entry backoff state. |
| `maint_dlq_consumer_broken_threshold` | `5` | ≥ 1 | Distinct failed `request_id`s within window to trigger `consumer_likely_broken` + topic freeze. |
| `maint_dlq_consumer_broken_window_s` | `600` | ≥ 1 s | Rolling window (s) for consumer-broken detection. |

### Schema sentinel (`maint.schema.v1`)

| Key | Default | Range | Safety note |
|---|---|---|---|
| `maint_schema_sample_rate_per_s` | `5` | > 0 | Schema-fingerprint sample rate (envelopes/s). |
| `maint_schema_burst` | `10` | ≥ 1 | Token-bucket burst size for schema sampling. |
| `maint_schema_drift_debounce_s` | `60` | ≥ 1 s | Minimum seconds between consecutive drift alerts for the same schema. |
| `maint_schema_drift_lru` | `512` | ≥ 1 | LRU size for per-schema debounce tracking. |
| `maint_schema_pg_check_interval_s` | `3600` | ≥ 1 s | Interval for Postgres schema Detector B check. |
| `maint_schema_snapshot_retention_days` | `90` | ≥ 1 d | Retention for schema snapshots [1–3650]. |
| `maint_schema_auto_apply_enabled` | `false` | bool | If `true`, sentinel auto-applies additive migrations. **Dangerous; leave `false` in prod.** |
| `maint_schema_validate_max_rps` | `50` | 1–500 | Hard per-process cross-topic validation-rate cap (§8.14.7). Exceeding 500 refuses boot (`fail_safe_validate_rps_cap_exceeded`). |

### Security maintenance (`maint.sec.v1`)

| Key | Default | Range | Safety note |
|---|---|---|---|
| `maint_sec_pattern_ttl_s` | `604800` (7 d) | ≥ 1 s | TTL before a promoted allowlist pattern expires. |
| `maint_sec_pattern_promote_threshold` | `1` | ≥ 1 | Min hit count before a pending pattern is promoted to active. |
| `maint_sec_pattern_pending_ttl_days` | `30` | ≥ 1 d | Days before an unreviewed pending pattern is expired. |
| `maint_sec_allowlist_pending_ttl_days` | `30` | ≥ 1 d | Canonical Phase 8 name for the same pending-TTL gate. |
| `maint_sec_request_lru` | `2048` | ≥ 1 | LRU size for per-request sec-event deduplication. |
| `maint_sec_decimate_min_interval_s` | `300` | ≥ 1 s | Hysteresis: min seconds between consecutive denylist decimate Lua calls. |

### Planned-pause / dead-man's silence

| Key | Default | Range | Safety note |
|---|---|---|---|
| `maint_pause_default_ttl_s` | `600` | ≥ 1 s | Default TTL when `ops.maint-pause` is invoked without `--ttl-s`. |
| `maint_pause_max_ttl_s` | `86400` (24 h) | ≥ 1 s | Hard cap; `ops.maint-pause --ttl-s` is clamped to this. |
| `maint_silence_alert_h` | `24` | ≥ 1 h | Hours of no `maint.event.v1` before `maint_silence_alert` fires. |
| `maint_silence_dedup_s` | `300` | ≥ 1 s | Dedup window for silence alerts; one alert per window maximum. |
| `maint_silence_warmup_s` | `3600` | ≥ 0 s | Startup grace period before the silence watchdog activates. |

### Self-monitoring / plane health

| Key | Default | Range | Safety note |
|---|---|---|---|
| `maint_self_dlq_alert` | `100` | ≥ 1 | Maint agent's own DLQ depth triggering a self-alert. |
| `maint_self_dlq_growth_alert` | `20` | [1, 100000] | Per-heartbeat growth rate threshold for DLQ depth. |
| `maint_plane_lag_alert_ms` | `5000` | [100, 300000] ms | Consumer lag (ms) to trigger tier-1 shedding + alert. |
| `maint_plane_lag_alert_window_s` | `60` | [1, 3600] s | Rolling window for lag tier evaluation. |
| `maint_plane_recovery_window_s` | `120` | [1, 3600] s | Seconds of clear lag before a recovery event fires. |

### Bus circuit-breaker / per-agent spool

| Key | Default | Range | Safety note |
|---|---|---|---|
| `maint_bus_fail_threshold` | `3` | [1, 100] | Consecutive bus publish failures before agent enters `bus_degraded` and starts spooling. |
| `maint_bus_spool_max_entries` | `1024` | [1, 100000] | Global bus-down spool cap (shared). |
| `maint_agent_spool_dir` | `data/maint/agent_spool` | dir path | Base directory for per-agent spool subdirectories. |
| `maint_agent_spool_max_entries` | `1024` | [1, 100000] | Per-agent spool cap; oldest entry overwritten when exceeded. |

### Backpressure thresholds

Yellow < Red for every paired metric; boot validation refuses misconfiguration.

| Key | Default | Range | Safety note |
|---|---|---|---|
| `maint_backpressure_yellow_factor` | `4.0` | [1.0, 1000.0] | Yellow-zone signal amplification factor. |
| `maint_backpressure_yellow_queue_depth` | `200` | [1, 100M] | Queue depth for yellow tier; must be < red. |
| `maint_backpressure_yellow_head_age_s` | `60` | [0, 86400] s | Head-of-queue age for yellow tier; must be < red. |
| `maint_backpressure_yellow_storage_pct` | `75` | [0, 100] % | Disk used % for yellow tier; must be < red. |
| `maint_backpressure_yellow_error_rate_per_s` | `1` | [0, 1M] | Errors/s for yellow tier; must be < red. |
| `maint_backpressure_red_queue_depth` | `1000` | [1, 100M] | Queue depth for red (observer) tier. |
| `maint_backpressure_red_head_age_s` | `300` | [0, 86400] s | Head-of-queue age for red tier. |
| `maint_backpressure_red_storage_pct` | `92` | [0, 100] % | Disk used % for red tier. |
| `maint_backpressure_red_error_rate_per_s` | `10` | [0, 1M] | Errors/s for red tier. |

### Storage / lock limits

| Key | Default | Range | Safety note |
|---|---|---|---|
| `maint_storage_total_max_mb` | `512` | [1, 1048576] MB | Total data-dir budget; `0` = no limit. |
| `maint_advisory_lock_max_hold_ms` | `5000` | [1, 3600000] ms | Max advisory-lock hold time; `0` = no limit. |

### Audit log

| Key | Default | Range | Safety note |
|---|---|---|---|
| `maint_audit_hmac_key_b64` | `""` | base64 | HMAC-SHA256 signing key for audit row integrity; empty disables signing. **Set in prod.** |
| `maint_audit_partition_retention_days` | `365` | [1, 36500] d | Days to retain audit-log partitions before pruning. |
| `maint_audit_retention_days` | `365` | [1, 3650] d | Global per-kind retention; overridden per kind by `maint_audit_retention_days_overrides`. |
| `maint_audit_retention_days_overrides` | `{"pii_erased":2555}` | JSON object | Per-kind retention overrides (7 years for right-to-erasure evidence per `SECURITY.md`). |

### Backup agent (`maint.backup.v1`)

| Key | Default | Range / values | Safety note |
|---|---|---|---|
| `maint_backup_cron` | `0 3 * * *` | cron expr | Daily backup schedule (03:00 UTC); must not resolve to every-minute. |
| `maint_backup_dir` | `./data/backups` | dir path | Local backup storage root. |
| `maint_backup_retention_days` | `14` | [1, 3650] d | Daily dump retention. |
| `maint_backup_retention_weeks` | `4` | [1, 520] w | Weekly dump retention. |
| `maint_backup_dry_run` | `false` | bool | Skip actual dump/upload; mock-profile default is `true`. |
| `maint_backup_min_free_gb` | `5` | [1, 100000] GB | Min free disk before backup starts; checked against `max(2× last_dump, min_free_gb)`. |
| `maint_backup_max_skew_h` | `36` | [1, 8760] h | Max hours overdue before catch-up run fires. |
| `maint_backup_age_alert_h` | `30` | [1, 8760] h | Hours since last verified backup before `backup_age_alert`. |
| `maint_backup_clock_step_back_alert_s` | `300` | [1, 86400] s | Backward clock step (s) that triggers `backup_clock_skew` error + skips fire. |
| `maint_backup_clock_step_forward_alert_h` | `24` | > 0 h | Forward clock leap (h) that emits `backup_clock_skew` warn; catch-up still fires. |
| `maint_backup_pg_jobs` | `2` | [1, 64] | Parallel pg_dump/pg_restore workers. |
| `maint_backup_pg_conn_limit` | `0` | [0, 10000] | `0` = auto (pg_jobs+1); refused if role `CONNECTION LIMIT` < pg_jobs+1 (`fail_safe_pg_conn_limit_too_low`). |
| `maint_backup_prune_batch` | `10000` | [1, 1000000] | Max rows per prune transaction batch (bounds lock-hold time). |
| `maint_backup_prune_max_lock_ms` | `500` | [1, 300000] ms | Max table-lock hold per batch; exceeded → emergency abort. |
| `maint_backup_pg_dsn` | `""` | DSN | Postgres DSN; empty inherits `DATABASE_URL`. |
| `maint_backup_encryption_key_dir` | `""` | dir path | Age keypair directory; must be set in `profile=prod` (`fail_safe_no_encryption_in_prod`). |
| `maint_backup_age_recipients_file` | `""` | file path | Age public-key recipients file; empty = no encryption. |
| `maint_backup_min_dr_recipients` | `2` | [1, 64] | Min DR-class recipients required in prod (`fail_safe_min_recipients`). |
| `maint_backup_age_identity_file` | `""` | file path | Age private identity for verify-only decryption inside `SidecarVerifier`. |
| `maint_backup_verify_pg_image` | `postgres:16-alpine` | image ref | PG image for K8s restore-verify Job; must not end in `:latest`. |
| `maint_backup_verify_mode` | `full` | `full\|toc_only` | Restore verify depth. |
| `maint_backup_verify_orphan_ttl_h` | `6.0` | > 0 h | Hours before orphaned verify Jobs/PVCs are swept on agent boot. |
| `maint_backup_pvc_size_gb` | `10` | [1, 65536] Gi | Ephemeral K8s PVC size for restore-verify. |
| `maint_backup_pii_excluded_columns` | `quarantine_samples.raw_bytes_b64` | CSV `table.column` | Columns excluded from dumps (PII-aware backup policy). |
| `maint_backup_pg_role` | `negelir_backup` | role name | PG role the agent must run as; refused otherwise (`fail_safe_wrong_pg_role`, `fail_safe_superuser`). |
| `maint_backup_cold_verify_cron` | `0 5 * * 0` | cron expr | Weekly cold-verify schedule (Sun 05:00 UTC). |
| `maint_backup_verify_key_rotate_per_dump` | `true` | bool | Rotate verify keypair on every nightly dump. |
| `maint_backup_offsite_target` | `none` | `none\|s3` | Offsite backend. |
| `maint_backup_offsite_endpoint` | `""` | URL | S3/MinIO endpoint; required when `offsite_target=s3`. |
| `maint_backup_offsite_bucket` | `""` | string | Target bucket name. |
| `maint_backup_offsite_multipart_threshold_mb` | `64` | ≥ 1 MB | File size above which multipart upload is used. |
| `maint_backup_offsite_bw_kbps` | `0` | ≥ 0 Kbps | Upload bandwidth cap; `0` = unlimited. |
| `maint_backup_offsite_upload_timeout_h` | `6` | > 0 h | Max hours per offsite upload before failure + critical alert. |
| `maint_backup_offsite_object_lock_days` | `0` | ≥ 0 d | WORM object-lock retention; `0` = no lock. |
| `maint_backup_offsite_age_alert_h` | `48` | ≥ 0 h | Hours since last offsite upload before `backup_offsite_failed`; `0` disables watchdog. |
| `maint_backup_offsite_retention_days` | `7` | ≥ 1 d | Days to retain offsite dumps. |

### Source-watcher summarizer (Phase 8 / §2.8)

The summarizer is **narration-only** — it cannot mutate classifier output (boundary test enforced).

| Key | Default | Range / values | Safety note |
|---|---|---|---|
| `source_watcher_summarizer_enabled` | `false` | bool | Enable LLM narration; off by default to avoid unplanned token spend. |
| `source_watcher_summarizer_model_id` | `""` | model ID | Must pin a specific version; `*-latest` refused at boot. Required when enabled. |
| `source_watcher_summarizer_probe_url` | `""` | URL | Health-check URL verified before first call. Required when enabled. |
| `source_watcher_summarizer_probe_timeout_sec` | `2.0` | [1, 30] s | Probe request timeout. |
| `source_watcher_summarizer_max_tokens_per_call` | `4096` | [1, 65536] | Per-call token cap; request is bounded to this value. Fallback deterministic narration emitted on refusal. |
| `source_watcher_summarizer_max_tokens_per_day` | `50000` | ≥ `max_tokens_per_call` | Daily token budget; exceeded → fallback narration + `summarizer_cost_capped{scope=per_day}`. |
| `source_watcher_summarizer_ledger_path` | `data/maint/summarizer_ledger.json` | file path | Persistent daily token-usage ledger. |

<!-- BEGIN GENERATED -->
## Exported Configuration Registry

The following registry is automatically generated from `common/config/defaults.yaml`.
Do not edit this section by hand; run `make config.export-doc` to regenerate.

| Variable | Default | Range / values | Notes |
|---|---|---|---|
| `POSTGRES_HOST` | `localhost` | — | Auto-generated |
| `POSTGRES_PORT` | `5432` | — | Auto-generated |
| `POSTGRES_DB` | `negelir` | — | Auto-generated |
| `POSTGRES_USER` | `negelir` | — | Auto-generated |
| `REDIS_HOST` | `localhost` | — | Auto-generated |
| `REDIS_PORT` | `6379` | — | Auto-generated |
| `NEGELIR_REDIS_SOCKET_TIMEOUT` | `2` | — | Auto-generated |
| `SERVER_URL` | `http://localhost:8080` | — | Auto-generated |
| `NEGELIR_SERVER_FETCH_TIMEOUT` | `10` | — | Auto-generated |
| `AI_LOG_LEVEL` | `DEBUG` | — | Auto-generated |
| `NEGELIR_COMMON_DEFAULT_LEAGUE_ID` | `super_lig` | — | Auto-generated |
| `NEGELIR_DEFAULT_SEASON` | `""` | — | Auto-generated |
| `NEGELIR_MACKOLIK_GROUP_ID` | `1` | — | Auto-generated |
| `NEGELIR_MACKOLIK_LEAGUE_FILTER` | `"Süper Lig"` | — | Auto-generated |
| `NEGELIR_SCRAPE_TRIGGER_TIMEOUT` | `30` | — | Auto-generated |
| `NEGELIR_HEALTH_CHECK_TIMEOUT` | `5` | — | Auto-generated |
| `NEGELIR_MACKOLIK_HTTP_TIMEOUT` | `15` | — | Auto-generated |
| `NEGELIR_SCRAPE_HTTP_TIMEOUT` | `15` | — | Auto-generated |
| `NEGELIR_FOOTBALLDATA_HTTP_TIMEOUT` | `10` | — | Auto-generated |
| `NEGELIR_SCHEDULE_DAILY_SCRAPE_HOUR` | `6` | — | Auto-generated |
| `NEGELIR_SCHEDULE_DAILY_SCRAPE_MINUTE` | `0` | — | Auto-generated |
| `NEGELIR_SCHEDULE_OUTCOME_CHECK_HOUR` | `22` | — | Auto-generated |
| `NEGELIR_SCHEDULE_OUTCOME_CHECK_MINUTE` | `0` | — | Auto-generated |
| `NEGELIR_SCHEDULE_RETRAIN_HOUR` | `3` | — | Auto-generated |
| `NEGELIR_SCHEDULE_HEARTBEAT_MINUTES` | `5` | — | Auto-generated |
| `NEGELIR_STALE_CONFIDENCE_PENALTY` | `0.5` | — | Auto-generated |
| `NEGELIR_SOURCE_FAILURE_THRESHOLD` | `3` | — | Auto-generated |
| `SCRAPE_RATE_LIMIT_SECONDS` | `2` | — | Auto-generated |
| `NEGELIR_REAL_DATA_RATE_LIMIT` | `1.0` | — | Auto-generated |
| `SCRAPE_USER_AGENT` | `"Xops/0.1 (Football Analysis Research)"` | — | Auto-generated |
| `SCRAPE_RESPECT_ROBOTS_TXT` | `true` | — | Auto-generated |
| `NEGELIR_TRAINING_NOISE_PCT` | `0.005` | — | Auto-generated |
| `NEGELIR_TRAINING_TEST_SPLIT` | `0.2` | — | Auto-generated |
| `NEGELIR_TRAINING_SEED` | `42` | — | Auto-generated |
| `NEGELIR_TRAINING_CROSS_SOURCE_AGREEMENT_MULTI` | `0.95` | — | Auto-generated |
| `NEGELIR_MODEL_MAX_SIZE_MB` | `8.0` | — | Auto-generated |
| `NEGELIR_TRAINING_MIN_MATCHES` | `100` | — | Auto-generated |
| `NEGELIR_NLP_MIN_ANSWER_CHARS` | `20` | — | Auto-generated |
| `NEGELIR_NLP_MAX_ANSWER_CHARS` | `600` | — | Auto-generated |
| `NEGELIR_NLP_REPEAT_COLLAPSE_MAX_LEN` | `64` | — | Auto-generated |
| `NEGELIR_NLP_REPEAT_COLLAPSE_MIN_FREQ` | `100` | — | Auto-generated |
| `NEGELIR_NLP_DIGIT_LETTER_FOLD_ENABLED` | `true` | — | Auto-generated |
| `NEGELIR_NLP_NEGATION_ENABLED` | `true` | — | Auto-generated |
| `NEGELIR_NLP_COMPOUND_QUERY_ENABLED` | `true` | — | Auto-generated |
| `NEGELIR_NLP_EMOJI_HINT_ENABLED` | `true` | — | Auto-generated |
| `NEGELIR_NLP_HASHTAG_HANDLING_ENABLED` | `true` | — | Auto-generated |
| `NEGELIR_NLP_AT_MENTION_HANDLING_ENABLED` | `true` | — | Auto-generated |
| `NEGELIR_NLP_HTML_UNESCAPE_ENABLED` | `true` | — | Auto-generated |
| `NEGELIR_NLP_HARMONY_TOLERANT_STRIP_ENABLED` | `true` | — | Auto-generated |
| `NEGELIR_NLP_PREAMBLE_STRIP_ENABLED` | `true` | — | Auto-generated |
| `NEGELIR_NLP_CONSONANT_ALTERNATION_ENABLED` | `true` | — | Auto-generated |
| `NEGELIR_NLP_ASSIMILATION_FOLD_ENABLED` | `true` | — | Auto-generated |
| `NEGELIR_NLP_COMPOUND_SPLIT_ENABLED` | `true` | — | Auto-generated |
| `NEGELIR_NLP_TR_PII_REDACT_ENABLED` | `true` | — | Auto-generated |
| `NEGELIR_NLP_TELEGRAPHIC_MAX_TOKENS` | `4` | — | Auto-generated |
| `NEGELIR_NLP_TELEGRAPHIC_MIN_ENTITY_CONFIDENCE` | `0.85` | — | Auto-generated |
| `NEGELIR_NLP_TELEGRAPHIC_INFERENCE_ENABLED` | `true` | — | Auto-generated |
| `NEGELIR_NLP_KI_CONTEXT_DISAMBIGUATION` | `true` | — | Auto-generated |
| `NEGELIR_NLP_TR_NORMALIZE_SPEC_PATH` | `"ai/common/text/tr_normalize_spec.json"` | — | Auto-generated |
| `NEGELIR_NLP_TR_NORMALIZE_SPEC_REQUIRED` | `enforce` | — | Auto-generated |
| `NEGELIR_NLP_LOANWORD_VARIANTS_ENABLED` | `true` | — | Auto-generated |
| `NEGELIR_NLP_LOANWORD_SINGULARISATION_ENABLED` | `true` | — | Auto-generated |
| `NEGELIR_NLP_QUEUE_PRESSURE_THRESHOLD` | `100` | — | Auto-generated |
| `NEGELIR_NLP_PRESSURE_HUMANIZE_OFF_S` | `60` | — | Auto-generated |
| `NEGELIR_NLP_EVAL_CORPUS_PR_MAX_ADDED_ROWS_PER_QUARTER` | `500` | — | Auto-generated |
| `NEGELIR_NLP_EVAL_CORPUS_REVIEW_REQUIRED` | `true` | — | Auto-generated |
| `NEGELIR_NLP_ANSWER_SAMPLE_INVERSE` | `1000` | — | Auto-generated |
| `NEGELIR_NLP_ANSWER_SAMPLE_DAILY_CAP` | `5000` | — | Auto-generated |
| `NEGELIR_NLP_AUDIT_BUNDLE_RETENTION_DAYS` | `2555` | — | Auto-generated |
| `NEGELIR_NLP_DEFAULT_ANSWER_FORMAT` | `"plain"` | — | Auto-generated |
| `NEGELIR_NLP_ANSWER_FORMATS` | `"plain,markdown_safe,screen_reader,whatsapp_4096,sms_160,tts_neutral"` | — | Auto-generated |
| `NEGELIR_NLP_ANSWER_FORMAT_ENABLED` | `'{"plain": true, "markdown_safe": true, "screen_reader": true, "whatsapp_4096": false, "sms_160": false, "tts_neutral": false}'` | — | Auto-generated |
| `NEGELIR_NLP_TEMPLATE_GIT_SHA` | `""` | — | Auto-generated |
| `NEGELIR_NLP_PIPELINE_VERSION` | `"10.0.0"` | — | Auto-generated |
| `NEGELIR_NLP_COMPATIBILITY_MATRIX_PATH` | `"ai/nlp/_compat/compatibility_matrix.json"` | — | Auto-generated |
| `NEGELIR_NLP_SYSTEM_CAPABILITY_TEMPLATE_PATH` | `""` | — | Auto-generated |
| `NEGELIR_NLP_BOOT_BUDGET_S` | `30` | — | Auto-generated |
| `NEGELIR_NLP_BOOT_LIVENESS_GRACE_S` | `60` | — | Auto-generated |
| `NEGELIR_NLP_SHUTDOWN_GRACE_S` | `20` | — | Auto-generated |
| `NEGELIR_NLP_LOG_MAX_UNREDACTED_STR_LEN` | `64` | — | Auto-generated |
| `NEGELIR_PREDICT_CITATION_HMAC_KEY_PATH` | `/var/lib/negelir/secrets/predict_citation_hmac.key` | — | Auto-generated |
| `NEGELIR_PREDICT_CITATION_HMAC_KEY_GRACE_S` | `86400` | — | Auto-generated |
| `NEGELIR_NLP_PREDICT_CITATION_HMAC_REQUIRED` | `warn` | — | Auto-generated |
| `NEGELIR_NLP_JINJA_BCC_DIR` | `"data/cache/jinja_bcc"` | — | Auto-generated |
| `NEGELIR_NLP_TEMPLATE_FINALIZE_MIN_USER_TEXT_LEN` | `6` | — | Auto-generated |
| `NEGELIR_TELEMETRY_MAX_STREAM` | `50000` | — | Auto-generated |
| `NEGELIR_TELEMETRY_DEBUG_ENABLED` | `false` | — | Auto-generated |
| `NEGELIR_TELEMETRY_DEBUG_MAX_SERIES` | `5000` | — | Auto-generated |
| `SWARM_CONSUMER_GROUP_PREFIX` | `swarm` | — | Auto-generated |
| `SWARM_HEARTBEAT_SEC` | `5` | — | Auto-generated |
| `SWARM_REGISTRY_TTL_SEC` | `30` | — | Auto-generated |
| `SWARM_MAX_IN_FLIGHT` | `32` | — | Auto-generated |
| `SWARM_RETRY_BUDGET` | `3` | — | Auto-generated |
| `SWARM_DLQ_MAX_LEN` | `10000` | — | Auto-generated |
| `SWARM_PENDING_CLAIM_SEC` | `60` | — | Auto-generated |
| `SWARM_METRICS_PORT` | `9100` | — | Auto-generated |
| `SCRAPE_HTTP_MAX_RETRIES` | `3` | — | Auto-generated |
| `NEGELIR_CATEGORIZER_MIN_CONF` | `0.55` | — | Auto-generated |
| `NEGELIR_CATEGORIZER_MODEL_PATH` | `data/models/categorizer_v1.joblib` | — | Auto-generated |
| `NEGELIR_CACHE_RECORD_TTL_SEC` | `600` | — | Auto-generated |
| `NEGELIR_CACHE_PREDICTION_TTL_SEC` | `300` | — | Auto-generated |
| `NEGELIR_TELEMETRY_METRICS_PORT` | `9101` | — | Auto-generated |
| `NEGELIR_TELEMETRY_METRICS_BIND` | `127.0.0.1` | — | Auto-generated |
| `NEGELIR_REACTOR_MAX_EVENT_AGE_SEC` | `86400` | — | Auto-generated |
| `NEGELIR_REACTOR_LEDGER_MAX_SIZE` | `100000` | — | Auto-generated |
| `NEGELIR_CONSENSUS_WINDOW_MS` | `750` | — | Auto-generated |
| `NEGELIR_CONSENSUS_MIN_CONFIDENCE` | `0.0` | — | Auto-generated |
| `NEGELIR_CONSENSUS_MIN_VOTERS` | `3` | — | Auto-generated |
| `NEGELIR_CONSENSUS_BRIER_WINDOW` | `200` | — | Auto-generated |
| `NEGELIR_CONSENSUS_MAX_PENDING` | `4096` | — | Auto-generated |
| `NEGELIR_CONSENSUS_OVERFLOW_FLAG_MIN_INTERVAL_SEC` | `10` | — | Auto-generated |
| `NEGELIR_PREDICTOR_MARKET_FEATURES_ENABLED` | `false` | — | Auto-generated |
| `NEGELIR_PREDICTOR_MAX_VRAM_MB` | `1024` | — | Auto-generated |
| `NEGELIR_TRAINER_DEBOUNCE_SEC` | `300` | — | Auto-generated |
| `NEGELIR_BACKTEST_SWARM_FLOOR_PCT` | `0.01` | — | Auto-generated |
| `NEGELIR_BACKTEST_WINDOW_WEEKS` | `12` | — | Auto-generated |
| `NEGELIR_BACKTEST_MIN_N` | `20` | — | Auto-generated |
| `NEGELIR_API_CONSENSUS_OVERHEAD_MS` | `250` | — | Auto-generated |
| `NEGELIR_PROOFREADER_QUORUM_WINDOW_MS` | `200` | — | Auto-generated |
| `NEGELIR_SOURCE_WATCHER_SUMMARIZER_ENABLED` | `false` | — | Auto-generated |
| `NEGELIR_SOURCE_WATCHER_SUMMARIZER_MODEL_ID` | `""` | — | Auto-generated |
| `NEGELIR_SOURCE_WATCHER_SUMMARIZER_PROBE_URL` | `""` | — | Auto-generated |
| `NEGELIR_SOURCE_WATCHER_SUMMARIZER_PROBE_TIMEOUT_SEC` | `2.0` | — | Auto-generated |
| `NEGELIR_SOURCE_WATCHER_SUMMARIZER_MAX_TOKENS_PER_CALL` | `4096` | — | Auto-generated |
| `NEGELIR_SOURCE_WATCHER_SUMMARIZER_MAX_TOKENS_PER_DAY` | `50000` | — | Auto-generated |
| `NEGELIR_SOURCE_WATCHER_SUMMARIZER_LEDGER_PATH` | `data/maint/summarizer_ledger.json` | — | Auto-generated |
| `NEGELIR_SEC_INPUT_MAX_LEN` | `8192` | — | Auto-generated |
| `NEGELIR_SEC_INPUT_GATEWAY_MAX_LATENCY_MS` | `10` | — | Auto-generated |
| `NEGELIR_SEC_INPUT_CLASSIFIER_MAX_LATENCY_MS` | `100` | — | Auto-generated |
| `NEGELIR_SEC_INPUT_CLASSIFIER_BATCH_SIZE` | `8` | — | Auto-generated |
| `NEGELIR_SEC_INPUT_CLASSIFIER_BATCH_WINDOW_MS` | `20` | — | Auto-generated |
| `NEGELIR_SEC_INPUT_CLASSIFIER_MAX_PENDING` | `256` | — | Auto-generated |
| `NEGELIR_SEC_INPUT_BREAKER_OPEN_S` | `30` | — | Auto-generated |
| `NEGELIR_SEC_INPUT_PATTERN_RELOAD_S` | `30` | — | Auto-generated |
| `NEGELIR_SEC_INPUT_ALLOWLIST_HMAC_KEY_PATH` | `/var/lib/negelir/secrets/allowlist_hmac.key` | — | Auto-generated |
| `NEGELIR_SEC_INPUT_ALLOWLIST_HMAC_KEY_MAX_AGE_DAYS` | `365` | — | Auto-generated |
| `NEGELIR_SEC_QUARANTINE_TTL_DAYS` | `30` | — | Auto-generated |
| `NEGELIR_SEC_QUARANTINE_PRODUCER_QUEUE_MAX` | `1000` | — | Auto-generated |
| `NEGELIR_SEC_QUARANTINE_STORAGE_LAG_ALERT_MS` | `5000` | — | Auto-generated |
| `NEGELIR_SEC_SCRAPE_SIZE_DELTA_PCT` | `200.0` | — | Auto-generated |
| `NEGELIR_SEC_SCRAPE_INFLATE_RATIO_MAX` | `50.0` | — | Auto-generated |
| `NEGELIR_SEC_SCRAPE_WARMUP_SAMPLES` | `50` | — | Auto-generated |
| `NEGELIR_SEC_SCRAPE_BASELINE_FLUSH_S` | `300` | — | Auto-generated |
| `NEGELIR_SEC_SCRAPE_MAX_PENDING` | `4096` | — | Auto-generated |
| `NEGELIR_SEC_SCRAPE_DEDUP_WINDOW` | `4096` | — | Auto-generated |
| `NEGELIR_SEC_SCRAPE_DOM_FINGERPRINT_MAX_NODES` | `5000` | — | Auto-generated |
| `NEGELIR_SEC_SCRAPE_SIMHASH_RING_SIZE` | `8` | — | Auto-generated |
| `NEGELIR_SEC_RATE_PRE_AUTH_CAPACITY` | `30` | — | Auto-generated |
| `NEGELIR_SEC_RATE_PRE_AUTH_REFILL_PER_S` | `0.5` | — | Auto-generated |
| `NEGELIR_SEC_RATE_POST_AUTH_CAPACITY` | `600` | — | Auto-generated |
| `NEGELIR_SEC_RATE_POST_AUTH_REFILL_PER_S` | `5.0` | — | Auto-generated |
| `NEGELIR_SEC_RATE_BUCKET_IDLE_TTL_S` | `3600` | — | Auto-generated |
| `NEGELIR_SEC_RATE_MAX_SUBJECTS` | `100000` | — | Auto-generated |
| `NEGELIR_SEC_RATE_IPV4_PREFIX` | `32` | — | Auto-generated |
| `NEGELIR_SEC_RATE_IPV6_PREFIX` | `64` | — | Auto-generated |
| `NEGELIR_SEC_RATE_REDIS_TIMEOUT_MS` | `50` | — | Auto-generated |
| `NEGELIR_SEC_RATE_SECONDARY_CAPACITY` | `300` | — | Auto-generated |
| `NEGELIR_SEC_RATE_SECONDARY_REFILL_PER_S` | `5.0` | — | Auto-generated |
| `NEGELIR_SEC_RATE_DEFAULT_COST` | `1` | — | Auto-generated |
| `NEGELIR_SEC_RATE_EVICTION_RATE_ALERT_PER_S` | `50.0` | — | Auto-generated |
| `NEGELIR_SEC_RATE_EVICTION_RATE_WINDOW_S` | `60` | — | Auto-generated |
| `NEGELIR_SEC_BURST_THRESHOLD` | `100` | — | Auto-generated |
| `NEGELIR_SEC_BURST_WINDOW_MS` | `60000` | — | Auto-generated |
| `NEGELIR_SEC_BURST_DEDUP_WINDOW` | `10000` | — | Auto-generated |
| `NEGELIR_SEC_DENYLIST_TTL_S` | `3600` | — | Auto-generated |
| `NEGELIR_SEC_DENYLIST_ESCALATION_FACTOR` | `2.0` | — | Auto-generated |
| `NEGELIR_SEC_DENYLIST_MAX_ENTRIES` | `250000` | — | Auto-generated |
| `NEGELIR_SEC_ALERT_DEBOUNCE_TTL_S` | `60` | — | Auto-generated |
| `NEGELIR_SEC_ALERT_CRITICAL_DEBOUNCE_ENABLED` | `false` | — | Auto-generated |
| `NEGELIR_SEC_ALERT_DEBOUNCER_MAX_BUCKETS` | `4096` | — | Auto-generated |
| `NEGELIR_QA_REQUEST_V1_DEDUP_WINDOW_S` | `300` | — | Auto-generated |
| `NEGELIR_NLP_INPUT_MAX_CODEPOINTS` | `512` | — | Auto-generated |
| `NEGELIR_NLP_COLLAPSE_UNICODE_SPACES` | `true` | — | Auto-generated |
| `NEGELIR_NLP_REQUEST_DEDUP_WINDOW_S` | `330` | — | Auto-generated |
| `NEGELIR_NLP_FAIRNESS_KEY` | `account_id` | — | Auto-generated |
| `NEGELIR_NLP_PER_TENANT_INFLIGHT_MAX` | `8` | — | Auto-generated |
| `NEGELIR_NLP_FAIRNESS_MAX_TRACKED_KEYS` | `10000` | — | Auto-generated |
| `NEGELIR_NLP_TENANT_ABUSE_QPS_THRESHOLD` | `10` | — | Auto-generated |
| `NEGELIR_NLP_TENANT_ABUSE_WINDOW_S` | `60` | — | Auto-generated |
| `NEGELIR_NLP_HYPOTHESIS_MAX_EXAMPLES` | `1000` | — | Auto-generated |
| `NEGELIR_NLP_SINGLEFLIGHT_SWEEP_INTERVAL_S` | `30` | — | Auto-generated |
| `NEGELIR_NLP_SINGLEFLIGHT_EVENT_MAX_AGE_S` | `60` | — | Auto-generated |
| `NEGELIR_NLP_SINGLEFLIGHT_MAX_INFLIGHT` | `2048` | — | Auto-generated |
| `NEGELIR_ADVERSARIAL_CORPUS_MAX_ADDED_ROWS_PER_QUARTER` | `500` | — | Auto-generated |
| `NEGELIR_FUZZ_NIGHTLY_BUDGET_S` | `600` | — | Auto-generated |
| `NEGELIR_NLP_BUS_FAILURE_CIRCUIT_THRESHOLD` | `3` | — | Auto-generated |
| `NEGELIR_NLP_SPOOL_MAX_ENTRIES` | `1000` | — | Auto-generated |
| `NEGELIR_NLP_AGENT_SPOOL_DIR` | `"data/nlp/spool"` | — | Auto-generated |
| `NEGELIR_NLP_SPOOL_PAYLOAD_PII_STRIP` | `true` | — | Auto-generated |
| `NEGELIR_NLP_PIPELINE_TIMEOUT_MS` | `1800` | — | Auto-generated |
| `NEGELIR_NLP_DISPATCH_OVERHEAD_MS` | `200` | — | Auto-generated |
| `NEGELIR_NLP_CONSENSUS_OVERHEAD_MS` | `100` | — | Auto-generated |
| `NEGELIR_NLP_HUMANIZER_MAX_LATENCY_MS` | `600` | — | Auto-generated |
| `NEGELIR_NLP_HUMANIZER_BREAKER_OPEN_S` | `60` | — | Auto-generated |
| `NEGELIR_NLP_HUMANIZE` | `false` | — | Auto-generated |
| `NEGELIR_NLP_HUMANIZER_MAX_NEW_TOKENS` | `120` | — | Auto-generated |
| `NEGELIR_NLP_MAX_HUMANIZER_TOKENS_PER_REQUEST` | `120` | — | Auto-generated |
| `NEGELIR_NLP_MAX_HUMANIZER_TOKENS_PER_TENANT_PER_MIN` | `2400` | — | Auto-generated |
| `NEGELIR_NLP_HUMANIZER_REQUEST_RATE` | `0.6` | — | Auto-generated |
| `NEGELIR_NLP_HUMANIZER_BUDGET_REDIS_KEY_PREFIX` | `"nlp:humanizer:budget:"` | — | Auto-generated |
| `NEGELIR_NLP_TIER_HUMANIZER_TOKENS_PER_MIN` | `{}` | — | Auto-generated |
| `NEGELIR_NLP_MAX_HUMANIZER_TOKENS_PER_POD_PER_HOUR` | `720000` | — | Auto-generated |
| `NEGELIR_NLP_HUMANIZER_POD_COOLDOWN_S` | `300` | — | Auto-generated |
| `NEGELIR_NLP_HUMANIZER_TEMPERATURE` | `0.3` | — | Auto-generated |
| `NEGELIR_NLP_HUMANIZER_TOP_P` | `0.9` | — | Auto-generated |
| `NEGELIR_NLP_HUMANIZER_REPETITION_PENALTY` | `1.05` | — | Auto-generated |
| `NEGELIR_NLP_HUMANIZER_MAX_EDIT_RATIO` | `0.6` | — | Auto-generated |
| `NEGELIR_NLP_HUMANIZER_BREAKER_SCOPE` | `pod` | — | Auto-generated |
| `NEGELIR_NLP_PER_TENANT_HUMANIZER_BURST` | `4` | — | Auto-generated |
| `NEGELIR_NLP_PER_TENANT_HUMANIZER_REFILL_PER_S` | `2.0` | — | Auto-generated |
| `NEGELIR_NLP_BENCH_LATENCY_P95_THRESHOLD_MS` | `5` | — | Auto-generated |
| `NEGELIR_NLP_LEXICON_RELOAD_S` | `30` | — | Auto-generated |
| `NEGELIR_NLP_REPAIR_DENSITY_P95_MAX` | `0.5` | — | Auto-generated |
| `NEGELIR_NLP_LANG_TR_DIR` | `"ai/nlp/lang_tr"` | — | Auto-generated |
| `NEGELIR_NLP_LANG_TR_RELOAD_S` | `30` | — | Auto-generated |
| `NEGELIR_NLP_LEXICON_MAX_ENTRIES_PER_FILE` | `50000` | — | Auto-generated |
| `NEGELIR_NLP_LEXICON_MAX_ALIASES_PER_CANONICAL` | `12` | — | Auto-generated |
| `NEGELIR_NLP_LEXICON_MAX_RSS_MB` | `128` | — | Auto-generated |
| `NEGELIR_NLP_LEXICON_MAX_OLD_GENERATIONS` | `2` | — | Auto-generated |
| `NEGELIR_NLP_LEXICON_SWAP_ATOMICITY` | `all_or_nothing` | — | Auto-generated |
| `NEGELIR_NLP_LEXICON_SWAP_GRACE_S` | `120` | — | Auto-generated |
| `NEGELIR_NLP_LEXICON_SWAP_MAX_LAG_S` | `600` | — | Auto-generated |
| `NEGELIR_NLP_PREVIEW_DIR` | `"data/nlp/preview"` | — | Auto-generated |
| `NEGELIR_NLP_COMPLAINT_TRACE_DIR` | `"data/nlp/complaint_traces"` | — | Auto-generated |
| `NEGELIR_NLP_COMPLAINT_TRACE_DEFAULT_WINDOW_H` | `24` | — | Auto-generated |
| `NEGELIR_NLP_ABUSE_WINDOW_H` | `168` | — | Auto-generated |
| `NEGELIR_NLP_ABUSE_DYM_ACCEPTANCE_ANOMALY_RATIO` | `4.0` | — | Auto-generated |
| `NEGELIR_NLP_ABUSE_STYLE_SHIFT_KL` | `0.6` | — | Auto-generated |
| `NEGELIR_NLP_ABUSE_SHADOW_CONCENTRATION_DISTINCT_BUCKETS_MIN` | `5` | — | Auto-generated |
| `NEGELIR_NLP_ABUSE_ACCOUNT_FARM_JACCARD_MIN` | `0.5` | — | Auto-generated |
| `NEGELIR_NLP_ABUSE_ACCOUNT_FARM_ACCOUNT_COUNT_MIN` | `100` | — | Auto-generated |
| `NEGELIR_NLP_INTENT_TRAIN_MAX_ROWS_PER_SUBJECT_BUCKET` | `500` | — | Auto-generated |
| `NEGELIR_NLP_QA_ANSWER_MIN_SUPPORTED_VERSION` | `1` | — | Auto-generated |
| `NEGELIR_NLP_LEXICON_FEED_MAX_SUPPORTED_SCHEMA_VERSION` | `1` | — | Auto-generated |
| `NEGELIR_NLP_CRF_MAX_RSS_MB` | `5` | — | Auto-generated |
| `NEGELIR_NLP_SYMSPELL_MAX_RSS_MB` | `100` | — | Auto-generated |
| `NEGELIR_NLP_JINJA_CACHE_MAX_RSS_MB` | `50` | — | Auto-generated |
| `NEGELIR_NLP_PYTHON_OVERHEAD_MB` | `200` | — | Auto-generated |
| `NEGELIR_NLP_HUMANIZER_MAX_RSS_MB` | `1024` | — | Auto-generated |
| `NEGELIR_NLP_POD_RSS_MAX_MB` | `2048` | — | Auto-generated |
| `NEGELIR_NLP_TYPO_MAX_EDIT_DISTANCE` | `2` | — | Auto-generated |
| `NEGELIR_NLP_TYPO_MAX_LOOKUPS_PER_QUERY` | `8` | — | Auto-generated |
| `NEGELIR_NLP_ASR_FILLER_STRIP_MAX` | `6` | — | Auto-generated |
| `NEGELIR_NLP_DIACRITIC_TIE_BREAK_RATIO` | `1.5` | — | Auto-generated |
| `NEGELIR_NLP_DIACRITIC_HARD_CALL_MIN_FREQ` | `10000` | — | Auto-generated |
| `NEGELIR_NLP_DIACRITIC_MAX_RISK_PER_TOKEN` | `2.5` | — | Auto-generated |
| `NEGELIR_NLP_ASCII_VS_RESTORED_MARGIN` | `0.2` | — | Auto-generated |
| `NEGELIR_NLP_NORMALIZE_STAGE_TIMEOUT_MS` | `20` | — | Auto-generated |
| `NEGELIR_NLP_NORMALIZE_TOTAL_BUDGET_P99_MS` | `12` | — | Auto-generated |
| `NEGELIR_NLP_MATCH_SEPARATOR_PATTERN` | `'^(-|–|—|vs\.?|x|×|/)$'` | — | Auto-generated |
| `NEGELIR_NLP_INTENT_MODEL_PATH` | `"data/models/nlp/intent.tr.bin"` | — | Auto-generated |
| `NEGELIR_NLP_INTENT_MODEL_SHA256` | `""` | — | Auto-generated |
| `NEGELIR_NLP_INTENT_MODEL_MAX_SIZE_MB` | `20` | — | Auto-generated |
| `NEGELIR_NLP_INTENT_CALIBRATION_PATH` | `""` | — | Auto-generated |
| `NEGELIR_NLP_MIN_INTENT_CONF` | `0.55` | — | Auto-generated |
| `NEGELIR_NLP_INTENT_ACCURACY_FLOOR` | `0.92` | — | Auto-generated |
| `NEGELIR_NLP_INTENT_DRIFT_WINDOW` | `1000` | — | Auto-generated |
| `NEGELIR_NLP_ENTITY_F1_FLOOR` | `0.90` | — | Auto-generated |
| `NEGELIR_NLP_INTENT_MODEL_VERSION` | `""` | — | Auto-generated |
| `NEGELIR_NLP_NUMPY_PIN` | `""` | — | Auto-generated |
| `NEGELIR_NLP_FASTTEXT_PIN` | `""` | — | Auto-generated |
| `NEGELIR_NLP_INTENT_CACHE_MAX_ENTRIES` | `10000` | — | Auto-generated |
| `NEGELIR_NLP_INTENT_CACHE_TTL_S` | `300` | — | Auto-generated |
| `NEGELIR_NLP_POD_ID` | `"local"` | — | Auto-generated |
| `NEGELIR_NLP_ANSWER_CACHE_TTL_DATA_S` | `120` | — | Auto-generated |
| `NEGELIR_NLP_ANSWER_CACHE_TTL_PREDICT_S` | `60` | — | Auto-generated |
| `NEGELIR_NLP_L0_CACHE_TTL_S` | `300` | — | Auto-generated |
| `NEGELIR_NLP_L1_ANSWER_CACHE_TTL_S` | `600` | — | Auto-generated |
| `NEGELIR_NLP_ENTITY_KIND_PRIORITY` | `"team,player,league,competition,market,date,time,weekday,ordinal,money_amount,score"` | — | Auto-generated |
| `NEGELIR_NLP_ENTITY_CRF_MODEL_PATH` | `""` | — | Auto-generated |
| `NEGELIR_NLP_ENTITY_CRF_MODEL_SHA256` | `""` | — | Auto-generated |
| `NEGELIR_NLP_ENTITY_CRF_MODEL_MAX_SIZE_MB` | `5` | — | Auto-generated |
| `NEGELIR_NLP_ENTITY_BENCH_LATENCY_P95_THRESHOLD_MS` | `8` | — | Auto-generated |
| `NEGELIR_NLP_DEFAULT_FIXTURE_WINDOW_H` | `48` | — | Auto-generated |
| `NEGELIR_NLP_SUMMARY_MAX_FIXTURES` | `10` | — | Auto-generated |
| `NEGELIR_NLP_SUMMARY_AGGREGATION_TIMEOUT_MS` | `1500` | — | Auto-generated |
| `NEGELIR_NLP_SUMMARY_CALIBRATION_MISMATCH_POLICY` | `note` | — | Auto-generated |
| `NEGELIR_NLP_DISPATCH_DEDUP_WINDOW_S` | `600` | — | Auto-generated |
| `NEGELIR_NLP_INTENT_TIER_MAP` | `"{}"` | — | Auto-generated |
| `NEGELIR_NLP_CONFIDENCE_BANDS` | `'[[0.0,0.55,"düşük"],[0.55,0.75,"orta"],[0.75,1.01,"yüksek"]]'` | — | Auto-generated |
| `NEGELIR_NLP_DEFAULT_LOCALE` | `"tr-TR"` | — | Auto-generated |
| `NEGELIR_NLP_LOCALE_FALLBACK_CHAIN` | `'["tr-TR"]'` | — | Auto-generated |
| `NEGELIR_API_BURST_CAPACITY` | `60` | — | Auto-generated |
| `NEGELIR_API_BURST_REFILL_PER_S` | `2.0` | — | Auto-generated |
| `NEGELIR_API_REQUEST_TIMEOUT_MS` | `2500` | — | Auto-generated |
| `NEGELIR_API_CONSENSUS_OVERHEAD_MS` | `200` | — | Auto-generated |
| `NEGELIR_API_TRANSIT_JITTER_MS` | `100` | — | Auto-generated |
| `NEGELIR_API_REQUEST_MAX_BYTES` | `65536` | — | Auto-generated |
| `NEGELIR_QA_INPUT_MAX_BYTES` | `4096` | — | Auto-generated |
| `NEGELIR_API_FIXTURE_WINDOW_MAX_DAYS` | `14` | — | Auto-generated |
| `NEGELIR_API_ALLOWED_MARKETS` | `"ms,au_2.5,btts,ah_home,modal_score"` | — | Auto-generated |
| `NEGELIR_API_CURSOR_TTL_S` | `1800` | — | Auto-generated |
| `NEGELIR_API_IDEMPOTENCY_TTL_S` | `86400` | — | Auto-generated |
| `NEGELIR_API_IDEMPOTENCY_INFLIGHT_WAIT_MS` | `1500` | — | Auto-generated |
| `NEGELIR_API_SWR_INFLIGHT_MAX` | `64` | — | Auto-generated |
| `NEGELIR_API_CACHE_STALE_AFTER_S` | `30` | — | Auto-generated |
| `NEGELIR_API_CACHE_MAX_AGE_S` | `300` | — | Auto-generated |
| `NEGELIR_API_REPLY_REAPER_S` | `60` | — | Auto-generated |
| `NEGELIR_API_PREDICT_REQUEST_BACKLOG_HIGH` | `5000` | — | Auto-generated |
| `NEGELIR_API_MAX_CONCURRENT_REQUESTS` | `5000` | — | Auto-generated |
| `NEGELIR_API_RESPONSE_WRITE_TIMEOUT_MS` | `5000` | — | Auto-generated |
| `NEGELIR_API_BCRYPT_COST` | `12` | — | Auto-generated |
| `NEGELIR_API_ACCESS_TTL_S` | `900` | — | Auto-generated |
| `NEGELIR_API_REFRESH_TTL_S` | `2592000` | — | Auto-generated |
| `NEGELIR_API_REFRESH_REPLAY_GRACE_S` | `30` | — | Auto-generated |
| `NEGELIR_API_REVOCATION_SET_MAX` | `10000` | — | Auto-generated |
| `NEGELIR_API_JWT_KEY_POLL_S` | `10` | — | Auto-generated |
| `NEGELIR_API_JWT_RETIRED_GRACE_S` | `960` | — | Auto-generated |
| `NEGELIR_API_JWT_CLOCK_SKEW_S` | `30` | — | Auto-generated |
| `NEGELIR_API_SELF_REGISTRATION_ENABLED` | `false` | — | Auto-generated |
| `NEGELIR_API_REGISTER_CAP_PER_SUBNET_PER_H` | `20` | — | Auto-generated |
| `NEGELIR_API_TRUSTED_PROXIES` | `""` | — | Auto-generated |
| `NEGELIR_API_LOG_SAMPLE_PCT` | `10` | — | Auto-generated |
| `NEGELIR_API_TIER_ENFORCEMENT_ENABLED` | `false` | — | Auto-generated |
| `NEGELIR_API_DEPRECATION_WINDOW_DAYS` | `90` | — | Auto-generated |
| `NEGELIR_API_SCHEMA_VERSION` | `1` | — | Auto-generated |
| `NEGELIR_API_SLO_BURN_WINDOW_S` | `3600` | — | Auto-generated |
| `NEGELIR_API_SLO_BURN_THRESHOLD` | `2.0` | — | Auto-generated |
| `NEGELIR_API_TIME_FORMAT` | `"iso8601_utc"` | — | Auto-generated |
| `NEGELIR_API_DEMO_BASE_URL` | `"http://localhost:8080"` | — | Auto-generated |
| `NEGELIR_API_GO_MEM_LIMIT_MIB` | `0` | — | Auto-generated |
| `NEGELIR_API_GO_GC_PERCENT` | `50` | — | Auto-generated |
| `NEGELIR_API_READ_HEADER_TIMEOUT_MS` | `5000` | — | Auto-generated |
| `NEGELIR_API_READ_TIMEOUT_MS` | `10000` | — | Auto-generated |
| `NEGELIR_API_WRITE_TIMEOUT_MS` | `15000` | — | Auto-generated |
| `NEGELIR_API_IDLE_TIMEOUT_MS` | `60000` | — | Auto-generated |
| `NEGELIR_API_SHUTDOWN_GRACE_S` | `30` | — | Auto-generated |
| `NEGELIR_API_IN_MESH_PORT` | `"8082"` | — | Auto-generated |
| `NEGELIR_API_PG_POOL_MAX_CONNS` | `25` | — | Auto-generated |
| `NEGELIR_API_PG_REPLICA_URL` | `""` | — | Auto-generated |
| `NEGELIR_API_PG_REPLICA_LAG_CHECK_S` | `10` | — | Auto-generated |
| `NEGELIR_API_PG_REPLICA_LAG_MAX_MS` | `500` | — | Auto-generated |
| `NEGELIR_API_REDIS_CACHE_POOL_SIZE` | `50` | — | Auto-generated |
| `NEGELIR_API_REDIS_BUS_POOL_SIZE` | `20` | — | Auto-generated |
| `NEGELIR_API_BREAKER_FAIL_RATIO` | `0.5` | — | Auto-generated |
| `NEGELIR_API_BREAKER_WINDOW_S` | `10` | — | Auto-generated |
| `NEGELIR_API_BREAKER_MIN_REQUESTS` | `20` | — | Auto-generated |
| `NEGELIR_API_BREAKER_OPEN_S` | `15` | — | Auto-generated |
| `NEGELIR_API_HEDGE_AFTER_MS` | `200` | — | Auto-generated |
| `NEGELIR_API_HEDGING_ENABLED` | `true` | — | Auto-generated |
| `NEGELIR_API_HEDGE_BUDGET_PCT` | `10` | — | Auto-generated |
| `NEGELIR_API_RETRY_BUDGET_PER_S` | `10` | — | Auto-generated |
| `NEGELIR_API_RETRY_BUDGET_CAPACITY` | `50` | — | Auto-generated |
| `NEGELIR_API_BENCH_TARGET_RPS` | `200` | — | Auto-generated |
| `NEGELIR_API_L0_CACHE_MAX_ENTRIES` | `10000` | — | Auto-generated |
| `NEGELIR_API_L0_CACHE_MAX_BYTES` | `67108864` | — | Auto-generated |
| `NEGELIR_API_L0_MAX_TTL_S` | `5` | — | Auto-generated |
| `NEGELIR_API_NEGATIVE_CACHE_S` | `10` | — | Auto-generated |
| `NEGELIR_API_L0_REFRESH_MAX_WAIT_MS` | `200` | — | Auto-generated |
| `NEGELIR_API_L0_INVALIDATION_LAG_MAX_MS` | `500` | — | Auto-generated |
| `NEGELIR_API_AUDIT_BATCH_MAX` | `64` | — | Auto-generated |
| `NEGELIR_API_AUDIT_BATCH_MAX_MS` | `10` | — | Auto-generated |
| `NEGELIR_API_AUDIT_CHAN_CAP` | `4096` | — | Auto-generated |
| `NEGELIR_API_AUDIT_SAMPLE_PCT_UNDER_PRESSURE` | `10` | — | Auto-generated |
| `NEGELIR_API_TCP_USER_TIMEOUT_MS` | `20000` | — | Auto-generated |
| `NEGELIR_API_ADAPTIVE_ERROR_RATE_THRESHOLD` | `0.02` | — | Auto-generated |
| `NEGELIR_API_ADAPTIVE_SHED_FACTOR` | `0.5` | — | Auto-generated |
| `NEGELIR_API_ADAPTIVE_SHED_DURATION_S` | `60` | — | Auto-generated |
| `NEGELIR_API_PRIORITY_TIER_FLOOR` | `0` | — | Auto-generated |
| `NEGELIR_API_PPROF_ENABLED_DEV` | `true` | — | Auto-generated |
| `NEGELIR_API_PPROF_ENABLED_PROD` | `false` | — | Auto-generated |
| `NEGELIR_API_ALLOC_SAMPLE_RATE` | `0.001` | — | Auto-generated |
| `NEGELIR_API_PPROF_DIR` | `"data/api/profiles"` | — | Auto-generated |
| `NEGELIR_OPSCTL_ACK_TIMEOUT_MS` | `5000` | — | Auto-generated |
| `NEGELIR_OPSCTL_ACK_TIMEOUT_MS_LIVE_DEMO` | `1000` | — | Auto-generated |
| `NEGELIR_OPSCTL_SPOOL_MAX_ENTRIES` | `1024` | — | Auto-generated |
| `NEGELIR_OPSCTL_NLP_KILL_MAX_TTL_S` | `3600` | — | Auto-generated |
| `NEGELIR_OPSCTL_CRITICAL_AGENTS` | `"consensus.v1,sec.rate.v1,maint.backup.v1"` | — | Auto-generated |
| `NEGELIR_OPSCTL_AUDIT_PATH` | `""` | — | Auto-generated |
| `NEGELIR_OPSCTL_SPOOL_DIR` | `""` | — | Auto-generated |
| `NEGELIR_OPSCTL_LOCK_DIR` | `""` | — | Auto-generated |
| `NEGELIR_OPSCTL_LOCK_STALE_FACTOR` | `2` | — | Auto-generated |
| `NEGELIR_OPSCTL_SPOOL_ACK_MAX_WAIT_H` | `24` | — | Auto-generated |
| `NEGELIR_OPSCTL_SPOOL_FLUSH_MAX_PER_RUN` | `100` | — | Auto-generated |
| `NEGELIR_MAINT_ACK_PAYLOAD_MAX_BYTES` | `4096` | — | Auto-generated |
| `NEGELIR_MAINT_ACK_REASON_MAX_BYTES` | `512` | — | Auto-generated |
| `NEGELIR_MAINT_ACK_DETAILS_MAX_BYTES` | `2048` | — | Auto-generated |
| `NEGELIR_OPSCTL_REDIS_EXPECTED_USER` | `negelir_opsctl` | — | Auto-generated |
| `NEGELIR_OPSCTL_REQUIRE_SIGNATURE` | `true` | — | Auto-generated |
| `NEGELIR_OPSCTL_KEY_PATH` | `""` | — | Auto-generated |
| `NEGELIR_OPSCTL_OPERATORS_FILE` | `""` | — | Auto-generated |
| `NEGELIR_OPSCTL_AUTHZ_FILE` | `""` | — | Auto-generated |
| `NEGELIR_OPSCTL_KEY_REVOCATION_GRACE_S` | `60` | — | Auto-generated |
| `NEGELIR_OPSCTL_KEY_MAX_AGE_DAYS` | `365` | — | Auto-generated |
| `NEGELIR_OPSCTL_KEY_REVOCATION_GRACE_DAYS` | `30` | — | Auto-generated |
| `NEGELIR_OPSCTL_OPERATORS_RELOAD_S` | `60` | — | Auto-generated |
| `NEGELIR_OPSCTL_KILL_SWITCH_PATH` | `""` | — | Auto-generated |
| `NEGELIR_OPSCTL_KILL_SWITCH_MAX_AGE_H` | `24` | — | Auto-generated |
| `NEGELIR_OPSCTL_KEY_RATE_LIMIT_PER_MIN` | `30` | — | Auto-generated |
| `NEGELIR_MAINT_SCALER_DECISION_WINDOW_MS` | `30000` | — | Auto-generated |
| `NEGELIR_MAINT_SCALER_CLOCK_SOURCE` | `auto` | — | Auto-generated |
| `NEGELIR_MAINT_CLOCK_SUSPEND_ALERT_S` | `30` | — | Auto-generated |
| `NEGELIR_MAINT_SCALER_MAX_TARGETS` | `256` | — | Auto-generated |
| `NEGELIR_MAINT_SCALER_MAX_REPLICAS` | `16` | — | Auto-generated |
| `NEGELIR_MAINT_SCALER_DEFAULT_MAX_REPLICAS` | `0` | — | Auto-generated |
| `NEGELIR_MAINT_SCALER_MIN_REPLICAS` | `1` | — | Auto-generated |
| `NEGELIR_MAINT_SCALER_SCALE_UP_QUEUE_DEPTH` | `50` | — | Auto-generated |
| `NEGELIR_MAINT_SCALER_SCALE_DOWN_QUEUE_DEPTH` | `5` | — | Auto-generated |
| `NEGELIR_MAINT_SCALER_SCALE_UP_HEAD_AGE_S` | `30` | — | Auto-generated |
| `NEGELIR_MAINT_SCALER_HYSTERESIS_WINDOWS` | `3` | — | Auto-generated |
| `NEGELIR_MAINT_SCALER_HYSTERESIS_GRACE` | `1` | — | Auto-generated |
| `NEGELIR_MAINT_SCALER_MAX_CHANGES_PER_WINDOW` | `4` | — | Auto-generated |
| `NEGELIR_MAINT_SCALER_MANUAL_PIN_TTL_S` | `1800` | — | Auto-generated |
| `NEGELIR_MAINT_SCALER_MAX_REPLICAS_OVERRIDES_CSV` | `""` | — | Auto-generated |
| `NEGELIR_MAINT_SCALER_WARMUP_REPLICAS` | `1` | — | Auto-generated |
| `NEGELIR_MAINT_SCALER_SELF_SCALING_TARGETS` | `"trainer.v1"` | — | Auto-generated |
| `NEGELIR_MAINT_SCALER_SIGNAL_WINDOW_SAMPLES` | `5` | — | Auto-generated |
| `NEGELIR_MAINT_SCALER_SCALE_DOWN_GRACE_WINDOWS` | `3` | — | Auto-generated |
| `NEGELIR_MAINT_SCALER_TARGET_LOAD_PER_REPLICA` | `25` | — | Auto-generated |
| `NEGELIR_MAINT_SCALER_MAX_STEP_PER_WINDOW` | `2` | — | Auto-generated |
| `NEGELIR_MAINT_SCALER_NOISE_WINDOWS` | `'["0 3-5 * * *","0 5 * * 0"]'` | — | Auto-generated |
| `NEGELIR_MAINT_RUNTIME` | `none` | — | Auto-generated |
| `NEGELIR_MAINT_SCALER_COMPOSE_FILE` | `docker-compose.yml` | — | Auto-generated |
| `NEGELIR_MAINT_SCALER_RUNTIME_TIMEOUT_S` | `30` | — | Auto-generated |
| `NEGELIR_MAINT_SCALER_GLOBAL_MAX_REPLICAS` | `64` | — | Auto-generated |
| `NEGELIR_MAINT_SCALER_MIN_DECISION_INTERVAL_S` | `90` | — | Auto-generated |
| `NEGELIR_MAINT_SCALER_VRAM_HEADROOM_MB` | `1024` | — | Auto-generated |
| `NEGELIR_MAINT_SCALER_VRAM_PESSIMISTIC_THRESHOLD_PCT` | `0.6` | — | Auto-generated |
| `NEGELIR_MAINT_SCALER_CPU_BUDGET_PCT` | `0.8` | — | Auto-generated |
| `NEGELIR_MAINT_SCALER_RUNTIME_HISTOGRAM_BUCKETS` | `"0.005,0.01,0.025,0.05,0.1,0.25,0.5,1.0,2.5,5.0,10.0"` | — | Auto-generated |
| `NEGELIR_MAINT_SCALER_HISTORY_MAX` | `1024` | — | Auto-generated |
| `NEGELIR_MAINT_LEADER_LEASE_DURATION_S` | `15` | — | Auto-generated |
| `NEGELIR_MAINT_DLQ_PER_TOPIC_QUOTA` | `100` | — | Auto-generated |
| `NEGELIR_MAINT_DLQ_REPLAY_BACKOFF_S` | `60` | — | Auto-generated |
| `NEGELIR_MAINT_DLQ_BACKOFF_LRU` | `1024` | — | Auto-generated |
| `NEGELIR_MAINT_DLQ_BACKOFF_FACTOR` | `2` | — | Auto-generated |
| `NEGELIR_MAINT_DLQ_STATE_MAX` | `100000` | — | Auto-generated |
| `NEGELIR_MAINT_DLQ_REPLAY_TOPICS_ALLOW_CSV` | `""` | — | Auto-generated |
| `NEGELIR_MAINT_DLQ_REPLAY_ALLOW_OVERRIDES` | `[]` | — | Auto-generated |
| `NEGELIR_MAINT_DLQ_VISIT_MAX` | `2` | — | Auto-generated |
| `NEGELIR_MAINT_DLQ_PER_TOPIC_MAX_PER_MIN` | `60` | — | Auto-generated |
| `NEGELIR_MAINT_DLQ_VISIT_LRU` | `4096` | — | Auto-generated |
| `NEGELIR_MAINT_DLQ_MAX_REPLAYS_PER_TICK` | `50` | — | Auto-generated |
| `NEGELIR_MAINT_DLQ_CONSUMER_BROKEN_THRESHOLD` | `5` | — | Auto-generated |
| `NEGELIR_MAINT_DLQ_CONSUMER_BROKEN_WINDOW_S` | `600` | — | Auto-generated |
| `NEGELIR_MAINT_DLQ_REPLAY_RPS` | `10` | — | Auto-generated |
| `NEGELIR_MAINT_DLQ_BACKLOG_ALERT` | `1000` | — | Auto-generated |
| `NEGELIR_MAINT_SCHEMA_SAMPLE_RATE_PER_S` | `5` | — | Auto-generated |
| `NEGELIR_MAINT_SCHEMA_BURST` | `10` | — | Auto-generated |
| `NEGELIR_MAINT_SCHEMA_DRIFT_DEBOUNCE_S` | `60` | — | Auto-generated |
| `NEGELIR_MAINT_SCHEMA_DRIFT_LRU` | `512` | — | Auto-generated |
| `NEGELIR_MAINT_SCHEMA_PG_CHECK_INTERVAL_S` | `3600` | — | Auto-generated |
| `NEGELIR_MAINT_SCHEMA_AUTO_APPLY_ENABLED` | `false` | — | Auto-generated |
| `NEGELIR_MAINT_SCHEMA_VALIDATE_MAX_RPS` | `50` | — | Auto-generated |
| `NEGELIR_MAINT_SEC_PATTERN_TTL_S` | `604800` | — | Auto-generated |
| `NEGELIR_MAINT_SEC_PATTERN_PROMOTE_THRESHOLD` | `1` | — | Auto-generated |
| `NEGELIR_MAINT_SEC_PATTERN_PENDING_TTL_DAYS` | `30` | — | Auto-generated |
| `NEGELIR_MAINT_SEC_REQUEST_LRU` | `2048` | — | Auto-generated |
| `NEGELIR_MAINT_SEC_DECIMATE_MIN_INTERVAL_S` | `300` | — | Auto-generated |
| `NEGELIR_MAINT_PAUSE_DEFAULT_TTL_S` | `600` | — | Auto-generated |
| `NEGELIR_MAINT_SILENCE_DEDUP_S` | `300` | — | Auto-generated |
| `NEGELIR_MAINT_SILENCE_ALERT_H` | `24` | — | Auto-generated |
| `NEGELIR_MAINT_SILENCE_WARMUP_S` | `3600` | — | Auto-generated |
| `NEGELIR_MAINT_SELF_DLQ_ALERT` | `100` | — | Auto-generated |
| `NEGELIR_MAINT_SELF_DLQ_THROTTLE_RECOVERY_S` | `120` | — | Auto-generated |
| `NEGELIR_MAINT_PLANE_LAG_ALERT_MS` | `5000` | — | Auto-generated |
| `NEGELIR_MAINT_PLANE_LAG_ALERT_WINDOW_S` | `60` | — | Auto-generated |
| `NEGELIR_SEC_PLANE_LAG_ALERT_MS` | `5000` | — | Auto-generated |
| `NEGELIR_SEC_PLANE_LAG_ALERT_WINDOW_S` | `60` | — | Auto-generated |
| `NEGELIR_MAINT_PLANE_RECOVERY_WINDOW_S` | `120` | — | Auto-generated |
| `NEGELIR_MAINT_BUS_FAIL_THRESHOLD` | `3` | — | Auto-generated |
| `NEGELIR_MAINT_BUS_FAIL_WINDOW_S` | `30.0` | — | Auto-generated |
| `NEGELIR_MAINT_BUS_SPOOL_MAX_ENTRIES` | `1024` | — | Auto-generated |
| `NEGELIR_MAINT_AGENT_SPOOL_DIR` | `"data/maint/agent_spool"` | — | Auto-generated |
| `NEGELIR_MAINT_BACKPRESSURE_YELLOW_FACTOR` | `4.0` | — | Auto-generated |
| `NEGELIR_MAINT_BACKPRESSURE_YELLOW_QUEUE_DEPTH` | `200` | — | Auto-generated |
| `NEGELIR_MAINT_BACKPRESSURE_YELLOW_HEAD_AGE_S` | `60` | — | Auto-generated |
| `NEGELIR_MAINT_BACKPRESSURE_YELLOW_STORAGE_PCT` | `75` | — | Auto-generated |
| `NEGELIR_MAINT_BACKPRESSURE_YELLOW_ERROR_RATE_PER_S` | `1` | — | Auto-generated |
| `NEGELIR_MAINT_BACKPRESSURE_RED_QUEUE_DEPTH` | `1000` | — | Auto-generated |
| `NEGELIR_MAINT_BACKPRESSURE_RED_HEAD_AGE_S` | `300` | — | Auto-generated |
| `NEGELIR_MAINT_BACKPRESSURE_RED_STORAGE_PCT` | `92` | — | Auto-generated |
| `NEGELIR_MAINT_BACKPRESSURE_RED_ERROR_RATE_PER_S` | `10` | — | Auto-generated |
| `NEGELIR_MAINT_STORAGE_TOTAL_MAX_MB` | `512` | — | Auto-generated |
| `NEGELIR_MAINT_SPOOL_ENTRY_MAX_AGE_H` | `168` | — | Auto-generated |
| `NEGELIR_SWARM_MIN_SUPPORTED_SCHEMA_VERSION` | `1` | — | Auto-generated |
| `NEGELIR_MAINT_ADVISORY_LOCK_MAX_HOLD_MS` | `5000` | — | Auto-generated |
| `NEGELIR_MAINT_AUDIT_HMAC_KEY_B64` | `""` | — | Auto-generated |
| `NEGELIR_MAINT_AUDIT_PARTITION_RETENTION_DAYS` | `365` | — | Auto-generated |
| `NEGELIR_AUDIT_CHAIN_HMAC_KEY_PATH` | `"/var/lib/negelir/secrets/audit_chain.key"` | — | Auto-generated |
| `NEGELIR_OPSCTL_AUDIT_MAX_BYTES (10 MB)` | `10485760` | — | Auto-generated |
| `NEGELIR_MAINT_AUDIT_ROW_MAX_BYTES` | `16384` | — | Auto-generated |
| `NEGELIR_MAINT_AUDIT_PER_KIND_DETAILS_MAX_BYTES` | `'{"dlq_escalated": 8192, "schema_drift_detected": 4096, "backup_dump_file_corrupted": 8192, "default": 2048}'` | — | Auto-generated |
| `NEGELIR_MAINT_BACKUP_CRON` | `"0 3 * * *"` | — | Auto-generated |
| `NEGELIR_MAINT_BACKUP_DIR` | `"./data/backups"` | — | Auto-generated |
| `NEGELIR_MAINT_BACKUP_RETENTION_DAYS` | `14` | — | Auto-generated |
| `NEGELIR_MAINT_BACKUP_RETENTION_WEEKS` | `4` | — | Auto-generated |
| `NEGELIR_MAINT_BACKUP_DRY_RUN` | `false` | — | Auto-generated |
| `NEGELIR_MAINT_BACKUP_MIN_FREE_GB` | `5` | — | Auto-generated |
| `NEGELIR_MAINT_BACKUP_MAX_SKEW_H` | `36` | — | Auto-generated |
| `NEGELIR_MAINT_BACKUP_AGE_ALERT_H` | `30` | — | Auto-generated |
| `NEGELIR_MAINT_BACKUP_CLOCK_STEP_BACK_ALERT_S` | `300` | — | Auto-generated |
| `NEGELIR_MAINT_BACKUP_CLOCK_STEP_FORWARD_ALERT_H` | `24` | — | Auto-generated |
| `NEGELIR_MAINT_BACKUP_PG_JOBS` | `2` | — | Auto-generated |
| `NEGELIR_MAINT_BACKUP_PRUNE_MAX_LOCK_MS` | `500` | — | Auto-generated |
| `NEGELIR_MAINT_SCHEMA_SNAPSHOT_RETENTION_DAYS` | `90` | — | Auto-generated |
| `NEGELIR_SWARM_DLQ_PG_RETENTION_DAYS` | `14` | — | Auto-generated |
| `NEGELIR_MAINT_AUDIT_RETENTION_DAYS` | `365` | — | Auto-generated |
| `NEGELIR_MAINT_BACKUP_PG_DSN` | `""` | — | Auto-generated |
| `NEGELIR_MAINT_BACKUP_AGE_RECIPIENTS_FILE` | `""` | — | Auto-generated |
| `NEGELIR_MAINT_BACKUP_ENCRYPTION_KEY_DIR` | `""` | — | Auto-generated |
| `NEGELIR_MAINT_BACKUP_MIN_DR_RECIPIENTS` | `2` | — | Auto-generated |
| `NEGELIR_MAINT_BACKUP_AGE_IDENTITY_FILE` | `""` | — | Auto-generated |
| `NEGELIR_MAINT_BACKUP_VERIFY_PG_IMAGE` | `"postgres:16-alpine"` | — | Auto-generated |
| `NEGELIR_MAINT_BACKUP_VERIFY_ORPHAN_TTL_H` | `6.0` | — | Auto-generated |
| `NEGELIR_MAINT_BACKUP_PII_EXCLUDED_COLUMNS` | `"quarantine_samples.raw_bytes_b64"` | — | Auto-generated |
| `NEGELIR_FAIL_SAFE_OFFSITE_OBJECT_LOCK_DISABLED` | `true` | — | Auto-generated |
| `NEGELIR_FAIL_SAFE_OFFSITE_RETENTION_NOT_APPLIED` | `true` | — | Auto-generated |
| `NEGELIR_FAIL_SAFE_OFFSITE_LOCK_NOT_ENFORCED` | `true` | — | Auto-generated |
| `NEGELIR_MAINT_BACKUP_OFFSITE_ENDPOINT` | `""` | — | Auto-generated |
| `NEGELIR_MAINT_BACKUP_OFFSITE_BUCKET` | `""` | — | Auto-generated |
| `NEGELIR_MAINT_BACKUP_OFFSITE_MULTIPART_THRESHOLD_MB` | `64` | — | Auto-generated |
| `NEGELIR_MAINT_BACKUP_OFFSITE_UPLOAD_TIMEOUT_H` | `6` | — | Auto-generated |
| `NEGELIR_MAINT_BACKUP_OFFSITE_RETENTION_DAYS` | `7` | — | Auto-generated |
| `NEGELIR_MAINT_BACKUP_OFFSITE_ACCESS_KEY_ID` | `""` | — | Auto-generated |
| `NEGELIR_MAINT_BACKUP_OFFSITE_SECRET_ACCESS_KEY_SECRET_REF` | `""` | — | Auto-generated |
| `NEGELIR_MAINT_BACKUP_OFFSITE_S3_REGION` | `"us-east-1"` | — | Auto-generated |
| `NEGELIR_MAINT_BACKUP_OFFSITE_RSYNC_HOST` | `""` | — | Auto-generated |
| `NEGELIR_MAINT_BACKUP_OFFSITE_RSYNC_DEST_PATH` | `""` | — | Auto-generated |
| `NEGELIR_MAINT_BACKUP_OFFSITE_RSYNC_SSH_KNOWN_HOSTS` | `""` | — | Auto-generated |
| `NEGELIR_MAINT_BACKUP_DR_DRILL_CSV` | `"data/backups/dr_drills.csv"` | — | Auto-generated |
| `NEGELIR_MAINT_BACKUP_DR_DRILL_ALERT_DAYS` | `100` | — | Auto-generated |
| `NEGELIR_MAINT_BACKUP_MODEL_REPRODUCIBILITY_WINDOW_H` | `24` | — | Auto-generated |
| `NEGELIR_MAINT_BACKUP_MODEL_OFFSITE_RETENTION_DAYS` | `30` | — | Auto-generated |
| `NEGELIR_MAINT_BACKUP_MODEL_LINEAGE_MISSING_DEBOUNCE_H` | `24` | — | Auto-generated |
| `DATA_DIR` | `/data` | — | Auto-generated |
| `MODEL_DIR` | `/data/models` | — | Auto-generated |
| `NEGELIR_REPORT_DIR` | `/data/reports` | — | Auto-generated |
| `NEGELIR_THRESHOLD_MODEL_ACC` | `0.50` | — | Auto-generated |
| `NEGELIR_THRESHOLD_HOLDOUT_ACC` | `0.50` | — | Auto-generated |
| `NEGELIR_THRESHOLD_QUARANTINE_MAX` | `0.10` | — | Auto-generated |
| `NEGELIR_THRESHOLD_MIN_HOLDOUT_MATCHES` | `5` | — | Auto-generated |
| `NEGELIR_VERIFICATION_WINDOW_WEEKS` | `4` | — | Auto-generated |
<!-- END GENERATED -->
