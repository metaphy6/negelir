# Phase 10 §10.27 — Match-lifecycle, abuse-resilience, regulatory compliance, operator tooling

> **Provenance.** Carved out of `docs/planning/ROADMAP.md` Phase 10 on the Phase 10 split (post-13th-pass) so the ROADMAP stays navigable. Content here is the **binding** Phase 10 contract; ROADMAP §10 now points at this folder. Any edit must update `xops/versioning/chart.json` (`docs` minor) and the tracker (per AGENTS.md §3 + §6.1). Cross-phase references (Phase 5/7/8/9/11/12/13a/14/16/19/20) remain authoritative against ROADMAP and the matching `docs/design/*.md` anchors.


### 10.27 Match-lifecycle, abuse-resilience, regulatory compliance, and operator tooling (binding addendum)

> Mirrors the §10.21–§10.26 pattern. **Eighth** Phase 10 design pass.
> §10.21 = integrity floor; §10.22 = TR-language correctness; §10.23 =
> production serving; §10.24 = TR-input completeness; §10.25 =
> lifecycle / conversation / time-travel; §10.26 = morphology /
> input modality / counterfactual; §10.27 = **match-lifecycle, abuse,
> regulatory, operator tooling** — the residue that turns "a system
> that handles a single pre-match Turkish query well" into "a system
> that survives live football matches, production incidents, evolving
> client SDKs, and Turkish law". Every `[ ]` here is binding for
> Phase 10 DoD (per §10.20 item 25). New cfg knobs land alongside
> §10.19 in the same triangle commit.

#### 10.27.1 Fixture-state machine (binding closed enum) and dispatch routing

- [x] **Closed enum.** `ai/common/fixture_state.py::FixtureState`
  ∈ `{scheduled, prematch_locked, in_play_first_half, halftime,
  in_play_second_half, in_play_extra_time, penalty_shootout,
  finished, postponed, suspended, abandoned, cancelled, awarded,
  unknown}` (14 values, schema_version=1, additive-only). Source
  of truth: Phase 4 storage agent's `match_normalized.state` field
  (extended additively); LeagueCatalog never emits these — they
  are runtime computed from the upstream feed by the datasource
  layer (Phase R1). NLP **never** infers state from kickoff_time
  alone (real bug class: a 21:00 kickoff with a 90-minute delayed
  start would otherwise be silently treated as "scheduled" at
  21:30 and route to pre-match predictors).
- [x] **Lookup contract.** `nlp.dispatcher.v1` calls
  `FixtureStateLookup.get(match_id) → (state, as_of_utc, source)`
  via `data.request.v1{kind=fixture_state}` (NEW kind under the
  closed `data.request.v1` kind enum — additive). Reply MUST
  arrive within `cfg.nlp_fixture_state_lookup_timeout_ms=250`
  (deadline-propagated from `nlp_pipeline_timeout_ms`); on
  timeout → fall through to `unknown` with explicit
  `degraded_reason=fixture_state_unknown`. **NEVER** assume
  `scheduled` as a default — that would silently re-enable the
  pre-match predictor on a postponed match.
- [x] **Routing matrix (binding, deterministic, table-driven in
  `ai/nlp/dispatch/fixture_state_routing.yaml`):**

  | State | `predict.*` intents | `data.*` intents | `summary.*` intents |
  |---|---|---|---|
  | `scheduled` / `prematch_locked` | route normally | route normally | route normally |
  | `in_play_*` / `halftime` / `penalty_shootout` | **REFUSE** → `meta.live_match_unsupported` template (humanizer-bypassed, Turkish "Maç şu an oynanıyor; canlı tahmin sunmuyorum, mevcut skoru paylaşırım") + auto-route the underlying match-id to `data.request.v1{kind=live_state}` | route to `data.request.v1{kind=live_state}` (NEW kind, additive) | refuse for affected fixture; remainder of summary proceeds |
  | `finished` | route to `data.request.v1{kind=h2h}` w/ outcome — NEVER `predict.*` | route normally | route normally |
  | `postponed` / `suspended` | refuse → `meta.fixture_postponed` template w/ new kickoff if known else `meta.fixture_postponed_unknown_reschedule` | route to `data.fixture_lookup` w/ explicit Turkish "ertelendi" disclosure | exclude from summary; mention in disclosure |
  | `abandoned` | refuse → `meta.fixture_abandoned` (rare; UEFA crowd-trouble cases) | route w/ disclosure | exclude w/ disclosure |
  | `cancelled` / `awarded` | refuse → `meta.fixture_cancelled` (awarded carries forfeit context) | route w/ awarded result if applicable | exclude |
  | `unknown` | refuse → `meta.fixture_state_unknown` (degraded) | route w/ degraded flag | refuse for affected fixture |

  AST `test_nlp_dispatcher_consults_fixture_state_before_predict`
  — every dispatcher branch that constructs `predict.request.v1`
  must be preceded by a `FixtureStateLookup.get` call; ordered by
  control-flow traversal not source-line ordering.
- [x] **`data.request.v1{kind=live_state}` is a new closed kind**
  (additive, schema_version=1; consumer = Phase 4 storage agent's
  Pivot R1 successor). Out of scope for v1: betting markets on
  live state — that is a Phase 22+ capability and explicitly
  reserved (CLAUDE.md doctrine: never route a "live tahmin?"
  query to a predictor that has never seen a live state).
