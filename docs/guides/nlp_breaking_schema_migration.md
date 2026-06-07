# NLP Breaking Schema Migration Playbook

> **Audience:** operators, release engineers, and Phase 10 NLP maintainers.
> **Anchor:** Phase 10 §10.32.17 — breaking-schema migration for `qa.answer.v1`.

## Overview

This playbook documents the exact steps for moving a Phase 10 NLP schema
from one additive-compatible version to a breaking new major version. It is
only used when the schema contract must change in a way that cannot be
handled by additive-only clients.

The migration is gated in six phases:

1. **T-90d: Deprecation announce**
   - Publish the migration goal and the planned schema version bump.
   - Enable dual emission for old and new schema via
     `cfg.nlp_qa_answer_dual_emit_enabled=true`.
   - Mark the old schema as deprecated with `deprecated_at_utc=<T+90d>`.
   - Capture client telemetry for schema-version pin distribution.

2. **T-60d: New-schema-default**
   - Bump `nlp_qa_answer_default_schema_version` to the new version.
   - Continue serving old schema to clients that explicitly pin the old
     version via Accept-pin semantics.
   - Trigger an alert if more than 1% of traffic still pins the old schema.

3. **T-30d: Sunset warning**
   - Add `Sunset: <T>` HTTP header to old-schema responses in accordance
     with RFC 8594.
   - Hard-map deprecated client domains to operator alerts so that the
     support team can proactively reach out before the cut-over.

4. **T-7d: Final preview**
   - Run `make nlp.deprecation-rehearsal` with the old schema disabled in
     dry-run mode.
   - This rehearsal validates eval, prober, and regression suites against
     the would-be cut-over behavior without mutating production state.

5. **T+0: Cut-over**
   - Remove the old schema from the live pipeline.
   - Clients still pinning the old version receive `426 Upgrade Required`
     with a Turkish error body explaining the upgrade path.
   - Continue a one-week grace window with
     `cfg.nlp_qa_answer_legacy_grace_enabled=true`.
   - During the grace window, old-schema responses are served from a
     frozen snapshot, not from the live pipeline, to ensure deterministic
     behavior and avoid production drift.

6. **T+7d: Frozen-snapshot tear-down**
   - Set `cfg.nlp_qa_answer_legacy_grace_enabled=false`.
   - Ensure all responses are served only in the new schema.
   - Verify that no client is still pinning the old schema.

## Operator checklist

- Confirm that `cfg.nlp_qa_answer_dual_emit_enabled` is enabled before
  the T-90d announcement.
- Verify the old schema is annotated with `deprecated_at_utc` and that
  telemetry is collecting schema pinning data.
- Run `make nlp.deprecation-rehearsal` at T-7d and confirm the rehearsal
  report passes without hard failures.
- During the cut-over week, monitor old-schema traffic and the `Sunset`
  header behavior.
- If `426 Upgrade Required` spikes, identify the client domains still
  pinning the old schema and reach out to them.
- After T+7d, validate that the old schema snapshot is disabled and that
  all production responses use the new schema.

## Related artifacts

- `cfg.nlp_qa_answer_default_schema_version`
- `cfg.nlp_qa_answer_dual_emit_enabled`
- `cfg.nlp_qa_answer_legacy_grace_enabled`
- `make nlp.deprecation-rehearsal`
- `qa.answer.v1` schema versions

