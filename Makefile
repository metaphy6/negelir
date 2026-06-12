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

.PHONY: verify.adversarial-corpora
verify.adversarial-corpora: ## Phase 12 §12.2 — verify adversarial corpus integrity (disjointness, PII, SHA256, reviewers)
	@$(XOPS)/verify.py adversarial-corpora

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

.PHONY: league.scaffold
league.scaffold: env ## Phase 13.3 — scaffold new league preset (LEAGUE_ID=… COUNTRY=… CONFEDERATION=…)
	@$(XOPS)/league.py scaffold

.PHONY: identity.merge
identity.merge: env ## Phase 13.4.4 — operator merge stable_ids (STABLE_IDS=a,b REASON="")
	@$(XOPS)/identity.py merge --stable-ids "$(STABLE_IDS)" --reason "$(REASON)"

.PHONY: identity.split
identity.split: env ## Phase 13.4.4 — operator split stable_id (STABLE_ID=x INTO=a,b REASON="")
	@$(XOPS)/identity.py split --stable-id "$(STABLE_ID)" --into "$(INTO)" --reason "$(REASON)"

.PHONY: nlp.audit-rerender
nlp.audit-rerender: env ## Operator-only runbook for NLP audit bundle re-render
	@$(XOPS)/nlp.py nlp.audit-rerender

.PHONY: nlp.complaint-trace
nlp.complaint-trace: env ## Phase 10 §10.27.3 — operator forensic complaint trace rebuild by request_id
	@$(XOPS)/nlp.py nlp.complaint-trace

.PHONY: nlp.complaint-trace-with-text
nlp.complaint-trace-with-text: env ## Phase 10 §10.27.3 — operator complaint trace with PII confirmation
	@$(XOPS)/nlp.py nlp.complaint-trace-with-text $(ARGS)

.PHONY: nlp.sbom
nlp.sbom: env ## Generate NLP SBOM and write data/nlp/sbom.json
	@$(XOPS)/nlp.py nlp.sbom

.PHONY: nlp.license-attribution
nlp.license-attribution: env ## Generate NLP license attribution report at data/nlp/build_reports/license_attribution.md
	@$(XOPS)/nlp.py nlp.license-attribution

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
backtest: env ## Backtest: market (WEEKS=N) or competition calibration (COMPETITION=<id> [SEED=...] [WORKERS=...])
	@$(XOPS)/ai_commands.py backtest \
		$(if $(COMPETITION),--competition $(COMPETITION),--weeks $(or $(WEEKS),3)) \
		$(if $(MIN_CONFIDENCE),--min-confidence $(MIN_CONFIDENCE),) \
		$(if $(MARKETS),--markets $(MARKETS),) \
		$(if $(SEED),--seed $(SEED),) \
		$(if $(WORKERS),--workers $(WORKERS),) \
		$(if $(ALL),--all,)

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

.PHONY: nlp.spike-test
nlp.spike-test: ## Phase 10 §10.23.10 — operator-facing 3× spike rehearsal target for NLP spike-run drill
	@$(XOPS)/nlp.py nlp.spike-test

.PHONY: nlp.dr-drill
nlp.dr-drill: ## Phase 10 §10.23.11 — human-only NLP disaster-recovery drill helper and report stub
	@$(XOPS)/nlp.py nlp.dr-drill

.PHONY: nlp.intent-pin
nlp.intent-pin: ## Phase 10 §10.4 — SHA256-pin the fastText intent model (hashes model file, writes sha to chart.json)
	@$(XOPS)/nlp.py nlp.intent-pin

.PHONY: nlp.intent-train
nlp.intent-train: ## Phase 10 §10.25.5 — operator-driven intent model retrain from shadow samples and write a candidate model
	@$(XOPS)/nlp.py nlp.intent-train $(ARGS)

.PHONY: nlp.lexicon-build
nlp.lexicon-build: ## Phase 10 §10.2 — apply _aliases_delta.tr.yaml onto lexicons, bump patch version
	@$(XOPS)/nlp.py nlp.lexicon-build

.PHONY: nlp.lexicon-restore-from-snapshot
nlp.lexicon-restore-from-snapshot: ## Phase 10 §10.32 — dry-run-safe lexicon restore runbook command
	@$(XOPS)/nlp.py nlp.lexicon-restore-from-snapshot

