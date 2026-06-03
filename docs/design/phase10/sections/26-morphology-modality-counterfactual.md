# Phase 10 §10.26 — Morphological correctness, input modality, counterfactual handling

> **Provenance.** Carved out of `docs/planning/ROADMAP.md` Phase 10 on the Phase 10 split (post-13th-pass) so the ROADMAP stays navigable. Content here is the **binding** Phase 10 contract; ROADMAP §10 now points at this folder. Any edit must update `xops/versioning/chart.json` (`docs` minor) and the tracker (per AGENTS.md §3 + §6.1). Cross-phase references (Phase 5/7/8/9/11/12/13a/14/16/19/20) remain authoritative against ROADMAP and the matching `docs/design/*.md` anchors.


### 10.26 Morphological correctness, input modality, and counterfactual handling (binding addendum)

> **Why a seventh pass.** §10.21 fixed integrity, §10.22 fixed
> TR-language correctness, §10.23 fixed serving, §10.24 fixed messy
> wrong-Turkish surface, §10.25 fixed lifecycle / conversation /
> time-travel. Three classes of real-world Turkish input pathology
> still slip through and cause user-visible wrong answers, not just
> degraded ones: (a) **morphological-analyzer ambiguity** — Zemberek
> routinely returns 5+ parses for a single agglutinated token and the
> wrong root resolves to the wrong canonical entity; (b) **input
> modality variance** — voice-to-text, mobile IME, and copy-paste
> long-form input each produce distinct, high-frequency artifact
> classes that desktop-typed corpora never see; (c) **counterfactual
> and modal-aspect intent** — "yenseydi", "oynayacak mıydı", "olur
> muydu" naively route to `predict.*` (future) when the user is
> asking about a hypothetical past, producing a *confidently wrong*
> answer instead of a graceful refusal. §10.26 closes all three with
> deterministic gates, closed tables, AST guards, and ~72 new proof
> tests on top of the §10.25 baseline.

#### 10.26.1 Morphological analyzer ambiguity discipline (Zemberek top-K + confidence floor)

- [x] **Real bug §10.1 step 7 left open.** "Zemberek tokens"
  (vendored rules in `ai/nlp/vendor/zemberek_rules.json`) was
  spec'd as a single best-parse output. In production Zemberek-style
  analysers commonly emit 3–8 candidate parses for one Turkish
  token (e.g. `evine` → `ev+P3sg+Dat`, `evi+P3sg+Dat`,
  `ev+P2sg+Dat`, ...). Picking the lexicographically-first or
  longest-suffix parse silently mis-routes the wrong root downstream
  to the gazetteer, especially on proper nouns
  (*Galatasaray'ından* — possessive vs ablative collide on the
  surface form *-ından*).
- [x] **Top-K parse acceptance.** `cfg.nlp_morph_topk=3` candidate
  parses retained per token. `MorphCandidate = (root, suffix_class,
  pos, confidence, ambiguity_class ∈ {unique, low, high,
  unparseable})`. Stored on the token, NOT collapsed at this stage.
- [x] **Confidence floor + abstention.** Each parse carries a
  unigram-frequency-weighted confidence `0.0..1.0` from
  `ai/nlp/data/tr_morph_freq.json` (SHA-pinned, rebuilt from the
  same Wikipedia corpus as §10.3 diacritics). Floor
  `cfg.nlp_morph_min_confidence=0.55`; below floor → flag
  `ambiguity_class=high`. **Never** silently pick a low-confidence
  parse — emit `nlp.event.v1{kind=morph_parse_ambiguous,
  surface_form_sha8, candidate_count}` (debounced 60s, PII-safe via
  sha8 only).
- [x] **Resolution arbitration (deterministic, ordered).** When
  multiple parses survive the confidence floor:
  1. **Gazetteer cross-check wins.** If exactly one candidate root
     matches a `lexicon_canonical_id` in §10.2, pick it.
  2. **POS preference per intent class.** Closed table
     `morph_pos_preferences.tr.yaml` (`predict.* → noun_proper >
     noun_common`, `data.player_card_risk → noun_proper`,
     `meta.help → any`).
  3. **Co-token context.** If a high-confidence neighbouring token
     (within radius `cfg.nlp_morph_context_radius=4`) selects a POS,
     prefer the matching parse on the ambiguous token.
  4. **Tie-break by frequency rank.** Higher unigram frequency wins.
  5. **Still tied** → emit `slot_resolution_failed` (per §10.5) and
     route to `did_you_mean` (NEVER guess).
