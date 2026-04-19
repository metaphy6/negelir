# ══════════════════════════════════════════════════════════════
#  Negelir — Project Makefile
#  Multi-league Football Match Analysis & Prediction System
# ──────────────────────────────────────────────────────────────
#  Targets are thin dispatchers. The actual cross-platform logic
#  lives in xops/makefile/<module>.py. See xops/README.md.
# ══════════════════════════════════════════════════════════════

# ── Tunables (override on the CLI: `make ai-backtest WEEKS=5`) ──

WEEKS ?= 3
WEEKS_SHORT ?= 2
WEEKS_LONG ?= 10
WEEKS_MARKET ?= 5
MIN_CONFIDENCE ?= 0.55
MARKETS_1X2 ?= ms
MARKETS_GOALS ?= au_1.5,au_2.5,au_3.5,kg,tc,skor,skor_top3
MARKETS_HALFTIME ?= iy,2y,iy_ms,iy_au_05
LEAGUE ?= super_lig
BOOTSTRAP_MIN_MATCHES ?= 100

# ── OS / Python launcher detection ──────────────────────────

ifeq ($(OS),Windows_NT)
	SHELL := cmd.exe
	PY := python
else
	SHELL := /bin/bash
	PY := python3
endif

XOPS := $(PY) xops/makefile

.DEFAULT_GOAL := help

# ── Environment ─────────────────────────────────────────────

.PHONY: env
env: ## Create .env from .env.example if it doesn't exist
	@$(XOPS)/env.py env

# ── Build & Run ─────────────────────────────────────────────

.PHONY: build
build: env ## Build all Docker images
	@$(XOPS)/services.py build

.PHONY: up
up: env ## Start all services (build + run)
	@$(XOPS)/services.py up

.PHONY: up-detached
up-detached: env ## Start all services in background
	@$(XOPS)/services.py up-detached

.PHONY: down
down: ## Stop and remove all containers
	@$(XOPS)/services.py down

.PHONY: restart
restart: ## Restart all services
	@$(XOPS)/services.py restart

# ── Individual Services ─────────────────────────────────────

.PHONY: ai
ai: env ## Run only the AI pipeline
	@$(XOPS)/services.py ai

.PHONY: server
server: env ## Run only the Go server + dependencies
	@$(XOPS)/services.py server

.PHONY: infra
infra: env ## Start only infrastructure (PostgreSQL + Redis)
	@$(XOPS)/services.py infra

# ── AI Commands ─────────────────────────────────────────────

.PHONY: scrape
scrape: env ## Scrape and cache real match data for a league (override: LEAGUE=en_premier_league)
	@$(XOPS)/ai_commands.py scrape --league $(LEAGUE)

.PHONY: bootstrap
bootstrap: env ## Scrape + validate real data cache before training
	@$(XOPS)/ai_commands.py bootstrap --league $(LEAGUE) --min-matches $(BOOTSTRAP_MIN_MATCHES)

.PHONY: train
train: train-full ## Phase 3 alias — full-system training pipeline (back-compat: see ai-train for legacy single-stage trainer)

.PHONY: train-full
train-full: env ## Phase 3 — Training pipeline (scrape → validate → split → train → verify → report)
	@$(XOPS)/ai_commands.py train-full --league $(LEAGUE)

.PHONY: train-model
train-model: env ## Phase 3 — Stages 1–4 only (data + training, no verify/report)
	@$(XOPS)/ai_commands.py train-model --league $(LEAGUE)

.PHONY: ai-pipeline
ai-pipeline: env ## Run the full AI pipeline (scrape → process → analyze → respond)
	@$(XOPS)/ai_commands.py ai-pipeline

.PHONY: ai-train
ai-train: env ## Legacy single-stage trainer (no holdout split, no report)
	@$(XOPS)/ai_commands.py ai-train --league $(LEAGUE)

.PHONY: ai-demo
ai-demo: env ## Run Turkish Q&A demo questions
	@$(XOPS)/ai_commands.py ai-demo

