# Phase 10 §10.29 — Deep-morphology, telegraphic-input, silent-failure floor

> **Provenance.** Carved out of `docs/planning/ROADMAP.md` Phase 10 on the Phase 10 split (post-13th-pass) so the ROADMAP stays navigable. Content here is the **binding** Phase 10 contract; ROADMAP §10 now points at this folder. Any edit must update `xops/versioning/chart.json` (`docs` minor) and the tracker (per AGENTS.md §3 + §6.1). Cross-phase references (Phase 5/7/8/9/11/12/13a/14/16/19/20) remain authoritative against ROADMAP and the matching `docs/design/*.md` anchors.


### 10.29 Deep-morphology, telegraphic-input, and silent-failure floor (binding addendum)

> **Why this section exists.** §10.0–§10.28 hardened nine independent
> floors (integrity, TR-correctness, serving, completeness, lifecycle,
> morphology+modality, lifecycle+abuse+regulatory, authentic-Turkish).
> Tenth-pass review against real-world Turkish football queries
> surfaces a residual class of *confidently-wrong* cases: deep
> morphology beyond the rules already enumerated (geminate restoration,
> stem-vowel deletion, irregular pronoun datives, -nk → -ng softening),
> Turkish-football telegraphic style ("Galatasaray bugün?" with no
> question marker and no verb), coordinator-driven multi-fixture parses
> ("Galatasaray ya da Fenerbahçe"), gerund-vs-nominalisation ambiguity
> that flips the *subject* of the question, and three integrity gaps
> that nine passes missed. Each `[ ]` here is binding for Phase 10 DoD
> per §10.20 item 27 (added in this pass).

#### 10.29.1 Geminate restoration (Arabic/Persian-origin doubled consonants)

- [x] **The problem.** Turkish single-stem stems borrowed from Arabic/Persian
  restore the dropped second consonant when a vowel-initial suffix attaches:
  `hak → hakkı` (right-acc), `sır → sırrı` (secret-acc), `his → hissi`
  (feeling-acc), `zan → zannı`, `şık → şıkkı`. Native speakers do this
  reflexively; ASCIIfication / Symspell / suffix-stripper currently treat
  `hakkı` as `hak+kı` (wrong: `kı` is not a Turkish suffix) → fall-through
  to typo correction → silent garbage.
- [ ] **Fix.** Closed `ai/nlp/lang_tr/spelling/geminate_restoration.tr.yaml`
  — `{stem, doubled_form, source: arabic|persian|turkish, _meta:
  added_at_utc, min_corpus_appearances ≥ 3}`. New §10.1 step 8c
  `restore_geminate` AFTER §10.28.1 consonant-alternation, BEFORE typo
  correction. Symspell index gains both forms via `_xref` collapse to a
  single canonical id.
- [ ] **Build refusal.** `make verify.nlp-lexicons` AST-asserts every
  LeagueCatalog player surname ending in single `{p,t,k,c}` whose
  Arabic-origin form is geminate has an explicit decision row (`{stem,
  decision: geminate|invariant, source: human|corpus_majority}`).
- [ ] **Proof tests.** ≥30-row positive golden (hak→hakkı, sır→sırrı, his→
  hissi, zan→zannı, şık→şıkkı + every doubled-consonant LeagueCatalog
  surname); ≥15-row negative (gol→golü NOT gollü, top→topu NOT toppu);
  Hypothesis idempotency ≥500 (`restore_geminate(restore_geminate(x))
  == restore_geminate(x)`); cross-language byte-parity test against the
  Phase 7 Go sec layer (extracted single-source `tr_geminate.py` →
  ported to `server/internal/sec/tr_geminate.go`).

#### 10.29.2 Stem-final vowel deletion before suffix (`ünlü düşmesi`)

