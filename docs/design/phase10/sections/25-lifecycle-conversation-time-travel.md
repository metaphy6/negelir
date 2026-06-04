# Phase 10 §10.25 — Lifecycle, conversation, and time-travel

> **Provenance.** Carved out of `docs/planning/ROADMAP.md` Phase 10 on the Phase 10 split (post-13th-pass) so the ROADMAP stays navigable. Content here is the **binding** Phase 10 contract; ROADMAP §10 now points at this folder. Any edit must update `xops/versioning/chart.json` (`docs` minor) and the tracker (per AGENTS.md §3 + §6.1). Cross-phase references (Phase 5/7/8/9/11/12/13a/14/16/19/20) remain authoritative against ROADMAP and the matching `docs/design/*.md` anchors.


### 10.25 Lifecycle, conversation, and time-travel addendum (binding)

> **Why this section exists.** §10.0–§10.24 specify a *correct, robust,
> messy-input-tolerant, production-served* single-shot pipeline. They
> say nothing about (a) how a second message in the same conversation
> reuses the first, (b) how an answer streams to the client when a 600
> ms humanizer run would otherwise pin the response, (c) how an auditor
> reproduces a 6-month-old answer byte-identically, (d) how the four
> versioned artifacts (lexicon × intent × CRF × calibration × template)
> are kept compatible across rollouts, (e) how the intent model itself
> is retrained, (f) who writes new lexicon entries and how they are
> reviewed, (g) how a `did-you-mean` suggestion accepted by the user
> feeds back into the system, (h) how to detect when lexicons have
> stopped covering real input, (i) how a Phase 8 `quarantine_erase`
> propagates through NLP's caches and spool, (j) how an advertiser /
> legal ban-list overrides at render-time without poisoning the
> classifier, (k) what happens when Phase 5 `consensus.v1` is not yet
> emitting at NLP cold-start, (l) what happens when a Saturday matchday
> has more than `nlp_summary_max_fixtures` fixtures, and (m) how Turkish
> religious / national holidays interact with the date resolver. Every
> `[ ]` here is binding for Phase 10 DoD (per §10.20 item 23). New cfg
> knobs land alongside §10.19 / §10.21.12 / §10.22.14 / §10.23.13 /
> §10.24.14 in the same triangle commit.

#### 10.25.1 Multi-turn conversation context (stateful follow-ups, bounded scope)

- [x] **Real gap §10.0–§10.24 misses.** Every `qa.request.v1` is treated
  as stateless. A user asking "Galatasaray Fenerbahçe maçı ne zaman?"
  followed by "tahmin ne?" forces the second query through the full
  pipeline with no context — intent classifier hits `meta.unsupported`
  (no entity), dispatcher fires `did-you-mean`. Real chat UX is broken.
- [x] **`qa.context.v1` (data plane, additive).** New topic;
  `additionalProperties:false`; producer = `nlp.dispatcher.v1`;
  consumer = `nlp.intent.v1`. Schema:
  `{conversation_id (uuid), turn_index (≥0), entities[] (frozen
  resolved entities from prior turn — NOT raw text), intent (last),
  expires_at_utc, schema_version=1}`. NEVER carries text — the entity
  list is the only conversational handle. PII guarantee identical to
  §10.21.7 spool: text is fetched on-demand from the bus by
  `request_id` if needed, never persisted in the context envelope.
- [x] **Conversation lifetime caps.** `cfg.nlp_conversation_max_turns=8`
  (hard cap; over-cap → context dropped, fresh start, info event);
  `cfg.nlp_conversation_idle_ttl_s=180` (3 min idle → expire);
  `cfg.nlp_conversation_redis_key_prefix="nlp:ctx:"`; per-pod LRU L0 +
  Redis L1 (mirrors §10.23.9 5-component cache key, +`conversation_id`
  as 6th component). Redis-down → fall-through to stateless (NEVER
  block on context).
- [x] **Authority of explicit re-mention.** When the new turn contains
  an entity that conflicts with the carried context (user changes
  team), the new entity wins; carried entities of the same `kind` are
  evicted; `nlp.event.v1{kind=conversation_entity_overridden}` debounced.
  Closed precedence rules in `ai/nlp/conversation/precedence.tr.yaml`.
- [x] **Conversation-id authority.** API gateway (Phase 9) mints
  `conversation_id` per session token (per device, not per user — multi-
  device users get distinct contexts deliberately to avoid cross-device
  surprise). Anonymous users get `conversation_id = null`; NLP runs
  stateless. Boundary test: `test_nlp_anonymous_request_has_no_context`.
- [x] **Adversarial.** Carried context MUST NOT survive a
  `proofreader_blocked` turn (e.g., a slur turn poisoning the next).
  Block → context cleared + `nlp.alert.v1{kind=conversation_context_cleared_after_block, severity=info}`.
- [x] **Tier-aware (Phase 20 hook, dormant).** `cfg.nlp_conversation_enabled_tier_floor=0`
  default 0 (everyone); Phase 20 may flip to gate behind a tier.
- [x] **Proof:** `test_nlp_followup_resolves_entity_from_context`,
  `test_nlp_context_capped_at_max_turns`, `test_nlp_context_idle_ttl_evicts`,
  `test_nlp_explicit_team_mention_overrides_context`,
  `test_nlp_proofreader_block_clears_context`,
  `test_nlp_redis_down_falls_through_to_stateless` (skip-if-no-redis).

#### 10.25.2 Streaming response (SSE / chunked humanizer w/ mid-stream proofreader gate)

