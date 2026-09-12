# ⚽ Negelir — Multi-League Football Match Analysis & Prediction

> **Ne gelir?** *(Turkish: "What will come?")*
> An agent-swarm AI system that scrapes football data from open data sources
> (mackolik / nesine / tff / openfootball / football-data.co.uk — see
> [`xops/env/.env.example`](xops/env/.env.example)), predicts match outcomes with an ensemble of
> small models, and answers questions in fluent Turkish — built
> **container-first**, **config-driven**, and **Turkish-out / English-in** by
> doctrine. Per-league behaviour lives in `LeagueConfig`; the seeded default is
> the Turkish Süper Lig and the roadmap (Phase 13) adds top European leagues
> + cups.

---

## 📌 Status

Active development. See [`docs/planning/ROADMAP.md`](docs/planning/ROADMAP.md)
for the full plan and [`docs/tracking/phases.csv`](docs/tracking/phases.csv)
for live phase status.

| Phase | Title | Status |
|---|---|---|
| 0 | Repo Reset & Cleanup | ✅ |
| 1 | Centralized Configuration | ✅ |
| 2 | Mock-Data Dev Stack ("Fake Internet") | ✅ |
| 3 | Swarm Foundation (Bus, Registry, Supervisor) | ✅ |
| 4 | Core Worker Agents | ✅ |
| 5 | Predictor Swarm & Consensus | ✅ |
| 6+ | Proofreader • Defense • Self-Maintenance • API • NLP • GPU/NPU • Chaos • Multi-League • Cloud • Frontend | ✅ |

---

## 🏗️ Architecture (target)

```
   Flutter clients (future, Phase 15)
              │ HTTPS + JWT
              ▼
   ┌─────────────────────────────────────┐
   │  🟦 Go REST API gateway (Phase 9)   │
   └────────────────┬────────────────────┘
                    │ Redis Streams
                    ▼
   ┌─────────────────────────────────────────────────────────┐
   │            🟪 Swarm bus (Redis → NATS later)            │
   │   topics: scrape.* • predict.* • proof.* • sec.* • …    │
   └──┬──────┬──────┬──────┬──────┬──────┬──────┬──────┬─────┘
      ▼      ▼      ▼      ▼      ▼      ▼      ▼      ▼
   Scrape  Categ.  Proc.  Pred.  Proof  Drift  Sec   Maint
                          ×N      ×N
                          │
                          ▼
   ┌──────────────────────────────────────────────────────┐
   │  🟨 Storage:  PostgreSQL (truth)  •  Redis (cache)   │
   └──────────────────────────────────────────────────────┘
```

Read more in [`docs/design/ARCHITECTURE.md`](docs/design/ARCHITECTURE.md) and
[`docs/design/SWARM.md`](docs/design/SWARM.md).

---

## 📦 Components today

| Path | Role |
|---|---|
| [`ai/`](ai) | Python 3.11 — scrapers, proofreader, GBDT model, league configs (`common/league_config.py`), Turkish-language NLP/QA layer, training pipeline |
| [`server/`](server) | Go REST middleware — will split into `cmd/api` (Phase 9) and `cmd/mocksrv` (Phase 2) |
| [`migrations/`](migrations) | PostgreSQL schema |
| [`docs/`](docs) | Master roadmap, design notes, setup guide, phase tracker |
| [`docs/tracking/`](docs/tracking) | CSV phase log + cross-platform CLI |

---

## 🚀 Quick start

### Prerequisites
- 🐳 Docker & Docker Compose v2
- 🐍 Python 3.10+ (only for the local phase-tracker CLI)
- 🐧 Linux / 🍎 macOS / 🪟 Windows (PowerShell + Docker Desktop)

### 1. Bootstrap env

```bash
make env             # copy xops/env/.env.example → xops/env/.env if missing
```

> Set `POSTGRES_PASSWORD` in `xops/env/.env` before bringing the stack up — it is intentionally
> required, with no default.

### 2. Bring the stack up

```bash
make up              # build + start all services (foreground)
make up DETACH=1     # background
```

### 3. Train the GBDT (Phase 0 stub pipeline)

The pipeline is league-agnostic — pass any league id registered in
`ai/common/league_config.py` (currently Turkish Süper Lig is the seeded
default; more presets land in Phase 13).

```bash
make bootstrap LEAGUE=super_lig    # one-time real-data scrape + validate
make train      LEAGUE=super_lig   # 6 stages: scrape → validate → split → train → verify → report
```

The legacy ensemble stages are gone; the swarm-based predictor mesh
will replace them in Phase 5.

### 4. Tests

```bash
make test               # all Python tests
make test.ai            # AI tests only
make test.integration   # full training pipeline (skipped if no real data cached)
```

