# Phase 10 §10.33 — Turkish input flawlessness, wrong-assumption sweep, missing proof tests (binding addendum, 14th pass)

> **Provenance.** Authored on the Phase 10 split, after the §10.0–§10.32
> contract was carved out of `docs/planning/ROADMAP.md` into
> `docs/design/phase10/sections/`. This file is the **14th** design pass and
> is binding for Phase 10 DoD (added as §10.20 DoD item 31 below).
>
> **Why a 14th pass after thirteen?** The prior thirteen passes built a
> wide and deep contract for *recognising* messy Turkish, but a focused
> review surfaced three classes of residue: (1) **wrong assumptions** —
> places where a closed table or a "deterministic floor" was specified
> but the underlying assumption is empirically false on real Turkish
> input; (2) **missing proof tests** — checklists that say "handle X"
> with no test that actually exercises X end-to-end on adversarial
> input; (3) **the generic-and-wrong-Turkish floor** — the system
> handles "academically wrong" Turkish (typo, missing diacritic,
> dialect) but still trusts certain shapes of *generically broken*
> Turkish (mixed-script paste, vowel-harmony violation, suffix-on-loan
> "Englishe" mid-word, zero-width-joiner injection, mojibake-recovered
> double-decoded UTF-8, etc.) that today silently route to wrong
> handlers or produce confidently-wrong answers.
>
> **Mirrors the §9.17 / §10.21 pattern:** prior addenda are the surface
> contract; §10.33 is the *correctness-proof floor* underneath. Every
> `[ ]` here is binding for Phase 10 DoD. New cfg knobs land alongside
> §10.19 (now in `00-baseline.md`) in the same triangle commit.
>
> **Cross-pass contract (binding).** §10.33 must not silently re-spec
> any prior addendum. When §10.33 strengthens a prior assumption, it
> says so by section number and references the prior text verbatim.
> When §10.33 adds a *new* surface (new wire field, new closed table,
> new gate), it must land in the **same** triangle commit as the
> matching cfg knob in §10.19, the matching DoD bullet in this file
> §10.33.DoD, and the matching `make verify.*` target.

## 10.33.1 Wrong-assumption sweep (binding)

Each item below cites the prior addendum claim, names the empirical
counter-example, and states the binding correction. Tests live in
`ai/swarm/agents/nlp/tests/wrong_assumptions/`.

- [x] **Assumption (§10.1):** "Normalize is deterministic, ordered,
      idempotent."
      **Counter-example:** NFC then casefold is **not** idempotent on
      certain pre-composed characters (e.g. `İ` casefolds to `i\u0307`
      under default Unicode locale; re-applying NFC composes it back
      only conditionally depending on locale). On Turkish locale,
      `İ.lower()` returns `i` (correct); on default locale it returns
      `i̇` with a combining dot above. A boot probe must lock the
      runtime locale to `tr_TR.UTF-8` (or `und-TR`) and refuse start
      otherwise. Add `test_normalize_locale_lock` that asserts
      `locale.getlocale(locale.LC_CTYPE)` matches an allow-list and
      that `"İ".lower() == "i"` byte-for-byte.
      **Correction:** §10.1 normalize chain MUST run under a pinned
      Turkish locale; cfg `nlp_runtime_locale=tr_TR.UTF-8` (added
      §10.33-knob-1); boot refuse on mismatch with
      `nlp.alert.v1{kind=nlp_runtime_locale_mismatch, severity=critical}`.

- [x] **Assumption (§10.21.5 confusables):** "Cyrillic / Latin / Greek
      look-alikes folded to canonical Latin."
      **Counter-example:** Mixed-script paste from social media often
      includes the **Mathematical Alphanumeric Symbols** block
      (U+1D400..U+1D7FF — bold, italic, double-struck Latin), the
      **Halfwidth and Fullwidth Forms** block (U+FF21..U+FF5A —
      `Ｇａｌａｔａｓａｒａｙ`), and **Tag** characters (U+E0020..) used in
      modern emoji-flag spoofing. The §10.21.5 confusables table covers
      Cyrillic but does not enumerate these.
      **Correction:** Extend `confusables_spec.json` to include
      Mathematical Alphanumeric, Halfwidth/Fullwidth, Tag, and Enclosed
      Alphanumerics blocks. Add `test_normalize_mathalpha_fold`,
      `test_normalize_fullwidth_fold`, `test_normalize_tag_strip`,
      `test_normalize_enclosed_alpha_fold`. Each test runs a 50-row
      adversarial corpus and asserts the normalized output equals the
      pure-ASCII canonical equivalent byte-for-byte.