- [x] **Real gap §10.7 / §10.8 / §10.9 misses.** Humanizer p95 600 ms is
  acceptable for one-shot but feels broken in a chat UI vs the same
  time spent token-streaming. §10.9 proofreader is whole-answer; if
  applied post-stream, the user has already seen forbidden-phrase
  tokens before they're masked. Naïve streaming = PII / jailbreak echo.
- [x] **Two-pass guarded streaming.** New mode
  `cfg.nlp_answer_streaming=disabled|guarded|off` default `disabled`
  at v1 (rolled out behind explicit operator flag). Under `guarded`:
  (1) template renders deterministically and is **fully** proofread
  via §10.9 → "skeleton" answer; (2) skeleton chunks emitted to client
  immediately as SSE; (3) humanizer runs in parallel on skeleton +
  context, producing "polish" tokens; (4) per-chunk proofreader gate
  (re-run §10.9 gates 2/4/5 — English drift, PII, forbidden-phrase —
  on each accumulated buffer of `cfg.nlp_streaming_proofread_chunk_chars=80`);
  (5) chunk fails gate → stream cuts to skeleton continuation +
  `nlp.alert.v1{kind=streaming_humanizer_chunk_blocked, severity=warn}`.
- [x] **Citation block NEVER streamed.** Citation MUST land as the final
  whole-block frame after humanize completes; if humanize fails mid-
  stream, citation lands attached to the skeleton continuation. AST
  guard: `test_nlp_citation_never_in_streaming_chunk`.
- [x] **Backpressure.** Slow client (write blocks > `cfg.nlp_streaming_write_timeout_ms=2000`)
  → cancel humanize, fall to skeleton-only completion, emit
  `nlp.event.v1{kind=streaming_client_slow_canceled}`. Mirrors Phase 9
  §9.17.4 slow-client doctrine.
- [x] **Cancellation contract.** `predict.cancel.v1` (Phase 9) → also
  cancels the humanize call; in-flight chunks NOT sent after cancel.
  Boundary test: `test_nlp_streaming_honors_predict_cancel`.
- [x] **Cache coherence.** Streamed answers cached as `(chunks[], final)`
  tuple under same §10.23.9 key; cache hit returns the assembled answer
  in one shot (NOT replayed as a stream — re-streaming a cached answer
  fakes "live generation" and is forbidden). AST guard:
  `test_nlp_cached_answer_never_re_streamed`.
- [x] **Proof:** `test_nlp_streaming_skeleton_first_then_polish`,
  `test_nlp_streaming_chunk_blocked_on_pii`,
  `test_nlp_streaming_slow_client_cancels_humanize_in_under_2s`,
  `test_nlp_streaming_disabled_mode_falls_through_to_oneshot`,
  `test_nlp_citation_never_in_streaming_chunk` (AST),
  `test_nlp_cached_answer_never_re_streamed` (AST).

#### 10.25.3 Time-travel audit re-render bundle (forensic reproducibility)

- [x] **Real gap §10.14 / §10.21.7 misses.** Sampled audit captures the
  answer text but not the artifact-snapshot needed to re-render it 6
  months later for legal / regulatory / drift-investigation purposes.
  Re-deriving requires: lexicon snapshot SHAs (all 6+1 files at swap
  generation), `intent.tr.bin.sha256`, `crf.tr.model.sha256`,
  calibration version, template git SHA, `pipeline_version`, fixture
  state from `predict.approved.v1`, `request_id`, normalized text.
- [x] **`nlp_audit_bundle_sha` field added to sampled audit row.** Single
  hex string = sha256 over the canonical-form quintet
  `(lexicon_snapshot_sha, intent_model_sha, crf_model_sha,
  calibration_version, template_git_sha, pipeline_version)`. Acts as a
  pointer; the actual bundle lives in `data/nlp/audit_bundles/<sha>/`
  (immutable; populated on first observation; later requests with the
  same quintet reuse the same dir).
- [x] **Bundle contents.** `manifest.json` (the quintet + UTC timestamp
  of first observation + retention class) + `lexicons/*.tr.yaml.sha256`
  (SHAs only — actual bytes recovered from Phase 16 lexicon feed
  cold-storage by SHA) + `intent.tr.bin.sha256` + `crf.tr.model.sha256`
  + `templates/*.j2.sha256` (resolved against repo `templates/` at
  `template_git_sha`). NEVER the raw model bytes (would explode disk
  + duplicate Phase 16 cold storage).
- [x] **`make nlp.audit-rerender BUNDLE=<sha> REQUEST_ID=...`** runbook
  CLI: fetches the original `qa.request.v1` from Phase 8 backup if
  retention permits, fetches `predict.approved.v1` similarly, rebuilds
  a sandboxed Python venv pinned to the chart compat block of the
  bundle's date, re-renders, asserts byte-equality with the audited
  answer text. Operator-only; logged as `maint.event.v1{kind=nlp_audit_rerender_executed}`.
- [x] **Retention.** Bundle dirs retained `cfg.nlp_audit_bundle_retention_days=2555`
  (7 years — matches `pii_erased` retention floor in §8.3 doctrine for
  legal-hold compatibility). Storage cost negligible (SHAs only, not
  bytes). Per-quintet dedup makes total dir count ≪ total request count.
- [x] **Right-to-erasure interaction.** `quarantine_erase` (§10.25.9)
  nullstamps the audit ROW; bundle dir is unaffected (the bundle
  doesn't contain user PII — it's artifact metadata only).