.PHONY: nlp.intent-model-restore
nlp.intent-model-restore: ## Phase 10 §10.32 — dry-run-safe intent model restore runbook command
	@$(XOPS)/nlp.py nlp.intent-model-restore

.PHONY: nlp.calibration-pin
nlp.calibration-pin: ## Phase 10 §10.32 — dry-run-safe calibration snapshot pin command
	@$(XOPS)/nlp.py nlp.calibration-pin

.PHONY: nlp.humanizer-rollback
nlp.humanizer-rollback: ## Phase 10 §10.32 — dry-run-safe humanizer rollback runbook command
	@$(XOPS)/nlp.py nlp.humanizer-rollback

.PHONY: nlp.transliteration-build
nlp.transliteration-build: ## Phase 10 §10.28 — validate loanword transliteration variants table and write build report
	@$(XOPS)/nlp.py nlp.transliteration-build

.PHONY: nlp.lexicon-deploy
nlp.lexicon-deploy: ## Phase 10 §10.27 — validate and drain lexicon deploy candidates before promotion
	@$(XOPS)/nlp.py nlp.lexicon-deploy $(ARGS)

.PHONY: nlp.lexicon-eval
nlp.lexicon-eval: ## Phase 10 §10.25.6 — run lexicon acceptance corpus regression check after lexicon build
	@$(XOPS)/nlp.py nlp.lexicon-eval $(ARGS)

.PHONY: nlp.diacritics-build
nlp.diacritics-build: ## Phase 10 §10.3 — generate _diacritics.tr.yaml from tr_word_freq.txt + lexicon union
	@$(XOPS)/nlp.py nlp.diacritics-build

.PHONY: nlp.rotate-citation-key
nlp.rotate-citation-key: ## Phase 10 §10.21.8 — rotate predict citation HMAC key (dual-acceptance grace window)
	@$(XOPS)/nlp.py nlp.rotate-citation-key

.PHONY: nlp.rotate-answer-hmac-key
nlp.rotate-answer-hmac-key: ## Phase 10 §10.26.8 — rotate qa.answer.v1 envelope HMAC key (dual-acceptance grace window)
	@$(XOPS)/nlp.py nlp.rotate-answer-hmac-key

.PHONY: nlp.template-lint
nlp.template-lint: ## Phase 10 §10.15 — AST-assert no {{ free_text }} slot in any template (hallucination guard)
	@$(XOPS)/nlp.py nlp.template-lint

.PHONY: nlp.capacity-report
nlp.capacity-report: ## Phase 10 §10.23.10 — generate the NLP capacity report artifact at data/nlp/capacity_report.md
	@$(XOPS)/nlp.py nlp.capacity-report

.PHONY: nlp.compat-validate
nlp.compat-validate: ## Phase 10 §10.25.4 — validate NLP compatibility matrix and artifact quartet before merge
	@$(XOPS)/nlp.py nlp.compat-validate

.PHONY: nlp.eval-diff
nlp.eval-diff: ## Phase 10 §10.18 — Regression diff: compare intent/entity/render outcomes vs BASELINE sha (usage: make nlp.eval-diff BASELINE=<sha>)
	@$(XOPS)/nlp.py nlp.eval-diff $(BASELINE)

.PHONY: nlp.canary-promote
nlp.canary-promote: ## Phase 10 §10.23 — gate canary rollout to 100% only when shadow metrics and eval harness gates pass
	@$(XOPS)/nlp.py nlp.canary-promote $(ARGS)

.PHONY: nlp.canary-rollback
nlp.canary-rollback: ## Phase 10 §10.23 — rollback canary pods with a single operator command and emit nlp.alert.v1
	@$(XOPS)/nlp.py nlp.canary-rollback $(ARGS)

.PHONY: verify.nlp-lexicons
verify.nlp-lexicons: ## Phase 10 §10.2 — assert (a) canonical_id resolves (b) no uncovered alias collision (c) normalize round-trip
	@$(XOPS)/nlp.py verify.nlp-lexicons

.PHONY: verify.nlp-lexicon-diff
verify.nlp-lexicon-diff: ## Phase 10 §10.26 — assert lexicon PR diff size cap and bot impersonation defense
	@$(XOPS)/nlp.py verify.nlp-lexicon-diff

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

# ── Feeds operations (PITR, manifest, retention) ────
# Phase 16 — Datasource emitter & feed contract

.PHONY: feeds.up
feeds.up: env ## Start feed infrastructure (Postgres, Redis, NATS)
	@$(XOPS)/feeds.py up

