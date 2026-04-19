# 🛠️ Language Choices

> Decision: **Python (ML + agents) + Go (API + bus glue + mock-source server) + optional Rust (hot paths).**
> Companion to Phase 0 / Phase 9 of [`../planning/ROADMAP.md`](../planning/ROADMAP.md).

## ❓ "Should we drop Python for performance?"

Short answer: **no, and here's why.**

### What Python wins on

- **ML ecosystem.** PyTorch, XGBoost, LightGBM, scikit-learn, transformers, OpenVINO, ONNX Runtime, Optuna, Hypothesis. The closest competitors (Rust `linfa`, Julia `MLJ`, Go `gorgonia`) are 5–10× narrower in coverage and have meaningfully fewer pre-trained models.
- **Iteration speed.** Most agents are < 300 lines. The cost of a bad design choice is a rewrite, which is cheap in Python.
- **Existing codebase.** The current scraping, NLP, and training code is Python. Rewriting it for an unproven win is the wrong investment now.
- **Hiring & docs.** Every AI tutorial, every paper, every model card assumes Python.

### Where Python *actually* hurts

- Hot loops on bytes: HTML parsing, regex on millions of strings, CBOR encoding at very high QPS.
- Memory overhead per process (~80 MB minimum). Multiplied by many replicas, it adds up.
- GIL interaction with multi-threaded workers (mitigated by multi-process or `asyncio` + I/O bound design).

### What we do about it

| Concern | Mitigation |
|---|---|
| Slow HTML parse | `selectolax` (Cython) — already 10× BeautifulSoup |
| Slow message encode | `cbor2` (C-accelerated) |
| Hot regex pre-filter in security agent | **Rust** sidecar exposed via `pyo3` if profiling demands it (Phase 7+) |
| Memory per replica | Use **process pools per agent**, not one process per concept; share large model files via `mmap` |
| GIL / async | All I/O-bound agents are `asyncio`; CPU-bound work in `multiprocessing` or via the Rust sidecar |

### Where Go wins (and we already use it)

- The **REST gateway**: native HTTP/2, easy mTLS, fast JSON, low memory, single static binary.
- The **mock-source server**: deterministic, no GC surprises, ships as a 15 MB binary.
- **Bus utilities** (`swarmctl`): a CLI that lives next to the bus needs to be fast and dependency-free.

### When Rust enters

Rust is on the table **only** when a profiler shows Python > 30 % of agent CPU on the
hot path, and only for that specific path. Examples:

- `sec.input.v1` deterministic prefilter (regex / NFC / charset).
- `processor.match_detail.v1` HTML → struct on very high-volume sources.

Rust is **not** an across-the-board rewrite. It's a scalpel.

## 🔚 Final stack

| Layer | Language | Notes |
|---|---|---|
| Public API | **Go** | Gin or chi, mTLS, JWT |
| Mock-source server | **Go** | One binary, two modes |
| Swarm CLI | **Go** | Static, easy to ship |
| Swarm SDK (Python) | **Python 3.13** | Free-threaded build when stable |
| Swarm SDK (Go) | **Go** | For Go-native agents |
| ML training & inference | **Python** | XGBoost, LightGBM, PyTorch, OpenVINO |
| Hot pre-filters (optional) | **Rust** | Only after profiling justifies it |
| Frontend (future) | **Dart / Flutter** | Phase 15 |
