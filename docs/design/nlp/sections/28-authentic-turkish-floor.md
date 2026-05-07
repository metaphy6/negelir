# Phase 10 §10.28 — Authentic-Turkish floor: orthographic, structural, resource discipline

> **Provenance.** Carved out of `docs/planning/ROADMAP.md` Phase 10 on the Phase 10 split (post-13th-pass) so the ROADMAP stays navigable. Content here is the **binding** Phase 10 contract; ROADMAP §10 now points at this folder. Any edit must update `xops/versioning/chart.json` (`docs` minor) and the tracker (per AGENTS.md §3 + §6.1). Cross-phase references (Phase 5/7/8/9/11/12/13a/14/16/19/20) remain authoritative against ROADMAP and the matching `docs/design/*.md` anchors.


### 10.28 Authentic-Turkish floor — orthographic, structural, and resource discipline (binding addendum)

> **Why this section exists.** §10.21–§10.27 hardened integrity, TR-language correctness,
> production serving, wrong-Turkish input completeness, lifecycle, morphology / modality,
> and match-lifecycle / abuse / regulatory. Eight passes still left **specific classes of
> authentically wrong Turkish** under-handled — failures that surface as *confidently
> wrong* (not gracefully degraded) answers when a real Turkish-speaker types fast,
> mis-spells per the orthographic rules native speakers actually break, concatenates
> words without spaces (mobile keyboard reality), shouts in ALL CAPS, pastes in a
> distractor preamble, embeds a TC kimlik no in their question, or otherwise hits a
> pathology no §10.x addendum has yet pinned. §10.28 is the **authentic-Turkish floor**:
> orthographic-rule tolerance (the rules native speakers most often break), structural
> robustness (no-space compounds, fragments, distractor preambles), TR-specific PII,
> and the resource-discipline guards (per-request CPU / memory budget, hot-reload
> back-pressure, cross-component skew detector) that keep the long pipeline honest
> under load. Every `[ ]` here is binding for Phase 10 DoD (per §10.20 item 26 added
> alongside this section).

#### 10.28.1 Consonant softening / vowel-drop tolerance (`ünsüz yumuşaması` + `ünlü düşmesi`)