- [x] **Assumption (§10.22 ZWJ/ZWNJ):** "Zero-width joiner / non-joiner
      stripped during normalize."
      **Counter-example:** **Variation Selectors** (U+FE00..U+FE0F),
      **Mongolian Vowel Separator** (U+180E), **Word Joiner**
      (U+2060), **Function Application** (U+2061..U+2064), **Hangul
      Filler** (U+115F, U+1160, U+3164), and the **Bidi controls**
      (U+202A..U+202E, U+2066..U+2069) all survive ZWJ/ZWNJ-only
      stripping and can be used to (a) inject hidden text into entity
      mentions (`Galatasaray\u202EFenerbahçe` renders right-to-left
      flipped), (b) bypass the §10.30.10 slur-obfuscation table by
      splitting characters with U+2060.
      **Correction:** Replace ZWJ/ZWNJ-only stripping with an explicit
      **default-strip allow-list** of "format" category characters:
      `unicodedata.category(c) == "Cf"` is stripped *unless* the codepoint
      is on a documented allow-list (none today; the list is `[]` and
      is enforced by `test_normalize_no_format_chars_pass`). Also strip
      `Cn` (unassigned), `Co` (private use), `Cs` (surrogates) with
      `nlp.event.v1{kind=normalize_disallowed_codepoint_stripped}`
      telemetry. Bidi controls in particular get a dedicated alert
      (`bidi_control_stripped`, severity=warn) because they signal
      adversarial paste.

- [x] **Assumption (§10.28 orthographic floor):** "Apostrophe between
      proper noun and case suffix is mandatory in formal Turkish."
      **Counter-example:** TDK (Türk Dil Kurumu) rules permit and
      prefer the apostrophe for proper nouns, but real-world Turkish
      football discourse drops the apostrophe ~60% of the time on
      well-known club names (`Galatasarayda` for `Galatasaray'da`),
      and the §10.32.5 `proper_noun_apostrophe_spec.json` spec assumes
      the apostrophe is the disambiguator. With the apostrophe absent,
      the suffix boundary must come from a different signal (longest
      proper-noun match against the lexicon).
      **Correction:** §10.32.5 spec is extended with an
      **apostrophe-absent disambiguation rule**: if the input contains
      a token that is a known proper-noun prefix followed by a known
      Turkish case-suffix and *no* apostrophe, treat it as if the
      apostrophe were present and emit `nlp.event.v1{kind=
      apostrophe_inferred, evidence=lexicon_prefix_match,
      original=<token>, canonical=<token_with_apostrophe>}` for audit.
      Test: `test_apostrophe_dropped_60_pct_corpus` exercises a
      curated 200-row corpus of apostrophe-dropped real fan input and
      asserts ≥ 95% recall on entity extraction.

- [x] **Assumption (§10.4 / §10.30.5):** "Politeness markers stripped
      BEFORE classifier so they cannot bias routing."
      **Counter-example:** The strip set (`lütfen`, `acaba`, `mümkünse`,
      `rica etsem`, `-yebilir misiniz`) does not cover the **second-
      person plural respect form** (`yapar mısınız`, `söyleyebilir misiniz`,
      `bakar mısınız`) which is morphologically a question, not a
      politeness marker, and the **conditional-polite chain**
      (`bakabilir miydiniz`, `söyleyebilir miydiniz`) which compounds
      politeness with conditional + past, gating the classifier with
      a tense it should not see for routing.
      **Correction:** Extend politeness-strip table to include the
      respect-form question pattern (regex over morphemic boundaries,
      not surface form) AND the conditional-polite chain. Verify with
      `test_politeness_strip_respect_form` (60 rows) and
      `test_politeness_strip_conditional_polite_chain` (40 rows). The
      stripped form must route identically to the bare form.

- [x] **Assumption (§10.31.6 score notation):** "Home-team-first in
      written reports, winner-first in spoken commentary."
      **Counter-example:** This dichotomy is true **only** for Turkish
      sports media. User-generated content on social media (the bulk
      of `qa.request.v1` traffic) follows neither convention reliably —
      it follows whoever the user mentioned first in conversational
      context. The §10.31.6 alphabetical-first default is wrong; the
      conversational-first heuristic applies.
      **Correction:** Promote conversational-first (last-mentioned-team
      bound to a score position) to the default disambiguation when a
      cross-turn context is present, fall back to alphabetical-first
      only when the score appears in the very first user turn.
      Disambiguation prompt is unchanged. Test:
      `test_score_notation_conversational_first_default` exercises a
      150-row two-turn corpus where the score-notation reading depends
      on which team the user mentioned in turn 1.

- [x] **Assumption (§10.32.4 dialect normalization):** "≥ 120-rule
      closed table covers Aegean / Black Sea / Cypriot / diaspora."
      **Counter-example:** The dialect map's closed-table assumption
      is empirically false for **diaspora code-mixing** specifically:
      diaspora users mix Turkish morphology with English / German /
      Dutch / French **roots** in the same word (`maçı watch'ladım`,
      `transferi finalize'ledik`, `sarı kart'ı geçti, dafür got banned`).
      A closed table cannot enumerate the open class of foreign roots.
      **Correction:** Replace the diaspora portion of the closed table
      with a **morpheme-boundary rule**: any token of shape
      `<foreign_root>'<turkish_suffix>` where `<foreign_root>` matches
      `[A-Za-z]{3,20}` and is **not** in the Turkish lexicon and
      `<turkish_suffix>` is a valid Turkish suffix sequence is treated
      as an English/foreign verb-like root and routed via a NEW
      `meta.code_switched_unsupported_at_v1` template (closed Turkish
      apology) at v1, with telemetry `nlp.event.v1{kind=
      diaspora_code_switch_observed, foreign_root=<root>}` for product
      to prioritise top-N foreign roots in v2 lexicon.
      Test: `test_diaspora_code_switch_route` exercises 40 rows from
      the residue.

