# Phase 10 §10.32 — Discourse-pragmatic, dialectal, operational-resilience floor

> **Provenance.** Carved out of `docs/planning/ROADMAP.md` Phase 10 on the Phase 10 split (post-13th-pass) so the ROADMAP stays navigable. Content here is the **binding** Phase 10 contract; ROADMAP §10 now points at this folder. Any edit must update `xops/versioning/chart.json` (`docs` minor) and the tracker (per AGENTS.md §3 + §6.1). Cross-phase references (Phase 5/7/8/9/11/12/13a/14/16/19/20) remain authoritative against ROADMAP and the matching `docs/design/*.md` anchors.


### 10.32 Discourse-pragmatic, dialectal, and operational-resilience floor (binding addendum)

> Mirrors the §10.21–§10.31 pattern: §10.0–§10.31 are the surface +
> integrity + correctness + serving + completeness + lifecycle +
> morph + lifecycle + authentic-TR + deep-morph + conversational +
> pragmatics contract; §10.32 is the **thirteenth-pass residue**. It
> closes (a) discourse-pragmatic & dialectal pathologies the prior
> twelve passes left producing *confidently wrong* answers on real
> messy Turkish, and (b) operational-resilience gaps that surface
> only when the long pipeline runs in production at scale (cross-pod
> drift, partial-bus survival, breaking-schema migration, synthetic
> proof-of-life beyond healthz, eval-corpus curation lifecycle).
> Every `[ ]` here is binding for Phase 10 DoD (per §10.20 item 30).

#### 10.32.1 Reported-speech / quotative-chain firewall (CRITICAL — confidently-wrong class)

- [x] **Real failure pattern.** *"Hocan diyor ki yarın 3-0 bitecekmiş"*,
  *"X gazetesine göre Y kazanacak"*, *"Twitter'da yazıyorlar Galatasaray
  şampiyon"*  — the surface form contains a `predict.match_outcome`-
  shaped clause **embedded inside a hearsay frame**. The prior twelve
  passes route these to `predict.*` because the clause-internal verb
  (`bitecekmiş`/`kazanacak`) parses as predict-future. The user is
  asking *"who said this?"* / *"is this rumor true?"* — a `data.*`
  question — **not** asking the system for its own forecast.
- [x] **Closed `quotative_frames.tr.yaml`** — frame markers in 4
  classes:
  - `direct_quote_marker` (`diyor ki`, `dedi ki`, `şöyle yazıyor`,
    `der ki`)
  - `attributed_source` (`X'e göre`, `X'in dediğine göre`, `X'in
    açıklamasına göre`, `X kaynaklarına göre`)
  - `evidential_hearsay_compound` (`-mIş` + `bilinen`/`söylenen`/
    `iddia edilen`; distinct from §10.26.5 bare `-mIş` evidential —
    these are quotative-chained)
  - `social_media_attribution` (`Twitter'da`, `sosyal medyada`,
    `forumda`, `internette`)
- [x] **Detection ordering** — runs AFTER §10.31.1 sarcasm strip
  AFTER §10.30.5 politeness strip AFTER §10.30.3 idiom expand
  BEFORE §10.31.7 negation-scope BEFORE classifier. Ordering
  pinned in §10.1 step list as **step 7d**; AST guard
  `test_nlp_quotative_runs_in_pinned_order`.
- [x] **Cross-language SHA pin** — `quotative_frames.tr.yaml` SHA in
  Phase 9 gateway compatibility quartet; refuse-boot on drift
  (mirrors §10.31.10 lexicon-catalog discipline).