- [x] **`meta.live_match_unsupported`, `meta.fixture_postponed`,
  `meta.fixture_postponed_unknown_reschedule`,
  `meta.fixture_abandoned`, `meta.fixture_cancelled`,
  `meta.fixture_state_unknown`** added to the §10.4 closed intent
  enum (additive; intent classifier never emits these — they are
  *router-injected* terminal intents). `make verify.nlp-templates`
  asserts a `<intent>.tr.j2` exists for each.
- [x] **Idempotency under state change mid-RPC.** If the
  predictor RPC was already in flight when state flipped to
  `in_play_*` (kickoff happened during `predict.request →
  predict.approved` hop), the dispatcher discards the
  `predict.approved.v1` on arrival and emits the live-match
  refusal instead. New `nlp.event.v1{kind=fixture_state_flipped_during_rpc}`
  carries `(match_id, prior_state, new_state, rpc_age_ms)` —
  PII-clean, bounded cardinality (state pairs only).
- [x] **Proof tests** (≥ 14 deterministic):
  `test_dispatcher_refuses_predict_on_in_play_state`,
  `test_dispatcher_routes_live_query_to_live_state_kind`,
  `test_dispatcher_treats_unknown_state_as_refuse_not_scheduled`,
  `test_dispatcher_postponed_routes_to_fixture_postponed_template`,
  `test_dispatcher_finished_routes_to_h2h_not_predict`,
  `test_dispatcher_abandoned_distinct_from_cancelled`,
  `test_dispatcher_awarded_carries_forfeit_context`,
  `test_dispatcher_state_lookup_timeout_falls_through_to_unknown`,
  `test_dispatcher_consults_state_before_every_predict_request_ast`,
  `test_dispatcher_state_flip_mid_rpc_discards_prediction`,
  `test_dispatcher_state_flip_mid_rpc_emits_event`,
  `test_summary_excludes_postponed_fixture_with_disclosure`,
  `test_meta_live_match_unsupported_template_humanizer_bypassed`,
  `test_fixture_state_routing_yaml_matches_enum_completeness`.

#### 10.27.2 Calibration-vs-fixture-state freshness gate

- [x] **Real bug** the prior 7 passes missed: §10.21.10 pinned
  confidence-band stability for *probability* values but did not
  check that the calibration profile's *training horizon* is
  appropriate for the fixture's current state. Concretely: a
  pre-match calibration trained on minute-0 features will
  silently apply to a "what's the probability now?" query at
  minute 65 — answer would be probabilistically nonsensical.
- [x] **Calibration freshness contract.** Every
  `predict.approved.v1` carries
  `calibration_state_horizon ∈ {prematch, live, both}`
  (additive on the existing schema_version 2 → 3; mirrors §10.0
  `degraded` round-trip). NLP rejects any approval whose horizon
  does not match the fixture's current state at answer-render
  time — emits `meta.calibration_horizon_mismatch` template and
  one `nlp.alert.v1{kind=calibration_horizon_mismatch, severity=error}`
  (debounced 300s per `(profile_id, state_class)` to bound
  cardinality). State change between RPC start and render time is
  the §10.27.1 case and takes precedence.
- [x] **Backstop for v1.** Phase 5 / Phase 16 only train pre-match
  calibrations at v1 (live calibration is a Phase 22+ deliverable);
  setting `cfg.nlp_calibration_horizon_strict=true` (default true)
  hard-rejects any approval with `horizon != prematch` for v1
  delivery — defense in depth against an upstream miswiring.
- [x] **Proof tests** (≥ 5):
  `test_nlp_rejects_live_horizon_calibration_in_v1`,
  `test_nlp_rejects_prematch_horizon_on_in_play_fixture`,
  `test_nlp_alert_calibration_horizon_mismatch_debounced`,
  `test_nlp_calibration_horizon_round_trip_through_qa_answer`,
  `test_nlp_calibration_horizon_strict_default_true_in_config_sync`.

#### 10.27.3 Forensic incident response — complaint trace rebuild

- [x] **Real operator gap** — §10.25.3 ships time-travel re-render
  but only by `nlp_audit_bundle_sha`; no operator workflow goes
  from "user complaint → re-render". Add `make nlp.complaint-trace
  REQUEST_ID=<uuidv7>` (new xops/makefile/nlp.py command). Resolves
  request_id → audit row → bundle_sha → re-render → byte-identical
  comparison against the audit-stamped output → exit 0 (match) or
  exit 7 (drift) with a unified-diff report at
  `data/nlp/complaint_traces/<request_id>/diff.txt`. PII-redacted
  per §10.21.7 PIIScrubFilter.
- [x] **Audit row resolution.** request_id (UUIDv7, sortable
  timestamp prefix per Phase 9 §9.1) → audit-CSV scan bounded to
  the 24h window centred on the embedded timestamp (rejects
  unbounded scans → operator paste-error defense). >1 match raises
  `RequestIdCollision` (real but extremely rare per UUIDv7);
  operator flag `--strict-uniqueness=false` allows the latest.
- [x] **No PII in the trace dir.** Bundle sha + canonical inputs
  only; original user text **never** materialised on disk
  (mirrors §10.21.7 spool discipline). When the original text is
  needed for a deeper investigation, separate operator-confirmed
  workflow `make nlp.complaint-trace-with-text REQUEST_ID=...
  --confirm-pii` (typed-token confirmation gate, mirrors §8.1/§8.9
  doctrine; emits `maint.event.v1{kind=nlp_pii_recovered_for_trace,
  operator_id_h, request_id, reason_text_sha8}` audit row to
  `maint_audit_log` — operator accountability).