- [x] **Proof:** `test_nlp_audit_row_carries_bundle_sha`,
  `test_nlp_bundle_quintet_canonical_form_byte_stable`,
  `test_nlp_audit_rerender_dry_run_produces_byte_identical_answer`
  (compose-mode, mocked Phase 8 lookups),
  `test_nlp_bundle_dir_dedupes_across_requests`,
  `test_nlp_bundle_dir_contains_no_raw_user_text`.

#### 10.25.4 Cross-artifact compatibility matrix (lexicon × intent × CRF × calibration × template)

- [x] **Real bug §10.21.1 / §10.21.2 / §10.21.4 misses.** Each artifact
  is SHA-pinned individually but nothing pins their *compatible
  product*. A new `intent.tr.bin` trained on a lexicon snapshot that
  introduced a new market alias may classify queries into a market enum
  value the calibration table doesn't have — silent miscalibration. A
  new template referencing `entity.role_class` (added in §10.24.8)
  paired with an old CRF that doesn't emit it → render-time
  `UndefinedError` under StrictUndefined.
- [x] **`compatibility_matrix.json`** (new file at
  `ai/nlp/_compat/compatibility_matrix.json`, schema_version=1,
  `additionalProperties:false`). One row per `pipeline_version`. Each
  row pins the exact compatible quartet:
  `{pipeline_version, lexicon_set_sha (computed over sorted SHA list of
  all lexicon files at that snapshot), intent_model_sha, crf_model_sha,
  calibration_version_min..max, template_git_sha, humanizer_model_sha,
  introduced_at_utc, retired_at_utc?}`. Append-only; `retired_at_utc`
  set when a row is no longer accepted at boot.
- [x] **Boot-time validator.** NLP agent at startup walks the matrix,
  finds the row matching its current `pipeline_version`, asserts every
  loaded artifact SHA matches; mismatch → refuse boot +
  `nlp.alert.v1{kind=nlp_compatibility_quartet_mismatch, severity=critical, missing: [...]}`.
- [x] **Calibration version range.** Calibration is the only artifact
  that can move forward without a coordinated rollout (new calibration
  every Phase 5 retrain). Each compat row carries `calibration_version_min..max`;
  out-of-range → refuse the specific calibration (degrades to template-
  only mode for that intent group, NEVER renders a half-calibrated
  answer).
- [x] **CI gate.** `make nlp.compat-validate` runs before any PR that
  touches `ai/nlp/lexicon/`, `intent.tr.bin*`, `crf.tr.model*`,
  `ai/nlp/templates/`, or the humanizer pin in chart.json. Refuses
  merge if a new artifact lands without a matching new matrix row.
- [x] **Lockstep with `pipeline_version`.** §10.23.9 cache key already
  includes `pipeline_version`; the matrix bumps `pipeline_version` on
  every quartet change → cache naturally evicts. AST guard:
  `test_nlp_pipeline_version_bumped_when_quartet_changed`.
- [x] **Proof:** `test_nlp_compat_matrix_loaded_at_boot`,
  `test_nlp_compat_quartet_mismatch_refuses_boot`,
  `test_nlp_calibration_out_of_range_degrades_to_template_for_intent_group`,
  `test_nlp_compat_matrix_append_only_no_row_mutation` (AST),
  `test_nlp_pipeline_version_bumped_when_quartet_changed` (CI gate).

#### 10.25.5 Intent-model retraining lifecycle (data sourcing, gating, rollback)

- [x] **Real gap §10.4 misses.** Treats `intent.tr.bin` as an immutable
  SHA-pinned blob. Reality: classifier accuracy decays as fan slang
  evolves; we need a documented retraining loop with safety gates.
- [x] **Data sourcing.** Training corpus assembled from `nlp.shadow.v1`
  weekly continuous-eval samples (§10.23.3) — already PII-scrubbed,
  trunc 200, UNK-replaced, 3-of-5 labelled. NEVER from raw audit logs;
  NEVER from `qa.request.v1` text directly; NEVER from a user-supplied
  upload. Boundary AST: `test_nlp_intent_trainer_imports_only_shadow_v1`.
- [x] **`make nlp.intent-train`** (operator-driven, NEVER CI-auto-trains
  prod) writes a candidate `intent.tr.bin.candidate`; runs §10.18 eval
  harness; refuses to label as candidate if ANY of the §10.18 gates
  regress (intent acc, entity F1, did-you-mean coverage, adversarial
  block, suffix harmony golden) by > `cfg.nlp_intent_retrain_max_regression=0.005`
  on the held-out slice + dialect/code-switch/honorific/negation slices
  added by §10.24.
- [x] **Canary promotion.** Mirrors §10.23.2 model-canary: pod-level env
  flag, 10% sticky on `(account_id // 1000)`; shadow-mode at 1%; 72h
  observation window; promote on `make nlp.intent-promote` only if
  shadow disagreement ≤ 0.03 AND |Δp95 confidence| ≤ 0.05 AND
  continuous-eval (§10.23.3) shows no regression.
- [x] **Rollback runbook.** `make nlp.intent-rollback` swaps the active
  symlink back to the prior SHA-pinned blob; readiness drops + reboots
  pods; emits `maint.event.v1{kind=nlp_intent_rolled_back, from_sha,
  to_sha, reason}`. Time budget: ≤ 15 min from operator decision to
  full cluster on prior model.
- [x] **Calibration coupling.** Every new intent model triggers a
  Platt-recalibration pass on the same shadow slice; the new
  `intent.tr.calibration.json` is pinned in the §10.25.4 compat row.
