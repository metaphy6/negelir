# ══════════════════════════════════════════════════════════════
#  Negelir — Project Makefile
#  Turkish Football Match Analysis & Prediction System
# ══════════════════════════════════════════════════════════════

COMPOSE := docker compose
ENV_FILE := .env
WORKSPACE_DIR := /workspace
TEST_PYTHONPATH := $(WORKSPACE_DIR)/ai

# Tunable defaults for backtest targets (override on the CLI: `make ai-backtest WEEKS=5`)
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

# Detect OS for cross-platform compatibility
ifeq ($(OS),Windows_NT)
	SHELL := cmd.exe
	COPY_CMD := copy
	RM_CMD := del /q
	PY := python
else
	SHELL := /bin/bash
	COPY_CMD := cp
	RM_CMD := rm -f
	PY := python3
endif

.DEFAULT_GOAL := help

# ── Environment ─────────────────────────────────────────────

.PHONY: env
env: ## Create .env from .env.example if it doesn't exist
	@test -f $(ENV_FILE) || ($(COPY_CMD) .env.example $(ENV_FILE) && echo "✅ Created .env from .env.example")
	@test -f $(ENV_FILE) && echo "📄 .env exists"

# ── Build & Run ─────────────────────────────────────────────

.PHONY: build
build: env ## Build all Docker images
	$(COMPOSE) build

.PHONY: up
up: env ## Start all services (build + run)
	$(COMPOSE) up --build

.PHONY: up-detached
up-detached: env ## Start all services in background
	$(COMPOSE) up --build -d

.PHONY: down
down: ## Stop and remove all containers
	$(COMPOSE) down

.PHONY: restart
restart: down up ## Restart all services

# ── Individual Services ─────────────────────────────────────

.PHONY: ai
ai: env ## Run only the AI pipeline
	$(COMPOSE) up --build ai

.PHONY: server
server: env ## Run only the Go server + dependencies
	$(COMPOSE) up --build postgres redis server

.PHONY: infra
infra: env ## Start only infrastructure (PostgreSQL + Redis)
	$(COMPOSE) up -d postgres redis

# ── AI Commands ─────────────────────────────────────────────

.PHONY: scrape
scrape: env ## Scrape and cache real match data for a league (override: LEAGUE=en_premier_league)
	@echo "📥 Scraping real data for $(LEAGUE)..."
	$(COMPOSE) run --rm \
		-e NEGELIR_DEFAULT_LEAGUE_ID=$(LEAGUE) \
		ai python -m scraper.real_data --league $(LEAGUE) --output /data/$(LEAGUE)_real.json

.PHONY: bootstrap
bootstrap: env ## Scrape + validate real data cache before training
	@echo "🚀 Bootstrapping real data for $(LEAGUE)..."
	$(MAKE) scrape LEAGUE=$(LEAGUE)
	$(COMPOSE) run --rm \
		-e NEGELIR_DEFAULT_LEAGUE_ID=$(LEAGUE) \
		ai python -m proofreader.validator --input /data/$(LEAGUE)_real.json --min-matches $(BOOTSTRAP_MIN_MATCHES)
	@echo "✅ Bootstrap complete. $(LEAGUE) data is ready for training."

.PHONY: train
train: train-full ## Phase 3 alias — full-system training pipeline (back-compat: see ai-train for legacy single-stage trainer)

.PHONY: train-full
train-full: env ## Phase 3 — Training pipeline (scrape → validate → split → train → verify → report)
	@test -f data/$(LEAGUE)_real.json || (echo "❌ Missing data/$(LEAGUE)_real.json. Run 'make bootstrap LEAGUE=$(LEAGUE)' first." && exit 1)
	$(COMPOSE) run --rm \
		-e NEGELIR_DEFAULT_LEAGUE_ID=$(LEAGUE) \
		ai python -m orchestrator.state_machine --mode full-training --league $(LEAGUE)

.PHONY: train-model
train-model: env ## Phase 3 — Stages 1–4 only (data + training, no verify/report)
	@test -f data/$(LEAGUE)_real.json || (echo "❌ Missing data/$(LEAGUE)_real.json. Run 'make bootstrap LEAGUE=$(LEAGUE)' first." && exit 1)
	$(COMPOSE) run --rm \
		-e NEGELIR_DEFAULT_LEAGUE_ID=$(LEAGUE) \
		ai python -m orchestrator.state_machine --mode model-only --league $(LEAGUE)

.PHONY: ai-pipeline
ai-pipeline: env ## Run the full AI pipeline (scrape → process → analyze → respond)
	$(COMPOSE) run --rm ai python -m pipeline.runner