- [x] **Assumption (§10.5 / §10.26.1 morphology):** "Stem-final consonant
      mutation handled (`-k → -ğ`, `-p → -b`, `-t → -d`, `-ç → -c`)."
      **Counter-example:** Mutation is **conditional** on the suffix
      starting with a vowel **and** the stem being polysyllabic of
      Turkish origin. The current rule misfires on (a) monosyllabic
      stems where mutation does not occur (`saç → saçı` not `*sacı`,
      `at → atı` not `*adı`), (b) loan stems that resist mutation
      (`hukuk → hukuku` not `*huğuğu`, common in the football corpus
      via player names like `Demirbey` → `Demirbey'in` not
      `*Demirbeğin`), and (c) the inverse — stems that the current
      rule does not mutate but should (`ağaç → ağacı`).
      **Correction:** Replace the mutation rule with a **lexicon-
      driven** mutation table built from a public Turkish morphology
      corpus (Turkish Treebank or Zemberek's morpheme lexicon, license
      reviewed). Boot-time probe asserts the lexicon contains ≥ 5,000
      stem entries. Polysyllabic / monosyllabic / loan classification
      stamped per stem. Tests: `test_mutation_monosyllabic_no_change`
      (80 rows), `test_mutation_loan_resist` (60 rows),
      `test_mutation_polysyllabic_ck_to_g` (100 rows).

- [x] **Assumption (§10.7 templates):** "Templates parameterised on
      slot values via Turkish-morphology-aware suffix bindings."
      **Counter-example:** The current binding library covers ablative,
      dative, locative, accusative, genitive on **noun** slots, but
      football discourse uses three additional case-marked forms the
      library does not produce correctly: **comitative-instrumental**
      (`Galatasaray ile`, separate from `-yle/-yla` enclitic suffix),
      **equative** (`Galatasaray gibi`, particle not suffix),
      **distributive** (`takımlarca`, `takım başına`). Templates
      currently silently emit ungrammatical Turkish for these cases.
      **Correction:** Extend the binding library with the three forms,
      each with its own AST guard
      (`test_template_emits_grammatical_<form>_for_all_lexicon_entries`).
      §10.31.8 output-grammar proofreader gate is extended to flag
      these.

## 10.33.2 Missing proof tests (binding)

Each item adds an end-to-end proof test that closes a previously-
unverified `[ ]` claim. Tests live in
`ai/swarm/agents/nlp/tests/proof/` and are CI-required.

- [x] **§10.0 boundary discipline.**
      `test_nlp_boundary_discipline_outbound_set` walks the registry
      and asserts the NLP outbound topic set is **exactly** the
      enumerated set in §10.0 (`{qa.intent.v1, qa.answer.v1,
      nlp.event.v1, nlp.alert.v1, nlp.gossip.v1, nlp.prober.v1,
      qa.context_extension.v1, predict.request.v1, data.request.v1}`).
      Today the claim is in prose; this test makes it executable.
- [x] **§10.10 graceful degradation matrix.**
      `test_degradation_matrix_every_failure_class_has_user_visible_template`
      walks `degradation_matrix.yaml` and asserts every failure class
      has a corresponding closed Turkish template AND a `meta.*`
      reason code from the §10.31.9 enum.
- [x] **§10.11 wire schemas.**
      `test_wire_schemas_additional_properties_false` walks every
      `qa.*.v1.json` / `nlp.*.v1.json` schema and asserts
      `additionalProperties: false` at every nested object level (not
      just root). The current §10.11 claim is root-only; this test
      catches the residual class.
- [x] **§10.12 caching.**
      `test_cache_key_does_not_depend_on_pii` runs a 200-row corpus
      where the same intent is asked with vs. without PII (phone
      number, email, name in the question body unrelated to the
      football query) and asserts the L0 cache key is byte-identical.
      Closes the privacy-leak class where a cache hit reveals another
      user's question shape.
- [x] **§10.14 observability.**
      `test_telemetry_no_pii_in_event_body` walks a 500-row PII-spiked
      corpus through the NLP pipeline and asserts no event body emitted
      to `telemetry.v1` contains any of the §10.21.7 PII patterns
      (post-redaction). Today §10.14 says "PII-clean" in prose.
- [x] **§10.16 calibration.**
      `test_degraded_flag_propagates_to_answer` runs a 100-row corpus
      where the upstream consensus carries `degraded=true` and asserts
      every `qa.answer.v1` body carries the §10.16-mandated disclaimer
      text byte-for-byte. Closes the "calibration awareness" claim
      that today is a §10.20 DoD bullet without a test.