- [x] **Proper-noun morphology guard.** Proper-noun stems
  (`is_proper=True` from §10.22.2 `strip_proper_noun_suffix`)
  short-circuit the parser — Zemberek does not own proper-noun
  morphology and frequently truncates them
  (*Beşiktaş'tan* → `Beşik+taş` wrong-stem). AST guard
  `test_nlp_proper_noun_skips_zemberek` asserts the surface form
  reaches the gazetteer untransformed when `is_proper=True`. Bypass
  emits `nlp.event.v1{kind=morph_proper_noun_bypassed}` (debounced).
- [x] **Unparseable token policy.** Zemberek returning zero parses
  is a **valid signal** (foreign word, code-switch, neologism,
  emoji-name); fall through to: (a) gazetteer pass, (b) §10.22.8
  bilingual gazetteer, (c) §10.24.10 abbrev table, (d) §10.3
  Symspell. Only if all four miss → token is "unresolved" and feeds
  the §10.25.8 `nlp_unresolved_token_top_k` telemetry. Never raise.
- [x] **Ambiguity budget per query.** ≤ `cfg.nlp_morph_ambiguous_max_per_query=4`
  high-ambiguity tokens; over-budget → `did_you_mean` fallback with
  the first 2 unambiguous content tokens echoed back. Defends
  against pathologically agglutinated input
  (*"Galatasaraylılaştıramadıklarımızdan mısınız?"* — fun trivia,
  but not a useful classifier signal).
- [x] **Determinism guarantee.** Same input + same
  `zemberek_rules.json` SHA + same `tr_morph_freq.json` SHA + same
  arbitration tables → byte-identical `MorphCandidate[]` ordering
  across runs. Hypothesis property test (≥ 500 examples,
  `derandomize=True`) seeds + hashes parser output.
- [x] **Cross-language parity unaffected.** Morphology runs Python-
  side only — Go sec layer (Phase 7) does not parse morphology and
  does not need to mirror this. Boundary test
  `test_go_sec_layer_does_not_parse_morphology` asserts no Zemberek
  port lands under `server/internal/sec/`.

#### 10.26.2 Voice-to-text / ASR-input tolerance (binding)

- [x] **Why this section.** Mobile clients (Phase 9 forward) will
  ship a speech-to-text affordance. ASR engines (Google/Apple/Yandex
  TR models) emit input that systematically violates assumptions
  baked into §10.1: no punctuation, no question marks, no
  capitalization (or wrong capitalization on proper nouns),
  hesitation tokens (*ııı*, *eee*, *şey*), filler words (*yani*,
  *aslında*, *ya*, *işte*), and missing diacritics on lower-frequency
  proper nouns the ASR LM hasn't seen. None of §10.22.4 (particle
  disambiguation), §10.22.5 (dialect/abbreviation), §10.24.5 (run-on
  multi-question split) handles this cleanly because they assume
  punctuation as a primary signal.
