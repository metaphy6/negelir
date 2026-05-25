# Phase 8.8 — Sec-denylist sweeper (`maint.sec.v1` slice)

> Extracted from `docs/planning/ROADMAP.md` §8.8
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/nlp/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 8.8 Sec-denylist sweeper (`maint.sec.v1` slice)

> Promotes the §7.3 deferred "halve TTL of oldest decile" sweeper. Activates only under cap-mode pressure.

- [x] Subscribes to `sec.alert.v1{kind=denylist_growth_anomaly, severity=critical}` (Phase 7 §7.3 publisher).
- [x] On consume, runs new Lua script `infra/redis/lua/sec_denylist_decimate.lua` (VERSION + SHA256 header + `make verify.lua` CI gate + embedded copy at `server/internal/sec/embedded/` + `embedded_parity_test.go`, exactly like the existing two scripts):
  - Atomically (single Lua call — no client-side round-trips, no race with concurrent denylist mutations) identifies the oldest decile of `sec:denylist:_zset` members by score (= `expires_at_ms`).
  - Halves their remaining TTL: `new_score = now_ms + (old_score - now_ms) / 2`; `PEXPIREAT sec:denylist:<subject> new_score` AND `ZADD sec:denylist:_zset new_score subject` (single transaction — zset and key TTL never disagree).
  - **Cap-flag fast-clear.** If post-decimation `ZCARD < cfg.sec_denylist_cap × cfg.sec_denylist_cap_exit_ratio` (computed in Lua from the passed-in cap arg), executes `DEL sec:denylist:capped` and returns `cap_cleared=true`. Without this, the gateway's subnet-mode would persist for up to the 300s flag TTL even after the actual pressure drops — fast-clear is the user-facing reliability win.
  - **Concurrency safety.** A second decimate call entering while the first is mid-script is impossible (Redis Lua is atomic). Two *separate* alert consumers calling the script back-to-back are de-duplicated by the §8.8 hysteresis below; if hysteresis is bypassed (test path), the second call is still safe — the worst case is two halvings of the same TTL window, never an inconsistent zset.
  - **Mandatory args.** `now_ms` (ARGV[1]) and `cap` (ARGV[2]) are required; absence/zero returns `"error"` (mirrors the §7.3 v1.1.0 lesson — silent defaults broke lazy eviction).
  - Returns `{evicted_count, decile_size, new_zcard, cap_cleared: bool}` for audit.
- [x] Emits `maint.event.v1{kind=denylist_decimate, target=<source>, evicted_count, decile_size, new_zcard, cap_cleared}` and a separate `kind=denylist_cap_cleared` only when `cap_cleared=true` (operator-facing signal that subnet-mode is over).
- [x] **Decile-size boundary.** Decile is computed `decile_size = max(1, ZCARD // 10)`. When `ZCARD < 10`, decile_size = 1 (still meaningful). When `ZCARD == 0` the script is a no-op returning `evicted_count=0, decile_size=0, cap_cleared=false` (alert was spurious; agent records and debounces). Proof test covers both edges.
- [x] **Hysteresis.** No more than one decimate per `cfg.maint_sec_decimate_min_interval_s` (default 300s) **globally** (single zset, single global pressure signal — per-subject hysteresis is meaningless for a global cap). Tracked in agent state, not Redis (state survives within a single agent process; `replicas: 1` enforced). Hysteresis state survives leader handover via the §8.10 `Leader` Protocol's `last_action_at` slot in the K8s Lease annotation (Phase 14 only); compose-mode handover is N/A (single replica per service).