- [x] **Proof:** `test_nlp_intent_train_refuses_on_regression`,
  `test_nlp_intent_canary_blocks_promote_on_disagreement`,
  `test_nlp_intent_rollback_reverts_within_budget` (compose-mode mock),
  `test_nlp_intent_trainer_data_source_is_shadow_only` (AST),
  `test_nlp_intent_train_writes_candidate_calibration`.

#### 10.25.6 Lexicon contributor governance (PR-gated alias delta, two-reviewer rule)

- [x] **Real gap §10.2 misses.** Added explicit governance: `_aliases_delta.tr.yaml` entries now include `kind`, `source`, `added_by_pr`, and `added_at_utc`; `make nlp.lexicon-build` validates the closed source set and refuses unknown canonical IDs.
- [x] **`ai/nlp/lexicon/_aliases_delta.tr.yaml`** is the only file
  humans edit; CODEOWNERS requires ≥ 1 reviewer for routine adds.
  `markets.tr.yaml` + `entities_negative.tr.yaml` + `dialect.tr.yaml` +
  `phonetic_aliases.tr.yaml` + `offensive.tr.yaml` are
  GENERATED-OR-HIGH-LEVERAGE: any direct edit requires **2 reviewers
  (CODEOWNERS rule)**, one of whom carries the `nlp-curator` GitHub
  team membership. CI: `make verify.nlp-codeowners` enforces.
- [x] **`source` annotation per delta entry.** Every alias_delta row
  carries `{alias, canonical_id, kind, source: <free_text>, added_by_pr,
  added_at_utc}`. `source` must be one of: `tff_official`, `mackolik`,
  `nesine`, `openfootball`, `fan_corpus_<n>`, `operator_curation`. CI
  refuses unknown sources. Catches "someone made up an alias" bugs.
- [x] **Conflict review.** `make nlp.lexicon-build` runs the §10.21.3
  cross-file referential validator BEFORE producing the build artifact.
  Any new alias that maps to a canonical not in LeagueCatalog →
  refuses build. New alias that collides with an existing alias under
  a *different* canonical → refuses build unless a corresponding
  `entities_negative` disambiguator is added in the same PR.
- [x] **Acceptance corpus regression.** `make nlp.lexicon-eval`
  re-runs the §10.18 evaluation harness after lexicon-build but
  BEFORE accepting the diff. Any regression > 0.5% on entity F1 fails
  the PR. Same pattern as intent-model retraining gate (§10.25.5).
- [x] **Per-league quota.** `cfg.nlp_lexicon_max_aliases_per_canonical=12`
  hard cap — defends against "quoting the manager's nickname graph"
  bloat that hurts Symspell precision. Over-quota → CI fail with
  message naming the offending canonical.
- [x] **Proof:** `test_nlp_alias_delta_source_in_closed_set` (CI),
  `test_nlp_high_leverage_files_require_two_reviewers` (CODEOWNERS
  parse), `test_nlp_alias_collision_without_negative_disambiguator_fails_build`,
  `test_nlp_lexicon_eval_regression_blocks_pr`, `test_nlp_alias_per_canonical_quota_enforced`.

#### 10.25.7 Did-you-mean feedback loop (active learning, no PII echo)

- [x] **Real gap §10.4 / §10.6 misses.** "Did-you-mean" abstention is a
  one-way door — the system never learns from which suggestion the
  user accepted. Over time, the same correctable inputs keep hitting
  the abstention path.
- [x] **`qa.feedback.v1`** (data-plane, additive). Producer = API
  gateway (Phase 9, when the user clicks a suggestion or re-types
  within 30s of a `did-you-mean`); consumer = `nlp.dispatcher.v1` →
  active-learning queue. Schema:
  `{request_id, did_you_mean_offered_intents[], accepted_intent (or
  null if user retyped instead), original_qa_correlation_id,
  schema_version=1}`. NEVER carries text — accepted_intent is one of
  the closed enum values.
- [x] **Active-learning queue.** Bounded ring buffer
  `cfg.nlp_active_learning_queue_max=10000` per pod; oldest evicted
  when full + `nlp.event.v1{kind=active_learning_queue_overflow}`
  debounced. Spilled to disk weekly via `make nlp.active-learning-spill`
  (operator-driven, mirrors §10.23.3 weekly cron).
- [x] **Active-learning data hygiene.** Spilled rows are PII-scrubbed
  identically to §10.23.3 shadow rows; same 3-of-5 labeller agreement
  required before promotion into intent-retrain corpus (§10.25.5).
  Active-learning data is ONLY one input among many — never the sole
  source for a retrain (defends against feedback loops where an early
  classifier mistake re-trains itself).
