# NLP Disaster Recovery Runbook

> **Audience:** operators and on-call engineers responsible for Phase 10 Turkish NLP resilience.
> **Anchor:** `docs/design/phase10/sections/32-discourse-pragmatic-dialectal-operational-resilience.md` §10.32.17.

## Dry-run safety

All documented runbook commands support `DRY_RUN=true`. In dry-run mode, the command must print the intended action without mutating state.

Example:

```bash
DRY_RUN=true make nlp.lexicon-restore-from-snapshot SNAPSHOT_ID=... 
```

If the dry run is successful, repeat the same command without `DRY_RUN=true` to execute the recovery.

## Scenarios

### All-lexicon-corruption

Trigger:
- Cluster-wide lexicon load failures on every NLP pod.
- `nlp.event.v1{kind=lexicon_sha_verify_failed}` or repeated `nlp_safe_mode_active` alerts.

Operator action:
1. Verify the snapshot and restore candidate using the backup-agent snapshot ID from Phase 8.
2. Run dry-run first:

```bash
DRY_RUN=true make nlp.lexicon-restore-from-snapshot SNAPSHOT_ID=<snapshot-id>
```

3. If the dry run is clean, execute:

```bash
make nlp.lexicon-restore-from-snapshot SNAPSHOT_ID=<snapshot-id>
```

4. Confirm per-pod cold-start validation passes and the restored SHA tuple matches the expected lexicon hash before allowing pods back into gateway traffic.

### Intent-model-corrupt-on-all-pods

Trigger:
- All pods refuse to boot due to intent package SHA verification failure.
- `nlp.event.v1{kind=intent_model_sha_mismatch}` or `nlp.alert.v1{kind=intent_model_corrupt}`.

Operator action:
1. Identify the prior good intent package version from the compatibility matrix.
2. Dry-run the restore command:

```bash
DRY_RUN=true make nlp.intent-model-restore VERSION=<prior_sha>
```

3. Execute the rollback if dry-run output is correct:

```bash
make nlp.intent-model-restore VERSION=<prior_sha>
```

4. Validate that pods rejoin the gateway pool and that `nlp.event.v1{kind=humanizer_disabled}` is not active unless expected.

### Calibration-store-unreachable-extended

Trigger:
- Calibration store remains unreachable for more than one hour.
- Automatic fall-through to template-only answers is active per §10.10 degradation matrix.

Operator action:
1. Pin a known-good calibration snapshot to restore stable predictions.
2. Dry-run first:

```bash
DRY_RUN=true make nlp.calibration-pin SNAPSHOT_ID=<snapshot-id>
```

3. Run the pin command:

```bash
make nlp.calibration-pin SNAPSHOT_ID=<snapshot-id>
```

4. Confirm the system enters the 24h pinned-snapshot grace period and that live traffic remains non-degraded.

### Humanizer-LLM-version-drift

Trigger:
- Humanizer CPU-only parity tests fail after deploy.
- `nlp.event.v1{kind=humanizer_disabled}` or failed parity gate events.

Operator action:
1. Dry-run the rollback:

```bash
DRY_RUN=true make nlp.humanizer-rollback VERSION=<prior_sha>
```

2. Execute rollback when dry-run output is validated:

```bash
make nlp.humanizer-rollback VERSION=<prior_sha>
```

3. Re-run the CPU-only parity test and confirm the humanizer resume path is healthy.

## Verification

For every scenario:

- Use `DRY_RUN=true` before applying a recovery step.
- Confirm the intended recovery action is printed but not executed.
- After recovery, verify that the corresponding alert clears and the relevant `nlp.event.v1` or `nlp.alert.v1` condition returns to healthy.

## Notes

- Do not rely on this runbook if the impacted issue requires a different recovery path; follow the specific recovery instructions in the relevant section of `docs/guides/nlp_runbook.md` or the Phase 10 issue tracker.
- This guide is intended to be dry-run-safe and operator-friendly for Phase 10 DR scenarios.