- [x] **§10.18 evaluation harness.**
      `test_eval_harness_corpus_is_pii_clean` runs the §10.21.7 PII
      detector over the eval corpus itself and asserts zero matches.
      Defends against a leaked production sample contaminating the
      corpus during the §10.32.14 quarterly curation cycle.
- [x] **§10.21.8 citation HMAC.**
      `test_citation_hmac_rejects_tampered_citation` mutates the
      citation block in 200 sampled answers (single-byte flip in the
      `prediction_id` field, suffix swap, timestamp drift, signer-id
      swap) and asserts every mutation is rejected by the verifier.
      Today the §10.21.8 claim is "HMAC verified"; this proves it
      against a real adversarial set.
- [x] **§10.22 messy-Turkish floor.**
      `test_messy_turkish_floor_corpus` runs a 1,000-row real-world
      messy-Turkish corpus (deduped, PII-scrubbed, two-reviewer signed
      off) end-to-end and asserts intent_id top-1 ≥ 0.92 and entity
      top-1 ≥ 0.88, refusal-rate ≤ 5%. Caps regressions in CI.
- [x] **§10.23 production-serving floor.**
      `test_canary_promotion_gate_blocks_on_intent_drift` simulates a
      shadow-canary deploy where the new lexicon flips 3% of intent
      assignments and asserts the §10.31.15 canary gate blocks
      promotion with `nlp.alert.v1{kind=canary_promotion_blocked,
      severity=critical}`.
- [x] **§10.25 conversation lifecycle.**
      `test_time_travel_re_render_byte_identical` re-renders a 200-row
      historical conversation against the pinned pipeline-version
      snapshot and asserts byte-identical output. Today the §10.25
      claim is "time-travel safe"; this proves it.
- [x] **§10.26.5 modality firewall.**
      `test_counterfactual_past_never_routes_predict` runs a 100-row
      counterfactual-past corpus (`yenmeseydi ne olurdu?`,
      `oynamasaydı kazanır mıydık?`) and asserts NONE route to any
      `predict.*` intent. AST guard alone is not sufficient — this is
      the runtime proof.
- [x] **§10.27.6 abuse resilience.**
      `test_coordinated_abuse_signal_threshold` simulates a per-user
      query rate ramp and asserts the abuse signal trips at the
      configured threshold with the configured cooldown.
- [x] **§10.29.12 prediction-id determinism.**
      `test_prediction_id_re_derivation_rejects_swapped_envelope`
      crafts an envelope whose HMAC is valid but whose `prediction_id`
      does not match `sha256(match_id|market|request_id|
      calibration_version)` and asserts the NLP plane rejects it with
      `nlp.alert.v1{kind=prediction_id_mismatch, severity=critical}`.
- [x] **§10.30.10 slur-obfuscation defense.**
      `test_slur_obfuscation_corpus` runs a curated 200-row
      obfuscation corpus (asterisk / dot / leetspeak / cyrillic-
      homoglyph / U+2060-split) and asserts ≥ 99% detection AND ≤ 1%
      false-positive on a 200-row legitimate-text negative corpus.
- [x] **§10.31.8 output-grammar proofreader.**
      `test_output_grammar_proofreader_blocks_vowel_harmony_violation`
      injects a deliberately-broken template binding (vowel-harmony
      violation, consonant-mutation violation, wrong genitive marker,
      stem-final-vowel-deletion failure — one per case) into the
      template engine and asserts the proofreader gate blocks the
      answer with `nlp.alert.v1{kind=tr_output_grammar_violation,
      severity=error}` and falls back to the §10.31.9 grammar-fallback
      template.
- [x] **§10.31.11 outbound checksum.**
      `test_outbound_checksum_rejects_post_proofreader_mutation`
      simulates middleware mutation of the answer body between
      proofreader-sign and gateway-emit (single-byte flip, field
      reorder, length change) and asserts the gateway refuses to ship.
- [x] **§10.32.4 dialect normalization.**
      `test_dialect_intent_accuracy_per_class` runs a per-dialect
      stratified corpus (Aegean / Black Sea / Cypriot / German-diaspora
      / Dutch-diaspora / UK-diaspora, ≥ 80 rows each) and asserts
      intent top-1 ≥ 0.85 per dialect class. Caps the §10.32.4 closed
      table claim with a per-class regression gate.
- [x] **§10.32.12 cross-pod gossip.**
      `test_gossip_divergence_alert_fires_on_lexicon_skew` deploys two
      shadow pods with deliberately-skewed lexicon SHAs and asserts
      `nlp.alert.v1{kind=lexicon_state_divergence_detected,
      severity=critical}` fires within the 5-minute window AND the
      divergent pod is auto-quarantined.
- [x] **§10.32.q breaking-schema migration.**
      `test_breaking_schema_migration_dry_run` exercises the full
      6-phase 90-day deprecation runbook against a synthetic
      `qa.intent.v1 → v2` migration in a CI-only ephemeral environment
      and asserts every gate (frozen-snapshot read, dual-publish
      window, downgrade-negotiation parity, sunset-day rejection) is
      enforced.

