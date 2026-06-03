# Phase 10 §10.30 — Conversational completeness, intent-enum closure, classifier-bias floor

> **Provenance.** Carved out of `docs/planning/ROADMAP.md` Phase 10 on the Phase 10 split (post-13th-pass) so the ROADMAP stays navigable. Content here is the **binding** Phase 10 contract; ROADMAP §10 now points at this folder. Any edit must update `xops/versioning/chart.json` (`docs` minor) and the tracker (per AGENTS.md §3 + §6.1). Cross-phase references (Phase 5/7/8/9/11/12/13a/14/16/19/20) remain authoritative against ROADMAP and the matching `docs/design/*.md` anchors.


### 10.30 Conversational completeness, intent-enum closure, and classifier-bias floor (binding addendum)

> **Why this section exists.** §10.0–§10.29 hardened ten independent
> floors. Eleventh-pass review against real-world Turkish football
> conversations surfaces a residual class of *gracefully-wrong* and
> *confidently-routed-to-the-wrong-handler* cases the prior passes
> did not close: (i) the closed `intent_id` enum in §10.4 covers
> match outcomes and basic data lookups but **omits the queries
> Turkish fans actually send most often** — top-scorer / table-leader
> aggregations, lineups, injury / suspension lists, referee
> appointments, weather conditions; the system today routes these
> to `meta.unsupported` with no migration path; (ii) WH-word → intent
> mapping (`kim` / `ne zaman` / `nerede` / `kaç` / `nasıl` / `niye`)
> is implicit in the classifier features but is not a binding closed
> table, so a classifier retraining drift can silently flip
> `kim → data.top_scorer` to `kim → predict.match_outcome`; (iii)
> Turkish football idioms (`ipi göğüslemek` = win the title,
> `küme düşmek` = relegation, `averaj farkı` = goal difference,
> `derbi` = derby, `transfer dönemi` = transfer window) are atomic
> meaning-units that decompose to wrong tokens under generic
> tokenisation; (iv) `-sa/-se` conditional + `eğer/şayet` explicit
> conditional both must route to a NEW intent_modifier *conditional*
> distinct from §10.29.8 *comparative*, with deterministic dispatch
> by tense (conditional+future → predict with disclaimer,
> conditional+past → §10.26.5 counterfactual_past firewall,
> conditional+present → data lookup); (v) politeness-register
> markers (`lütfen`, `acaba`, `mümkünse`, `rica etsem`,
> `-yebilir/-abilir misiniz`) bias the classifier when they
> co-occur with rare-class intents — *politeness must be a
> non-feature*; (vi) search-operator syntax (`+galatasaray
> -fenerbahçe`, `"şampiyonlar ligi"`, `OR`/`AND`) sent by power
> users is misinterpreted as natural language today; (vii) cross-turn
> anaphora (`onlar`/`bunlar`/`kendisi`/`orası` referring to a prior
> match / team / venue mentioned 3 turns ago) has no formal
> resolver; (viii) ASR-delivered `virgül`/`nokta` (the *words* for
> punctuation, transcribed when the speaker said them out loud)
> bleed into queries as literal tokens; (ix) repeated-query within
> the same conversation has no operator-grade response (currently
> served as a fresh request, hiding the user's confusion signal);
> (x) slur obfuscation (`s*ktir`, `am*na`, `o.ç`) bypasses the
> §10.22.9 offensive gate; (xi) the closed `intent_id` enum is
> consumed by Phase 9 gateway for tier mapping (§10.0) but has no
> cross-language byte-parity gate, so an additive intent change in
> Python that the gateway hasn't picked up returns `403
> tier_unknown`; (xii) the L0 in-process LRU on each pod has no
> per-pod cache-key salt, so an adversarial collision against the
> 64-bit subject-key truncate produces wrong-answer-from-cache;
> (xiii) the venue → home-team inference is implicit in the
> entity recognizer but is not a closed table — `Türk Telekom
> Stadyumu` mention without explicit `Galatasaray` is currently a
> CRF-confidence gamble; (xiv) cross-conversation entity-graph
> staleness (a fixture mentioned 30 min ago has now finished, and
> the cached `predict.approved.v1` answer is now wrong-tense)
> has no re-resolution gate. This addendum closes all fourteen.

#### 10.30.1 Closed intent-enum completion (`schema_version=4` for `qa.intent.v1`)

- [x] **New intent_ids land additively in `_intent_enum.json`** (the
  CODEOWNERS-protected closed enum from §10.27.6 and prior):
  `data.top_scorer` (e.g., *bu sezon gol kralı kim?*),
  `data.assist_leader` (*asist kralı*),
  `data.clean_sheets_leader` (*en az gol yiyen kaleci*),
  `data.table_leader` (*lig lideri kim?*),
  `data.relegation_zone` (*küme düşme hattındaki takımlar*),
  `data.lineup_probable` (*muhtemel ilk 11*),
  `data.lineup_official` (*açıklanan kadro*),
  `data.injury_list` (*sakat oyuncular*),
  `data.suspension_list` (*cezalı oyuncular / kart cezalısı*),
  `data.referee_appointment` (*maçın hakemi kim?*),
  `data.weather_at_kickoff` (*maç saatinde hava*),
  `data.transfer_window_status` (*transfer dönemi açık mı?*),
  `data.head_to_head_history` (*tarihte 5 maç önce ne oldu?* —
  distinct from §10.5.x `data.h2h` which is per-fixture immediate
  pre-match summary; this is multi-historical-fixture aggregation),
  `predict.match_outcome.conditional` (NEW — see §10.30.4 below;
  *Galatasaray kazanırsa lider olur mu?*).
- [x] **Schema-version bump.** `qa.intent.v1` → `schema_version=4`
  (additive: enum widening only; existing v3 producers/consumers
  unchanged; §10.27.7 schema-downgrade negotiation contract honored
  — old SDK clients sending `Accept: application/vnd.negelir.qa-intent+json; version=3`
  receive `meta.unsupported` with closed Turkish disclosure
  *"İstediğiniz sorgu türü için lütfen güncel uygulamayı kullanın"*
  rather than silent enum-value drop).
- [x] **Cross-language gate.** `ai/common/nlp/intent_enum_spec.json`
  is single source; `ai/swarm/agents/nlp/intent.py` and
  `server/internal/api/intent_tier.go` (gateway tier-mapper) both
  load it and refuse boot on SHA mismatch (mirrors §10.29.11
  normalize-spec pattern). Each new intent_id ships with its
  `tier_id_required` row in `intent_tier_map.json` in the SAME
  commit; CI gate `test_intent_enum_has_tier_mapping_row` rejects
  any enum entry without a tier mapping. Defends against the
  `403 tier_unknown` class on additive enum landings.
- [x] **Per-intent template existence gate.** CI walks
  `ai/nlp/templates/tr_TR/*.j2` and asserts each new intent_id has
  at least one bound template (with at least one *missing-data*
  variant for graceful degradation). `test_intent_enum_has_template_coverage`.
- [x] **Per-intent dispatcher route gate.** `nlp.dispatcher.v1`
  route table is closed; AST guard `test_dispatcher_routes_cover_intent_enum`
  enumerates the intent_enum at test-collection time and asserts
  every value has a route (or an explicit `meta.unsupported`
  fallback flagged as such). Defends against the silent
  enum-not-routed bug where a new intent reaches the dispatcher
  and falls through to whatever default the prior implementer
  picked.
- [x] **Proof:** `test_intent_enum_v4_additive_only`,
  `test_intent_enum_cross_language_sha_match`,
  `test_intent_enum_has_tier_mapping_row`,
  `test_intent_enum_has_template_coverage`,
  `test_dispatcher_routes_cover_intent_enum`,
  `test_qa_intent_v3_client_negotiation_returns_meta_unsupported_for_v4_only_intents`.

#### 10.30.2 WH-word → intent binding table (deterministic feature, classifier-blind)

- [x] **Closed `wh_intent_map.tr.yaml`** lists every Turkish
  question word and its prior-belief intent class:
  `kim` → `data.lineup_*` / `data.top_scorer` / `data.referee_appointment`
  (person-asking class; classifier picks among them);
  `ne zaman` → `data.kickoff_time` / `data.transfer_window_status`
  (time-asking); `nerede` → `data.venue` / `data.weather_at_kickoff`;
  `kaç` → `data.score_current` / `data.h2h_count` / `data.standings`
  (cardinality); `nasıl` → `data.form_recent` (manner / how-doing);
  `niye`/`niçin`/`neden` → `meta.opinion_unsupported`
  (causal questions are out-of-scope at v1, never silently routed
  to predict); `hangi` → `data.fixture_lookup` (which-of); `ne`
  (bare) → `data.fixture_today` (most ambiguous; lowest prior
  weight). Each row carries a *prior_log_odds* float that is
  ADDED to the classifier logit at inference (NOT trained into
  the classifier — kept as a separate deterministic feature so a
  classifier retrain cannot silently flip the prior).
- [x] **AST guard: WH-word coverage.** Test scans the file at
  collection time, asserts every Turkish WH-word in a closed
  `wh_words.tr.yaml` (≥ 12 entries including `kimler`/`hangileri`/
  `kaçıncı`/`hangisi`/`kaç tane`) has a row in `wh_intent_map.tr.yaml`;
  missing entry → test fail. Defends against the
  add-WH-word-forget-the-mapping class.
- [x] **Inference-time guard.** `nlp.intent.v1` inference applies the
  WH-word prior AFTER the fastText logit, BEFORE the §10.4
  Platt-calibration; record both `intent_score_raw_logit` and
  `intent_score_after_wh_prior` in `nlp.event.v1{kind=intent_decision_breakdown}`
  for explainability and drift monitoring (per-WH-word mean shift
  > `nlp_wh_prior_drift_alert_pp=2.0` percentage points over a
  7-day window → `nlp.alert.v1{kind=wh_prior_drift, severity=warn}`).
- [x] **Tier-blind invariant.** AST guard ensures the WH-prior
  table is consulted by the *intent classifier only* and never by
  the dispatcher, the proofreader, or the template selector
  (those operate on the post-classifier `intent_id`, not the
  WH-token). Defends against the WH-token being smuggled into
  routing as a side channel.
- [x] **Proof:** `test_wh_intent_map_covers_all_wh_words`,
  `test_wh_prior_applied_after_logit_before_calibration`,
  `test_wh_prior_drift_alert_fires_above_threshold`,
  `test_wh_token_not_consulted_post_classifier_ast`.

#### 10.30.3 Football-idiom phrasebook (atomic meaning units, expansion BEFORE classifier)

- [x] **Closed `idioms.tr.yaml`** ships ≥ 60 atomic Turkish football
  idioms with their canonical-token expansion: `ipi göğüslemek`
  → `(intent: predict.match_outcome.conditional, modifier: comparative,
  trigger: title_race)`; `küme düşmek` → `(intent: data.relegation_zone)`;
  `averaj farkı`/`gol averajı` → `(intent: data.standings, slot: tiebreak=goal_diff)`;
  `derbi` → `(slot: fixture_class=derby)`;
  `transfer dönemi açık` → `(intent: data.transfer_window_status)`;
  `son düdük` → `(slot: phase=full_time)`;
  `topu yuvarladılar` → `(slot: phase=kicked_off)`;
  `nizami gol` → `(slot: goal_class=valid)`;
  `bonservissiz` → `(slot: transfer_class=free_agent)`;
  `kart cezalısı` → `(intent: data.suspension_list)`;
  `form grafiği` → `(intent: data.form_recent)`;
  plus regional / supporter / commentary register entries
  (`teknik adam`, `defansın gediği`, `kontra atak`, `çift forvet`,
  `dar alan oyunu`, `top sahibi olmak`, `pres yapmak`).
- [x] **Expansion stage in normalize pipeline.** New deterministic
  step inserted between §10.1 step 6 (lexicon-canonicalisation)
  and step 7 (Symspell typo correction): idiom multi-token match
  (longest-match-first, deterministic on tie via lexicographic
  token order — never `set` iteration). Each expansion records a
  `nlp.event.v1{kind=idiom_expansion, idiom_id, span, replaced_tokens}`
  for full traceability; the expansion is REVERSIBLE for audit
  re-render (the audit bundle stores both pre- and post-expansion
  token streams per §10.27.3).
- [x] **Provenance & two-reviewer rule.** `idioms.tr.yaml` is added
  to the §10.25.6 lexicon-contributor governance high-leverage
  table (PR-gated, two-reviewer minimum, alias-delta cap per
  §10.26.6). `nlp-curator` orthographic + `nlp-domain-football`
  (NEW CODEOWNERS group) co-required.
- [x] **Idiom-vs-literal disambiguation.** When an idiom span is
  also a valid literal phrase (`son düdük` literally = "the last
  whistle" but in commentary = "full time"), require contextual
  trigger from a closed `idiom_context.tr.yaml` (e.g., requires a
  match-state token within ±5 tokens). No-context match → emit
  `nlp.event.v1{kind=idiom_ambiguous, idiom_id}` and proceed
  with literal interpretation; coverage telemetry tracks per-idiom
  trigger-hit-rate.
- [x] **Coverage seed.** Initial v1 ships ≥ 60 idioms; CI gate
  `test_idiom_phrasebook_min_coverage` enforces floor; eval-set
  §10.18 grows by ≥ 25 idiom-bearing rows.
- [x] **Proof:** `test_idiom_expansion_is_deterministic_and_longest_match`,
  `test_idiom_expansion_is_reversible_in_audit_bundle`,
  `test_idiom_event_emitted_per_expansion`,
  `test_idiom_ambiguous_falls_back_to_literal_with_event`,
  `test_idiom_phrasebook_min_coverage`,
  `test_idiom_phrasebook_codeowners_enforced`.

#### 10.30.4 Conditional-clause routing (`-sa/-se` + `eğer/şayet`) — new intent_modifier

- [x] **Closed `conditional_markers.tr.yaml`** lists the explicit
  conditional triggers: lexical (`eğer`, `şayet`, `farzedelim`,
  `tutalım ki`, `diyelim ki`, `kazanırsa`-style suffix-with-`mı`)
  + suffixal (`-sa`/`-se`/`-ysa`/`-yse` after vowel-harmony resolution
  via Zemberek). At least one trigger present → set
  `intent_modifier=conditional` in `qa.intent.v1` (joins
  existing `none`/`comparative` from §10.29.8; enum becomes 3-valued).
- [x] **Tense-discriminated dispatch matrix** (deterministic, AST-guarded):
  | Trigger tense | Intent class | Route |
  |---|---|---|
  | conditional + future verb (*kazanırsa lider olur* — *future projected*) | `predict.*` | `predict.match_outcome.conditional` (NEW intent_id, §10.30.1); template appends closed-text disclosure *"Şartlı bir tahmin yapıyorum; gerçek sonuç farklı olabilir."* |
  | conditional + past verb (*kazansaydı lider olurdu* — *counterfactual past*) | (none) | §10.26.5 counterfactual_past firewall → `meta.counterfactual_past_unsupported` |
  | conditional + present verb (*Galatasaray oynarsa kim oynar* — *present hypothetical*) | `data.lineup_probable` | regular dispatch, modifier carried to `request_metadata.intent_modifier=conditional` for analytics |
- [x] **Routing AST guard.** `test_conditional_routing_matrix_complete`
  walks the dispatcher and asserts every (intent_class × tense)
  cell has an explicit route or refusal — no fall-through default.
- [x] **Conditional + comparative compose-ability.** When BOTH
  conditional and comparative triggers fire (*Galatasaray
  kazanırsa Fenerbahçe'den önde mi olur?*), modifier is the
  ordered tuple `(conditional, comparative)`; dispatcher routes
  to `predict.match_outcome.conditional` and the comparative-leg
  fan-out from §10.29.8 applies on the predicted-state world.
  Closed enum for ordered tuples.
- [x] **Proof:** `test_conditional_marker_table_byte_identical_cross_phase`,
  `test_conditional_modifier_set_when_marker_present`,
  `test_conditional_future_routes_to_predict_conditional`,
  `test_conditional_past_routes_to_counterfactual_firewall`,
  `test_conditional_present_routes_to_data_lookup`,
  `test_conditional_plus_comparative_tuple_routing`,
  `test_conditional_routing_matrix_complete_ast`.

#### 10.30.5 Politeness-register classifier-bias guard (politeness is a non-feature)

- [x] **Closed `politeness_markers.tr.yaml`** lists ≥ 30 politeness
  tokens / patterns: `lütfen`, `acaba`, `mümkünse`, `rica etsem`,
  `rica ediyorum`, `eğer mümkünse`, `zahmet olmazsa`,
  `-yebilir misiniz` / `-abilir misiniz` (suffixal-formed — match
  via Zemberek root-form), `bir bakar mısınız`, `söyler misiniz`,
  `mümkün mü acaba`, `yardımcı olur musunuz`. Plus regional /
  formal / Ottoman-formal register variants.
- [x] **Pre-classifier strip-with-recording.** During §10.1
  normalize, politeness markers are stripped to a separate
  `politeness_class ∈ {neutral, polite, very_polite, curt}`
  (curt = ALL-CAPS without polite markers, per §10.28.10 ALL-CAPS
  normalization), recorded on `qa.intent.v1.request_metadata`,
  and REMOVED from the token stream the classifier sees. Defends
  against the classifier learning `lütfen` → any-rare-class
  spurious-correlation (politeness markers correlate with hesitant
  users who ask exotic queries; classifier should not pick this
  up).
- [x] **AST guard: politeness tokens not in classifier features.**
  `test_politeness_tokens_absent_from_classifier_input` runs the
  100-row golden corpus through the normalize pipeline and asserts
  no politeness-marker token survives into the classifier feature
  vector.
- [x] **AST guard: politeness not consulted by routing/proofreader.**
  `test_politeness_class_only_used_by_template_selector_ast`
  scans `nlp.dispatcher`, `nlp.proofreader`, `nlp.calibrator` and
  rejects any read of `request_metadata.politeness_class`. Only
  `nlp.template_selector` may read it (to choose the polite vs
  neutral closed-template variant; tier-blind to routing).
- [x] **Tier-blind invariant.** Per-tenant template-selection by
  politeness MUST NOT change the underlying answer payload, only
  the surface form. `test_politeness_class_does_not_change_answer_payload`
  runs the same query twice (one polite, one curt) and asserts
  byte-identical `qa.answer.v1.parts[1:]` (data block) with
  potentially-different `parts[0]` (rendered template only).
- [ ] **Drift telemetry.** Per-week distribution of politeness_class
  (proportion polite / very_polite / curt) is exported as a
  Prometheus histogram; > 10pp shift week-over-week → `nlp.alert.v1{kind=politeness_distribution_drift, severity=info}`
  (informational; could be a UI change, not necessarily a problem).
- [ ] **Proof:** `test_politeness_marker_table_complete_for_zemberek_suffixal_forms`,
  `test_politeness_tokens_absent_from_classifier_input`,
  `test_politeness_class_only_used_by_template_selector_ast`,
  `test_politeness_class_does_not_change_answer_payload`,
  `test_politeness_distribution_drift_alert`.

#### 10.30.6 Search-operator syntax detection (`+`/`-`/`"…"`/`OR`/`AND`) → explicit refusal

- [x] **Closed `search_operator_patterns.tr.yaml`** detects power-user
  search syntax: leading `+`/`-` on word boundary
  (`+galatasaray -fenerbahçe`), bare `OR`/`AND` uppercase keywords
  (Turkish equivalents `VE`/`VEYA` ALL-CAPS), `site:`/`from:`/`title:`
  field-prefixed terms, double-quoted exact-match spans (covered
  partially by §10.26.9 paste hygiene but the *semantics* are
  different — paste hygiene strips quotes; this addendum *honors*
  them as exact-match assertions). Detection is an OR over all
  patterns; any hit → `query_style=search`.
- [ ] **v1 contract: refuse, never reinterpret.** `query_style=search`
  → short-circuit dispatch to `meta.search_syntax_unsupported`
  with closed Turkish template *"Bu sistem doğal dilde sorulara
  yanıt veriyor; arama operatörleri (+, -, OR, AND, tırnak) şu an
  desteklenmiyor. Lütfen sorunuzu cümle olarak yazınız."* Defends
  against `+galatasaray` being misread as the literal token
  `+galatasaray` (Symspell-corrected to garbage) or as natural
  emphasis (silently misinterpreting the user's intent).
- [ ] **Quoted-exact-match exception (forward hook).** Reserved
  enum value `query_style=quoted_exact_search` (dormant at v1) for
  future support of `"şampiyonlar ligi"` as exact-string entity
  resolution. Schema lands now; route returns
  `meta.search_syntax_unsupported` until the entity-exact-match
  path lands in a future phase.
- [x] **AST guard: search-operator detection runs BEFORE classifier.**
  `test_search_operator_detection_pre_classifier_ast` walks the
  pipeline order and asserts the detector fires before any
  expensive classifier / extractor work (cost containment + no
  search-style query reaches the classifier and contributes to
  intent-distribution drift).
- [ ] **Proof:** `test_search_operator_patterns_detect_plus_minus`,
  `test_search_operator_detects_ve_veya_uppercase_only`,
  `test_search_operator_detects_field_prefix`,
  `test_quoted_exact_match_route_is_reserved_enum`,
  `test_search_operator_short_circuit_returns_closed_template`,
  `test_search_operator_detection_pre_classifier_ast`.

#### 10.30.7 Cross-turn anaphora resolver (`onlar` / `bunlar` / `kendisi` / `orası`)

- [ ] **Closed `anaphora_pronouns.tr.yaml`** lists Turkish anaphoric
  pronouns and their type-constraints: `onlar`/`bunlar`/`şunlar`
  (plural; antecedent must be a *set* of teams or players —
  fixture-set, derby-week multi-fixture, top-N standings list);
  `o` (singular; team OR player OR fixture — type ambiguous);
  `kendisi` (formal singular; person only — coach / referee /
  player); `orası`/`burası`/`şurası` (locative; venue only);
  `oraya`/`buraya` (locative + direction); `oradakiler` (locative +
  plural-resident; team or supporter group). Each entry carries
  the type-constraint as a closed enum so antecedent search is
  constrained.
- [ ] **Cross-turn antecedent search.** Conversation context
  (§10.25.1) ships a per-conversation entity-mention stack
  (insertion-ordered, capped at `nlp_anaphora_lookback_turns=5`,
  `nlp_anaphora_lookback_seconds=900` whichever fires first).
  When an anaphoric pronoun is detected in the current turn, the
  resolver scans the stack newest-first and picks the most-recent
  type-compatible mention. Confidence floor:
  `nlp_anaphora_min_antecedent_confidence=0.70` (computed as
  recency-decay × type-match × salience). Below floor → emit
  disambiguation answer (closed template *"Hangi takımı / oyuncuyu
  kastettiğinizi netleştirir misiniz? Son konuşmada şu adlar
  geçti: A, B, C."*) — never silently pick.
- [ ] **Type-constraint AST guard.**
  `test_anaphora_resolver_respects_type_constraint_ast` runs a
  golden fixture stack and asserts the resolver only matches
  type-compatible candidates (`orası` cannot resolve to a team).
- [ ] **Stack staleness gate.** Antecedents older than
  `nlp_anaphora_lookback_seconds` are silently evicted but the
  fact of eviction is recorded as
  `nlp.event.v1{kind=anaphora_antecedent_evicted}` (rate-limited
  per conversation per `nlp_anaphora_eviction_event_ratelimit_s=60`)
  for drift observability.
- [ ] **Multi-pronoun composition.** *"Onlar oraya gidecek mi?"*
  carries TWO anaphora (`onlar` = team-set; `oraya` = venue).
  Both must resolve independently; either ambiguous → single
  disambiguation answer covering both slots. Closed
  `anaphora_compose.yaml` lists the legal pronoun-cooccurrence
  patterns.
- [ ] **Cache-key salt.** L0 / L1 cache keys for anaphora-resolved
  queries include the resolved-antecedent IDs (NOT just the
  pronouns) so two different conversations with the same surface
  text but different antecedents do not cross-cache. Defends
  against the §10.30.12 cache-collision class for the
  conversational variant.
- [ ] **Proof:** `test_anaphora_pronoun_table_covers_all_zemberek_anaphora_lemmas`,
  `test_anaphora_resolver_respects_type_constraint_ast`,
  `test_anaphora_resolver_below_confidence_emits_disambiguation`,
  `test_anaphora_eviction_event_emitted_with_ratelimit`,
  `test_multi_pronoun_compose_emits_single_disambiguation`,
  `test_anaphora_resolved_cache_key_includes_antecedent_ids`.

#### 10.30.8 ASR-delivered punctuation-words & numeric tie-break (`virgül` / `yirmi bir`)

- [ ] **Closed `asr_punctuation_words.tr.yaml`** lists Turkish words
  for punctuation that ASR transcribes literally: `virgül`,
  `nokta`, `noktalı virgül`, `iki nokta`, `soru işareti`,
  `ünlem işareti`, `tire`, `parantez`, `tırnak`. Detection: only
  active when `request_metadata.input_modality=voice` (carried by
  the inbound `qa.request.v1` from §10.26.2). Adjacent-to-digit
  context strips and replaces with the literal punctuation
  character (`yirmi virgül beş` → `20,5`); standalone (no digit
  context) → strip silently and emit
  `nlp.event.v1{kind=asr_punctuation_word_stripped}` for drift
  observability.
- [ ] **Voice number-word ↔ digit tie-break table.** Closed
  `voice_number_context.tr.yaml` resolves the
  number-word-vs-digit ambiguity from §10.26.4 with input-modality
  context: `(voice, time-context)` → digit interpretation; `(voice,
  scoring-context)` → ordinal; `(voice, cardinality-context)` →
  raw number; `(voice, year-context)` → 4-digit year if 4 number
  words concatenate to a year-like value. Resolves the conflict
  from §10.26.4 where the same surface form had two valid
  interpretations.
- [ ] **AST guard: voice-only branches gated.**
  `test_asr_punctuation_word_stripping_only_in_voice_modality_ast`
  walks the normalize pipeline and asserts the punctuation-word
  branch is dead code when `input_modality != voice`. Defends
  against typed input containing the literal word `virgül`
  (e.g., a player nicknamed *Virgül*) being silently stripped.
- [ ] **Proof:** `test_asr_punctuation_words_stripped_only_in_voice_modality`,
  `test_asr_punctuation_word_emits_event_when_standalone`,
  `test_voice_number_tiebreak_resolves_time_to_digit`,
  `test_voice_number_tiebreak_resolves_score_to_ordinal`,
  `test_voice_number_tiebreak_resolves_year_to_four_digit`,
  `test_voice_only_branch_dead_when_typed_modality_ast`.

#### 10.30.9 Repeated-query within-conversation acknowledgement & summary-mode escalation

- [ ] **Repeated-query detector.** Same `(intent_id, primary_entity_set,
  modifier)` triple within the same conversation, within
  `nlp_repeated_query_window_s=300`, count > `nlp_repeated_query_threshold=3`
  → prepend closed-template ack *"Az önce sorduğunuz [X] için
  güncel cevap: ..."* (humanizer-bypassed; mirrors §10.27.3
  forensic-bundle template-discipline). Defends against the
  silent re-fetch hiding the user's confusion signal.
- [ ] **Escalation to summary-mode.** Repeat count >
  `nlp_repeated_query_summary_threshold=5` within the same window →
  emit closed-template *"Bu konuyu birkaç kez sordunuz. Belki
  şunu denemek istersiniz: özet modu (yaz: 'özet')."* with a
  forward-hook intent_id `data.conversation_summary` (reserved
  enum, dormant at v1).
- [ ] **Telemetry & abuse-resilience link.**
  `nlp.event.v1{kind=repeated_query_threshold_crossed, repeat_count, window_s}`
  emitted on every threshold crossing; per-conversation rolling
  window aggregated into the §10.27.6 coordinated-abuse detector
  signal set as a soft input (high repeat-rate from a single
  client_id across conversations is a rate-limit-evasion signal).
- [ ] **Cache-vs-fresh decision.** Repeat-detected → serve from
  cache IF `qa.answer.v1.cached_at` is within `nlp_repeated_query_cache_max_age_s=60`
  (NOT the regular cache TTL — repeat-context demands tighter
  freshness); else re-fetch even on cache hit. Mitigates the
  user-asks-because-the-answer-felt-stale case.
- [ ] **Proof:** `test_repeated_query_ack_template_prepended_at_threshold`,
  `test_repeated_query_summary_mode_template_at_higher_threshold`,
  `test_repeated_query_ack_humanizer_bypassed`,
  `test_repeated_query_threshold_event_emitted`,
  `test_repeated_query_serves_fresh_when_cache_older_than_repeat_max_age`,
  `test_repeated_query_signal_feeds_coordinated_abuse_detector`.

#### 10.30.10 Slur-obfuscation defense (`s*ktir`, `am*na`, `o.ç`)

- [ ] **Closed `offensive_obfuscated.tr.yaml`** lists ≥ 80 known
  obfuscation patterns for Turkish slurs (asterisk-replacement,
  dot-replacement, leetspeak, cyrillic-homoglyph variants beyond
  §10.21.5 confusables, intentional-typo `şktir`). Each row pairs
  the obfuscated pattern with the canonical slur token AND a
  regex-allowed-context (slurs in football commentary about an
  *event* — *"hakem o.ç gibi davrandı"* — are still slurs;
  no whitelist for "context").
- [ ] **Detection runs AFTER §10.21.5 confusables fold + §10.28.x
  PII redaction, BEFORE classifier.** Match → token replaced with
  canonical slur form, then routed via §10.22.9 offensive gate
  (existing closed refusal template). Defends against the
  user-evades-by-asterisk class.
- [ ] **PR-time review gate.** `offensive_obfuscated.tr.yaml` is
  in the §10.25.6 high-leverage table; CODEOWNERS requires
  `nlp-curator` + `nlp-compliance` (existing roles, no new role
  needed). The CI gate `test_offensive_obfuscated_pattern_min_coverage`
  enforces that every entry in `offensive_canonical.tr.yaml`
  (the source of canonical slurs) has at least 2 obfuscation
  variants in this file (one asterisk-style, one
  dot/separator-style minimum).
- [ ] **False-positive guardrail.** Pattern `o.ç` could match
  legitimate text *"3 üst, 2.5 ç(eyrek)"* etc.; each pattern row
  carries a `context_negation_regex` that vetoes the match. Any
  veto → emit `nlp.event.v1{kind=obfuscated_slur_negated, pattern_id}`
  for false-positive observability and future tuning.
- [ ] **Proof:** `test_obfuscated_slur_table_min_coverage_per_canonical`,
  `test_obfuscated_slur_detected_after_confusables_fold`,
  `test_obfuscated_slur_routes_through_offensive_gate`,
  `test_obfuscated_slur_context_negation_vetoes_match`,
  `test_obfuscated_slur_negation_event_emitted`.

#### 10.30.11 Venue → home-team inference (closed table, confidence-bounded)

- [x] **Closed `venues.tr.yaml`** lists active TR football venues with
  their home-team binding and a per-row `(season_start, season_end)`
  validity window: `Türk Telekom Stadyumu` → `Galatasaray` (season
  2011–present), `Vodafone Park` → `Beşiktaş` (2016–present),
  `Ülker Stadyumu Şükrü Saraçoğlu Spor Kompleksi` → `Fenerbahçe`
  (2016–present), `Ali Sami Yen` → `Galatasaray` (until 2010 —
  historical-only entry; mention without explicit historical
  context emits `nlp.event.v1{kind=historical_venue_mentioned}`),
  plus all Süper Lig + 1. Lig home venues. Sponsor-renamed entries
  carry `aka` aliases (per §10.24.7 sponsor-seasonality).
- [ ] **Inference confidence cap.** Venue-only mention (no explicit
  team) infers home team but caps `entity.team.confidence ≤ nlp_venue_inferred_team_confidence_cap=0.70`;
  the dispatcher cross-checks against
  `data.fixture_lookup{venue, date_range}` BEFORE committing
  (the venue could host a neutral-ground fixture — a cup final,
  Milli Takım match). Mismatch → ask disambiguation, never silent
  pick.
- [ ] **Cross-language byte parity.** `venues.tr.yaml` is consumed by
  Phase 9 gateway venue-search endpoint AND by NLP entity
  extractor; SHA-pinned with cross-language gate (mirrors
  §10.30.1 intent-enum pattern).
- [ ] **Proof:** `test_venue_table_covers_all_active_super_lig_venues`,
  `test_venue_inference_confidence_capped`,
  `test_venue_inference_cross_checks_fixture_lookup`,
  `test_venue_inference_disambiguates_on_neutral_ground_fixture`,
  `test_historical_venue_mention_emits_event`,
  `test_venues_yaml_cross_language_sha_match`.

#### 10.30.12 L0 LRU cache-collision integrity (per-pod salt + key-truncation defense)

- [x] **Per-pod cache-key salt.** L0 in-process LRU on each NLP pod
  is keyed by `sha256(pod_id || subject_key || schema_version || calibration_version)[:16]`
  rather than the §10.21.x `sha256(subject_key)[:8]` 64-bit truncate.
  16-byte (128-bit) prefix kills the §10.30 motivation
  (truncate-collision against the 64-bit subject-key bucket); the
  `pod_id` salt prevents two pods with adjacent traffic from
  observing aligned collisions.
- [x] **Cache-hit verification gate.** On every L0 hit, the entry's
  stored `subject_key_full_sha256` (not truncated) is compared
  against the request's; mismatch → drop entry, emit
  `nlp.alert.v1{kind=cache_subject_key_collision, severity=critical}`,
  re-RPC. Mirrors §10.21.x envelope-HMAC-mismatch pattern.
- [x] **L0/L1 schema-version namespacing.** Cache keys include
  `qa.answer.v1.schema_version` so the §10.27.7 schema-downgrade
  variants do not cross-cache (a v3 client and a v4 client asking
  the same surface query receive different rendered answers; cache
  must respect this). Per-version cache namespace.
- [x] **Proof:** `test_l0_cache_key_includes_pod_id_salt`,
  `test_l0_cache_key_uses_128bit_prefix_not_64bit`,
  `test_l0_cache_hit_verifies_full_subject_key_sha`,
  `test_l0_cache_collision_emits_critical_alert_and_redo_rpc`,
  `test_l0_cache_namespaced_by_schema_version`.

#### 10.30.13 Cross-conversation entity-graph staleness (re-resolve before answer)

- [ ] **Per-conversation entity-state TTL.** Each entity in the
  conversation context (§10.25.1) carries
  `last_resolved_state_at` and `state_class ∈ {pre_match, live,
  post_match, postponed, cancelled}`. On every subsequent turn
  that *references* the entity (anaphora resolution per §10.30.7
  OR explicit re-mention), the dispatcher checks
  `now - last_resolved_state_at`:
  - `pre_match` entity, age > `nlp_entity_pre_match_max_stale_s=300` (5 min) → re-resolve via `data.request.v1{kind=fixture_state}`
  - `live` entity, age > `nlp_entity_live_max_stale_s=30` (30 sec) → re-resolve
  - `post_match` entity, age > `nlp_entity_post_match_max_stale_s=3600` (1 hr) → re-resolve
- [ ] **State-change disclosure.** If re-resolution returns a
  state-class-different value (`pre_match → live`, `pre_match →
  postponed`, `live → post_match`), prepend closed-template
  Turkish disclosure *"Bahsettiğiniz [X] maçının durumu değişmiş:
  şimdi [Y]."* before the answer. Defends against the silent
  served-stale-tense answer.
- [ ] **State-change cache invalidation.** State-change → invalidate
  L0 + L1 cache entries for that entity (subject_key prefix scan
  on Redis L1 via §9.17.6 keyspace-notification, in-process
  iteration on L0). Mirrors right-to-erasure §10.25.9 pattern.
- [ ] **Proof:** `test_entity_state_ttl_per_class`,
  `test_entity_state_change_disclosure_template_prepended`,
  `test_entity_state_change_invalidates_caches`,
  `test_entity_state_change_invalidation_uses_keyspace_notification`.

#### 10.30.14 Boot-time corpus regression test (dev / CI only)

- [ ] **200-row golden corpus** (`ai/swarm/agents/nlp/tests/data/boot_regression_corpus.jsonl`)
  curated from PII-scrubbed, anonymized prior production traffic
  (per §10.27.x training-data exclusion rules — rows MUST come
  from approved, non-degraded, non-quarantined emissions; the
  curation pipeline is the same as eval-set §10.18). Each row
  carries the input + expected `(intent_id, top_3_entities,
  intent_modifier)` baseline.
- [ ] **Boot probe runs in dev / CI only** (`NEGELIR_PROFILE in
  {dev, ci}`); never in prod (cost + boot-time concerns). Replay
  every row through the full normalize → classifier → extractor
  pipeline; any drift on `(intent_id)` or top-1 entity → boot
  failure (CI) / boot warning (dev). Drift on top-2 / top-3
  entity or modifier → warning only.
- [ ] **Curation-vs-CI separation.** The boot-corpus is NEVER
  used as classifier training data (§10.27.x training-vs-eval
  membership manifest invariant carries through). The corpus is
  versioned with its own `boot_corpus_version` (semver) and is
  refreshed on a quarterly cadence; refresh requires
  `nlp-curator` + `nlp-compliance` two-reviewer rule.
- [ ] **Drift-tolerance schedule.** v1 ships with strict
  zero-tolerance on `intent_id`; allows `top_1_entity` drift at
  ≤ 2 rows out of 200 (one classifier minor-version retrain can
  legitimately shift one or two boundary cases). Tolerance
  ratchets down to ≤ 1 row at v2 and 0 at v3; tracked in
  ROADMAP §10.30.14 sub-bullet.
- [ ] **Proof:** `test_boot_corpus_min_row_count`,
  `test_boot_corpus_intent_drift_zero_tolerance`,
  `test_boot_corpus_top1_entity_drift_within_tolerance`,
  `test_boot_corpus_not_in_classifier_training_data_manifest`,
  `test_boot_corpus_version_bumps_require_two_reviewers`.

#### 10.30.15 Cross-phase impact, configuration knobs, and event/alert kinds

- [ ] **Cross-phase impact.**
  - Phase 9 gateway: consumes `intent_enum_spec.json` (§10.30.1) +
    `venues.tr.yaml` (§10.30.11) cross-language; refuses boot on
    SHA mismatch.
  - Phase 7 sec: politeness-class (§10.30.5) feeds nothing
    (politeness is tier-blind); slur-obfuscation defense
    (§10.30.10) pre-empts §7 offensive-input gate so §7 sees
    canonical-slur tokens, not obfuscated ones (consistent with
    §7 contract).
  - Phase 8 ops: new `nlp.alert.v1` kinds register with the alert
    routing table (`cache_subject_key_collision` → critical →
    pager; `wh_prior_drift` → warn → dashboard; `politeness_distribution_drift`
    → info → log-only).
  - Phase 5 predictor: new intent_id `predict.match_outcome.conditional`
    consumes the existing `predict.approved.v1` topic with an
    additive `request_metadata.conditional_clause_text` field
    (additive-only schema; no Phase 5 code change required at
    v1 — predictor ignores the field; future predictor versions
    may consume it for conditional-aware modelling).
  - Phase 6 proofreader: new closed-text disclosures
    (conditional-prediction caveat per §10.30.4, repeated-query
    ack per §10.30.9, state-change disclosure per §10.30.13)
    must be in the proofreader closed-template allowlist; none
    pass through humanizer.
  - Phase 12 chaos: new chaos scenarios — `chaos.l0-cache-collision-injection`
    (validates §10.30.12 verification gate fires);
    `chaos.entity-state-change-mid-conversation` (validates
    §10.30.13 disclosure prepend); `chaos.repeated-query-burst`
    (validates §10.30.9 thresholds without false-firing the
    coordinated-abuse detector).
- [ ] **Configuration knobs (~22 new keys, §10.19 triangle update).**
  | Key | Default | Purpose |
  |---|---|---|
  | `nlp_intent_enum_v4_enabled` | `true` | Hard cutover guard for the additive intent-enum bump. |
  | `nlp_wh_prior_log_odds_max` | `1.5` | Cap per-WH-word logit nudge to prevent over-correction. |
  | `nlp_wh_prior_drift_alert_pp` | `2.0` | Warn threshold on weekly prior-drift. |
  | `nlp_idiom_max_phrase_len_tokens` | `5` | Longest-match window for idiom expansion. |
  | `nlp_idiom_ambiguous_event_ratelimit_s` | `300` | Per-idiom emission rate-limit. |
  | `nlp_conditional_marker_lookahead_tokens` | `8` | Window to detect conditional + verb-tense pair. |
  | `nlp_politeness_marker_strip_enabled` | `true` | Master toggle for the strip-and-record path. |
  | `nlp_politeness_distribution_drift_pp` | `10.0` | Weekly drift trigger. |
  | `nlp_search_operator_detection_enabled` | `true` | Master toggle (off = re-interpret as natural — NOT recommended). |
  | `nlp_anaphora_lookback_turns` | `5` | Cross-turn antecedent search depth. |
  | `nlp_anaphora_lookback_seconds` | `900` | Time-bound on antecedent search. |
  | `nlp_anaphora_min_antecedent_confidence` | `0.70` | Below floor → disambiguation. |
  | `nlp_anaphora_eviction_event_ratelimit_s` | `60` | Per-conversation event rate-limit. |
  | `nlp_repeated_query_window_s` | `300` | Repeat-detection window. |
  | `nlp_repeated_query_threshold` | `3` | Ack-prepend trigger. |
  | `nlp_repeated_query_summary_threshold` | `5` | Summary-mode escalation trigger. |
  | `nlp_repeated_query_cache_max_age_s` | `60` | Tighter freshness for repeat context. |
  | `nlp_venue_inferred_team_confidence_cap` | `0.70` | Caps venue-only team inference. |
  | `nlp_entity_pre_match_max_stale_s` | `300` | Pre-match entity-state TTL. |
  | `nlp_entity_live_max_stale_s` | `30` | Live entity-state TTL. |
  | `nlp_entity_post_match_max_stale_s` | `3600` | Post-match entity-state TTL. |
  | `nlp_boot_corpus_top1_entity_drift_max_rows` | `2` | v1 drift tolerance. |
- [ ] **Event/alert kind inventory (additive-only, CODEOWNERS-protected
  closed enums per §10.27.6 / §10.28.13).**
  - `nlp.event.v1` new kinds: `intent_decision_breakdown`,
    `idiom_expansion`, `idiom_ambiguous`, `asr_punctuation_word_stripped`,
    `repeated_query_threshold_crossed`, `obfuscated_slur_negated`,
    `historical_venue_mentioned`, `anaphora_antecedent_evicted`.
  - `nlp.alert.v1` new kinds: `wh_prior_drift` (warn),
    `politeness_distribution_drift` (info),
    `cache_subject_key_collision` (critical).
- [ ] **CODEOWNERS additions.** New file group:
  `ai/common/nlp/intent_enum_spec.json`,
  `ai/nlp/lang_tr/wh_intent_map.tr.yaml`,
  `ai/nlp/lang_tr/idioms.tr.yaml`,
  `ai/nlp/lang_tr/idiom_context.tr.yaml`,
  `ai/nlp/lang_tr/conditional_markers.tr.yaml`,
  `ai/nlp/lang_tr/politeness_markers.tr.yaml`,
  `ai/nlp/lang_tr/search_operator_patterns.tr.yaml`,
  `ai/nlp/lang_tr/anaphora_pronouns.tr.yaml`,
  `ai/nlp/lang_tr/anaphora_compose.yaml`,
  `ai/nlp/lang_tr/asr_punctuation_words.tr.yaml`,
  `ai/nlp/lang_tr/voice_number_context.tr.yaml`,
  `ai/nlp/lang_tr/offensive_obfuscated.tr.yaml`,
  `ai/nlp/lang_tr/venues.tr.yaml`. All require `nlp-curator`
  reviewer; `idioms.tr.yaml` + `idiom_context.tr.yaml`
  additionally require new `nlp-domain-football` reviewer
  group; `offensive_obfuscated.tr.yaml` additionally requires
  `nlp-compliance`. `intent_enum_spec.json` additionally
  requires Go owner (cross-language single-source per §10.30.1).
  `make verify.nlp-codeowners` CI-gated.
- [ ] **Versioning.** `swarm` minor (additive intent-enum bump +
  new closed tables + new `intent_modifier=conditional` enum
  value) + `docs` minor in same commit. Chart compatibility
  block re-pinned (no new third-party deps; uses existing
  Zemberek + Symspell + python-crfsuite stack).
- [ ] **Tracker row + ROADMAP checkbox flips** per AGENTS.md §3 + §3.4
  — every checkbox in §10.30.1–§10.30.15 flipped to `[x]` at landing,
  with §10.20 DoD item 28 also flipped.
