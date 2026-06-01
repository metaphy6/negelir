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

.PHONY: verify.lua
verify.lua: ## Phase 7 §7.3 — verify infra/redis/lua/*.lua SHA headers
	@$(XOPS)/lua.py verify

.PHONY: verify.age-pin
verify.age-pin: ## Phase 8 §8.14.3 — verify age binary SHA-256 vs provenance record (CI supply-chain gate)
	@$(XOPS)/backup_pin.py verify-age-pin

.PHONY: verify.dlq-replay-policy
verify.dlq-replay-policy: ## Phase 8 §8.16.7 — verify DLQ replay overrides vs security exception registry
	@$(XOPS)/verify.py dlq-replay-policy

.PHONY: audit.verify-api
audit.verify-api: ## §9.8 — walk api_audit_log HMAC chain; Phase 1 linkage check + Phase 2 HMAC recomputation (exit 1 on any break)
	@$(XOPS)/audit_api.py verify-api

.PHONY: audit.repair-api
audit.repair-api: ## §9.17.7 — drain api_audit_log_quarantine back to api_audit_log after chain-integrity break (operator runbook)
	@$(XOPS)/audit_api.py repair-api

.PHONY: ops.backup-bump-age
ops.backup-bump-age: ## §8.14.3 — upgrade the age binary pin (VERSION=<v>) — sanctioned operator path
	@$(XOPS)/backup_pin.py backup-bump-age

.PHONY: ops.bootstrap-key
ops.bootstrap-key: ## §8.14.4 — generate per-operator HMAC key (OPERATOR=<email>) at ~/.negelir/opsctl_key (mode 0600)
	@$(XOPS)/opsctl.py bootstrap-key

.PHONY: ops.bootstrap-audit-key
ops.bootstrap-audit-key: ## §8.15.7 — generate audit chain HMAC key at cfg.audit_chain_hmac_key_path (mode 0400)
	@$(XOPS)/opsctl.py bootstrap-audit-key

.PHONY: ops.bootstrap-allowlist-key
ops.bootstrap-allowlist-key: ## §8.16.10 — generate allowlist HMAC key at cfg.sec_input_allowlist_hmac_key_path (mode 0400)
	@$(XOPS)/opsctl.py bootstrap-allowlist-key

.PHONY: ops.verify-key-id
ops.verify-key-id: ## §8.16.14 — self-verify local key_id matches opsctl_operators.json (OPERATOR=<email>)
	@$(XOPS)/opsctl.py verify-key-id

.PHONY: fix.lua
fix.lua: ## Phase 7 §7.3 — rewrite Lua SHA headers after intended edits
	@$(XOPS)/lua.py fix

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

.PHONY: swarm.backtest
swarm.backtest: ## Phase 5.5 — replay swarm chain over historical matches (WEEKS=N)
	@$(XOPS)/ai_commands.py swarm.backtest --weeks $(or $(WEEKS),3)

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

.PHONY: api.up
api.up: ## Bring up the API compose service
	@$(XOPS)/api.py up

.PHONY: api.down
api.down: ## Stop the API compose service
	@$(XOPS)/api.py down

.PHONY: api.build
api.build: ## Build the Go server binary (cpu_only build tag)
	@$(XOPS)/api.py build

.PHONY: api.gen
api.gen: ## Regenerate Go handlers from server/api/openapi.yaml (oapi-codegen)
	@$(XOPS)/api.py gen

.PHONY: api.gen-check
api.gen-check: ## CI gate: regenerate into tmpdir, assert no handler drift
	@$(XOPS)/api.py gen-check

.PHONY: api.docs
api.docs: ## Serve Swagger UI on localhost:8081 (compose profile=docs)
	@$(XOPS)/api.py docs

.PHONY: api.init
api.init: ## §9.10 First-run bootstrap: JWT keypair kid_001, cursor seal key, optional mTLS (WITH_TLS=--with-tls)
	@$(XOPS)/api.py init $(WITH_TLS)

.PHONY: api.rotate-jwt-key
api.rotate-jwt-key: ## Rotate JWT keypair (pending→active, old→retired, grace purge)
	@$(XOPS)/api.py rotate-jwt-key

.PHONY: api.revoke-jti
api.revoke-jti: ## Add JTI to Redis revocation deny-set (JTI=<uuid>)
	@$(XOPS)/api.py revoke-jti --jti $(JTI)