## 10.33.3 Generic-and-broken-Turkish floor (binding)

The "messy Turkish" floor (§10.22) targets *academically wrong*
Turkish (typo, missing diacritic, dialect). The "broken Turkish" floor
below targets *generically broken* input that survives a casual visual
inspection but is structurally hostile to the pipeline. These are not
adversarial — they are what real users on real keyboards on real
browsers actually paste — but they are the residue the prior thirteen
passes treated as edge cases.

- [x] **Mojibake / double-decoded UTF-8.** Input frequently arrives as
      `Galatasarayâ€™Ä±n` (UTF-8 bytes interpreted as Latin-1 then
      re-encoded as UTF-8). Add `mojibake_recovery.py` that detects
      the double-decode signature (high frequency of `â€`, `Ã§`, `Ä±`,
      `Ã¶`, `Ã¼`, `Ä°`, `Ã¶`) and reverses it via `ftfy`-style
      heuristics under a closed allow-list of expected mis-encodings.
      cfg `nlp_mojibake_recovery_enabled=true` (added §10.33-knob-2).
      On recovery, emit `nlp.event.v1{kind=mojibake_recovered,
      original_sha256=..., recovered_sha256=...}` for telemetry.
      Test: `test_mojibake_recovery_corpus` (300 rows, Turkish-class
      mis-encoded as Latin-1).

- [x] **Smart-quote / em-dash / ellipsis paste.** WhatsApp / iOS /
      macOS auto-correct injects U+2018, U+2019, U+201C, U+201D,
      U+2013, U+2014, U+2026 into pasted Turkish football queries. The
      §10.32.5 apostrophe spec assumes U+0027. Normalize MUST collapse
      U+2018/U+2019 → U+0027, U+201C/U+201D → U+0022, U+2013/U+2014 →
      U+002D, U+2026 → `...` BEFORE the apostrophe parser runs.
      Test: `test_smart_quote_paste_normalizes_to_apostrophe` (50
      rows). The apostrophe-suffix detection must succeed identically
      on smart-quoted vs straight-quoted input.

- [x] **Vowel-harmony violation tolerance (input side).** §10.31.8
      handles output-side vowel-harmony violation. Input-side, the
      pipeline must **accept** vowel-harmony-violating user input
      (very common with loanwords and slang: `messajlerimi` instead of
      `mesajlarımı`) and route it correctly via charity-canonicalization
      against the lexicon. Today the typo-correction (§10.3) is
      Symspell-distance-based and does not weight stem matches over
      suffix matches; vowel-harmony violations on suffixes silently
      fail to canonicalize.
      **Spec:** charity-canonicalization scores stem-distance × 3 +
      suffix-distance × 1 (cfg `nlp_charity_stem_weight=3`,
      `nlp_charity_suffix_weight=1`, added §10.33-knob-3) and accepts
      the candidate iff total weighted distance ≤ 4. Test:
      `test_vowel_harmony_input_charity` (120 rows of harmony-violating
      real input asserts ≥ 90% canonicalization).

- [x] **Mixed-case shouting / SpongeCase / iNvErTeD case.**
      Auto-casefold (§10.1) handles `GALATASARAY` → `galatasaray` and
      `galatasaray` → `galatasaray` but the proofreader output-side
      template assumes a known input case to mirror back; with
      SpongeCase input (`gAlAtAsArAy`) the answer template currently
      mirrors back the un-canonicalized form for proper-noun slots.
      **Correction:** §10.7 template engine uses the **canonical**
      proper-noun form from the lexicon for output, never the user's
      input case. Test: `test_template_proper_noun_canonical_case`
      (40 rows of weird-cased proper noun input asserts byte-identical
      output regardless of input case).

- [x] **Trailing / leading invisible whitespace from copy-paste.**
      Browser select-copy from rich-text widgets injects U+00A0 (NBSP),
      U+2009 (thin space), U+202F (narrow NBSP), U+3000 (ideographic
      space) into pasted text. Today these survive normalize and
      become silent token-boundary disruptors: `Galatasaray\u00A0Fenerbahçe`
      tokenizes as one token, not two.
      **Correction:** Normalize collapses every Unicode `Zs` (space-
      separator) category to a single U+0020. cfg
      `nlp_collapse_unicode_spaces=true` (added §10.33-knob-4).
      Test: `test_unicode_space_collapse` (60 rows, every space-class
      character asserted to fold).

- [x] **Dotted-i / dotless-i confusion at word boundary.**
      §10.21.5 handles confusables; this is the *Turkish-specific*
      class where `İstanbul` typed on a non-Turkish keyboard becomes
      `Istanbul` (ASCII I), and the user expects both to resolve to
      the same canonical entity. Today §10.3 typo correction handles
      stem-internal but not word-initial. The lexicon must have
      bi-directional aliases for every proper-noun starting with `İ`.
      **Correction:** Boot probe asserts every lexicon entry starting
      with `İ` has an `I`-prefixed alias AND every entry starting with
      `I` has an `İ`-prefixed alias. Mismatch refuses boot. Test:
      `test_lexicon_dotted_dotless_i_bidirectional`.

