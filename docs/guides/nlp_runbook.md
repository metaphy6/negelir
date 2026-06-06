# NLP Runbook — Turkish Input Quality Dashboard

> **Audience:** operators, on-call engineers.
> **Anchor:** `docs/design/phase10/sections/22-turkish-input-robustness.md` §10.22.13.
> This runbook is operator-facing and describes the dashboard, alert thresholds,
> and corrective actions for Turkish NLP input-quality drift.

## Prerequisites

- `make env` — `xops/env/.env` must exist and be populated.
- Prometheus / Grafana access for the Negelir observability stack.
- Local access to the repository for lexicon review and root-cause inspection.

## Key metrics

Use these metrics as the dashboard foundation:

- `nlp_input_repair_density` — histogram of repairs per query token.
- `nlp_input_repair_total{class=...}` — repair counts by rule class.
- `nlp_disambiguation_offered_total{cause=...}` — ambiguity resolution offers.
- `nlp_offensive_input_total{class=...}` — offensive-input detection.

The phase baseline is `cfg.nlp_repair_density_p95_max=0.5`.

## Dashboard panels

Create operator-facing panels that show:

- `nlp_input_repair_density` p50/p95 and tail trend.
- Top repair classes from `nlp_input_repair_total`.
- `nlp_disambiguation_offered_total` by cause.
- `nlp_offensive_input_total` by class.
- `nlp_input_repair_density` across tenant or league slices, if available.

## Repair-density alert triage

- **Alert** when `nlp_input_repair_density` p95 exceeds `0.5` for 15 minutes.
- **Page** on sustained drift: p95 > `0.6` for 30 minutes or repeated daily growth.
- **Review** if any of these repair classes spike by more than 3× baseline:
  `code_switch_token`, `dialect_expanded`, `abbreviation_expanded`, `apostrophe_inserted`,
  `particle_repaired`.
- **Verify** immediately if `nlp_offensive_input_total{class=severe_threat}` rises above zero
  for more than 5 minutes. Confirm whether the input is user intent or abusive language.
- **Escalate** if `nlp_disambiguation_offered_total{cause=ambiguous_match_pair}` climbs
  while overall intent confidence drops.

## Repair-density triage by class

This section points operators at the §10.22.13 telemetry counters extended in
§10.24 and helps distinguish a narrow rule/lexicon gap from wider input drift.

- `nlp_input_repair_total{class=...}` is the primary Phase 10.24 counter family.
  The extended classes include:
  `suffix_harmony_repaired`, `repeated_char_normalized`, `digit_letter_confusable_folded`,
  `turkish_i_normalized`, `multi_question_split`, `negation_disambiguated`,
  `compound_name_normalized`, `honorific_normalized`, `emoji_signal_ignored`,
  `social_handle_hygiene`, `score_numeric_disambiguated`,
  `garden_path_backtracked`, and `pathological_input_handled`.
- Use the `nlp_input_repair_density` p50/p95 trend together with class-level
  counts to decide whether the drift is caused by a single noisy input class.
- Prioritize follow-up on spikes in `digit_letter_confusable_folded` and
  `turkish_i_normalized` for orthographic noise, `compound_name_normalized` and
  `honorific_normalized` for entity-resolution gaps, and
  `garden_path_backtracked` for phrase-structure ambiguity.
- When a single repair class dominates the spike, treat it as a narrow
  lexicon or rule gap; when multiple classes rise together, the issue is more
  likely a broader Turkish-input distribution or training drift.
- For Phase 10.24-specific triage, prefer a narrow alias or hygiene rule fix
  over broad threshold relaxations.

## Morphology ambiguity-rate triage

- Watch `nlp_morph_ambiguity_rate_high` and related ambiguity telemetry.
- If the rate exceeds the configured threshold, inspect whether proper-noun
  bypass or gazetteer cross-check thresholds are too aggressive.
- Confirm the offending queries emit `nlp.event.v1{kind=morph_parse_ambiguous}`
  and that the fallback path is not silently discarding valid team or player
  names.
- Adjust the morphology ambiguity floor only after a review of the closed
  gazetteer tables in `ai/nlp/lexicon` and the parse confidence thresholds.

## Voice-path diacritic-aggression triage

- Watch `nlp_voice_path_diacritic_overaggressive` and voice-path restoration
  rates in Grafana.
- If this alert fires, verify whether voice input is being over-normalized and
  whether the system is restoring diacritics in cases where the user likely
  intended a bare ASCII query.
- Tune the voice-path thresholds, not the downstream intent classification,
  unless the signal is consistently misrouted.
- Confirm that `autocorrect_cascade_repaired` and `asr_input_auto_detected`
  events are still emitted for diagnostics.

## Lexicon PR-flood incident response

- If `nlp_lexicon_pr_diff_oversize` or `nlp_lexicon_typo_squat_detected` is
  raised, pause lexicon merges and review the PR diff size and canonical ID
  provenance.