.PHONY: feeds.down
feeds.down: ## Stop and drain feed infrastructure
	@$(XOPS)/feeds.py down

.PHONY: feeds.tail
feeds.tail: ## Tail live feed emissions (STREAM=<stream_id>)
	@$(XOPS)/feeds.py tail $(STREAM)

.PHONY: feeds.snapshot.rebuild
feeds.snapshot.rebuild: ## Rebuild snapshot partition (SOURCE=<id> [AFTER=<utc-iso>])
	@$(XOPS)/feeds.py snapshot.rebuild $(SOURCE) $(AFTER)

.PHONY: feeds.prune
feeds.prune: ## Prune expired records before cutoff (BEFORE=<utc-iso> [DRY_RUN=1])
	@$(XOPS)/feeds.py prune $(BEFORE) $(DRY_RUN)

.PHONY: feeds.fsck
feeds.fsck: ## Filesystem integrity check on /data/feeds tree and manifest hashes
	@$(XOPS)/feeds.py fsck

.PHONY: feeds.manifest.rebuild
feeds.manifest.rebuild: ## Rebuild manifest.json from current partition tree (operator runbook)
	@$(XOPS)/feeds.py manifest.rebuild

.PHONY: feeds.parity
feeds.parity: ## Run parity test: live feed vs snapshot vs NDJSON (SOURCE=<id>)
	@$(XOPS)/feeds.py parity $(SOURCE)

.PHONY: feeds.schema.review
feeds.schema.review: ## Manual review of feed schema and partitioning strategy
	@$(XOPS)/feeds.py schema.review

.PHONY: feeds.schema.audit
feeds.schema.audit: ## Audit schema compatibility across all feed versions
	@$(XOPS)/feeds.py schema.audit

.PHONY: feeds.backfill
feeds.backfill: ## Backfill missing feed partitions (SOURCE=<id> FROM=<utc-iso> TO=<utc-iso>)
	@$(XOPS)/feeds.py backfill $(SOURCE) $(FROM) $(TO)

.PHONY: feeds.backfill.promote
feeds.backfill.promote: ## Promote backfilled partitions from staging to live feed tree
	@$(XOPS)/feeds.py backfill.promote

.PHONY: feeds.chaos.run
feeds.chaos.run: ## Run chaos scenario on feeds (SCENARIO=<id>)
	@$(XOPS)/feeds.py chaos.run $(SCENARIO)

.PHONY: feeds.cost.report
feeds.cost.report: ## Report storage + compute cost of feed tree (by source, region, retention)
	@$(XOPS)/feeds.py cost.report

.PHONY: feeds.tombstone.audit
feeds.tombstone.audit: ## Audit tombstone (deleted record) coverage and retention policy compliance
	@$(XOPS)/feeds.py tombstone.audit

.PHONY: feeds.pitr.restore
feeds.pitr.restore: ## Rebuild feeds manifest tree at target time — TARGET=<utc-iso> ROOT=<path> [REGION=eu]
	@$(XOPS)/feeds.py pitr.restore $(TARGET) $(ROOT) $(REGION)

# ── League management (readiness, promotion, calibration) ────
# Phase 13 — League catalog & tier system

.PHONY: leagues.readiness
leagues.readiness: ## Check league readiness for T2/T1 promotion (LEAGUE=<id> TARGET_TIER=<T2|T1>)
	@$(XOPS)/makefile/leagues.py readiness $(LEAGUE) $(TARGET_TIER)

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

# ══════════════════════════════════════════════════════════════
#       PHASE 12 — ADVERSARIAL & CHAOS TEST SUITE (§12.4–§12.5)
# ══════════════════════════════════════════════════════════════

.PHONY: chaos.up
chaos.up: env ## Bring up chaos profile (Toxiproxy + Pumba + chaos-tagged services)
	@$(XOPS)/chaos.py up

.PHONY: chaos.down
chaos.down: ## Tear down chaos profile (idempotent; sweeps orphaned toxics)
	@$(XOPS)/chaos.py down

.PHONY: chaos.run
chaos.run: ## Run one catalogue scenario by stable ID: TEST=<id> (e.g., P12-8-A)
	@$(XOPS)/chaos.py run $(TEST)

.PHONY: chaos.list
chaos.list: ## Print the chaos catalogue (single source: docs/testing/phase12_catalogue.md)
	@$(XOPS)/chaos.py list

