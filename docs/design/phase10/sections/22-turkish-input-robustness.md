# Phase 10 §10.22 — Turkish-language input robustness ('messy Turkish' floor)

> **Provenance.** Carved out of `docs/planning/ROADMAP.md` Phase 10 on the Phase 10 split (post-13th-pass) so the ROADMAP stays navigable. Content here is the **binding** Phase 10 contract; ROADMAP §10 now points at this folder. Any edit must update `xops/versioning/chart.json` (`docs` minor) and the tracker (per AGENTS.md §3 + §6.1). Cross-phase references (Phase 5/7/8/9/11/12/13a/14/16/19/20) remain authoritative against ROADMAP and the matching `docs/design/*.md` anchors.


### 10.22 Turkish-language input robustness (binding addendum — "messy Turkish" floor)

> **Why this addendum exists.** §10.1–§10.21 build a deterministic,
> integrity-clean pipeline. They do **not** by themselves guarantee that
> real-world Turkish input — typed on a US keyboard with no diacritics,
> in colloquial register, with attached/detached `de`/`da`/`ki`/`mi`
> particles in the wrong places, with omitted apostrophes on proper-noun
> suffixation, mixed with English brand and league names, abbreviated
> ("GS-FB", "RM"), or written in regional dialect — is parsed correctly.
> §10.22 is the binding **language-quality floor**: any Phase 10
> deployment that ships without these gates may pass §10.21 hardening
> tests yet still mis-route the median Turkish football fan's query.
>
> **Doctrine reminder.** Per AGENTS.md Rule 4 (smallest model that
> works) and CLAUDE.md (no LLM in decision paths), every rule below is
> **deterministic** — table-driven, tokenizer-driven, regex-driven, or
> CRF-feature-driven. The humanizer LLM (§10.8) **never** participates
> in the input-understanding side of the pipeline. The §10.4 fastText
> classifier is the only ML in the input path, and §10.21.1 already
> pinned its determinism floor. Everything in §10.22 hardens the
> deterministic path **before** the classifier sees the text.
>
> **Single source for the rules.** Every table referenced below lives
> at `ai/nlp/lang_tr/` (NEW directory created in this phase): one YAML
> per rule family, frozen-via-SHA, hot-reloadable through the same §10.2
> atomic-swap mechanism (extended to cover this directory in
> §10.22.14). LeagueCatalog (Phase 13a) remains the sole source of
> canonical team / league / competition / player names — §10.22 only
> adds **how the user might spell those names wrong** and how to recover
> the canonical form.

#### 10.22.1 ASCIIfication tolerance (no-diacritic Turkish input)

- [x] **Real failure mode §10.3 underspecifies.** Default Turkish PC users
  type without `ç ğ ı ö ş ü` (and almost never the rare `â î û`):
  *"galatasaray fenerbahce maci tahmin"*, *"besiktas trabzon ne zaman
  oynuyor"*, *"unlu santrforun cezasi var mi"*. The diacritic-restore
  table in §10.3 is real but the **integration contract** is missing:
  what happens when a token has multiple plausible restorations
  (*"sik" → "şık"* or *"sık"*; *"ucu" → "üçü"* or *"ucu"*), and how
  does the gazetteer behave under restored vs unrestored ambiguity.
- [x] **Two-stage restoration policy.** §10.3 already pins the
  frequency-tie-break ratio (`cfg.nlp_diacritic_tie_break_ratio=1.5x`).
  §10.22.1 pins the **integration**: (a) gazetteer pass (§10.5) runs
  **twice** — first against the raw-ASCIIfied lexicon (every alias is
  also stored in its `unidecode`d form via the build pipeline of §10.2),
  then against the restored form; (b) longest-non-overlapping match
  across both passes; (c) if both passes hit different canonicals,
  prefer the restored-form hit ONLY when its frequency-weighted
  confidence exceeds the ASCII hit by `cfg.nlp_ascii_vs_restored_margin=0.2`.
- [x] **ASCIIfied alias index built at lexicon-load.** `make nlp.lexicon-build`
  emits a sibling `*.tr.ascii.idx` per lexicon file: `dict[ascii_alias →
  list[(canonical_id, original_alias, frequency_score)]]`. Conflict
  exposed at build time: when two different canonicals share an
  ASCIIfied alias (*"saray"* maps to "Galatasaray" and "Bağdat Sarayı"),
  build refuses unless an `entities_negative.tr.yaml` rule covers the
  ambiguity. Operator either resolves the disambiguator or accepts an
  explicit allow-list entry in `ai/nlp/lexicon/_ascii_collisions.tr.yaml`.
- [x] **Hard-call vs soft-call restoration.** Tokens with frequency >
  `cfg.nlp_diacritic_hard_call_min_freq=10000` (per `tr_word_freq.txt`)
  → restore even when ratio fails (the dominant form is overwhelmingly
  correct: *"futbol" never means anything else*). Below threshold →
  preserve original + flag to entity resolver.
- [x] **Per-character risk scoring.** Some letter swaps are far more
  ambiguous than others (*"i↔ı"* loses information; *"u↔ü"* often
  preserves meaning; *"o↔ö"* shifts vowel class which can break suffix
  harmony downstream). Restoration policy carries a per-character risk
  weight from `ai/nlp/lang_tr/diacritic_risk.tr.yaml`; total token risk
  > `cfg.nlp_diacritic_max_risk_per_token=2.5` → keep ASCII form even
  if a single restoration is unique.