.PHONY: api.tls-rotate
api.tls-rotate: ## Renew mTLS service certs from Phase 2 internal CA
	@$(XOPS)/api.py tls-rotate

.PHONY: api.rotate-cursor-key
api.rotate-cursor-key: ## Rotate the AES-GCM cursor seal key
	@$(XOPS)/api.py rotate-cursor-key

.PHONY: api.rotate-tls-session-key
api.rotate-tls-session-key: ## §9.17.8 — Rotate TLS session ticket key in Redis (api:tls:session_ticket_key); roll API replicas after
	@$(XOPS)/api.py rotate-tls-session-key

.PHONY: api.bump-bcrypt-cost
api.bump-bcrypt-cost: ## Bump NEGELIR_API_BCRYPT_COST and trigger rolling re-hash
	@$(XOPS)/api.py bump-bcrypt-cost

.PHONY: api.erase-user
api.erase-user: ## §9.8 GDPR right-to-erasure: null-stamp api_audit_log.user_id + purge users row + pii_erased emit (USER=<uuid-or-email>)
	@$(XOPS)/audit_api.py erase-user --user $(USER)

.PHONY: api.slo-report
api.slo-report: ## 28-day rolling SLO summary (Phase 19 GA gate input)
	@$(XOPS)/api.py slo-report

.PHONY: nlp.bench
nlp.bench: ## Phase 10 §10.1 — normalize_input p95 latency gate (≤5 ms on nlp_input_max_codepoints input)
	@$(XOPS)/nlp.py nlp.bench

.PHONY: nlp.entity-bench
nlp.entity-bench: ## Phase 10 §10.5 — EntityExtractor.extract p95 latency gate (≤8 ms on cap-length token list)
	@$(XOPS)/nlp.py nlp.entity-bench

.PHONY: nlp.intent-pin
nlp.intent-pin: ## Phase 10 §10.4 — SHA256-pin the fastText intent model (hashes model file, writes sha to chart.json)
	@$(XOPS)/nlp.py nlp.intent-pin

.PHONY: nlp.lexicon-build
nlp.lexicon-build: ## Phase 10 §10.2 — apply _aliases_delta.tr.yaml onto lexicons, bump patch version
	@$(XOPS)/nlp.py nlp.lexicon-build

.PHONY: nlp.diacritics-build
nlp.diacritics-build: ## Phase 10 §10.3 — generate _diacritics.tr.yaml from tr_word_freq.txt + lexicon union
	@$(XOPS)/nlp.py nlp.diacritics-build

.PHONY: nlp.rotate-citation-key
nlp.rotate-citation-key: ## Phase 10 §10.21.8 — rotate predict citation HMAC key (dual-acceptance grace window)
	@$(XOPS)/nlp.py nlp.rotate-citation-key

.PHONY: nlp.template-lint
nlp.template-lint: ## Phase 10 §10.15 — AST-assert no {{ free_text }} slot in any template (hallucination guard)
	@$(XOPS)/nlp.py nlp.template-lint

.PHONY: nlp.eval-diff
nlp.eval-diff: ## Phase 10 §10.18 — Regression diff: compare intent/entity/render outcomes vs BASELINE sha (usage: make nlp.eval-diff BASELINE=<sha>)
	@$(XOPS)/nlp.py nlp.eval-diff $(BASELINE)

.PHONY: verify.nlp-lexicons
verify.nlp-lexicons: ## Phase 10 §10.2 — assert (a) canonical_id resolves (b) no uncovered alias collision (c) normalize round-trip
	@$(XOPS)/nlp.py verify.nlp-lexicons

.PHONY: verify.nlp-schemas
verify.nlp-schemas: ## Phase 10 §10.19 — assert all four NLP topics (qa.intent.v1, qa.answer.v1, nlp.event.v1, nlp.alert.v1) have valid JSON Schema files
	@$(XOPS)/nlp.py verify.nlp-schemas

.PHONY: api.bench
api.bench: ## §9.17.5 per-endpoint latency benchmark (k6, 200 RPS, 60s); asserts §9.17.5 latency table
	@$(XOPS)/bench.py api.bench