.PHONY: test.chaos.inproc
test.chaos.inproc: ## Run in-process FaultInjector scenarios (deterministic, no compose)
	@PYTHONPATH=ai $(PY) -m pytest ai/tests/test_phase12_fault_injector.py -q

# ── §12.6 Bus & Network Chaos ──────────────────────────────

.PHONY: chaos.redis-flap
chaos.redis-flap: env ## [P12-6-A] Drop Redis mid-stream, assert at-least-once + idempotent
	@$(XOPS)/chaos.py redis-flap

.PHONY: chaos.bus-partition
chaos.bus-partition: env ## [P12-6-B] Split producers/consumers, assert backpressure + spool drain
	@$(XOPS)/chaos.py bus-partition

.PHONY: chaos.network-slow
chaos.network-slow: env chaos.up ## [P12-6-C] Inject latency via Toxiproxy, assert budget gates
	@$(XOPS)/chaos.py network-slow

.PHONY: chaos.bus-reorder
chaos.bus-reorder: env ## [P12-6-D] Deliver envelopes out of order, assert no silent FIFO
	@$(XOPS)/chaos.py bus-reorder

.PHONY: chaos.bus-duplicate
chaos.bus-duplicate: env ## [P12-6-E] Redeliver all envelopes twice, assert exactly-once effects
	@$(XOPS)/chaos.py bus-duplicate

.PHONY: chaos.bus-corrupt
chaos.bus-corrupt: env ## [P12-6-F] Flip bytes in envelopes, assert DLQ routing + validation
	@$(XOPS)/chaos.py bus-corrupt

.PHONY: chaos.dlq-poison
chaos.dlq-poison: env ## [P12-6-G] Inject poisoned DLQ entries, assert operator-confirm-only
	@$(XOPS)/chaos.py dlq-poison

.PHONY: chaos.redis-key-collision
chaos.redis-key-collision: env ## [P12-6-H] Test Redis namespace isolation (datasource|swarm|server|common)
	@$(XOPS)/chaos.py redis-key-collision

# ── §12.7 Resource Exhaustion & Performance ─────────────────

.PHONY: chaos.cpu-saturate
chaos.cpu-saturate: env ## [P12-7-A] Pin all vCPUs, assert CPU budget gates + graceful degradation
	@$(XOPS)/chaos.py cpu-saturate

.PHONY: chaos.rss-pressure
chaos.rss-pressure: env ## [P12-7-B] Drive RSS toward pod budget, assert RLIMIT + no OOM-kill
	@$(XOPS)/chaos.py rss-pressure

.PHONY: chaos.fd-exhaust
chaos.fd-exhaust: env ## [P12-7-C] Exhaust file descriptors, assert bounded pools + graceful shed
	@$(XOPS)/chaos.py fd-exhaust

.PHONY: chaos.conn-pool-starve
chaos.conn-pool-starve: env ## [P12-7-D] Starve PG connection pool, assert timeout → structured refusal
	@$(XOPS)/chaos.py conn-pool-starve

.PHONY: chaos.disk-pressure
chaos.disk-pressure: env ## [P12-7-E] Fill data volume, assert pressure alert + refuse before corruption
	@$(XOPS)/chaos.py disk-pressure

.PHONY: chaos.queue-depth-flood
chaos.queue-depth-flood: env ## [P12-7-F] Flood bus queue, assert humanizer-disable + adaptive-shed
	@$(XOPS)/chaos.py queue-depth-flood

.PHONY: chaos.cache-stampede
chaos.cache-stampede: env ## [P12-7-G] N concurrent misses on hot key, assert singleflight collapses
	@$(XOPS)/chaos.py cache-stampede

.PHONY: load.api
load.api: env up ## [P12-7 gate] Performance: k6 driver against API surface, assert p50/p95/p99 budgets
	@$(XOPS)/chaos.py load.api

.PHONY: load.nlp
load.nlp: env up ## [P12-7 gate] Performance: Locust driver against NLP, assert latency budget
	@$(XOPS)/chaos.py load.nlp

.PHONY: load.predictor
load.predictor: env up ## [P12-7 gate] Performance: synthetic prediction load, assert p99 latency
	@$(XOPS)/chaos.py load.predictor

# ── §12.8 Soak & Endurance ──────────────────────────────────

.PHONY: soak.nightly
soak.nightly: env ## [P12-8 nightly] Short soaks: soak.nlp.leak + soak.swarm.short (~1–2h)
	@$(XOPS)/chaos.py soak.nightly