- [x] **Proof:** `test_nlp_ascii_pass_resolves_galatasaray_no_diacritics`
  (corpus 100 queries), `test_nlp_ascii_collision_build_refuses_without_allowlist`,
  `test_nlp_diacritic_restore_prefers_high_freq_form`,
  `test_nlp_diacritic_high_risk_token_keeps_ascii`,
  `test_nlp_double_pass_gazetteer_picks_longer_match` (parameterized 20 cases).

#### 10.22.2 Apostrophe discipline on proper-noun suffixation

 [x] **Real failure mode.** Turkish writes proper-noun + suffix with an
  apostrophe (*"Galatasaray'ın"*, *"Real Madrid'e"*), but users
  routinely omit it (*"Galatasarayın"*, *"Real Madride"*) or place it
  wrongly (*"Galata'sarayın"*, *"Realmadrid'in"*). §10.5 gazetteer
  and §10.7 `match_label`/`team` filter renders the OUTPUT incorrectly
  if the apostrophe rule isn't applied symmetrically.
- [x] **Input-side suffix-stripper.** Pre-gazetteer step:
  `ai/common/text/turkish.py::strip_proper_noun_suffix(token)` returns
  `(stem, suffix_class)` for any token matching the pattern
  `^[A-ZÇĞİÖŞÜ][^']*('?)([a-zçğıiöşü]{1,4})$` where the trailing 1–4
  lowercase chars match a known suffix family (genitive, dative,
  accusative, locative, ablative, plural, person-marker). The stripped
  stem is what goes through the gazetteer; the suffix is preserved as
  a slot annotation `entities[].grammatical_suffix` so the answer
  generator (§10.7) can reproduce it correctly.
- [x] **Output-side filter discipline.** Every Jinja2 morphology filter
  (`dative`, `accusative`, `locative`, `ablative`, `genitive`) MUST
  inject the apostrophe when the stem is in the proper-noun set
  (LeagueCatalog teams + leagues + players + competitions + venues).
  Filter signature changes from `dative(name)` to `dative(name,
  proper=False)`; `match_label` / `team` filters auto-set
  `proper=True`. AST guard `test_nlp_morph_filters_set_proper_for_canonical_entities`
  asserts every emit site uses the right flag.
- [x] **Foreign-stem apostrophe rule.** Non-Turkish proper nouns ending
  in a consonant cluster that doesn't match Turkish vowel harmony
  (*"Manchester City"*, *"Bayern"*, *"PSG"*) MUST always carry the
  apostrophe before the suffix; the rule is "if last vowel of stem is
  ambiguous in TR vowel-class system, use back-vowel suffix and
  apostrophe" (e.g., *"PSG'ye"* not *"PSG'ye"*-with-front-vowel). Table
  at `ai/nlp/lang_tr/foreign_stem_overrides.tr.yaml` overrides the
  vowel-harmony default per known stem (covers ~200 frequent foreign
  team / league names; build refuses if an entry doesn't resolve to a
  LeagueCatalog canonical).
- [x] **Apostrophe-noise tolerance.** Input may contain typographic
  apostrophes `'`, `'`, `'`, `` ` ``, `´` — §10.1 step 5 normalizes
  to ASCII `'`. AST guard asserts `'` is the only apostrophe character
  reaching the suffix-stripper.
- [x] **Proof:** `test_nlp_strip_suffix_recovers_galatasarayin_to_galatasaray`,
  `test_nlp_strip_suffix_recovers_realmadride_to_real_madrid`,
  `test_nlp_morph_filter_renders_apostrophe_for_proper_noun`
  (20-case golden table including *"Manchester City'nin"*, *"PSG'ye"*,
  *"Trabzonspor'a"*), `test_nlp_apostrophe_normalization_to_ascii`,
  `test_nlp_foreign_stem_overrides_resolve_to_catalog`.

#### 10.22.3 Buffer-consonant renderer (-y / -n / -s / -ş)

- [x] **Real failure mode.** When a Turkish suffix beginning with a
  vowel (`-a`, `-e`, `-ı`, `-i`, `-u`, `-ü`) attaches to a stem ending
  in a vowel, a buffer consonant is required: `Trabzon` + `-a` →
  `Trabzon'a`, but `Galatasaray` + `-a` → `Galatasaray'a` (no buffer
  needed because stem ends in `y`). For *"Bursa"* + `-a` →
  `Bursa'ya` (insert `y`); for possessive `-ı` after vowel-ending
  stem: *"Bursa"* + `-ı` → `Bursa'sı` (insert `s`). Without this rule
  the answer text reads non-grammatically, which is the most-flagged
  category in human review of Turkish-NLP outputs.
- [x] **`buffer_consonant(stem, suffix_class) -> str` helper.**
  Single source at `ai/common/text/turkish.py`; called from every
  morphology filter. Decision matrix:
  ```
  stem_last_char ∈ vowels AND suffix_class ∈ {dat, acc, abl} → 'y'
  stem_last_char ∈ vowels AND suffix_class == possessive_3sg  → 's'
  stem_last_char ∈ vowels AND suffix_class == compound_marker → 'n'
  stem_last_char ∈ vowels AND suffix_class == verb_passive_3sg → 'ş'
  otherwise → ''
  ```
  Tabled in `ai/nlp/lang_tr/buffer_consonant.tr.yaml` for testability;
  AST asserts the helper consults the table (no hardcoded branches).