- Validate every alias against the closed canonical table and confirm there are
  at least three provenance entries for each new alias when required.
- Run `make verify.nlp-lexicons` and `make nlp.lexicon-build` after fixing the
  alias set.
- Prefer narrow lexicon delta fixes over broad new alias additions.

## Envelope-HMAC key rotation

- If `nlp_answer_envelope_signature_invalid` alerts, rotate the answer envelope
  HMAC key with `make nlp.rotate-answer-hmac-key`.
- Maintain the dual-acceptance grace window so answers signed with the previous
  key remain valid for a short overlap period.
- Confirm that `qa.answer.v1.envelope_signature_key_id` is populated and that the
  produced `envelope_signature` verifies before enforcement is tightened.

## Lexicon swap

If the issue is lexicon-related, update `ai/nlp/lexicon/_aliases_delta.tr.yaml`
with the new alias or dialect mapping. Prefer narrow alias additions over broad
rule relaxations.

1. Confirm the metric spike in Grafana and examine the `nlp_input_repair_density`
   tail panel.
2. Open the sampled audit slice for the affected time window and inspect repair classes.
3. Determine whether the spike is caused by a lexicon gap, new dialect/code-switch usage,
   or a purely noisy input burst.
4. If the issue is lexicon-related, update `ai/nlp/lexicon/_aliases_delta.tr.yaml`
   with the new alias or dialect mapping.
5. Run `make verify.nlp-lexicons` to validate the lexicon change.
6. Build the updated lexicon with `make nlp.lexicon-build` and confirm the dashboard
   normalizes the sample query properly.

## Intent rollback runbook

When an intent retrain or model drift incident occurs, rollback the intent
package and confirm that any in-flight summaries still use the prior calibration.

1. Identify the offending intent version via `nlp.intent.promote` metadata and
   `nlp.event.v1{kind=nlp_intent_rolled_back}` events.
2. Promote the previous intent package into canary mode and monitor for
   `nlp_canary_rolled_back` warnings.
3. If a rollback is required, keep the humanizer and proofreader versions
   unchanged until the new intent package is validated.
4. Document the rollback in the incident ticket and update the model regression
   blockers for the next training cycle.

## Right-to-erasure runbook

If a user exercises deletion rights, ensure the NLP audit trail and spool
data propagate the erase across the observability pipeline.

1. Verify `qa.request.v1` and `qa.answer.v1` audit bundle references for the
   request ID targeted by the erasure.
2. Remove or redact the corresponding spool payload entries and replace
   `sanitized_text` with `sanitized_text_sha256` in the spooled envelope.
3. Confirm the bus replay path can still correlate the erased request via
   `request_id` while preserving the privacy contract.
4. If the original text is unavailable during replay, drop the envelope and
   emit `nlp.alert.v1{kind=nlp_spool_replay_text_unavailable}`.

## Compliance ban-list operator workflow

Use the compliance ban-list to block or degrade content in regulated
jurisdictions without changing the underlying intent model.

1. Review the current ban-list overlay and the per-tenant compliance rules in
   `cfg.nlp_compliance_reload_s`.
2. When a new phrase or content class must be banned, add it to the overlay and
   validate it with `make nlp.template-lint` and the relevant policy tests.
3. Reload the compliance overlay with the configured watch path.
4. Monitor `nlp.alert.v1{kind=compliance_refusal_triggered}` and confirm the
   rendered output uses the compliance-safe template.

## Cold-start consensus-smoke triage

When boot latency or readiness issues occur, validate the NLP boot consensus
smoke path before permitting production traffic.

1. Check `nlp.event.v1{kind=cold_start_stage}` events to see which boot stage
   last completed.
2. If boot stage 6 is not reached within `cfg.nlp_boot_budget_s`, the pod stays
   503 and emits `nlp.alert.v1{kind=nlp_cold_start_timeout}`.
3. Verify that the readiness probe is not satisfied until the final Jinja warm
   stage completes.
4. Use the consensus-smoke signal to decide whether to restart the pod or
   accept a longer boot-budget window for the current release.

## GPU-lease leak recovery

If the humanizer subprocess or GPU lease path fails, recover without leaking
the lease or dropping unrelated requests.

1. Detect `nlp.event.v1{kind=humanizer_disabled}` or
   `nlp.alert.v1{kind=humanizer_subprocess_died}` events.
2. Gracefully stop accepting new humanizer requests while preserving template
   fallbacks.
3. Drain in-flight requests and release the GPU lease before restarting the
   subprocess.
4. Confirm the next pod startup does not reuse a stale lease token.

## Disaster recovery drill

Use a staging pod and a copy of the lexicon feed to rehearse a full lexicon corruption
recovery without impacting production.

1. Corrupt a copy of the primary lexicon snapshot in the staging pod's directory.
2. Confirm the staging pod enters safe mode and emits an `nlp_safe_mode_active`
   alert while staying healthy enough to serve readiness probes.
