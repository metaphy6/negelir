# 🧪 Testing Strategy

> Companion to Phase 12 of [`../planning/ROADMAP.md`](../planning/ROADMAP.md).
> **Mantra:** *every public surface has at least one fuzz / injection / chaos test.*

## 🗂️ Test taxonomy (Phase 12 §12.1)

The eleven-layer test pyramid from Phase 12 §12.1. Each layer has a **single owning lane** (§12.13), a **determinism contract**, and an **example name** so the taxonomy is enforceable, not decorative.

| Layer | Kind | Owns | Lane | Example |
|---|---|---|---|---|
| **Unit** | Pure logic, no I/O | every package | fast (push) | `test_dixon_coles_grid_sums_to_one` |
| **Property** | Invariants under random input | every public type | fast (push) | `test_match_envelope_roundtrip_property` |
| **Contract** | Wire schemas / OpenAPI | bus topics + API | fast (push) | `test_predict_final_matches_schema` |
| **Integration** | Agent ↔ bus ↔ agent | swarm + storage | pr | `test_scraper_to_storage_happy_path` |
| **Adversarial** | Injection / payload abuse / homoglyph | every trust boundary | pr | `test_qa_resists_ignore_previous_instructions` |
| **Fuzz** | Coverage-guided random bytes | every parser/decoder | nightly | `fuzz_sec_input_sanitize` |
| **Load** | Throughput + latency budgets under RPS | API + NLP + predictor | nightly | `load_qa_p99_within_budget` |
| **Chaos** | Kill / slow / partition / corrupt | full stack | nightly | `chaos.redis-flap` |
| **Soak** | Long-run leak / drift / MTBF | every long-lived agent | nightly + weekly | `soak.swarm.24h` |
| **Regression/Golden** | Frozen-output byte-identity | NLP render, citations | pr | `test_nlp_audit_rerender_byte_identical` |
| **Mutation** | "Covered ⇒ asserted" | security/integrity hot paths | nightly | `mutmut run --paths-to-mutate ai/swarm/agents/sec` |

## 🎯 Adversarial corpus

`ai/tests/fixtures/adversarial/`:

- `prompt_injection.tr.yaml` — Turkish jailbreak attempts.
- `prompt_injection.en.yaml` — English jailbreak attempts (cross-language defense).
- `payload_oversize.yaml` — multi-MB Turkish wall-of-text.
- `unicode_tricks.yaml` — RTL overrides, zero-width joiners, homoglyphs.
- `html_injection.yaml` — fake mock-source HTML containing `<script>`, base64'd payloads, JS redirects.
- `replay_traffic.yaml` — synthetic patterns mirroring real attacker behaviors.

Each entry maps to the **agent that must catch it**. A miss is a CI failure.

## 🌪️ Chaos lab

`make chaos-*` targets — runnable locally, also in nightly CI:

```
chaos-redis-flap       drops Redis 5 s; assert no msg loss
chaos-postgres-slow    +500 ms latency; assert API stays under SLO
chaos-kill-predictor   kills 50 % of predictor replicas; assert publish continues
chaos-network-partition splits agents from bus for 3 s; assert reconnection
chaos-disk-full        fills /tmp; assert graceful degradation, no crash
```

## 🧰 Smoke + happy path

`make smoke` *(target lands with the Go API in Phase 9; today the
canonical green-bar is `make test` over `make up`)* — must pass on
every PR. The intended Phase 12 happy path:

1. `POST /v1/auth/login` with the seeded dev user.
2. `GET /v1/leagues` returns at least one league.
3. `GET /v1/leagues/tr_super_lig/fixtures` returns ≥ 1 fixture.
4. `POST /v1/qa` with `{"text": "Bugün maç var mı?"}` returns 200 with TR text.
5. `swarmctl ps` *(introduced in Phase 3)* shows all agents with green heartbeats.

## 📊 Coverage

- Per-package line coverage ≥ 85 %.
- Adversarial corpus: 0 `xfail` allowed.
- Chaos suite: 0 `xfail` allowed.
- Soak: failure tolerated only with documented post-mortem and a tracking issue.

## ✍️ Authoring rule

Every PR that adds a new agent, topic, or HTTP route also adds:

1. A unit test for the happy path.
2. A property test for at least one invariant.
3. An adversarial test or a justification entry in the PR body explaining why none applies.

CI rejects the PR if any of those three is missing for new public surface.