- [x] **Suffix-vowel-class lookup.** Suffix vowel chosen by 4-way
  harmony (front-rounded / front-unrounded / back-rounded /
  back-unrounded) from `ai/nlp/lang_tr/vowel_harmony_4way.tr.yaml`.
  Already implicit in §10.7 filters; §10.22.3 makes the table the
  single source and asserts every filter consults it (no inline vowel
  literals — AST guard).
- [x] **Foreign-stem opt-out.** Some foreign stems are pronounced with
  a final consonant even though spelled with a vowel (*"Lyon"* — final
  `n` is silent in French but pronounced in Turkish; suffix attaches
  as if consonant-final). Per-stem override in
  `foreign_stem_overrides.tr.yaml::pronunciation_class`.
- [x] **Golden table proof.** `ai/nlp/lang_tr/golden/buffer_golden.yaml`
  — 300 rows of `(stem, suffix_class, expected_output)` covering every
  frequent team / league / venue / player name in the v1 catalog.
  100% pass required by §10.20 / §10.22 DoD.
- [x] **Proof:** `test_nlp_buffer_consonant_table_drives_decision`
  (AST), `test_nlp_buffer_golden_table_100_percent`,
  `test_nlp_buffer_consonant_handles_lyon_foreign_pronunciation_override`,
  `test_nlp_no_inline_vowel_literals_in_morph_filters` (AST scan
  rejects regex / string literal containing only vowel chars in
  `ai/nlp/jinja_filters_tr.py`).

#### 10.22.4 Particle disambiguation: "de/da", "ki", "mi/mı/mu/mü"

- [x] **Real failure mode — the most common Turkish writing error.**
  - **`de` / `da` (also vs locative)**: *"Galatasarayda maç var"* (=
    "match at Galatasaray"; locative — must be ATTACHED) vs
    *"Galatasaray da kazandı"* (= "Galatasaray, too, won"; conjunction
    — must be DETACHED). Users routinely write the wrong form;
    intent / entity extractor must read the **intended** sense.
  - **`ki`**: *"evdeki maç"* (= "the match at home"; relative — must
    be ATTACHED) vs *"söyledi ki ..."* (= "he said that ..."; complement
    — must be DETACHED).
  - **`mi/mı/mu/mü`**: question particle — must always be SEPARATE
    (*"oynuyor mu?"*); users frequently attach (*"oynuyormu?"*).
- [x] **Token-level normalizer.** New step **8a** in §10.1 (between
  tokenization and typo correction; doesn't change semantic order
  because §10.1 step 8 is "typo correction" — particle normalization
  is a more structural pre-typo pass):
  - Detach attached `mi/mı/mu/mü` from any token where the substring
    matches the question-particle vowel-harmony rule AND removing it
    leaves a valid Turkish-shaped stem (vowel-final or
    consonant-final, respects vowel harmony of stem).
  - Attached vs detached `de/da` / `ki`: do NOT silently re-attach;
    instead carry an annotation `tokens[].particle_attachment_repaired`
    so the §10.4 fastText classifier sees the canonical form (always
    detached) AND the §10.5 gazetteer can match either form.
  - **Never** auto-detach `de/da` from a stem where doing so changes
    the canonical entity (e.g., do NOT split *"Edirne"* → *"Edirn"* +
    *"e"* — `Edirne` is an indivisible canonical city name).
    Decision rule: only normalize when the stem-after-detach is in
    the lexicon stem-set OR is a verb root recognised by the Zemberek
    rules subset.
- [x] **Particle rules in `ai/nlp/lang_tr/particles.tr.yaml`** — single
  source: `mi_variants: [mi, mı, mu, mü, miyim, misin, miyiz, ...]`
  with vowel-harmony match per stem class. Same for `de_da_pairs` and
  `ki_pairs`. AST asserts no hardcoded particle string in `_normalize.py`.
- [x] **Adversarial caution.** Particle normalization is adversarially
  exploitable: *"sen de gel"* (= "you come too") vs *"sende gel"* (=
  ungrammatical). Normalizer must NEVER force-detach in cases that
  generate a non-Turkish-shaped stem. Test corpus
  `ai/tests/fixtures/turkish_particles.yaml` (≥ 60 rows) covers
  positive AND negative cases, with `expected_change: bool`.
- [x] **Proof:** `test_nlp_question_particle_detached_from_oynuyormu`,
  `test_nlp_de_da_attachment_recovered_for_galatasarayda_locative`,
  `test_nlp_de_da_not_split_when_stem_is_canonical_entity`
  (Edirne / Adana / Konya regression set), `test_nlp_ki_attached_in_evdeki`,
  `test_nlp_particle_rules_loaded_from_yaml_only` (AST),
  `test_nlp_particle_normalizer_adversarial_corpus` (60-row
  parametrized — all positive AND negative outcomes pinned).

#### 10.22.5 Colloquial / dialect / abbreviation expansion

- [x] **Real failure mode.** Spoken-Turkish-typed-on-keyboard:
  *"yapıcaz"* (= "yapacağız" / "we will do"), *"geliyo"* (= "geliyor"),
  *"di mi"* / *"dimi"* (= "değil mi"), *"bişey"* / *"birşey"* (= "bir
  şey"), *"napıyo"* (= "ne yapıyor"), *"abi"* (vocative; should not
  carry semantic weight). Plus team abbreviations: *"GS"* → Galatasaray,
  *"FB"* → Fenerbahçe, *"BJK"* → Beşiktaş, *"TS"* → Trabzonspor — and
  composite *"GS-FB"* → match between the two.
