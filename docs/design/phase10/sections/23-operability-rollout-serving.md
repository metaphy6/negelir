# Phase 10 §10.23 — Operability, rollout, serving quality (production-serving floor)

> **Provenance.** Carved out of `docs/planning/ROADMAP.md` Phase 10 on the Phase 10 split (post-13th-pass) so the ROADMAP stays navigable. Content here is the **binding** Phase 10 contract; ROADMAP §10 now points at this folder. Any edit must update `xops/versioning/chart.json` (`docs` minor) and the tracker (per AGENTS.md §3 + §6.1). Cross-phase references (Phase 5/7/8/9/11/12/13a/14/16/19/20) remain authoritative against ROADMAP and the matching `docs/design/*.md` anchors.


### 10.23 Operability, rollout, serving quality (binding addendum — "production-serving floor")

> **Why this addendum exists.** §10.0–§10.20 specify the surface
> contract; §10.21 the integrity floor; §10.22 the TR-language
> correctness floor. None of those tell us how to **roll out a new
> intent model without a 5-minute accuracy regression**, how to
> **isolate a single abusive tenant from starving the humanizer queue**,
> what to display when **7 of 10 fixtures in a summary fan-out come
> back** (and 3 timed out), how to format **"1.000 TL" vs "1,000 TL"**
> per Turkish locale convention, how to keep a screen-reader-using fan
> from getting noise-decorated emoji answers, what timezone the
> rendered "21:30" is in, how to bound the **per-request cost in tokens
> × USD**, what happens to the L0 cache when the **lexicon swaps
> mid-request on one pod but not another**, how to plan **NLP capacity
> from a 3× traffic spike**, how to **drill a full lexicon corruption
> recovery**, and what the **CVE response runbook** is when
> `python-crfsuite` ships a critical advisory at 02:00 UTC.
>
> §10.23 closes those gaps. Each rule below is operationally binding;
> none introduce ML — they are deployment, scheduling, formatting, and
> runbook contracts. The combined floor (§10.21 + §10.22 + §10.23) is
> what "production-ready Turkish-NLP plane" means in this codebase.
>
> **Doctrine reminder.** AGENTS.md Rule 5 (scale symmetry — same code
> at 1 replica or 1000), Rule 8 (phase gates — DoD is binding), and
> CLAUDE.md (no `*-latest` model IDs) all apply. Every rollout knob
> below is single-source per Rule 1; every observable per-tenant /
> per-tier metric is cardinality-bounded per §10.14.

#### 10.23.1 Multi-tenant fairness & abuse isolation inside the NLP plane

- [x] **Real failure mode.** §10.12 cap "queue > 100 → disable
  humanizer" is global. A single noisy tenant (or compromised account)
  flooding `qa.request.v1` at 50 QPS can blow the queue → humanizer
  disabled for everyone → tier-paying users see degraded answers
  caused by another tenant's behaviour. Phase 7 rate-limit at the
  gateway exists, but it is per-IP / per-account, NOT per-NLP-stage —
  a tenant within their gateway budget can still saturate the humanizer
  GPU lease.
- [x] **Per-tenant fair-queue at NLP intake.** `qa.request.v1` consumer
  on the NLP pod implements weighted-fair-queueing keyed by
  `cfg.nlp_fairness_key ∈ {tenant_id, account_id, ip_bucket}` default
  `account_id` (Phase 9 stamps `account_id` onto every `qa.request.v1`;
  unauthenticated → `ip_bucket` derived from /24). Each key gets one
  virtual queue with `cfg.nlp_per_tenant_inflight_max=8` concurrent
  intake slots; over-cap → request queued behind that key's own slots,
  NOT behind other tenants. Implementation: deterministic round-robin
  over the keys with non-empty queues (per AGENTS.md Rule 5 — single
  pod or 1000 pods, the same code path). Cardinality cap on tracked
  keys = `cfg.nlp_fairness_max_tracked_keys=10000` (LRU eviction with
  `nlp.event.v1{kind=fairness_key_evicted}` debounced).
- [x] **Humanizer GPU lease fair-share.** The humanizer breaker (§10.8)
  is global; the GPU lease (§10.21.9 stage 6) is per-pod. Per-tenant
  weighted-fair scheduling extends to humanizer admission: each tenant
  gets a token-bucket of `cfg.nlp_per_tenant_humanizer_burst=4` and
  refill `cfg.nlp_per_tenant_humanizer_refill_per_s=2`. Over-budget →
  request silently degrades to template-only answer (NOT an error;
  user sees a slightly less polished sentence — degraded path is
  already proof-tested in §10.10). `degraded_reason="humanizer_tenant_budget_exceeded"`
  added to the §10.10 enum.
- [x] **Abuse detection signal.** `nlp_tenant_intake_rate{key_class}`
  histogram (key classes: `account_paid`, `account_free`,
  `ip_anonymous`, `ip_known_proxy`) — when a single key sustains >
  `cfg.nlp_tenant_abuse_qps_threshold=10` for `cfg.nlp_tenant_abuse_window_s=60`,
  emit `nlp.alert.v1{kind=nlp_tenant_intake_abuse, severity=warn,
  key_class, qps_observed}` (debounced 5min per key class — bounded
  cardinality). Phase 7 sec.alert.v1 is the right place for *blocking*
  decisions; this NLP-side alert is observability only.
- [x] **Closed-set tenant-class enum.** `cfg.nlp_tenant_class_enum =
  ["account_paid", "account_free", "ip_anonymous", "ip_known_proxy"]`
  — single source. AST guard `test_nlp_no_unbounded_tenant_label`
  rejects any metric / log / event that emits `tenant_id` directly
  (high-cardinality leak); only the closed `key_class` enum may appear
  in observable surfaces.
- [x] **Proof:** `test_nlp_per_tenant_inflight_cap_isolates_noisy_tenant`
  (chaos: tenant A floods 50 QPS, tenant B sees < `cfg.nlp_p95_total_ms`
  latency unchanged), `test_nlp_humanizer_tenant_budget_degrades_to_template`,
  `test_nlp_fairness_key_eviction_lru_bounded`,
  `test_nlp_tenant_class_enum_closed` (AST), `test_nlp_no_raw_tenant_id_in_metrics`
  (AST registry walk).