- [x] **Proof tests** (≥ 6):
  `test_complaint_trace_byte_identical_when_artifacts_pinned`,
  `test_complaint_trace_exit_7_on_drift`,
  `test_complaint_trace_collision_strict_default`,
  `test_complaint_trace_no_raw_text_in_output_dir_default_path`,
  `test_complaint_trace_with_text_requires_confirm_pii_token`,
  `test_complaint_trace_with_text_emits_pii_recovered_audit_row`.

#### 10.27.4 In-flight bad-batch kill switch

- [x] **Operator runbook step that does not exist today.** When
  the proofreader has a regression / template renders an
  unintended phrase / humanizer leaks an offensive token through
  the §10.22.9 gate, the only available action is "wait for the
  next deploy". Add `ops.nlp-kill-pattern` (new opsctl
  subcommand under §8 maint surface): operator submits a
  pattern-pack `{template_id?, intent_class?, lexicon_hit?,
  body_substring_sha8?, ttl_s ≤ cfg.opsctl_nlp_kill_max_ttl_s=3600}`
  via the standard maint envelope; NLP pods subscribe to
  `maint.event.v1{kind=nlp_kill_pattern_armed}` and rewrite any
  matching in-flight or cache-hit answer to the
  `meta.temporarily_unavailable` template until TTL expiry.
- [x] **Cache invalidation.** Arming a kill-pattern publishes a
  bumped `cache:nlp:kill_gen` counter; L0 (§10.23.9) and L1
  caches treat all stored answers as stale until the next
  successful render confirms the new gen does not match.
  Operator-driven; not a freshness signal.
- [x] **Audit + sec.alert.** Every armed pattern emits
  `maint.event.v1{kind=nlp_kill_pattern_armed,operator_id_h,
  pattern_pack_sha8,ttl_s}` and one
  `sec.alert.v1{kind=nlp_kill_pattern_armed,severity=warn,
  event_correlation_id=<maint_request_id>}` (per §8.16.9 dual-emit
  doctrine). Auto-disarmed at TTL expiry → matching `_disarmed`
  events. **No silent armed kill-patterns** — boot-time validator
  refuses start if a `armed` row exists past its TTL (operator
  forgot to disarm, system would silently filter forever).
- [x] **Closed scope.** Pattern-pack matching is **deterministic
  and bounded**: substring-sha8 only (no live regex compile —
  defends against operator-supplied catastrophic backtracking),
  intent_class ∈ closed §10.4 enum, template_id ∈ closed registry,
  lexicon_hit canonical_id only. AST guard
  `test_nlp_kill_pattern_pack_no_regex_compile_path`.
- [x] **Proof tests** (≥ 7):
  `test_kill_pattern_armed_rewrites_inflight_render`,
  `test_kill_pattern_armed_rewrites_cache_hit`,
  `test_kill_pattern_auto_disarms_at_ttl`,
  `test_kill_pattern_boot_refuses_on_stale_armed_row`,
  `test_kill_pattern_pack_no_regex_compile_path_ast`,
  `test_kill_pattern_emits_dual_maint_and_sec_alert`,
  `test_kill_pattern_ttl_capped_at_opsctl_nlp_kill_max_ttl_s`.

#### 10.27.5 Operator preview mode (impersonation without side effects)

- [x] **Why.** Operators triaging an incident need to reproduce a
  user's view without (a) writing audit rows that pollute the
  forensic trace, (b) writing shadow-training rows that pollute
  the next intent retrain, (c) decrementing the user's tier
  quota (Phase 20 forward), (d) consuming budget under
  §10.23.8.
- [x] **Header contract.** `X-NLP-Preview: true` header on
  `qa.request.v1` (gateway honours after operator-cert mTLS
  validation per Phase 9; the §10.21.7 PIIScrubFilter ensures
  no operator-introduced PII leaks). Server stamps
  `request_metadata.preview=true` on every downstream
  envelope; consumers MUST honour:
  - `nlp.shadow.v1` writer **drops** preview rows (AST guard
    `test_nlp_shadow_writer_drops_preview_rows`).
  - Audit pipeline writes to `data/nlp/audit_preview/<utc>/...`
    (separate dir, rotated weekly, NEVER fed to
    `make nlp.complaint-trace`).
  - Cache writes are **disabled** (preview answers never
    contaminate the user-facing cache).
  - Tier quota middleware (Phase 20) skips preview requests.
  - Humanizer cost accounting (§10.23.8) writes preview tokens
    to a separate per-operator counter (`nlp_preview_tokens_per_operator`)
    capped at `cfg.nlp_preview_token_budget_per_operator_per_h=2400`
    — defends against runaway operator-driven cost.
- [x] **Boundary discipline.** AST guard
  `test_nlp_preview_flag_propagates_through_full_pipeline`
  (every envelope schema that traverses NLP carries the
  `request_metadata.preview` field; AST scan asserts no
  intermediate envelope drops it).
- [x] **Proof tests** (≥ 5):
  `test_preview_request_does_not_write_shadow`,
  `test_preview_request_writes_to_separate_audit_dir`,
  `test_preview_request_does_not_populate_cache`,
  `test_preview_token_budget_capped_per_operator`,
  `test_preview_flag_propagates_full_pipeline_ast`.