.PHONY: api.pprof-enable
api.pprof-enable: ## §9.17.10 enable pprof on the metrics port for POD (1h TTL); usage: make api.pprof-enable POD=<pod-name>
	@$(XOPS)/api.py pprof-enable --pod $(POD)

.PHONY: api.profile-show
api.profile-show: ## §9.17.10 print the latest continuous CPU profile path (or open it); LATEST=1 for the most recent file
	@$(XOPS)/api.py profile-show $(if $(LATEST),--latest,)

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

.PHONY: test.fast
test.fast: env ## Fast loop: full suite minus @pytest.mark.slow tests (audit P6)
	@$(XOPS)/tests.py test-fast

.PHONY: test.integration
test.integration: env ## Full-pipeline integration test (skips cleanly if real data missing)
	@$(XOPS)/tests.py test-integration

# ══════════════════════════════════════════════════════════════
#                       PHASE 4 SWARM DEMO
# ══════════════════════════════════════════════════════════════

.PHONY: swarm.demo
swarm.demo: ## Phase 4.8 DoD — end-to-end scrape→categorize→process→store
	@$(XOPS)/swarm.py demo $(if $(LEAGUE),--league $(LEAGUE),)

.PHONY: swarm.demo.nlp
swarm.demo.nlp: ## Phase 10 §10.21.14 — swarm.demo + NLP extension scenarios within 30s budget
	@$(XOPS)/swarm.py demo-nlp $(if $(LEAGUE),--league $(LEAGUE),)

.PHONY: swarm.demo.live
swarm.demo.live: ## Phase 8.16.13 — live Redis ops.denylist-clear demo with realistic ack budget
	@$(XOPS)/swarm.py demo-live

.PHONY: reactor.replay
reactor.replay: ## Replay freshness events for one reactor (REACTOR=name SINCE=ts)
	@$(XOPS)/reactor.py replay --reactor $(REACTOR) --since $(SINCE)

# ══════════════════════════════════════════════════════════════
#                  PHASE 8 — OPS CONSOLE (§8.1)
# ══════════════════════════════════════════════════════════════
#  Operator CLI for the maint plane. Publishes maint.event.v1 and
#  waits for maint.ack.v1 from the registered consumer set (kind→
#  consumer map at ai/swarm/agents/maint/_ack_routing.py). Exit
#  codes are pinned in xops/opsctl/_exit_codes.py and consumed by
#  runbooks + the dead-mans-switch alerter.

.PHONY: ops.liveness
ops.liveness: ## §8.1 — read-only smoke check (no bus publish)
	@$(XOPS)/opsctl.py liveness

.PHONY: ops.denylist-clear
ops.denylist-clear: ## §8.1 — clear sec.rate.v1 denylist (TARGET=<subject>)
	@$(XOPS)/opsctl.py denylist-clear

.PHONY: ops.quarantine-erase
ops.quarantine-erase: ## §8.1 — erase quarantine sample (TARGET=<id> CONFIRM=<token>) DESTRUCTIVE
	@$(XOPS)/opsctl.py quarantine-erase

.PHONY: ops.baseline-reset
ops.baseline-reset: ## §8.1 — reset sec.scrape.v1 source baseline (TARGET=<source_id>)
	@$(XOPS)/opsctl.py baseline-reset

.PHONY: ops.quarantine-clear
ops.quarantine-clear: ## §8.1 — clear quarantine FP (TARGET=<sample_id>) [§8.7 consumer pending]
	@$(XOPS)/opsctl.py quarantine-clear

.PHONY: ops.spool-flush
ops.spool-flush: ## §8.1 — drain bus-down spool (MAX_ENTRIES=<n>)
	@$(XOPS)/opsctl.py spool-flush

.PHONY: ops.maint-pause
ops.maint-pause: ## §8.10 — pause maint agent(s) (TARGET=<agent|all> [TTL_S=<s>])
	@$(XOPS)/opsctl.py maint-pause

.PHONY: ops.maint-resume
ops.maint-resume: ## §8.10 — resume maint agent(s) (TARGET=<agent|all>)
	@$(XOPS)/opsctl.py maint-resume

.PHONY: ops.scale
ops.scale: ## §8.2 — pin replicas (TARGET=<agent> REPLICAS=<n> [TTL_S=<s>])
	@$(XOPS)/opsctl.py scale