- [ ] **Real bug.** §10.22.2 strips proper-noun suffixes correctly *when present*, but
  silently mishandles the inverse: real users type the unsoftened form (e.g.
  *"Beşiktaşın maçı"* instead of canonical *"Beşiktaş'ın maçı"*, or *"kitabı"* when
  they mean *"kitap+ı"*) **and** the softened-without-apostrophe form (*"futbolcunun
  ayağı"* vs erroneous *"ayagı"*). Lexicon hits miss because the surface form drifted
  one consonant.
- [ ] **Closed table** `ai/nlp/lang_tr/spelling/consonant_alternations.tr.yaml`:
  per-canonical-stem `{stem, final_char, soften_to, soften_blocked: bool, source:
  manual|tdk}`. AST-asserted CODEOWNER `nlp-curator`. Initial set = every
  LeagueCatalog team / player / city stem ending in `{p,ç,t,k}` plus the closed
  TR-orthography exception list (proper nouns ending in `{p,t,k}` whose softening
  is *blocked* by tradition — e.g. *"Tokat→Tokatın"* not *"Tokadın"*; *"Halit→Halitin"*
  not *"Halidin"*). Build refuses if any canonical from LeagueCatalog isn't in the
  table when its final char is in `{p,ç,t,k}` (forces explicit decision).
- [ ] **New §10.1 step 8b** `tolerate_consonant_alternation(token, lexicon_index)`
  AFTER §10.22 particle disambiguation, BEFORE typo correction. Two probes per
  unresolved token: *(a)* try softening the final consonant (`p→b, ç→c, t→d, k→ğ`)
  and re-lookup; *(b)* try un-softening if the surface form ends in `{b,c,d,ğ}` and
  the un-softened canonical exists. Cost ≤ 2 lookups (cheap; far below
  `nlp_typo_max_lookups_per_query`). Hit emits `nlp.event.v1{kind=consonant_softening_repaired}`
  debounced 60s.
- [ ] **`ünlü düşmesi` (vowel drop in 2-syllable nouns)** — *"akıl+ı"* → *"aklı"*,
  *"burun+u"* → *"burnu"*, *"şehir+i"* → *"şehri"*. Closed table
  `vowel_drop_stems.tr.yaml` with `{full_stem, dropped_form, suffix_pattern}`. Symspell
  index includes BOTH forms; canonical-id collapse via `_xref.py::validate_xref`
  ensures both surface forms map to the same canonical (build refuses on collision).
  AST `test_nlp_vowel_drop_round_trip` asserts every entry resolves bidirectionally.
- [ ] **Hard guard.** Never apply consonant softening / vowel drop to a token already
  in `_no_strip_canonicals.tr.yaml` (extends §10.22.4). Concretely: tokens *"Edirne",
  "Manisa", "Adana"* etc. must not be re-spelled; lookup hits before alternation.
- [ ] **Proof tests.** ≥ 30-row golden `consonant_alternation_corpus.tr.json` with
  1:1 expected canonical_id per surface form; CI gate 100%. Hypothesis property test
  ≥ 500 examples: `tolerate_consonant_alternation(canonical) == canonical` for every
  closed-table canonical (idempotency).

#### 10.28.2 Consonant assimilation tolerance (`ünsüz benzeşmesi / sertleşmesi`)

- [ ] **Real bug.** TR locative suffix `-de/-da` becomes `-te/-ta` after voiceless
  consonants (`p, ç, t, k, f, h, s, ş`); user-typed *"futbolda"* (correct) vs
  *"futbolta"* (wrong) vs *"galatasarayda"* (correct) vs *"galatasarayta"* (wrong)
  must all resolve to the same intent / entity. The §10.22.4 particle table only
  handles the orthographic *space* particle, not the suffixed assimilation form.
- [ ] **Closed table** `ai/nlp/lang_tr/spelling/assimilation_pairs.tr.yaml` —
  `{voiced: 'de|da|den|dan', voiceless: 'te|ta|ten|tan', triggers: [voiceless_consonants]}`.
  Two-way fold inside the §10.22.4 particle step: any `-te/-ta/-ten/-tan` after a
  vowel-final stem is folded back to `-de/-da/-den/-dan` for canonicalisation
  (purely a normalize step; the original surface form preserved in
  `entities[].original_text` per §10.21.5).
- [ ] **Symmetric: `-le/-la` → `-yle/-yla` after vowel-final stems.** Both surface
  forms map to one canonical instrumental marker.
- [ ] **Hard guard.** Never apply to tokens that are themselves dictionary entries
  (e.g. *"Nokta"* is a word, not *"Nok"+ta*). Lookup precedence: lexicon hit > particle fold.
- [ ] **Proof tests.** 40-row golden `assimilation_corpus.tr.json` covering both
  directions × 4 suffix families × 5 trigger consonants; CI 100%.

#### 10.28.3 No-space compound splitting (`birleşik yazım`)

- [ ] **Real bug.** Mobile fans drop spaces (autocorrect race, fat-finger): *"galatasarayfenerbahçe
  derbisi"*, *"liverpoolmanutd"*, *"tahminneolur"*. §10.22.7 match-pattern parser
  assumes whitespace separation; this slice silently mis-classifies as one
  unresolvable mega-token → `meta.unsupported`.
- [ ] **`compound_splitter.py`** — bounded recursive longest-prefix split against
  `(lexicon ∪ TR top-5k word-frequency)`; max 4 splits per token; max 1 application
  per query (no quadratic blow-up on adversarial input). Greedy with one-step
  backtrack only when the residual tail itself fails to lex. Cost ceiling
  `nlp_compound_split_max_lookups_per_query=24` enforced via shared budget with §10.3 typo.
- [ ] **Decision rule.** Only emit a split when *all* resulting parts resolve to
  lexicon entries OR top-1k frequency-table words. Partial coverage → discard split,
  preserve original token, fall through to typo correction. Avoids producing
  hallucinated entity pairs from random concatenations.
- [ ] **PII safety.** AST `test_nlp_compound_splitter_skips_pii_kinds` — never
  attempt to split a token already flagged by §10.28.4 PII detector (otherwise a
  concatenated TC kimlik no could be split into "harmless" digits and lose its
  PII flag).
- [ ] **Telemetry.** `nlp.event.v1{kind=compound_word_split, parts_count, applied_strategy}`
  debounced 60s/intent_class.
- [ ] **Proof tests.** ≥ 25-row corpus covering 2-, 3-, and 4-way splits; 100% gate.
  10-row negative corpus (genuine single-token: *"Galatasaraylılar"* must NOT split into
  *"Galatasaray+lılar"* because the residual is a valid TR suffix-form not a top-1k word).
  Adversarial 50-row `random_concatenation_flood.tr.json` ≥ 95% routed to
  `meta.unsupported` (NEVER hallucinated entities).

#### 10.28.4 TR-specific PII detector & redactor

- [ ] **Real bug.** §10.5 / §10.21.7 PII discipline catches `phone | email | credit-card`
  via generic patterns. Turkish users routinely embed **TC kimlik no** (11-digit,
  mod-10 + mod-11 checksum), **IBAN-TR** (`TR` + 24 digits + ISO-13616 mod-97 check),
  **Turkish mobile phone** (`+90 5XX` / `0 5XX` formats), **Turkish landline**
  (`0212/0216/0312` ...), **vehicle plate** (`34 ABC 1234`), **VKN** (10-digit tax id).
  None of these have TR-specific detectors today; KVKK Art 6/8 exposure on data-at-rest.
- [ ] **`ai/common/security/tr_pii.py`** (single source — Phase 7 sec layer also
  imports this; cross-language Go port mirrors via the §10.24.4 pattern). Detectors:
  `detect_tc_kimlik(text) -> [Span]` (regex `\b\d{11}\b` + checksum validate; first
  digit ≠ 0 + Σ-rule); `detect_iban_tr(text)` (regex `\bTR\d{2}\s?(\d{4}\s?){5}\d{2}\b` +
  mod-97 == 1); `detect_phone_tr(text)` (closed regex set covering `+90`, `0`, and
  10-digit forms with optional separators); `detect_plate_tr(text)` (`\b\d{2}\s?[A-ZÇĞİÖŞÜ]{1,3}\s?\d{2,4}\b`
  bounded, plate-number range 01-81); `detect_vkn(text)` (10-digit + Türkiye VKN
  algorithm).
- [ ] **Pipeline integration.** New §10.1 step 0.5 `redact_tr_pii` BEFORE length cap
  (oversized PII could otherwise be split across the cap boundary and one half slip
  through unredacted). Each detected span replaced with closed sentinel
  `[REDACTED:KIND:sha8=...]`; sha8 enables idempotent operator forensic recovery via
  the `make nlp.complaint-trace --confirm-pii` workflow (§10.27.3) without ever
  storing the raw PII at rest.
- [ ] **Per-kind alert.** Each detector hit emits `nlp.alert.v1{kind=nlp_pii_in_input_<kind>,
  severity=warn}` debounced per `(subject_key_sha8, kind)` for 600s. Aggregated
  daily by Phase 8 maint console.
- [ ] **Cross-language parity.** Phase 7 Go sec layer imports the same algorithm
  (port `server/internal/sec/tr_pii.go`); byte-parity test with the Python reference
  on a 200-row corpus (positives + negatives + boundary cases: 11-digit numbers that
  are NOT valid TC because checksum fails).
- [ ] **AST guards.** (a) `test_nlp_tr_pii_runs_before_length_cap` asserts step
  ordering. (b) `test_nlp_tr_pii_redacts_inplace_no_leak` walks every downstream
  payload (`qa.intent.v1`, `qa.answer.v1`, audit rows, spool envelopes, log strings)
  and asserts no surviving raw PII byte sequence with hypothesis ≥ 1000 examples.
  (c) `test_nlp_tr_pii_idempotent` — re-running detector on already-redacted text
  is a no-op.
- [ ] **Proof tests.** ≥ 60-row golden `tr_pii_corpus.json` (12 per kind × 5 kinds)
  with positive and adversarial-near-miss examples; CI 100%.

#### 10.28.5 Loan-word transliteration unification (`ofsayt/offside/ofsayd/ofsait`)

- [ ] **Real bug.** Football-specific bilingual vocab (§10.26.10) covered the
  *concept* table; doesn't address the *spelling-variant* problem where the same
  word has 3-5 attested Turkish-pronounced spellings (*"ofsayt"*, *"ofsait"*,
  *"offside"*, *"ofsayd"*, *"ofsayde"*). Symspell with edit-distance ≤ 2 over a
  single canonical may not reach all variants; some variants are edit-distance ≥ 3
  from the canonical.
- [ ] **Closed table** `ai/nlp/lang_tr/loanwords/transliteration_variants.tr.yaml` —
  `{canonical, variants: [...], domain: football|generic, source: corpus_freq>=N}`.
  Built via `make nlp.transliteration-build` from a frequency-curated TR football
  corpus + manual curation. Each variant is a primary alias in the lexicon; canonical
  is the resolution target. Bypasses Symspell entirely (deterministic table lookup
  is cheaper and more accurate for known variants).
- [ ] **AST guard `test_nlp_loanword_variants_dont_collide_across_domains`** —
  *"sayı"* is a Turkish word, not a transliteration of English *"si"*; build refuses
  if a variant string is also a TR top-1k frequency word in a different sense. Closed
  override file `_loanword_overrides.tr.yaml` for hand-arbitrated cases (e.g.
  *"set"* is both English *"set"* (volleyball) and TR *"set"* (collection); both
  uses retained, disambiguated by §10.5 co-token context).
- [ ] **Proof tests.** ≥ 40-row golden `loanword_corpus.tr.json` with 4-8 variants
  per canonical for football terms; 100% gate.

#### 10.28.6 Fragment / incomplete-sentence detection

- [ ] **Real bug.** Users hit Send by mistake or autocorrect drops the last word:
  *"Galatasaray ve"* (hanging conjunction), *"için"* (dangling postposition only),
  *"Beşiktaş maçı"* (subject only, no question). §10.24.13 handles single-char /
  empty / pure-greeting; this slice handles **structurally incomplete** fragments
  that have ≥ 2 tokens but no predicate.
- [ ] **`ai/nlp/lang_tr/fragments/`** — closed structural-pattern detector:
  *(a)* trailing conjunction (`ve, ile, veya, ya da, ama, fakat`); *(b)* trailing
  postposition (`için, gibi, kadar, ile, üzerine`); *(c)* missing verb particle
  (no question particle, no verb root, no inflected predicate); *(d)* nominal-only
  with no inflected suffix. Detection via Zemberek POS-tag tail check (pure
  `_NN_TRAILING / _CC_TRAILING / _PP_TRAILING` enums; AST guard `test_nlp_fragment_detector_uses_zemberek_only`
  rejects regex-based heuristics).
- [ ] **Routing.** Fragment → closed `meta.fragment_detected.<locale>.j2` template
  ("Sorduğunuz şey eksik kalmış görünüyor; tahmin mi, skor mu, kadro mu istiyorsunuz?")
  + entity hint of any partial canonical-resolved tokens ("Galatasaray"). NEVER guesses
  the missing predicate.
- [ ] **False-positive guard.** Closed allow-list for legitimate fragment-shaped
  queries that are actually complete in spoken TR (*"Galatasaray nasıl?"*, *"Skor?"*).
  Allow-list source: 30-row hand-curated `fragment_negative_corpus.tr.json`; CI
  100% pass-through.
- [ ] **Proof tests.** ≥ 25 fragment positives + 30 negative; FP rate ≤ 3%.

#### 10.28.7 Distractor-preamble stripping

- [ ] **Real bug.** Voice / paste / mobile users routinely prepend distractor
  preambles before the actual question: *"merhaba arkadaşlar bakın bence Galatasaray
  bu hafta kazanır mı?"*. §10.24.13 handles *pure* greetings (no payload after);
  doesn't strip a greeting / vocative preamble before a real question. Result:
  classifier confidence drops because the prefix dilutes the intent signal.
- [ ] **`preamble_strippers.tr.yaml`** — closed phrase set (≤ 200 entries):
  greeting families (`merhaba|selam|slm|meraba|kolay gelsin|iyi günler`),
  attention-grab (`bakın|baksanıza|bak ya|ya|şey|peki`), vocative
  (`arkadaşlar|hocam|abi|reis|kanka|dostum`), filler-opinion
  (`bence|bana göre|şahsen|valla|yani`). Each entry MUST be ≤ 3 tokens; longer
  phrases → REFUSE build (defends against poisoned-table attacks via overlong
  patterns).
- [ ] **New §10.1 step 6.7** `strip_preamble` AFTER ASR-filler strip (§10.26.2)
  BEFORE morphology. Cap = `nlp_preamble_max_strip_tokens=8` per query (defends
  against unbounded chained preambles); over-cap → emit
  `nlp.event.v1{kind=preamble_strip_capped}` and short-circuit.
- [ ] **Hard guard.** Never strip if the resulting tail has < 2 tokens (would
  collapse a vocative-only message to empty; §10.24.13 owns that path). AST
  `test_nlp_preamble_does_not_collapse_to_empty`.
- [ ] **Audit invariant.** Original full text preserved in spool / audit rows
  per §10.21.7 PII discipline; only the *classifier input* is the stripped form.
- [ ] **Proof tests.** ≥ 25-row corpus (preamble + real question pairs) — assert
  intent-confidence on the stripped form ≥ confidence on the raw form for ≥ 90% of
  the corpus (correctness signal); 10-row negative corpus where stripping must NOT
  fire (legitimate messages that begin with stripped-table words but use them as
  the entity, e.g. *"Selam'ın gol attığı maç"*).

#### 10.28.8 ALL-CAPS / shout normalization

- [ ] **Real bug.** *"GALATASARAY KAZANIR MI BU HAFTA?"* — fully valid TR question,
  but Symspell + Zemberek + lexicon all index lowercase forms; §10.1 step 4 lowers
  via the explicit Turkish-aware fold. The drop is silent. However, ALL-CAPS is
  *also a signal*: §10.5 entity disambiguation should not use Turkish capitalization
  as a weak entity-hint when the entire message is uppercase (everything looks like
  a proper noun — false positives explode).
- [ ] **`detect_all_caps(text) -> bool`** — ratio of uppercase letters to total
  letters ≥ `nlp_all_caps_threshold=0.85` AND total letters ≥ 4. Flag stored as
  `request_metadata.shout=true`. Pipeline behaviour: lowercase as normal (no change
  to §10.1 step 4); §10.5 capitalization-as-hint feature **disabled** when
  `shout=true` (entity resolution falls back to gazetteer + co-token only — same
  behaviour §10.26.2 voice path uses).
- [ ] **Telemetry.** `nlp_input_shout_total` counter; over-pressure
  (`shout_rate_per_subject > 0.5` over 5min, AND req_count ≥ 20) emits
  `nlp.alert.v1{kind=nlp_shout_rate_anomaly_per_subject, severity=warn}` debounced
  600s/subject. Tier-blind (per AGENTS.md monetization doctrine).
- [ ] **Output policy.** NEVER mirror shouting in the answer; templates are
  fixed-case. AST `test_nlp_template_renderer_does_not_propagate_shout` asserts no
  template branches on `shout`.
- [ ] **Proof tests.** ≥ 15-row corpus (clean shouts that should still resolve), ≥
  10-row negative (mostly-uppercase but punctuation-mixed must NOT trigger), ≥ 5-row
  edge cases (1-letter messages, no-letter messages must not divide-by-zero).

#### 10.28.9 Soft-g (`yumuşak g`) loss tolerance

- [ ] **Real bug.** TR `ğ` is hard to type on some IMEs / disappears in fast typing /
  is dropped by Latin transliteration tools: *"yaptıgını"* → *"yaptığını"*,
  *"degil"* → *"değil"*, *"sagol"* → *"sağol"*. Diacritic restoration (§10.3) covers
  the dotted-letter family but not the standalone `g↔ğ` swap (which §10.22.1
  weighting downplays as "low risk" — wrong for `ğ`-stem proper nouns where the
  difference is meaningful).
- [ ] **Closed `g_to_softg.tr.yaml`** — corpus-derived list of words where `g→ğ`
  swap produces a dictionary form (`degil→değil, dogru→doğru, agac→ağaç,
  yagmur→yağmur, sagol→sağol`). Build refuses if any entry's swap produces an
  ambiguous resolution (multiple canonicals); ambiguous cases go through
  context-disambiguation per §10.5.
- [ ] **Pipeline integration.** §10.1 step 6 (diacritic restore) extends with a
  dedicated `softg_restore` sub-pass keyed off this table; never folds blindly
  every `g`. Risk-weighted per §10.22.1 (`nlp_diacritic_softg_min_freq=500`).
- [ ] **Proof tests.** ≥ 30-row corpus; CI 100%; ≥ 15-row negative (words like
  *"gol"*, *"galatasaray"*, *"genç"* must NOT have `g→ğ` applied).

#### 10.28.10 Meta / rhetorical / non-answerable question routing

- [ ] **Real bug.** *"Sen ne biliyorsun ki?"*, *"yardım edebilir misin?"*,
  *"sen kimsin?"*, *"ne yaparsın?"* — these are not predict.* / data.* questions;
  they are meta-questions about the system. §10.4 closed enum has `meta.help`,
  `meta.unsupported`, `meta.adversarial` — under-utilised for the rhetorical
  / system-self questions class. Result: the rhetorical *"ne diyorsun lan?"*
  (rude rhetorical, NOT a request) routes to `data.h2h` (because of *"diyorsun"*)
  and produces a confidently wrong answer.
- [ ] **`meta_questions.tr.yaml`** — closed enumeration of rhetorical /
  system-self / non-answerable patterns split into 3 classes: `meta.system_self`
  (asking what the bot is / can do), `meta.rhetorical_dismissive` (rude rhetorical
  with no real intent), `meta.opinion_request` (asking the bot's opinion outside
  prediction; routed to a polite refusal — bot does not opine outside predict.*).
  Each entry is a fixed phrase or a closed Zemberek POS-pattern; AST rejects regex
  heuristics. Closed table size cap `nlp_meta_question_table_max=500`.
- [ ] **Routing override.** Detection happens AFTER §10.26.5 modality firewall but
  BEFORE intent classifier. Hit short-circuits to the matching `meta.*` template;
  classifier never sees the message (defends against "what do you think" leaking
  into `predict.*`).
- [ ] **Tier-blind.** Refusal templates are tier-blind (free + paid both get the
  polite refusal). AST `test_nlp_meta_questions_tier_blind`.
- [ ] **Proof tests.** ≥ 40-row golden across 3 classes; CI 100%; ≥ 15-row
  negative (genuine predict / data queries that contain meta-question-shaped
  fragments must NOT route to meta.*).

#### 10.28.11 Per-request CPU + memory budget enforcement

- [ ] **Real bug.** Worst-case combinatorial blow-up: §10.1 normalize + §10.3
  Symspell + §10.4 fastText + §10.5 Zemberek + CRF + §10.7 template render +
  §10.8 humanizer can stack, especially under §10.24.5 multi-subquery split (3
  subqueries × full pipeline). §10.0 timeout-chain inequality bounds wall-clock
  but does NOT bound CPU-seconds or RSS — a runaway query can pin a CPU core
  without exceeding wall-clock if the pod is contended.
- [ ] **`ai/nlp/runtime/budget.py`** — `RequestBudget` context manager:
  *(a)* `signal.setitimer(ITIMER_PROF, nlp_per_request_cpu_budget_ms / 1000)` on
  entry; SIGPROF handler raises `BudgetExceeded` (CPython only — AST guard
  `test_nlp_budget_signal_main_thread_only` rejects use under sub-thread); *(b)*
  `resource.setrlimit(RLIMIT_AS, current_rss + nlp_per_request_rss_budget_mb*1024**2)`
  on entry — process-wide cap raised on exit; *(c)* monotonic wall-clock check at
  every pipeline boundary as a backup.
- [ ] **Default budgets** (cfg-tunable). `nlp_per_request_cpu_budget_ms=200`
  (no humanizer) / `=800` (with humanizer); `nlp_per_request_rss_budget_mb=128`.
  Boot-time refuses if budgets are below `cfg.nlp_per_request_cpu_budget_min_ms=50`
  (defends against accidental zeroing).
- [ ] **Budget exhaustion → degraded path.** `BudgetExceeded` at any pipeline
  stage → fall-through to template-only with `degraded_reason=cpu_budget_exceeded`
  / `rss_budget_exceeded`; emits `nlp.alert.v1{kind=nlp_request_budget_exhausted,
  severity=warn}` debounced per stage 60s. NEVER returns 5xx (per §10.10
  graceful-degradation matrix invariant).
- [ ] **Subprocess discipline.** Humanizer (§10.25.11) runs in a subprocess
  already; subprocess inherits a separate `setrlimit` budget per spawn. Subprocess
  OOM → supervisor catches `BudgetExceeded` and treats as humanizer breaker open
  (§10.8 path, no new alert kind needed).
- [ ] **Proof tests.** *(a)* `test_nlp_runaway_normalize_cpu_budget_kicks` —
  inject a synthetic Symspell-pathological token; assert `BudgetExceeded` raised
  within `cpu_budget_ms × 1.5` (allows one pipeline step grace). *(b)*
  `test_nlp_rss_budget_kicks_on_lexicon_pathological_load` — synthetic 200MB
  allocation inside a normalize step; assert raised. *(c)* parametrized matrix
  covering 5 pipeline stages × 2 budget kinds (CPU / RSS) = 10 cases. *(d)*
  `test_nlp_budget_does_not_fire_on_clean_query` — 1000 representative clean
  queries, none exceed budget on a 2-vCPU container (CI gate, parametrised by
  `nlp_per_request_cpu_budget_ms`).

#### 10.28.12 Symspell / CRF hot-reload back-pressure

- [ ] **Real bug.** §10.21.2 specifies "Symspell rebuilt-not-mutated on swap" but
  doesn't bound *how many* concurrent rebuilds may run. A 6-file `nlp.lexicon-deploy`
  (§10.27.9) can fan out to 6 simultaneous Symspell rebuilds across pods; under
  high-QPS the rebuild pulls 50-200 MB transiently, racing the per-request RSS
  budget (§10.28.11). Result: false-positive RSS exhaustion alerts during a
  legitimate lexicon swap.
- [ ] **`nlp_lexicon_rebuild_concurrency_max=2`** — at most 2 of {teams, players,
  leagues, competitions, markets, dialects} may be rebuilding simultaneously per
  pod; remainder queue (FIFO; bounded queue cap `=8`; over-cap drops oldest +
  emits `nlp.alert.v1{kind=lexicon_rebuild_queue_overflow, severity=error}` —
  rare; means deploy cadence outpacing per-pod CPU budget).
- [ ] **Rebuild RSS reservation.** Each in-flight rebuild reserves
  `nlp_lexicon_rebuild_rss_reservation_mb=200` against the pod's `RLIMIT_AS`
  headroom; insufficient headroom → defer the rebuild (queue) and emit
  `nlp.event.v1{kind=lexicon_rebuild_deferred_for_rss}`. Defends §10.28.11 budget
  against the swap edge.
- [ ] **Per-request budget exception during swap.** Requests landing during an
  active rebuild get a one-time `nlp_per_request_rss_budget_swap_grace_mb=64`
  bonus on top of the normal budget, capped at `nlp_lexicon_swap_grace_s=120`
  window after the swap (§10.27.9 already gates the swap window). Cleanly avoids
  a flap of false `cpu_budget_exceeded` alerts during a normal deploy.
- [ ] **Proof tests.** *(a)* `test_nlp_lexicon_concurrent_rebuild_capped_at_two` —
  trigger 6 simultaneous rebuilds; assert at most 2 active, others queued. *(b)*
  `test_nlp_request_grace_during_lexicon_swap_window` — issue normal-load requests
  during a synthetic swap; assert no `cpu_budget_exceeded` fires.

#### 10.28.13 Cross-component classifier-vs-extractor confidence skew detector

- [ ] **Real bug.** §10.4 abstention floor + §10.5 entity ambiguity each fire
  independently. The pathological *both-confident-but-disagreeing* case has no
  guard: classifier says `predict.match_outcome` with conf=0.93 but extractor
  resolves zero `team` entities. Today: dispatcher emits a `disambiguation`
  answer, but no observability surfaces the silent contradiction → drift goes
  unnoticed across calibration cycles.
- [ ] **`SkewDetector`** in `nlp.dispatcher.v1`: per-decision compute
  `skew_score = max(0, intent_confidence - entity_coverage_ratio)` where
  `entity_coverage_ratio = (resolved_entity_kinds_required_by_intent /
  required_kinds)`. Required-kinds map per intent in
  `intent_required_entities.tr.yaml` (closed; CODEOWNER `nlp-curator`); e.g.
  `predict.match_outcome` requires `{team(2), kickoff_or_recent}`,
  `data.kickoff_time` requires `{team(2)}`, `meta.help` requires `{}` (no
  required kinds → skew always 0).
- [ ] **Telemetry only at v1.** Histogram `nlp_classifier_extractor_skew` per
  intent; rolling window `nlp_skew_window_s=600` p95 > `nlp_skew_alert_p95=0.4`
  on req_count ≥ 100 → `nlp.alert.v1{kind=nlp_classifier_extractor_skew_high,
  severity=warn}` debounced 600s/intent. NEVER changes routing decision at v1
  (would risk hard-coding a noisy gate); the dispatcher continues with
  disambiguation-fallback per §10.6. Forward-phase hook for Phase 5.x retraining
  loop to consume this signal.
- [ ] **Proof tests.** *(a)* `test_nlp_skew_detector_fires_on_synthetic_skew` —
  inject classifier_conf=0.95 + zero entities for `predict.*`; assert one alert
  after window. *(b)* `test_nlp_skew_detector_silent_on_meta_intents` —
  meta intents always 0 skew. *(c)* `test_nlp_skew_does_not_change_routing` —
  parametrised 50-row corpus; routing decisions identical with detector enabled
  vs disabled.

#### 10.28.14 Cross-phase contracts

- [ ] **Phase 4 (storage).** §10.28.4 PII redaction runs BEFORE storage of any
  audit / spool row; storage layer never sees raw TC kimlik / IBAN / phone.
  Boundary test (Phase 4 side): `test_storage_no_unredacted_tr_pii_at_rest`
  walks a synthetic day's audit rows and asserts zero raw matches against the
  TR-PII regex set.
- [ ] **Phase 5 (calibration).** Skew detector (§10.28.13) emits histogram
  consumed by Phase 5.x retraining trigger heuristic; not a hard dependency, no
  schema change at v1.
- [ ] **Phase 7 (sec layer).** TR-PII detector module (`tr_pii.py`) is
  cross-language single-source; Go sec layer imports the byte-equivalent port
  per §10.24.4 helper-sharing pattern. Boundary test asserts byte-parity on a
  200-row corpus across Python and Go drivers.
- [ ] **Phase 8 (patcher).** Patcher scope EXCLUDES `ai/nlp/lang_tr/spelling/`,
  `ai/nlp/lang_tr/loanwords/`, `ai/nlp/lang_tr/fragments/`,
  `ai/nlp/lang_tr/preamble_strippers.tr.yaml`,
  `ai/nlp/lang_tr/meta_questions.tr.yaml`,
  `ai/common/security/tr_pii.py` — orthographic and PII tables ship via human
  review; auto-patch could ship a regression that mis-classifies a real PII
  pattern as benign. Boundary test (Phase 8 side): patcher scope-registry walk.
- [ ] **Phase 9 (gateway).** Gateway honours the `request_metadata.shout`
  flag forwarded in `qa.intent.v1` for telemetry only; no header surface.
- [ ] **Phase 11 (compute).** §10.28.11 budget module is CPU-only; AST guard
  `test_nlp_budget_module_does_not_import_torch` re-asserts. The skew detector
  (§10.28.13) is also CPU-only.
- [ ] **Phase 12 (chaos).** New stubs:
  `chaos.tr-pii-flood` (assert TR-PII detector p99 latency < `nlp_tr_pii_p99_max_ms=15`
  under 200 RPS of PII-bearing input);
  `chaos.compound-flood` (assert §10.28.3 compound splitter does NOT exceed
  shared lookup budget under 1000 RPS of synthetic concatenated tokens);
  `chaos.lexicon-rebuild-storm` (6 simultaneous rebuilds + 200 RPS — assert
  zero false-positive `cpu_budget_exceeded` per §10.28.12 grace);
  `chaos.runaway-normalize` (synthetic Symspell-pathological corpus — assert
  100% caught by §10.28.11 CPU budget, zero pod OOMs).
- [ ] **Phase 13a (LeagueCatalog).** §10.28.1 consonant-alternation table
  build refuses if any LeagueCatalog stem ending in `{p,ç,t,k}` is missing a
  decision row. Forces explicit human curation when a new league lands.
- [ ] **Phase 14 (K8s).** No new probes; §10.28.11 budget exhaustion does NOT
  fail liveness (degraded path is graceful per §10.10). Readiness is unaffected.
- [ ] **Phase 16 (Emitter).** `LexiconStore` Protocol unchanged; new tables
  (`consonant_alternations`, `vowel_drop_stems`, `assimilation_pairs`,
  `loanword_variants`, `g_to_softg`, `meta_questions`, `preamble_strippers`,
  `intent_required_entities`) flow through the same Protocol.
- [ ] **Phase 19 (long-tail leagues).** All §10.28 tables grow additively per
  league; AST `test_nlp_no_per_league_branch` re-asserts on the new code surface.
- [ ] **Phase 20 (monetization).** All §10.28 paths are tier-blind (orthographic
  tolerance, PII redaction, fragment detection, preamble stripping, meta-question
  refusal, budget enforcement, skew detection — none gate on tier). Three
  explicit AST guards: `test_nlp_consonant_alternation_tier_blind`,
  `test_nlp_meta_question_tier_blind`, `test_nlp_request_budget_tier_blind`.

#### 10.28.15 Knob inventory + new event / alert kinds + DoD

- [ ] **~24 new cfg knobs** (additive, documented in `xops/env/.env.example`,
  Triangle-test extends): `nlp_compound_split_max_lookups_per_query=24`,
  `nlp_all_caps_threshold=0.85`, `nlp_diacritic_softg_min_freq=500`,
  `nlp_meta_question_table_max=500`, `nlp_preamble_max_strip_tokens=8`,
  `nlp_per_request_cpu_budget_ms=200`,
  `nlp_per_request_cpu_budget_humanize_ms=800`,
  `nlp_per_request_cpu_budget_min_ms=50`,
  `nlp_per_request_rss_budget_mb=128`,
  `nlp_lexicon_rebuild_concurrency_max=2`,
  `nlp_lexicon_rebuild_queue_max=8`,
  `nlp_lexicon_rebuild_rss_reservation_mb=200`,
  `nlp_per_request_rss_budget_swap_grace_mb=64`,
  `nlp_skew_window_s=600`, `nlp_skew_alert_p95=0.4`,
  `nlp_tr_pii_p99_max_ms=15`,
  plus 8 feature-flag toggles (`nlp_consonant_alternation_enabled=true`,
  `nlp_assimilation_fold_enabled=true`, `nlp_compound_split_enabled=true`,
  `nlp_tr_pii_redact_enabled=true`, `nlp_loanword_variants_enabled=true`,
  `nlp_fragment_detection_enabled=true`, `nlp_preamble_strip_enabled=true`,
  `nlp_meta_question_routing_enabled=true`).
- [ ] **New `nlp.event.v1` kinds**: `consonant_softening_repaired`,
  `vowel_drop_repaired`, `assimilation_folded`, `compound_word_split`,
  `loanword_variant_resolved`, `fragment_detected`, `preamble_strip_capped`,
  `softg_restored`, `meta_question_routed_<class>` (3 sub-kinds),
  `lexicon_rebuild_deferred_for_rss`.
- [ ] **New `nlp.alert.v1` kinds**: `nlp_pii_in_input_tc_kimlik`,
  `nlp_pii_in_input_iban`, `nlp_pii_in_input_phone`, `nlp_pii_in_input_plate`,
  `nlp_pii_in_input_vkn` (5 PII alert kinds, all warn-debounced per
  `(subject_key_sha8, kind)` 600s); `nlp_shout_rate_anomaly_per_subject` (warn);
  `lexicon_rebuild_queue_overflow` (error);
  `nlp_request_budget_exhausted` (warn, per-stage debounced);
  `nlp_classifier_extractor_skew_high` (warn, per-intent debounced).
- [ ] **~70 new proof tests** on top of §10.20+§10.21+§10.22+§10.23+§10.24+§10.25+§10.26+§10.27
  baseline; cumulative Phase 10 ≈ **535+ tests**. `make swarm.demo.nlp.full`
  extends ≤ 60s covering all 13 §10.28 paths (one positive + one negative per
  sub-section).
- [ ] **`make nlp.transliteration-build`** (NEW xops target) regenerates
  loanword-variants table; CI gate refuses PR diffs > 50 rows without
  `nlp-curator` CODEOWNER ack.
- [ ] **CODEOWNERS additions**: every new YAML under `ai/nlp/lang_tr/spelling/`,
  `ai/nlp/lang_tr/loanwords/`, `ai/nlp/lang_tr/fragments/`,
  `ai/nlp/lang_tr/preamble_strippers.tr.yaml`,
  `ai/nlp/lang_tr/meta_questions.tr.yaml`,
  `ai/nlp/lang_tr/intent_required_entities.tr.yaml`,
  `ai/common/security/tr_pii.py` requires `nlp-curator` (orthographic) +
  `nlp-compliance` (PII-related) reviewer. `make verify.nlp-codeowners`
  CI-gated.
- [ ] **Versioning.** `swarm` minor (or patch if no public surface change),
  `docs` minor in same commit. Chart compatibility block re-pinned (no new
  deps; pure-Python `signal` / `resource` / Zemberek already pinned).
- [ ] **Tracker row + ROADMAP checkbox flips** per AGENTS.md §3 + §3.4 — every
  checkbox in §10.28.1–§10.28.15 flipped to `[x]` at landing, with the §10.20
  DoD item 26 also flipped.