#### 10.23.2 Canary rollout & shadow-mode for intent model + lexicons

- [x] **Real failure mode.** A new `intent.tr.bin` with subtly
  different boundary behaviour (e.g., calibration shift) deployed to
  100% of pods at once = blast-radius of a bad model = entire user
  base. Same for a lexicon swap that introduces a new alias collision.
  §10.21.9 cold-start drains gracefully but does NOT compare new vs
  old behaviour before promotion.
- [x] **Pod-level rollout percentage.** K8s `Deployment` ships new
  pods with `cfg.nlp_intent_model_canary_pct=10` (env-var driven —
  the 10% of pods with `NLP_CANARY=1` at startup load
  `intent.tr.bin.canary` and the matching calibration file; the rest
  load `intent.tr.bin`). API gateway routes by hashing
  `(account_id // bucket_size)` → sticky per-account assignment so a
  single user sees consistent classifier behaviour during the canary
  window. Sticky bucket size = `cfg.nlp_canary_account_bucket_size=1000`.
- [x] **Shadow-mode evaluation.** Independent of canary routing,
  `cfg.nlp_intent_shadow_mode ∈ {off, on}` default `off`; when `on`,
  every pod (canary OR baseline) runs BOTH models on every request
  and records `(input_hash, baseline_intent, baseline_conf,
  canary_intent, canary_conf, agreement)` to a sampled audit stream
  `nlp.shadow.v1` (cardinality bounded — sampling rate
  `cfg.nlp_shadow_sample_rate=0.01`). Only the baseline answer is
  delivered to the user. Operator runs `make nlp.shadow-report` over
  the last 24h of `nlp.shadow.v1` records to compute disagreement
  rate, intent-distribution KL-divergence, and per-intent confidence
  delta histograms.
- [x] **Promotion gate.** `make nlp.canary-promote` refuses to flip
  `cfg.nlp_intent_model_canary_pct=100` unless: (a) shadow-mode has
  run for ≥ `cfg.nlp_canary_min_shadow_hours=72`; (b) disagreement
  rate ≤ `cfg.nlp_canary_max_disagreement_rate=0.03`; (c) per-intent
  confidence drift |Δp95| ≤ `cfg.nlp_canary_max_confidence_drift=0.05`;
  (d) §10.18 evaluation harness PASSES on the canary model
  end-to-end. Refusal returns a structured report on which gate
  failed.