.PHONY: ops.dlq-replay
ops.dlq-replay: ## §8.5 — replay DLQ (TARGET=<topic.dlq> [MAX_MSGS=<n>] [DROP=1] [CONFIRM_PII=1])
	@$(XOPS)/opsctl.py dlq-replay

.PHONY: ops.dlq-unfreeze
ops.dlq-unfreeze: ## §8.5 — lift poison-pattern freeze (TARGET=<topic.dlq>)
	@$(XOPS)/opsctl.py dlq-unfreeze

.PHONY: ops.denylist-decimate-now
ops.denylist-decimate-now: ## §8.8 — force denylist decimation sweep ([TARGET=all])
	@$(XOPS)/opsctl.py denylist-decimate-now

.PHONY: ops.scale-pin
ops.scale-pin: ## §8.1 — sugar over ops.scale (TARGET=<agent> REPLICAS=<n> [TTL_S=<s>])
	@$(XOPS)/opsctl.py scale-pin

.PHONY: ops.scale-unpin
ops.scale-unpin: ## §8.1 — cancel an active scale pin (TARGET=<agent>)
	@$(XOPS)/opsctl.py scale-unpin

.PHONY: ops.spool-show
ops.spool-show: ## §8.1 — read-only spool listing ([LIMIT=<n>])
	@$(XOPS)/opsctl.py spool-show

.PHONY: ops.spool-reconcile
ops.spool-reconcile: ## §8.16.2 — alert on stale incomplete spool-flush ack rows ([HORIZON_H=<h>])
	@$(XOPS)/opsctl.py spool-reconcile

.PHONY: ops.retrain-approve
ops.retrain-approve: ## §8.1 — authorize a trainer run (TARGET=<predictor> [DRIFT_REQUEST_ID=<uuid>] [NOTE=<text>])
	@$(XOPS)/opsctl.py retrain-approve

.PHONY: ops.backup-now
ops.backup-now: ## §8.1/§8.3 — force PG dump+verify (TARGET=pg [SKIP_PRUNE=1] [REASON=<text>])
	@$(XOPS)/opsctl.py backup-now

.PHONY: ops.backup-rotate-key
ops.backup-rotate-key: ## §8.1/§8.13.6 — rotate backup keys (TARGET=<label> SCOPE=verify|dr [ADD_RECIPIENT=<age>] CONFIRM=<token>) DESTRUCTIVE
	@$(XOPS)/opsctl.py backup-rotate-key

.PHONY: ops.restore
ops.restore: ## §8.1/§8.3 — restore PG (DATE=YYYY-MM-DD [TARGET=<dsn>] [FROM_OFFSITE=1] [CONFIRM_OVERWRITE_LIVE=1] CONFIRM=<token>) DESTRUCTIVE
	@$(XOPS)/opsctl.py restore

.PHONY: ops.allowlist-extend
ops.allowlist-extend: ## §8.1/§8.7 — extend allowlist row TTL (TARGET=<source>:<rule> [TTL_S=<s>])
	@$(XOPS)/opsctl.py allowlist-extend

.PHONY: ops.allowlist-approve
ops.allowlist-approve: ## §8.1/§8.7 — promote allowlist row pending→active (TARGET=<source>:<rule>)
	@$(XOPS)/opsctl.py allowlist-approve

.PHONY: ops.allowlist-show
ops.allowlist-show: ## §8.1/§8.7 — read-only allowlist query (TARGET=all|<source>|<source>:<rule> [INCLUDE_EXPIRED=1])
	@$(XOPS)/opsctl.py allowlist-show

.PHONY: ops.allowlist-rehash
ops.allowlist-rehash: ## §8.16.10 — trigger legacy SHA→HMAC allowlist rehash ([TARGET=all|<source>] [BATCH_SIZE=<n>])
	@$(XOPS)/opsctl.py allowlist-rehash

.PHONY: ops.rotate-allowlist-key
ops.rotate-allowlist-key: ## §8.16.10 — trigger allowlist HMAC key rotation ([TARGET=<label>] [NO_REHASH=1])
	@$(XOPS)/opsctl.py rotate-allowlist-key

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

.PHONY: version.compatibility-check
version.compatibility-check: ## Validate top-level compatibility constraints in chart.json
	@$(XOPS)/version.py compatibility-check