---

## 🧭 Phase tracker

Every phase milestone is logged to [`docs/tracking/phases.csv`](docs/tracking/phases.csv)
with date, status, notes, divergences, etc. The
[`docs/tracking/track.py`](docs/tracking/track.py) CLI is **Python-3 stdlib
only** and runs identically on Linux, macOS, and Windows.

```bash
# Linux / macOS
python3 docs/tracking/track.py list
python3 docs/tracking/track.py show 0
python3 docs/tracking/track.py add --phase 1 --status in-progress --note "Started config audit"

# Windows (PowerShell)
py -3 docs/tracking/track.py list
```

Or via Make (cross-platform — uses `python3` on POSIX, `python` on Windows):

```bash
make track.list
make track.show PHASE=0
make track.add PHASE=1 STATUS=in-progress NOTE="Started config audit"
```

See [`docs/tracking/README.md`](docs/tracking/README.md) for the full state
machine and column definitions.

---

## 🛠️ Makefile cheatsheet

The Makefile is organised into **daily verbs** (short, unprefixed) and
**`domain.action`** subcommands. Run `make help` to see the full list.

### Daily commands

| Command | Description |
|---|---|
| `make env` | Create `xops/env/.env` from `xops/env/.env.example` |
| `make up` / `make down` | Bring the full stack up / down (`DETACH=1` to background) |
| `make logs` | Tail logs (`SVC=ai` for one service) |
| `make scrape LEAGUE=…` | Scrape and cache real data |
| `make bootstrap LEAGUE=…` | Scrape + validate cache (gate before training) |
| `make train LEAGUE=…` | Full 6-stage training pipeline |
| `make backtest WEEKS=N` | Multi-market backtest (also `MIN_CONFIDENCE=…`, `MARKETS=…`) |
| `make test` | Run the full test suite |
| `make help` | Print every documented target |

### Domains (selection)

| Family | Examples |
|---|---|
| `ai.*` | `ai.pipeline`, `ai.demo`, `ai.shell`, `ai.continuous` |
| `db.*` / `cache.*` | `db.migrate`, `db.seed`, `db.shell`, `db.reset`, `cache.shell` |
| `api` | `make api ENDPOINT=health` (also `matches`, `teams`, `scrape/trigger METHOD=POST`) |
| `mock.*` | Phase 2 mock-data dev stack (`mock.up`, `mock.smoke`, `mock.capture`, …) |
| `hosts.*` / `watch.*` | `/etc/hosts` for mock vhosts; source-watcher agent |
| `track.*` / `version.*` | Phase tracker + versioning chart |
| `clean` / `clean.all` | ⚠️ Volumes destroyed by `clean.all`; add `DATA=1` to also wipe `./data` |

> Legacy `verb-noun` names (`db-seed`, `train-full`, `ai-backtest`, `track-list`, …)
> still work but print a deprecation warning. They are slated for removal one
> release after this rename.

---

## ⚙️ Environment variables

`xops/env/.env.example` is the canonical list. Every key documented there is consumed
either by the Python config layer (`ai/common/config.py`), the Go server, or
docker-compose itself — `ai/tests/test_config_sync.py` enforces parity. See
[`xops/env/README.md`](xops/env/README.md) for the env-folder conventions.

Most-touched knobs:

| Variable | Default | Purpose |
|---|---|---|
| `POSTGRES_PASSWORD` | _(required)_ | Postgres credential — no default by design |
| `NEGELIR_COMMON_DEFAULT_LEAGUE_ID` | `super_lig` | League id used when `LEAGUE=` is omitted |
| `AI_DEVICE` | `auto` | `cpu` / `cuda` / `auto` for ML compute |
| `AI_LOG_LEVEL` | `DEBUG` | Python log verbosity |
| `BOOTSTRAP_MIN_MATCHES` | `100` | Gate before training is allowed |
| `NEGELIR_THRESHOLD_MODEL_ACC` | `0.50` | Minimum test accuracy for a `PASS` verdict |
| `SIMULATION_INTERVAL` | `30` | Seconds between cycles in continuous modes |

Naming convention: `NEGELIR_*` (Python AI), `SCRAPE_*` (scraper sources),
`POSTGRES_*` / `REDIS_*` (shared), `AI_*` (Python runtime, legacy prefix
kept for back-compat), Go-only knobs are tagged in the `xops/env/.env.example`
header.

---

## 🤖 VS Code / Copilot configuration

The repo ships an opinionated GitHub Copilot setup so any new contributor
gets the same doctrine-aware behaviour out of the box. Roadmap and
rationale live in [`docs/coding/ai/automation.md`](docs/coding/ai/automation.md).

