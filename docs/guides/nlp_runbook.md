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