- [x] **Keyboard-layout slip patterns (Q vs F).** Turkish has two
      official keyboard layouts (Q = QWERTY-Turkish, F = Turkish F).
      A user typing on layout F who thinks they're on Q produces a
      consistent character-substitution pattern (and vice versa).
      §10.26.3 mentions IME but doesn't specify the QF-slip table.
      **Spec:** Maintain `tr_keyboard_layouts.yaml` with the QF
      character-substitution map. The §10.3 typo corrector tries the
      QF-inverse of the input as an additional candidate when
      Symspell-distance-1 yields no lexicon hit. cfg
      `nlp_qf_layout_slip_enabled=true` (added §10.33-knob-5). Test:
      `test_qf_layout_slip_corpus` (80 rows of real QF-slipped input
      asserts ≥ 80% canonicalization to the lexicon).

- [x] **Apostrophe-vs-suffix collision on imported player names.**
      §10.32.5 covers Turkish proper nouns. Imported player names
      with embedded apostrophes (`O'Neill`, `D'Ambrosio`, `N'Golo`)
      collide with the §10.32.5 apostrophe-as-suffix-marker rule.
      **Correction:** Maintain a closed `proper_noun_internal_apostrophe.yaml`
      whitelist of entity-internal apostrophes. The §10.32.5 spec is
      extended: an apostrophe is treated as suffix-marker iff the
      pre-apostrophe substring is **not** in the internal-apostrophe
      whitelist. Test:
      `test_internal_apostrophe_player_names_corpus` (60 rows of
      imported-player-name queries asserts no spurious suffix-split).

- [x] **Number-word vs digit collision in voice-typed input.**
      §10.30.8 ties this to voice-modality but does not specify the
      ambiguity in numerically-named contexts: `"on bir"` (eleven) vs
      `"on, bir"` (ten, one) vs `"on 1"` vs `"11"` vs `"on1"` (a real
      typo class). The closed table must enumerate the resolution per
      voice-modality flag value.
      **Correction:** Closed `numeric_voice_disambiguation.tr.yaml`
      table mapping every (modality, surface_form) pair to a resolved
      digit. Test: `test_numeric_voice_disambiguation` (100 rows
      across all 4 modalities × 5 surface forms).

- [x] **Emoji + ZWJ sequence handling in player nicknames.**
      Player nicknames in fan posts include emoji (`Mertens 🐉`,
      `Mauro 👑`) and emoji-ZWJ sequences (`👨‍👨‍👦`). Today emoji
      survive the §10.1 normalize but are treated as content tokens
      by the entity extractor, polluting span boundaries.
      **Correction:** Normalize strips `So` (symbol-other) and `Sk`
      (symbol-modifier) categories AND every emoji-ZWJ sequence
      (sequence detected via the official Unicode emoji-data file
      pinned at `xops/lint/unicode_emoji_pin.txt`). cfg
      `nlp_strip_emoji=true` (added §10.33-knob-6). Test:
      `test_emoji_strip_preserves_entity_spans` (50 rows).

- [x] **Right-to-left text injection in usernames / mentions.**
      Bidi controls (U+202A..U+202E, U+2066..U+2069) covered above
      under §10.33.1. This item adds the **`@username`** mention class
      where the username itself contains adversarial Bidi controls
      that can flip a quoted opponent name. Mention parser rejects any
      `@token` that contains `Cf` characters with
      `nlp.alert.v1{kind=mention_bidi_attack_blocked, severity=warn}`.