- [x] **Suggestion provenance.** `did_you_mean_offered_intents[]` MUST
  match exactly what was rendered to the user; mismatch in
  `qa.feedback.v1` (e.g., user accepted an intent that wasn't offered)
  → drop + `nlp.alert.v1{kind=feedback_provenance_mismatch, severity=warn}`.
  Defends against client-side tampering.
- [x] **NEVER personalise.** Feedback signal aggregates across users
  only (no per-user adaptation in v1). AST guard:
  `test_nlp_feedback_processor_does_not_branch_on_user_id`.
- [x] **Proof:** `test_nlp_feedback_v1_schema_round_trip`,
  `test_nlp_feedback_provenance_mismatch_dropped`,
  `test_nlp_feedback_queue_overflow_evicts_oldest`,
  `test_nlp_feedback_processor_does_not_branch_on_user_id` (AST),
  `test_nlp_feedback_spill_pii_scrubbed_identically_to_shadow`.

#### 10.25.8 Lexicon coverage telemetry (entity-hit-rate as drift leading indicator)

- [ ] **Real gap §10.14 / §10.22.13 misses.** Tracks input-repair density
  (a quality-of-input signal) but NOT lexicon coverage (a quality-of-
  lexicon signal). When a new fan-coined nickname ("Cimbom Junior" for
  a youth player who debuted last week) hits 10% of queries before the
  lexicon ships an alias, we have no leading signal — we only see the
  downstream rise in `did-you-mean` and `meta.unsupported`.
- [ ] **`nlp_lexicon_coverage` histogram.** Per-intent-class buckets
  `{0.0, 0.25, 0.5, 0.75, 1.0}` — fraction of resolvable-class tokens
  in the input that hit the gazetteer (numerator = gazetteer-hit
  tokens of class team/player/league/competition/market; denominator
  = all "content" tokens after stopword strip). Computed per query;
  exported to telemetry.v1.
- [ ] **`nlp_unresolved_token_top_k`** (rolling, capped at
  `cfg.nlp_unresolved_token_top_k=50` per hour, PII-scrubbed via the
  long-string heuristic from §10.21.7). Operators see "the 50 most
  common tokens we couldn't resolve last hour" → directly actionable
  alias_delta candidates. Capped count + per-token sha8 prevents
  exfiltration vector. Reset hourly.
- [ ] **Drift alerts.** `cfg.nlp_lexicon_coverage_p50_floor=0.6` per
  intent class on a 1h sliding window; sustained breach for > 30 min
  → `nlp.alert.v1{kind=lexicon_coverage_below_floor, intent_class,
  observed_p50, severity=warn}`. Multiple intent classes breaching
  simultaneously upgrades to `severity=error` (likely lexicon
  catastrophe — Phase 16 feed corruption suspected).
- [ ] **Coverage staleness.** `cfg.nlp_lexicon_max_age_days=14`; lexicon
  files unchanged for that long → daily `nlp.alert.v1{kind=lexicon_stale,
  severity=info}`. Catches "Phase 16 feed pipeline silently broke
  upstream" weeks earlier than coverage drift would.
- [ ] **Proof:** `test_nlp_coverage_histogram_per_intent_class`,
  `test_nlp_unresolved_top_k_pii_scrubbed_and_capped`,
  `test_nlp_coverage_below_floor_alert_fires`,
  `test_nlp_lexicon_stale_alert_after_14_days` (mock clock).

#### 10.25.9 End-to-end right-to-erasure (Phase 8 → NLP audit + L1 cache + spool)

- [ ] **Real gap §10.21.7 misses.** Pins NLP audit redaction whitelist
  but never wires `quarantine_erase` (§8.3 / §8.16) through to NLP's
  on-disk state. A user erasure request leaves `nlp_audit_log` rows
  with `qa_correlation_id` linkable to the now-erased predictor row,
  L1 `cache.v1` answer entries cache-keyed on `(user_id_h, ...)`, and
  spool envelopes in `data/nlp/spool/` carrying `qa_correlation_id`.
- [ ] **NLP subscribes to `maint.event.v1{kind=quarantine_erase}`** (the
  ack contract was already defined in §8.0; this is the real consumer
  for the NLP plane). On receipt: (a) `UPDATE nlp_audit_log SET ...
  user_id_h=NULL, qa_correlation_id_h=hash(qa_correlation_id) WHERE
  user_id_h=<target>`; (b) `redis.del(cache:answer:<user_id_h>:*)` via
  `SCAN+UNLINK` (cap `cfg.nlp_erase_scan_batch=500`); (c) walk
  `data/nlp/spool/` for envelopes with matching `user_id_h` → `unlink`.
  Emits `maint.ack.v1{accepted=true, accepted_by="nlp.audit.v1"}` on
  completion or `accepted=false` w/ reason on failure.
- [ ] **Idempotency.** Multiple erase events for the same `user_id_h`
  → second is a no-op (no rows match) but STILL acks success.
  Mirrors §8.1 denylist_clear idempotency lesson.
- [ ] **Audit-bundle dirs untouched.** §10.25.3 bundles contain artifact
  metadata only — no user PII — so erase does not propagate there.
  Pinned doctrine; documented in `nlp_runbook.md`.
- [ ] **Conversation context erase.** `qa.context.v1` Redis state is
  also erased: `redis.del(nlp:ctx:<conversation_id>)` for every
  conversation_id linked to the erased user (linkage table
  `data/nlp/conversation_index.sqlite` or Redis sorted set, single-
  source choice pinned in `cfg.nlp_conversation_index_backend ∈
  {redis, sqlite}` default `redis`).
- [ ] **Proof:** `test_nlp_quarantine_erase_nullstamps_audit_row`,
  `test_nlp_quarantine_erase_evicts_l1_cache`,
  `test_nlp_quarantine_erase_unlinks_spool_envelopes`,
  `test_nlp_quarantine_erase_idempotent_on_already_erased`,
  `test_nlp_quarantine_erase_clears_conversation_context`,
  `test_nlp_quarantine_erase_emits_ack` (per §8.0 ack contract).

#### 10.25.10 Per-tenant compliance ban-list overlay (advertiser / legal carve-outs)

- [ ] **Real gap.** Some deployments need to suppress specific terms in
  rendered answers (advertiser conflicts: "rakip bahis sitesi adı";
  legal: a banned trademark; defamation-safe: a player accused of an
  offence). §10.22.9 offensive-language gate is global; per-tenant
  carve-outs are an orthogonal axis.
- [ ] **`ai/nlp/compliance/banlist.tr.yaml`** (per-tenant; structure:
  `tenant_id: [{term, action ∈ {redact, refuse, replace_with},
  replace_text?, expires_at_utc?, source_pr_url, added_by, added_at}]`).
  Atomic-swap mtime-poll (mirrors §10.2 lexicon discipline; distinct
  lock); `cfg.nlp_compliance_reload_s=60`; SHA-pinned per snapshot.
- [ ] **Render-time only.** Ban-list applied AFTER §10.9 proofreader,
  BEFORE returning to API gateway. NEVER fed to classifier or entity
  extractor — keeps the classifier tenant-blind (mirrors §10.0
  Phase 20 doctrine: NLP is tier-blind; same applies to compliance).
- [ ] **`refuse` action.** Replaces the entire answer with a closed-
  template `meta.compliance_refused.<locale>.j2` ("Bu konuda bilgi
  veremiyoruz."). Citation block preserved. `nlp.event.v1{kind=
  compliance_refusal_triggered, tenant_id_h, term_sha8}` (term itself
  NEVER logged — only its sha8 prefix).
- [ ] **`redact` / `replace_with`.** Token-level substitution on the
  rendered answer string; multiple substitutions applied in a single
  pass (sorted by `len(term) desc` — longest first, prevents partial
  overlap pathology). AST guard: substitution code uses no regex on
  user-controlled patterns (defends against ReDoS via tenant config).
- [ ] **Cache-key extension.** `(tenant_id, banlist_snapshot_sha)`
  added as the 7th + 8th components of the §10.23.9 cache key (was 5,
  context made 6, ban-list makes 7-8). Atomic ban-list swap evicts
  cache for that tenant naturally.
- [ ] **Proof:** `test_nlp_banlist_redacts_term_in_rendered_answer`,
  `test_nlp_banlist_refuse_returns_closed_template_with_citation`,
  `test_nlp_banlist_substitution_longest_first_no_partial_overlap`,
  `test_nlp_banlist_never_seen_by_classifier_or_extractor` (AST),
  `test_nlp_banlist_term_never_logged_in_clear` (AST + log-filter probe),
  `test_nlp_banlist_swap_evicts_per_tenant_cache`.

#### 10.25.11 Boot-dependency graph (Phase 5 cold-start, GPU-lease leak on humanizer crash)

- [ ] **Real gap §10.21.9 misses.** Boot stages 1-6 cover NLP-internal
  state but the pipeline is unusable until Phase 5 `consensus.v1` is
  emitting `predict.approved.v1` for AT LEAST a smoke-set of fixtures.
  At cluster cold-start (compose-up or K8s rolling deploy), NLP can
  pass readiness while consensus is still warming → 503-but-200
  paradox: `/v1/qa` accepts the request, fans out `predict.request.v1`,
  times out, returns degraded.
- [ ] **Boot stage 6.5 added.** `consensus_smoke_observed`: NLP at boot
  publishes a single canary `predict.request.v1{match_id=<sentinel>,
  market=1x2, request_id=nlp-boot-canary-<pod>, qa_correlation_id=null}`
  and waits up to `cfg.nlp_boot_consensus_smoke_timeout_s=10` for the
  matching `predict.approved.v1`. Success → readiness 200. Timeout →
  readiness stays 503 + `nlp.alert.v1{kind=nlp_consensus_smoke_failed,
  severity=warn}` (warn not critical — cluster-wide cold start can
  validly take longer; auto-promotes to critical at 60s via
  `cfg.nlp_boot_consensus_smoke_critical_s=60`).
- [ ] **Sentinel match.** `cfg.nlp_boot_consensus_sentinel_match_id="nlp:boot:canary"`
  recognised by Phase 5 consensus as a fast-path response (returns a
  pre-canned `predict.approved.v1` with `degraded=true,
  degraded_reason=boot_canary` — never hits real predictors). Boundary
  test in Phase 5: `test_consensus_recognises_nlp_boot_canary`.
- [ ] **GPU-lease leak on humanizer crash.** §10.21.4 breaker is
  per-pod; §10.0 says lease via Phase 11. If the humanizer subprocess
  crashes (segfault on bad input, OOM kill), the in-process Python
  agent process MAY survive but the GPU lease record in Redis is
  orphaned for `cfg.compute_lease_ttl_s` (Phase 11 default 600s),
  blocking the next pod's lease acquisition. Real bug.
- [ ] **Subprocess supervisor.** Humanizer runs in a `multiprocessing.Process`
  child supervised by the agent (mirrors `aitext.v1` Phase 11 pattern,
  if not already pinned, this section pins it). Child death detected
  via `Process.exitcode != None`; supervisor immediately
  releases the GPU lease (Redis `DEL compute:lease:nlp.humanizer.v1:<pod>`),
  emits `nlp.alert.v1{kind=humanizer_subprocess_died, exitcode,
  severity=error}`, opens the §10.21.4 breaker for the rest of the
  breaker window (recovery via §10.10 "humanizer fail" row → template
  fallback), and respawns child after `cfg.nlp_humanizer_respawn_cooldown_s=30`.
  AST guard: `test_nlp_humanizer_runs_in_subprocess_not_thread`.
- [ ] **Proof:** `test_nlp_readiness_503_until_consensus_smoke`,
  `test_nlp_consensus_smoke_promotes_to_critical_at_60s`,
  `test_consensus_recognises_nlp_boot_canary` (Phase 5),
  `test_nlp_humanizer_subprocess_death_releases_gpu_lease`,
  `test_nlp_humanizer_subprocess_death_opens_breaker`,
  `test_nlp_humanizer_runs_in_subprocess_not_thread` (AST).

#### 10.25.12 Summary fan-out overflow (matchday > nlp_summary_max_fixtures)

- [ ] **Real bug §10.6 misses.** `cfg.nlp_summary_max_fixtures=10` cap
  silently truncates a Saturday with 9 Süper Lig + 6 1.Lig fixtures;
  the user sees "10 maç" but doesn't know 5 were dropped. Worse:
  truncation is FIFO by `predict.request.v1` arrival order — non-
  deterministic across pods.
- [ ] **Salience-ranked overflow.** When fixture count > cap, NLP
  computes a salience score per fixture and selects top-N. Single-
  source `ai/nlp/dispatcher/salience.py::compute_salience(fixture) ->
  float` over the closed feature set: `(league_tier from LeagueCatalog,
  is_derby from `derbies.tr.yaml`, kickoff_proximity_to_query_time,
  prior_user_team_mentions_in_conversation_context (§10.25.1))`.
  Deterministic; tie-break on `match_id` lex-sort. AST guard:
  `test_nlp_salience_inputs_in_closed_set`.
- [ ] **Explicit Turkish disclosure.** Answer carries
  `truncated_count=N, top_n_by="öncelik (lig sıralaması, derbi, saat)"`
  + a closed-template line: "Bu hafta {total} maç var; en öne çıkan
  {n} tanesini özetledim. Diğerleri için lig listelerine bakabilirsiniz."
  NEVER silent truncation. AST: `test_nlp_summary_truncation_disclosed_in_answer`.
- [ ] **Hard upper cap.** `cfg.nlp_summary_max_fixtures_hard=20` (cap
  on cap — at this size even salience-ranked output is too long for
  template clarity). Over the hard cap → degrade entirely to a list-
  only meta answer with the disclosure + a per-league link table.
- [ ] **Caching.** Salience-ranked top-N cache key includes
  `query_time_bucket=hour-truncated` and the closed feature set hash,
  so the same query 5 minutes later hits the same cache entry.
- [ ] **Proof:** `test_nlp_summary_overflow_uses_salience_not_fifo`,
  `test_nlp_summary_truncation_disclosed_in_answer`,
  `test_nlp_summary_hard_cap_degrades_to_list_meta`,
  `test_nlp_salience_deterministic_across_pods`,
  `test_nlp_salience_inputs_in_closed_set` (AST).

#### 10.25.13 Religious / national holiday calendar in date resolver

- [ ] **Real gap §10.5 / §10.22.6 misses.** Date resolver covers "yarın"
  / "cuma" / "27 Nisan saat 21:30" but NOT culturally-grounded Turkish
  date references: "bayramda maç var mı" (Ramazan / Kurban — moving
  dates), "Cumhuriyet Bayramı'nda kim oynar" (29 Ekim, fixed), "milli
  maç haftası" (FIFA windows — moving). These return `meta.unsupported`
  today, which is a fan-visible quality bug.
- [x] **`ai/nlp/dates/holidays_tr.yaml`** (single-source).  Each entry:
  `{key (closed enum: ramazan_bayrami | kurban_bayrami | yilbasi |
  cumhuriyet_bayrami | zafer_bayrami | gencler_bayrami |
  ulusal_egemenlik | demokrasi_bayrami), name_tr, name_aliases[],
  date_kind ∈ {fixed_gregorian, fixed_hijri_observed, fifa_window},
  fixed_md? (e.g., "10-29"), hijri_year_lookup? (per-year computed
  by `ai/nlp/dates/hijri.py` — vendored deterministic lookup, NEVER
  network), fifa_window_lookup? (per-year from `openfootball` feed
  cached locally + SHA-pinned per year)}`.
- [x] **Lookup horizon.** `cfg.nlp_holiday_lookup_horizon_days=540`
  (~18 months — covers any "next year's bayram" query). Refuses to
  resolve dates beyond horizon → falls back to numeric-date prompt.
- [ ] **Hijri determinism.** `hijri.py` is a vendored table for the next
  20 years (small file, ~400 rows, SHA-pinned in chart compat block);
  table generated by `make nlp.hijri-rebuild` from a deterministic
  astronomical algorithm (Umm al-Qura observed dates), NEVER from a
  live API. Per-year discrepancy with Turkey's official calendar
  (Diyanet) noted in a `_diyanet_overrides.tr.yaml` allow-list.
- [ ] **FIFA window cache.** Per-year `data/nlp/fifa_windows/<year>.json`
  populated from openfootball feed at lexicon-build time; SHA-pinned;
  fallback if file absent → `meta.unsupported` (NEVER guess).
- [ ] **Holiday-as-context.** When holiday entity is present + "maç var
  mı" intent, dispatcher routes to `data.fixture_lookup` with
  `(start_utc, end_utc)` derived from the holiday's resolved date
  range. Fan-friendly UX without changing intent enum.
- [ ] **Proof:** `test_nlp_resolves_ramazan_bayrami_2026`,
  `test_nlp_resolves_cumhuriyet_bayrami_fixed_date`,
  `test_nlp_resolves_fifa_window_from_openfootball_cache`,
  `test_nlp_holiday_beyond_horizon_returns_meta_unsupported`,
  `test_nlp_hijri_table_sha_pinned_in_chart`,
  `test_nlp_diyanet_override_table_respected`.

#### 10.25.14 Knob inventory + new event/alert kinds + DoD additions

- [ ] **New cfg knobs (~22):** `nlp_conversation_max_turns=8`,
  `nlp_conversation_idle_ttl_s=180`, `nlp_conversation_redis_key_prefix="nlp:ctx:"`,
  `nlp_conversation_enabled_tier_floor=0`, `nlp_conversation_index_backend="redis"`,
  `nlp_answer_streaming="disabled"`, `nlp_streaming_proofread_chunk_chars=80`,
  `nlp_streaming_write_timeout_ms=2000`, `nlp_audit_bundle_retention_days=2555`,
  `nlp_intent_retrain_max_regression=0.005`,
  `nlp_active_learning_queue_max=10000`, `nlp_unresolved_token_top_k=50`,
  `nlp_lexicon_coverage_p50_floor=0.6`, `nlp_lexicon_max_age_days=14`,
  `nlp_erase_scan_batch=500`, `nlp_compliance_reload_s=60`,
  `nlp_boot_consensus_smoke_timeout_s=10`,
  `nlp_boot_consensus_smoke_critical_s=60`,
  `nlp_boot_consensus_sentinel_match_id="nlp:boot:canary"`,
  `nlp_humanizer_respawn_cooldown_s=30`,
  `nlp_summary_max_fixtures_hard=20`,
  `nlp_holiday_lookup_horizon_days=540`,
  `nlp_lexicon_max_aliases_per_canonical=12`. Plus 8 feature-flag
  toggles (one per §10.25.1–§10.25.13 sub-section, default `false`
  except `nlp_conversation_enabled=true`). Triangle test extends.
  Go-side `TestEnvSync` covers `nlp_humanizer_respawn_cooldown_s` and
  the streaming knobs (Phase 9 SSE handler will read them).
- [ ] **New `qa.context.v1` topic** registered in §3.5 wire authority
  (additive). Producer set bounded to `nlp.dispatcher.v1`; consumer
  bounded to `nlp.intent.v1`. `additionalProperties:false` schema.
- [x] **New `qa.feedback.v1` topic** registered in §3.5 wire authority
  (additive). Producer set bounded to `api.gateway.v1`; consumer
  bounded to `nlp.dispatcher.v1`. `additionalProperties:false` schema.
- [ ] **New `nlp.event.v1` kinds** (open-enum, registered):
  `conversation_entity_overridden`, `streaming_client_slow_canceled`,
  `active_learning_queue_overflow`, `compliance_refusal_triggered`,
  `nlp_intent_rolled_back`, `nlp_audit_rerender_executed`. Per-kind
  sub-schemas under `ai/swarm/sdk/schemas/nlp.event.v1/<kind>.json`.
- [ ] **New `nlp.alert.v1` kinds** (open-enum, registered):
  `conversation_context_cleared_after_block` (info),
  `streaming_humanizer_chunk_blocked` (warn),
  `nlp_compatibility_quartet_mismatch` (critical),
  `feedback_provenance_mismatch` (warn),
  `lexicon_coverage_below_floor` (warn / error on multi-class),
  `lexicon_stale` (info),
  `nlp_consensus_smoke_failed` (warn → critical at 60s),
  `humanizer_subprocess_died` (error).
- [ ] **DoD proof tests aggregate** (new in §10.25, all required for
  Phase 10 closure):
  - §10.25.1 — 6 tests (multi-turn context)
  - §10.25.2 — 6 tests (streaming + AST guards)
  - §10.25.3 — 5 tests (audit bundle + re-render)
  - §10.25.4 — 5 tests (compatibility matrix)
  - §10.25.5 — 4 tests (intent retrain lifecycle)
  - §10.25.6 — 5 tests (lexicon governance)
  - §10.25.7 — 5 tests (feedback loop)
  - §10.25.8 — 4 tests (coverage telemetry)
  - §10.25.9 — 6 tests (right-to-erasure end-to-end)
  - §10.25.10 — 6 tests (compliance ban-list)
  - §10.25.11 — 6 tests (boot dependency + GPU-lease)
  - §10.25.12 — 5 tests (summary overflow salience)
  - §10.25.13 — 6 tests (holiday calendar)
  - **Total: ≈ 69 new proof tests added on top of §10.21/§10.22/§10.23/§10.24
    aggregate.** Cumulative Phase 10: ≈ 320+ proof tests.
- [ ] **Chart compatibility additions.** Pin Unicode TR39 confusables
  rev (already in §10.21), `hijri.py` vendored table SHA, openfootball
  FIFA-window seed SHA, Diyanet override table SHA. Pin
  `python-multiprocessing` semantics by recording the host glibc
  version range that was tested for subprocess supervisor (defends
  against silent fork() vs spawn() differences).
- [ ] **`make swarm.demo.nlp.full`** extends to exercise (within the
  ≤ 60s compose budget, tightening from §10.23.13 baseline): (a) one
  multi-turn conversation (3 turns); (b) one streaming response
  (asserting skeleton-first then polish); (c) one re-render via
  `make nlp.audit-rerender` of a synthetic audit bundle; (d) one
  intent-rollback dry-run; (e) one compliance refuse triggered; (f)
  one summary overflow with disclosure rendered; (g) one holiday-
  context query ("bayramda maç var mı") resolved.
- [ ] **Documentation.** `docs/design/TURKISH_NLP.md` gains five new
  sections: "Conversational Context", "Streaming Response", "Audit
  Re-render Bundles", "Lexicon Contributor Guide", "Holiday Calendar".
  `docs/guides/nlp_runbook.md` gains: "Intent rollback runbook",
  "Right-to-erasure runbook", "Compliance ban-list operator workflow",
  "Cold-start consensus-smoke triage", "GPU-lease leak recovery".
