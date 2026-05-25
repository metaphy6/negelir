# `docs/design/phase8/` — Phase 8 detail

> **Why this folder exists.** Phase 8 (Self-Maintenance Agents (Ops Console, Auto-Scaler, Backup + Off-Host DR, DLQ Supervisor, Watcher Graduation)) grew
> past ROADMAP's review threshold and was carved out into one file
> per sub-section, mirroring the Phase 10 pattern at
> [`../nlp/sections/`](../nlp/sections/). Content here is **binding**
> — the ROADMAP §8 stub is now a pointer that delegates to this
> folder.
>
> **Editing rules.**
> 1. Every `[ ]` / `[x]` checkbox flip lives in **this** folder, in
>    the per-section file that owns the item. The ROADMAP §8
>    stub carries only the phase-rollup checkbox.
> 2. Any non-trivial edit triggers `make version.bump COMPONENT=docs
>    LEVEL=minor NOTE="..."` in the same commit (per AGENTS.md §6.1).
> 3. Cross-phase references are authoritative against
>    [`../../planning/ROADMAP.md`](../../planning/ROADMAP.md) and the
>    matching `docs/design/*.md` anchors. Fix this folder if a claim
>    drifts — never silently re-plan a sister phase.
> 4. No rename of these files without explicit human request (URL
>    stability); no deletion of a binding `[ ]` item; no weakening
>    of a Definition-of-Done gate.

## Layout

| Source | File | Theme |
|---|---|---|
| §8.1 | [`sections/01-ops-console.md`](sections/01-ops-console.md) | Ops console (`ops_console` publisher of `maint.event.v1`) |
| §8.2 | [`sections/02-auto-scaler-agent.md`](sections/02-auto-scaler-agent.md) | Auto-scaler agent (`maint.scaler.v1`) |
| §8.3 | [`sections/03-backup-retention-agent.md`](sections/03-backup-retention-agent.md) | Backup / retention agent (`maint.backup.v1`) |
| §8.4 | [`sections/04-source-watcher-sdk-llm-summarizer-graduation.md`](sections/04-source-watcher-sdk-llm-summarizer-graduation.md) | Source-watcher SDK + LLM-summarizer graduation |
| §8.5 | [`sections/05-dlq-supervisor.md`](sections/05-dlq-supervisor.md) | DLQ supervisor (`maint.dlq.v1`) |
| §8.6 | [`sections/06-internal-schema-drift-sentinel.md`](sections/06-internal-schema-drift-sentinel.md) | Internal schema-drift sentinel (`maint.schema.v1`) |
| §8.7 | [`sections/07-pattern-false-positive-feedback-loop.md`](sections/07-pattern-false-positive-feedback-loop.md) | Pattern false-positive feedback loop (`maint.sec.v1` slice) |
| §8.8 | [`sections/08-sec-denylist-sweeper.md`](sections/08-sec-denylist-sweeper.md) | Sec-denylist sweeper (`maint.sec.v1` slice) |
| §8.9 | [`sections/09-definition-of-done.md`](sections/09-definition-of-done.md) | Definition of Done |
| §8.10 | [`sections/10-liveness-leader-election-and-dead-mans-switch.md`](sections/10-liveness-leader-election-and-dead-mans-switch.md) | Liveness, leader-election, and dead-mans-switch |
| §8.11 | [`sections/11-maint-plane-backpressure-self-shedding.md`](sections/11-maint-plane-backpressure-self-shedding.md) | Maint plane backpressure & self-shedding |
| §8.12 | [`sections/12-disaster-recovery-off-host-backup-replication.md`](sections/12-disaster-recovery-off-host-backup-replication.md) | Disaster recovery & off-host backup replication |
| §8.13 | [`sections/13-fourth-pass-deep-revision-additions.md`](sections/13-fourth-pass-deep-revision-additions.md) | Fourth-pass deep-revision additions (model-artifact DR, plane storage cap, spool aging, restore version-invariant, pause/resume idempotency, key-compromise runbook) |
| §8.14 | [`sections/14-fifth-pass-deep-revision-additions.md`](sections/14-fifth-pass-deep-revision-additions.md) | Fifth-pass deep-revision additions (audit-log partitioning, per-file dump checksum manifest, `age` supply-chain pin, opsctl ACL + signed envelopes, DLQ recursion guard, ack trace propagation, schema-sentinel rps cap, trainer scale-target sole-writer, `pg_dump` nice + verify-PG version invariant, spool-flush dir lock + newest-first ordering) |
| §8.15 | [`sections/15-sixth-pass-deep-revision-additions.md`](sections/15-sixth-pass-deep-revision-additions.md) | Sixth-pass deep-revision additions (clock-source identity, sub-schema versioning, advisory-lock registry, operator-key lifecycle, audit-log row caps + integrity chain, K8s RBAC catalogue, shed-tier handover, DLQ-drop audit, scheduler noise-windows, verify-concurrency cap + offsite credential rotation + restore-verify forensic capture) |
| §8.16 | [`sections/16-seventh-pass-deep-revision-additions.md`](sections/16-seventh-pass-deep-revision-additions.md) | Seventh-pass deep-revision additions (registry-vs-config drift, ack-in-vacuum on spool flush, prune execution-order doctrine, ack metric cardinality, S3 multipart-upload-id TTL, Object-Lock boot probe, DLQ deny-prefix forward-compat, per-model VRAM footprint hints, maint-vs-sec topic crossover doctrine, fingerprint authentication strength, sec-plane backpressure symmetry, qa↔predict DLQ correlation, swarm.demo live-Redis profile, key-id derivation invariant, Phase-5 trainer prerequisite gate) |

## Reading order

1. The ROADMAP §8 stub (`docs/planning/ROADMAP.md`) — goal,
   dependencies, and rollup checkbox.
2. The earliest section file relevant to the area you're modifying.
   Later sub-sections often assume earlier ones are in force; if a
   later file's `Depends on` clause names another sub-section,
   re-read it first.
3. The Definition-of-Done sub-section (the one whose title contains
   *Definition of Done* or matching `DoD` rollup) — this is the
   gate that flips the rollup checkbox in ROADMAP.