.PHONY: ai-train
ai-train: env ## Legacy single-stage trainer (no holdout split, no report)
	@test -f data/$(LEAGUE)_real.json || (echo "❌ Missing data/$(LEAGUE)_real.json. Run 'make bootstrap LEAGUE=$(LEAGUE)' first." && exit 1)
	$(COMPOSE) run --rm \
		-e NEGELIR_DEFAULT_LEAGUE_ID=$(LEAGUE) \
		ai python -m model.trainer

.PHONY: ai-demo
ai-demo: env ## Run Turkish Q&A demo questions
	$(COMPOSE) run --rm ai python -m pipeline.runner --demo

.PHONY: ai-backtest
ai-backtest: env ## Multi-market backtest (all betting types, last 3 weeks)
	$(COMPOSE) run --rm ai python -m backtest.evaluator --weeks $(WEEKS)

.PHONY: ai-backtest-2w
ai-backtest-2w: env ## Multi-market backtest (last 2 weeks, high-confidence only)
	$(COMPOSE) run --rm ai python -m backtest.evaluator --weeks $(WEEKS_SHORT) --min-confidence $(MIN_CONFIDENCE)

.PHONY: ai-backtest-1x2
ai-backtest-1x2: env ## Backtest only 1X2 market
	$(COMPOSE) run --rm ai python -m backtest.evaluator --weeks $(WEEKS) --markets $(MARKETS_1X2)

.PHONY: ai-backtest-goals
ai-backtest-goals: env ## Backtest goal-related markets (AU, KG, skor)
	$(COMPOSE) run --rm ai python -m backtest.evaluator --weeks $(WEEKS_MARKET) --markets $(MARKETS_GOALS)

.PHONY: ai-backtest-halftime
ai-backtest-halftime: env ## Backtest half-time markets (IY, IY/MS)
	$(COMPOSE) run --rm ai python -m backtest.evaluator --weeks $(WEEKS_MARKET) --markets $(MARKETS_HALFTIME)

.PHONY: ai-backtest-full
ai-backtest-full: env ## Full backtest across 10 weeks with all markets
	$(COMPOSE) run --rm ai python -m backtest.evaluator --weeks $(WEEKS_LONG)

.PHONY: ai-tqu-test
ai-tqu-test: env ## Test TQU with sample Turkish questions
	$(COMPOSE) run --rm ai python -m tqu.classifier

.PHONY: ai-shell
ai-shell: env ## Open a shell in the AI container
	$(COMPOSE) run --rm ai bash

.PHONY: ai-continuous
ai-continuous: env ## Run AI pipeline in continuous loop (Ctrl+C to stop)
	$(COMPOSE) run --rm ai python main.py --continuous

.PHONY: ai-continuous-demo
ai-continuous-demo: env ## Run AI demo in continuous loop (Ctrl+C to stop)
	$(COMPOSE) run --rm ai python main.py --demo --continuous

# ── Phase Tracking ──────────────────────────────────────────

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
	@curl -s -X POST http://localhost:8080/api/v1/scrape/trigger | python3 -m json.tool 2>/dev/null || echo "⚠️  Server not running. Use 'make server' first."

.PHONY: server-health
server-health: ## Check Go server health
	@curl -s http://localhost:8080/api/v1/health | python3 -m json.tool 2>/dev/null || echo "⚠️  Server not running."

.PHONY: server-matches
server-matches: ## List cached matches from Go server (requires 'make db-seed' first)
	@curl -s http://localhost:8080/api/v1/matches | python3 -m json.tool 2>/dev/null || echo "⚠️  Server not running. Use 'make server' first."
	@echo ""
	@echo "💡  Empty? Run: make db-seed  (imports local JSON cache into PostgreSQL)"

.PHONY: server-teams
server-teams: ## List teams from Go server
	@curl -s http://localhost:8080/api/v1/teams | python3 -m json.tool 2>/dev/null || echo "⚠️  Server not running."

# ── Database ────────────────────────────────────────────────