#### 10.27.6 Coordinated abuse detector (orthogonal to per-request §7 sec)

- [x] **Real attack class** prior passes missed: §7 sec rate-
  limits per-subject; §10.25.7 active-learning has anti-
  tampering on provenance mismatch. Neither catches **slow-burn
  coordinated** attacks: 1000 distinct accounts each submit one
  query/hour for a week, all crafted to nudge the next intent
  classifier retrain toward a chosen mis-classification. Each
  individual query is benign; the aggregate is not.
- [x] **Detector.** `nlp.abuse.v1` (NEW agent class in
  `ai/swarm/agents/nlp/abuse.py`, replicas:1 — single-publisher
  for cluster-wide aggregates; consumes `nlp.shadow.v1` only,
  PII-clean by construction). Maintains 4 streaming aggregates
  over the rolling `cfg.nlp_abuse_window_h=168` (1 week):
  1. **Did-you-mean acceptance ratio per (offered_intent,
     accepted_intent) pair.** Sustained `accepted/offered >
     cfg.nlp_abuse_dym_acceptance_anomaly_ratio=4.0` ×
     `(prior 4-week ewma)` → `nlp.alert.v1{kind=nlp_abuse_did_you_mean_anomaly,
     severity=warn}`.
  2. **Cohort style-shift (account-takeover proxy).** Per
     `account_id_h`, rolling 7-day distribution over (locale,
     mean_token_length, intent_class top-3, voice/keyboard
     modality from §10.26.2) — KL-divergence vs. the prior
     30-day baseline > `cfg.nlp_abuse_style_shift_kl=0.6` →
     `nlp.alert.v1{kind=nlp_abuse_style_shift, severity=warn}`
     (per-account; debounced 24h per account_id_h). Phase 9
     auth surface consumes the alert and may trigger step-up
     auth (forward contract; not a hard block from NLP).
  3. **Shadow-training cohort correlation.** Per `(intent_class,
     subject_key_sha8_prefix_2)` bucket — if > 30% of new
     shadow-rows in the past 24h come from < 5 distinct
     prefix-2 buckets (1024 total possible), → `nlp.alert.v1
     {kind=nlp_abuse_shadow_concentration, severity=warn}`.
     `make nlp.intent-train` consumes the alert state and
     refuses to train (per §10.25.5 lifecycle gates) until
     operator ack via `make nlp.abuse-shadow-clear`.
  4. **"Same fingerprint, many accounts" graph signal.** Per
     `(client_fingerprint_hash, account_id_h)` edges over
     7d — Jaccard-similarity bucket flagged if > 100 distinct
     accounts share a single client_fingerprint_hash AND > 0.5
     of them appear in the same shadow-training-eligible bucket
     → `nlp.alert.v1{kind=nlp_abuse_account_farm, severity=error}`.
- [x] **Closed alert kinds + open-enum AST guard.** All four
  kinds added to `KNOWN_NLP_ALERT_KINDS` (mirrors §7.4
  doctrine). Producer set bounded — only `nlp.abuse.v1` may
  emit; `test_only_nlp_abuse_v1_emits_abuse_kinds`.
- [x] **Tier-blind.** Detector is account-class-agnostic; AST
  guard `test_nlp_abuse_detector_does_not_branch_tier`.
- [x] **Proof tests** (≥ 8):
  `test_did_you_mean_anomaly_fires_above_ratio_floor`,
  `test_did_you_mean_anomaly_does_not_fire_at_baseline_drift`,
  `test_style_shift_fires_on_synthetic_kl_above_threshold`,
  `test_shadow_concentration_blocks_intent_train_until_ack`,
  `test_account_farm_emits_error_severity`,
  `test_abuse_detector_consumes_only_nlp_shadow_v1_ast`,
  `test_abuse_alert_producer_set_bounded`,
  `test_abuse_detector_does_not_branch_tier_ast`.

#### 10.27.7 Schema-version downgrade for old clients (qa.answer.v1 v3 → v1)

- [x] **Real client-compat bug.** §10.24.5 bumped `qa.answer.v1`
  schema 1 → 2 (added `parts[]`); §10.26.8 bumped 2 → 3 (added
  `envelope_signature`). Old client SDKs pinned to schema=1 will
  see additional fields they don't recognise; some will
  hard-fail JSON-decode on `additionalProperties:false`-style
  client validators. Single-source doctrine: the *server*
  honours the client's requested schema version and downgrades.
- [x] **Header contract** (Phase 9 forward addition):
  `Accept: application/vnd.negelir.qa-answer+json; version=1|2|3`
  (default = highest stable = 3 at landing). Server picks the
  intersection of `client_max ≤ server_supported ≤ client_min`
  and downgrades the response by **stripping additive-only
  fields** (`parts[1:]` collapsed into top-level for v1;
  `envelope_signature` omitted for v < 3). Schema for the
  downgraded body still validates against the version's pinned
  schema file (cross-language gate test).
- [x] **Downgrade compatibility matrix** at
  `ai/swarm/sdk/schemas/qa.answer.v1.downgrade_matrix.json`
  (single-source — handler reads this, never hardcodes
  per-version logic in the renderer): `{from_version → to_version
  → list[strip_field_path]}`. AST asserts handler dispatches via
  this matrix only (`test_nlp_qa_answer_downgrade_handler_uses_matrix_only`).
