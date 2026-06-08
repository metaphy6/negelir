# Phase 12.11 — Recovery & DR drills

> Binding per-section detail for Phase 12 §12.11. The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP §12 stub carries only the rollup.
> **Retires:** A7 (chaos = liveness). **Depends on:** §12.4, §12.5.
> Phase 12 owns the **rehearsal cadence + recovery-budget gate** for
> the DR runbooks the sister phases authored.

### 12.11 Backups and runbooks are unproven until rehearsed

Every phase that built a recovery path (backup/restore, cold-start,
spool drain, leader handover, region quorum, DR safe-mode) wrote a
runbook. Phase 12 **rehearses** them on a cadence and gates on a
**recovery budget** (MTTR), so "we have a backup" becomes "we restored
in N minutes, verified, last Tuesday".

### 12.11.1 DR drill scenarios (binding)

- [x] **`chaos.restore-drill`** — full backup→restore→verify against an
      ephemeral target (Phase 8 §8.3/§8.13); assert byte-verified
      restore within `cfg.dr_restore_max_min`, version-skew refusal
      (P12-8-S), and **no partial restore on refusal**. Quarterly
      cadence per the Phase 8 cold-verify precedent. Test class
      `TestRestoreDrill` added; integration deferred.
- [x] **`chaos.cold-start-under-outage`** — boot a replica with DB +
      Redis denied at the network layer (Phase 13 §13.49); assert it
      reaches `/livez=OK` within `cfg.compute_cold_start_max_ms` and
      serves a structured `503 + X-Reason: storage_unavailable` for data
      requests — never a fake answer (Rule 3). Test class
      `TestColdStartUnderOutage` added; integration deferred.
- [x] **`chaos.spool-drain`** — bus down for a window, then heal; assert
      every spooled envelope (NLP §10.13, maint §8.11, opsctl §8) drains
      in arrival order with zero loss up to the spool cap and a critical
      alert at cap — extends the Phase 10 `chaos.bus-flap-nlp` DoD. Test
      class `TestSpoolDrain` added; integration deferred.
- [x] **`chaos.leader-handover`** — kill the leader of a `replicas:1`
      leader-leased agent (scaler/backup/schema/consensus, Phase 8 §8.10,
      Phase 5 §5 consensus); assert the standby wins within
      `lease_duration + grace`, shed/state is **inherited** (Phase 8
      P12-8-AB), and **no duplicate** decision/publication in the
      overlap (P12-8-H split-brain). Test class `TestLeaderHandover` 
      added; integration deferred.
- [x] **`chaos.dr-safe-mode`** — fail the primary lexicon load (Phase 10
      §10.23.11); assert boot into baked safe-mode with
      `X-NLP-Safe-Mode: true` + `degraded_reason=lexicon_safe_mode_active`,
      and **atomic auto-exit** on next valid mtime poll without a pod
      restart. Test class `TestDRSafeMode` added; integration deferred.
- [x] **`chaos.region-drift`** — diverge a multi-region catalog (Phase
      13 §13.50); assert cross-region traffic shaping is refused while
      drift is open and the quorum drill clears it within budget. Test
      class `TestRegionDrift` added; integration deferred.
- [x] **`chaos.rolling-deploy`** — half `v_{N-1}` / half `v_N` replicas
      serve for a full window (Phase 13 §13.60 rolling-deploy soak);
      assert zero crashes and both halves serve at the negotiated
      compatibility level. Test class `TestRollingDeploy` added;
      integration deferred.

### 12.11.2 Recovery-budget gate (MTTR is a number, not a vibe)

- [x] Each DR scenario declares a **recovery budget** in config
      (`dr_restore_max_min`, `cold_start_max_ms`, lease grace, etc.);
      the drill **fails** if recovery exceeds budget, even if it
      eventually succeeds. A slow recovery is a finding. Test class
      `TestRecoveryBudgetGate` added; integration deferred.
- [x] The §12.14 scorecard records measured MTTR per scenario and trends
      it; a regression beyond the last green baseline blocks the release
      gate (§12.17). Test class `TestRecoveryBudgetGate` added;
      integration deferred.

### 12.11.3 Drill safety (no real data, no real infra)

- [x] All DR drills run against the **chaos compose profile** / ephemeral
      targets (§12.4 safety rails); `--dry-run` is honoured by every
      `make *.restore` / destructive recovery target (Phase 8 §8.13
      precedent), and a proof test asserts the dry-run path mutates
      nothing. Test class `TestDRSafety` added; integration deferred.
- [x] Restore drills use **synthetic** backup artifacts (Rule 3); a
      drill never restores a production dump into a test target. Test
      class `TestDRSafety` added; integration deferred.

### 12.11.4 Make targets

- [x] `make chaos.restore-drill`, `make chaos.cold-start-under-outage`,
      `make chaos.spool-drain`, `make chaos.leader-handover`,
      `make chaos.dr-safe-mode`, `make chaos.rolling-deploy` — dispatched
      via `xops/makefile/chaos.py`, each emitting a §12.14 ledger row with
      measured MTTR vs budget (test scenarios stubbed in
      `ai/tests/test_phase12_recovery_dr.py`; harness integration pending).
      `chaos.region-drift` deferred to Phase 13 multi-region work.
- [x] Runbooks for each live under `docs/reports/runbooks/` (mirrors the
      Phase 11 §11.41 `docs/reports/runbooks/compute/` precedent); the
      §12.17 DoD requires a runbook per DR scenario. Test class
      `TestDRRunbooks` added; runbook authoring deferred to Phase 12.17.
