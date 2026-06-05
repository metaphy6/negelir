# Phase 10 §10.31 — Pragmatics, semantic-frame integrity, final-mile reliability

> **Provenance.** Carved out of `docs/planning/ROADMAP.md` Phase 10 on the Phase 10 split (post-13th-pass) so the ROADMAP stays navigable. Content here is the **binding** Phase 10 contract; ROADMAP §10 now points at this folder. Any edit must update `xops/versioning/chart.json` (`docs` minor) and the tracker (per AGENTS.md §3 + §6.1). Cross-phase references (Phase 5/7/8/9/11/12/13a/14/16/19/20) remain authoritative against ROADMAP and the matching `docs/design/*.md` anchors.


### 10.31 Pragmatics, semantic-frame integrity, and final-mile reliability (binding addendum)

> **Why this section exists.** §10.0–§10.30 closed eleven independent
> floors covering integrity, TR-language correctness, production
> serving, TR-input completeness, lifecycle/conversation, morphology
> + modality + counterfactual, match-lifecycle + abuse + regulatory
> + operator tooling, authentic-Turkish orthography + structure +
> resource discipline, deep-morphology + telegraphic-input + silent
> failure, and conversational completeness + intent-enum closure +
> classifier-bias. Twelfth-pass review against (a) authentically
> wrong / sloppy Turkish that fans actually type and (b) the
> production-reliability boundary between NLP and downstream
> consumers surfaces a residual class of *confidently-wrong*,
> *operationally-opaque*, and *integrity-soft* cases the prior
> eleven passes did not close: (i) **sarcasm and ironic praise** in
> Turkish football discourse (`harika oynadılar!` after a 0-5 loss)
> route to opinion-shaped intents that the system answers
> straight-faced — sentiment is positive, semantics are negative,
> classifier has no signal; (ii) **question-tag pragmatics**
> (`Galatasaray kazandı, değil mi?` is *confirmation-seeking* and
> presupposes truth; `Galatasaray kazandı mı?` is
> *information-seeking* and presupposes nothing) collapse to the
> same intent today, so the system silently answers a wrong-presupposition
> query without flagging the user's incorrect assumption; (iii)
> **pro-drop / null-subject** queries (`yenecek mi?` with no
> explicit team) rely on cross-turn anaphora (§10.30.7) but
> §10.30.7 only resolves *explicit* pronouns — the *absence* of a
> subject is a different signal that needs its own resolver with a
> defined default-team policy; (iv) **multi-genitive possessive
> chains** (`Galatasaray'ın Fenerbahçe ile maçında kalecisinin
> formu` — 3-level possessive) tokenise correctly under §10.28
> but the *semantic frame* (whose-form-of-whose-keeper-in-whose-match)
> is left to classifier inference, which routinely picks the wrong
> head; (v) **comparative degree composition** (`daha`, `en`,
> `kadar`, `gibi`, `-(ı)mtırak`) is partially handled by §10.29.8
> comparative fan-out but the *degree* (more vs most vs as-much-as
> vs roughly) and the *negative-comparative* (`kadar değil`) are
> not closed-table; (vi) **score-notation convention ambiguity**
> (`Galatasaray 2-1 Fenerbahçe` is winner-first in spoken Turkish
> commentary but home-team-first in written match reports) — both
> conventions appear in user input with no marker, and the
> entity extractor today picks per-row alphabetical-first which
> silently flips ~40% of cases; (vii) **negation-scope at clause
> boundary** (`Galatasaray Fenerbahçe'yi yenmedi mi?` is
> *rhetorical-confirmation* in colloquial Turkish ≈ "*they did
> beat them, didn't they*", BUT in formal register is
> *genuine-negative-question* ≈ "*did they not beat them*") —
> tense + register + intonation-marker absence determine which;
> (viii) **output-side TR grammar correctness** has no
> proofreader gate today — Jinja templates can render with
> wrong vowel-harmony suffix (`-ı` vs `-i`), wrong consonant
> mutation (`-da` vs `-de` after vowel-harmony resolved on a
> dynamically-bound entity name), or wrong genitive marker
> (`'ın` vs `'in` vs `'nın` vs `'nin`), and the system ships
> grammatically-broken Turkish answers that the classifier
> tier never sees because it operates on input not output;
> (ix) **refusal-template rotation** — every meta.* refusal
> within a conversation today returns the byte-identical closed
> template, which feels robotic and feeds the §10.30.9
> repeated-query confusion signal as a false-positive; refusals
> need a bounded equivalent-template pool with deterministic
> per-`request_id` rotation (replay-stable) and a structured
> `refusal_reason_code` enum so analytics can drive product
> decisions; (x) **lexicon vs LeagueCatalog conflict** —
> `ai/common/league_config.py` (Phase 13) and `lexicon.tr.yaml`
> can both define a team alias (e.g. *G.Saray* → which
> canonical?) and there is no defined precedence today, so
> classifier-time and gateway-time entity resolution can
> silently disagree; (xi) **wire-integrity end-to-end** — the
> §10.21.x envelope HMAC and §10.26.7 body HMAC defend against
> bus-envelope mutation between producer and broker, but the
> *gateway* re-emits the answer to the user with no outbound
> integrity check, so a compromised gateway pod (or in-process
> middleware bug) can silently mutate the rendered answer
> after proofreader sign; (xii) **per-intent SLO** — `meta.help`
> and `predict.match_outcome.conditional` have wildly different
> latency expectations (200ms vs 2s), but §10.12 ships a single
> p99 budget which is dominated by the slow class and hides
> regressions in the fast class; (xiii) **healthz realism** —
> the NLP healthz endpoint today checks process-alive +
> bus-reachable, but does not perform an actual classifier
> inference roundtrip on a baked golden, so a corrupt
> `intent.bin` or unloadable `crf_model` ships green-healthz
> and only fails on first user request; (xiv) **multi-subquery
> budget governance** — §10.24.5 splits up to 3 subqueries on
> run-on input, and each subquery today gets a *full* humanizer
> + per-pipeline budget, so an adversarial 3-way split
> multiplies the per-request budget 3x — budgets must be
> SHARED across the split, not per-subquery; (xv) **lexicon
> canary shadow-comparison** — promoting a new lexicon today
> goes through §10.25.6 PR governance + §10.30.x SHA-pinning,
> but the actual entity-resolution behavioural diff between
> old and new is never measured on real traffic before
> promotion, so a lexicon PR that is syntactically clean and
> review-approved can still flip 5% of entity resolutions on
> production traffic; canary needs a shadow-A/B that compares
> old-vs-new entity-resolution outputs on N requests and
> gates promotion on `<X% disagreement`. This addendum closes
> all fifteen.

#### 10.31.1 Sarcasm & ironic-praise detection (refusal, never re-route)

- [x] **Closed `sarcasm_markers.tr.yaml`** lists Turkish sarcasm
  cues that football fans use systematically: opinion-shaped
  superlative + recent-defeat context (`harika oynadılar`,
  `muhteşem maç`, `şahane defans`, `efsane gol` after a loss);
  ironic-quotation `"…"` around a praise word (`"yıldız"
  oyuncumuz`); diminutive-of-respect (`takımcığımız`,
  `hocacığımız`); explicit irony tags (`tabii ya`, `ne güzel`,
  `helal olsun!`, `hayırlısı`); negative-amplifier-with-positive
  surface (`çok iyiydiler!` with `!!!`+ negative-event token
  within ±10 tokens). Each entry carries (a) a *cue_class*
  (`opinion_superlative` / `quotation_irony` / `diminutive` /
  `ironic_tag` / `amplifier_with_negation_context`), and (b) a
  *requires_context* flag — most cues require a co-occurring
  recent-negative-event token (loss, defeat-score, red card,
  manager-firing) within `nlp_sarcasm_context_window_tokens=10`.