- [x] **Same gates apply to lexicon swap.** A NEW lexicon snapshot
  carries a `lexicon_version_id`; canary pods serve from the new
  snapshot, baseline from the old; same shadow / promotion gates
  apply (with `disagreement` defined as "different gazetteer
  resolution for the same input").
- [x] **Rollback is a one-command.** `make nlp.canary-rollback` flips
  the env-var on the canary pods (K8s rolling restart) AND emits
  `nlp.alert.v1{kind=nlp_canary_rolled_back, severity=warn,
  model_or_lexicon, reason}`.
- [x] **Proof:** `test_nlp_canary_routing_is_account_sticky`,
  `test_nlp_shadow_mode_records_disagreements`,
  `test_nlp_canary_promote_refuses_below_min_hours`,
  `test_nlp_canary_promote_refuses_on_disagreement_breach`,
  `test_nlp_canary_promote_refuses_on_eval_harness_fail`,
  `test_nlp_lexicon_canary_uses_same_gates`.

#### 10.23.3 Continuous-evaluation drift detection (post-deploy regression)

- [x] **Real failure mode.** §10.18 evaluation harness gates **at
  deploy time**. Real-world traffic distribution drifts (new league
  starts, transfer window, viral storyline) → the deployed model
  silently underperforms on emerging slices weeks after the gate
  passed. No mechanism to detect this without humans noticing user
  complaints.
- [x] **Weekly automated re-evaluation.** `xops/ci/nlp_weekly_eval.yml`
  cron job (Monday 03:00 UTC): (a) sample
  `cfg.nlp_weekly_eval_sample_size=2000` queries from the last 7 days
  of `nlp.shadow.v1` (PII-scrubbed per §10.21.7); (b) human-label
  pipeline (separate workflow — PR-style review with 3-of-5 labeller
  agreement; results land in `data/nlp/weekly_eval/YYYY-WW/labels.yaml`);
  (c) re-run §10.18 evaluation harness against the labelled slice;
  (d) emit `nlp.alert.v1{kind=nlp_weekly_eval_regression, severity=warn,
  intent_accuracy_delta, slice}` if absolute accuracy on any slice
  drops by > `cfg.nlp_weekly_eval_max_accuracy_drop=0.03` from the
  prior week.
- [x] **Decoupling from traffic.** Sample is representative-sampled
  by `(intent_class, has_entity, has_dialect, has_code_switch,
  hour_of_day_bucket)` strata, NOT pure random — protects against a
  noisy storyline week from making the eval all-about-Galatasaray.
  Stratification pinned in `ai/nlp/eval/_sample.py`; AST asserts the
  strata enum is closed.
- [x] **No PII leaves the system.** Sampled queries are
  PII-scrubbed AND length-truncated to
  `cfg.nlp_weekly_eval_sample_max_chars=200` AND any token NOT in the
  combined `(LeagueCatalog ∪ ai/nlp/lang_tr/* ∪ TR top-10k word freq)`
  set is replaced with `<UNK>` before labelling. Labellers see only
  the sanitized form.
- [x] **Auto-degrade on sustained regression.** When 2 consecutive
  weekly evals show > `cfg.nlp_weekly_eval_consecutive_drop_threshold=0.05`
  cumulative drop, the next `make nlp.canary-promote` of any newer
  model is REFUSED until a human acknowledges via
  `data/nlp/weekly_eval/YYYY-WW/ack.yaml` (PR-merged). Forces human
  attention on persistent regressions.
- [x] **Proof:** `test_nlp_weekly_eval_sample_stratified_correctly`,
  `test_nlp_weekly_eval_pii_scrubbed`,
  `test_nlp_weekly_eval_unknown_tokens_replaced`,
  `test_nlp_weekly_eval_alert_fires_on_threshold`,
  `test_nlp_canary_promote_refuses_on_consecutive_regression_without_ack`.

#### 10.23.4 Summary fan-out partial-failure semantics

- [x] **Real failure mode §10.6 underspecifies.** A `summary.weekend`
  query fans out to N=10 fixtures via §10.6 `nlp.dispatcher.v1`. If 3
  predictions time out and 7 succeed, what does the user see? Today
  the contract is silent → renderer either blocks the whole answer
  (unfair to the 7 that succeeded) or silently omits the 3 (lying by
  omission). Neither is acceptable.
- [x] **K-of-N quorum policy.** `cfg.nlp_summary_min_fixture_quorum=0.6`
  (60% of fan-out fixtures must respond within
  `cfg.nlp_summary_fanout_timeout_ms=2500`). Three outcomes:
  - **Quorum met (≥ 60% returned):** render answer with TR-disclosed
    omission ("10 maçtan 7'si için tahmin hazır; kalan 3'ün durumu için
    sayfaya bakın."). Per-fixture skip enumerated as a sub-list with
    `degraded_reason` per fixture (closed enum: `predict_timeout`,
    `predict_unavailable`, `data_lookup_failed`,
    `calibration_mismatch_refused` per §10.21.10).
  - **Quorum missed but ≥ 1 returned:** render a **per-fixture-only**
    answer (NOT a summary) with TR disclosure ("Tüm maçları kapsayan
    bir özet hazırlanamadı; gelen tahminler aşağıda.") and degraded
    reason at the answer level.
  - **Zero returned:** standard `nlp_predict_timeout` template (per
    §10.10 row 7).
- [x] **Per-fixture timeout independence.** Fan-out timeouts are
  per-fixture, NOT cumulative. A single slow fixture cannot block
  the others — `asyncio.as_completed` pattern with hard
  per-future timeout. AST guard `test_nlp_summary_fanout_no_gather`
  rejects `asyncio.gather(...)` in the dispatcher (it propagates the
  slowest tail latency and binds futures to the cancelled context).
- [x] **Stable Turkish disclosure templates.** `summary_partial.tr.j2`
  and `summary_per_fixture_only.tr.j2` (NEW templates) — each with
  slot for `(returned_count, total_count, missing_fixtures[].label,
  missing_fixtures[].degraded_reason_tr)`. Reason-translation table
  at `ai/nlp/lang_tr/degraded_reasons.tr.yaml` (closed enum →
  user-facing TR string). Every `degraded_reason` enum value MUST
  have a TR translation; build refuses on missing entries.
- [x] **Citation-block accommodation.** Citations §10.7 / §10.21.6
  carry the per-fixture model_versions list; in a partial summary
  the citation block reflects ONLY the returned fixtures (NOT the
  intended N). Calibration-mismatch policy from §10.21.10 still
  applies across the returned subset.
- [x] **Proof:** `test_nlp_summary_quorum_met_renders_partial_with_disclosure`,
  `test_nlp_summary_quorum_missed_renders_per_fixture_only`,
  `test_nlp_summary_zero_returns_renders_predict_timeout_template`,
  `test_nlp_summary_fanout_no_gather_in_dispatcher` (AST),
  `test_nlp_summary_per_fixture_independent_timeout`
  (chaos: 3 fixtures sleep 5s, 7 return at 100ms → answer at p95 ≤ 2.7s),
  `test_nlp_degraded_reason_tr_translation_table_complete` (build).

#### 10.23.5 Output-side TR formatting discipline (numbers, dates, scores)

- [x] **Real failure mode.** Turkish convention: thousands separator
  `.`, decimal `,` (German style); time format `HH:MM` (24h, never
  am/pm); date `DD.MM.YYYY` or `DD Ay YYYY`; football scores
  `home-away` (no space). Default Python / Jinja2 / Go formatting
  emits `1,000.5` (US), `9:30 PM`, `2026-04-27`, `1 - 0` — all WRONG
  for TR users and visibly amateurish.
- [x] **Single-source TR formatter.** `ai/common/text/tr_format.py`:
  - `tr_format_number(value, decimals=0) -> str` — `1234.56` →
    `"1.234,56"`; uses `decimal.Decimal` for exact rounding (no
    binary-float drift). Banker's rounding default; configurable via
    `cfg.nlp_format_number_rounding ∈ {bankers, half_up}` default
    `bankers` (matches scikit-learn / standard ML probability
    rounding).
  - `tr_format_money(value, currency="TRY") -> str` — `1234.56` →
    `"1.234,56 TL"` for TRY, `"1.234,56 €"` for EUR (suffix table
    at `ai/nlp/lang_tr/currency_suffix.tr.yaml`).
  - `tr_format_clock(dt, tz="Europe/Istanbul") -> str` — always 24h
    `HH:MM`; tz-aware (see §10.23.6).
  - `tr_format_date(d) -> str` — default `"27 Nisan 2026"` (long
    form); month names in `ai/nlp/lang_tr/month_names.tr.yaml`. Short
    form `tr_format_date_short(d)` → `"27.04.2026"`.
  - `tr_format_score(home, away) -> str` — `"1-0"` (ASCII hyphen, no
    space). Final-score shorthand consistent with §10.22.6 input
    parsing.
- [x] **Jinja2 filter registration.** Every formatter exported as a
  Jinja2 filter (`number_tr`, `money_tr`, `clock_tr`, `date_tr`,
  `date_tr_short`, `score_tr`). AST guard
  `test_nlp_no_python_default_format_in_templates` rejects any
  template emitting `{{ value }}` for fields whose type is `int`,
  `float`, `Decimal`, `datetime`, `date` — must use a `_tr` filter.
  Filter signatures introspected from `ai/nlp/render.py`.
- [x] **Locale-pinned via babel optional dep.** `babel` is OPTIONAL —
  not a hard dependency (CLAUDE.md prefers smallest stack). When
  installed, locale formatting via `babel.numbers.format_decimal(
  value, locale='tr_TR')` is used for cross-validation in tests
  (regression: `tr_format_number(1234.56) == babel.format_decimal(
  1234.56, locale='tr_TR')` — proof at test time only). Production
  uses our own deterministic implementation; `babel` is dev-only.
- [x] **Negative-zero, infinity, NaN policy.** Formatters refuse
  `float('inf')`, `float('-inf')`, `float('nan')` — raise
  `ValueError` (callers must clamp upstream). `-0.0` formats as
  `"0"` (not `"-0"`). Guard tests pin every edge case.
- [x] **Proof:** `test_tr_format_number_thousands_dot_decimal_comma`
  (parametrized over 30 values), `test_tr_format_money_try_suffix`,
  `test_tr_format_clock_always_24h_no_am_pm`,
  `test_tr_format_date_long_form_uses_tr_month_names`,
  `test_tr_format_score_no_space_ascii_hyphen`,
  `test_tr_format_negative_zero_renders_zero`,
  `test_tr_format_inf_nan_raises`,
  `test_nlp_no_python_default_format_in_templates` (AST),
  `test_tr_format_matches_babel_when_available` (skip-if-no-babel).

#### 10.23.6 Timezone discipline (render TZ vs storage TZ)

- [x] **Real failure mode.** "Maç saat 21:30'da" — in WHICH timezone?
  Turkish users assume Europe/Istanbul (UTC+3, no DST since 2016).
  But fixture data may carry kickoff in UTC (Phase 4 storage convention)
  or in the venue's local TZ (UEFA fixtures across Europe). Rendering
  a UTC-stored time as Istanbul-local requires explicit conversion;
  silent assumption = users miss matches by hours.
- [x] **Storage TZ = UTC, render TZ = Europe/Istanbul (default).**
  `cfg.nlp_render_timezone="Europe/Istanbul"` (single default at v1
  per §10.17 locale chain). All `qa.answer.v1` rendered times go
  through `tr_format_clock(dt_utc, tz=cfg.nlp_render_timezone)`. AST
  guard `test_nlp_no_naive_datetime_in_render` rejects any naive
  `datetime` (no tzinfo) reaching a formatter — must be UTC-aware
  on the wire and converted at format time.
- [x] **Citation always carries UTC.** Per §10.21.6 / §10.21.8 the
  citation block carries `produced_at_utc` (ISO-8601 with `Z` suffix,
  microsecond precision). Render TZ applies to user-visible body
  ONLY; citation is byte-stable across TZ changes.
- [x] **DST-edge / leap-second tests.** Even though Turkey has no DST
  since 2016, storage may carry pre-2016 kickoffs (historical eval),
  AND `Europe/Istanbul` IANA tz database row covers historical DST
  transitions. Test corpus pins:
  `tr_format_clock(2014-03-30T01:30:00Z) == "03:30"` (DST window),
  `tr_format_clock(2014-03-30T02:30:00Z) == "04:30"` (post-spring-forward),
  `tr_format_clock(2026-04-27T18:30:00Z) == "21:30"` (current).
  Leap-second handling: Python `datetime` doesn't model leap seconds
  → assert that any input claiming `:60` seconds raises (no silent
  truncation).
- [x] **`zoneinfo` SHA pin.** `cfg.nlp_zoneinfo_dir` defaults to
  system zoneinfo; production deployments override to a pod-shipped
  `zoneinfo/` directory whose SHA is recorded in `chart.json`
  compatibility block (mirrors §10.21.5 confusables-table SHA pin).
  Boot probe asserts `Europe/Istanbul` row present + SHA matches.
  Defends against a host-OS tzdata downgrade silently changing
  rendered times.
- [x] **Forward hook for venue-local TZ.** When future locales add
  `tr-DE`, `tr-CY`, etc. (§10.22.11), per-locale render TZ default
  table at `ai/nlp/lang_tr/locale_render_tz.tr.yaml`. v1 entry: only
  `tr-TR → Europe/Istanbul`.
- [x] **Proof:** `test_nlp_clock_renders_istanbul_offset_currently_plus3`,
  `test_nlp_clock_naive_datetime_rejected` (AST + runtime),
  `test_nlp_dst_window_2014_renders_correctly` (3-point probe),
  `test_nlp_leap_second_input_rejected`,
  `test_nlp_zoneinfo_sha_pinned_at_boot`,
  `test_nlp_citation_always_utc_z_suffix`.

#### 10.23.7 Accessibility & answer-format negotiation

- [x] **Real failure mode.** Default answers pepper text with emoji
  (⚽ 🏆 🟢 🔴) and decorative chars (▶ ✓ ✗); screen readers (NVDA,
  JAWS, VoiceOver) read these as "soccer ball, trophy, large green
  circle, large red circle, play button" — verbose and disruptive
  for blind / low-vision users. Unicode "soft hyphen" (U+00AD) and
  combining marks similarly confuse assistive tech.
- [x] **Closed `answer_format` enum on `qa.request.v1`.**
  `cfg.nlp_answer_formats = ["plain", "markdown_safe", "screen_reader"]`
  (Phase 9 wires the param; defaults `plain`). Each formats the
  same answer payload differently:
  - `plain`: current default; emoji and decorative chars allowed
    from the closed `cfg.nlp_decorative_set` only (no free-text emoji
    from the LLM — humanizer's tokenizer-mask already excludes the
    emoji range per §10.8 decoding constraints; reasserted here as
    binding).
  - `markdown_safe`: GFM (CommonMark + extensions) safe subset; no
    inline HTML; emoji preserved; tables for fixture lists; bold for
    canonical names.
  - `screen_reader`: emoji STRIPPED entirely; decorative chars
    replaced with semantic markers (`✓` → `"evet"`, `✗` → `"hayır"`);
    every number is space-separated for natural reading
    (`"yüzde 67"` not `"%67"`); soft-hyphen and combining marks
    NORMALIZED out (`unicodedata.normalize('NFC', ...)` then strip
    U+00AD).
- [x] **Per-format renderer.** `ai/nlp/render_format.py` —
  `render(answer_blocks, format)` dispatches; each format has its
  own template directory under `ai/nlp/templates/<format>/`. Templates
  share the same slot dict (§10.21.6 closed schema); no per-format
  template logic in code. AST guard `test_nlp_per_format_templates_share_slots`
  asserts every template across the three format dirs declares the
  same Jinja2 variable set.
- [x] **Format negotiation precedence.** `?answer_format=` query
  param > `Accept` header (`text/plain` → `plain`,
  `text/markdown` → `markdown_safe`, `text/x-screen-reader` → custom
  MIME for SR clients) > default `plain`.
- [x] **Default decorative set.** `cfg.nlp_decorative_set = ["⚽",
  "🏆", "🟢", "🔴", "🟡"]` — closed list at v1; AST asserts no other
  emoji codepoints reach the `plain` template output. The
  humanizer tokenizer-mask (§10.8) is the FIRST defense; this is
  the second — proofreader §10.9 gate scans rendered output for
  emoji not in the set, blocks + alerts on hit.
- [ ] **Proof:** `test_nlp_screen_reader_format_strips_all_emoji`,
  `test_nlp_screen_reader_format_normalizes_combining_marks`,
  `test_nlp_screen_reader_renders_percent_as_words`,
  `test_nlp_markdown_safe_no_inline_html` (regex on rendered output),
  `test_nlp_format_negotiation_param_over_header_over_default`,
  `test_nlp_per_format_templates_share_slots` (AST),
  `test_nlp_decorative_set_closed_at_render` (proofreader gate).

#### 10.23.8 Per-request cost-of-serving budget

- [ ] **Real failure mode.** Humanizer is the dominant per-request
  cost (GPU lease seconds × wall-clock × electricity ≈ stable
  per-token). At v1 this is on-prem GPU so "cost" is wall-clock; at
  Phase 20 monetization-on it's a hard $ ceiling per tier. No
  mechanism today bounds total humanizer-tokens per request, per
  tenant per minute, or per pod per hour.
- [ ] **Per-request token budget.** `cfg.nlp_max_humanizer_tokens_per_request=120`
  (already implied by §10.8 `max_new=120` decode cap, restated here
  as the binding doctrine — single source). Over-budget would be
  caught at decode time; this restatement makes the cost-budget
  contract explicit.
- [ ] **Per-tenant per-minute budget.** `cfg.nlp_max_humanizer_tokens_per_tenant_per_min=2400`
  (= 20 humanized requests × 120 tokens). Tracked via a sliding
  60s window per `cfg.nlp_fairness_key` (reuse §10.23.1
  infrastructure). Over-budget → degrade to template per §10.23.1
  `humanizer_tenant_budget_exceeded` reason. Counter is process-local
  + best-effort gossip via Redis (`cfg.nlp_humanizer_budget_redis_key_prefix=
  "nlp:humanizer:budget:"`, TTL 120s); cross-pod budget enforcement
  is best-effort, NOT strict (Redis outage → fall back to per-pod
  budget × pod-count estimate; documented as acceptable slop).
- [ ] **Per-pod per-hour ceiling.** `cfg.nlp_max_humanizer_tokens_per_pod_per_hour=720000`
  (= 100 req/min sustained × 60 min × 120 tokens). Over-ceiling →
  pod globally degrades humanizer for `cfg.nlp_humanizer_pod_cooldown_s=300`,
  emits `nlp.alert.v1{kind=nlp_humanizer_pod_budget_exceeded,
  severity=warn}`. Defends against runaway loops or model-mode
  pathology emitting maximum-length completions on every request.
- [ ] **Phase 20 hook.** When monetization is on, the per-tenant budget
  is OVERRIDDEN by the tier's allowed tokens; v1 default budgets are
  the floor for free tier. Tier mapping pinned in §10.21.11 contract
  (`tier_id_required` is per-intent; tokens-per-tenant-per-min is
  per-tier — both single-source via Phase 20 config).
- [ ] **Cost telemetry.** `nlp_humanizer_tokens_emitted_total{tenant_class,
  intent}` counter (cardinality bounded by closed enums); per-hour
  rollup feeds the §10.23.10 capacity-planning model.
- [ ] **Proof:** `test_nlp_per_request_token_cap_enforced_at_decode`,
  `test_nlp_per_tenant_per_min_budget_degrades_to_template`,
  `test_nlp_per_pod_per_hour_ceiling_triggers_cooldown`,
  `test_nlp_redis_outage_falls_back_to_per_pod_budget`,
  `test_nlp_humanizer_token_counter_cardinality_bounded`.

#### 10.23.9 Cross-pod cache-coherence & poisoning defense

- [ ] **Real failure mode.** §10.12 L0 intent cache and L1 answer
  cache (`cache.v1`) key on `(normalized_text, lexicon_version,
  intent_model_version)`. Today only `normalized_text` is in the key
  → if pod A has lexicon v17 and pod B has v18 (rolling lexicon
  swap mid-request), pod B can serve a v17 cached answer attributing
  it to v18 → citation/version mismatch is silent.
- [ ] **Versioned cache keys.** Cache key = `sha256(normalized_text ||
  intent_model_version || lexicon_version_id || calibration_version ||
  cfg.nlp_pipeline_version)`. ALL components MUST be present; AST
  guard `test_nlp_cache_key_includes_all_versions` walks the cache
  put/get sites and asserts the key-builder consults all 5 fields.
- [ ] **Atomic version-stamping.** Versions captured at request entry
  (snapshot read of all 4 version fields under one read of an
  immutable `VersionSnapshot` struct that is replaced atomically on
  any swap) — NEVER read individually mid-request (would yield a
  torn snapshot under concurrent swap). Snapshot held for the
  request's lifetime.
- [ ] **TTL is short.** L0 cache TTL = `cfg.nlp_l0_cache_ttl_s=300`
  (already pinned in §10.12); L1 (`cache.v1`) TTL =
  `cfg.nlp_l1_answer_cache_ttl_s=600`. Both are short relative to
  lexicon swap cadence (mtime poll = 30s default per §10.2). After
  lexicon swap, stale entries in L0/L1 with old version-key are
  unreachable (different key) → naturally evict via TTL. No
  cross-pod cache invalidation needed (the version in the key IS
  the invalidation).
- [ ] **Cache poisoning defense.** L1 (`cache.v1` shared via Redis
  per Phase 7) — adversary with Redis write access could craft a
  fake `(key, value)` pair. Each cached answer is HMAC-signed with
  `cfg.nlp_l1_cache_hmac_key_path` (mode 0400, mirrors §10.21.8 key
  doctrine); on cache hit, signature verified before deserialization.
  Verify-fail → drop entry, emit `nlp.alert.v1{kind=
  nlp_l1_cache_signature_invalid, severity=warn}`, fall through to
  fresh compute. Phase 7 Redis is trusted in v1 but the signature
  closes the door even on supply-chain compromise.
- [ ] **Cache stampede — single-flight reasserted.** §10.12 already
  pins per-pod single-flight; §10.23.9 reasserts that single-flight
  IS the correct stampede protection — no thundering-herd Redis-side
  lock needed. Cross-pod stampede on a viral query is bounded by
  pod-count (each pod computes once, then all share via L1).
- [ ] **Proof:** `test_nlp_cache_key_includes_all_5_version_fields`
  (AST), `test_nlp_version_snapshot_held_for_request_lifetime`,
  `test_nlp_l1_cache_signature_verified_on_hit`,
  `test_nlp_l1_cache_signature_invalid_drops_and_alerts`,
  `test_nlp_lexicon_swap_naturally_evicts_l0_via_versioned_key`
  (chaos: swap mid-traffic → no stale-version answer observable).

#### 10.23.10 Capacity planning model & bottleneck documentation

- [ ] **Real failure mode.** Operators face "we're hitting 70% CPU,
  do we add a pod?" — without an explicit capacity model the answer
  is guessed. §10.12 latency table tells per-stage budget but doesn't
  derive the throughput ceiling.
- [ ] **Per-pod throughput model documented.** `docs/design/TURKISH_NLP.md`
  gains a "Capacity model" section with:
  - **Little's Law derivation**: `throughput_pod = parallelism /
    avg_latency` per stage.
  - **Per-stage parallelism**:
    - Normalize / lexicon / intent / entity / dispatcher = CPU-bound,
      parallelism = `cfg.nlp_intake_workers=8` (default; sized for
      4 vCPU pod).
    - Humanizer = GPU-lease serialized, parallelism = `1` (per pod).
  - **Per-stage avg latency** (from §10.12 table p50 column):
    normalize 5ms, intent 25ms, entity 40ms, render 30ms, humanizer
    300ms (when used), proofreader 15ms.
  - **Throughput ceiling** (without humanizer): `8 / 0.115s ≈ 70 QPS`
    per pod. With humanizer (default ON): `1 / 0.300s ≈ 3.3 QPS`
    per pod for humanized fraction × `cfg.nlp_humanizer_request_rate=0.6`
    → effective ~ 5.5 QPS per pod under default config. Pinned
    numbers in the doc with provenance (which `make nlp.bench` row
    they came from + git SHA of the bench).
- [ ] **`make nlp.capacity-report`** — generates a fresh capacity
  estimate from the latest `nlp.bench` run + current cfg values;
  output `data/nlp/capacity_report.md` with throughput-per-pod,
  bottleneck stage, and "to handle X QPS you need Y pods" calculator.
  CI runs on PRs that touch any §10.19 / §10.21.12 / §10.22.14 /
  §10.23.13 cfg knob and updates the report.
- [ ] **Bottleneck assertion at start.** Boot probe checks
  `cfg.nlp_intake_workers ≤ os.cpu_count() * 2` (oversubscription
  guard) and `cfg.nlp_intake_workers ≥ 2` (under-subscription guard
  — single-worker pods deadlock on singleflight in adversarial
  patterns). Refuse start on either.
- [ ] **3× spike rehearsal.** `make nlp.spike-test` (NEW;
  human-invoked, NOT in CI by default — too expensive): synthetic
  load generator hits a 3-pod stack at 3× current sustained QPS for
  5 minutes; success criteria = no `nlp.alert.v1{severity=critical}`
  fires AND p99 stays within `cfg.nlp_p99_total_ms` × 1.5. Documented
  in `docs/guides/nlp_runbook.md`. Run quarterly per ops convention.
- [ ] **Proof:** `test_nlp_intake_workers_validated_at_boot`,
  `test_nlp_capacity_report_generated_on_cfg_change` (CI gate),
  `test_nlp_capacity_model_doc_contains_required_sections` (doc
  presence test).

#### 10.23.11 Disaster recovery drill (full-lexicon corruption + pod restart)

- [ ] **Real failure mode.** §10.21.3 atomic-swap-or-revert defends
  against a single mid-poll corruption. It does NOT exercise
  recovery from the case where the source-of-truth lexicon files
  on disk are corrupted (filesystem rot, accidental `git push --force`
  reverting a lexicon update, deploy-script bug writing zero-byte
  files) AND every pod restarts at once (deploy event coinciding
  with corruption). Then atomic-swap has nothing valid to swap to →
  pods refuse boot → entire NLP plane down.
- [ ] **Bootstrap-fallback lexicon.** A minimal "safe-mode" lexicon
  shipped in the container image at `ai/nlp/lexicon_safe_mode/`
  (read-only, baked-in, NOT mtime-poll watched). Contains: top-100
  team aliases (LeagueCatalog v1 floor), top-10 intent templates,
  closed market enum, no dialect/abbreviation entries. When primary
  lexicon load FAILS at boot AND `cfg.nlp_safe_mode_fallback_enabled=true`
  (default `true`), pod boots in safe mode → readiness probe returns
  200 with header `X-NLP-Safe-Mode: true` AND every emitted
  `qa.answer.v1` carries `degraded=true,
  degraded_reason="lexicon_safe_mode_active"`. Operator sees
  perpetual `nlp.alert.v1{kind=nlp_safe_mode_active,
  severity=critical, debounce=300s}` until primary lexicon recovers.
- [ ] **Recovery contract.** Once primary lexicon recovers (operator
  fixes the source file → mtime-poll detects valid swap), pod EXITS
  safe mode atomically (next mtime-poll cycle detects valid lexicon
  → atomic swap to primary → safe-mode flag flipped off → next
  request renders without degraded flag). NO pod restart required.
  Proof: chaos test corrupts lexicon, all 3 pods enter safe mode,
  then restores, all 3 pods exit safe mode within
  `cfg.nlp_lexicon_reload_s + 5s`.
- [ ] **DR drill runbook.** `docs/guides/nlp_runbook.md` (per §10.22
  scope) gains a "Disaster recovery drills" section covering:
  - Full lexicon corruption scenario.
  - Intent model corruption scenario (no safe-mode model — pod
    refuses boot per §10.21.1; humans must restore from
    `data/nlp/model_history/<sha>/intent.tr.bin` archive).
  - Citation-key compromise scenario (rotate immediately per
    §10.21.8).
  - Lexicon-feed-key compromise scenario (rotate per §10.22.12).
  - Time-budget per scenario: ≤ 15 min for lexicon corruption (safe
    mode auto-engages), ≤ 60 min for model corruption (manual
    restore), ≤ 30 min for any key rotation (dual-acceptance window
    means no service disruption).
- [ ] **Quarterly drill cadence.** `make nlp.dr-drill` (human-only
  — destructive) — corrupts a copy of the lexicon in a staging pod,
  asserts safe-mode engages within budget, then restores and asserts
  recovery within budget. Run quarterly; result logged to
  `docs/reports/nlp_dr_drill_YYYY-Q.md`.
- [ ] **Proof:** `test_nlp_safe_mode_engages_when_primary_lexicon_corrupt`,
  `test_nlp_safe_mode_serves_with_degraded_flag`,
  `test_nlp_safe_mode_exits_atomically_on_primary_recovery`,
  `test_nlp_safe_mode_lexicon_size_bounded` (≤ 100 teams, ≤ 1MiB —
  no scope creep into the safe-mode artifact),
  `test_nlp_dr_drill_runbook_sections_present` (doc presence).

#### 10.23.12 Dependency CVE response policy

- [ ] **Real failure mode.** Phase 10 depends on `fasttext`,
  `python-crfsuite`, `jinja2`, `numpy`, `babel` (optional),
  `unicode-tables` (Confusables.txt source), `zoneinfo` (system
  tzdata). A critical CVE in any (e.g., Jinja2 sandbox-escape
  CVE-2024-XXXXX hypothetical) requires a coordinated patch ship.
  No documented response runbook = ad-hoc panic = slow patch.
- [ ] **CVE feed monitoring.** `xops/ci/nlp_cve_scan.yml` — daily
  CI job runs `pip-audit` against `ai/requirements.txt` (pinned per
  §10.21.1) AND polls GitHub Security Advisories for each pinned
  dependency. Any CRITICAL (CVSS ≥ 9.0) or HIGH (CVSS ≥ 7.0)
  advisory matching a pinned version → opens a GitHub issue
  automatically with label `phase:10` + `cve` + severity, AND
  emits a Slack/PagerDuty page (operator-configured, optional).
- [ ] **Response time targets.** Pinned in `docs/guides/nlp_runbook.md`:
  - **Critical (CVSS ≥ 9.0)**: patch ship target ≤ 24h. If patch
    not available upstream → mitigations documented (e.g., Jinja2
    sandbox CVE → enforce stricter `Environment(autoescape=True,
    sandbox=True)` config; AST guard already enforces no
    `from_string` per §10.21.2 → most exploit vectors closed).
  - **High (CVSS 7.0–8.9)**: patch ship target ≤ 7 days.
  - **Medium / Low**: bundle into next regular dependency-bump cycle.
- [ ] **Mitigations catalogue.** `ai/nlp/security/mitigations.md`
  (NEW) — running list of dependency CVE classes and the
  defense-in-depth measure already in place that mitigates them
  (e.g., "Jinja2 RCE via from_string → AST guard rejects from_string;
  sandbox-escape via filter chaining → custom finalize callback
  validates types"). Reviewed in PR for every dep version bump.
- [ ] **SBOM emission.** `make nlp.sbom` emits a CycloneDX-format
  SBOM at `data/nlp/sbom.json` covering all NLP-plane direct + transitive
  Python deps + the lexicon files (which carry their own provenance:
  source URL, SHA, license — many football-data lexicons are derived
  from openfootball.json which is ODbL-licensed; license
  attribution required). CI publishes the SBOM as a release artifact
  (Phase 14 release scope).
- [ ] **License attribution for lexicon-derived data.** Some team
  / league names are trademarked (UEFA, FIFA marks); LeagueCatalog
  Phase 13a is the registered source-of-truth and carries its own
  legal review. `data/nlp/build_reports/license_attribution.md`
  (CI-generated) lists every external data source feeding the
  lexicons + the legal basis (fair use for canonical names,
  attribution for openfootball-derived aliases).
- [ ] **Proof:** `test_nlp_cve_scan_ci_job_present` (workflow file
  presence), `test_nlp_runbook_cve_response_section_present`,
  `test_nlp_mitigations_catalogue_present`,
  `test_nlp_sbom_includes_all_pinned_deps`,
  `test_nlp_license_attribution_report_generated_in_build`.

#### 10.23.13 Knob inventory + DoD aggregate (~25 new keys, on top of §10.19 + §10.21.12 + §10.22.14)

- [ ] **New cfg knobs:**
  `nlp_fairness_key="account_id"`,
  `nlp_per_tenant_inflight_max=8`,
  `nlp_fairness_max_tracked_keys=10000`,
  `nlp_per_tenant_humanizer_burst=4`,
  `nlp_per_tenant_humanizer_refill_per_s=2`,
  `nlp_tenant_abuse_qps_threshold=10`,
  `nlp_tenant_abuse_window_s=60`,
  `nlp_tenant_class_enum=["account_paid","account_free","ip_anonymous","ip_known_proxy"]`,
  `nlp_intent_model_canary_pct=10`,
  `nlp_canary_account_bucket_size=1000`,
  `nlp_intent_shadow_mode="off"`,
  `nlp_shadow_sample_rate=0.01`,
  `nlp_canary_min_shadow_hours=72`,
  `nlp_canary_max_disagreement_rate=0.03`,
  `nlp_canary_max_confidence_drift=0.05`,
  `nlp_weekly_eval_sample_size=2000`,
  `nlp_weekly_eval_max_accuracy_drop=0.03`,
  `nlp_weekly_eval_consecutive_drop_threshold=0.05`,
  `nlp_weekly_eval_sample_max_chars=200`,
  `nlp_summary_min_fixture_quorum=0.6`,
  `nlp_summary_fanout_timeout_ms=2500`,
  `nlp_format_number_rounding="bankers"`,
  `nlp_render_timezone="Europe/Istanbul"`,
  `nlp_zoneinfo_dir=""` (empty = system),
  `nlp_decorative_set=["⚽","🏆","🟢","🔴","🟡"]`,
  `nlp_max_humanizer_tokens_per_request=120`,
  `nlp_max_humanizer_tokens_per_tenant_per_min=2400`,
  `nlp_max_humanizer_tokens_per_pod_per_hour=720000`,
  `nlp_humanizer_pod_cooldown_s=300`,
  `nlp_humanizer_request_rate=0.6`,
  `nlp_humanizer_budget_redis_key_prefix="nlp:humanizer:budget:"`,
  `nlp_l0_cache_ttl_s=300`,
  `nlp_l1_answer_cache_ttl_s=600`,
  `nlp_l1_cache_hmac_key_path="infra/nlp/l1_cache_hmac.key"`,
  `nlp_intake_workers=8`,
  `nlp_safe_mode_fallback_enabled=true`,
  `nlp_pipeline_version="1.0.0"`.
  Triangle test extends. Go-side `TestEnvSync` covers
  `nlp_render_timezone` (gateway needs it to render error responses
  consistently per RFC7807 mapping in §10.21.11) and
  `nlp_l1_cache_hmac_*` (gateway shares the L1 read path — Phase 7
  cache.v1 doctrine).
- [ ] **New `nlp.event.v1` kinds** (open-enum, registered):
  `fairness_key_evicted`,
  `cache_signature_dropped`,
  `safe_mode_engaged`,
  `safe_mode_exited`,
  `canary_shadow_disagreement`.
- [ ] **New `nlp.alert.v1` kinds** (open-enum, registered):
  `nlp_tenant_intake_abuse` (warn, debounced 5min),
  `nlp_canary_rolled_back` (warn),
  `nlp_weekly_eval_regression` (warn),
  `nlp_humanizer_pod_budget_exceeded` (warn),
  `nlp_l1_cache_signature_invalid` (warn),
  `nlp_safe_mode_active` (critical, debounced 300s).
- [ ] **New degraded-reason enum entries** (per §10.10):
  `humanizer_tenant_budget_exceeded`,
  `lexicon_safe_mode_active`,
  `summary_quorum_missed_per_fixture_only`,
  `calibration_mismatch_refused` (already pinned in §10.21.10 — reasserted).
  Each MUST have a TR translation in `degraded_reasons.tr.yaml`
  (per §10.23.4); build refuses on missing.
- [ ] **New build artifacts.** `data/nlp/capacity_report.md`,
  `data/nlp/sbom.json`, `data/nlp/build_reports/license_attribution.md`,
  `docs/reports/nlp_dr_drill_YYYY-Q.md` (quarterly).
- [ ] **DoD proof tests aggregate (new in §10.23):**
  - §10.23.1 — 5 tests (fairness + abuse isolation)
  - §10.23.2 — 7 tests (canary + shadow + promotion gates)
  - §10.23.3 — 5 tests (weekly eval + auto-degrade)
  - §10.23.4 — 6 tests (summary partial-failure semantics)
  - §10.23.5 — 9 tests (TR formatting incl. babel cross-validation)
  - §10.23.6 — 6 tests (timezone + DST + zoneinfo SHA)
  - §10.23.7 — 7 tests (accessibility + format negotiation)
  - §10.23.8 — 5 tests (cost-of-serving budget)
  - §10.23.9 — 5 tests (cache coherence + signature)
  - §10.23.10 — 3 tests (capacity model + boot validation)
  - §10.23.11 — 5 tests (DR safe-mode + recovery)
  - §10.23.12 — 5 tests (CVE scan + SBOM + license attribution)
  - **Total: ≈ 68 new proof tests added on top of §10.20 + §10.21 +
    §10.22 baseline. Cumulative Phase 10 proof-test count ≈ 250+.**
- [ ] **Chart compatibility additions.** Pin `babel` (optional dep
  version), `pip-audit` (CVE-scan tool version), CycloneDX schema
  version, IANA tzdata baseline date (e.g., `2026a`).
- [ ] **`make swarm.demo.nlp` extends** to cover §10.23 paths:
  one query each for: (a) tenant-fairness isolation under load (3
  tenants, 1 noisy); (b) canary routing + shadow-mode disagreement
  recording; (c) summary fan-out with 2 of 5 fixtures timing out
  (quorum-met partial-render); (d) `?answer_format=screen_reader`
  query (emoji-stripped output asserted byte-stable); (e) safe-mode
  engage/exit via injected lexicon corruption + recovery. All within
  the < 30s compose budget; if budget is tight, sub-set selectable
  via `make swarm.demo.nlp.fast` (fast-path) vs
  `make swarm.demo.nlp.full` (covers all of §10.21 + §10.22 + §10.23).
- [ ] **Documentation extensions.** `docs/design/TURKISH_NLP.md`
  gains: Capacity Model section, Output-Formatting section,
  Accessibility section, Tenant-Fairness section.
  `docs/guides/nlp_runbook.md` (per §10.22 scope) gains: Canary
  rollout playbook, Weekly-eval triage, DR drill procedures, CVE
  response runbook, Cost-budget tuning. `docs` minor bump alongside
  the §10.23 land per AGENTS.md §6.1.