.PHONY: ai-backtest
ai-backtest: env ## Multi-market backtest (all betting types, last 3 weeks)
	@$(XOPS)/ai_commands.py ai-backtest --weeks $(WEEKS)

.PHONY: ai-backtest-2w
ai-backtest-2w: env ## Multi-market backtest (last 2 weeks, high-confidence only)
	@$(XOPS)/ai_commands.py ai-backtest --weeks $(WEEKS_SHORT) --min-confidence $(MIN_CONFIDENCE)

.PHONY: ai-backtest-1x2
ai-backtest-1x2: env ## Backtest only 1X2 market
	@$(XOPS)/ai_commands.py ai-backtest --weeks $(WEEKS) --markets $(MARKETS_1X2)

.PHONY: ai-backtest-goals
ai-backtest-goals: env ## Backtest goal-related markets (AU, KG, skor)
	@$(XOPS)/ai_commands.py ai-backtest --weeks $(WEEKS_MARKET) --markets $(MARKETS_GOALS)

.PHONY: ai-backtest-halftime
ai-backtest-halftime: env ## Backtest half-time markets (IY, IY/MS)
	@$(XOPS)/ai_commands.py ai-backtest --weeks $(WEEKS_MARKET) --markets $(MARKETS_HALFTIME)

.PHONY: ai-backtest-full
ai-backtest-full: env ## Full backtest across 10 weeks with all markets
	@$(XOPS)/ai_commands.py ai-backtest --weeks $(WEEKS_LONG)

.PHONY: ai-tqu-test
ai-tqu-test: env ## Test TQU with sample Turkish questions
	@$(XOPS)/ai_commands.py ai-tqu-test

.PHONY: ai-shell
ai-shell: env ## Open a shell in the AI container
	@$(XOPS)/ai_commands.py ai-shell

.PHONY: ai-continuous
ai-continuous: env ## Run AI pipeline in continuous loop (Ctrl+C to stop)
	@$(XOPS)/ai_commands.py ai-continuous

.PHONY: ai-continuous-demo
ai-continuous-demo: env ## Run AI demo in continuous loop (Ctrl+C to stop)
	@$(XOPS)/ai_commands.py ai-continuous-demo

# ── Lint (Phase 1.4) ────────────────────────────────────────

.PHONY: lint
lint: ## Run hardcode/no-magic lint over ai/ (Phase 1.4)
	@$(XOPS)/lint.py lint

# ── Phase Tracking ──────────────────────────────────────────
# (intentionally inline — already thin Python wrappers around docs/tracking/track.py)

.PHONY: track-list
track-list: ## List latest status per roadmap phase
	@$(PY) docs/tracking/track.py list

.PHONY: track-show
track-show: ## Show full history for one phase (PHASE=0)
	@$(PY) docs/tracking/track.py show $(PHASE)

.PHONY: track-add
track-add: ## Append entry (PHASE=N STATUS=… [SUB=…] [NOTE="…"] [DIVERGENCE="…"])
	@$(PY) docs/tracking/track.py add --phase $(PHASE) --status $(STATUS) \
		$(if $(SUB),--subphase $(SUB),) \
		$(if $(NOTE),--note "$(NOTE)",) \
		$(if $(DIVERGENCE),--divergence "$(DIVERGENCE)",)

.PHONY: track-export
track-export: ## Export the tracker log (FORMAT=md|csv)
	@$(PY) docs/tracking/track.py export --format $(or $(FORMAT),md)

# ── Server Commands ─────────────────────────────────────────

.PHONY: server-scrape
server-scrape: env ## Trigger data scraping via Go server
	@$(XOPS)/server_api.py server-scrape

.PHONY: server-health
server-health: ## Check Go server health
	@$(XOPS)/server_api.py server-health

.PHONY: server-matches
server-matches: ## List cached matches from Go server (requires 'make db-seed' first)
	@$(XOPS)/server_api.py server-matches