- [ ] **The problem.** Disyllabic stems with a high vowel in the second
  syllable drop that vowel before a vowel-initial suffix:
  `oğul → oğlu` (son-acc), `burun → burnu` (nose-acc), `ağız → ağzı`
  (mouth-acc), `omuz → omzu`, `karın → karnı`, `gönül → gönlü`,
  `boyun → boynu`. **Common in TR surnames** (Oğuz, Yağız, Yamaç) so
  hits LeagueCatalog. Distinct from §10.28.1 vowel-drop in that it is
  the *suffix-attachment* trigger, not a stem-internal alternation.
- [ ] **Fix.** Closed `ai/nlp/lang_tr/spelling/vowel_drop_before_suffix.tr.yaml`
  — `{stem, dropped_form, suffix_classes: [acc,gen,dat,...]}`. Reuses
  §10.28.1 infrastructure but distinguished by `kind=before_suffix` enum.
  §10.5 entity extractor consults the table BEFORE gazetteer match so
  `Oğlu Mehmet'in` resolves to `Oğul Mehmet` (genitive) with explicit
  `entities[].morph={stem,dropped_vowel,suffix}` audit trail.
- [ ] **LeagueCatalog build refusal.** Any player/manager surname ending
  in `{Cl,Cn,Cr,Cz,Cm}` clusters where C is a stop must have a decision
  row (`drops|invariant`).
- [ ] **Proof tests.** 25-row positive + 10-row negative (gol→golü never
  drops; ev→evi never drops); LeagueCatalog-coverage assertion (every
  catalog surname matching the cluster pattern resolved); humanizer
  bypass test (humanizer must NOT rephrase `oğlu` back to `oğulu` —
  closed `meta.template.surface_morphology_invariant` lint rule).

#### 10.29.3 -nk → -ng softening (separate from generic -k → -ğ)

- [ ] **The problem.** Stems ending in `-nk` soften the `k` to `g` (not
  `ğ`) before vowel-initial suffix: `renk → rengi` (colour-acc), `ahenk
  → ahengi`, `çelenk → çelengi`. §10.28.1 generic k-softening rule
  produces `renk → renği` which is wrong — the spelling rule
  is specifically `nk → ng` (no breve). Misses today.
- [ ] **Fix.** Extend `consonant_alternations.tr.yaml` with `kind=nk_to_ng`
  branch keyed on the digraph; AST asserts the generic `-k → -ğ` branch
  fires only when the preceding character is NOT `n`.
- [ ] **Proof tests.** 12-row positive (5 catalog colours + 7 corpus
  words) + 8-row negative (`bank → bankı` NOT `bangı`; loanwords
  bypass); cross-language Go-side parity.

#### 10.29.4 Pronominal dative irregularity (`bana / sana / ona`)

- [ ] **The problem.** First/second-person/demonstrative pronouns have
  irregular dative forms: `ben → bana`, `sen → sana`, `o → ona`,
  `kim → kime` (regular but worth pinning), `bu → buna`, `şu → şuna`.
  Common in user opinion-framing: *"bana göre Galatasaray kazanır"*
  ("in my opinion Galatasaray wins"). Symspell currently treats `bana`
  as a typo of `bana?` lookups; sometimes resolves to a player surname
  with edit-distance 1 on a small lexicon → confidently wrong entity.
- [ ] **Fix.** Closed `ai/nlp/lang_tr/morph/pronouns_irregular.tr.yaml`
  — full paradigm table (8 pronouns × 6 cases). New step 5.5 in §10.5
  entity extractor: `mark_pronouns` runs BEFORE gazetteer match;
  matched tokens annotated `kind=pronoun` and EXCLUDED from gazetteer +
  Symspell + CRF NER. AST guard `test_nlp_pronouns_skip_lexicon`
  rejects any code path that calls `lexicon.lookup(token)` after
  `pronoun_marked=True`.
- [ ] **Proof tests.** 48-row paradigm completeness (8 × 6); 20-row
  adversarial (every irregular dative paired with a similarly-spelled
  LeagueCatalog surname → assert pronoun wins); idempotency.

#### 10.29.5 Loanword plural-as-singular drift

