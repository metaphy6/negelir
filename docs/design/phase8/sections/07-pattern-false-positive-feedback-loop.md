# Phase 8.7 — Pattern false-positive feedback loop (`maint.sec.v1` slice)

> Extracted from `docs/planning/ROADMAP.md` §8.7
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/nlp/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 8.7 Pattern false-positive feedback loop (`maint.sec.v1` slice)

> Promotes the §7.x deferred FP loop. Operator clears a quarantined sample → the rule that triggered it adds to a per-source allowlist (autolearn-on) **or** queues for explicit operator approval (autolearn-off, default).

- [x] Subscribes to `maint.event.v1{kind=quarantine_clear, target=<quarantine_id>}` (Phase 7 publisher hook stub).
- [x] Resolves `quarantine_id → (source, rule_id, hit_substring)` from `quarantine_samples`. Computes `hit_fingerprint = sha256(NFC(hit_substring))[:16]` (deterministic, language-stable, never stores the raw substring in the live allowlist row — PII contains-checks are operator-only via `ops.allowlist-show`).
- [x] **Two-mode insertion.** On-disk `state` is encoded as `CHAR(1) IN ('p','a','e')` (per migration 010); the `_ack_routing.py`-style `_state_codec.py` maps it to bus-event strings `'pending'|'active'|'expired'` (single source of truth, boundary-tested). Bus events ALWAYS use the long form; SQL ALWAYS uses the short form.
  - `cfg.sec_input_pattern_autolearn_enabled = true`: insert with `state='a', expires_at = now() + cfg.maint_sec_allowlist_ttl_days, added_by_request_id`. Emits `kind=pattern_allowlist_added`.
  - `cfg.sec_input_pattern_autolearn_enabled = false` (default): insert with `state='p', expires_at = NULL, proposed_at = now()`. Emits `kind=pattern_allowlist_pending` (informational; **does not** count as `added`). Operator promotes via `ops.allowlist-approve --id <row_id> --ttl-days N` → row flips to `state='a'` and a `kind=pattern_allowlist_added` event fires. Pending rows older than `cfg.maint_sec_allowlist_pending_ttl_days` (default 30) are pruned by §8.3.
- [x] `sec.input.v1` reads only `state='a' AND (expires_at IS NULL OR expires_at > now())` rows on each pattern hit — if `(source, rule_id, hit_fingerprint)` matches, the hit is suppressed (counted in `sec_input_allowlist_hits_total` for visibility, never silently lost). The cache is refreshed via mtime-equivalent on a `pattern_allowlist_version` row in a metadata table (poll interval `cfg.sec_input_allowlist_reload_s`, default 60s) — same pattern as §7.4 sec.config fan-out (deliberately mtime-style, not bus fan-out). **Cache-reload race:** the version-row read uses `REPEATABLE READ` snapshot isolation against the same connection that subsequently reads `pattern_allowlist`, so promote-while-evaluating either sees the old version-row + old cache (next poll tick reloads) OR the new version-row + new cache (atomic refresh) — never a half-applied state. Proof test in §8.9 forces the race with `pg_advisory_lock` interleaving.
- [x] **SQL-injection guard.** All inserts/queries use parameterized statements (`psycopg.sql.Composed`, never f-string concat). Boundary test: AST scan of `ai/swarm/agents/maint/sec.py` rejects `cursor.execute(f"...")` and `"%s" %` patterns inside SQL builders. The hit_substring is **never** placed in a SQL `LIKE` or `=` clause — only the fingerprint hash is.
- [x] Emits `maint.event.v1{kind=pattern_allowlist_added|pattern_allowlist_pending|pattern_allowlist_expired}` accordingly. Expiry sweep runs at the §8.3 cron tick.