# ══════════════════════════════════════════════════════════════
#                CODEGRAPH (dev MCP index)
# ══════════════════════════════════════════════════════════════
#  Local semantic code index exposed to all four agent surfaces.
#  Sanctioned host-tool exception per AGENTS.md §2 Rule 2.
#  See docs/guides/CODEGRAPH.md.

.PHONY: codegraph.status
codegraph.status: ## Sanity-check the local CodeGraph index (cheap; agent-safe)
	@$(XOPS)/codegraph.py status

.PHONY: codegraph.reindex
codegraph.reindex: ## Rebuild the CodeGraph index from scratch (after big refactors)
	@$(XOPS)/codegraph.py reindex

.PHONY: codegraph.check
codegraph.check: ## Compare pinned npm version to latest; audit wiring drift
	@$(XOPS)/codegraph.py check

.PHONY: codegraph.upgrade
codegraph.upgrade: ## Bump pin across all wirings [VERSION=x.y.z, default=latest]
	@$(XOPS)/codegraph.py upgrade

# ══════════════════════════════════════════════════════════════
#               ROADMAP PHASE ORCHESTRATION
# ══════════════════════════════════════════════════════════════
#  Parallel-safe coordinator for delegating ROADMAP phases to
#  context-isolated subagents. See xops/orchestrator/README.md and
#  .github/prompts/orchestrate.roadmap.prompt.md.
#
#  Filter env vars (most targets): INCLUDE=5,8.13  EXCLUDE=9.17.11
#                                  INCLUDE_BRANCHES=1  INCLUDE_COMPLETE=1
#                                  JSON=1  LEAVES=1

.PHONY: orchestrate.list
orchestrate.list: ## List every phase with checkbox status (LEAVES=1 for leaves only)
	@$(XOPS)/orchestrate.py list

.PHONY: orchestrate.plan
orchestrate.plan: ## Dry-run the include/exclude filter (INCLUDE=…  EXCLUDE=…)
	@$(XOPS)/orchestrate.py plan

.PHONY: orchestrate.next
orchestrate.next: ## Print the next eligible un-claimed phase
	@$(XOPS)/orchestrate.py next

.PHONY: orchestrate.slice
orchestrate.slice: ## Print the ROADMAP slice for PHASE=<id> [OUT=path]
	@$(XOPS)/orchestrate.py slice

.PHONY: orchestrate.claim
orchestrate.claim: ## Acquire the per-phase lock — PHASE=<id> [CLAIMER=<id>]
	@$(XOPS)/orchestrate.py claim

.PHONY: orchestrate.release
orchestrate.release: ## Release the per-phase lock — PHASE=<id> [FORCE=1]
	@$(XOPS)/orchestrate.py release

.PHONY: orchestrate.locks
orchestrate.locks: ## List currently held phase locks
	@$(XOPS)/orchestrate.py locks

.PHONY: orchestrate.state
orchestrate.state: ## Show orchestrator state — [PHASE=<id>] for one phase
	@$(XOPS)/orchestrate.py state

.PHONY: orchestrate.advance
orchestrate.advance: ## Record a review pass — PHASE=<id> [STATUS=…] [ROLE=…] [OUTCOME=…] [MODEL=…] [NOTES=…]
	@$(XOPS)/orchestrate.py advance

.PHONY: orchestrate.unlock
orchestrate.unlock: ## [OPERATOR] Force-clear a stale lock — PHASE=<id>
	@$(XOPS)/orchestrate.py unlock

.PHONY: orchestrate.resume-list
orchestrate.resume-list: ## List CI resume cursors (READY=1 for cursors past not_before)
	@$(XOPS)/orchestrate.py resume-list

.PHONY: orchestrate.resume-drop
orchestrate.resume-drop: ## Drop a CI resume cursor — RUN_ID=<id>
	@$(XOPS)/orchestrate.py resume-drop

.PHONY: roadmap.split
roadmap.split: ## Extract a long ROADMAP phase into docs/design/phase<N>/ — PHASE=<id> [FORCE=1] [DRY=1]
	@PHASE=$(PHASE) FORCE=$(FORCE) DRY=$(DRY) python3 $(XOPS)/roadmap_split.py extract \
	    --phase $(PHASE) $(if $(filter 1 true yes,$(FORCE)),--force,) $(if $(filter 1 true yes,$(DRY)),--dry-run,)

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