- [x] **Two-table normalizer.** `ai/nlp/lang_tr/dialect.tr.yaml` (token
  → canonical-token-sequence; e.g., *"yapıcaz" → "yapacağız"*) + the
  existing `dialects.tr.yaml` per §10.2 (which becomes a **subset**
  for entity-related dialect — team-name abbreviations). Two tables,
  one purpose split: linguistic vs entity. Build asserts they are
  disjoint (no token in both).
- [x] **Abbreviation table format.** `ai/nlp/lang_tr/abbreviations.tr.yaml`:
  `{abbreviation, expansion_canonical_id, ambiguity_class ∈ {hard,
  soft}, requires_co_token: [...]}`. Hard = always expand (e.g.,
  "GS" never means anything else in football context). Soft = expand
  only with required co-token (e.g., "RM" could be Real Madrid OR
  "ruh hali" — requires `[madrid, real, futbol, maç]` neighbour). The
  ambiguity class is the input to the §10.5 conflict resolver.
- [x] **Composite-abbreviation pattern.** *"GS-FB"*, *"FB vs BJK"*,
  *"GS Fener"* — handled at the **dispatcher** (§10.6), not at the
  tokenizer. After gazetteer resolution, when two team entities resolve
  AND the token between them matches `cfg.nlp_match_separator_pattern`
  (default `^(-|–|—|vs\.?|x|×|/)$`), the dispatcher promotes the pair
  to a `match_lookup` slot (Phase 4 storage agent answers via
  `data.fixture_lookup` keyed on `team_a_id, team_b_id`). Without a
  separator (*"GS Fener"*), the dispatcher requires a co-token like
  *"maç"* / *"derbi"* / *"karşılaşma"* to trigger the same path;
  otherwise it falls through to disambiguation.
- [x] **Vocative / filler stripping.** Tokens like *"abi"*, *"reis"*,
  *"hocam"*, *"bro"*, *"kanka"* are dropped from the token stream
  pre-classifier (do NOT influence intent). Table at
  `ai/nlp/lang_tr/vocative_filler.tr.yaml`; build asserts every token
  is documented; AST asserts the strip step exists and consults the
  table.
- [x] **Proof:** `test_nlp_dialect_yapicaz_expands_to_yapacagiz`,
  `test_nlp_abbreviation_gs_resolves_to_galatasaray`,
  `test_nlp_abbreviation_rm_requires_co_token`,
  `test_nlp_match_separator_promotes_to_match_lookup`
  (parametrized over `[-, –, —, vs, x, ×, /]`),
  `test_nlp_vocative_filler_dropped_does_not_change_intent`,
  `test_nlp_dialect_and_entity_dialect_tables_are_disjoint` (build).

#### 10.22.6 Date / time / score / weekday TR-specific parsing

- [x] **Real failure mode §10.5 underspecifies.** Turkish users write:
  - **Times**: *"21:30"*, *"21.30"*, *"21,30"*, *"21de"*, *"saat 9"*,
    *"akşam 9"*, *"21'de"*, *"21'inde"* (locative inflection on
    numerical clock).
  - **Dates**: *"27/04"*, *"27.04"*, *"27 nisan"*, *"27 Nisan"*,
    *"27nisan"*, *"27.04.2026"*, *"27 nisan 2026"*, *"önümüzdeki
    cuma"*, *"haftaya"*, *"hafta sonu"*, *"sonraki hafta"*,
    *"gelecek pazartesi"*. Year is frequently omitted; default
    resolution = "next occurrence in [now, now + `cfg.nlp_date_default_window_days=180`]".
  - **Scores**: *"1-0"*, *"1:0"*, *"1 0"*, *"bir sıfır"* (Turkish
    numerals), *"1'e 0"*, *"1-0'lık"* (with possessive).
  - **Weekdays**: *"pazartesi"* / *"Pazartesi"* (TDK convention is
    lowercase except sentence-start); *"pzt"* / *"sal"* / *"çar"* /
    *"per"* / *"cum"* / *"cmt"* / *"paz"* abbreviations.
- [x] **Per-class CRF feature templates** (extends §10.5 step 2). One
  feature template file per class (`time.tmpl`, `date.tmpl`,
  `score.tmpl`, `weekday.tmpl`) under `ai/nlp/lang_tr/crf_templates/`;
  trained CRF model carries the template hash in its sidecar so model
  + template stay in sync (refuse-load on hash mismatch — mirrors
  §10.21.1 fastText SHA pin).