- [x] **Sunset for old versions.** `cfg.nlp_qa_answer_min_supported_version=1`;
  flipping to 2 emits 6-month `Sunset:` + `Deprecation:` headers
  per Phase 9 RFC 8594 doctrine, then refuses with 426 Upgrade
  Required at the deadline. Operator-toggleable; documented in
  `docs/guides/nlp_runbook.md` runbook.
- [x] **Round-trip integrity invariant.** When envelope_signature
  was stripped (downgrade to v < 3), the *client* cannot verify
  HMAC; this is acceptable for v < 3 clients (they predate the
  feature) but the server SHOULD log the downgrade event to
  `nlp.event.v1{kind=qa_answer_downgraded, from=3, to=1,
  client_id_h, sha_envelope}` so operators can drive deprecation.
- [x] **Proof tests** (≥ 6):
  `test_qa_answer_downgrade_v3_to_v1_strips_signature_and_collapses_parts`,
  `test_qa_answer_downgrade_v3_to_v2_keeps_parts_strips_signature`,
  `test_qa_answer_downgrade_v2_to_v1_collapses_parts_only`,
  `test_qa_answer_downgrade_handler_uses_matrix_only_ast`,
  `test_qa_answer_v1_min_supported_426_at_deadline`,
  `test_qa_answer_downgrade_emits_event_per_request`.

#### 10.27.8 Regulatory disclosure invariant (KVKK Art 11 + Turkish gambling law + GDPR Art 22 equivalent)

- [x] **Why this is mandatory not optional.** Negelir produces
  algorithmic outputs about football match probabilities served
  to Turkish-resident users. Three regulatory regimes intersect:
  **KVKK Art 11** (data subject rights — must surface a path to
  view / correct / erase personal data); **Turkish gambling law**
  (predictions involving outcomes against a tier-priced surface
  trigger Spor Toto / Iddaa wording obligations and 18+ gating —
  even though Phase 20 monetization is dormant at v1, the
  prediction surface itself qualifies); **GDPR-Art-22-equivalent**
  KVKK Art 11/h (right not to be subject to a solely automated
  decision — predictions must be disclosed as such, not framed
  as expert advice).
- [x] **Closed disclosure registry.** `ai/nlp/compliance/disclosures.tr.yaml`
  (single-source, hot-reloadable per §10.2 atomic-swap
  discipline; CODEOWNERS includes `nlp-compliance` reviewer per
  §10.25.6 governance):
  - `kvkk_user_rights_footer_first_per_conversation` — appended
    to the first answer of every new `conversation_id`
    (§10.25.1) by the renderer; suppressed on subsequent turns
    via in-memory `conversation_disclosures_emitted` set.
  - `gambling_law_disclaimer_band` — prepended to every
    `predict.*` answer; closed Turkish text, version-stamped,
    last 4 chars of `disclosure_sha8` recorded in
    `qa.answer.v1.disclosures[]` (NEW additive field on schema
    v3 → v4; falls under §10.27.7 downgrade as `[strip]` for
    v < 4).
  - `automated_decision_notice` — appended once per
    `conversation_id` to `predict.*` answers.
  - `eighteen_plus_gate` — prepended to first per-conversation
    `predict.*` answer if `request_metadata.user_age_attestation
    is None` AND `cfg.nlp_age_gating_enabled=true`. Defaults
    OFF at v1 (no auth → no age attestation); flipped ON when
    Phase 9 self-registration ships post-Phase-9 §9.2.
- [x] **Renderer order (binding).** `[gambling_law_disclaimer_band]
  + [eighteen_plus_gate?] + body + [kvkk_user_rights_footer?] +
  [automated_decision_notice?]`. Humanizer-bypassed (§10.7
  doctrine — disclosures are byte-stable closed text, never
  rephrased). AST `test_nlp_disclosures_humanizer_bypassed`.
  `make nlp.template-lint` extended to assert no template ever
  templates a disclosure substring (defense in depth — keeps
  disclosures owned by the renderer, not template authors).
- [x] **Locale resolution.** `disclosures.<locale>.yaml` per
  §10.17 forward hook; v1 ships `tr.yaml` only; missing locale
  falls back to `tr.yaml` w/ `nlp.event.v1{kind=disclosure_locale_fallback}`.
- [x] **Audit.** Every emitted disclosure logs
  `nlp.event.v1{kind=disclosure_emitted, disclosure_id,
  disclosure_version, conversation_id, request_id}` so legal /
  compliance can prove on demand which exact text version was
  served at time T. PII-clean (no body text — disclosure_id +
  version + conversation_id only).
- [x] **Closed enum + version policy.** `disclosure_id` ∈ closed
  enum (4 values at v1); each carries `version: <int>` +
  `effective_from_utc`. Bumping a disclosure version is a Phase
  10 / Phase 20 codepath that requires `nlp-compliance` reviewer;
  CODEOWNERS-enforced. Revoking a disclosure (rare; requires
  legal sign-off) is a separate 2-reviewer gate.
- [x] **Cache key extension.** L0 / L1 cache key (per §10.25.10
  7-8 components) gains `disclosures_snapshot_sha` as a 9th
  component — atomic disclosure-text rotation invalidates the
  cache cluster-wide on next read (no stale disclosure ever
  served).