.PHONY: server-teams
server-teams: ## List teams from Go server
	@$(XOPS)/server_api.py server-teams

# ── Database ────────────────────────────────────────────────

.PHONY: db-migrate
db-migrate: env ## Run all pending database migrations
	@$(XOPS)/db.py db-migrate

.PHONY: db-seed
db-seed: env ## Seed PostgreSQL with local JSON cache (dev only; run 'make infra' first)
	@$(XOPS)/db.py db-seed

.PHONY: db-shell
db-shell: env ## Open PostgreSQL shell
	@$(XOPS)/db.py db-shell

.PHONY: db-reset
db-reset: ## Reset database (WARNING: destroys all data)
	@$(XOPS)/db.py db-reset

.PHONY: redis-shell
redis-shell: env ## Open Redis CLI
	@$(XOPS)/db.py redis-shell

# ── Logs ────────────────────────────────────────────────────

.PHONY: logs
logs: ## Tail all service logs
	@$(XOPS)/logs.py logs

.PHONY: logs-ai
logs-ai: ## Tail AI service logs
	@$(XOPS)/logs.py logs-ai

.PHONY: logs-server
logs-server: ## Tail Go server logs
	@$(XOPS)/logs.py logs-server

# ── Testing ─────────────────────────────────────────────────

.PHONY: test
test: env ## Run all tests
	@$(XOPS)/tests.py test

.PHONY: test-ai
test-ai: env ## Run AI module tests
	@$(XOPS)/tests.py test-ai

.PHONY: test-integration
test-integration: env ## Phase 3 — Full-pipeline integration test (skips cleanly if real data missing)
	@$(XOPS)/tests.py test-integration

# ── Cleanup ─────────────────────────────────────────────────

.PHONY: clean
clean: ## Remove containers, networks, and build cache
	@$(XOPS)/cleanup.py clean

.PHONY: clean-all
clean-all: ## Remove everything including volumes (WARNING: destroys data)
	@$(XOPS)/cleanup.py clean-all

.PHONY: clean-data
clean-data: ## Remove local data directory contents
	@$(XOPS)/cleanup.py clean-data

# ── Status ──────────────────────────────────────────────────

.PHONY: health
health: ## Check health of all running services
	@$(XOPS)/status.py health

.PHONY: status
status: ## Show running service status
	@$(XOPS)/status.py status

.PHONY: ports
ports: ## Show exposed ports
	@$(XOPS)/status.py ports

# ── Git Shortcuts ───────────────────────────────────────────
#
#  ⚠️  HUMAN-ONLY TARGETS — DO NOT USE FROM AN AI ASSISTANT  ⚠️
#
#  `make git` stages everything, derives a Conventional Commits
#  message from the rows added to docs/tracking/phases.csv since
#  HEAD, commits, and pushes to the current branch with the
#  operator's credentials. AI coding assistants (Copilot, Claude
#  Code, Cursor, Aider, Codex, etc.) MUST NOT invoke it. Authorship
#  and intent must be the human's. See AGENTS.md §operationalSafety.
#
#  `make git.dry` is the safe preview: it runs the same logic and
#  prints the commit message + file list it would produce, but
#  never touches the index, the working tree, or the remote.

.PHONY: git
git: ## [HUMAN-ONLY] Stage all, commit (Conventional Commits, msg from new phases.csv rows), push
	@$(XOPS)/git_helper.py commit

.PHONY: git.dry
git.dry: ## Preview the commit `make git` would create — no staging, no commit, no push
	@$(XOPS)/git_helper.py dry

# ── Help ────────────────────────────────────────────────────

.PHONY: help
help: ## Show this help message
	@echo ""
	@echo "⚽ Negelir — Multi-league Football Analysis System"
	@echo "════════════════════════════════════════════════════"
	@echo ""
	@grep -E '^[a-zA-Z0-9_.-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'
	@echo ""