- [ ] **The problem.** Turkish often borrows English/Italian plurals as
  singular and re-pluralises Turkish-style: `data → datalar`,
  `media → medyalar`, `link → linkler`, `mail → mailler`. Symspell may
  resolve `linkler` to `link + ler` (double-plural detection) and
  classifier sees a different token from the user's intent.
- [ ] **Fix.** Closed `ai/nlp/lang_tr/loanwords/loan_singularisation.tr.yaml`
  — `{loan_form, accepted_plural, decision: singular|plural|both}`.
  Suffix stripper consults this BEFORE generic plural strip; matched
  tokens carry `morph.loan=true` to suppress §10.28.5
  transliteration-variant rewrite (which would over-fold).
- [ ] **Proof tests.** 30-row positive + 10-row negative; hot-reload
  proof; `_xref` build refusal on ambiguous decision.

#### 10.29.6 Verbal-noun gerund vs nominalisation ambiguity

- [ ] **The problem.** `-mak/-mek` (infinitive) vs `-ma/-me` (verbal
  noun) flips the **subject** of the question:
  - *"Galatasaray oynamak"* → "to play Galatasaray" (Galatasaray is the
    object — speaker plans to play AS Galatasaray, e.g. in a video game
    — should route to `meta.unsupported`).
  - *"Galatasaray'ın oynaması"* → "Galatasaray's playing" (Galatasaray
    is the subject — should route to `data.fixture_lookup`).
  - *"Galatasaray oynaması"* (missing genitive marker — common
    colloquial elision) → ambiguous, must offer disambiguation, NEVER
    silently pick.
- [ ] **Fix.** Closed `ai/nlp/lang_tr/morph/verbal_nouns.tr.yaml`
  — recogniser table for the four surface forms (-mak/-mek/-ma/-me);
  combined with §10.5 entity-genitive marker detection produces a
  `subject_polarity ∈ {entity_subject, entity_object, ambiguous}` signal
  carried on `qa.intent.v1.entities[].syntactic_role`. Dispatcher
  routes ambiguous cases to disambiguation answer with explicit Turkish
  gloss ("Galatasaray'ın oynaması mı, yoksa Galatasaray oynamak mı?").
- [ ] **AST guard.** `test_nlp_verbal_noun_ambiguity_never_silently_resolved`
  rejects any §10.6 dispatcher branch that picks a single fixture when
  `subject_polarity == ambiguous`.
- [ ] **Proof tests.** 40-row corpus (10 entity-subject + 10
  entity-object + 20 ambiguous); 100% disambiguation-or-correct gate.

#### 10.29.7 Reduplicated-emphasis collapse

- [ ] **The problem.** Turkish emphasises adjectives by full-word
  repetition: *"yeşil yeşil"*, *"uzun uzun"*, *"kırmızı kırmızı"*. §10.24.2
  `collapse_repeated_chars` only handles intra-token char repeats
  (`evettttt → evet`), not whole-word repeats. Classifier may double-count
  features.