- [x] **Proof tests** — 35-row golden corpus (10 per frame class
  confidence ≥ `nlp_quotative_min_confidence=0.70`:
  - `direct_quote_marker` + `attributed_source` → route to NEW
    `data.attributed_claim` intent (additive; `qa.intent.v1`
    schema v5→v6); answer template lists known claims about the
    fixture from `data.request.v1{kind=attributed_claim_lookup}`,
    NEVER offers system's own prediction.
  - `social_media_attribution` → route to closed
    `meta.social_media_unverifiable` template ("Sosyal medyadaki
    iddiaları doğrulayamam") humanizer-bypassed; tier-blind.
  - `evidential_hearsay_compound` → already routed via §10.26.5
    inferential_past path; this section adds the test-coverage
    gate (was tested in isolation, never composed with quotative).
- [x] **Negative-quotative tolerance** — *"hiç kimse demedi ki Y
  kazanır"* → route to `data.attributed_claim` with negation flag,
  NOT to predict; closed `quotative_negation.tr.yaml` 12-row.
- [x] **Cross-language SHA pin** — `quotative_frames.tr.yaml` SHA in
  Phase 9 gateway compatibility quartet; refuse-boot on drift
  (mirrors §10.31.10 lexicon-catalog discipline).
- [x] **Audit event** `kind=quotative_frame_detected` with closed-enum
  `frame_class` field; PII-clean (no quoted text, only frame
  signal).
- [x] **Proof tests** — 35-row golden corpus (10 per frame class
  minus negative-quotative which gets 5) requires 100% routing
  to `data.*` / `meta.*`, **0 leak to `predict.*`**; AST guard
  `test_nlp_quotative_never_routes_predict`; Hypothesis property
  test (≥ 200 examples) — every quotative frame composed with any
  `predict.*`-shaped inner clause routes to `data.attributed_claim`.

#### 10.32.2 Aspectual-stack & serial-verb modality composition

- [x] **Real failure pattern.** *"yenmiş olacak"*, *"kazanmış olur"*,
  *"oynayacak olan"*, *"başlamak üzereler"*, *"bitiyor olabilir"* —
  Turkish stacks aspect markers into compound forms that combine
  modalities §10.26.5 handles individually but **not in stack**.
  The §10.26.5 modality firewall checks one suffix-tail at a time;
  the §10.31.5 comparative table doesn't apply; today these route
  by their *outermost* aspect, which is wrong (e.g. `yenmiş olacak`
  routed as future predict because `olacak` wins, but the inner
  `-mIş` makes the entire clause a *future-perfect-evidential*
  meaning "will turn out to have beaten" — a counterfactual probe,
  not a prediction).
- [x] **Closed `aspectual_stacks.tr.yaml`** — 6-row type-grammar
  matrix `(inner_aspect, outer_aspect) → composed_modality` with
  the 18 valid Turkish stacks: future-perfect-evidential,
  perfect-modal-potential, future-relative-clause-attributive,
  imminent-progressive, progressive-epistemic, progressive-
  inferential. AST guard rejects inline detection — must be table-
  driven (mirrors §10.31.4 grammar discipline).
- [x] **Right-recursive parse** with depth cap `nlp_aspectual_stack_max_depth=3`
  (DoS guard); ambiguous parse → §10.31.9 disambiguation refusal
  with `refusal_reason_code=aspectual_stack_ambiguous` (added to
  the §10.31.9 enum, schema v5→v6 additive).
- [x] **Routing matrix** binding:
  - future-perfect-evidential → `meta.counterfactual_probe`
    (NEW; closed Turkish refusal "Olması durumunda nasıl olurdu
    sorusuna cevap veremem") humanizer-bypassed.
  - perfect-modal-potential → `meta.modality_unsupported` (existing).
  - imminent-progressive (`başlamak üzere`, `kazanmak üzere`) →
    routes to `data.live_state` (per §10.27.1 fixture-state) NOT
    predict (the match is about-to-start or in-progress, not a
    pre-match query).
  - progressive-epistemic (`oynuyor olabilir`) → routes to
    `data.fixture_lookup` with `state=in_play` filter; NEVER predict.
  - future-relative-clause-attributive (`oynayacak olan kim`) →
    routes to `data.lineup_probable` (per §10.30.1 v4 enum); NEVER
    predict.
- [x] **Composition with §10.30.4 conditional & §10.31.5 comparative**
  — when an aspectual stack composes with a conditional or
  comparative modifier (e.g. *"eğer yenmiş olacaksa"* — conditional-
  future-perfect), the composed routing is the **most restrictive**
  of the three (any single class refusing → entire query refuses);
  AST guard `test_nlp_modality_composition_uses_most_restrictive`.
- [x] **Proof tests** — 50-row golden corpus across the 18 valid
  stacks (~3 each + adversarial); 100% correct routing; 0 leak
  to `predict.*`; Hypothesis property: every (inner, outer) pair
  in the table produces a deterministic routing decision.

#### 10.32.3 Postposition stack disambiguation

- [x] **Real failure pattern.** Turkish postpositions stack with
  subtle meaning shift: *"Galatasaray'a karşı"* (vs.) ≠
  *"Galatasaray ile karşı karşıya"* (face-to-face); *"maç için
  karşı"* (against-the-match — adversarial sense vs. preparation
  sense); *"3 gol kadar gibi"* (approximate-comparative ≈ "about
  3 goals"). Today these are normalized away by §10.22.4
  particle stripper which **collapses postpositions before
  parsing** — losing the distinction.
- [x] **Closed `postposition_stacks.tr.yaml`** — 4-class table:
  - `vs_marker` (`-A karşı`, `-A karşı karşıya`, `-A göre`)
  - `comparison_marker` (`-A göre`, `kadar`, `gibi`, `nazaran`)
  - `instrumental_marker` (`ile`, `-yle`, `-la`, `beraber`,
    `birlikte`)
  - `causal_marker` (`için`, `-DEn dolayı`, `nedeniyle`,
    `yüzünden`)
- [x] **Stack-aware parser** — recognises 12 valid 2-postposition
  stacks (e.g. `karşı karşıya`, `kadar gibi`, `için karşı`) with
  closed disambiguation rules; un-listed 2-stack → preserve
  surface form + emit `nlp.event.v1{kind=postposition_stack_unknown}`
  + fall through to existing §10.22.4 single-postposition path.
- [x] **Entity role projection** — when `vs_marker` detected, the
  governed entity is marked `entity_role=opponent` in
  `qa.intent.v1.entities[].syntactic_role` (additive, joins
  §10.29.6 `entity_subject`/`entity_object`/`ambiguous` →
  4-valued). When `instrumental_marker`, role is
  `entity_companion` (used for *"X ile beraber"* attendance
  queries vs. *"X'e karşı"* fixture queries).
- [x] **Dispatch hook** — `qa.intent.v1{intent=data.fixture_lookup,
  entities=[{kind=team, role=opponent}]}` resolves via NEW
  `data.request.v1{kind=fixture_vs_team_lookup}` (additive
  kind; v4→v5 additive — coordinated with §10.27.1 schema
  evolution).
- [x] **Proof tests** — 40-row golden corpus across 4 classes +
  12 valid stacks; 100% correct role projection; 0 confusion
  between `karşı`-as-vs and `karşı`-as-physical-direction
  (closed `karsi_disambig.tr.yaml` 8-row trigger window ±3
  tokens around `karşı` for the latter sense).

#### 10.32.4 Regional & diaspora-dialect normalization

- [x] **Real failure pattern.** Native speakers of regional /
  diaspora variants produce input that breaks Zemberek (which is
  trained on Standard Turkish). Examples actually observed in
  Turkish football fan corpora:
  - **Aegean** (`-yon`/`-yom` for `-yor`): *"gidiyon"*, *"ne
    yapıyom"*
  - **Black Sea / Karadeniz** (`-er` + dropped vowel, distinct
    `-um` for `-Im`): *"gelmişum"*, *"oynerum"*, *"olmuştu mi?"*
  - **Cypriot Turkish** (different `-mIş` distribution, `-DI mI`
    inverted): *"yenmiştir mi?"*, *"oynayceği"* (with
    Cypriot-specific verb-final cluster)
  - **Diaspora** (German-Turkish: *"schalterda"*, *"Kreis ligesi"*;
    Dutch-Turkish: *"voetbalcı"*; UK-Turkish: *"premier liglerde"*) —
    code-mixing inside single token via §10.32.4 vs. across-token
    via existing §10.26.10 bilingual football vocab
- [ ] **Closed `regional_dialect_normalization.tr.yaml`** — 4
  dialect families × ~30 entries each = ~120 deterministic
  `dialect_form → standard_form` rewrites (closed table; never
  fuzzy). Per-rule `dialect_class ∈ {aegean, black_sea, cypriot,
  diaspora}` for telemetry and dialectal-coverage tracking. Per-
  rule `audit_only ∈ {true, false}` — `audit_only=true` rewrites
  emit a `nlp.event.v1{kind=dialect_normalized}` event but DO
  produce the standard form silently (most rewrites); `false`
  rewrites preserve original surface in a `dialect_alternatives[]`
  field on `qa.intent.v1` and **may** trigger a
  did-you-mean-style clarification when ambiguous.
- [x] **Detection ordering** — runs as new §10.1 **step 6.3**
  AFTER §10.1 step 6 (diacritic restore) AFTER §10.28.1 consonant
  alternation tolerance BEFORE §10.29.1 geminate restoration.
  Pinned in step list; AST guard.
- [x] **Confidence floor** — dialect rewrite is applied only when
  the dialect form is **not** itself a Standard Turkish word in
  the §10.2 lexicons or LeagueCatalog (defends against rewriting
  *"Schalke"* the team name as German-Turkish diaspora variant).
  Closed `dialect_no_rewrite_canonicals.tr.yaml` allow-list for
  edge cases.
- [ ] **Per-dialect coverage telemetry** — `nlp_dialect_normalization_rate`
  histogram per `dialect_class`; threshold `nlp_dialect_class_min_recall=0.80`
  on the §10.18 evaluation harness's per-dialect slice (NEW
  ≥ 30-row slice per dialect family); below → warn alert
  `dialect_class_recall_below_floor` for lexicon-curator action.
- [ ] **Two-reviewer rule extension** — `regional_dialect_normalization.tr.yaml`
  added to §10.25.6 high-leverage governance list; CODEOWNERS
  requires `nlp-curator` + new `nlp-dialect-curator` group.
- [ ] **Proof tests** — 4 × 30-row dialect golden corpora with
  per-dialect intent accuracy ≥ 0.85 + entity F1 ≥ 0.85 (slightly
  relaxed from main §10.18 floors of 0.92 / 0.90 — dialects are
  long-tail). Adversarial `dialect_squat` test: 20-row corpus
  where a dialect form **collides with a player surname**
  (e.g. "gelmiş" the inflected verb vs. a hypothetical surname)
  — must NOT rewrite, must resolve to surname.

#### 10.32.5 Apostrophe-suffix proper-noun robustness (extends §10.31.8)

- [x] **Real failure pattern not covered by §10.31.8.** §10.31.8 is
  an *output-side* grammar-check gate; this section is *input-side*
  apostrophe robustness. Native Turkish writers commonly:
  - Drop the apostrophe entirely on proper-noun + suffix:
    *"Galatasaraya"* (should be *"Galatasaray'a"*)
  - Place apostrophe in wrong position: *"Galat'asaraya"*,
    *"Galatas'araya"* (mobile-keyboard slip)
  - Use Unicode quote characters (U+2019, U+02BC, U+02BB) instead
    of ASCII apostrophe; partly normalized by §10.26.9 paste-
    hygiene but not in *all* apostrophe positions
  - Apostrophes inside brand names themselves: *"Akhisar'spor"*
    (legitimate league spelling), *"D'Or"* (player nickname)
- [x] **Closed `apostrophe_proper_noun.tr.yaml`** — three rule
  classes:
  - `missing_apostrophe_suffix` — heuristic: token of length ≥
    7 ending in {`a`, `e`, `de`, `da`, `den`, `dan`, `ya`, `ye`,
    `nın`, `nin`, `nun`, `nün`, `lı`, `li`, `lu`, `lü`} where
    the prefix-without-suffix matches a LeagueCatalog canonical
    via §10.28.1 alternation tolerance → re-insert apostrophe;
    AST guard prevents heuristic from firing on common nouns
    (closed `apostrophe_no_insert.tr.yaml` allow-list of
    100-row common-noun negative examples)
  - `misplaced_apostrophe` — when `find_canonical_with_apostrophe_anywhere(token)`
    returns exactly one match within edit-distance ≤ 1 of the
    canonical's correct apostrophe position → repair; ambiguous
    → did-you-mean (NEVER silent pick)
  - `legitimate_internal_apostrophe` — closed allow-list of brand
    names that contain internal apostrophes; bypasses both
    repair classes
- [x] **Detection ordering** — runs as new §10.1 **step 6.7**
  AFTER §10.32.4 dialect normalize AFTER §10.29.1 geminate
  restoration BEFORE §10.5 entity extraction. AST guard.
- [ ] **Cross-language consistency with §10.31.8 output-side** —
  the *closed canonical apostrophe-insertion table* (which suffix
  triggers apostrophe per Turkish proper-noun rule, e.g. consonant
  vs. vowel-final stem) is shared single-source via NEW
  `ai/common/text/proper_noun_apostrophe_spec.json`; both §10.32.5
  input repair and §10.31.8 output-side validator import from this
  spec; cross-language SHA pin (Python NLP + Go sec layer); boot-
  refuse on drift (mirrors §10.29.11 `tr_normalize_spec.json`
  doctrine).
- [ ] **Proof tests** — 60-row golden (20 missing-apostrophe + 20
  misplaced + 20 legitimate-internal); 100% correct repair on the
  first two classes; 100% non-touch on the third class; Hypothesis
  property: every LeagueCatalog canonical with every valid Turkish
  case suffix (8 cases × 4 vowel-harmony classes = 32 forms)
  round-trips through repair byte-identically when input has the
  apostrophe in the right position (idempotent on correct input).

#### 10.32.6 Embedded focus-particle (mi/mı inside larger question)

- [ ] **Real failure pattern.** *"Galatasaray ne zaman mı oynayacak?"* —
  Turkish allows `mi/mı/mu/mü` to attach as a **focus particle**
  inside a wh-question, where it does NOT make the sentence
  yes/no but emphasises the wh-element ("**when** is Galatasaray
  playing?"). §10.31.2 question-tag classifier sees the `mı` and
  routes as confirmation_seeking; §10.30.2 wh-intent map sees
  the `ne zaman` and routes as data.kickoff_time; the dispatcher
  silently breaks the tie alphabetically — wrong half the time.
- [ ] **Closed `focus_particle_disambiguation.tr.yaml`** — when
  both a wh-word AND `mi/mı/mu/mü` appear in the same clause,
  the particle is **focus** not question; the wh-intent wins;
  the §10.31.2 confirmation/information classifier is **bypassed**
  for this token. AST guard
  `test_nlp_focus_particle_bypasses_question_tag_classifier`.
- [ ] **Composition with §10.31.7 negation-scope** — *"yenmedi mi
  kim?"* (rhetorical negative + focus particle + wh) → route
  via §10.31.7 rhetorical-correction first, then wh-intent wins.
- [ ] **Proof tests** — 25-row golden; 100% routing to wh-intent
  when both signals coexist; 0 leak to question-tag classifier.

#### 10.32.7 Numeric-with-suffix realization (apostrophe-bound)

- [ ] **Real failure pattern.** *"3'ü kazanmıştı"*, *"2008'de"*,
  *"1-1'lik beraberlik"*, *"5-0'lık galibiyet"*, *"100.'sü"* —
  Turkish numbers take case suffixes via apostrophe (`3'ü`,
  `2008'de`) and ordinals/derivative-forms also via apostrophe
  (`1-1'lik`, `5-0'lık`, `100.'sü`). §10.26.4 numeric/temporal
  resolver handles standalone numbers; §10.32.5 handles proper-
  noun apostrophes; **neither covers numeric-with-apostrophe-
  suffix**. Today these are rejected by Symspell (no lexicon
  match) and fall through with the suffix attached, breaking
  downstream score / time / line resolution.
- [ ] **Closed parser** at `ai/nlp/numbers/apostrophe_suffixed.py` —
  pure-stdlib regex over the closed shape
  `^(?P<num>\d+|\d+[-–]\d+|\d+\.)'(?P<suffix>[a-zçğıöşü]+)$`
  (with §10.26.9 dash canonicalisation already applied).
  Suffix interpreted via existing `vowel_drop_before_suffix`
  (§10.29.2) and case-suffix table; produces
  `NumericEntity{value, kind ∈ {cardinal, score_pair, ordinal},
  case ∈ {nominative, accusative, dative, locative, ablative,
  genitive, ablative_distributive, derivative_lik}}`.
- [ ] **Score-pair handling** — `1-1'lik` parsed as
  `NumericEntity{value=(1,1), kind=score_pair, case=derivative_lik}`;
  consumed by §10.24.11 decimal-vs-score parser as **definitive
  score** (no ambiguity — the `'lik` derivative makes it
  unambiguously a result-noun); routes to `data.h2h` not
  `data.over_under`.
- [ ] **Cross-language byte-parity** — Go sec layer adds parallel
  parser (single-source `numeric_apostrophe_spec.json`); SHA pin
  + refuse-boot on drift (mirrors §10.29.11 doctrine).
- [ ] **Proof tests** — 45-row golden (15 cardinal-with-case + 15
  score-pair-derivative + 15 ordinal-derivative); 100% correct
  parse; 0 silent fall-through; Hypothesis property: all
  combinations of (number-shape, vowel-harmony-class, case)
  produce deterministic parse.

#### 10.32.8 Slang-suffixation tolerance

- [ ] **Real failure pattern.** Turkish freely derives nouns and
  adjectives from any stem via productive suffixes: *"GSlilik"*
  (Galatasaray-supporter-quality), *"Beşiktaşlılarımız"*
  (our-Beşiktaş-supporters), *"transferlik"* (transfer-worthy),
  *"şampiyonluğa giderlik"* (championship-going-quality),
  *"derbilik"* (derby-quality). The §10.30.3 idiom phrasebook
  doesn't cover these; the §10.5 gazetteer doesn't recognise
  the inflected forms; Zemberek often parses but loses the
  underlying canonical reference.
- [ ] **Productive-suffix peeler** at `ai/nlp/morph/productive_suffixes.py` —
  closed `productive_suffixes.tr.yaml` with 8-row family of
  productive derivational suffixes (`-lI`, `-lIk`, `-cI`, `-CIk`,
  `-mIş`, `-yorlu`, `-lIlIk`, `-lIlAr`); peel iteratively up to
  `nlp_productive_peel_max_depth=3` (DoS guard) checking after
  each peel whether the residue resolves to a LeagueCatalog
  canonical. First-resolving residue wins; preserves audit trail
  in `entities[].morph={original_token, peeled_suffixes[]}`.
- [ ] **Composition with §10.32.5 apostrophe repair** — *"GS'lilik"*
  (apostrophe-correct) and *"GSlilik"* (apostrophe-dropped) both
  resolve to same canonical via the §10.32.5 missing-apostrophe
  rule firing **before** the productive-peel; AST ordering guard.
- [ ] **Negative test discipline** — peel must NOT fire on closed
  allow-list of common nouns ending in productive suffixes (e.g.
  *"birlik"* the noun, not *"bir+lik"*); closed
  `productive_peel_no_fire.tr.yaml` 50-row negative corpus.
- [ ] **Proof tests** — 40-row positive + 50-row negative; 100%
  resolution on positives; 0 false-fire on negatives.

#### 10.32.9 Self-meta / conversational-meta routing

- [ ] **Real failure pattern.** *"ne demek istedin?"*, *"şaka mı?"*,
  *"kafa mı buluyorsun?"*, *"sen kimsin?"*, *"benim hakkımda ne
  biliyorsun?"*, *"daha önce ne sormuştum?"* — meta-conversational
  queries about the system's own behavior or prior conversation
  state. §10.28.10 covers system_self / rhetorical_dismissive /
  opinion_request but **not** the per-conversation introspection
  class.
- [ ] **Closed `conversational_meta.tr.yaml`** in 4 sub-classes:
  - `system_clarification_request` (`ne demek istedin?`, `bunu
    açıklayabilir misin?`) → routes to `meta.last_answer_explain`
    (NEW; v5→v6 additive); template re-renders the prior
    `qa.answer.v1` with explicit step-by-step (template_id
    suffix `.explained`); humanizer-bypassed; tier-blind.
  - `prior_query_recall` (`daha önce ne sormuştum?`, `önceki
    sorum neydi?`) → routes to NEW `meta.conversation_history`;
    template lists prior `qa.intent.v1` summaries from the
    §10.25.1 conversation context (bounded to last 8 turns,
    PII-clean per §10.27.12 entity-graph snapshot discipline).
  - `system_capability_query` (`sen kimsin?`, `neler yapabilirsin?`,
    `hangi ligleri biliyorsun?`) → routes to closed
    `meta.system_capabilities` (NEW; deterministic answer from
    `cfg.nlp_system_capability_template_path`; refreshed at
    deploy not at runtime).
  - `personal_info_about_user` (`benim hakkımda ne biliyorsun?`,
    `kimim ben?`) → routes to closed
    `meta.user_data_disclosure` (NEW); closed Turkish answer
    references KVKK-Art-11 disclosure mechanism (per §10.27.8
    regulatory disclosures); NEVER discloses any actual user
    data (boundary doctrine — NLP layer never reads user-PII
    columns).
- [ ] **Routing precedence** — these intents short-circuit AFTER
  §10.31.1 sarcasm AFTER §10.30.5 politeness BEFORE the main
  classifier (mirrors §10.28.10 meta-routing position). AST
  ordering guard.
- [ ] **Per-intent SLO** — all four meta intents map to
  `slo_fast` per §10.31.12 (250ms p99); they are deterministic
  template lookups + (for `prior_query_recall`) a single
  conversation-context read.
- [ ] **Proof tests** — 4 × 15-row golden = 60-row; 100% routing
  to corresponding meta intent; 0 leak to predict.* / data.*;
  AST guard `test_nlp_user_data_disclosure_template_never_reads_user_columns`.

#### 10.32.10 Inline self-correction & stutter handling

- [ ] **Real failure pattern.** *"Galat- Galatasaray bugün
  oynuyor mu?"*, *"yok yok Fenerbahçe demiştim"*, *"Beşik-
  Beşiktaş'ı sormuştum aslında"* — voice-typed or fast-typed
  inputs frequently contain inline self-corrections that today
  the entity extractor sees as **two distinct entities** and
  the dispatcher treats as multi-fixture (per §10.29.8
  coordinator splitting), arriving at the wrong answer.
- [ ] **Closed `inline_correction_markers.tr.yaml`** in 3 classes:
  - `stutter_repeat` — same-prefix-token immediately repeated
    (≥ 3 chars overlap, edit-distance ≤ 1); closed heuristic
    via Levenshtein on adjacent tokens
  - `verbal_self_correction` — `yok`, `yok yok`, `pardon`,
    `affedersin`, `aslında`, `daha doğrusu`, `yanlış`, `şey`
    immediately preceded or followed by an entity-replacement
  - `restart_marker` — `tamam`, `başa dön`, `unut`, `bırak`
    (whole-conversation reset; routes to §10.26.7 multi-turn
    correction grammar — already covered there)
- [ ] **Detection ordering** — runs as §10.1 **step 7c.5** AFTER
  §10.29.7 reduplication collapse AFTER §10.24.5 multi-question
  split BEFORE §10.32.6 focus-particle disambiguation. AST
  ordering guard.
- [ ] **Resolution rule** — when stutter or verbal-self-correction
  detected, the **later** entity wins (right-most replacement
  semantics — matches actual Turkish self-correction usage); the
  earlier entity is dropped + audit-traced in
  `entities[].correction_dropped=true` (additive field on
  `qa.intent.v1`); NEVER emitted as a fan-out.
- [ ] **Conservatism** — when entities are of **different kinds**
  (e.g. team vs. player), self-correction does NOT apply
  (likely a legitimate two-entity query); falls through to
  normal extraction. AST guard
  `test_nlp_self_correction_only_replaces_same_kind`.
- [ ] **Proof tests** — 35-row golden (15 stutter + 15 verbal +
  5 different-kind-no-fire); 100% correct; Hypothesis property:
  identical input + repeated entity → resolves to single entity;
  different-kind entities → resolves to multi-entity.

#### 10.32.11 System-uttered-anaphora resolver (extends §10.30.7)

- [ ] **Real failure pattern.** §10.30.7 cross-turn anaphora
  resolves pronouns referring to entities the **user** mentioned
  in prior turns. But users also reference entities the **system
  itself** mentioned in its own prior answer: *"ya öbür maç?"*,
  *"daha önce dediğin Galatasaray maçı ne zaman?"*, *"bahsettiğin
  o oyuncu kim?"*. Today these resolve via §10.30.7 stack which
  contains user-mentioned entities only — system-uttered entities
  are invisible.
- [ ] **System-uttered entity capture** — the §10.7 template
  renderer, alongside producing the answer text, emits a
  parallel `qa.context_extension.v1{entities[]}` envelope to the
  conversation context (PII-clean — canonical IDs only, per
  §10.27.12 doctrine). Capture is **post-render** so it captures
  exactly what the user saw (not what the dispatcher intended).
- [ ] **Resolver extension** — the §10.30.7 `EntityMentionStack`
  gains a 6th type slot `mentioned_by ∈ {user, system}`; pronoun
  resolution prefers user-mentioned entities when both exist
  (matches Turkish discourse-pragmatic preference) but falls
  through to system-mentioned when user-mentioned is empty;
  cache key composition includes `mentioned_by` to defend against
  the §10.30.12 cache-collision class extending to mixed
  user/system anaphora.
- [ ] **Specific marker handling** — *"öbür"*, *"diğer"*, *"diğeri"*,
  *"öteki"* (the-other) trigger **complementary** resolution: if
  the system mentioned 2 fixtures and user references *"öbür"*
  → resolves to the one **not** the most-recent-user-focus.
  Closed `complementary_anaphora.tr.yaml` 8-row; AST guard
  enforces this is the only place complement semantics fires.
- [ ] **Disambiguation when system mentioned > 1 entity of same
  kind** — falls through to §10.30.7 floor-confidence
  disambiguation; NEVER silent pick.
- [ ] **Proof tests** — 30-row golden (10 system-only-mentioned +
  10 mixed user-system + 10 complementary `öbür/diğer`); 100%
  correct resolution; AST guard `test_nlp_system_uttered_anaphora_capture_is_pii_clean`.

#### 10.32.12 Cross-pod lexicon-state divergence detection (gossip)

- [ ] **Real failure pattern not covered by §10.27.9.** §10.27.9
  pins the swap timing; once two pods have completed swap, today
  there is no **steady-state** check that they agree on lexicon
  state. A subtle pod-local corruption (memory bit-flip, partial-
  write recovery, stuck old-generation pinned by an in-flight
  request) produces silent cross-pod answer divergence — same
  query to different pods returns different answers.
- [ ] **Periodic gossip-based consistency check** — every
  `nlp_lexicon_gossip_interval_s=300` (5min) each pod publishes
  to NEW `nlp.gossip.v1` topic (data-plane; consumer = telemetry
  + the gossip aggregator pod) the SHA tuple
  `(lexicon_set_sha, intent_sha, crf_sha, calibration_version,
  template_git_sha, pipeline_version)` plus its `pod_instance_id`.
  Aggregator (replicas:1, leader-leased per Phase 14) maintains a
  rolling window of the last 12 gossip rounds (1 hour). Any pod
  reporting a SHA tuple **different** from the cluster modal
  tuple for ≥ `nlp_lexicon_divergence_min_rounds=2` consecutive
  rounds → emit `nlp.alert.v1{kind=lexicon_state_divergence,
  severity=critical, divergent_pod_id, expected_tuple_sha,
  observed_tuple_sha}`.
- [ ] **Auto-quarantine of divergent pod** — when divergence
  alert fires AND `cfg.nlp_lexicon_divergence_auto_quarantine=true`
  (default true), the divergent pod's readyz turns 503 (removes
  from gateway pool). Operator runbook in
  `docs/guides/nlp_runbook.md` (NEW) documents the manual
  recovery path (typically: SIGTERM the divergent pod;
  Kubernetes restarts it; cold-start reload restores cluster
  consistency).
- [ ] **Bounded gossip cardinality** — `nlp_gossip_max_pods=50`
  (refuse-boot if cluster size exceeds — defends against
  unbounded gossip storm in a runaway-scale-up scenario);
  `nlp.gossip.v1` payload bounded to ≤ 256 bytes (closed schema
  `additionalProperties:false`).
- [ ] **Cross-phase wire-authority** — `nlp.gossip.v1` added to
  §3.5 catalog with producer set bounded to NLP plane agents
  (`nlp.intent.v1`, `nlp.dispatcher.v1`, `nlp.answer.v1`,
  `nlp.proofreader.v1`); consumer set bounded to
  `nlp.gossip_aggregator.v1` (NEW agent, replicas:1) +
  `telemetry.v1`; boundary tests enforce.
- [ ] **Proof tests** — synthetic divergence test: spin up 3 pods,
  inject lexicon corruption in 1 pod, assert alert fires within
  2 × `gossip_interval_s` and divergent pod's readyz turns 503;
  4-pod test with 2-vs-2 split (modal-tuple is unclear) → emit
  `lexicon_state_divergence_no_modal` event (warn, not auto-
  quarantine — operator must intervene).

#### 10.32.13 Synthetic continuous prober (independent of §10.31.13 healthz)

- [ ] **Real failure pattern not covered.** §10.31.13 healthz
  realism probe runs once-per-pod-per-15s on a single golden
  query. It catches cold-start corruption but **not** drift
  that develops mid-flight (e.g. a closed-table file got
  silently truncated by a runaway disk-full) or steady-state
  regressions (e.g. a recent humanizer LLM weight load
  produced a subtle decoding shift).
- [ ] **Independent prober agent** `nlp.prober.v1` (replicas:1,
  leader-leased; CPU-only AST guard) at
  `ai/swarm/agents/nlp/prober.py`. Every
  `nlp_prober_interval_s=60` publishes a `qa.request.v1` envelope
  bearing `request_metadata.synthetic_prober=true` (additive
  immutable field; v3→v4 schema bump on `qa.request.v1`) for
  each of `nlp_prober_corpus_size=50` baked golden queries
  (`prober_corpus.jsonl` — distinct file from §10.30.14
  boot-regression corpus, can overlap; CODEOWNERS = `nlp-curator`
  + `nlp-compliance` for PII-clean curation).
- [ ] **Result verification** — prober subscribes to
  `qa.answer.v1` (consumer-side, normal subscription), filters by
  `synthetic_prober=true`, byte-compares `(intent_id, top_1_entity_id,
  refusal_reason_code, post_render_template_sha,
  outbound_checksum)` against expected. Mismatch → emit
  `nlp.alert.v1{kind=prober_drift_detected, severity=warn (per
  query) | critical (≥ 5 in 30min), expected, observed,
  drift_field}`.
- [ ] **Tier-blind, audit-clean, cache-bypass discipline** —
  `synthetic_prober=true` envelopes:
  - bypass §9.7 rate limiting (separate prober token bucket
    `cfg.api_prober_bucket_rps=2` so prober can never starve
    real traffic)
  - bypass L0 / L1 cache (each prober request hits the full
    pipeline — that's the point)
  - are excluded from §10.27.10 anti-leakage training corpus
    (closed AST guard `test_nlp_intent_trainer_excludes_synthetic_prober`)
  - are excluded from §10.27.6 abuse detector (closed guard)
  - are excluded from `qa.feedback.v1` collection (per §10.25.7
    closed guard)
  - WRITE `qa.answer.v1{synthetic_prober=true}` so downstream
    audit can also exclude (one-source-of-truth)
- [ ] **Cost discipline** — prober's humanizer is **always
  disabled** regardless of `cfg.nlp_humanize` (template-only
  mode); prober cost is bounded to ≤ 50 × 60 = 3000 template-
  only renders per pod per hour, well below background noise.
- [ ] **Cross-phase** — Phase 9 gateway honors `synthetic_prober=true`
  for the cache-bypass and rate-limit-bypass; Phase 8 telemetry
  exposes `nlp_prober_success_rate` gauge per intent class.
- [ ] **Proof tests** — synthetic regression: inject a wrong
  template version on one pod, assert prober alert fires within
  2 × `prober_interval_s` for the affected golden queries.

#### 10.32.14 Production-sample → eval-corpus curation lifecycle

- [ ] **Real failure pattern not covered.** §10.30.14 has a static
  boot regression corpus (200 PII-scrubbed rows) and §10.18 has
  a static evaluation harness (≥ 250 rows). Neither has a
  **lifecycle for adding to it from real production traffic**.
  Real-world Turkish football query distribution drifts seasonally
  (player transfers, league restructuring, new derbies) and the
  static corpus loses representativeness within months.
- [ ] **Quarterly curation pipeline** at `xops/nlp/eval_corpus_curator.py`:
  1. Sample ≥ 5000 rows from `nlp.shadow.v1` (per §10.27.10)
     stratified by (intent_class, dialect_class, has_dialect,
     has_anaphora, has_negation) with proportional allocation
     to under-represented buckets.
  2. Apply PII-scrub via §10.28.4 `tr_pii.py` AND independent
     redaction-verification (separate verifier process refuses to
     proceed if any PII pattern slips through — defense-in-depth).
  3. Run §10.18 evaluation harness over the candidate set;
     keep only rows where current-pipeline prediction differs
     from a quorum of (current-pipeline, prior-pipeline-version,
     human-curator-baseline) — surfaces **drift** examples
     (the high-value adds).
  4. Two-reviewer sign-off (`nlp-curator` + `nlp-domain-football`
     CODEOWNERS) on every batch < 100 rows; batch ≥ 100 requires
     additional `nlp-compliance` review.
  5. Diff-cap discipline (mirrors §10.26.6 lexicon supply-chain):
     `nlp_eval_corpus_pr_max_added_rows_per_quarter=500`;
     over-cap → CI fail.
- [ ] **Versioned corpus file** at `data/nlp/eval_corpus/<year>q<n>.jsonl`
  with `_meta.{schema_version, generated_at_utc, source_window_start,
  source_window_end, reviewer_signoffs[], curator_pipeline_version}`;
  immutable once promoted (corrections via additive next-quarter
  delta).
- [ ] **Eval-set evolution rate gauge** — `nlp_eval_corpus_growth_rate`
  histogram per intent class; if any intent class stays
  unchanged for ≥ 4 quarters → warn alert
  `eval_corpus_intent_class_stale` (the curator missed coverage).
- [ ] **Proof tests** — curator deterministic on fixed shadow sample
  + random seed; PII-scrub round-trip (curator output passes
  independent PII detector); diff-cap enforcement; reviewer-
  signoff structure validation.

#### 10.32.15 Per-stage operator flame-chart capture (one-shot, PII-clean)

- [ ] **Real failure pattern.** When a single request is anomalously
  slow (per §10.31.12 SLO breach) but the per-pod cumulative
  metrics look normal, operator has **no per-stage breakdown**
  for that specific request — the §10.14 sampled audit captures
  the answer, not the timing flame.
- [ ] **One-shot operator-triggered flame capture** — `make ops.nlp-flame-capture
  REQUEST_ID=<uuidv7>` (mirrors §10.27.3 forensic complaint trace
  pattern). On next occurrence of that `request_id` (or
  `qa_correlation_id`), the NLP pipeline records per-stage
  `(stage_name, monotonic_ns_in, monotonic_ns_out, allocated_bytes,
  ruleset_version)` for every step in §10.1 / §10.4 / §10.5 /
  §10.6 / §10.7 / §10.8 / §10.9 / §10.31.8 / §10.31.13. Output
  written to `data/nlp/flame_captures/<request_id>.flame.json`
  (PII-clean — no input text, only stage-level structural metadata
  + redacted intent/entity tuple).
- [ ] **Capture is sticky-armed via Redis** — `nlp:flame:<request_id>`
  TTL `cfg.opsctl_flame_capture_ttl_h=24`; first matching request
  triggers capture and clears the flag; cluster-wide via
  `maint.event.v1{kind=nlp_flame_armed}` + `nlp_flame_captured`;
  one-shot integrity (capture once, then clear — defends against
  flooding).
- [ ] **Cost & boundary discipline** — capture overhead bounded
  to ≤ 5% of pipeline latency (per-stage `time.monotonic_ns()`
  + `tracemalloc` snapshot; closed-form, not flame-graph
  sampling); when not armed, code path is a single
  `if redis_get('nlp:flame:'+req_id):` early-out (≤ 10ns).
  Operator can arm at most `cfg.opsctl_flame_capture_max_armed_per_h=10`
  request_ids per hour cluster-wide (defends against capture-
  storm DoS).
- [ ] **Forward-phase contract Phase 9** — gateway passes
  `request_id` immutably; Phase 8 telemetry exposes
  `nlp_flame_capture_armed_count` gauge for operator visibility.
- [ ] **Proof tests** — round-trip: arm flame, send request,
  assert capture file exists, asserts every pipeline stage
  appears in capture, asserts no PII (raw input substring scan
  on capture file = 0 matches), asserts overhead ≤ 5% (timed
  comparison vs. uncaptured request, threshold validated over
  100-trial mean).

#### 10.32.16 Partial-bus graceful degradation matrix

- [ ] **Real failure pattern not covered.** §10.10 graceful
  degradation matrix covers full-component failures (lexicon /
  classifier / predict / humanizer / proofreader / bus). It does
  **not** cover the *partial-bus* case where some topics are
  reachable but others are not (e.g. `predict.approved.v1` stream
  readable, but `data.request.v1` stream timing out — common
  during Redis hot-spot or per-stream Lua-script bug). Today
  NLP just times-out per request with no holistic per-topic
  awareness.
- [ ] **Per-topic reachability gauge** at the SDK level
  (`swarm.sdk.bus_health.v1`) — every pod tracks per-subscribed-
  topic `(last_successful_read_at, last_successful_publish_at,
  consecutive_error_count)`; per-topic health = `green`
  (last_success ≤ 30s) | `yellow` (≤ 5min) | `red` (> 5min OR
  consecutive errors ≥ 5).
- [ ] **Per-intent-class topic-dependency map** at
  `ai/nlp/runtime/topic_dependency.yaml` (closed; cross-language
  with Phase 9 gateway):
  - `predict.*` intents need `predict.request.v1` (publish) +
    `predict.approved.v1` (consume)
  - `data.fixture_lookup` / `data.kickoff_time` / `data.h2h` /
    `data.attributed_claim` (per §10.32.1) need `data.request.v1`
    (publish) + `data.response.v1` (consume)
  - `data.live_state` (per §10.27.1) needs `data.request.v1`
    with `kind=live_state` filter (separate logical stream;
    treated as distinct topic for health tracking)
  - `meta.*` intents need no bus topics (template-only)
- [ ] **Pre-dispatch topic-health check** — dispatcher consults
  per-topic health BEFORE publishing; if a needed topic is `red`,
  short-circuit to NEW `meta.partial_bus_unavailable` template
  (closed Turkish: "Bu sorgu için gerekli olan veri kanalı şu an
  ulaşılamıyor; kısa süre sonra tekrar deneyebilir misiniz?")
  with `degraded=true, degraded_reason=partial_bus_<topic_name>`
  carried through to `qa.answer.v1`. NEVER block on a red topic.
- [ ] **Yellow-state SWR** — when topic is `yellow`, dispatcher
  publishes BUT in parallel queries L0/L1 cache; if cache hit,
  returns cached + emits `nlp.event.v1{kind=partial_bus_swr_served_cache}`;
  if neither cache nor bus respond within the §10.31.12 SLO
  budget, fall through to graceful refusal.
- [ ] **`meta.*` intents always pass** — even when ALL bus topics
  are red, meta intents (help, capabilities, system_clarification,
  etc.) continue to serve from template-only. This is the user's
  only feedback channel during plane-wide outage; AST guard
  `test_nlp_meta_intents_have_zero_topic_dependencies`.
- [ ] **Proof tests** — synthetic per-topic outage: simulate
  `predict.request.v1` being red, assert `predict.*` queries
  refuse with closed template + correct `degraded_reason`;
  assert `data.*` queries still succeed; assert `meta.*` always
  succeeds; per-topic-health gauge correctly transitions
  green→yellow→red→green over time.

#### 10.32.17 Breaking-schema migration playbook + NLP-plane DR runbook

- [ ] **Real failure pattern not covered.** §10.27.7 covers
  schema-version downgrade for old clients consuming additive-only
  bumps. The doctrine is "additive-only" but **eventually a
  breaking change is needed** (e.g. removing a deprecated intent,
  re-keying the entity-frame format). There is no documented
  playbook for this.
- [ ] **NEW `docs/guides/nlp_breaking_schema_migration.md`** —
  binding playbook with 6 phases, each gated:
  1. **T-90d: Deprecation announce** — schema bump goal posted;
     dual-emit of old + new schema enabled via
     `cfg.nlp_qa_answer_dual_emit_enabled=true`; old schema
     marked `deprecated_at_utc=<T+90d>`; client telemetry
     captures schema-version-pin distribution.
  2. **T-60d: New-schema-default** — `nlp_qa_answer_default_schema_version`
     bumped to N+1; old clients on Accept-pin still served old
     schema; alert if > 1% traffic still pinning old.
  3. **T-30d: Sunset warning** — `Sunset: <T>` HTTP header (per
     RFC 8594) on old-schema responses; deprecated client
     domains hard-mapped to operator alerts.
  4. **T-7d: Final preview** — `make nlp.deprecation-rehearsal`
     runs all eval/prober/regression suites with old schema
     disabled in dry-run.
  5. **T+0: Cut-over** — old schema removed; clients still pinning
     get RFC 8594 `426 Upgrade Required` with Turkish error
     body; one-week grace window with `cfg.nlp_qa_answer_legacy_grace_enabled=true`
     where the cutover-old responses are served from a
     **frozen snapshot** (not the live pipeline) so no behavior-
     change diff during grace.
  6. **T+7d: Frozen-snapshot tear-down** — `cfg.nlp_qa_answer_legacy_grace_enabled=false`;
     all responses are new-schema only.
- [ ] **NEW `docs/guides/nlp_dr_runbook.md`** — DR scenarios with
  closed runbook per scenario:
  - **all-lexicon-corruption** (every pod's lexicon files
    corrupted simultaneously — rare but possible via runaway
    backup-restore): cluster-wide §10.32.16 partial-bus mode
    automatically engages (every needed topic depends on
    lexicon-resolved entities); operator runs
    `make nlp.lexicon-restore-from-snapshot SNAPSHOT_ID=...`
    which restores from §8.3 backup-agent snapshot; per-pod
    cold-start re-validates SHA tuple (per §10.32.12 gossip)
    before joining the gateway pool.
  - **intent-model-corrupt-on-all-pods**: §10.21.3 SHA verify
    refuses boot on every pod → cluster has 0 healthy NLP pods
    → gateway returns 503 across the board for any qa.request →
    operator runs `make nlp.intent-model-restore`; rollback uses
    the prior `intent.tr.bin` already SHA-pinned in the
    compatibility matrix (per §10.25.4).
  - **calibration-store-unreachable-extended** (>1h): per §10.10
    degradation matrix, per-request fall-through to template-only
    is automatic; this DR runbook adds the **operator-side
    workaround** of pinning a known-good calibration snapshot
    via `make nlp.calibration-pin SNAPSHOT_ID=...`; serves stale
    but non-degraded predictions for up to 24h pinned-snapshot
    grace period.
  - **humanizer-LLM-version-drift** (cluster-wide humanizer
    cpu_only parity test fails post-deploy): humanizer auto-
    disables (per §10.10 + §10.31.x); operator runs
    `make nlp.humanizer-rollback VERSION=<prior_sha>`; cpu_only
    parity test re-runs and gates re-enable.
- [ ] **Proof tests** — DR-runbook scripts are dry-run-safe
  (each `make nlp.*-restore` accepts `DRY_RUN=true` env var
  printing intended actions without mutation); CI gates that
  every documented runbook scenario has a dry-run-mode test in
  `xops/nlp/tests/test_dr_dry_run.py`.

#### 10.32.18 Cross-phase impact, configuration knobs, and event/alert kind inventory

- **Schema bumps** (additive-only — single migration commit):
  - `qa.intent.v1` schema v5 → v6: additive `correction_dropped`
    (bool, per §10.32.10), `entity_role` (4-valued enum extended
    with `opponent`/`companion`, per §10.32.3 — supersedes
    §10.29.6 3-valued), `dialect_alternatives[]` (per §10.32.4),
    `peeled_suffixes[]` (per §10.32.8), `pragmatic_class` extended
    with `focus_particle_disambiguated` flag (per §10.32.6),
    `quotative_frame_class` (closed enum, per §10.32.1),
    `aspectual_stack_decision` (closed enum, per §10.32.2),
    `numeric_apostrophe_entities[]` (per §10.32.7).
  - `qa.answer.v1` schema v5 → v6: additive `synthetic_prober`
    (bool, per §10.32.13), `partial_bus_topics_red[]` (per
    §10.32.16), `refusal_reason_code` enum extended with
    `aspectual_stack_ambiguous` / `quotative_unattributed_at_v1`
    / `partial_bus_<topic>` (per §10.32.2 / §10.32.1 / §10.32.16).
  - `qa.request.v1` schema v3 → v4: additive
    `request_metadata.synthetic_prober` (bool, per §10.32.13).
  - `predict.approved.v1` and `predict.request.v1`: no schema
    impact (all NLP-internal additive fields).
  - NEW topic `nlp.gossip.v1` (per §10.32.12); schema
    `additionalProperties:false`; producer set bounded to NLP
    plane; consumer = aggregator + telemetry.
  - NEW topic `qa.context_extension.v1` (per §10.32.11);
    schema additive; producer = template renderer; consumer =
    conversation context store.
  - NEW intent enum values (closed):
    `data.attributed_claim` (per §10.32.1),
    `meta.counterfactual_probe` (per §10.32.2),
    `meta.last_answer_explain` / `meta.conversation_history` /
    `meta.system_capabilities` / `meta.user_data_disclosure`
    (per §10.32.9), `meta.social_media_unverifiable` (per §10.32.1),
    `meta.partial_bus_unavailable` (per §10.32.16). All gated by
    cross-language enum-spec SHA parity with Phase 9.

- **New `nlp.event.v1` kinds** (open-enum):
  `quotative_frame_detected`, `aspectual_stack_resolved`,
  `aspectual_stack_disambiguation_offered`, `postposition_stack_unknown`,
  `dialect_normalized`, `apostrophe_proper_noun_repaired`,
  `focus_particle_disambiguated`, `numeric_apostrophe_parsed`,
  `productive_suffix_peeled`, `productive_peel_canonical_resolved`,
  `system_meta_routed`, `inline_self_correction_applied`,
  `system_uttered_anaphora_resolved`, `complementary_anaphora_resolved`,
  `nlp_flame_armed`, `nlp_flame_captured`,
  `partial_bus_swr_served_cache`, `partial_bus_topic_health_changed`,
  `lexicon_state_divergence_no_modal`,
  `prober_corpus_executed`, `eval_corpus_curated`,
  `nlp_dr_runbook_dry_run_executed`,
  `nlp_legacy_schema_grace_served`.

- **New `nlp.alert.v1` kinds** (open-enum, severity in parens):
  `quotative_misroute_to_predict_blocked` (warn) — fired when
  the §10.32.1 firewall blocked an envelope mid-flight (defense-
  in-depth post-detection); `aspectual_stack_unknown_pattern`
  (warn) — input contained a stack not in the closed table;
  `dialect_class_recall_below_floor` (warn, per-dialect-class);
  `apostrophe_repair_ambiguous_did_you_mean` (info, per-occurrence
  rate-limited); `focus_particle_classifier_disagreement` (info);
  `numeric_apostrophe_parse_silent_fall_through` (warn —
  defense-in-depth; should be 0 in production);
  `productive_peel_max_depth_hit` (info); `meta_user_data_disclosure_template_drift`
  (critical, AST-guarded); `inline_self_correction_skipped_different_kind`
  (info); `system_uttered_anaphora_capture_pii_leak_detected`
  (critical — AST-guarded; defense-in-depth);
  `lexicon_state_divergence` (critical, per-pod);
  `lexicon_state_divergence_auto_quarantine_fired` (warn);
  `prober_drift_detected` (warn per-occurrence, critical at ≥ 5
  in 30min); `prober_corpus_unavailable` (error — file missing
  refuses prober start); `eval_corpus_intent_class_stale` (warn
  per-quarter); `eval_corpus_pii_redaction_verifier_disagreement`
  (critical — defense-in-depth on §10.32.14 step 2);
  `nlp_flame_capture_quota_exhausted` (warn — per-hour cap hit);
  `nlp_flame_capture_overhead_above_floor` (warn — capture cost
  > 5% threshold); `partial_bus_topic_red_for_intent_class`
  (warn per-topic per-class); `legacy_schema_pin_residual_traffic_above_floor`
  (warn — > 1% traffic still on deprecated schema past T-60d).

- **New `cfg` knobs** (~30 — single-source via `ai/common/config.py`
  + `xops/env/.env.example` + `defaults.yaml`):
  `nlp_quotative_min_confidence=0.70`,
  `nlp_aspectual_stack_max_depth=3`,
  `nlp_postposition_stack_unknown_event_enabled=true`,
  `nlp_dialect_class_min_recall=0.80`,
  `nlp_dialect_normalization_enabled=true`,
  `nlp_apostrophe_repair_enabled=true`,
  `nlp_apostrophe_repair_min_token_len=7`,
  `nlp_focus_particle_disambiguation_enabled=true`,
  `nlp_numeric_apostrophe_parse_enabled=true`,
  `nlp_productive_peel_max_depth=3`,
  `nlp_productive_peel_min_residue_resolution=true`,
  `nlp_self_correction_max_lookback_tokens=4`,
  `nlp_system_uttered_anaphora_capture_enabled=true`,
  `nlp_system_uttered_anaphora_max_lookback_turns=3`,
  `nlp_lexicon_gossip_interval_s=300`,
  `nlp_lexicon_divergence_min_rounds=2`,
  `nlp_lexicon_divergence_auto_quarantine=true`,
  `nlp_gossip_max_pods=50`,
  `nlp_prober_interval_s=60`,
  `nlp_prober_corpus_size=50`,
  `nlp_prober_humanizer_disabled=true`,
  `api_prober_bucket_rps=2` (Phase 9 mirror),
  `opsctl_flame_capture_ttl_h=24`,
  `opsctl_flame_capture_max_armed_per_h=10`,
  `nlp_flame_capture_overhead_floor_pct=5.0`,
  `nlp_eval_corpus_pr_max_added_rows_per_quarter=500`,
  `nlp_eval_corpus_review_required=true`,
  `nlp_partial_bus_topic_red_threshold_s=300`,
  `nlp_partial_bus_topic_yellow_threshold_s=30`,
  `nlp_meta_intents_zero_dep_enforced=true`,
  `nlp_qa_answer_dual_emit_enabled=false`,
  `nlp_qa_answer_legacy_grace_enabled=false`,
  `nlp_qa_answer_default_schema_version=6`.
  Triangle test extends; Go-side TestEnvSync covers Phase 9
  cross-language mirrors (`api_prober_bucket_rps`,
  `nlp_qa_answer_default_schema_version`,
  `apostrophe_proper_noun_spec` and `numeric_apostrophe_spec`
  SHA pins, topic-dependency map SHA pin).

- **Cross-phase impact:**
  - **Phase 5 (predictor):** zero schema impact (all NLP-internal
    additive fields).
  - **Phase 7 (sec):** shares NEW `proper_noun_apostrophe_spec.json`
    + `numeric_apostrophe_spec.json` cross-language + topic-
    dependency-map SHA pin; per §10.29.11 doctrine for byte-
    parity refuse-boot. Sec layer **does not parse morphology**
    — re-asserted by AST guard `test_go_sec_layer_does_not_parse_morphology`
    extended to new specs.
  - **Phase 8 (maint):** patcher EXCLUDES new
    `lang_tr/quotative/`, `lang_tr/aspectual/`, `lang_tr/postposition/`,
    `lang_tr/dialect/`, `lang_tr/apostrophe/`, `lang_tr/focus/`,
    `lang_tr/numeric_apostrophe/`, `lang_tr/productive_suffix/`,
    `lang_tr/self_correction/`, `lang_tr/system_meta/`,
    `lang_tr/conversational_meta/` (language tables ship via
    human review only); maint kind map extended for new
    `nlp_flame_armed` / `nlp_flame_captured` / `lexicon_state_divergence_auto_quarantine_fired`;
    backup-agent §8.3 covers new lexicon directories under
    its existing snapshot policy.
  - **Phase 9 (gateway):** consumes NEW
    `topic_dependency.yaml` byte-parity SHA pin; honors
    `synthetic_prober=true` (cache-bypass + rate-limit-bypass);
    handles `426 Upgrade Required` per §10.32.17 schema
    migration playbook; verifies §10.32.5 + §10.32.7
    cross-language specs at boot. Boundary test
    `test_gateway_does_not_strip_synthetic_prober_metadata`.
  - **Phase 11 (compute):** all §10.32 helpers CPU-only (AST
    rejects cuda/mps/rocm under
    `ai/nlp/quotative/`, `ai/nlp/aspectual/`, `ai/nlp/postposition/`,
    `ai/nlp/dialect/`, `ai/nlp/apostrophe/`, `ai/nlp/numeric_apostrophe/`,
    `ai/nlp/productive_suffix/`, `ai/nlp/self_correction/`,
    `ai/nlp/system_meta/`, `ai/nlp/conversational_meta/`,
    `ai/nlp/runtime/topic_dependency.py`, `ai/swarm/agents/nlp/prober.py`,
    `ai/swarm/agents/nlp/gossip_aggregator.py`).
  - **Phase 12 (chaos):** NEW chaos catalogue stubs:
    `chaos.lexicon-state-divergence-injection` (corrupt 1 pod's
    lexicon, assert §10.32.12 alert fires + auto-quarantine
    within 2 × gossip interval),
    `chaos.partial-bus-topic-red-injection` (block a single bus
    topic; assert §10.32.16 graceful degradation per intent
    class),
    `chaos.synthetic-prober-corpus-drift-injection` (mutate one
    expected output; assert §10.32.13 prober-drift alert fires),
    `chaos.flame-capture-overhead-injection` (induce slow per-
    stage; assert §10.32.15 overhead-floor alert fires),
    `chaos.dr-runbook-cold-restore-rehearsal` (full DR-runbook
    dry-run rehearsal — quarterly).
  - **Phase 13a (LeagueCatalog):** new lexicon-vs-catalog
    discipline §10.31.10 extended to NEW
    `apostrophe_proper_noun.tr.yaml` + `numeric_apostrophe_spec.json`
    +`postposition_stacks.tr.yaml`; `make verify.lexicon-catalog-consistency`
    extended.
  - **Phase 14 (K8s):** `nlp.gossip_aggregator.v1` and
    `nlp.prober.v1` are replicas:1, leader-leased per §8.10
    pattern; Lease annotations carry per-agent shed-tier per
    §8.15.8.
  - **Phase 16 (Emitter):** `LexiconStore` Protocol gains
    `dialect_normalization_table`, `apostrophe_proper_noun_table`,
    `productive_suffix_table` accessor methods; existing
    in-memory + Postgres + Feed backends extend via the same
    Protocol (no signature breakage).
  - **Phase 19 (deferred-tail leagues):** league-blind discipline
    re-asserted; AST guard `test_nlp_no_per_league_branch` walks
    all NEW §10.32 modules.
  - **Phase 20 (monetization):** every §10.32 routing decision
    is **tier-blind**; 4 new explicit AST guards
    (`test_nlp_quotative_routing_does_not_branch_tier`,
    `test_nlp_aspectual_routing_does_not_branch_tier`,
    `test_nlp_dialect_normalization_does_not_branch_tier`,
    `test_nlp_meta_user_data_disclosure_does_not_branch_tier`).
    Tier enforcement still lives in Phase 9 middleware only;
    NLP labels intent class only.

- **Cumulative proof-test count.** ~80 new proof tests on top
  of §10.20+§10.21–§10.31 baseline → cumulative Phase 10
  ≈ **735+ tests**. `make swarm.demo.nlp.full` extends to
  ≤ 75s budget covering 17 §10.32 paths (one per sub-section).

- **CODEOWNERS additions:** every new closed table requires
  `nlp-curator`; `regional_dialect_normalization.tr.yaml`
  additionally requires NEW `nlp-dialect-curator` group;
  `quotative_frames.tr.yaml` + `aspectual_stacks.tr.yaml` +
  `postposition_stacks.tr.yaml` + `inline_correction_markers.tr.yaml`
  + `conversational_meta.tr.yaml` additionally require
  `nlp-domain-football`; `prober_corpus.jsonl` + `eval_corpus/`
  also require `nlp-compliance` (PII-clean curation); cross-
  language specs (`proper_noun_apostrophe_spec.json`,
  `numeric_apostrophe_spec.json`, `topic_dependency.yaml`) also
  require Go owner. `make verify.nlp-codeowners` extended;
  CI-gated.

- **Versioning.** `swarm` minor (additive `qa.intent.v1`
  v5→v6 + `qa.answer.v1` v5→v6 + `qa.request.v1` v3→v4 +
  NEW `nlp.gossip.v1` + NEW `qa.context_extension.v1`;
  new closed tables; new modifier values; new event/alert
  kinds; new intent enum values) + `docs` minor in same
  commit. Chart compatibility block re-pinned (no new third-
  party deps; uses existing Zemberek + Symspell + python-
  crfsuite + Jinja2 stack; new pure-stdlib parsers in
  `ai/nlp/numbers/`, `ai/nlp/quotative/`, `ai/nlp/aspectual/`,
  `ai/nlp/dialect/`, `ai/nlp/apostrophe/`, `ai/nlp/productive_suffix/`,
  `ai/nlp/self_correction/`, `ai/nlp/system_meta/`,
  `ai/nlp/runtime/topic_dependency.py`).

- **Tracker row + ROADMAP checkbox flips** per AGENTS.md §3 +
  §3.4 — every checkbox in §10.32.1–§10.32.18 flipped to `[x]`
  at landing, with §10.20 DoD item 30 also flipped.