- [x] **Proof tests** (≥ 9):
  `test_kvkk_footer_first_per_conversation_only`,
  `test_gambling_disclaimer_on_every_predict_answer`,
  `test_automated_decision_notice_first_per_conversation_only`,
  `test_disclosures_humanizer_bypassed_ast`,
  `test_template_lint_rejects_disclosure_substring_in_template`,
  `test_disclosures_locale_fallback_emits_event`,
  `test_disclosure_version_bump_requires_compliance_codeowner_via_make_verify`,
  `test_cache_key_includes_disclosures_snapshot_sha`,
  `test_qa_answer_disclosures_field_strippable_for_v_lt_4_clients`.

#### 10.27.9 Cross-pod lexicon-swap consistency window (drain-before-swap)

- [x] **Real correctness bug** §10.21.5 missed: lexicon hot-reload
  is per-pod-mtime-poll; in a multi-pod deployment (Phase 14)
  pods see the new file at slightly different times within
  `cfg.nlp_lexicon_reload_s=30`. Two users hitting two pods
  during the swap edge see *different canonical resolutions*
  for the same query — silent A/B inconsistency.
- [x] **Drain protocol.** `make nlp.lexicon-deploy LEXICON=<name>
  VERSION=<sha>` (new xops/makefile/nlp.py command) writes the
  new file with `_meta.swap_at_utc = now() + cfg.nlp_lexicon_swap_grace_s=120`
  marker. Pods load the file at mtime detection but DO NOT swap
  the active pointer until `now_utc() ≥ swap_at_utc`. All pods
  swap in a tight cluster-wide window (≤ NTP skew, typ. <1s)
  rather than over the full mtime-poll window.
- [x] **Stragglers.** Pods that load the new file > 30s after
  `swap_at_utc` (mtime-poll missed it) emit
  `nlp.alert.v1{kind=lexicon_swap_late, severity=warn,
  pod_id, lag_s}` and proceed to swap immediately. Pods unable
  to load the file by `swap_at_utc + cfg.nlp_lexicon_swap_max_lag_s=600`
  emit `severity=error` and refuse new traffic (readiness 503
  mirrors §10.21.9 cold-start gate) until they catch up.
- [x] **Atomicity preserved.** Within a single pod, §10.21.3
  all-or-nothing 6-file swap still applies; this addendum
  coordinates *across* pods, not within.
- [x] **Cache coherence.** Lexicon swap bumps the
  `lexicon_snapshot_sha` cache-key component (§10.23.9) — old
  cache entries invalidate naturally as the new gen propagates.
- [x] **Proof tests** (≥ 5):
  `test_lexicon_swap_at_utc_marker_respected_by_pods`,
  `test_lexicon_swap_late_emits_warn_alert`,
  `test_lexicon_swap_max_lag_pod_drains_to_503`,
  `test_lexicon_atomic_swap_within_pod_still_holds`,
  `test_lexicon_swap_bumps_cache_key_snapshot_sha`.

#### 10.27.10 Anti-leakage gates on shadow → training pipeline

- [x] **Real bug** §10.25.5 left implicit: "data ONLY from
  `nlp.shadow.v1`" doesn't pin *which* shadow rows are eligible
  for training. Three classes of row are toxic to the next
  intent retrain:
  1. `degraded=true` rows — model would learn to mimic
     degraded behaviour.
  2. Quarantined rows (sec gate emitted `sec.quarantine.v1`
     for the underlying request) — model would learn from
     adversarial inputs.
  3. Proofreader-blocked rows (§10.9 fired) — model would
     learn from outputs the system itself rejected.
  4. Preview rows (§10.27.5) — model would learn from
     operator probes, not real user intent.
  5. Kill-pattern-rewritten rows (§10.27.4) — similar to
     proofreader-blocked.
- [x] **Eligibility filter** in
  `ai/swarm/agents/nlp/training/eligibility.py` (single source);
  AST guard `test_nlp_intent_trainer_consults_eligibility_filter`
  (every `make nlp.intent-train` data-loader path passes through
  this filter). Filter emits a manifest at
  `data/nlp/training_manifests/<train_run_id>.json` listing
  excluded row counts per reason — operator-auditable proof of
  no leakage.
- [x] **Eval-vs-train membership manifest.** §10.18 evaluation
  fixtures (≥ 250 entries) carry `request_id_h` (sha256 of the
  hand-curated entry); `make nlp.intent-train` MUST exclude any
  shadow row whose `request_id_h` matches an eval-set entry.
  AST `test_nlp_train_excludes_eval_set_membership` + manifest
  carries the cross-check sha to prove the exclusion ran.
- [x] **Cohort-de-duplication.** Beyond per-row exclusion, group
  rows by `(subject_key_sha8_prefix_2)` and cap each bucket at
  `cfg.nlp_intent_train_max_rows_per_subject_bucket=500` to
  defend against the §10.27.6 abuse-class shadow concentration
  reaching the trainer even if the abuse detector missed it
  (defence in depth).
- [x] **Proof tests** (≥ 7):
  `test_eligibility_excludes_degraded_rows`,
  `test_eligibility_excludes_quarantined_rows`,
  `test_eligibility_excludes_proofreader_blocked_rows`,
  `test_eligibility_excludes_preview_rows`,
  `test_eligibility_excludes_kill_pattern_rewritten_rows`,
  `test_train_excludes_eval_set_membership_via_manifest`,
  `test_train_caps_per_subject_bucket_under_abuse_threshold`.