.PHONY: soak.weekly
soak.weekly: env ## [P12-8 weekly, self-hosted] 24h + GPU heat soaks (runs on self-hosted runner)
	@$(XOPS)/chaos.py soak.weekly

.PHONY: soak.report
soak.report: env ## [P12-8 gate] Regenerate soak report from latest ledger rows (freshness-gated)
	@$(XOPS)/chaos.py soak.report

# ── §12.9 Data-Integrity & Corruption Injection ─────────────

.PHONY: chaos.tamper-hmac
chaos.tamper-hmac: env test.chaos.inproc ## [P12-9-A] Tamper with HMAC/signatures, assert detection
	@$(XOPS)/chaos.py tamper-hmac

.PHONY: chaos.checksum-mismatch
chaos.checksum-mismatch: env test.chaos.inproc ## [P12-9-B] Inject checksum corruption, assert detection
	@$(XOPS)/chaos.py checksum-mismatch

.PHONY: chaos.audit-chain-break
chaos.audit-chain-break: env test.chaos.inproc ## [P12-9-C] Corrupt audit-log hash-chain, assert detection
	@$(XOPS)/chaos.py audit-chain-break

.PHONY: chaos.replay-storm
chaos.replay-storm: env ## [P12-9-D] Replay envelope stream 5× through idempotent consumers
	@$(XOPS)/chaos.py replay-storm

.PHONY: chaos.split-write
chaos.split-write: env ## [P12-9-E] Kill agent mid multi-step write, assert clean recovery
	@$(XOPS)/chaos.py split-write

.PHONY: chaos.erasure-under-chaos
chaos.erasure-under-chaos: env ## [P12-9-F] GDPR erasure during bus flap, assert idempotent cleanup
	@$(XOPS)/chaos.py erasure-under-chaos

.PHONY: chaos.audit-pii-scan
chaos.audit-pii-scan: env ## [P12-9-G] Scan audit/spool/logs for residual PII after chaos run
	@$(XOPS)/chaos.py audit-pii-scan

.PHONY: verify.integrity-coverage
verify.integrity-coverage: ## [P12-9 gate] Verify every integrity primitive has a proof test
	@$(XOPS)/verify.py integrity-coverage

# ── §12.10 Security Chaos & Abuse ──────────────────────────

.PHONY: chaos.prompt-injection
chaos.prompt-injection: env ## [P12-10-A] Replay prompt-injection corpus through gateway→NLP
	@$(XOPS)/chaos.py prompt-injection

.PHONY: chaos.homoglyph-rtl-flood
chaos.homoglyph-rtl-flood: env ## [P12-10-B] Send confusable-char + RTL + zero-width payloads
	@$(XOPS)/chaos.py homoglyph-rtl-flood

.PHONY: chaos.oversize-zerowidth
chaos.oversize-zerowidth: env ## [P12-10-C] Send oversized + zero-width-padded Turkish queries
	@$(XOPS)/chaos.py oversize-zerowidth

.PHONY: chaos.slur-obfuscation
chaos.slur-obfuscation: env ## [P12-10-D] Replay obfuscated-slur corpus, assert ≥99% detection
	@$(XOPS)/chaos.py slur-obfuscation

.PHONY: chaos.credential-stuffing
chaos.credential-stuffing: env ## [P12-10-D] Burst /v1/auth/*, assert rate caps + latency budgets
	@$(XOPS)/chaos.py credential-stuffing

.PHONY: chaos.xff-spoof
chaos.xff-spoof: env ## [P12-10-E] Spoof X-Forwarded-For, assert trusted-proxy gate
	@$(XOPS)/chaos.py xff-spoof

.PHONY: chaos.redis-fail-open
chaos.redis-fail-open: env ## [P12-10-F] Kill Redis during rate-limit, assert fail-open + secondary buckets
	@$(XOPS)/chaos.py redis-fail-open

.PHONY: chaos.token-replay
chaos.token-replay: env ## [P12-10-G] Replay single-use + revoked tokens, assert rejection
	@$(XOPS)/chaos.py token-replay

.PHONY: chaos.cert-expiry
chaos.cert-expiry: env ## [P12-10-H] Present expired/near-expiry mTLS cert, assert refusal
	@$(XOPS)/chaos.py cert-expiry

