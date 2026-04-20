# 📚 Negelir — Documentation Index

> **Project codename:** *Negelir* (Turkish: "Ne gelir?" → "What will come?")
> **Mission:** A self-hosted, swarm-AI football intelligence backend that scrapes,
> reasons, predicts and answers in **natural Turkish** — runnable on a laptop,
> scalable to a cloud cluster.

This documentation tree was reset on **2026-04-19** as part of the
**Swarm Pivot** (P2P removed → Swarm-AI Agents introduced).
There are no archives — the canonical, current plan lives here.

---

## 🗺️ Start Here

| You want to... | Read this |
|---|---|
| Understand the **whole plan, top-to-bottom** | [`planning/ROADMAP.md`](planning/ROADMAP.md) |
| See the **system architecture** | [`design/ARCHITECTURE.md`](design/ARCHITECTURE.md) |
| Understand the **agent swarm** | [`design/SWARM.md`](design/SWARM.md) |
| Detect **new content on data sources** (proposed agent) | [`design/CONTENT_FRESHNESS.md`](design/CONTENT_FRESHNESS.md) |
| Know **why we picked our languages** | [`design/LANGUAGE_CHOICES.md`](design/LANGUAGE_CHOICES.md) |
| Set up the **fake-data dev environment** | [`design/MOCK_DATA_SERVER.md`](design/MOCK_DATA_SERVER.md) |
| Understand **identity / API security** | [`design/SECURITY.md`](design/SECURITY.md) |
| Understand **GPU/CPU/NPU device strategy** | [`design/COMPUTE_DEVICES.md`](design/COMPUTE_DEVICES.md) |
| Understand **centralized configuration** | [`design/CONFIGURATION.md`](design/CONFIGURATION.md) |
| Understand **Turkish-language NLP pipeline** | [`design/TURKISH_NLP.md`](design/TURKISH_NLP.md) |
| Understand **adversarial / chaos testing** | [`design/TESTING_STRATEGY.md`](design/TESTING_STRATEGY.md) |
| Get **local dev running** | [`guides/SETUP.md`](guides/SETUP.md) |

---

## 📁 Folder Layout

```
docs/
├── README.md                        ← you are here
├── planning/
│   └── ROADMAP.md                   ← master plan, single source of truth
├── design/
│   ├── ARCHITECTURE.md              ← high-level system diagram
│   ├── SWARM.md                     ← agent roles, consensus, message bus
│   ├── CONTENT_FRESHNESS.md         ← proposed Phase 3 freshness agent (sketch)
│   ├── LANGUAGE_CHOICES.md          ← Python vs Rust vs Go decision
│   ├── MOCK_DATA_SERVER.md          ← fake-internet dev stack
│   ├── SECURITY.md                  ← identity, mTLS, rate limit, threat model
│   ├── COMPUTE_DEVICES.md           ← GPU / CPU / NPU strategy
│   ├── CONFIGURATION.md             ← single-source config doctrine
│   ├── TURKISH_NLP.md               ← TR pipeline, dialect & typo tolerance
│   └── TESTING_STRATEGY.md          ← unit, integration, chaos, adversarial
└── guides/
    └── SETUP.md                     ← zero-to-running-stack on a fresh machine
```

---

## ✅ Doctrine (applies everywhere, no exceptions)

1. **🔧 Centralized configuration** — every value comes from a single config layer driven by env vars. No magic numbers. No per-module duplicate constants.
2. **📦 Containerized always** — local dev is `docker compose`, prod is Docker or K8s. No "run it on the host" instructions.
3. **🚫 No fabricated production data** — synthetic data is only allowed inside `tests/` directories and must be explicitly marked.
4. **⚡ Minimal-cost AI** — pick the smallest model that passes the quality gate. LLMs are a last resort for any given task.
5. **📈 Scale-agnostic design** — the same code path runs on a laptop and on a 100-node K8s cluster.
6. **🇹🇷 Turkish-first UX, English-only infra** — code, comments, logs, metrics: English. AI input/output: Turkish (with dialect & typo tolerance).
7. **🧪 Tests cover behavior + adversarial surface** — prediction quality, system behavior, fuzzing, prompt injection, malicious payloads.
8. **🔁 Phase-gated** — every phase has explicit completion criteria; nothing ships half-done.

---

## 🚫 What This Project Is **Not**

- ❌ A P2P / gossip network — *removed in the 2026-04-19 Swarm Pivot.*
- ❌ A production-grade secret-management showcase — local/experimental scope only.
- ❌ A frontend — Flutter web/mobile is a **future** workstream.
- ❌ An "everything is an LLM" system — most agents are deterministic or use ≤ 100 MB models.