#### 10.27.11 Edge-platform answer-format profile (forward hook; dormant at v1)

- [x] **Forward hook only at Phase 10.** WhatsApp / Telegram /
  SMS / TTS deployments have hard constraints (4096-char body,
  no markdown, 160-char SMS, prosody-friendly phrasing for
  TTS). The accessibility addendum §10.23.7 already supports
  `cfg.nlp_answer_formats=[plain, markdown_safe, screen_reader]`;
  this extends to `[plain, markdown_safe, screen_reader,
  whatsapp_4096, sms_160, tts_neutral]` — the three new formats
  ship with **stub renderers** that emit a `meta.format_unsupported`
  template at v1 (so the negotiation surface exists but the
  channel itself is not enabled). Reserves the enum slot
  (additive-safe forward).
- [x] **Negotiation.** `?answer_format=` query param > `Accept`
  header > `cfg.nlp_default_answer_format=plain`. AST
  `test_nlp_format_negotiation_order_pinned`.
- [x] **Closed config.** `nlp_answer_format_enabled` map
  `{plain:true, markdown_safe:true, screen_reader:true,
  whatsapp_4096:false, sms_160:false, tts_neutral:false}` —
  defaults pinned; flipping requires per-channel renderer impl
  (Phase 22+ deliverables).
- [x] **Proof tests** (≥ 4):
  `test_format_negotiation_order_query_then_accept_then_default`,
  `test_format_unsupported_returns_meta_template`,
  `test_format_enum_reserves_three_new_slots_additively`,
  `test_format_enabled_default_pins_three_new_off`.

#### 10.27.12 Per-conversation entity-graph snapshot (extends §10.25.3 audit bundle)

- [x] **Real gap** §10.25.3 stores `(lexicon_set_sha, intent_sha,
  crf_sha, calibration_version, template_git_sha, pipeline_version)`
  but NOT the conversation context that produced the answer (the
  `qa.context.v1` entities-only graph from §10.25.1). Without it,
  a re-render of turn 5 of a 7-turn conversation cannot reproduce
  the answer because turn 5's entity inheritance from turns 1-4
  is lost.
- [x] **Bundle extension.** `nlp_audit_bundle_sha` extended (single
  fixed extension; bumps `pipeline_version` once at landing) to
  include `conversation_entity_graph_sha` = sha256 over the
  canonical-serialised `qa.context.v1` snapshot at the moment of
  the request. Bundle directory gains
  `<sha>/conversation_entity_graph.json` (PII-clean — entity
  canonical_ids only, no text). Re-render reads this file and
  reconstructs the conversation context before dispatching.
- [x] **Storage cost.** Quartet-dedup (§10.25.3) extends to
  quintet-dedup; expected bundle dir count remains ≪ requests
  because conversation graphs share canonical-id sets across
  many conversations.
- [x] **Erasure compliance.** §10.25.9 right-to-erasure extended
  to walk the bundle dir's `conversation_entity_graph.json` and
  drop any reference to the erased user's `account_id_h` —
  bundle re-rendering survives (canonical_ids alone), only the
  cross-link to the deleted account is severed.
- [x] **Proof tests** (≥ 4):
  `test_audit_bundle_includes_conversation_entity_graph_sha`,
  `test_audit_rerender_with_conversation_context_byte_identical`,
  `test_quintet_dedup_keeps_bundle_count_bounded`,
  `test_audit_erasure_drops_account_id_h_from_graph_file`.

#### 10.27.13 Knob inventory (~22 new) + new event/alert kinds + new `data.request.v1` kinds

- [x] **New cfg knobs** (single-source; triangle test extends):
  `nlp_fixture_state_lookup_timeout_ms=250`,
  `nlp_calibration_horizon_strict=true`,
  `opsctl_nlp_kill_max_ttl_s=3600`,
  `nlp_preview_token_budget_per_operator_per_h=2400`,
  `nlp_abuse_window_h=168`,
  `nlp_abuse_dym_acceptance_anomaly_ratio=4.0`,
  `nlp_abuse_style_shift_kl=0.6`,
  `nlp_abuse_shadow_concentration_distinct_buckets_min=5`,
  `nlp_abuse_account_farm_jaccard_min=0.5`,
  `nlp_abuse_account_farm_account_count_min=100`,
  `nlp_qa_answer_min_supported_version=1`,
  `nlp_age_gating_enabled=false`,
  `nlp_lexicon_swap_grace_s=120`,
  `nlp_lexicon_swap_max_lag_s=600`,
  `nlp_intent_train_max_rows_per_subject_bucket=500`,
  `nlp_default_answer_format=plain`,
  `nlp_answer_format_enabled` (map; closed),
  `nlp_disclosure_locale_fallback_chain=[tr-TR]`,
  `nlp_complaint_trace_default_window_h=24`,
  `nlp_kill_pattern_arm_max_concurrent=8`,
  `nlp_preview_dir`,
  `nlp_complaint_trace_dir`.
  Plus 6 feature-flag toggles for §10.27.1/§10.27.4/§10.27.5/
  §10.27.6/§10.27.7/§10.27.11.
