# ══════════════════════════════════════════════════════════════
#  Negelir — Project Makefile
#  Multi-league Football Match Analysis & Prediction System
# ──────────────────────────────────────────────────────────────
#  Targets are thin dispatchers. The actual cross-platform logic
#  lives in xops/makefile/<module>.py. See xops/README.md.
#
#  Convention
#  ----------
#    • Daily verbs are short & unprefixed: env, up, down, restart,
#      logs, test, lint, train, scrape, bootstrap, backtest, help.
#    • Everything else is `domain.action`:
#        ai.*       — one-shot AI workloads inside the AI container
#        db.*       — Postgres / migrations / seed
#        cache.*    — Redis
#        api.*      — Go server REST endpoints
#        mock.*     — Phase 2 mock-data dev stack
#        hosts.*    — /etc/hosts integration for mock vhosts
#        watch.*    — Phase 2.8 source-watcher
#        track.*    — phases.csv tracker
#        version.*  — versioning chart
#        clean.*    — destructive housekeeping
# ══════════════════════════════════════════════════════════════

# ── Tunables (override on the CLI: `make backtest WEEKS=5`) ──

WEEKS ?= 3
MIN_CONFIDENCE ?=
MARKETS ?=
LEAGUE ?= super_lig
BOOTSTRAP_MIN_MATCHES ?= 100
SVC ?=
DETACH ?=
DATA ?=
MODE ?=
ENDPOINT ?= health
METHOD ?= GET

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

# ══════════════════════════════════════════════════════════════
#                      DAILY VERBS
# ══════════════════════════════════════════════════════════════

.PHONY: env
env: ## Bootstrap xops/env/.env from xops/env/.env.example
	@$(XOPS)/env.py env

.PHONY: up
up: env ## Start all services (DETACH=1 for background)
	@$(XOPS)/services.py up

.PHONY: down
down: ## Stop and remove all containers
	@$(XOPS)/services.py down

.PHONY: restart
restart: ## Restart all services
	@$(XOPS)/services.py restart

.PHONY: logs
logs: ## Tail logs (SVC=ai|server|… for one service; default: all)
	@$(XOPS)/logs.py logs

.PHONY: test
test: env ## Run the full test suite
	@$(XOPS)/tests.py test

.PHONY: lint
lint: ## Run hardcode/no-magic lint over ai/
	@$(XOPS)/lint.py lint

# ── AI workflows (daily) ────────────────────────────────────

.PHONY: scrape
scrape: env ## Scrape & cache real match data (LEAGUE=super_lig)
	@$(XOPS)/ai_commands.py scrape --league $(LEAGUE)

.PHONY: bootstrap
bootstrap: env ## Scrape + validate cache (gate before training)
	@$(XOPS)/ai_commands.py bootstrap --league $(LEAGUE) --min-matches $(BOOTSTRAP_MIN_MATCHES)

.PHONY: train
train: env ## Full training pipeline (scrape → validate → split → train → verify → report)
	@$(XOPS)/ai_commands.py train-full --league $(LEAGUE)

.PHONY: train-model
train-model: env ## Training pipeline stages 1-4 only (no verify/report)
	@$(XOPS)/ai_commands.py train-model --league $(LEAGUE)

.PHONY: backtest
backtest: env ## Multi-market backtest (WEEKS=N MIN_CONFIDENCE=0.55 MARKETS=ms,au_2.5,…)
	@$(XOPS)/ai_commands.py backtest --weeks $(WEEKS) \
		$(if $(MIN_CONFIDENCE),--min-confidence $(MIN_CONFIDENCE),) \
		$(if $(MARKETS),--markets $(MARKETS),)

# ══════════════════════════════════════════════════════════════
#                       AI (one-shot)
# ══════════════════════════════════════════════════════════════

.PHONY: ai.pipeline
ai.pipeline: env ## Run the full AI pipeline (scrape → process → analyze → respond)
	@$(XOPS)/ai_commands.py ai.pipeline

.PHONY: ai.demo
ai.demo: env ## Run Turkish Q&A demo questions
	@$(XOPS)/ai_commands.py ai.demo

.PHONY: ai.shell
ai.shell: env ## Open a shell in the AI container
	@$(XOPS)/ai_commands.py ai.shell

.PHONY: ai.continuous
ai.continuous: env ## Run AI in a continuous loop (MODE=pipeline|demo, default: pipeline)
	@$(XOPS)/ai_commands.py ai.continuous

# ══════════════════════════════════════════════════════════════
#                  PER-SERVICE SHORTCUTS
# ══════════════════════════════════════════════════════════════

.PHONY: ai
ai: env ## Run only the AI service
	@$(XOPS)/services.py ai