| File | Role |
|---|---|
| [`.github/copilot-instructions.md`](.github/copilot-instructions.md) | Repo-wide system prompt. Tells Copilot to read [`AGENTS.md`](AGENTS.md) §1 first, defaults to Claude Sonnet 4.5, restates the binding rules (no `git`, single-source config, Turkish UX, tracker + version bump in same commit). |
| [`.github/instructions/ai-python.instructions.md`](.github/instructions/ai-python.instructions.md) | Auto-applied (`applyTo: ai/**/*.py`). Pytest, config layer, logging, source-watcher discipline. |
| [`.github/instructions/server-go.instructions.md`](.github/instructions/server-go.instructions.md) | Auto-applied (`applyTo: server/**/*.go`). Modes (`api` vs `mocksrv`), config, table tests, forbidden surfaces. |
| [`.github/instructions/xops-make.instructions.md`](.github/instructions/xops-make.instructions.md) | Auto-applied (`applyTo: Makefile,xops/makefile/**,xops/mcp/**`). Dispatcher pattern, sanctioned `sudo` callers, cross-platform rules. |
| [`.github/chatmodes/doctrine-reader.chatmode.md`](.github/chatmodes/doctrine-reader.chatmode.md) | Read-only auditor. Cites `file:line`, never edits. Switch to it from the Copilot Chat mode picker when you want a "what does the doctrine say?" answer. |
| [`.github/prompts/tour.repo.prompt.md`](.github/prompts/tour.repo.prompt.md) | `/tour.repo` — top-down onboarding tour for new contributors. |
| [`.github/prompts/audit.config.prompt.md`](.github/prompts/audit.config.prompt.md) | `/audit.config` — finds Rule 1 (single-source config) violations in the named module. |
| [`.github/prompts/test.gap.prompt.md`](.github/prompts/test.gap.prompt.md) | `/test.gap` — lists untested public surfaces in the named module. |
| [`.vscode/settings.json`](.vscode/settings.json) | Enables prompt / instruction / chat-mode folders; auto-approves a curated allow-list of read-only Make targets (`track.list`, `version.show`, `lint`, `mock.verify`, `health`, …); explicitly **denies** `git`, `rm -rf`, `pip install`, `go install`. The four sanctioned `sudo` mock-stack targets (`hosts.install`, `mock.trust`, …) are intentionally **not** denied — Copilot may run them but VS Code will prompt for confirmation since they aren't in the auto-approve list. |
| [`.vscode/mcp.json`](.vscode/mcp.json) | Registry for project MCP servers. The `negelir-make` server (currently disabled — leading `_`) will expose the read-only Make allow-list to Copilot once the stdio JSON-RPC loop in [`xops/mcp/make_allowlist.py`](xops/mcp/make_allowlist.py) is implemented. |
| [`xops/mcp/`](xops/mcp/) | Scaffolding for project MCP wrappers. See [`xops/mcp/README.md`](xops/mcp/README.md). |

### Planned prompt catalogue

The full Copilot roadmap in
[`docs/coding/ai/automation.md`](docs/coding/ai/automation.md) defines a
broader set of slash-prompts that will land alongside the existing
three. Each is intentionally narrow and read-mostly. The default
model is **Claude Sonnet 4.5** unless the prompt's reasoning depth
warrants **Claude Opus 4.7** (per
[`AGENTS.md`](AGENTS.md) doctrine on the smallest model that works).

| Prompt | Owner mode | Cadence | Default model | Output |
|---|---|---|---|---|
| `/test.gap <module>` | Test Author | on demand | Sonnet 4.5 | Ranked list of public functions with no test, plus a first valuable test draft. ✅ **shipped** |
| `/test.regression <bug>` | Test Author | after a bug report | Sonnet 4.5 | A failing test capturing the bug; stops before the fix. |
| `/test.flake <test-id>` | Debugger | repeated CI flakes | Opus 4.7 | Reproduction strategy (seed, ordering, time/locale dependency); proposes a deterministic guard. |
| `/lint.debt <area>` | Doctrine Reader | weekly | Sonnet 4.5 | Inventory of `# noqa`, `// nolint`, `type: ignore`, magic numbers; ordered by blast radius. |
| `/dead.symbols <area>` | Doctrine Reader | monthly | Sonnet 4.5 | Symbols exported but never imported; references-in-tests filter applied. |
| `/dup.scan <area>` | Doctrine Reader | quarterly | Opus 4.7 | Cross-module duplication candidates with extraction sketch. |
| `/deps.stale` | Doctrine Reader | weekly cron | Sonnet 4.5 | Diff of `requirements.txt` / `go.mod` against latest stable; flags CVEs first. |
| `/deps.cve` | Doctrine Reader | on GHSA notice | Opus 4.7 | Per-dependency exposure map: which modules import the affected symbols. |
| `/i18n.audit` | Doctrine Reader | weekly | Sonnet 4.5 | TR strings missing from `ai/common/locale_tr.yaml`; EN strings leaking into user-facing surfaces (Rule 6 enforcement). |
| `/tour.repo` | (any mode) | on demand | Sonnet 4.5 | Top-down onboarding tour. ✅ **shipped** |
| `/audit.config <module>` | Doctrine Reader | on demand | Sonnet 4.5 | Rule 1 (single-source config) violations. ✅ **shipped** |

