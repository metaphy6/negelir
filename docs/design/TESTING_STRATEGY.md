# 🧪 Testing Strategy

> Companion to Phase 12 of [`../planning/ROADMAP.md`](../planning/ROADMAP.md).
> **Mantra:** *every public surface has at least one fuzz / injection / chaos test.*

## 🗂️ Test taxonomy

| Layer | Tooling | Lives in | Runs in |
|---|---|---|---|
| Unit | `pytest`, `go test` | `**/tests/unit/` | every PR |
| Integration | `pytest` + `InMemoryBus` / real Redis | `**/tests/integration/` | every PR |
| Contract | `openapi-validator`, CDDL validator | `tests/contract/` | every PR |
| Property | `hypothesis` (Py), `gopter` (Go) | inline w/ unit | every PR |
| Adversarial | curated corpora + classifier suite | `tests/adversarial/` | every PR |
| Fuzz | `boofuzz`, `cargo-fuzz` (if Rust), `go-fuzz` | `tests/fuzz/` | nightly |
| Chaos | `pumba`, `toxiproxy` | `tests/chaos/` | nightly |
| Soak | full stack, 8 h, synthetic load | `tests/soak/` | weekly |

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
