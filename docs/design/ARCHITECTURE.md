# 🏛️ Architecture

> Companion to [`../planning/ROADMAP.md`](../planning/ROADMAP.md).
> This doc focuses on **structure** — what runs where, talks to whom, and why.

---

## 🧱 Layers

```
┌───────────────────────────────────────────────────────────┐
│   L5 — Clients          Flutter (web/mobile, Phase 15)    │
├───────────────────────────────────────────────────────────┤
│   L4 — Public API       Go REST gateway, JWT, rate-limit  │
├───────────────────────────────────────────────────────────┤
│   L3 — Swarm            Many small agents, message bus    │
├───────────────────────────────────────────────────────────┤
│   L2 — Storage          PostgreSQL (truth), Redis (warm)  │
├───────────────────────────────────────────────────────────┤
│   L1 — Sources          Real internet OR mock-data stack  │
└───────────────────────────────────────────────────────────┘
```

Each layer talks **only to the layer immediately above and below it**. This rule
keeps deployments swappable: replace L1 with the mock stack for tests, replace
L4 with a CLI for batch jobs, scale L3 horizontally without touching anything
else.

## 🔄 Request lifecycle (Turkish QA → answer)

1. **Client** posts to `POST /v1/qa` with a Turkish question.
2. **API gateway** verifies JWT, applies rate limit (`sec.rate.v1` consult).
3. Gateway publishes `qa.request{trace_id, text}` and awaits `qa.final{trace_id}` on its `reply_to` topic.
4. **`sec.input.v1`** sanitizes / quarantines.
5. **NLP layer** (Phase 10) extracts intent + entities → publishes `predict.request` if needed.
6. **Predictor swarm** votes → **consensus** → **proofreader quorum** → `predict.final`.
7. **NLP humanizer** turns the structured prediction into a Turkish sentence.
8. **Gateway** returns JSON; cache agent stores by hash for warm replays.

> 💡 **No agent ever calls another agent directly.** Everything goes through the bus. This is the property that makes scale symmetry work.

## 🗂️ State boundaries

| Where | What lives there | Persistence |
|---|---|---|
| Postgres | matches, lineups, odds, outcomes, users, calibration tables, telemetry events | durable |
| Redis Streams | message bus topics | durable (with retention) |
| Redis hashes | agent registry, denylist, rate-limit buckets | ephemeral |
| Agent process memory | nothing important — a kill should lose nothing | ephemeral |

## 🧬 Why "many small agents" beats "one big service"

- Independent **deploy / scale / restart** per role.
- Faults stay local (`predictor.tabnet` dying does not stop scraping).
- New ideas land as new agents, not as `if` branches in a monolith.
- Adversarial surface is per-agent; the security layer can target it precisely.