- [ ] **Fix.** New §10.1 step 7c `collapse_reduplication` AFTER 7a
  (intra-token) and BEFORE 7b (question split). Closed
  `ai/nlp/lang_tr/morph/reduplication_pairs.tr.yaml` whitelist (build
  refuses non-identical pairs and pairs that are not in the closed
  emphatic-adjective set — defends against legit phrases like *"maç
  maç"* meaning "match by match").
- [ ] **Proof tests.** 25-row positive + 15-row negative (`ev ev` →
  *home-by-home* NOT collapsed; `maç maç` → *match-by-match* preserved);
  hypothesis idempotency.

#### 10.29.8 Coordinator-driven multi-fixture parsing (`ya da / veya / ya … ya`)

- [ ] **The problem.** *"Galatasaray ya da Fenerbahçe kim kazanır?"* is a
  **two-fixture comparative**, not a single question. Today §10.6
  dispatcher picks first-found entity → confidently wrong fixture
  routing. Worse: *"Ya Galatasaray ya Fenerbahçe"* (correlative) is a
  three-token-window construction prior passes don't recognise.
- [ ] **Fix.** Closed `ai/nlp/lang_tr/morph/coordinating_particles.tr.yaml`
  — `{form: ya_da|veya|ya_X_ya|veyahut, polarity: disjunctive|inclusive}`.
  §10.24.5 split-questions step extends to recognise these as
  multi-entity boundaries (NOT sub-question boundaries — the question
  itself is one). §10.6 dispatcher emits a comparative intent
  (`predict.match_outcome.comparative`, NEW) routing to a multi-fixture
  fan-out with comparative aggregation template.
- [ ] **Wire schema additive.** `qa.intent.v1.intent_modifier ∈ {none,
  comparative, conditional}` (additive enum, default `none`); schema
  bumped 3→4 (additive).
- [ ] **Proof tests.** 35-row corpus (15 ya-da + 10 veya + 10
  correlative ya-X-ya); 100% routes to comparative path.

#### 10.29.9 Telegraphic-style intent inference (no question marker, no verb)

- [ ] **The problem.** Turkish football fans write telegraphically:
  *"Galatasaray bugün"* — no `?`, no verb, no `mı`. §10.4 abstention
  floor today routes this to `meta.help` ("did you mean?"). The user's
  intent is unambiguously `data.fixture_lookup` (entity + temporal
  entity + nothing else).
- [ ] **Fix.** New deterministic heuristic in §10.4 BEFORE classifier:
  `infer_telegraphic_intent(entities, intent_distribution) → intent | None`.
  Fires when ALL of:
  1. ≥1 high-confidence entity (gazetteer hit) of kind `team|player|
     league|competition`,
  2. ≥1 temporal entity (date / time / weekday),
  3. Token count ≤ `nlp_telegraphic_max_tokens=4`,
  4. No verb-form detected (Zemberek POS tag absent),
  5. No question marker AND no `mı/mi/mu/mü`.
  → routes to `data.fixture_lookup` with confidence stamped
  `confidence=0.65, reason=telegraphic_inference`. Closed config table
  `ai/nlp/lang_tr/intent_telegraphic.tr.yaml` per intent class enum
  (5 classes whitelisted: fixture_lookup / kickoff_time / standings /
  h2h / player_card_risk).
- [ ] **AST guard.** `test_nlp_telegraphic_inference_never_routes_predict`
  — telegraphic path EXCLUDES every `predict.*` intent (predictions
  require explicit user assent — *"tahmin"* / *"olur mu"* / *"kim
  kazanır"*). This is a tier-blind safety floor.
- [ ] **Proof tests.** 45-row corpus (3-token telegraphic / 4-token
  telegraphic / boundary cases — verb present cancels, missing temporal
  cancels, `mı` cancels); 0-row predict.* leak; ≥0.85 fixture-lookup
  recall on telegraphic slice; abstention floor still fires when ANY
  condition fails.

#### 10.29.10 Particle "ki" colloquial-vs-formal disambiguation

- [ ] **The problem.** §10.22.4 detached particle `ki` but treats every
  occurrence the same. Two distinct uses:
  - **Relative** (formal, comma-bound): *"Galatasaray kazandı, ki bu
    sürpriz"* — `ki` introduces a relative clause; should be stripped
    from intent classification (it's discourse glue, not lexical).
  - **Emphatic** (colloquial, sentence-final): *"Galatasaray kazandı ki!"*
    — `ki` is a polarity intensifier; should propagate as a polarity hint.
  Confusing them flips affirmative/exclamatory framing.
- [ ] **Fix.** Particle detacher gains context test: presence of comma
  immediately before/after `ki` → relative; sentence-final or
  exclamation-mark-bounded → emphatic. Closed
  `ai/nlp/lang_tr/spelling/ki_context.tr.yaml` for ambiguous cases
  (build-curated, not heuristic).
- [ ] **Proof tests.** 25-row positive (relative + emphatic) + 10-row
  ambiguous (must offer disambiguation OR fall through to most common
  reading with explicit `ki_disambiguation_low_confidence` event); 0
  silent picks on the ambiguous slice.

#### 10.29.11 Cross-language TR-normalize byte-parity gate (single-source contract)

- [ ] **The problem.** Phase 7 Go sec layer (`server/internal/sec/sanitize.go`)
  and Python NLP normalize (`ai/swarm/agents/nlp/normalize.py`) each
  reimplement Turkish lowercase, NFC, control-strip, etc. Cross-language
  byte-parity for `tr_pii.py` was added at §10.28.4, but the *normalize*
  pipeline itself was never byte-parity-gated. Real risk: a Turkish-i
  fold that produces different bytes on the two sides → identical user
  input is sanitized differently at the gateway vs the NLP intake →
  classifier sees different tokens than the sec gate inspected →
  injection bypass class.
- [ ] **Fix.** Single-source spec at
  `ai/common/text/tr_normalize_spec.json` (canonical step list, codepoint
  mappings, NFC discipline, length-cap order). Both Python and Go
  implementations carry SHA of the spec at boot; refuse boot on
  mismatch. NEW corpus-driven differential test:
  `test_tr_normalize_python_go_byte_parity` — 1000-row Turkish corpus
  (seed=2026, mix of clean / typo / homoglyph / leetspeak / shouting /
  ASCIIfied / NBSP-padded) → byte-identical output between the two
  implementations on every row. Failure = build break.
- [ ] **Spec versioning.** `tr_normalize_spec.json` carries
  `spec_version=1`; bumping requires both implementations updated in
  the same PR (CODEOWNERS = both Python and Go owners), CI gate refuses
  PRs that bump spec without touching both implementations.
- [ ] **Proof tests.** Round-trip property (`normalize(normalize(x)) ==
  normalize(x)` on both sides); empty-string / single-char / max-cap
  boundary tests; spec-SHA-mismatch boot-refuse test on both sides.

#### 10.29.12 Prediction-id determinism gate (independent of envelope HMAC)

- [ ] **The problem.** §10.21.8 envelope HMAC catches forged
  `predict.approved.v1` envelopes when the HMAC key is intact and
  protected. If the operator HMAC key leaks (compromised pod, dev key
  reused in prod), HMAC verification passes but the producer was the
  attacker. Prior passes had no second independent integrity gate.
- [ ] **Fix.** §5 specifies `prediction_id = sha256(match_id | market |
  request_id | calibration_version)` as deterministic. NLP receiver
  re-derives this from envelope fields and rejects when mismatched.
  Catches: (a) HMAC-key compromise where attacker-injected envelope
  carries forged match_id but reused prediction_id from a real
  prediction (cache poisoning); (b) bus-level replay where prediction_id
  was crafted with a different calibration_version than what the
  envelope claims.
- [ ] **Wire.** New cfg knob
  `nlp_predict_prediction_id_determinism_required ∈ {off, warn, enforce}`
  default `warn` at v1, `enforce` post-Phase-14. New `nlp.alert.v1`
  kind `predict_prediction_id_mismatch` (severity=critical, debounced
  per producer-pod since attack would be sustained). Mismatched
  envelope → drop + route to `predict.timeout` template (degraded
  graceful, no user surface change).
- [ ] **Proof tests.** Synthesise an envelope with valid HMAC but
  wrong prediction_id → assert (a) drop event, (b) critical alert
  fires, (c) user sees degraded answer not silent wrong answer;
  legitimate envelope passes silently.

#### 10.29.13 Pipeline-version monotonicity (cache.v1 + L0 cache safety)

- [ ] **The problem.** Cache key includes `pipeline_version` (§10.23.9).
  Operational rollback past a cached `pipeline_version=N` would cause
  `pipeline_version=N-1` pods to read cache entries the older code
  cannot interpret (additive-only doctrine protects schema, but
  cached *outputs* may have used templates / morphology rules that
  the older code lacks). Today the boot validator only checks
  `compatibility_matrix.json` quartet; doesn't pin pipeline_version
  monotonicity against the live cache.
- [ ] **Fix.** Boot probe writes `cache:nlp:pipeline_max_seen` (Redis
  key, MAX-update via Lua CAS); pods at boot refuse start if
  `cfg.nlp_pipeline_version < pipeline_max_seen` AND
  `cfg.nlp_allow_pipeline_downgrade=false` (default false). Operator
  override `make nlp.allow-downgrade VERSION=<n> TTL=<s>` for
  emergency rollback (sets a Redis key with TTL; bumps an
  audit + critical alert per pod that uses it).
- [ ] **L0 cache invariant.** L0 entry carries the writer pod's
  `pipeline_version`; reader rejects (treat as miss) when
  `cached_pv > self.pv`. Defends in-process against lazy rollouts
  where some pods are still on N+1 while others rolled back.
- [ ] **Proof tests.** Boot-refuse test on cache-newer-than-self;
  L0 reject-on-version-mismatch test; emergency-override audit test;
  Lua CAS race test (two pods racing to bump max-seen → exactly one
  observed value, no lost updates).

#### 10.29.14 Cross-phase additions

- [ ] **Phase 4 (R1 storage).** No schema impact. Audit walks of
  `match_normalized.audit_jsonb` get a NEW field
  `morph_decisions[]` (geminate / vowel-drop / pronoun) for forensic
  re-render fidelity (additive, nullable; existing rows unaffected).
- [ ] **Phase 5 (consensus).** No schema impact. New consumer test
  asserts predict.approved.v1 with mismatched prediction_id is
  rejected per §10.29.12 — but Phase 5 itself MUST keep emitting the
  current deterministic id (pre-existing requirement, re-asserted as
  AST guard `test_consensus_emits_deterministic_prediction_id`).
- [ ] **Phase 7 (sec).** Cross-language byte-parity gate per §10.29.11
  added to existing `test_sec_input_python_go_parity` family (which
  was a §10.28.4 PII-only gate; now covers full normalize spec).
  Boundary discipline unchanged — sec layer still does NOT call NLP
  morphology helpers.
- [ ] **Phase 8 (patcher).** Patcher EXCLUDES new tables under
  `ai/nlp/lang_tr/{spelling,morph,loanwords,intent_telegraphic,
  spelling/ki_context}/*.yaml` (orthographic + grammar tables ship
  via human review only — re-asserts §10.28.14 doctrine for the new
  files).
- [ ] **Phase 9 (gateway).** No new HTTP-surface change. Gateway
  honours additive `qa.intent.v1.intent_modifier` field via JSON
  passthrough only (no semantic decision at the API tier; NLP owns
  intent semantics). The `test_qa_intent_v1_schema_additive_only`
  Phase 9 forward gate is widened to validate the new enum values.
- [ ] **Phase 11 (compute).** Telegraphic-inference helper, geminate /
  vowel-drop / pronoun helpers all CPU-only — AST guard rejects
  CUDA/MPS imports under `ai/nlp/lang_tr/`.
- [ ] **Phase 12 (chaos).** New stubs: `chaos.tr-normalize-spec-drift`
  (mutate one byte in `tr_normalize_spec.json` → both implementations
  refuse boot), `chaos.predict-prediction-id-forgery` (inject envelope
  with forged prediction_id → asserted dropped + alert + degraded
  template), `chaos.pipeline-version-rollback` (pod with pv=N-1
  attempts boot when cache has pv=N entries → refuse), `chaos.telegraphic-flood`
  (1000 RPS telegraphic queries → assert no predict.* leak, p99 dispatch
  latency unchanged).
- [ ] **Phase 13a (LeagueCatalog).** Build refusal extends to include
  geminate-restoration and vowel-drop-before-suffix decision rows for
  every catalog player/manager surname; coverage test
  `test_league_catalog_morph_completeness`.
- [ ] **Phase 14 (K8s).** No new probes. Pipeline-version monotonicity
  check runs at boot (already inside readiness stage 1 per §10.21.9 —
  add validation step in same stage).
- [ ] **Phase 16 (Emitter).** `LexiconStore` Protocol unchanged; the 7
  new tables flow through unchanged (additive). Feed schema bumps
  follow §10.21.13 doctrine.
- [ ] **Phase 19 (long-tail leagues).** League-blind re-asserted: no
  per-league branch in any new code; AST guard `test_nlp_no_per_league_branch`
  walks the new modules.
- [ ] **Phase 20 (monetization).** Telegraphic inference, comparative
  intent, geminate restoration, pronoun bypass all tier-blind. 4 new
  explicit AST guards (one per feature) re-assert no `tier_id` branch.

#### 10.29.15 Knob inventory & wire additions

- [ ] **~16 new cfg knobs:** `nlp_telegraphic_max_tokens=4`,
  `nlp_telegraphic_min_entity_confidence=0.85`,
  `nlp_telegraphic_inference_enabled=true`,
  `nlp_geminate_restoration_enabled=true`,
  `nlp_vowel_drop_before_suffix_enabled=true`,
  `nlp_pronoun_lexicon_bypass_enabled=true`,
  `nlp_loanword_singularisation_enabled=true`,
  `nlp_verbal_noun_disambiguation_enabled=true`,
  `nlp_reduplication_collapse_enabled=true`,
  `nlp_coordinator_split_enabled=true`,
  `nlp_ki_context_disambiguation=true`,
  `nlp_predict_prediction_id_determinism_required=warn`,
  `nlp_pipeline_version=<int>` (single-source from chart),
  `nlp_allow_pipeline_downgrade=false`,
  `nlp_tr_normalize_spec_path`, `nlp_tr_normalize_spec_required=enforce`.
- [ ] **8 new `nlp.event.v1` kinds** (open enum per §8.16.2):
  `geminate_restored`, `vowel_dropped_before_suffix`,
  `pronoun_lexicon_bypassed`, `loanword_singularised`,
  `verbal_noun_disambiguation_offered`, `reduplication_collapsed`,
  `coordinator_split_applied`, `telegraphic_intent_inferred`,
  `ki_context_disambiguated`.
- [ ] **5 new `nlp.alert.v1` kinds** (debounced per §10.21.13 doctrine):
  `tr_normalize_spec_drift` (critical, refuse boot),
  `predict_prediction_id_mismatch` (critical, debounced 60s per
  producer-pod), `pipeline_version_downgrade_blocked` (critical),
  `pipeline_version_downgrade_emergency_override_used` (warn,
  per-override), `verbal_noun_ambiguity_rate_high` (warn, debounced 600s).
- [ ] **~50 new proof tests** on top of cumulative §10.0–§10.28
  ≈ 535+ → cumulative Phase 10 ≈ 585+ tests.
- [ ] **`make swarm.demo.nlp.full`** extends ≤ 60 s budget covering 6
  §10.29 paths (geminate, vowel-drop, pronoun, telegraphic,
  comparative, byte-parity).

#### 10.29.16 Definition of Done additions

- [ ] All `[ ]` items in §10.29.1–§10.29.15 ticked.
- [ ] §10.20 DoD item 27 added (this section's binding).
- [ ] CODEOWNERS updated: `ai/nlp/lang_tr/spelling/{geminate_restoration,
  ki_context}.tr.yaml`, `ai/nlp/lang_tr/morph/*.tr.yaml`,
  `ai/nlp/lang_tr/loanwords/loan_singularisation.tr.yaml`,
  `ai/nlp/lang_tr/intent_telegraphic.tr.yaml`,
  `ai/common/text/tr_normalize_spec.json` require `nlp-curator`
  (orthographic / grammar) reviewer; `tr_normalize_spec.json` *also*
  requires Go owner (cross-language single-source). `make
  verify.nlp-codeowners` CI-gated.
- [ ] **Versioning.** `swarm` patch (no public surface change beyond
  additive intent_modifier enum); `docs` minor in same commit. Chart
  compatibility block re-pinned (no new deps; `signal` / `resource` /
  Zemberek already pinned at §10.21).
- [ ] **Tracker row + ROADMAP checkbox flips** per AGENTS.md §3 + §3.4
  — every checkbox in §10.29.1–§10.29.16 flipped to `[x]` at landing,
  with §10.20 DoD item 27 also flipped.