3. Restore the primary lexicon snapshot and wait for the next
   `cfg.nlp_lexicon_reload_s + 5s` cycle.
4. Confirm the staging pod exits safe mode and resumes serving from the recovered
   primary lexicon.
5. Run `make nlp.dr-drill --confirm` to create the report stub before the drill,
   then update `docs/reports/nlp_dr_drill_YYYY-Q.md` with the drill outcome.
6. Record the drill outcome in `docs/reports/nlp_dr_drill_YYYY-Q.md`.

## Canary rollout playbook

Use canary pods and shadow-mode telemetry to stage new NLP changes before
wider promotion.

1. Enable canary routing with `NEGELIR_NLP_CANARY_POD=1` and set the rollout
   percentage with `NEGELIR_NLP_INTENT_MODEL_CANARY_PCT`.
2. Enable shadow-mode with `NEGELIR_NLP_INTENT_SHADOW_MODE=on` and a sampling
   fraction via `NEGELIR_NLP_SHADOW_SAMPLE_RATE`.
3. Monitor `nlp_canary_rolled_back` warnings and `nlp_intent_shadow_mode`
   telemetry for disagreement rate drift.
4. Keep canary traffic narrow until the disagreement rate is consistently below
   `cfg.nlp_canary_max_disagreement_rate` and confidence drift is within
   `cfg.nlp_canary_max_confidence_drift`.
5. Promote the change only after the canary has accrued the minimum required
   shadow hours and no regression is observed.

## Weekly-eval triage

Use the weekly evaluation pipeline to catch regressions before they affect
production traffic.

- Confirm the weekly NLP evaluation workflow completes without regressions.
- Investigate `nlp_weekly_eval_regression` warnings immediately.
- If the weekly evaluation identifies a drift, open a fix PR and mark the
  issue with `phase:10` and `cve`/`nlp` labels as appropriate.
- Use the weekly evaluation results to tune the `nlp.summary` and
  `nlp.fairness` thresholds.

## Cost-budget tuning

Keep serving cost within the Phase 10 budget by tuning the model and
intake parameters.

- Track `nlp_humanizer_request_rate` and `nlp_max_humanizer_tokens_per_tenant_per_min`.
- Adjust `cfg.nlp_intake_workers` only after verifying CPU and latency impact.
- Use the `nlp_humanizer_pod_budget_exceeded` alert as the first signal to
  throttle new tenant intake or reduce humanizer usage.
- Prefer incremental threshold changes rather than broad capacity bumps.

## Dependency CVE response

The NLP plane must detect and respond to dependency advisories for any pinned
Python package that directly or transitively affects the NLP execution path.

- Run `xops/ci/nlp_cve_scan.yml` daily. It installs `pip-audit` and scans
  `ai/requirements.txt` to detect active advisories for the current pinned deps.
- If any advisory is classified as **Critical** or **High**, open a GitHub issue
  tagged `phase:10` and `cve`, then page the on-call channel.
- Document the response timelines here:
  - **Critical (CVSS ≥ 9.0):** patch ship target ≤ 24h.
  - **High (CVSS 7.0–8.9):** patch ship target ≤ 7 days.
  - **Medium / Low:** bundle into the next regular dependency-bump cycle.
- Keep `ai/nlp/security/mitigations.md` updated with the defense-in-depth measures
  that reduce exposure for the dependency classes used by the NLP plane.
- If the advisory affects a transitive runtime library, treat the closest direct
  dependency as the owner for response coordination.

## Feed and key-rotation events

If you observe an `nlp_lexicon_feed_signature_invalid` alert:

- Confirm `cfg.nlp_lexicon_source` and inspect the feed delivery path.
- If the feed is untrusted, temporarily fall back to `file` mode and continue investigation.
- Rotate or replace the HMAC key only after verifying the signing artifact and
  the feed schema version.

## Code-switch and dialect drift response

- For code-switch or dialect spikes, prefer a targeted lexicon alias fix over broad
  rule relaxations.
- Confirm whether the spike is driven by an entity gap (team/player name) or by a
  general dialect/abbreviation normalization failure.
- Add new dialect aliases to `ai/nlp/lang_tr/dialect.tr.yaml` only when the term is
  genuinely Turkish-style and does not create a false positive for foreign names.
- Keep entity-specific dialect aliases in `ai/nlp/lexicon/dialects.tr.yaml` and verify
  disjointness with general dialect rules using `test_nlp_dialect_and_entity_dialect_tables_are_disjoint`.
- If the spike persists after lexicon and rule updates, consider whether a new intent
  or query family belongs in the application surface instead of the NLP rules.

## Runbook maintenance

- Keep this guide aligned with the current metrics definitions in
  `docs/design/phase10/sections/22-turkish-input-robustness.md`.
- Update thresholds when `cfg.nlp_repair_density_p95_max` or related repair classes
  are changed in code or config.
- Add a Grafana panel for any new repair class introduced in the `nlp_input_repair_total`
  family.