.PHONY: server
server: env ## Run only the Go server + dependencies
	@$(XOPS)/services.py server

.PHONY: infra
infra: env ## Start only infrastructure (PostgreSQL + Redis)
	@$(XOPS)/services.py infra

# ══════════════════════════════════════════════════════════════
#                       DATABASE & CACHE
# ══════════════════════════════════════════════════════════════

.PHONY: db.migrate
db.migrate: env ## Run all pending database migrations
	@$(XOPS)/db.py db.migrate

.PHONY: db.seed
db.seed: env ## Seed PostgreSQL with local JSON cache
	@$(XOPS)/db.py db.seed

.PHONY: db.shell
db.shell: env ## Open PostgreSQL shell
	@$(XOPS)/db.py db.shell

.PHONY: db.reset
db.reset: ## Reset database (WARNING: destroys all data)
	@$(XOPS)/db.py db.reset

.PHONY: cache.shell
cache.shell: env ## Open Redis CLI
	@$(XOPS)/db.py cache.shell

# ══════════════════════════════════════════════════════════════
#                       GO SERVER (API)
# ══════════════════════════════════════════════════════════════

.PHONY: api
api: ## Call a Go server endpoint (ENDPOINT=health|matches|teams|scrape  METHOD=GET|POST)
	@$(XOPS)/server_api.py call --endpoint $(ENDPOINT) --method $(METHOD)

# ══════════════════════════════════════════════════════════════
#                          STATUS
# ══════════════════════════════════════════════════════════════

.PHONY: health
health: ## Check health of all running services
	@$(XOPS)/status.py health

.PHONY: status
status: ## Show running service status
	@$(XOPS)/status.py status

.PHONY: ports
ports: ## Show exposed ports
	@$(XOPS)/status.py ports

# ══════════════════════════════════════════════════════════════
#                          CLEANUP
# ══════════════════════════════════════════════════════════════

.PHONY: clean
clean: ## Remove containers, networks, and build cache
	@$(XOPS)/cleanup.py clean

.PHONY: clean.all
clean.all: ## Remove everything including volumes (DATA=1 also wipes ./data)
	@$(XOPS)/cleanup.py clean.all

# ══════════════════════════════════════════════════════════════
#               PHASE 2 — MOCK-DATA DEV STACK
# ══════════════════════════════════════════════════════════════

.PHONY: mock.up
mock.up: env ## Bring up nginx-mock + mocksrv
	@$(XOPS)/mock.py up

.PHONY: mock.down
mock.down: ## Tear down the mock stack
	@$(XOPS)/mock.py down

.PHONY: mock.smoke
mock.smoke: ## From-zero E2E sanity (reset → capture → up → curl every vhost)
	@$(XOPS)/mock.py smoke

.PHONY: mock.capture
mock.capture: ## Refresh seed corpus (idempotent; FORCE=1 to refetch, DEPTH=1 to crawl)
	@$(XOPS)/mock.py capture

.PHONY: mock.reset
mock.reset: ## Wipe seed corpus + manifest
	@$(XOPS)/mock.py reset

.PHONY: mock.verify
mock.verify: ## Offline integrity check of seed corpus
	@$(XOPS)/mock.py verify

.PHONY: mock.nginx
mock.nginx: ## Re-render infra/mock/nginx/ vhost configs
	@$(XOPS)/mock.py nginx

.PHONY: mock.ca-init
mock.ca-init: ## Generate self-signed root CA + leaf certs
	@$(XOPS)/mock.py ca-init

.PHONY: mock.ca-trust
mock.ca-trust: ## Rebuild & re-trust CA inside agent images
	@$(XOPS)/mock.py ca-trust

.PHONY: mock.sources
mock.sources: ## Print the registered mock sources
	@$(XOPS)/mock.py sources

.PHONY: mock.browser
mock.browser: ## Print exact sudo commands to make *.local browser-ready
	@$(XOPS)/mock.py browser

.PHONY: mock.trust
mock.trust: ## [sudo] Install dev root CA into system + every Firefox profile
	@$(XOPS)/mock.py trust

.PHONY: mock.untrust
mock.untrust: ## [sudo] Remove dev root CA from system + every Firefox profile
	@$(XOPS)/mock.py untrust

.PHONY: mock.setup
mock.setup: ## [sudo] One-shot: hosts.install + mock.trust + mock.up
	@$(XOPS)/mock.py setup

# ── /etc/hosts integration ──────────────────────────────────

.PHONY: hosts.install
hosts.install: ## [sudo] Add mock domain → 127.0.0.1 entries
	@$(XOPS)/hosts.py install

.PHONY: hosts.uninstall
hosts.uninstall: ## [sudo] Remove mock domain entries
	@$(XOPS)/hosts.py uninstall