.PHONY: chaos.key-rotation-midflight
chaos.key-rotation-midflight: env ## [P12-10-I] Rotate signing key during in-flight requests, assert grace window
	@$(XOPS)/chaos.py key-rotation-midflight

.PHONY: chaos.secret-unreadable
chaos.secret-unreadable: env ## [P12-10-I-alt] Make key path unreadable mid-run, assert fail-safe
	@$(XOPS)/chaos.py secret-unreadable

.PHONY: chaos.tampered-binary
chaos.tampered-binary: env ## [P12-10-J] Swap binary/image to unsigned substitute, assert supply-chain gate
	@$(XOPS)/chaos.py tampered-binary

.PHONY: chaos.cve-injection
chaos.cve-injection: env ## [P12-10-K] Pin known-vulnerable dependency, assert CVE scan blocks
	@$(XOPS)/chaos.py cve-injection

# ── §12.11 Recovery & DR Drills ─────────────────────────────

.PHONY: chaos.restore-drill
chaos.restore-drill: env ## [P12-11-A] Full backup→restore→verify cycle, assert MTTR within budget
	@$(XOPS)/chaos.py restore-drill

.PHONY: chaos.cold-start-under-outage
chaos.cold-start-under-outage: env ## [P12-11-B] Cold boot with DB + Redis denied, assert /livez within budget
	@$(XOPS)/chaos.py cold-start-under-outage

.PHONY: chaos.spool-drain
chaos.spool-drain: env ## [P12-11-C] Bus partition then heal, assert spool drains in order
	@$(XOPS)/chaos.py spool-drain

.PHONY: chaos.leader-handover
chaos.leader-handover: env ## [P12-11-D] Kill leader, assert standby takeover without duplicate
	@$(XOPS)/chaos.py leader-handover

.PHONY: chaos.dr-safe-mode
chaos.dr-safe-mode: env ## [P12-11-E] Fail lexicon load, assert safe-mode + auto-exit
	@$(XOPS)/chaos.py dr-safe-mode

.PHONY: chaos.rolling-deploy
chaos.rolling-deploy: env ## [P12-11-F] Mix v_{N-1} + v_N replicas, assert version tolerance
	@$(XOPS)/chaos.py rolling-deploy

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

.PHONY: test.adversarial
test.adversarial: env ## Phase 12 — Run adversarial corpus tests; zero xfail (§12.2.4)
	@PYTHONPATH=ai python3 -m pytest ai/tests/test_adversarial_corpus.py -q

.PHONY: fuzz.smoke
fuzz.smoke: ## Phase 12 — Replay persisted fuzz corpus (PR lane, deterministic)
	@$(XOPS)/fuzz.py smoke

.PHONY: fuzz.api
fuzz.api: ## Phase 12 — Nightly Go-fuzz coverage run (api gateway + sec; timeout: FUZZ_NIGHTLY_BUDGET_S)
	@$(XOPS)/fuzz.py api

.PHONY: fuzz.nlp
fuzz.nlp: ## Phase 12 — Nightly Atheris/libFuzzer coverage run (NLP; timeout: FUZZ_NIGHTLY_BUDGET_S)
	@$(XOPS)/fuzz.py nlp

.PHONY: fuzz.wire
fuzz.wire: ## Phase 12 — Nightly schema-aware fuzzing (bus envelope, API DTOs via Hypothesis)
	@$(XOPS)/fuzz.py wire

.PHONY: fuzz.corpus.min
fuzz.corpus.min: ## Phase 12 — Minimise + de-duplicate corpus after campaign (feeds growth-bound)
	@$(XOPS)/fuzz.py corpus.min

# ── §12.12 Coverage & Mutation Testing ──────────────────────

.PHONY: coverage.report
coverage.report: ## Phase 12 §12.12 — Line + branch coverage report (HTML + JSON artifact)
	@$(XOPS)/coverage.py report

.PHONY: coverage.diff
coverage.diff: ## Phase 12 §12.12.3 — PR gate: changed lines meet their tier floor
	@$(XOPS)/coverage.py diff

.PHONY: coverage.regression-proof
coverage.regression-proof: ## Phase 12 §12.12.3 — assert regression test fails before fix
	@$(XOPS)/coverage.py regression-proof

.PHONY: coverage.mutation
coverage.mutation: ## Phase 12 §12.12.4 — Nightly mutation testing (Tier-1 only, time-boxed)
	@$(XOPS)/coverage.py mutation