- [x] **Sarcasm-detector stage in dispatch.** New deterministic
  stage runs AFTER §10.30.5 politeness-strip and AFTER §10.30.3
  idiom-expansion, BEFORE classifier. Detection → set
  `intent_modifier=sarcastic` (additive enum value joining
  `none`/`comparative`/`conditional` from §10.30.4 → 4-valued).
  Dispatcher routes `sarcastic` modifier on opinion-shaped
  intents to `meta.opinion_unsupported` (NOT to `predict.*` or
  `data.sentiment.*`) with a closed Turkish refusal *"Yorum
  içerir görünen ifadeler için cevap üretmiyorum; somut bir
  veri sorusu yöneltirseniz yardımcı olabilirim."* Defends
  against the *answer-the-praise-as-if-genuine* class.
- [x] **Tier-blind invariant.** AST guard ensures the
  sarcasm-detector output (`intent_modifier=sarcastic` and the
  detector's internal cue-evidence list) is consulted ONLY by
  the dispatcher refusal path; never by the classifier
  (sarcasm cues must not become latent classifier features),
  the proofreader (sarcasm has nothing to do with output
  proofing), or the cache key. Cache key for sarcastic queries
  is the post-strip canonical form, so the same praise query
  in a non-sarcastic context (e.g. asked the day after a 5-0
  win) routes correctly through the regular path.
- [x] **False-positive guardrail.** Cues without context
  (`harika oynadılar` immediately after a real win) → no
  modifier set; emit `nlp.event.v1{kind=sarcasm_cue_no_context,
  cue_id}` for false-positive observability and PR-time
  context-window tuning. Per-cue precision tracked in eval-set
  §10.18; cues with precision < `nlp_sarcasm_cue_min_precision=0.85`
  on the eval set are auto-disabled at boot with a warning.
- [ ] **Drift telemetry.** Per-week cue-fire-rate is exported as
  a Prometheus histogram; > 50% week-over-week shift on any
  individual cue → `nlp.alert.v1{kind=sarcasm_cue_rate_drift,
  severity=info}` (informational; could be a real-world
  match-result swing, not necessarily a problem).
- [ ] **Proof:** `test_sarcasm_marker_table_codeowners_enforced`,
  `test_sarcasm_detector_runs_after_politeness_strip_ast`,
  `test_sarcasm_modifier_set_on_cue_plus_context`,
  `test_sarcasm_modifier_routes_opinion_intent_to_meta_opinion_unsupported`,
  `test_sarcasm_cues_absent_from_classifier_feature_vector_ast`,
  `test_sarcasm_cue_without_context_emits_no_context_event`,
  `test_sarcasm_cue_below_eval_precision_auto_disabled_at_boot`,
  `test_sarcasm_cache_key_is_post_strip_canonical_form`.

#### 10.31.2 Question-tag pragmatics (`değil mi` vs `mi`) — confirmation-seeking dispatch

- [ ] **Closed `question_tag_classifier.tr.yaml`** distinguishes
  three Turkish question shapes by surface form (deterministic;
  no classifier needed):
  - **Information-seeking** (`mi/mı/mu/mü` only, no negative
    polarity, no `değil`): `Galatasaray kazandı mı?` → no
    presupposition; default dispatch.
  - **Confirmation-seeking tag** (`, değil mi?` clause-final,
    after positive verb): `Galatasaray kazandı, değil mi?` →
    presupposes the positive proposition is true; user expects
    confirmation; new field `qa.intent.v1.pragmatic_class=confirmation_seeking`.
  - **Negative information-seeking** (`-ma/-me + mi/mı`):
    `Galatasaray kazanmadı mı?` → presupposes nothing; treated
    as information-seeking; `pragmatic_class=information_seeking`.
- [ ] **Confirmation-seeking dispatch contract.** When
  `pragmatic_class=confirmation_seeking`, the dispatcher
  fetches the data as usual BUT the proofreader inspects the
  result against the user's presupposed proposition:
  - **Match (presupposition true)** → closed prepend *"Evet,
    [X]."* before the regular answer.
  - **Mismatch (presupposition false)** → closed prepend
    *"Aslında hayır, [X]."* with the corrected fact. Defends
    against silently answering with a fact that contradicts
    the user's stated assumption — which in colloquial
    Turkish reads as the system *agreeing* with the wrong
    belief by omission.
- [ ] **Rhetorical-negative disambiguation hook to §10.31.7.**
  When the surface is `Galatasaray Fenerbahçe'yi yenmedi mi?`,
  surface alone is ambiguous between confirmation-seeking
  rhetorical (≈ "*they did, didn't they*") and genuine
  negative-information (≈ "*did they not*"); §10.31.7 owns the
  resolution; this section's contract is to *not* commit a
  pragmatic_class until §10.31.7 fires.
- [ ] **Schema-version bump.** `qa.intent.v1` →
  `schema_version=5` (additive: new `pragmatic_class` enum
  field; default `information_seeking` so v4 producers/
  consumers unchanged; §10.27.7 schema-downgrade negotiation
  honored — old SDK clients receive the answer without the
  prepend, semantically equivalent at worst).
- [ ] **Tier-blind invariant.** Pragmatic class never affects
  routing, classifier, or cache key — only the proofreader's
  prepend choice. AST guard
  `test_pragmatic_class_only_used_by_proofreader_prepend_ast`.
- [ ] **Proof:** `test_question_tag_classifier_distinguishes_three_shapes`,
  `test_confirmation_seeking_match_emits_evet_prepend`,
  `test_confirmation_seeking_mismatch_emits_aslinda_hayir_prepend`,
  `test_negative_information_seeking_emits_no_prepend`,
  `test_pragmatic_class_only_used_by_proofreader_prepend_ast`,
  `test_qa_intent_v4_client_negotiation_strips_pragmatic_class`.

#### 10.31.3 Pro-drop / null-subject resolver (the *absence* of subject)

- [ ] **Closed `pro_drop_intent_classes.tr.yaml`** lists intent
  classes where Turkish pro-drop is grammatical and ambiguous:
  predict.* (subject = team or player; *yenecek mi?* needs a
  subject), data.lineup_* (subject = team), data.score_current
  (subject = fixture; can be inferred from time-context), etc.
  Each class carries a `pro_drop_resolution_strategy`:
  `cross_turn_anaphora_then_default_team` /
  `cross_turn_anaphora_then_disambiguation` /
  `time_context_only` / `disambiguation_only`.
- [ ] **Pro-drop detector.** Runs after §10.5 entity extraction,
  before dispatch. If the intent's `pro_drop_resolution_strategy`
  is non-trivial AND no subject-class entity (team / player /
  fixture per intent class) was extracted, fire the resolver:
  - **Step 1 — cross-turn anaphora reuse.** Reuse the §10.25.1
    conversation-context entity stack (NOT the explicit-pronoun
    resolver of §10.30.7 — this is *implicit* subject reuse).
    Most-recent type-compatible entity within
    `nlp_pro_drop_lookback_turns=3` →
    `entity.subject.confidence = recency_decay × type_match`.
    Floor `nlp_pro_drop_min_implicit_subject_confidence=0.65`.
  - **Step 2 — default-team policy** (per `pro_drop_resolution_strategy=cross_turn_anaphora_then_default_team`).
    If conversation context is empty AND request carries
    `qa.request.v1.user_preferences.favorite_team` (Phase 9
    user-profile, additive-only), use that with cap
    `entity.subject.confidence ≤ nlp_pro_drop_default_team_confidence_cap=0.55`.
    Defends against silent-default to a wrong team for a
    user who has not declared favorites.
  - **Step 3 — disambiguation** (per `pro_drop_resolution_strategy=*_disambiguation`).
    No anaphora, no default → emit closed Turkish
    *"Hangi takımı/oyuncuyu kastettiğinizi belirtir misiniz?"*
    Never silently pick.
- [ ] **Pro-drop event audit.** Every pro-drop resolution emits
  `nlp.event.v1{kind=pro_drop_resolved, source ∈ {anaphora, default_team, disambiguation_emitted}, resolved_entity_id}`
  for time-travel re-render integrity (the audit bundle per
  §10.27.3 must reproduce the exact same resolution).
- [ ] **AST guard: pro-drop only fires on grammatical pro-drop
  classes.** `test_pro_drop_resolver_only_fires_on_pro_drop_intent_classes_ast`
  walks the intent-class table and asserts the resolver is
  dead-code for non-pro-drop intents (`meta.help`,
  `meta.search_syntax_unsupported`, etc.).
- [ ] **Cache-key salt.** L0 / L1 cache keys for pro-drop-resolved
  queries include the resolved-subject entity-ID (mirrors
  §10.30.7 explicit-pronoun cache-key pattern). Defends against
  the same surface-text query in two conversations cross-caching
  to the wrong subject.
- [ ] **Proof:** `test_pro_drop_intent_class_table_complete`,
  `test_pro_drop_resolver_uses_anaphora_first`,
  `test_pro_drop_default_team_capped_at_confidence`,
  `test_pro_drop_no_anaphora_no_default_emits_disambiguation`,
  `test_pro_drop_event_emitted_with_source_field`,
  `test_pro_drop_resolver_only_fires_on_pro_drop_intent_classes_ast`,
  `test_pro_drop_resolved_cache_key_includes_subject_id`.

#### 10.31.4 Multi-genitive possessive-chain semantic-frame parser

- [ ] **Closed `possessive_chain_grammar.tr.yaml`** declares the
  Turkish multi-genitive grammar pattern (right-headed,
  left-recursive): `[A'nın] [B(.GEN)] [C(.POSS)]` → C-of-B-of-A.
  Closed table lists the legal *type* compositions for football
  domain:
  | A type | B type | C type | Frame |
  |---|---|---|---|
  | team | team | match | "match between A and B" |
  | team | match | result | "result of A's match in B" |
  | team | match | player_role | "A's player in B's match" |
  | team | player | stat | "A's player's stat" |
  | match | player | stat | "stat of player in the match" |
  | competition | team | rank | "team's rank in the competition" |
- [ ] **Possessive-chain extractor.** Runs after §10.5 CRF
  extraction, before dispatch. Detects 2+ consecutive genitive/
  possessive markers (`-(n)ın/-(n)in/-(n)un/-(n)ün` for genitive
  + `-(s)ı/-(s)i/-(s)u/-(s)ü` for 3rd-person possessive),
  parses right-to-left with the closed type-grammar, and emits
  `qa.intent.v1.semantic_frame = {head_type, head_entity_id,
  modifiers: [{type, entity_id, role}]}` (additive field, schema
  bump joins §10.31.2's bump → `schema_version=5`).
- [ ] **Ambiguous-frame disambiguation.** When the chain admits
  multiple type-legal parses (e.g. `[Galatasaray'ın] [maçında]
  [kalecisinin] [formu]` could be "*the form of GS's keeper in
  THE-match*" vs "*the form of GS's keeper in GS's match*"
  with implicit-subject reuse), require an explicit-subject
  marker on B; absent → emit closed Turkish disambiguation
  *"İki olası okuma var: (1) [X], (2) [Y]. Hangisini
  kastediyorsunuz?"* Never silently pick.
- [ ] **Chain-depth cap.** `nlp_possessive_chain_max_depth=4`
  caps the parser; deeper chains (rare; mostly adversarial
  resource-exhaustion or syntax-error input) → refuse with
  closed Turkish *"Sorgunuzu daha kısa cümlelere bölerseniz
  daha iyi yanıt verebilirim."* Defends against
  combinatorial-explosion DoS on the type-grammar parser.
- [ ] **Cross-language byte parity.** `possessive_chain_grammar.tr.yaml`
  is consumed by Phase 9 gateway as part of `qa.intent.v1`
  schema validation (the gateway sees the produced
  `semantic_frame` field and must validate its shape against
  the same grammar); SHA-pinned with cross-language gate
  (mirrors §10.30.1 intent-enum + §10.30.11 venues pattern).
- [ ] **Proof:** `test_possessive_chain_grammar_parses_2_to_4_levels`,
  `test_possessive_chain_emits_semantic_frame_field`,
  `test_possessive_chain_ambiguous_emits_disambiguation`,
  `test_possessive_chain_depth_above_cap_refuses`,
  `test_possessive_chain_grammar_cross_language_sha_match`,
  `test_qa_intent_v4_client_negotiation_strips_semantic_frame`.

#### 10.31.5 Comparative-degree closed-table composition (`daha` / `en` / `kadar` / `gibi`)

- [ ] **Closed `comparative_degree.tr.yaml`** lists Turkish
  comparative-degree markers and their semantics:
  | Marker | Degree | Polarity | Example |
  |---|---|---|---|
  | `daha` + adj | comparative | positive | *daha iyi* |
  | `en` + adj | superlative | positive | *en iyi* |
  | `kadar` + adj | equative | positive | *kadar iyi* |
  | `kadar değil` + adj | equative | negative | *kadar iyi değil* |
  | `gibi` + adj | similative | neutral | *gibi oynuyor* |
  | `-(ı)mtırak/-msı` (suffixal) | attenuative | neutral | *iyimtırak* |
  | `çok daha` + adj | intensified-comparative | positive | *çok daha iyi* |
  | `bir o kadar daha` | doubled-equative-then-comparative | positive | *bir o kadar daha iyi* |
- [ ] **Composition with §10.29.8 comparative fan-out and
  §10.30.4 conditional modifier.** Comparative-degree feeds the
  existing `intent_modifier=comparative` from §10.29.8 BUT now
  carries a `comparative_degree ∈ {comparative, superlative,
  equative_positive, equative_negative, similative,
  attenuative, intensified}` sub-field. Dispatch matrix:
  - `equative_positive` → fan out to *both* legs symmetrically
    (no winner picked).
  - `equative_negative` → fan out + closed-template prepend
    *"Eşit olmadığı için karşılaştırma yapıyorum."*
  - `similative` → routes to `data.style_compare` (NEW intent
    in `data.*`, additive to §10.30.1 enum).
  - `attenuative` → strips the suffix and treats as base
    adjective with `attenuative=true` flag for template-only
    qualification (e.g. *iyimtırak* renders as "biraz iyi").
- [ ] **Negative-comparative semantic firewall.** Surface
  `Galatasaray Fenerbahçe kadar iyi değil` MUST NOT route to
  `predict.match_outcome` (a static-state assertion is not a
  prediction); routes to `data.form_compare` with
  `comparative_degree=equative_negative`. AST guard.
- [ ] **Proof:** `test_comparative_degree_table_complete`,
  `test_comparative_degree_composes_with_existing_modifier`,
  `test_equative_positive_fans_out_symmetrically`,
  `test_equative_negative_emits_disclaimer_prepend`,
  `test_similative_routes_to_style_compare`,
  `test_attenuative_suffix_stripped_with_template_flag`,
  `test_negative_comparative_does_not_route_to_predict_ast`.

#### 10.31.6 Score-notation order convention disambiguation (`2-1` left-team)

- [ ] **Closed `score_notation_conventions.yaml`** declares the
  two TR-football score-notation conventions and their *signal*
  patterns:
  - **Home-team-first** (written-report convention): `[Team A]
    [score₁]-[score₂] [Team B]` → A is home, B is away.
    Signal: precedes/follows a date+venue token, or appears in
    a paragraph-style block.
  - **Winner-first** (spoken-commentary convention):
    `[Team_winner] [score_winner]-[score_loser] [Team_loser]`
    → winner first regardless of home/away. Signal:
    `score₁ > score₂` AND no date/venue context.
- [ ] **Disambiguation rule.** When (a) `score₁ == score₂` (draw)
  → no ambiguity, both conventions agree; (b) `score₁ < score₂`
  AND home-team-first signals present → home-team-first;
  (c) `score₁ > score₂` AND winner-first signals present →
  winner-first; (d) otherwise → emit closed Turkish
  disambiguation *"[Team A] mı ev sahibiydi yoksa galip mi?
  Belirtirseniz daha doğru cevap verebilirim."* Never silently
  pick alphabetical-first (current §10.5 default).
- [ ] **Score-as-input vs score-as-output discipline.** This
  section governs *input parsing only*. The §10.7 template
  layer for *output* always uses home-team-first (canonical TR
  written convention); AST guard
  `test_score_output_template_uses_home_team_first`.
- [ ] **Proof:** `test_score_notation_conventions_table_complete`,
  `test_score_draw_no_ambiguity`,
  `test_score_with_date_venue_signal_uses_home_first`,
  `test_score_without_context_uses_winner_first_when_unequal`,
  `test_score_ambiguous_emits_disambiguation`,
  `test_score_output_template_uses_home_team_first`.

#### 10.31.7 Negation-scope at clause boundary (rhetorical vs genuine `değil mi`)

- [ ] **Closed `negation_scope_disambiguators.tr.yaml`** lists
  the Turkish surface markers and contextual cues that
  distinguish *rhetorical-negative-confirmation* from
  *genuine-negative-information*:
  - **Rhetorical signals** (→ `pragmatic_class=confirmation_seeking`,
    presupposed proposition is positive): present-tense surface
    + first-person-plural ownership marker (`bizimkiler`),
    colloquial register (lower-case, no formal honorifics),
    interjection co-occurrence (`yahu`, `be`, `ya`,
    `kardeşim`, `canım`).
  - **Genuine-negative signals** (→ `pragmatic_class=information_seeking`,
    no presupposition): formal register (capitalised opening,
    no slang), past-tense surface, third-person-distant
    reference (`takım`, `bu takım`), data-seeking co-occurrence
    (`kaç`, `ne zaman`, `hangi tarihte`).
- [ ] **Resolution algorithm.** Compute a rhetoric_score from
  the signal table (sum of fired-signal weights, clamped to
  [-1, 1]); `>= +0.5` → rhetorical; `<= -0.5` → genuine; in
  between → emit closed Turkish disambiguation *"Sorunuzu (1)
  Galatasaray Fenerbahçe'yi yendi mi (bilgi soruyorum) yoksa
  (2) Galatasaray Fenerbahçe'yi yendi, değil mi (onaylatmak
  istiyorum) olarak mı kastettiniz?"* Never silently pick.
- [ ] **Composition with §10.31.2.** This section's resolution
  fires BEFORE §10.31.2 commits its `pragmatic_class` (per
  §10.31.2's hook). On rhetorical-positive resolution, the
  proposition for §10.31.2's match/mismatch check is the
  *positive* form (negation cancels out — *"yenmedi mi?
  rhetorical"* presupposes "*yendi*").
- [ ] **Drift telemetry.** Per-week distribution of rhetoric_score
  bins exported as Prometheus histogram; > 15pp shift in any
  bin week-over-week → `nlp.alert.v1{kind=negation_scope_distribution_drift,
  severity=info}` for register-shift observability.
- [ ] **Proof:** `test_negation_scope_signal_table_complete`,
  `test_rhetorical_signal_resolves_positive_pragmatic_class`,
  `test_genuine_negative_signal_resolves_information_seeking`,
  `test_ambiguous_negation_scope_emits_disambiguation`,
  `test_rhetorical_resolution_feeds_pragmatic_class_positive_proposition`,
  `test_negation_scope_drift_alert`.

#### 10.31.8 Output-side TR grammar-check proofreader gate (post-render)

- [x] **`tr_output_grammar_validator.py`** — new proofreader
  stage that runs AFTER §10.7 template render, BEFORE
  §10.21.x envelope sign. Checks the rendered Turkish output
  for:
  - **Vowel-harmony violations on dynamically-bound suffixes.**
    Templates emit suffixes via Jinja filters (`{{ team | dat
    }}` → `Galatasaray'a`, `Fenerbahçe'ye`); a Jinja-filter
    bug or stale lexicon entry can produce *"Galatasaray'e"*
    (wrong vowel-harmony for back-vowel stem) which ships as
    the answer. Validator runs Zemberek vowel-harmony check
    on every `'X` apostrophe-suffixed token in the output.
  - **Consonant-mutation violations.** `Antep + 'da` → wrong;
    correct is `Antep + 'te` (final voiceless `p` triggers
    voiceless suffix). Validator runs §10.28.1 consonant-rule
    table over every locative-suffixed token.
  - **Wrong genitive marker.** `Galatasaray + nın` is wrong
    (no `n` buffer needed after consonant-final stem); correct
    `Galatasaray'ın`. Validator checks the buffer rule.
  - **Stem-final vowel deletion failures.** `oğul + u` → must
    drop to `oğlu`, not `oğulu`. Validator runs §10.29.1
    geminate/vowel-drop rules.
- [x] **Validation outcome contract.**
  - **All checks pass** → answer ships as-is.
  - **One or more violations detected** → DO NOT ship the
    answer; emit `nlp.event.v1{kind=tr_output_grammar_violation,
    template_id, violations: [{type, token, expected, got}]}`,
    fall back to a closed *grammar-fallback* template
    *"Yanıtım hazırlanırken bir hata oluştu. Lütfen tekrar
    deneyiniz."*, and emit
    `nlp.alert.v1{kind=tr_output_grammar_fallback_used,
    severity=warn}`. Defends against shipping
    grammatically-broken Turkish that the input pipeline
    never sees.
- [x] **Performance budget.** Validation cost must be
  ≤ `nlp_output_grammar_validator_p99_ms=15`; budget overrun
  triggers a kill-switch
  `nlp_output_grammar_validator_killswitch_enabled` (default
  off) that bypasses validation and emits
  `nlp.alert.v1{kind=tr_output_grammar_validator_killswitch_engaged,
  severity=critical}` for ops review.
- [x] **AST guard: validator runs after template render, before
  envelope sign.** `test_tr_output_grammar_validator_pipeline_position_ast`.
- [x] **Cross-language byte parity.** Vowel-harmony /
  consonant-mutation rule tables consumed by the validator are
  the same SHA-pinned files (§10.28.1) used by the input
  normalize stage; one-source-of-truth invariant.
- [x] **Proof:** `test_tr_output_grammar_validator_catches_vowel_harmony_violation`,
  `test_tr_output_grammar_validator_catches_consonant_mutation_violation`,
  `test_tr_output_grammar_validator_catches_genitive_buffer_violation`,
  `test_tr_output_grammar_validator_catches_stem_vowel_deletion_failure`,
  `test_tr_output_grammar_violation_falls_back_to_grammar_fallback_template`,
  `test_tr_output_grammar_violation_emits_event_and_alert`,
  `test_tr_output_grammar_validator_pipeline_position_ast`,
  `test_tr_output_grammar_validator_within_p99_budget`.

#### 10.31.9 Refusal-template rotation pool + structured `refusal_reason_code` taxonomy

- [ ] **Closed `refusal_template_pool.tr.yaml`** — every meta.*
  refusal carries (a) a single `refusal_reason_code` enum value
  (closed taxonomy below) and (b) a *pool* of ≥ 3 equivalent
  Turkish phrasings of the refusal text. Per-conversation,
  pool-index is selected deterministically by
  `index = sha256(conversation_id || refusal_reason_code)[:4] mod pool_size`,
  so the *same* conversation always sees the *same* phrasing
  for the *same* reason (no within-conversation rotation that
  would feed §10.30.9 repeated-query confusion), but *different*
  conversations see varied phrasings (no fleet-wide canned
  feel). Replay-stable: re-running the same `request_id`
  produces byte-identical output (audit-bundle requirement
  per §10.27.3).
- [ ] **Closed `refusal_reason_code` taxonomy** (additive enum
  on `qa.answer.v1`, schema bump joins §10.31.2 / §10.31.4 →
  `schema_version=5`):
  - `intent_unsupported_at_v1` — known closed-enum miss
    (§10.30.1 + future intents).
  - `entity_unrecognized_at_v1` — entity not in lexicon /
    catalog.
  - `entity_disambiguation_required` — multiple legal
    resolutions, no winner.
  - `pro_drop_no_subject` — pro-drop resolver hit
    disambiguation branch (§10.31.3).
  - `possessive_chain_ambiguous` — §10.31.4 disambiguation.
  - `score_notation_ambiguous` — §10.31.6 disambiguation.
  - `negation_scope_ambiguous` — §10.31.7 disambiguation.
  - `sarcasm_detected` — §10.31.1 refusal.
  - `counterfactual_past_unsupported` — §10.26.5 firewall.
  - `conditional_with_obligative_unsupported` — §10.26.5
    obligative refusal.
  - `search_syntax_unsupported` — §10.30.6.
  - `meta_opinion_unsupported` — opinion-shaped intent.
  - `live_query_during_calibration_freeze` — §10.27.x
    calibration-vs-fixture-state freshness gate.
  - `tier_unauthorized` — Phase 9 tier check failure.
  - `pii_detected_in_input` — §10.28.x PII pre-redaction
    (refusal variant when redaction would corrupt the query
    semantics).
  - `tr_output_grammar_fallback` — §10.31.8 validation
    fallback (rare; user-facing as "system error" but
    analytically distinct).
  - `repeated_query_summary_offered` — §10.30.9 escalation.
  - `chain_depth_exceeded` — §10.31.4 cap.
  - `meta_unspecified` — catch-all (must be < 1% of refusals
    in eval-set; > threshold → CI gate fails).
- [ ] **Analytics integration.** `qa.answer.v1.refusal_reason_code`
  feeds Prometheus counter `nlp_refusal_total{reason_code}`;
  per-week per-reason rate exported; rate spike > 3σ →
  `nlp.alert.v1{kind=refusal_reason_rate_spike,
  reason_code, severity=warn}` so product can prioritise
  closing the gap (e.g. a sustained spike in
  `intent_unsupported_at_v1` is a signal to add the intent
  to the next §10.30.1-style closed-enum bump).
- [ ] **Tier-blind invariant.** AST guard
  `test_refusal_reason_code_set_for_every_meta_intent_ast` —
  walks the dispatcher refusal paths and asserts every
  `meta.*` route sets a non-default `refusal_reason_code`.
- [ ] **Proof:** `test_refusal_template_pool_min_size_per_reason`,
  `test_refusal_pool_index_deterministic_by_conversation_id`,
  `test_refusal_pool_replay_stable_by_request_id`,
  `test_refusal_reason_code_taxonomy_complete`,
  `test_refusal_reason_code_set_for_every_meta_intent_ast`,
  `test_meta_unspecified_rate_below_eval_threshold`,
  `test_refusal_rate_spike_emits_alert`.

#### 10.31.10 Lexicon vs LeagueCatalog conflict resolution (catalog wins, audit logged)

- [ ] **Conflict-resolution invariant.** When `lexicon.tr.yaml`
  alias and `ai/common/league_config.py` (Phase 13 LeagueCatalog)
  alias resolve the same surface form to different canonical
  entity IDs, **the LeagueCatalog wins** (it is the authoritative
  source for league/team taxonomy; the lexicon is for textual
  expansion). The conflict MUST be logged at boot (every NLP pod
  scans for conflicts on lexicon load and emits one
  `nlp.alert.v1{kind=lexicon_catalog_alias_conflict, surface,
  lexicon_canonical, catalog_canonical, severity=warn}` per
  conflict per pod-boot).
- [ ] **Boot-time conflict-detection scan.** `make verify.lexicon-catalog-consistency`
  runs at CI as a separate gate; ANY detected conflict fails
  CI (forces explicit reconciliation in the same PR).
  Production pods log on boot but do not refuse boot (lexicon
  is hot-reloadable per §10.2; catalog changes deploy via
  Phase 13 release; race-window conflicts must be transient).
- [ ] **Resolution-time tracing.** Every entity resolution that
  *could* have hit a conflict (the surface had both a lexicon
  match and a catalog match) records a structured event
  `nlp.event.v1{kind=lexicon_catalog_alias_resolved, surface,
  chosen=catalog_canonical}` even when the two agreed
  (rate-limited per `nlp_lexicon_catalog_alias_event_ratelimit_s=300`
  per (surface, pod) tuple). Defends against the silent-drift
  case where a lexicon PR later introduces a conflict that
  goes unnoticed.
- [ ] **Forward hook to Phase 13 release.** When a Phase 13
  LeagueCatalog deploy lands a renaming (`Galatasaray A.Ş.` →
  `Galatasaray Spor Kulübü`), the NLP lexicon-curator workflow
  (§10.25.6) is auto-notified via a generated PR proposal so
  the lexicon expansions can follow. Dormant at v1; the
  notification webhook ships as a stub.
- [ ] **Proof:** `test_lexicon_catalog_conflict_resolves_to_catalog`,
  `test_lexicon_catalog_conflict_emits_boot_alert`,
  `test_lexicon_catalog_consistency_ci_gate_fails_on_conflict`,
  `test_lexicon_catalog_resolved_event_emitted_with_ratelimit`.

#### 10.31.11 Wire-integrity end-to-end answer checksum (proofreader → gateway)

- [ ] **`qa.answer.v1.outbound_checksum`** — additive field
  (schema bump joins §10.31.2 / §10.31.4 / §10.31.9 →
  `schema_version=5`) carrying
  `sha256(canonical_json(answer_payload_excluding_outbound_checksum)
  || outbound_secret_per_pod)`. Computed by the proofreader
  AFTER §10.31.8 grammar validation and AFTER §10.21.x
  envelope HMAC; the field is part of the envelope-HMAC'd
  body (so the §10.21.x envelope HMAC also covers the
  outbound_checksum field).
- [ ] **Gateway verification gate.** Phase 9 gateway, on
  consuming `qa.answer.v1`, recomputes the canonical-JSON
  SHA over the body (excluding `outbound_checksum`) and
  compares against the field. Mismatch → DO NOT emit to user;
  emit `nlp.alert.v1{kind=outbound_checksum_mismatch,
  severity=critical}`, return Phase 9 standard error
  payload to user. Defends against *in-process middleware
  mutation* in either NLP-side post-sign code paths or
  gateway-side pre-emit code paths (the §10.21.x envelope
  HMAC alone covers bus-transit but not in-process mutation
  on either end).
- [ ] **Outbound-secret rotation.** `outbound_secret_per_pod`
  is a 32-byte symmetric secret derived at pod boot from
  `nlp_outbound_secret_master + pod_id`; the master rotates
  on the §9.x sec-rotation cadence (90 days). Gateway reads
  the master from the same Phase 7 sec-rotation channel.
  Mirrors §10.26.7 envelope-HMAC key-rotation pattern.
- [ ] **AST guard.** `test_outbound_checksum_field_set_on_every_qa_answer_v1`
  walks the proofreader output paths and asserts every
  emitted `qa.answer.v1` carries a non-empty
  `outbound_checksum`. `test_outbound_checksum_excluded_from_self_input`
  asserts the canonical-JSON over the body for the SHA does
  NOT include the `outbound_checksum` field itself
  (otherwise the field would be self-referential).
- [ ] **Proof:** `test_outbound_checksum_set_on_every_emission`,
  `test_outbound_checksum_excluded_from_self_input`,
  `test_outbound_checksum_mismatch_blocks_gateway_emit`,
  `test_outbound_checksum_mismatch_emits_critical_alert`,
  `test_outbound_secret_rotates_on_sec_rotation_cadence`.

#### 10.31.12 Per-intent SLO classes + burn-rate alerts

- [ ] **Closed `intent_slo_classes.yaml`** assigns every
  closed-enum `intent_id` (per §10.30.1) to one of three SLO
  classes:
  | Class | p99 latency budget | Examples |
  |---|---|---|
  | `slo_fast` | 250ms | `meta.help`, `meta.search_syntax_unsupported`, all `meta.*_unsupported` refusals |
  | `slo_data` | 800ms | `data.fixture_lookup`, `data.lineup_*`, `data.standings`, `data.*_leader` |
  | `slo_predict` | 2500ms | `predict.match_outcome`, `predict.match_outcome.conditional`, `predict.match_outcome.comparative` |
- [ ] **Per-class SLO measurement.** Prometheus histogram
  `nlp_qa_answer_latency_seconds{intent_class, slo_class}`
  exported; per-class p99 burn-rate alert at the §8.x ops
  pattern (multi-window: 5min @ 14.4× burn fires
  `slo_burn_critical`; 1h @ 6× burn fires `slo_burn_warn`;
  per-class so a `slo_predict` regression doesn't drown out
  a `slo_fast` regression).
- [ ] **Class-assignment AST guard.**
  `test_every_intent_id_has_slo_class_assignment_ast` walks
  the §10.30.1 intent enum and asserts every value has a row
  in `intent_slo_classes.yaml`; missing → CI fail (forces
  PR-time decision on which SLO class a new intent belongs to).
- [ ] **Class-vs-budget invariant.** `test_intent_slo_classes_budgets_strictly_ascending`
  asserts the three class budgets are strictly ascending so
  the multi-class burn-rate-alert routing has no overlap
  ambiguity.
- [ ] **Cross-phase impact: Phase 9 gateway.** Gateway carries
  the same `intent_slo_classes.yaml` (cross-language byte-parity
  per §10.30.1 pattern) so its own per-route timeouts and
  retries are class-aware. Gateway timeout MUST be set to
  `class_budget × nlp_gateway_timeout_safety_factor=1.5` to
  give NLP headroom under load.
- [ ] **Proof:** `test_intent_slo_classes_table_covers_all_intent_ids`,
  `test_intent_slo_classes_budgets_strictly_ascending`,
  `test_per_class_slo_burn_alert_fires_independently`,
  `test_gateway_timeout_set_per_class_with_safety_factor`,
  `test_intent_slo_classes_cross_language_sha_match`.

#### 10.31.13 Healthz realism (classifier round-trip + template render on golden)

- [ ] **Replace process-alive healthz with realism healthz.** The
  NLP pod's `/healthz/ready` endpoint (consumed by
  Kubernetes readiness probe and §3.x supervisor health
  registry) currently returns 200 if the process is alive
  and bus-reachable. Replace with a *realism* probe that on
  every call:
  1. Loads a baked golden query (`ai/swarm/agents/nlp/tests/data/healthz_golden.json`,
     a single PII-scrubbed `qa.request.v1` with
     well-known expected `intent_id`, top-1 entity, and
     post-render template hash).
  2. Runs the FULL pipeline: normalize → idiom-expand →
     classifier-inference → entity-extract → dispatcher
     route → template render → §10.31.8 grammar validate.
     (Does NOT publish the result; pure in-process probe.)
  3. Compares actual `(intent_id, top_1_entity_id,
     post_render_template_sha)` against the baked
     expected. Mismatch → return 503 with a structured
     reason; match → 200.
- [ ] **Performance budget.** Probe cost ≤
  `nlp_healthz_realism_probe_max_ms=200` (well within the
  `slo_data` budget of §10.31.12). Probe budget overrun
  twice consecutively → return 503 (the pod is too loaded
  to do its job; let K8s evict it).
- [ ] **Probe rate-limit & memoisation.** Probe runs at most
  `nlp_healthz_realism_probe_min_interval_s=15` per pod;
  Kubernetes probes called more often receive the cached
  last result. Defends against probe-induced load amplification.
- [ ] **Healthz-failure event.**
  `nlp.event.v1{kind=healthz_realism_probe_failed, mismatch_field,
  expected, got}` emitted on every 503; rate-limited per
  pod per `nlp_healthz_realism_event_ratelimit_s=60`.
- [ ] **Golden refresh discipline.** `healthz_golden.json` is in
  the §10.30.14 boot-corpus governance scope (CODEOWNERS
  `nlp-curator` + `nlp-compliance`); refresh requires
  recomputing the expected `post_render_template_sha` after
  any template change.
- [ ] **AST guard.** `test_healthz_realism_probe_runs_full_pipeline_ast`
  walks the probe code and asserts every pipeline stage
  (normalize, idiom-expand, classifier, extractor, dispatcher,
  template, output-grammar-validator) is invoked. Defends
  against the probe degrading to a partial-pipeline check
  through accidental refactor.
- [ ] **Proof:** `test_healthz_realism_returns_200_on_match`,
  `test_healthz_realism_returns_503_on_intent_drift`,
  `test_healthz_realism_returns_503_on_template_sha_drift`,
  `test_healthz_realism_returns_503_on_budget_overrun_twice`,
  `test_healthz_realism_probe_runs_full_pipeline_ast`,
  `test_healthz_realism_event_emitted_with_ratelimit`,
  `test_healthz_realism_memoised_within_min_interval`.

#### 10.31.14 Multi-subquery budget governance (shared, not per-subquery)

- [ ] **Shared-budget invariant.** When §10.24.5 splits a run-on
  query into ≤ 3 subqueries, ALL of:
  - per-pipeline CPU budget (§10.28.x)
  - per-pipeline RSS budget (§10.28.x)
  - humanizer token budget (§10.8)
  - per-pipeline wall-clock budget (§10.31.12 SLO-class budget)
  - lexicon hot-reload back-pressure budget (§10.28.x)

  are **divided** across the subqueries (each subquery gets
  `budget × nlp_subquery_budget_share_factor=0.4`, so 3
  subqueries collectively get 1.2× a single budget — a small
  multiplier for orchestration overhead, NOT 3×). Defends
  against the *adversarial-3-way-split-multiplies-budget*
  class.
- [ ] **Subquery-fan-out cap.** Per-request cap
  `nlp_max_subqueries_per_request=3` (matches §10.24.5
  cap; reasserted here as the budget invariant depends on
  it). Inputs that yield > 3 subqueries → §10.31.9
  `chain_depth_exceeded`-style refusal with closed Turkish
  *"Sorgunuzu daha kısa cümlelere bölerseniz daha iyi
  yanıt verebilirim."*
- [ ] **Single-subquery degenerate case invariant.** When the
  splitter produces exactly 1 subquery (the common case), the
  budget-share factor is 1.0 (no penalty). AST guard
  `test_single_subquery_gets_full_budget_ast`.
- [ ] **Cross-cutting refusal vs partial-success contract.**
  When ANY subquery exhausts its share, the ENTIRE multi-
  subquery answer is marked `degraded=true` (existing field
  from §10.16) with a closed Turkish disclosure
  *"Birleşik sorunuzun bir kısmına yanıt veremedim."* —
  never silently drop a subquery, never silently extend
  shared budget for the surviving subqueries.
- [ ] **Proof:** `test_multi_subquery_budgets_divided_by_share_factor`,
  `test_single_subquery_gets_full_budget`,
  `test_subquery_count_above_cap_refuses`,
  `test_subquery_budget_exhaustion_marks_answer_degraded`,
  `test_subquery_budget_exhaustion_emits_closed_disclosure`,
  `test_subquery_budget_share_factor_in_config_layer`.

#### 10.31.15 Lexicon canary shadow-comparison gate (entity-resolution diff)

- [ ] **Canary shadow-comparison protocol.** Promoting a new
  `lexicon.tr.yaml` (or any §10.30.15 high-leverage closed
  table) goes through a NEW pre-promotion stage:
  1. Promote candidate to *shadow* lexicon (in-pod L0 cache
     keyed separately, NOT served).
  2. Run `nlp_lexicon_canary_min_requests=500` real
     production requests through BOTH the current and the
     shadow lexicon; compare on the structured fields
     `(intent_id, top_3_entities, intent_modifier,
     pragmatic_class, comparative_degree, semantic_frame)`.
  3. Compute disagreement rate per field.
  4. **Promote** iff `total_field_disagreement_rate <
     nlp_lexicon_canary_max_disagreement_pct=2.0` AND
     no individual field disagreement >
     `nlp_lexicon_canary_max_per_field_disagreement_pct=5.0`.
  5. **Reject** otherwise; emit detailed
     `nlp.alert.v1{kind=lexicon_canary_disagreement_above_threshold,
     field, rate, severity=critical}` and roll back.
- [ ] **Shadow-comparison time budget.** Comparison runs in the
  background (does NOT block production); per-request
  shadow-evaluation cost is amortised at the §10.31.12
  budget-share (the shadow gets `nlp_lexicon_canary_share_factor=0.10`
  of the per-request budget; it produces results
  best-effort and rows that exhaust their share are
  excluded from the comparison sample with explicit
  `skipped_due_to_budget` accounting).
- [ ] **Comparison-corpus sampling discipline.** Sampled
  requests MUST come from approved-tier production traffic
  (no degraded, no quarantined, no shadow-training pipeline
  outputs — same exclusion rules as §10.27.x training-data
  governance); sampling is uniform-random over a 1-hour
  rolling window, capped at
  `nlp_lexicon_canary_max_sample_rate_pct=5.0` of total
  traffic to bound the shadow-evaluation cost.
- [ ] **Forensic trace.** Every disagreement row recorded as
  `nlp.event.v1{kind=lexicon_canary_disagreement,
  request_id_sha, field, current_value, shadow_value,
  surface_token_excerpt}` (NEVER the raw input text — only
  the structured surface-token excerpt around the disagreeing
  entity, per §10.14 PII-clean observability) for
  PR-time review by the lexicon-curator.
- [ ] **Composition with §10.25.6 governance.** Canary
  shadow-comparison is a NEW required step in the
  high-leverage-table promotion workflow; the §10.25.6
  two-reviewer rule still applies, but reviewers also see
  the canary report and may block on disagreement-rate
  insights even if syntactic gates pass.
- [ ] **Proof:** `test_lexicon_canary_runs_in_shadow_only`,
  `test_lexicon_canary_compares_structured_fields`,
  `test_lexicon_canary_promotes_below_disagreement_threshold`,
  `test_lexicon_canary_rejects_above_per_field_threshold`,
  `test_lexicon_canary_excludes_degraded_and_quarantined`,
  `test_lexicon_canary_event_excludes_raw_input_text`,
  `test_lexicon_canary_share_factor_caps_shadow_cost`,
  `test_lexicon_canary_required_in_high_leverage_promotion_workflow`.

#### 10.31.16 Cross-phase impact, configuration knobs, and event/alert kind inventory

- [ ] **Cross-phase impact.**
  - Phase 9 gateway: consumes `intent_slo_classes.yaml`
    (§10.31.12), `possessive_chain_grammar.tr.yaml`
    (§10.31.4) cross-language; verifies
    `qa.answer.v1.outbound_checksum` (§10.31.11); honors
    `qa.intent.v1 schema_version=5` additive fields
    (`pragmatic_class`, `semantic_frame`, `comparative_degree`,
    `refusal_reason_code`).
  - Phase 7 sec: §10.31.1 sarcasm-detector pre-empts no §7
    gate (sarcasm is not abuse); §10.31.11
    `outbound_secret_master` rotates on the §7 sec-rotation
    channel.
  - Phase 8 ops: new alert kinds register in the alert-routing
    table (`outbound_checksum_mismatch` / `lexicon_canary_disagreement_above_threshold`
    / `tr_output_grammar_validator_killswitch_engaged` →
    critical → pager; `tr_output_grammar_fallback_used` /
    `refusal_reason_rate_spike` → warn → dashboard;
    `lexicon_catalog_alias_conflict` / `sarcasm_cue_rate_drift`
    / `negation_scope_distribution_drift` → info → log-only).
  - Phase 13 LeagueCatalog: §10.31.10 conflict-resolution
    invariant binds NLP and Phase 13; PR-time `make
    verify.lexicon-catalog-consistency` is a NEW Phase 13 gate.
  - Phase 6 proofreader: §10.31.8 output-grammar validator
    becomes part of the proofreader stage chain; new closed
    fallback templates added to allowlist; §10.31.9 refusal
    pool added to allowlist (all variants must pass the
    proofreader's existing closed-template invariant).
  - Phase 5 predictor: no schema impact (additive `qa.intent.v1`
    fields are NLP-internal; predictor input is unchanged).
  - Phase 12 chaos: new chaos scenarios —
    `chaos.outbound-checksum-mutation-injection` (validates
    §10.31.11 gate fires), `chaos.tr-output-grammar-violation-injection`
    (validates §10.31.8 fallback path),
    `chaos.lexicon-canary-disagreement-injection` (validates
    §10.31.15 reject path), `chaos.healthz-realism-template-sha-drift`
    (validates §10.31.13 503 path).
- [ ] **Configuration knobs (~25 new keys, §10.19 triangle update).**
  | Key | Default | Purpose |
  |---|---|---|
  | `nlp_sarcasm_context_window_tokens` | `10` | Cue-vs-context co-occurrence window. |
  | `nlp_sarcasm_cue_min_precision` | `0.85` | Eval-set precision floor for boot-time auto-disable. |
  | `nlp_pro_drop_lookback_turns` | `3` | Implicit-subject anaphora window. |
  | `nlp_pro_drop_min_implicit_subject_confidence` | `0.65` | Floor below which disambiguation fires. |
  | `nlp_pro_drop_default_team_confidence_cap` | `0.55` | Cap on user-favorite-team default. |
  | `nlp_possessive_chain_max_depth` | `4` | DoS guard on possessive parser. |
  | `nlp_output_grammar_validator_p99_ms` | `15` | Validation latency budget. |
  | `nlp_output_grammar_validator_killswitch_enabled` | `false` | Emergency bypass (off by default). |
  | `nlp_outbound_secret_master` | env-only | Cross-pod outbound-checksum master secret. |
  | `nlp_gateway_timeout_safety_factor` | `1.5` | Multiplier on per-class SLO budget for gateway timeout. |
  | `nlp_healthz_realism_probe_max_ms` | `200` | Probe latency budget. |
  | `nlp_healthz_realism_probe_min_interval_s` | `15` | Probe rate-limit. |
  | `nlp_healthz_realism_event_ratelimit_s` | `60` | Failure-event rate-limit. |
  | `nlp_subquery_budget_share_factor` | `0.4` | Budget share per subquery in multi-split. |
  | `nlp_max_subqueries_per_request` | `3` | Hard cap (re-asserts §10.24.5). |
  | `nlp_lexicon_canary_min_requests` | `500` | Sample size for shadow comparison. |
  | `nlp_lexicon_canary_max_disagreement_pct` | `2.0` | Promotion gate (total). |
  | `nlp_lexicon_canary_max_per_field_disagreement_pct` | `5.0` | Promotion gate (per-field). |
  | `nlp_lexicon_canary_share_factor` | `0.10` | Per-request budget share for shadow eval. |
  | `nlp_lexicon_canary_max_sample_rate_pct` | `5.0` | Cap on traffic sampled. |
  | `nlp_lexicon_catalog_alias_event_ratelimit_s` | `300` | Per-(surface, pod) tuple rate-limit. |
  | `nlp_refusal_pool_min_size` | `3` | Minimum equivalent variants per refusal_reason_code. |
  | `nlp_meta_unspecified_max_eval_pct` | `1.0` | CI gate on catch-all reason rate. |
  | `nlp_negation_scope_drift_alert_pp` | `15.0` | Weekly bin-drift trigger. |
  | `nlp_score_notation_disambiguation_enabled` | `true` | Master toggle (off = current alphabetical-first behaviour, NOT recommended). |
- [ ] **Event/alert kind inventory (additive-only, CODEOWNERS-protected
  closed enums per §10.27.6 / §10.28.13 / §10.30.15).**
  - `nlp.event.v1` new kinds: `sarcasm_cue_no_context`,
    `pro_drop_resolved`, `tr_output_grammar_violation`,
    `lexicon_catalog_alias_resolved`,
    `healthz_realism_probe_failed`,
    `lexicon_canary_disagreement`.
  - `nlp.alert.v1` new kinds: `sarcasm_cue_rate_drift` (info),
    `tr_output_grammar_fallback_used` (warn),
    `tr_output_grammar_validator_killswitch_engaged` (critical),
    `negation_scope_distribution_drift` (info),
    `refusal_reason_rate_spike` (warn),
    `lexicon_catalog_alias_conflict` (warn),
    `outbound_checksum_mismatch` (critical),
    `lexicon_canary_disagreement_above_threshold` (critical).
- [ ] **CODEOWNERS additions.** New files in the §10.30.15 group:
  `ai/nlp/lang_tr/sarcasm_markers.tr.yaml`,
  `ai/nlp/lang_tr/question_tag_classifier.tr.yaml`,
  `ai/nlp/lang_tr/pro_drop_intent_classes.tr.yaml`,
  `ai/nlp/lang_tr/possessive_chain_grammar.tr.yaml`,
  `ai/nlp/lang_tr/comparative_degree.tr.yaml`,
  `ai/nlp/lang_tr/score_notation_conventions.yaml`,
  `ai/nlp/lang_tr/negation_scope_disambiguators.tr.yaml`,
  `ai/nlp/lang_tr/refusal_template_pool.tr.yaml`,
  `ai/nlp/lang_tr/intent_slo_classes.yaml`. All require
  `nlp-curator`; `sarcasm_markers.tr.yaml` +
  `comparative_degree.tr.yaml` +
  `negation_scope_disambiguators.tr.yaml` additionally require
  `nlp-domain-football`; `refusal_template_pool.tr.yaml`
  additionally requires `nlp-compliance`;
  `intent_slo_classes.yaml` + `possessive_chain_grammar.tr.yaml`
  additionally require Go owner (cross-language single-source).
  `make verify.nlp-codeowners` extended; CI-gated.
- [ ] **Versioning.** `swarm` minor (additive
  `qa.intent.v1`/`qa.answer.v1` schema bump to v5; new
  closed tables; new modifier values; new event/alert kinds)
  + `docs` minor in same commit. Chart compatibility block
  re-pinned (no new third-party deps; uses existing
  Zemberek + Symspell + python-crfsuite + Jinja2 stack).
- [ ] **Tracker row + ROADMAP checkbox flips** per AGENTS.md §3 + §3.4
  — every checkbox in §10.31.1–§10.31.16 flipped to `[x]` at landing,
  with §10.20 DoD item 29 also flipped.