.PHONY: hosts.status
hosts.status: ## Show current /etc/hosts state for mock vhosts
	@$(XOPS)/hosts.py status

.PHONY: hosts.preview
hosts.preview: ## Show the hostnames the mock stack will register
	@$(XOPS)/hosts.py show

# ── Source-watcher agent (Phase 2.8) ────────────────────────

.PHONY: watch.run
watch.run: ## One-shot source-watcher pass against current seed corpus
	@$(XOPS)/watch.py run

.PHONY: watch.history
watch.history: ## Show snapshot history (SOURCE=<mock_host>)
	@$(XOPS)/watch.py history $(SOURCE)

.PHONY: watch.sources
watch.sources: ## List registered source keys/hosts
	@$(XOPS)/watch.py sources

# ══════════════════════════════════════════════════════════════
#                          TESTING
# ══════════════════════════════════════════════════════════════

.PHONY: test.ai
test.ai: env ## Run AI module tests only
	@$(XOPS)/tests.py test-ai

.PHONY: test.integration
test.integration: env ## Full-pipeline integration test (skips cleanly if real data missing)
	@$(XOPS)/tests.py test-integration

# ══════════════════════════════════════════════════════════════
#                       PHASE 4 SWARM DEMO
# ══════════════════════════════════════════════════════════════

.PHONY: swarm.demo
swarm.demo: ## Phase 4.8 DoD — end-to-end scrape→categorize→process→store
	@$(XOPS)/swarm.py demo $(if $(LEAGUE),--league $(LEAGUE),)

.PHONY: reactor.replay
reactor.replay: ## Replay freshness events for one reactor (REACTOR=name SINCE=ts)
	@$(XOPS)/reactor.py replay --reactor $(REACTOR) --since $(SINCE)

# ══════════════════════════════════════════════════════════════
#                       PHASE TRACKING
# ══════════════════════════════════════════════════════════════

.PHONY: track.list
track.list: ## List latest status per roadmap phase
	@$(PY) docs/tracking/track.py list

.PHONY: track.show
track.show: ## Show full history for one phase (PHASE=0)
	@$(PY) docs/tracking/track.py show $(PHASE)

.PHONY: track.add
track.add: ## Append entry (PHASE=N STATUS=… [SUB=…] [NOTE="…"] [DIVERGENCE="…"])
	@$(PY) docs/tracking/track.py add $(PHASE) --status $(STATUS) \
		$(if $(SUB),--subphase $(SUB),) \
		$(if $(NOTE),--note "$(NOTE)",) \
		$(if $(DIVERGENCE),--divergence "$(DIVERGENCE)",)

.PHONY: track.export
track.export: ## Export the tracker log (FORMAT=md|csv)
	@$(PY) docs/tracking/track.py export --format $(or $(FORMAT),md)

# ══════════════════════════════════════════════════════════════
#                        VERSIONING
# ══════════════════════════════════════════════════════════════

.PHONY: version.show
version.show: ## Print project + component versions (CHANGELOG=N for log tail)
	@$(XOPS)/version.py show

.PHONY: version.bump
version.bump: ## Bump COMPONENT=<key> LEVEL=<major|minor|patch> [NOTE="..."]
	@$(XOPS)/version.py bump

.PHONY: version.validate
version.validate: ## Validate chart.json schema
	@$(XOPS)/version.py validate

# ══════════════════════════════════════════════════════════════
#                  GIT (HUMAN-ONLY)
# ══════════════════════════════════════════════════════════════
#  ⚠️  AI assistants MUST NOT invoke `git` (see AGENTS.md §10).

.PHONY: git
git: ## [HUMAN-ONLY] Stage all, commit (Conventional Commits), push
	@$(XOPS)/git_helper.py commit

.PHONY: git.dry
git.dry: ## Preview the commit `make git` would create — no staging, no commit, no push
	@$(XOPS)/git_helper.py dry

# ══════════════════════════════════════════════════════════════
#                            HELP
# ══════════════════════════════════════════════════════════════

.PHONY: help
help: ## Show this help message
	@echo ""
	@echo "⚽ Negelir — Multi-league Football Analysis System"
	@echo "═══════════════════════════════════════════════════════════════"
	@echo ""
	@echo "Daily verbs:    env, up, down, restart, logs, test, lint, train,"
	@echo "                scrape, bootstrap, backtest, help"
	@echo "Domains:        ai.*  db.*  cache.*  api  mock.*  hosts.*  watch.*"
	@echo "                track.*  version.*  clean / clean.all"
	@echo ""
	@echo "All targets:"
	@echo ""
	@grep -E '^[a-zA-Z0-9_.-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'
	@echo ""
# ══════════════════════════════════════════════════════════════