.PHONY: coverage.ratchet
coverage.ratchet: ## Phase 12 §12.12.5 — Coverage ratchet: per-module cannot decline
	@$(XOPS)/coverage.py ratchet

# ── §12.13 CI Lane Dispatchers ──────────────────────────────

.PHONY: ci.fast
ci.fast: ## Phase 12 §12.13 — Fast lane (<5min): unit+property+contract (per-push)
	@$(XOPS)/tests.py ci-fast

.PHONY: ci.pr
ci.pr: ## Phase 12 §12.13 — PR lane (<20min): integration+adversarial+regression+diff-coverage
	@$(XOPS)/tests.py ci-pr

.PHONY: ci.nightly
ci.nightly: ## Phase 12 §12.13 — Nightly lane (<90min, self-hosted): fuzz+load+chaos+mutation
	@$(XOPS)/tests.py ci-nightly

.PHONY: ci.weekly
ci.weekly: ## Phase 12 §12.13 — Weekly lane (24h, self-hosted): full soaks+GPU heat+DR drills
	@$(XOPS)/tests.py ci-weekly

# ── §12.14 Chaos Observability & Ledger ────────────────────

.PHONY: chaos.scorecard
chaos.scorecard: ## Phase 12 §12.14.2 — Render resilience scorecard from ledger (MTTD/MTTR/coverage)
	@$(XOPS)/chaos.py scorecard

.PHONY: chaos.ledger.verify
chaos.ledger.verify: ## Phase 12 §12.14.1 — Schema + PII lint on data/chaos/ledger.jsonl
	@$(XOPS)/chaos.py ledger.verify

.PHONY: chaos.trend
chaos.trend: ## Phase 12 §12.14.2 — Compare current scorecard vs last-green baseline
	@$(XOPS)/chaos.py trend

# ══════════════════════════════════════════════════════════════
#                       PHASE 4 SWARM DEMO
# ══════════════════════════════════════════════════════════════

.PHONY: swarm.demo
swarm.demo: ## Phase 4.8 DoD — end-to-end scrape→categorize→process→store
	@$(XOPS)/swarm.py demo $(if $(LEAGUE),--league $(LEAGUE),)

.PHONY: swarm.demo.nlp
swarm.demo.nlp: ## Phase 10 §10.21.14 — swarm.demo + NLP extension scenarios within 30s budget
	@$(XOPS)/swarm.py demo-nlp $(if $(LEAGUE),--league $(LEAGUE),)

.PHONY: swarm.demo.nlp.full
swarm.demo.nlp.full: ## Phase 10 §10.24 — swarm.demo.nlp full coverage within 60s budget
	@$(XOPS)/swarm.py demo-nlp-full $(if $(LEAGUE),--league $(LEAGUE),)

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

# ── Full-roadmap loop ─────────────────────────────────────────
#  Serial end-to-end CI loop: implement every open phase, review
#  its PR, fix if needed, merge, then continue with the next phase.
#  See .github/prompts/orchestrate.fullroadmap.prompt.md and
#  .github/workflows/orchestrate-full-roadmap.yml.
#
#  Usage (local — dispatches CI, does not implement locally):
#    make orchestrate.fullroadmap
#    make orchestrate.fullroadmap MODEL=gpt-5 EXCLUDE=9.17
#
#  Status / abort:
#    make orchestrate.fullroadmap.status
#    make orchestrate.fullroadmap.drop

.PHONY: orchestrate.fullroadmap
orchestrate.fullroadmap: ## Dispatch the full-project CI loop (EXCLUDE=… MODEL=… MAX_PHASES=…)
	@gh workflow run orchestrate-full-roadmap.yml --ref main \
	    $(if $(MODEL),-f model="$(MODEL)",) \
	    $(if $(EXCLUDE),-f exclude="$(EXCLUDE)",) \
	    $(if $(MAX_PHASES),-f max_phases="$(MAX_PHASES)",)
	@echo "✔ orchestrate-full-roadmap.yml dispatched. Watch via: gh run list --workflow orchestrate-full-roadmap.yml"

.PHONY: orchestrate.fullroadmap.status
orchestrate.fullroadmap.status: ## Show progress of the active full-roadmap session
	@$(XOPS)/orchestrate.py full-roadmap-status

.PHONY: orchestrate.fullroadmap.drop
orchestrate.fullroadmap.drop: ## Abort the active full-roadmap session (prevents next phase dispatch)
	@$(XOPS)/orchestrate.py full-roadmap-drop

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
