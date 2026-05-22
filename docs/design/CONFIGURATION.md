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
| `NEGELIR_` | shared (Python + Go) | `NEGELIR_DEFAULT_LEAGUE_ID` |
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
- Strict mode (`NEGELIR_STRICT=1`) refuses unknown keys with our prefixes — catches typos and stale configs.
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