To add a new prompt, drop a `<name>.prompt.md` file under
`.github/prompts/` with frontmatter that pins `mode:` (and `model:`
if you need to override the default), then update this table and
bump `docs` per [`AGENTS.md`](AGENTS.md) §6.1.

### How to use it

1. **Open the repo in VS Code** with the GitHub Copilot Chat extension
   installed. The `.github/instructions/*.instructions.md` files apply
   automatically based on which file you have open.
2. **Use slash-prompts**. In Copilot Chat, type `/tour.repo`,
   `/audit.config`, or `/test.gap` to invoke the matching prompt
   against your current file or selection.
3. **Switch to the Doctrine Reader mode** when you want an audit
   instead of an edit — pick it from the chat mode dropdown. It has
   no terminal access and refuses to mutate files.
4. **Trust the auto-approve allow-list**. Copilot can run any of the
   read-only Make targets in [`.vscode/settings.json`](.vscode/settings.json)
   without a per-call confirmation. Anything that mutates state
   (especially `git`) prompts you every time.
5. **Add a new prompt / mode / MCP tool** by following the catalogue in
   [`docs/coding/ai/automation.md`](docs/coding/ai/automation.md) §3–§5.
   Drop a new file under `.github/prompts/`, `.github/chatmodes/`, or
   `xops/mcp/` and bump the `docs` (or `xops`) version per
   [`AGENTS.md`](AGENTS.md) §6.1.

> **Doctrine reminder.** Per [`AGENTS.md`](AGENTS.md) Rule 9, Copilot
> never runs `git`. Use `make git` (the human-only driver) to land
> commits. Everything else — tests, `docker compose`, tracker rows,
> version bumps, even root-scoped mock-stack provisioning — is fair
> game for the agent.

---

## 🛡️ Doctrine (non-negotiable)

1. **🔧 Single-source configuration** — no magic numbers; every tunable lives in `xops/env/.env.example` + a config layer.
2. **📦 Containerized only** — local dev = `docker compose`. There is no host-install path.
3. **🚫 Real data only in prod paths** — synthetic data is a *test fixture*, never a *fallback*.
4. **⚡ Smallest model that works** — deterministic > scikit-learn > XGBoost > small transformers > LLM. LLMs only when justified.
5. **📈 Scale symmetry** — same agent process whether 1 of it or 1000. State lives in Redis / Postgres.
6. **🇹🇷 Turkish UX / English infra** — user-facing strings TR; code, logs, config keys EN.
7. **🧪 Adversarial tests are first-class** — every public surface gets a fuzz / injection / chaos test.
8. **🔁 Phase gates** — a phase ships only when its [Definition of Done](docs/planning/ROADMAP.md#-appendix-b--definition-of-done-per-phase) is fully green in CI.

---

## 📁 Project structure

```
negelir/
├── README.md                 ← you are here
├── docker-compose.yml        ← service orchestration
├── Makefile                  ← cross-platform commands
├── xops/env/.env.example     ← canonical env-var list (see xops/env/README.md)
├── ai/                       ← Python 3.11 AI engine
│   ├── common/               ← config, constants, league_config, logging
│   ├── scraper/              ← source-specific scrapers + selectors
│   ├── proofreader/          ← validators
│   ├── model/                ← XGBoost trainer, features, device probe
│   ├── pipeline/             ← training pipeline + artifacts
│   ├── orchestrator/         ← pipeline state machine
│   ├── reports/              ← training-run report renderer
│   ├── tqu/ trc/ nlp/        ← Turkish-language NLP / QA / sentiment (UX layer)
│   └── tests/
├── server/                   ← Go middleware (Gin)
├── migrations/               ← PostgreSQL schema
├── data/                     ← runtime data (Docker volume)
└── docs/
    ├── README.md             ← documentation index
    ├── planning/ROADMAP.md   ← master roadmap (Swarm Pivot)
    ├── design/               ← architecture, swarm, security, NLP, …
    ├── guides/               ← setup & operator guides
    └── tracking/             ← phases.csv + cross-platform CLI
```

---

## 📜 License

See [LICENSE](LICENSE).