- [x] **Detect ASR origin (heuristic, advisory).** New
  `request_metadata.input_source ∈ {keyboard, voice, paste,
  unknown}` (additive on `qa.request.v1`, `qa.context.v1` —
  schema_version 2→3, default `unknown`). When `voice`, opt-in to
  the ASR-tolerant path. Heuristic detector (server-side, runs even
  when client doesn't supply): zero `?` + zero `,` + length ≥ 40
  chars + ≥ 2 hesitation tokens → auto-mark `voice` and emit
  `nlp.event.v1{kind=asr_input_auto_detected}` (debounced 60s).
  Detector NEVER mutates the request — only sets the flag.
- [x] **Hesitation / filler token table.** `ai/nlp/lang_tr/asr/fillers.tr.yaml`
  closed enum — `{ııı, eee, ee, ıı, mmm, hmmm, şey, yani, aslında,
  yaa, işte, falan, falan filan, ne bileyim}`. New §10.1 step 6.5
  `strip_asr_fillers` — runs ONLY when `input_source=voice` (do not
  strip *yani* from typed input — it is sometimes content-bearing).
  Per-query strip cap `cfg.nlp_asr_filler_strip_max=6` (over-cap →
  emit `asr_filler_overflow`, fall through to raw — defends against
  "ya ya ya ya ya ..." abuse).
- [x] **Implicit punctuation reconstruction.** When `input_source=voice`,
  apply §10.24.5 `split_questions` with **relaxed** rules: any
  occurrence of `mi/mı/mu/mü` followed by ≥ 5 content tokens splits
  even without a question mark; `ve` + clause-boundary detection
  upgraded from passive to active. Boundary test enforces this is
  a no-op when `input_source=keyboard`.
- [x] **Diacritic restoration aggressiveness toggle.** §10.3
  diacritic ambiguity tie-break ratio (`nlp_diacritic_tie_break_ratio=1.5x`)
  loosens to `cfg.nlp_diacritic_tie_break_ratio_voice=2.5x` when
  `input_source=voice` (ASR engines under-emit diacritics on
  low-frequency tokens; we accept more aggressive restoration on the
  voice path because the user's spoken input genuinely contained
  them).
- [ ] **Capitalization signal disabled on voice.** §10.22.2
  proper-noun detection MUST NOT short-circuit on capitalization
  alone when `input_source=voice` — ASR commonly lowercases
  everything OR over-capitalizes the first token of every
  utterance. Lexicon hit remains the sole authoritative proper-noun
  signal on this path. AST guard `test_nlp_voice_path_no_caps_short_circuit`.
- [ ] **Latency budget unchanged.** Voice path adds ≤ 3 ms p95 to
  §10.1 normalize stage (filler strip is one regex pass + table
  lookup). CI bench gate enforces.
- [ ] **Adversarial corpus extension.** §10.18 evaluation harness
  gains a `voice` slice of ≥ 30 transcribed utterances (curated
  from real ASR output of test reads, NOT synthesized — synthetic
  ASR has different artifact distribution per Rule 3). Slice gates
  are intent acc ≥ 0.85 (lower than clean per realism), entity F1
  ≥ 0.80; **abstention-on-low-confidence behaviour identical to
  keyboard path**.

#### 10.26.3 Mobile-IME pathologies (Q-keyboard / F-keyboard / swipe / autocorrect-cascade)

- [ ] **Why this matters.** Turkish mobile users split between Q
  (QWERTY) and F (Atatürk's official Turkish layout) keyboards —
  these produce **systematically different** typo-substitution
  matrices because adjacent keys differ. Symspell with a single
  edit-distance budget treats both equivalently and under-corrects
  one or over-corrects the other. Swipe keyboards add a third
  pattern: vowel-rich substitutions that Symspell rarely models.
  Autocorrect cascades produce the strangest class — a single
  mistyped letter triggers an autocorrect to a real-but-wrong word
  (*Galatasaray* → *Galatasarah* → autocorrect → *galatasaray* OK,
  but *Beşiktaş* → *Beşiktaa* → autocorrect → *beşiktas* — diacritic
  loss + final-consonant change).
- [ ] **Layout-aware confusable matrix.** `ai/nlp/lang_tr/ime/keyboard_confusables.tr.yaml`
  with three matrices: `q_layout`, `f_layout`, `swipe_vowel`. Each
  maps `(key, neighbour) → cost_multiplier` (default 1.0; adjacent
  keys 0.5; same-row-non-adjacent 0.8). Build pipeline
  `make nlp.ime-matrix-build` regenerates from public layout
  diagrams (SHA-pinned in chart) — no live download.
- [ ] **Layout detection (heuristic, advisory).** Optional
  `request_metadata.keyboard_hint ∈ {q, f, swipe, unknown}` on
  `qa.request.v1` (additive). When `unknown`, infer from typo
  pattern (run Symspell with both Q and F matrices on first 3
  ambiguous tokens; pick the matrix that yields more lexicon
  hits within budget). Inference cached per `client_id` (64-byte
  hash, NOT user_id) for `cfg.nlp_ime_layout_cache_s=3600`.
  Cache bypassed when `keyboard_hint` explicit.
- [ ] **Symspell extension.** `ai/nlp/vendor/symspell.py` gains
  `lookup(token, layout=None)` — when `layout` set, edit costs use
  the layout matrix; default budget unchanged. AST guard
  `test_nlp_symspell_layout_param_optional` asserts callers either
  pass `layout` explicitly or accept default-equal-weights.
- [ ] **Autocorrect-cascade detection.** Closed table
  `autocorrect_cascade.tr.yaml` of known cascades from observed
  corpora — `{wrong_form: canonical_form, layouts: [q, f]}`. Hit
  short-circuits Symspell + diacritic restoration for that token
  and emits `nlp.event.v1{kind=autocorrect_cascade_repaired}`
  (debounced 60s per cascade form). Single source — never
  inferred at runtime (would be unbounded).
- [ ] **Per-query layout-aware budget.** `cfg.nlp_typo_max_lookups_per_query`
  unchanged at 8; layout-aware lookups count as 0.5 each (cheaper
  search → more attempts allowed within same wall-clock budget).
  Boot validator asserts `0.5 * 8 < cfg.nlp_normalize_stage_timeout_ms / 2`.
- [ ] **Privacy.** `keyboard_hint` and `client_id`-keyed layout
  cache do NOT enter logs in clear; logs carry only
  `keyboard_hint_class ∈ {q, f, swipe, unknown}` (no client
  identification possible from log alone). PII discipline
  unchanged.

#### 10.26.4 Numerical and temporal Turkish completeness floor

- [ ] **Number-word ↔ digit bidirectional resolver.** §10.22.6
  spec'd `bir sıfır → 1-0` (score line) but left number-word
  resolution as a one-way street. Real input is bidirectional:
  *"2024 yılında"* and *"iki bin yirmi dört yılında"* must collapse
  to the same `(year=2024)` entity. NEW
  `ai/nlp/dates_tr.py::number_word_to_int(tokens) → (int, span)`
  + inverse `int_to_number_word(n, register='cardinal'|'ordinal')`.
  Closed Turkish lexicon `ai/nlp/lang_tr/numbers/number_words.tr.yaml`
  (sıfır..milyar). AST guard
  `test_nlp_number_resolver_bijective_on_0_to_9999` asserts
  `int_to_number_word(number_word_to_int(x)) == x` for every
  generated form.
- [ ] **Ordinal handling.** Closed forms only:
  - Word ordinals: *birinci, ikinci, üçüncü, ...* + *sonuncu*
  - Digit-ordinals with `'inci/'üncü/'üncü/'ıncı`: *3'üncü, 21'inci*
  - Suffix-ordinals: *3.* (dotted-numeric)
  All resolve to `OrdinalEntity{position: int, polarity:
  'forward'|'reverse'}` (`sonuncu` → reverse-1, *son* → reverse-1
  contextual, *önceki* → reverse-1 only with co-token like
  *hafta/maç*). Deterministic per closed table; never
  ML-predicted.
- [ ] **Fractional time.** `yarım/çeyrek/buçuk` resolver:
  *"yarım saat sonra"* → `+30min`, *"çeyrek saat sonra"* → `+15min`,
  *"iki buçuk saat sonra"* → `+150min`. Closed combinator over
  number-word-resolver output. Edge cases pinned in 30-row golden:
  *"buçukta"* (= half past the implicit hour — refuses without
  hour anchor; emits `slot_resolution_failed`).
- [ ] **Relative time enrichment.** Add to §10.5 date resolver:
  *önceki hafta, geçen hafta, geçen ay, geçen yıl, dünden önce,
  iki gün sonra, X gün önce, X hafta sonra, hafta sonu* — each
  resolves to `(start_utc, end_utc, granularity, polarity ∈
  {past, future, present})`. **Past polarity routes to historical
  intents (data.h2h, data.standings) NEVER to predict.\*** —
  closed table `temporal_intent_polarity.tr.yaml` enforces this
  routing constraint at the dispatcher. AST guard
  `test_nlp_past_polarity_never_routes_predict`.
- [ ] **DST-bridging clock arithmetic.** When relative time crosses
  Europe/Istanbul DST boundary (still observed historically pre-2016
  for past queries; post-2016 Türkiye is permanent UTC+3 — no DST
  active currently), use IANA tzdata (already SHA-pinned per
  §10.23.6); emit `nlp.event.v1{kind=temporal_dst_crossed}` with
  the crossing date for operator visibility on past queries
  (debounced).
- [ ] **Numeric format ambiguity (extends §10.24.11).** `1.234`
  is *one thousand two hundred thirty-four* in tr-TR (period as
  thousands separator) but `1.5` in same locale is *one point five*
  (period as decimal — borrowed from English betting odds context).
  Resolver examines co-tokens in radius 3: `[oran, kat, çarpan]`
  near `\d+\.\d+` → decimal (English betting); `[gol, sayı,
  taraftar]` → thousands (Turkish format). Ambiguous → emit
  disambiguation answer (NEVER silent pick).
- [ ] **Half-built number guard.** A user typing *"iki bin"* and
  pressing send has built half a number. Resolver returns
  `PartialNumberEntity{accumulator: 2000, unit_pending: True}` —
  dispatcher treats as unresolved and offers
  `did_you_mean: ["2000 yılı?", "2000. dakika?"]`. AST guard
  `test_nlp_partial_number_never_silently_completes`.

#### 10.26.5 Counterfactual / conditional / modal-aspect intent firewall

- [ ] **Real bug.** §10.4 intent enum has no slot for hypothetical-
  past queries. *"Galatasaray Fenerbahçe'yi yenseydi şampiyon
  olur muydu?"* (had Galatasaray beaten Fenerbahçe, would they
  have been champions?) classifies as `predict.match_outcome` with
  high confidence on a fastText keyword overlap → routes to
  predictors → returns a confidently wrong answer about the (now
  past) match. Worse: *"olur muydu"* (would it have been) marked
  as future-tense by the surface keyword `olur`.
- [ ] **Modal-aspect detector (deterministic, table-driven).** NEW
  `ai/nlp/lang_tr/modality/aspect_markers.tr.yaml` closed enum:
  - `counterfactual_past`: *yenseydi, oynasaydı, gelseydi,
    olsaydı, kazansaydı, olur muydu, olur muyduk*
  - `inferential_past`: *oynamış olur, kazanmış olur* (past
    inferential — historical lookup)
  - `epistemic_potential`: *oynayabilir, kazanabilir, olabilir*
    (potential — OK for `predict.*`)
  - `obligative`: *oynamalı, kazanmalı* (advice — refuse with
    explanation; no betting advice surface in v1)
  - `evidential_hearsay`: *oynamış, kazanmışmış, diyorlar*
    (hearsay — historical lookup)
- [ ] **Detection algorithm.** §10.5 entity pass gains
  `modality_class` extraction; pattern is suffix-tail match on
  any verb-position token. Suffix patterns regex-pinned in YAML;
  AST guard rejects inline regex literals in agent code.
- [ ] **Routing override (binding).** §10.6 dispatcher MUST NOT
  publish `predict.request.v1` when `modality_class ∈
  {counterfactual_past, inferential_past, evidential_hearsay,
  obligative}`. Routing table:
  - `counterfactual_past` → `meta.counterfactual_unsupported`
    template with explicit Turkish phrasing
    (*"Olmuş bir maçın farklı sonuçlanmış halini öngöremem; geçmiş
    sonuçlar için sorabilirsiniz."*) — humanizer-bypassed.
  - `inferential_past` → `data.h2h` if entities resolve, else
    `did_you_mean`.
  - `evidential_hearsay` → `data.h2h` (treats as past lookup).
  - `obligative` → `meta.advice_unsupported` template
    (*"Bahis tavsiyesi vermem; tahmin olasılıkları paylaşabilirim;
    bahis bilgisi için yetkili sitelere başvurun."*) —
    humanizer-bypassed; CRITICAL — also tier-blind (advice-refusal
    is a doctrine line, not a paywall).
- [ ] **Ambiguous modality.** When the modality classifier returns
  high confidence on `epistemic_potential` AND a past temporal
  entity is present (*"yarın oynayabilir mi"* with *yarın* → fine;
  *"dün oynayabilir mi"* → contradiction), prefer
  `meta.unsupported` with explicit disambiguation. AST guard
  `test_nlp_modal_x_temporal_contradiction_routes_unsupported`.
- [ ] **Proof-test density.** ≥ 30 modality cases curated by hand
  in `ai/nlp/tests/data/modality_corpus.tr.json` — each row pinned
  to expected (`modality_class`, `routed_intent`, `template`).
  100% gate, no `xfail`.

#### 10.26.6 Lexicon supply-chain defense (PR-flood, typo-squat, ortho-confusable canonical)

- [ ] **Real attack vector.** §10.25.6 added two-reviewer rule for
  high-leverage tables but did NOT cap PR diff size, did NOT detect
  typo-squat aliases (*Galaatasaray* alias added to a fake team
  canonical), did NOT detect ortho-confusable canonical IDs
  (someone introduces canonical_id `galatasaray_v2` colliding under
  §10.21.5 confusables fold with the real `galatasaray`).
- [ ] **PR diff size cap.** `make verify.nlp-lexicon-diff` (NEW;
  CI-gated) computes added-row count per file in the PR; hard cap
  `cfg.nlp_lexicon_pr_max_added_rows_per_file=200`, soft warn at
  50; over-cap → CI failure with explicit "split this PR" message.
  Defends against drive-by alias-flood.
- [ ] **Typo-squat detector.** For every newly added alias, run
  Symspell against the existing alias index of OTHER canonicals
  with edit budget 1. Hit on a different canonical → CI failure
  citing the collision. Over-ride only via explicit
  `_aliases_delta.tr.yaml::overrides` block listing both canonicals
  + a justification (e.g. legitimate near-collision *Adana
  Demirspor* vs *Adanaspor* — two real distinct teams).
- [ ] **Ortho-confusable canonical guard.** `make verify.nlp-lexicons`
  extends with: every canonical_id passes through §10.21.5
  confusables-fold; collision with another canonical's folded form
  → build failure (mirrors the §10.2 alias round-trip property,
  but on canonical IDs, which the prior pass missed because IDs
  are normally ASCII — but a malicious PR can use any UTF-8 code
  point). Closed allow-list under
  `lang_tr/_canonical_id_collision_allow.yaml` (empty at v1).
- [ ] **Alias age + provenance.** §10.25.6 added `source` field;
  this section adds `added_at_utc` and `min_corpus_appearances`
  (auto-populated by build pipeline from a SHA-pinned corpus
  excerpt — alias must appear ≥ N times across recent
  scraper output to ship; default `cfg.nlp_lexicon_min_alias_appearances=3`,
  override per row only with reviewer ack). Defends against
  pure-fabrication aliases.
- [ ] **Lexicon CI-bot impersonation defense.** The PR-flood
  attacker may try to impersonate the build bot. CODEOWNERS-derived
  `lexicon-build-bot` GH actor identity is the ONLY committer
  allowed to bypass §10.25.6 two-reviewer rule for auto-regenerated
  files (`teams.tr.yaml`, etc. that are derived from
  `_aliases_delta.tr.yaml` + LeagueCatalog). Boot-time validator
  in CI (NOT runtime) refuses any commit author mismatch on those
  files.

#### 10.26.7 Multi-turn correction grammar (extends §10.25.1)

- [ ] **Real gap.** §10.25.1 multi-turn conversation persists
  entities across turns but has no spec for *explicit user
  correction* — *"öyle değil, Beşiktaş demek istedim"* (not like
  that, I meant Beşiktaş). Without correction handling, the prior
  turn's wrong entity sticks for the rest of the conversation.
- [ ] **Correction-utterance detector.** Closed table
  `lang_tr/correction/correction_markers.tr.yaml`:
  - Negation-of-prior: *yok öyle değil, hayır onu demedim, yanlış
    anladın, ben X demek istedim*
  - Replacement: *X değil Y, X yerine Y, aslında Y*
  - Restart: *yok yok, baştan, unut onu*
- [ ] **Detection trigger + scope.** Detector fires only when
  `conversation_id` is bound AND there is at least one prior
  turn AND the current utterance starts with one of the markers
  OR contains a replacement bigram with high lexicon-hit rate on
  the second slot. False-positive rate target ≤ 1% on a
  hand-curated 100-row negative corpus.
- [ ] **Context-update semantics.** On detection:
  - `negation_of_prior` → mark prior turn's last entity as
    superseded; do NOT carry forward.
  - `replacement` → swap prior entity for the new one; emit
    `nlp.event.v1{kind=conversation_correction_applied}`.
  - `restart` → clear the conversation context entirely; emit
    `nlp.event.v1{kind=conversation_restarted_by_user}`.
- [ ] **Audit trail.** Every correction emits an audit row with
  the prior+new entity sha8 only (no raw text, mirrors §10.25.1
  PII discipline). Defense against an adversary using corrections
  to probe internal entity resolution.
- [ ] **Boundary.** Correction grammar is conversation-scoped
  ONLY. AST guard
  `test_nlp_correction_disabled_when_conversation_id_absent`.

#### 10.26.8 Output integrity envelope HMAC (extends §10.21.8)

- [ ] **Real gap §10.21.8 left open.** §10.21.8 added an HMAC over
  the prediction-citation block to detect a forged
  `predict.approved.v1` from a compromised bus worker. But the
  full `qa.answer.v1` envelope (including the body, citation,
  degraded flag, and `tier_id_required` per §10.0) is NOT covered.
  An attacker who can write to `cache.v1` directly (Phase 9 cache
  poisoning surface) can mutate the body field while the citation
  HMAC stays valid → user sees attacker-chosen text under a
  legitimate citation.
- [ ] **`qa.answer.v1.envelope_signature` (additive,
  schema_version 2→3).** HMAC-SHA256 over
  `(qa_correlation_id || produced_at_utc || body_canonical ||
  citation_canonical || degraded || degraded_reason ||
  tier_id_required || pipeline_version || compatibility_quartet_sha)`
  with `cfg.qa_answer_hmac_key_path` (mode 0400 — Phase 9 gateway-
  only readable; NLP writes it; gateway verifies it; bus worker
  cannot read it).
- [ ] **`body_canonical` derivation.** NFC-normalize body, replace
  every contiguous whitespace run with a single space, strip
  trailing whitespace per line, sha256 the bytes — pinned canonical
  form. Mirrors §10.21.6 citation-canonical doctrine.
- [ ] **Rollout discipline.** `cfg.nlp_answer_envelope_hmac_required
  ∈ {off, warn, enforce}` default `warn` at v1; `enforce` post
  Phase-14. `make nlp.rotate-answer-hmac-key` dual-acceptance
  window 24h.
- [ ] **Cache-write boundary.** AST guard
  `test_nlp_cache_writer_signs_envelope` asserts every
  `cache.v1{kind=qa_answer}` write includes `envelope_signature`.
- [ ] **Gateway-side verify** lives at Phase 9 §9.17.x (forward
  contract added to §10.0 cross-phase block) — Phase 9 gateway
  reads `cache.v1` for cached answers and MUST verify the HMAC
  before serving; on fail → emit
  `sec.alert.v1{kind=qa_answer_envelope_signature_invalid,
  severity=critical}`, evict cache entry, fall through to live
  RPC. Boundary test in Phase 9 enforces.

#### 10.26.9 Long-form copy-paste pathologies (binding)

- [ ] **Real-world input.** Users frequently paste a paragraph
  from a news article or social media as their question. This
  produces input that simultaneously violates §10.1 length cap,
  contains `\xa0` (non-breaking space — already strip-targeted in
  §10.1 step 3 but the step explicitly only strips
  *control/zero-width/RTL*, not whitespace variants), contains
  curly quotes (*"…"*, *'…'*), em-dashes (*—*), ellipsis (*…* as
  single codepoint U+2026), copy-paste artifacts from PDFs (soft
  hyphens U+00AD), and trailing source citations (`[1]`, `(via
  Twitter/X)`).
- [ ] **§10.1 step 3 widening.** Strip set extends to include:
  - Whitespace variants: `\xa0` (NBSP), `\u2007` (figure space),
    `\u202F` (narrow NBSP), `\u3000` (ideographic space) — all
    fold to ASCII space.
  - Soft-hyphen U+00AD: drop entirely (non-content; copy-paste
    artifact from PDF justification).
  - Quote canonicalization: `\u201C\u201D\u201E\u201F → "`,
    `\u2018\u2019\u201A\u201B → '` (and §10.22.2's apostrophe
    discipline already handled `\u02BC`).
  - Dash canonicalization: `\u2013\u2014\u2212 → -` (en-dash,
    em-dash, minus).
  - Ellipsis: `\u2026 → ...` (3 dots).
- [ ] **Determinism + idempotency.** All extensions tested by
  hypothesis property test; `normalize(normalize(x)) == normalize(x)`
  invariant from §10.1 must hold on the widened strip set
  (≥ 1000 examples, seed-pinned).
- [ ] **Length-cap ordering.** Strip extensions run AFTER length
  cap (per existing §10.1 step ordering — §10.1 step 1 is length
  cap, step 3 is strip). Boundary test
  `test_nlp_strip_runs_after_length_cap` asserts a 10000-char
  paste gets length-capped first (defends against attacker padding
  with millions of NBSPs hoping the strip will let it through).
- [ ] **Citation-tail stripper (closed enum).**
  `lang_tr/copy_paste/citation_tails.tr.yaml` with patterns
  `[via X], (via X), kaynak: X, source: X, [1], [2], (1), (2)`
  (anchored to end-of-string with optional whitespace). Stripped
  pre-classifier when `input_source=paste` OR detected
  heuristically (length ≥ 200 AND ends with one of the patterns).
  Stripped portion preserved in `request_metadata.stripped_tail`
  (for audit; never enters the answer).

#### 10.26.10 Football-specific bilingual vocabulary (extends §10.22.8)

- [ ] **Real gap.** §10.22.8 added a bilingual gazetteer pass for
  team / league names but football-specific *concept* vocab
  (positions, market types, in-game events, referee terms) lives
  in a half-Turkish half-English register that varies by media
  outlet and fan generation. *"Offside oldu mu?", "var kararı
  nedir?", "penaltı pozisyonu", "ekstra dakikalar / uzatma /
  added time"* all reach the classifier as code-switched and
  miss intent.
- [ ] **Closed football vocab table.** `lang_tr/football/vocab.tr.yaml`
  with schema `{canonical_concept, surface_forms_tr,
  surface_forms_en, register: media|fan|formal,
  intent_hint: optional}`. ~250 entries at v1 covering: position
  names (kaleci/keeper, defans/defender, ...), in-game events
  (gol, faul, ofsayt, korner, taç), market terms (handikap, çifte
  şans, alt/üst, karşılıklı gol/btts, ilk yarı, MS), referee
  terms (kırmızı kart, sarı kart, VAR, hakem, dördüncü hakem),
  competition events (devre arası, uzatma, penaltı atışları,
  tur atlama).
- [ ] **Resolver behaviour.** Each surface form maps to
  `canonical_concept` + optional `intent_hint` (e.g. *handikap* →
  intent_hint=`predict.handicap`; *btts* → `predict.btts`). The
  intent classifier (§10.4) is BIASED but not OVERRIDDEN — the
  hint becomes a fastText-input prefix marker
  `__concept_<canonical>__` that the model has been trained on.
  Hint without sufficient classifier confidence still abstains
  per §10.4 floor.
- [ ] **Bilingual abuse-token guard.** Some English football
  insults (*choke, bottle, parked the bus*) act as adversarial
  framing in TR queries about specific teams. Cross-reference
  with §10.22.9 offensive table — bilingual entries land in the
  same closed `offensive.tr.yaml` (kept single-source — vocab
  table never holds insults).
- [ ] **Build pipeline + governance.** Same two-reviewer
  `nlp-curator` rule as §10.25.6; added to CODEOWNERS scope.
  `make verify.nlp-football-vocab` AST-asserts: no entry
  duplicates a canonical_concept; every `intent_hint` resolves
  to a value in §10.4 closed enum.

#### 10.26.11 Empty / abuse-state observability (extends §10.24.13)

- [ ] **Real gap.** §10.24.13 handled the per-request empty-input
  floor but did NOT spec the cross-request anomaly signal. A
  spike of empty / single-char / pure-punctuation inputs from one
  `subject_key` (Phase 7 §7.6) is a behavioural fingerprint of
  abuse (script probing the floor; bot enumerating cost surface).
- [ ] **Per-subject empty-input rate gauge.** New
  `nlp_empty_input_rate_per_subject` histogram (cardinality
  bounded — top-K subjects only, per §10.14 PII discipline keys
  on `subject_key_sha8`, NOT raw subject). Anomaly detector:
  per-subject empty-rate > `cfg.nlp_empty_input_anomaly_threshold=0.3`
  over `cfg.nlp_empty_input_anomaly_window_s=300` AND
  per-subject request count ≥ 20 → emit
  `nlp.alert.v1{kind=nlp_empty_input_anomaly_per_subject,
  severity=warn}` (debounced 600s per subject).
- [ ] **Tier-blind by doctrine.** No tier-based exemption — alert
  fires on `account_paid` subjects same as anonymous (legitimate
  high-paid users do not produce 30%+ empty inputs in any
  observed corpus).
- [ ] **Boundary.** No automatic mitigation at NLP layer (rate-
  limit decisions live at Phase 7 sec gate). NLP only emits the
  signal; the §10.0 boundary discipline holds.

#### 10.26.12 Knob inventory addendum (extends §10.25.14)

`nlp_morph_topk=3`, `nlp_morph_min_confidence=0.55`,
`nlp_morph_context_radius=4`, `nlp_morph_ambiguous_max_per_query=4`,
`nlp_asr_filler_strip_max=6`, `nlp_diacritic_tie_break_ratio_voice=2.5`,
`nlp_ime_layout_cache_s=3600`, `nlp_lexicon_pr_max_added_rows_per_file=200`,
`nlp_lexicon_min_alias_appearances=3`, `nlp_answer_envelope_hmac_required=warn`,
`qa_answer_hmac_key_path`, `qa_answer_hmac_grace_s=86400`,
`nlp_empty_input_anomaly_threshold=0.3`,
`nlp_empty_input_anomaly_window_s=300`, plus 8 feature-flag
toggles (`nlp_morph_arbitration_enabled=true`,
`nlp_voice_path_enabled=true`, `nlp_ime_layout_aware_enabled=true`,
`nlp_temporal_polarity_routing_enabled=true`,
`nlp_modality_firewall_enabled=true`,
`nlp_correction_grammar_enabled=true`,
`nlp_long_paste_strip_extended_enabled=true`,
`nlp_football_vocab_hints_enabled=true`).

#### 10.26.13 New event / alert kinds (open-enum, mirrors §10.25.14 doctrine)

- `nlp.event.v1` kinds (debounced 60s unless noted):
  `morph_parse_ambiguous`, `morph_proper_noun_bypassed`,
  `asr_input_auto_detected`, `asr_filler_overflow`,
  `autocorrect_cascade_repaired`, `temporal_dst_crossed`,
  `temporal_polarity_routed_past`,
  `partial_number_disambiguation_offered`,
  `modality_routed_counterfactual`, `modality_routed_obligative`,
  `modality_routed_inferential_past`,
  `modality_routed_evidential_hearsay`,
  `conversation_correction_applied`,
  `conversation_restarted_by_user`,
  `paste_citation_tail_stripped`,
  `football_vocab_hint_emitted`.
- `nlp.alert.v1` kinds:
  `nlp_morph_ambiguity_rate_high` (warn; > 30% high-ambig over
  10min), `nlp_voice_path_diacritic_overaggressive` (warn; >
  20% restored on voice path), `nlp_lexicon_pr_diff_oversize`
  (warn; CI surface only — never user-facing),
  `nlp_lexicon_typo_squat_detected` (critical; CI surface),
  `nlp_lexicon_canonical_id_confusable_collision` (critical; CI
  surface), `nlp_answer_envelope_signature_invalid` (critical;
  Phase 9 emits, NLP receives via `maint.event.v1` for telemetry
  parity), `nlp_modality_x_temporal_contradiction` (warn; > 5%
  rate over 10min — model-quality regression signal),
  `nlp_empty_input_anomaly_per_subject` (warn; per-subject
  debounced 600s).
- `nlp.context.v1` (already exists per §10.25.1) — no schema
  change for §10.26.7 corrections; correction events are emitted
  out-of-band on `nlp.event.v1`.
- `qa.request.v1` schema_version 2→3 additive
  `request_metadata.input_source`, `request_metadata.keyboard_hint`.
- `qa.answer.v1` schema_version 2→3 additive
  `envelope_signature`, `body_canonical_sha`.

#### 10.26.14 Definition of Done additions (binding, on top of §10.25)

- [ ] All `[ ]` items in §10.26.1–§10.26.13 ticked.
- [ ] **§10.20 DoD item 24 added** — "All §10.26 ticks required."
- [ ] **~72 new proof tests** distributed:
  - §10.26.1 morphology: ≈ 14 (top-K, confidence floor, gazetteer
    cross-check, POS preference, co-token context, tie-break,
    proper-noun bypass, unparseable fall-through, ambiguity
    budget, determinism, parity, hypothesis-property, AST guard
    proper-noun, AST guard Go-no-morphology)
  - §10.26.2 ASR: ≈ 8 (auto-detect, filler strip happy + cap +
    abuse, relaxed split, diacritic loosening, capitalization
    short-circuit disabled, latency, voice-slice eval gate)
  - §10.26.3 IME: ≈ 7 (Q vs F lookup divergence, swipe,
    autocorrect cascade hit + miss, layout cache TTL, layout
    inference, AST optional-param, log-PII-hint-class-only)
  - §10.26.4 numeric/temporal: ≈ 9 (number-word bijection 0..9999
    sample, ordinal forms x3, fractional time x3,
    relative-temporal polarity, DST crossing, decimal-vs-thousands
    disambiguation, partial-number guard, AST guard past-routes-
    not-predict)
  - §10.26.5 modality: ≈ 6 (counterfactual route, inferential
    past, evidential hearsay, obligative refuse, epistemic OK,
    modal-x-temporal contradiction)
  - §10.26.6 lexicon supply-chain: ≈ 5 (PR diff cap, typo-squat
    detect, ortho-confusable canonical, alias provenance min-3,
    bot-impersonation refuse)
  - §10.26.7 correction: ≈ 5 (negation-of-prior, replacement,
    restart, false-positive corpus, AST guard
    no-correction-without-conversation-id)
  - §10.26.8 envelope HMAC: ≈ 5 (sign + verify happy, missing
    signature warn vs enforce, key rotation grace, cache-writer
    signs AST, gateway-verify boundary forward-contract)
  - §10.26.9 long-form paste: ≈ 6 (each whitespace variant,
    quotes, dashes, ellipsis, soft-hyphen, citation-tail,
    length-cap-ordering, hypothesis idempotency)
  - §10.26.10 football vocab: ≈ 4 (hint to classifier, abuse-
    bilingual via offensive table, build verify, intent_hint
    enum-membership)
  - §10.26.11 empty-input anomaly: ≈ 3 (rate trigger, debounce,
    AST guard no-mitigation-at-NLP-layer)
  - **Cumulative Phase 10: ≈ 390+ proof tests across §10.20 +
    §10.21 + §10.22 + §10.23 + §10.24 + §10.25 + §10.26.**
- [ ] **`make swarm.demo.nlp.full` extends** within ≤ 60s budget
  (tightening from §10.25 baseline) to exercise: (a) one
  morphologically ambiguous proper-noun input arbitrated via
  gazetteer cross-check; (b) one voice-path query with fillers
  stripped; (c) one autocorrect-cascade-repaired query; (d) one
  counterfactual-past query routed to `meta.counterfactual_unsupported`;
  (e) one paste-style input with citation-tail stripped; (f) one
  number-word year resolution; (g) one multi-turn correction;
  (h) one cache-served answer with envelope HMAC verified.
- [ ] **Chart compatibility additions.** Pin
  `tr_morph_freq.json` SHA, `keyboard_confusables.tr.yaml` source
  diagrams' SHA, `aspect_markers.tr.yaml` schema-version,
  `correction_markers.tr.yaml` schema-version, football vocab
  table SHA. No new third-party deps (all closed tables and
  pure-stdlib resolvers).
- [ ] **Documentation.** `docs/design/TURKISH_NLP.md` gains
  five new sections: "Morphological Arbitration", "Voice-to-Text
  Tolerance", "Mobile-IME Awareness", "Counterfactual & Modal-
  Aspect Firewall", "Output Envelope Integrity". `docs/guides/nlp_runbook.md`
  gains: "Morphology ambiguity-rate triage", "Voice-path
  diacritic-aggression triage", "Lexicon PR-flood incident
  response", "Envelope-HMAC key rotation".
- [ ] **Cross-phase contract updates.**
  - Phase 7 sec layer: no change (morphology is Python-only;
    boundary test asserts).
  - Phase 8 patcher scope: `nlp/lang_tr/modality/`,
    `nlp/lang_tr/correction/`, `nlp/lang_tr/numbers/`,
    `nlp/lang_tr/asr/`, `nlp/lang_tr/ime/`,
    `nlp/lang_tr/copy_paste/`, `nlp/lang_tr/football/` all
    EXCLUDED (mirrors §10.21.11) — language tables ship via human
    review, not auto-patch.
  - Phase 9 gateway: gains `qa.answer.v1` envelope HMAC
    verification (forward contract; Phase 9 §9.17.x picks up the
    obligation when implemented).
  - Phase 11 compute: morphological analyzer is CPU-only; AST
    guard rejects any `cuda` / `mps` import under `ai/nlp/morph/`.
  - Phase 13a LeagueCatalog: no change (morphology operates on
    surface forms; canonical IDs unchanged).
  - Phase 16 emitter: `LexiconStore` Protocol unchanged
    (morphology consumes the same lexicon snapshot).
  - Phase 19 long-tail leagues: morphology rules are language-
    level not league-level — no per-league branching introduced
    (AST guard `test_nlp_no_per_league_branch` from §10.0
    re-asserts on §10.26 code).
  - Phase 20 monetization: counterfactual + obligative refusals
    are tier-blind doctrine lines, not paywalls — explicit AST
    guard `test_nlp_modality_refusal_does_not_branch_tier`.