- [x] **New `nlp.event.v1` kinds**:
  `fixture_state_flipped_during_rpc`, `qa_answer_downgraded`,
  `disclosure_emitted`, `disclosure_locale_fallback`,
  `nlp_pii_recovered_for_trace` *(also in maint.event.v1)*,
  `nlp_complaint_trace_completed`,
  `nlp_complaint_trace_drift_detected`,
  `nlp_kill_pattern_armed_locally`, `nlp_kill_pattern_disarmed_locally`.
- [x] **New `nlp.alert.v1` kinds**:
  `calibration_horizon_mismatch` (error),
  `nlp_abuse_did_you_mean_anomaly` (warn),
  `nlp_abuse_style_shift` (warn),
  `nlp_abuse_shadow_concentration` (warn),
  `nlp_abuse_account_farm` (error),
  `lexicon_swap_late` (warn),
  `lexicon_swap_lag_drained_to_503` (error),
  `nlp_complaint_trace_drift` (warn),
  `nlp_kill_pattern_stale_armed_at_boot` (critical),
  `nlp_preview_token_budget_exhausted_per_operator` (warn).
- [x] **New `maint.event.v1` kinds** (consumed by NLP):
  `nlp_kill_pattern_armed`, `nlp_kill_pattern_disarmed`
  (each carries operator_id_h + pattern_pack_sha8 + ttl_s);
  `nlp_pii_recovered_for_trace` (operator-attested PII recovery).
- [x] **New `data.request.v1` kinds** (additive on §3.5 wire
  contract): `fixture_state`, `live_state`. Both consumer is
  Phase 4 / Pivot R1 storage agent; producer set bounded to
  `nlp.dispatcher.v1`.
- [x] **Producer set guarantees.** All new `nlp.alert.v1` kinds
  remain bounded to `{nlp.intent.v1, nlp.answer.v1,
  nlp.proofreader.v1, nlp.dispatcher.v1, nlp.abuse.v1}` —
  `test_nlp_alert_v1_producer_set_remains_bounded_after_phase_10_27`
  (mirrors §7.4 doctrine).

#### 10.27.14 Cross-phase contracts (binding)

- [x] **Phase 4 / Pivot R1 storage.** Adds `match_normalized.state`
  field (additive); emits via the `data.request.v1{kind=fixture_state}`
  reply. Boundary test: NLP never imports the storage agent
  directly (§10.0 doctrine — only via bus).
- [x] **Phase 5 predictors.** Calibration profiles gain
  `state_horizon` field; trainer refuses to mark a profile as
  `pre_match_locked` AND `live_eligible` simultaneously at v1
  (binary flag for now; multi-horizon Phase 22+).
- [x] **Phase 7 sec.** `qa.request.v1` schema additive: new
  `request_metadata.preview` boolean; `request_metadata.client_format_max_version`
  int (1-3 at landing). sec gate sees both, never mutates.
- [x] **Phase 8 maint.** New `nlp_kill_pattern_*`,
  `nlp_pii_recovered_for_trace` kinds added to
  `KIND_TO_CONSUMERS` map (§8.0). Operator subcommand wiring
  for `ops.nlp-kill-pattern` + `ops.nlp-disarm-kill-pattern`.
  Patcher scope continues to EXCLUDE `nlp/`.
- [x] **Phase 9 API gateway.** Honours `Accept:
  application/vnd.negelir.qa-answer+json; version=N` per
  §10.27.7; honours `X-NLP-Preview` per §10.27.5 (mTLS-gated);
  rejects `?answer_format=` values not in the §10.27.11 enum
  with 400 (validates BEFORE hitting NLP). Adds the
  `qa.answer.v1` envelope HMAC verifier (§10.26.8 picked up
  here). Forward contract.
- [x] **Phase 11 compute.** `nlp.abuse.v1` is CPU-only; AST
  rejects `cuda`/`mps`/`rocm` imports under `ai/swarm/agents/nlp/abuse.py`.
  No change to humanizer compute model.
- [x] **Phase 12 chaos.** New stubs:
  `chaos.fixture-state-flap` (asserts dispatcher routes by
  observed state, not assumed), `chaos.kill-pattern-mass-arm`
  (asserts cap `nlp_kill_pattern_arm_max_concurrent`),
  `chaos.lexicon-swap-staggered-pods` (asserts <1s cluster-wide
  window under §10.27.9), `chaos.client-pinned-old-schema-flood`
  (asserts downgrade matrix doesn't allocate per request).
- [x] **Phase 13a LeagueCatalog.** No change at v1; fixture-state
  is a runtime/scrape-derived attribute, not a catalog one.
- [x] **Phase 14 K8s.** `nlp.abuse.v1` is `replicas:1`
  (single-publisher; single-process aggregate state). Lease
  via the existing §8.10 Leader Protocol.
- [x] **Phase 16 Emitter.** `LexiconStore` Protocol gains
  `swap_at_utc` plumbing (additive; in-memory backend is no-op).
- [x] **Phase 19 long-tail.** Fixture-state routing is league-
  agnostic; AST `test_nlp_no_per_league_branch` re-asserts on
  §10.27 code surface.
- [x] **Phase 20 monetization.** Disclosure registry is
  tier-blind (regulatory disclosures apply to every tier
  including free); preview-mode is operator-only and skips
  tier accounting; abuse detector is tier-blind. Three explicit
  AST guards: `test_nlp_disclosures_tier_blind`,
  `test_nlp_preview_skips_tier_quota`,
  `test_nlp_abuse_detector_tier_blind` (already in §10.27.6,
  re-asserted here to surface in cross-phase scan).