- [x] **Number-word resolver.** `ai/nlp/lang_tr/number_words.tr.yaml`
  — table for *"sıfır"* → 0 ... *"yirmi"* → 20 plus *"otuz"*,
  *"kırk"*, ..., *"yüz"*, *"bin"*, *"milyon"*; composite (*"yirmi
  bir"* → 21) computed via `ai/common/text/turkish.py::parse_number_word`.
  Used by score parser to accept *"bir sıfır"*.
- [x] **Locative-on-clock disambiguation.** *"21'de"* (= "at 21:00")
  vs *"21'i"* (= "the 21st [of the month]") — distinguished by suffix
  class, not just regex. Suffix-stripper from §10.22.2 reused.
- [x] **Default time-of-day resolver.** *"akşam"* + numerical hour
  resolves to PM if hour < 12; *"sabah"* / *"öğleden önce"* → AM;
  *"gece yarısı"* → 00:00. Table at
  `ai/nlp/lang_tr/time_of_day.tr.yaml`. Match-time-typical bias:
  unqualified hour 1–11 in football context defaults to PM (matches
  rarely play AM); operator-tunable via `cfg.nlp_time_default_period`.
- [x] **Date relative to now.** *"haftaya"*, *"önümüzdeki hafta"*,
  *"gelecek hafta"*, *"hafta sonu"*, *"yarın"*, *"öbürsü gün"* /
  *"öbür gün"*, *"dün"*, *"evvelki gün"* — all resolved against
  `cfg.nlp_clock_now()` (already pinned at §10.5 for testability).
- [x] **Year-omission default.** Fixture lookup defaults to "next
  occurrence in [now, now + `cfg.nlp_date_default_window_days=180`]";
  if no fixture matches → disambiguation answer enumerating top-3
  candidates with explicit year.
- [x] **Proof:** `test_nlp_time_dot_separator_resolves_2130`,
  `test_nlp_time_locative_21de_resolves_to_2100`,
  `test_nlp_date_27_nisan_no_year_resolves_to_next_occurrence`,
  `test_nlp_score_bir_sifir_word_form_parses_to_1_0`,
  `test_nlp_weekday_abbreviation_cmt_resolves_to_saturday`,
  `test_nlp_weekday_case_insensitive`,
  `test_nlp_aksam_9_resolves_to_2100`,
  `test_nlp_haftaya_resolves_to_now_plus_7d_bounded`,
  `test_nlp_crf_template_hash_matches_model_sidecar` (refuse-load on
  drift).

#### 10.22.7 Match-pattern parsing (multi-format team-vs-team)

- [x] **Real failure mode.** Users describe a fixture in many ways:
  - *"Galatasaray-Fenerbahçe"*, *"Galatasaray Fenerbahçe maçı"*,
    *"GS - FB"*, *"GS-FB derbisi"*, *"galatasaray vs fenerbahce"*,
    *"galatasaray ile fenerbahçe"*, *"galatasaray fenere karşı"*.
  - Including a date / matchday: *"27 Nisan GS-FB"*, *"derbi
    cumartesi"*, *"haftaya Trabzon Beşiktaş"*.
- [x] **Dispatcher-side composite-entity resolver.** Already partially
  pinned in §10.22.5 (separator-driven). §10.22.7 expands to:
  - Word-bridges: `cfg.nlp_match_word_bridges = ["ile", "karşı",
    "vs", "vs.", "ve"]` — when two team entities are separated by
    one of these tokens (with optional intervening punctuation), they
    promote to a `match_lookup` slot.
  - Adjacency rule: two team entities with no intervening sentence
    boundary AND a co-token `match_co_tokens =
    ["maç", "maçı", "derbi", "karşılaşma", "fikstür", "oyun"]` within
    `cfg.nlp_match_adjacency_radius=4` tokens → also promotes.
  - Date / matchday adjacency: a resolved date/time entity within
    `cfg.nlp_fixture_date_adjacency_radius=8` tokens of a team-pair
    entity is bound to it as the fixture filter.
- [x] **Order-insensitive fixture lookup.** Once `(team_a_id, team_b_id)`
  resolves, the storage-agent query (Phase 4) must be order-insensitive
  (matches both home / away). Forward contract: `data.request.v1{kind=
  fixture_lookup, team_pair: [a_id, b_id]}` where the pair is
  alphabetically sorted before publish (deterministic dedup-friendly).
- [x] **Proof:** `test_nlp_match_word_bridge_ile_promotes_to_match_lookup`,
  `test_nlp_match_adjacency_co_token_derbi_promotes_pair`,
  `test_nlp_date_adjacent_to_pair_binds_fixture_filter`,
  `test_nlp_team_pair_sorted_before_dispatch`
  (deterministic-dedup probe).

#### 10.22.8 Code-switching (TR / EN intermix) handling

- [x] **Real failure mode.** *"manchester city formdaymış"*,
  *"premier league standings"*, *"fixture nasıl?"*,
  *"city'nin kadrosu"*, *"liverpool maçında kim sakat?"* — English
  team / league / common-noun mixed with Turkish syntax. Pure-TR
  classifier may abstain or mis-classify.
- [x] **Bilingual gazetteer pass.** Lexicon files already store
  English-canonical names (*"Premier League"*, *"Manchester City"*).
  §10.22.8 pins: gazetteer pass (§10.5) is **case-insensitive** AND
  the §10.22.1 ASCIIfied alias index covers EN spellings (a no-op
  for plain ASCII, but ensures the same code path).
- [x] **English-token tolerance in classifier.** fastText n-gram
  features cope with EN tokens natively; §10.18 evaluation harness
  `code_switch=20` slice already gates intent accuracy on this.
  §10.22.8 raises the gate: code-switch slice MUST hit
  `cfg.nlp_intent_accuracy_floor` (=0.92) — same as the clean slice
  (was previously implicitly weaker).
- [x] **English suffix-noise tolerance.** Users sometimes English-pluralize
  Turkish stems (*"galatasaraylar"* — ungrammatical) or vice-versa
  (*"city'nin"* — Turkish suffix on EN stem, handled by §10.22.2
  apostrophe rule + §10.22.3 buffer-consonant via foreign-stem
  override). Test corpus `ai/tests/fixtures/turkish_code_switch.yaml`
  covers ≥ 30 mixed-language queries with `expected_intent` and
  `expected_entities`.
- [x] **NEVER translate the user's text.** No machine translation
  layer in either direction; humanizer §10.8 is bound to TR-only
  output via the EN-blocklist in proofreader gate #2 (§10.9). AST
  asserts no `translate(`, `translation`, `googletrans`, `deep_translator`
  symbol anywhere under `ai/swarm/agents/nlp/**` and `ai/nlp/**`.
- [x] **Proof:** `test_nlp_code_switch_manchester_city_resolves_to_canonical`,
  `test_nlp_code_switch_intent_accuracy_meets_floor`
  (full code-switch corpus), `test_nlp_no_translation_dependency`
  (AST), `test_nlp_english_pluralized_galatasaraylar_recovers_to_galatasaray`.

#### 10.22.9 Offensive language / slang gate

- [x] **Real failure mode.** Users curse, joke, abuse the bot. Two
  sub-cases that need different handling:
  - **Direct abuse at the bot** — e.g., *"amk yapay zeka"* — must
    not be parroted back, must not fail loud, must route gracefully.
  - **Offensive content as part of a real query** — e.g.,
    *"hakemin amına koyim niye penaltı vermedi"* (= angry but
    contains a real intent: penalty / referee question). The intent
    extraction must succeed; the offensive tokens are stripped from
    any answer text but DO NOT block answering.
- [x] **Closed taxonomy.** `ai/nlp/lang_tr/offensive.tr.yaml` —
  three classes: `mild` (everyday vulgar; e.g., *"saçmalık"*, *"abi
  ya"*) — no action; `slur` (targeted slurs incl. ethnic / sexist /
  homophobic) — strip-and-answer + `nlp.alert.v1{kind=
  nlp_slur_in_input, severity=warn}` (debounced — operator
  visibility, not user-visible block); `severe_threat` (death
  threats, doxxing patterns, instructions to harm) — route to
  `meta.adversarial`, do NOT answer the question.
- [x] **Tokenizer-level stripping for `slur` class.** Replace each
  matched token with a sentinel `<STRIPPED>` BEFORE classifier sees
  text (so the classifier doesn't learn slur → intent association).
  Sentinel acts as a generic noise token; entity / intent extraction
  proceeds normally on the remaining stream.
- [x] **NEVER quote-back any class.** §10.21.6 already forbids raw
  user text in templates; §10.22.9 reasserts: even sanitized,
  the offensive tokens are NEVER reproduced in `qa.answer.v1`.
  Proofreader §10.9 gate #4 extends to scan for offensive-table
  matches in the rendered answer (defense-in-depth — should never
  fire because templates don't carry user text, but if it does, the
  answer is blocked + critical alert).
- [x] **Adversarial-jailbreak echoes.** Already covered by §10.9
  gate #5 (forbidden phrases). §10.22.9 adds the `slur` table to
  the same gate (single source — the gate consults both).
- [x] **Proof:** `test_nlp_slur_token_stripped_before_classifier`,
  `test_nlp_severe_threat_routes_to_adversarial`,
  `test_nlp_mild_offensive_does_not_block`,
  `test_nlp_proofreader_blocks_slur_in_rendered_answer`
  (defense-in-depth fail-loud), `test_nlp_offensive_table_loaded_with_three_classes`.

#### 10.22.10 Foreign-team transliteration variants

- [x] **Real failure mode.** *"Bayer Münih"* / *"Bayer Munih"* /
  *"Bayern"* (the user's confusion between Bayer Leverkusen and
  Bayern München is real); *"Mancester"* / *"Mancester Citi"* /
  *"Manchester Citi"* / *"M. City"* / *"Man City"*; *"Inter"* /
  *"Internazionale"* / *"Inter Milan"*; *"Atletico"* / *"Athletico"*
  (commonly confused with Athletic Bilbao); *"Saint Etienne"* /
  *"Sant Etienne"* / *"St Etienne"*.
- [x] **Phonetic-collision allow-list.** `ai/nlp/lang_tr/phonetic_aliases.tr.yaml`
  — manually curated list of `(phonetic_form, canonical_id, requires_co_token?,
  confused_with: [...])`. The `confused_with` field drives the
  `entities_negative.tr.yaml` rules: *"Bayer Münih"* alone resolves
  to Bayern München with a `nlp.event.v1{kind=
  phonetic_alias_resolved_with_confusion_warning, confused_with:
  ['Bayer Leverkusen']}` event so operators can see how often the
  user's "wrong" spelling is being silently corrected.
- [x] **Non-Latin script support (deferred but pinned).** Arabic /
  Cyrillic / Greek football terms not in scope at v1; gazetteer
  build refuses any entry with non-Latin characters AND no
  Latin-transliteration sibling. Forward hook: locale `tr-TR` only
  at v1 per §10.17; future locale additions reopen the question.
- [x] **Build-time collision report.** `make nlp.lexicon-build`
  emits `data/nlp/build_reports/phonetic_collisions.md` listing
  every `confused_with` pair. Reviewed in PR by humans (CI-gated:
  PR refuses merge if the file changed without a same-PR
  acknowledgement file `ai/nlp/lexicon/_phonetic_review.md` updated).
- [x] **Proof:** `test_nlp_phonetic_bayer_munih_resolves_to_bayern_with_event`,
  `test_nlp_phonetic_table_entries_resolve_to_catalog`,
  `test_nlp_phonetic_collisions_report_generated`,
  `test_nlp_no_non_latin_script_in_v1_lexicon` (build).

#### 10.22.11 Locale-tag normalization & fallback chain

- [x] **Real failure mode §10.17 underspecifies.** API gateway honors
  `Accept-Language`; users may send `tr`, `tr-TR`, `tr-CY` (Cyprus),
  `tr-DE` (German Turkish diaspora), `tr-NL`, or even malformed
  tags. v1 supports only `tr-TR`; everything else MUST graceful-fall.
- [x] **Fallback chain.** `cfg.nlp_locale_fallback_chain =
  ["tr-TR"]` (closed list at v1). Resolver:
  1. Parse incoming tag via BCP-47 rules (lowercase region,
     uppercase country); reject malformed → fall through.
  2. Exact match in chain → use it.
  3. Language-only match (`tr-*` → `tr-TR`) → use base locale.
  4. No match → `cfg.nlp_default_locale=tr-TR` + emit
     `nlp.event.v1{kind=locale_fallback_used, requested, resolved}`
     (debounced 60s per requested tag — bounded cardinality).
- [x] **Per-request override.** API surfaces an explicit
  `?locale=tr-TR` query param (Phase 9); param > header > default.
  Forward-compat: when a second locale is added, no schema change
  needed — just update the chain.
- [x] **Proof:** `test_nlp_locale_tr_only_falls_back_to_tr_tr`,
  `test_nlp_locale_tr_de_falls_back_with_event`,
  `test_nlp_locale_malformed_falls_back_default`,
  `test_nlp_locale_param_overrides_header`.

#### 10.22.12 Lexicon-feed integrity (Phase 16 supply-chain signature)

- [x] **Real attack §10.21.8 / §10.21.11 partially miss.** §10.21.8
  signs `predict.approved.v1` citations; §10.21.11 forces
  feed-schema-version refusal. Neither covers the case where Phase 16
  emitter publishes a **lexicon feed** with the same schema_version
  but adversarial / poisoned content (e.g., a malicious team alias
  mapping that re-routes "Galatasaray" queries to a different
  canonical_id; or a `dialects.tr.yaml` rule that injects an
  attacker-controlled token sequence into common queries).
- [x] **Feed signature.** Phase 16 emitter signs every lexicon feed
  payload with `cfg.nlp_lexicon_feed_hmac_key_path` (mode 0400,
  shared between emitter and NLP via secret-mount; rotated via
  `make nlp.rotate-lexicon-key` with 24h dual-acceptance window —
  mirrors §10.21.8 citation-key rotation). NLP REFUSES to swap a
  feed payload that fails signature verify; emits `nlp.alert.v1{kind=
  nlp_lexicon_feed_signature_invalid, severity=critical}`. Bypass
  switch: `cfg.nlp_lexicon_feed_signature_required ∈ {off, warn,
  enforce}` default `warn` at v1 (consistent with §10.21.8 rollout
  doctrine), `enforce` post-Phase-14.
- [x] **Fail-closed default for sensitive lexicons.** `markets.tr.yaml`
  AND `entities_negative.tr.yaml` ALWAYS require valid signature
  regardless of the global `*_required` setting (rationale: market
  enum + disambiguators are the highest-leverage corruption targets
  — a single bad market mapping mis-routes every betting query).
  Hard-coded list at `ai/swarm/agents/nlp/_critical_lexicons.py`.
- [x] **Signature key rotation runbook.** `make nlp.rotate-lexicon-key`
  shipped alongside the agent; same dual-window pattern as
  §10.21.8. Operator runbook entry in `docs/guides/nlp_runbook.md`
  (NEW file in this phase).
- [x] **Build-pipeline signature.** `make nlp.lexicon-build` emits
  signed bundles for non-feed-driven path too (when running from
  in-repo source pre-Phase-16); SHA-only verify at load (no HMAC)
  for in-repo flow, HMAC verify for Phase 16 feed flow. Boundary
  test: NLP runtime never trusts a SHA-only artifact when running
  in `cfg.nlp_lexicon_source ∈ {file, feed}` mode `feed`.
- [x] **Proof:** `test_nlp_lexicon_feed_invalid_signature_refused_in_enforce`,
  `test_nlp_lexicon_feed_warn_mode_swaps_with_alert`,
  `test_nlp_critical_lexicons_always_enforce_regardless_of_global_mode`,
  `test_nlp_lexicon_key_rotation_dual_acceptance_window`,
  `test_nlp_lexicon_runtime_rejects_sha_only_artifact_in_feed_mode`.

#### 10.22.13 Turkish-quality telemetry & error-class metrics

- [x] **Per-rule-class counters** (cardinality bounded — closed set):
  - `nlp_input_repair_total{class ∈ {ascii_restored, particle_detached_mi,
    particle_repaired_de_da, particle_repaired_ki, apostrophe_inserted,
    suffix_recovered, abbreviation_expanded, dialect_expanded,
    vocative_dropped, slur_stripped, code_switch_token, phonetic_alias_resolved,
    confusables_folded}}` — counter incremented per repair event.
  - `nlp_input_repair_density` histogram of (repairs / token-count)
    per query — high values indicate degrading input quality (or
    classifier confusion); §10.18 evaluation harness gates p95 ≤
    `cfg.nlp_repair_density_p95_max=0.5` on the clean slice.
  - `nlp_disambiguation_offered_total{cause ∈ {low_intent_conf,
    ambiguous_entity, ambiguous_match_pair, ambiguous_date,
    confused_phonetic_alias}}` counter.
  - `nlp_offensive_input_total{class ∈ {mild, slur, severe_threat}}`
    counter (debounce on emit, not on count — count is always
    truthful).
- [x] **Per-day quality dashboard.** Operator-facing aggregation over
  the above — tail of `nlp_input_repair_density` is the leading
  indicator of incoming input-quality drift (e.g., a viral tweet
  drives a flood of code-switched / dialect input). Documented in
  `docs/guides/nlp_runbook.md` with action thresholds.
- [x] **Sampled-answer audit slice tagging.** §10.14 sampling
  extends to record the per-rule-class repair list per sampled query
  (PII-redacted: only the class names, not the original tokens).
  Allows offline correlation of "repairs applied" vs "human-judged
  answer correctness".
- [x] **Proof:** `test_nlp_repair_counters_increment_per_class`
  (parametrized), `test_nlp_repair_density_metric_bounded_in_clean_slice`,
  `test_nlp_disambiguation_cause_bounded_enum`,
  `test_nlp_offensive_counter_truthful_under_debounce`.

#### 10.22.14 Knob inventory + DoD aggregate

- [x] **New cfg knobs (~22, on top of §10.19 + §10.21.12):**
  `nlp_ascii_vs_restored_margin=0.2`,
  `nlp_diacritic_hard_call_min_freq=10000`,
  `nlp_diacritic_max_risk_per_token=2.5`,
  `nlp_match_separator_pattern="^(-|–|—|vs\\.?|x|×|/)$"`,
  `nlp_match_word_bridges=["ile", "karşı", "vs", "vs.", "ve"]`,
  `nlp_match_co_tokens=["maç","maçı","derbi","karşılaşma","fikstür","oyun"]`,
  `nlp_match_adjacency_radius=4`,
  `nlp_fixture_date_adjacency_radius=8`,
  `nlp_date_default_window_days=180`,
  `nlp_time_default_period="pm"`,
  `nlp_locale_fallback_chain=["tr-TR"]`,
  `nlp_lexicon_feed_hmac_key_path="infra/nlp/lexicon_feed_hmac.key"`,
  `nlp_lexicon_feed_hmac_key_grace_s=86400`,
  `nlp_lexicon_feed_signature_required="warn"`,
  `nlp_lexicon_source="file"` (file at v1; feed post-Phase-16),
  `nlp_repair_density_p95_max=0.5`,
  `nlp_lang_tr_dir="ai/nlp/lang_tr"`,
  `nlp_lang_tr_reload_s=30` (mirrors §10.2 lexicon mtime poll cadence
   for the `lang_tr/*.yaml` rule tables — same atomic-swap discipline,
   distinct lock so language-rule reload doesn't block lexicon reads).
  Triangle test extends; Go-side `TestEnvSync` covers
  `nlp_lexicon_feed_hmac_*` (Phase 16 emitter is Go-friendly per
  §16 Pivot v3 ownership — when emitter ships, the gateway-equivalent
  signature-publishing path needs the shared knob).
- [x] **New `nlp.event.v1` kinds** (open-enum, registered):
  `phonetic_alias_resolved_with_confusion_warning`,
  `locale_fallback_used`,
  `dialect_expanded`,
  `abbreviation_expanded`,
  `particle_repaired`,
  `apostrophe_inserted`.
- [x] **New `nlp.alert.v1` kinds** (open-enum, registered):
  `nlp_slur_in_input` (warn, debounced),
  `nlp_lexicon_feed_signature_invalid` (critical),
  `nlp_repair_density_anomaly` (warn — fires when 10-min rolling
   p95 of repair-density exceeds the cfg cap).
- [x] **New build artifacts.** `data/nlp/build_reports/phonetic_collisions.md`
  (CI-tracked); `ai/nlp/lexicon/_phonetic_review.md` (PR-gated
  acknowledgement file).
- [x] **DoD proof tests aggregate (new in §10.22):**
  - §10.22.1 — 5 tests
  - §10.22.2 — 5 tests
  - §10.22.3 — 4 tests (incl. 300-row golden table)
  - §10.22.4 — 6 tests
  - §10.22.5 — 6 tests
  - §10.22.6 — 9 tests
  - §10.22.7 — 4 tests
  - §10.22.8 — 4 tests
  - §10.22.9 — 5 tests
  - §10.22.10 — 4 tests
  - §10.22.11 — 4 tests
  - §10.22.12 — 5 tests
  - §10.22.13 — 4 tests
  - **Total: ≈ 65 new proof tests added on top of §10.20 + §10.21
    baseline.**
- [x] **`make swarm.demo.nlp` extends** to cover the §10.22 paths:
  one query per family (ASCII-only, dropped-apostrophe,
  attached-question-particle, dialect, abbreviation, code-switch,
  date+match-pair, foreign-transliteration, locale-fallback,
  offensive-with-real-intent). All within the < 30s compose budget
  (per §10.20 item 16 — additional queries amortize via singleflight
  and L0 cache hits on shared sub-paths).
- [x] **Documentation.** `docs/design/TURKISH_NLP.md` rewritten in
  lockstep with §10.22 — every rule table referenced here gets a
  prose explanation + worked examples in the design doc.
  `docs/guides/nlp_runbook.md` (NEW): operator-facing playbook
  covering lexicon swap, key rotation, repair-density alert
  triage, code-switch & dialect drift response. `docs` minor bump
  alongside the §10.22 land per AGENTS.md §6.1.
