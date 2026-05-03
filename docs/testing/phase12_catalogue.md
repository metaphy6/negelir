# Phase 12 — Adversarial Testing Catalogue (Phase 7 stubs)

> **Status:** Stub. Implementation lands with Phase 12 (System
> Hardening). Each row below describes a defense-agent property
> that the §7.1 / §7.2 / §7.3 producers must hold under adversarial
> input. Bodies are deliberately marked `TBD — implementation
> pending Phase 12` so the catalogue can be filled in alongside
> the actual chaos / fuzzing harness without churning the row IDs.

The IDs are stable (Phase 12 fuzzers reference them in their
test names) and match the `kind` enum in `KNOWN_SEC_ALERT_KINDS`
(`ai/swarm/agents/payloads.py`) wherever the property fires the
matching `sec.alert.v1` envelope.

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