- [x] **Cross-paste boundary leak.** When a user pastes input from a
      mixed source (e.g. WhatsApp message + URL), the paste often
      contains a stray URL `https://...` that the §10.21.7 PII
      redactor leaves alone (URLs aren't PII) but that disrupts the
      §10.5 entity extractor and the §10.4 intent classifier.
      **Correction:** Normalize strips URLs (regex over `https?://\S+`,
      `www\.\S+`, `\S+@\S+\.\S+`) BEFORE classifier and emits a
      `nlp.event.v1{kind=normalize_url_stripped, count=N}` for
      telemetry. cfg `nlp_strip_urls=true` (added §10.33-knob-7).
      Test: `test_url_strip_preserves_intent` (80 rows).

- [x] **Generic-broken JSON/code-fence paste.** Power users sometimes
      paste a multi-line JSON or markdown-code-fenced block thinking
      the system will reason about it. Today the pipeline tries to
      classify the intent of the entire blob, occasionally
      hallucinating an entity match against `"team": "Galatasaray"`.
      **Correction:** A **structured-input refusal** stage runs
      AFTER URL strip and BEFORE classifier: input that contains a
      code-fence (` ``` `) or that parses as valid JSON/YAML/XML is
      short-circuited to closed Turkish refusal `meta.structured_input_refused`
      (added to the §10.31.9 refusal enum) with telemetry. Test:
      `test_structured_input_refusal_corpus` (40 rows of JSON / YAML /
      XML / markdown-fenced paste).

## 10.33.4 Adversarial test corpus discipline (binding)

- [x] **Fixed-seed hypothesis profile per corpus.** Every adversarial
      corpus introduced by §10.33 (~14 corpora across §10.33.1–§10.33.3)
      ships with a `corpus.yaml` declaring (a) seed for any random
      sampling, (b) sha256 of the canonical row set, (c) two-reviewer
      signoff, (d) PII-scrub verifier independent run. Boot probe
      walks `corpora/*/corpus.yaml` and refuses on missing fields.
- [x] **Per-corpus regression budget.** Each corpus has a regression
      threshold (e.g. mojibake corpus accepts ≤ 1% recall regression
      between consecutive lexicon promotions). CI gate
      `make verify.nlp-corpora` runs all 14 corpora and fails on
      threshold breach. Per-corpus drift telemetry to `nlp.event.v1`.
- [x] **Corpus-vs-training-set disjointness gate.** AST guard
      `test_corpus_disjoint_from_training_set` asserts no row in any
      §10.33 corpus appears in the §10.4 fastText training set. Today
      §10.18 enforces this for the eval corpus globally; this is the
      per-corpus gate.
- [x] **Quarterly refresh cadence.** Per the §10.32.14 lifecycle, every
      §10.33 corpus refreshes quarterly with the same PII-scrub +
      two-reviewer + diff-cap discipline. The 14th-pass corpora
      inherit the lifecycle.

## 10.33.5 Cross-language byte-parity additions (binding)

The §10.29 silent-failure floor introduced `tr_normalize_spec.json`
cross-language byte parity. The 14th pass adds five more parity gates
because every §10.33 normalize change must be implemented identically
in the Go gateway (`server/internal/sec/`) and the Python NLP
(`ai/nlp/`).

- [x] `confusables_spec.json` — the extended Mathematical Alphanumeric
      / Halfwidth-Fullwidth / Tag / Enclosed-Alpha confusables map.
- [x] `format_char_strip_spec.json` — the explicit allow-list /
      strip-list for Unicode `Cf` / `Cn` / `Co` / `Cs` categories.
- [x] `mojibake_recovery_spec.json` — the closed allow-list of expected
      mis-encoding signatures.
- [x] `tr_keyboard_layouts.yaml` — the QF-slip table (referenced by
      both Go gateway typo correction and Python NLP).
- [x] `pii_redaction_spec.json` — extended with URL, email, code-fence
      detection patterns added by §10.33.3.

For each: boot probe in BOTH languages computes the SHA of the spec
file, asserts equality, and refuses boot on mismatch with
`nlp.alert.v1{kind=cross_lang_spec_sha_mismatch, severity=critical,
spec=<filename>}`. CI gate `make verify.nlp-cross-lang-parity` runs
the matching 1,000-row spec-corpus through both implementations and
asserts byte-identical output.

## 10.33.6 Triangle-test cfg knobs introduced by §10.33

(Land alongside the §10.19 cfg knobs in the same triangle commit.)

| Knob | Default | Purpose | Owner spec |
|---|---|---|---|
| `nlp_runtime_locale` | `tr_TR.UTF-8` | Pin process locale; refuse-on-mismatch boot probe | §10.33.1 |
| `nlp_mojibake_recovery_enabled` | `true` | Toggle mojibake recovery stage | §10.33.3 |
| `nlp_charity_stem_weight` | `3` | Charity-canonicalization stem weight | §10.33.3 |
| `nlp_charity_suffix_weight` | `1` | Charity-canonicalization suffix weight | §10.33.3 |
| `nlp_collapse_unicode_spaces` | `true` | Fold `Zs` category to U+0020 | §10.33.3 |
| `nlp_qf_layout_slip_enabled` | `true` | QF-keyboard-slip typo candidate | §10.33.3 |
| `nlp_strip_emoji` | `true` | Strip `So`/`Sk` + emoji-ZWJ sequences | §10.33.3 |
| `nlp_strip_urls` | `true` | Strip URLs before classifier | §10.33.3 |
| `nlp_structured_input_refusal_enabled` | `true` | Short-circuit JSON/YAML/code-fence paste | §10.33.3 |
| `nlp_charity_max_total_distance` | `4` | Cap on weighted charity distance | §10.33.3 |
| `nlp_corpus_drift_threshold_pct` | `1.0` | Per-corpus regression budget | §10.33.4 |

## 10.33.DoD Definition of Done (binding addition to §10.20)

- [x] **All `[ ]` in §10.33.1 ticked.** Every wrong-assumption
      correction landed AND every cited test passes on real
      adversarial corpus.
- [x] **All `[ ]` in §10.33.2 ticked.** Every missing-proof-test added
      AND CI-gated.
- [x] **All `[ ]` in §10.33.3 ticked.** Every generic-broken-Turkish
      class handled AND tested.
- [x] **All `[ ]` in §10.33.4 ticked.** Adversarial corpus discipline
      gates green.
- [x] **All `[ ]` in §10.33.5 ticked.** Cross-language byte-parity
      additions green; both Python and Go boot probes refuse on spec
      SHA mismatch.
- [x] **All `[ ]` in §10.33.6 cfg knobs landed.** Documented in
      `xops/env/.env.example`; defaults reviewed; per-knob test
      coverage.
- [x] **`make verify.nlp-cross-lang-parity` green.** All five extended
      specs round-trip byte-identical between Python NLP and Go
      gateway on the 1,000-row corpus.
- [x] **`make verify.nlp-corpora` green.** All ~14 §10.33 adversarial
      corpora pass the per-corpus regression threshold.
- [x] **§10.20 DoD aggregator extended.** §10.20 (in `00-baseline.md`)
      adds DoD item 31: "All `[ ]` in §10.33.DoD ticked." This file's
      DoD bullet must flip to `[x]` in lockstep with the §10.20 item
      31 flip.
- [x] **Tracker row + version bump.** `make track.add PHASE=10
      STATUS=in-progress NOTE="§10.33 14th-pass landed: <summary>"`
      AND `make version.bump COMPONENT=docs LEVEL=minor NOTE="§10.33
      14th-pass binding addendum"` in the same commit, per AGENTS.md
      §3.3 + §6.1.
- [x] **Phase 10 rollup checkbox** in
      [`docs/planning/ROADMAP.md`](../../planning/ROADMAP.md) Phase 10
      stub flips to `[x]` once §10.0–§10.33 are all green (this
      §10.33.DoD plus every prior §10.X.DoD).

## 10.33.7 Cross-phase notes (informational)

How §10.33 interacts with adjacent phases — informational only; the
binding contracts live in the cited anchor docs.

- **Phase 7 (security input plane).** §10.33.5 cross-language parity
  extensions tighten the Go-gateway-vs-Python-NLP divergence class
  Phase 7 introduced. The two implementations share spec files in
  `ai/swarm/sdk/schemas/` (or the equivalent post-Pivot path) and
  must refuse boot together. Phase 7's `sec.input.v1` schema does not
  change; only the normalize spec the gateway runs *before* publishing
  to `qa.request.v1` is widened.
- **Phase 9 (API gateway).** No new gateway endpoints. The
  `meta.structured_input_refused` and `meta.code_switched_unsupported_at_v1`
  templates added by §10.33 use the existing RFC 7807 error shape
  Phase 9 codified. Per-intent SLO classes (§10.31.12) absorb the new
  refusal classes under the existing `slo_fast` budget.
- **Phase 8 (operator console).** Adds visualisation surfaces for the
  new `nlp.event.v1` kinds (`mojibake_recovered`, `bidi_control_stripped`,
  `apostrophe_inferred`, `diaspora_code_switch_observed`,
  `normalize_url_stripped`, `mention_bidi_attack_blocked`,
  `cross_lang_spec_sha_mismatch`). Phase 8 inherits the kind-
  discriminated event shape unchanged.
- **Phase 11 (compute).** §10.33 changes are CPU-only — no GPU/NPU
  dependency. Charity-canonicalization stays Symspell-based.
- **Phase 13a (LeagueCatalog + lexicon).** §10.33.1 (apostrophe-
  absent disambiguation, dotted/dotless-i bidirectional aliases) and
  §10.33.3 (internal-apostrophe whitelist) impose new boot probes on
  the lexicon emitter. Phase 13a inherits these as additional gates
  on the lexicon promotion pipeline.
- **Phase 16 (datasource → swarm emitter).** No new feeds. The
  lexicon-promotion canary gate (§10.31.15) absorbs the additional
  parity tests from §10.33.5 unchanged.
- **Phase 19 (league readiness).** No interaction.
- **Phase 20 (monetization).** No interaction (NLP is tier-blind per
  §10.0 doctrine).

## 10.33.8 Open questions / explicit non-goals

Documenting what §10.33 deliberately does **not** address, so a
hypothetical 15th pass starts with the right scope:

- **Speech-to-text quality of the upstream voice ASR is out of scope.**
  §10.33 handles *what arrives* in `qa.request.v1` regardless of
  modality but does not propose a new ASR vendor or model. The
  voice-modality flag plus §10.30.8 punctuation-word stripping plus
  §10.33.3 number-word disambiguation are the contract.
- **Translation of non-Turkish input to Turkish is out of scope.**
  §10.33.1 routes diaspora code-mixing to a closed apology template
  at v1; v2 may add a translation stage but that is a separate
  Phase 10 (or successor-phase) addendum.
- **Real-time-LLM-augmented disambiguation is out of scope.** Every
  disambiguation in §10.33 is closed-table or lexicon-driven.
  §10.8 humanizer remains opt-in polish only.
- **Pluralisation of refusal templates beyond the §10.31.9 rotation
  pool is out of scope.** §10.33 introduces 2 new reason codes
  (`structured_input_refused`, `code_switched_unsupported_at_v1`) into
  the existing pool.