.PHONY: db-migrate
db-migrate: env ## Run all pending database migrations
	@echo "🗄️  Running migrations..."
	@for f in migrations/*.sql; do \
		echo "  → $$f"; \
		$(COMPOSE) exec -T postgres psql -U negelir -d negelir < $$f 2>/dev/null \
			|| $(COMPOSE) exec postgres psql -U negelir -d negelir -f /dev/stdin < $$f; \
	done
	@echo "✅  Migrations complete"

.PHONY: db-seed
db-seed: env ## Seed PostgreSQL with local JSON cache (dev only; run 'make infra' first)
	@echo "🌱  Seeding database from local JSON cache..."
	$(COMPOSE) run --rm -v $(PWD)/data:/data:ro ai python /data/seed_db.py
	@echo "✅  Seed complete — now try: make server-matches"

.PHONY: db-shell
db-shell: env ## Open PostgreSQL shell
	$(COMPOSE) up -d postgres
	$(COMPOSE) exec postgres psql -U negelir -d negelir

.PHONY: db-reset
db-reset: ## Reset database (WARNING: destroys all data)
	@echo "⚠️  This will destroy all data. Press Ctrl+C to cancel."
	@sleep 3
	$(COMPOSE) down -v
	$(COMPOSE) up -d postgres
	@echo "✅ Database reset complete"

.PHONY: redis-shell
redis-shell: env ## Open Redis CLI
	$(COMPOSE) up -d redis
	$(COMPOSE) exec redis redis-cli

# ── Logs ────────────────────────────────────────────────────

.PHONY: logs
logs: ## Tail all service logs
	$(COMPOSE) logs -f

.PHONY: logs-ai
logs-ai: ## Tail AI service logs
	$(COMPOSE) logs -f ai

.PHONY: logs-server
logs-server: ## Tail Go server logs
	$(COMPOSE) logs -f server

# ── Testing ─────────────────────────────────────────────────

.PHONY: test
test: env ## Run all tests
	$(COMPOSE) run --rm \
		-v $(PWD):$(WORKSPACE_DIR) \
		-w $(WORKSPACE_DIR) \
		-e PYTHONPATH=$(TEST_PYTHONPATH) \
		ai python -m pytest ai/tests -v

.PHONY: test-ai
test-ai: env ## Run AI module tests
	$(COMPOSE) run --rm \
		-v $(PWD):$(WORKSPACE_DIR) \
		-w $(WORKSPACE_DIR) \
		-e PYTHONPATH=$(TEST_PYTHONPATH) \
		ai python -m pytest ai/tests -v

.PHONY: test-integration
test-integration: env ## Phase 3 — Full-pipeline integration test (skips cleanly if real data missing)
	$(COMPOSE) run --rm \
		-v $(PWD):$(WORKSPACE_DIR) \
		-w $(WORKSPACE_DIR) \
		-e PYTHONPATH=$(TEST_PYTHONPATH) \
		ai python -m pytest ai/tests/test_full_pipeline.py -v -s

# ── Cleanup ─────────────────────────────────────────────────

.PHONY: clean
clean: ## Remove containers, networks, and build cache
	$(COMPOSE) down --rmi local --remove-orphans

.PHONY: clean-all
clean-all: ## Remove everything including volumes (WARNING: destroys data)
	@echo "⚠️  This removes ALL data including database volumes."
	@sleep 3
	$(COMPOSE) down -v --rmi local --remove-orphans

.PHONY: clean-data
clean-data: ## Remove local data directory contents
	@echo "⚠️  Removing data/ contents..."
	find data/ -not -name '.gitkeep' -not -name 'data' -delete 2>/dev/null || true

# ── Status ──────────────────────────────────────────────────

.PHONY: health
health: ## Check health of all running services
	@echo "🏥  Service health check..."
	@curl -sf http://localhost:8080/api/v1/health > /dev/null && echo "✅  Go server  OK" || echo "❌  Go server  DOWN (run 'make server')"
	@$(COMPOSE) exec -T postgres pg_isready -U negelir -d negelir -q 2>/dev/null && echo "✅  PostgreSQL OK" || echo "❌  PostgreSQL DOWN (run 'make infra')"
	@$(COMPOSE) exec -T redis redis-cli ping 2>/dev/null | grep -q PONG && echo "✅  Redis      OK" || echo "❌  Redis      DOWN (run 'make infra')"

.PHONY: status
status: ## Show running service status
	$(COMPOSE) ps

.PHONY: ports
ports: ## Show exposed ports
	@echo "📡 Service Ports:"
	@echo "  PostgreSQL : localhost:5432"
	@echo "  Redis      : localhost:6379"
	@echo "  Go Server  : localhost:8080"
	@echo ""
	@echo "🔗 Useful URLs:"
	@echo "  Health     : http://localhost:8080/api/v1/health"
	@echo "  Matches    : http://localhost:8080/api/v1/matches"
	@echo "  Teams      : http://localhost:8080/api/v1/teams"

# ── Help ────────────────────────────────────────────────────

.PHONY: help
help: ## Show this help message
	@echo ""
	@echo "⚽ Negelir — Turkish Football Analysis System"
	@echo "══════════════════════════════════════════════"
	@echo ""
	@grep -E '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'
	@echo ""
