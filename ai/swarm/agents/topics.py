"""Phase 4 topic catalog (control plane + low-volume coordination).

Per ROADMAP §3.5: bus topics carry control + coordination, not
high-volume Records. Phase 16 emitter feeds carry the latter. The
topics below are exactly those listed in ROADMAP §4 and §3.5.

Naming: <area>.<verb> (lower-snake). `<topic>.dlq` is reserved.
Adding a new topic requires (a) a new constant here, (b) a JSON
schema in ai/swarm/sdk/schemas/<topic>.json, (c) a doc-row in
ROADMAP §3.5.
"""
from __future__ import annotations

from ..sdk.types import Topic

# Phase 4.1 — scrape lifecycle
SCRAPE_REQUEST = Topic("scrape.request")     # API/scheduler → scrapers
SCRAPE_RAW = Topic("scrape.raw")             # scrapers → categorizer
SCRAPE_CLASSIFIED = Topic("scrape.classified")  # categorizer → processors

# Phase 4.3-4.4 — normalized records lifecycle
MATCH_NORMALIZED = Topic("match.normalized")  # processors → storage
MATCH_STORED = Topic("match.stored")          # storage → cache + reactors

# Phase 5+ — terminal-state outcome stream (storage → drift / proofreader).
# Boundary: storage agent is the SOLE producer. Predictor / consensus
# agents must not publish here (mirrors the freshness.events back-emission
# ban). See ROADMAP §6.3 — drift detector consumes this for Brier.
MATCH_OUTCOME = Topic("match.outcome.v1")

# Phase 4.7 — freshness events (also written to freshness_events table)
FRESHNESS_EVENTS = Topic("freshness.events.v1")

# Phase 6 / proofreader linkage (declared here so processors can flag)
PROOF_FLAG = Topic("proof.flag")

# Phase 4.6 — telemetry sink
TELEMETRY = Topic("telemetry")

# Phase 5 — predictor swarm + consensus topics.
PREDICT_REQUEST = Topic("predict.request")     # API/reactor → predictors
PREDICT_VOTE = Topic("predict.vote")           # predictors → consensus
PREDICT_FINAL = Topic("predict.final")         # consensus → proofreader (CANDIDATE; never user-visible)

# Phase 6 — proofreader aggregator → user-facing surface.
# `predict.final` is a CANDIDATE; `predict.approved.v1` is the post-quorum,
# user-visible decision. The `cache.v1` agent and any API publisher subscribe
# HERE so a prediction cannot reach clients without proofreader approval
# (ROADMAP §736 contract). The proofreader_aggregator agent (Phase 6.1) is
# the SOLE producer.
PREDICT_APPROVED = Topic("predict.approved.v1")

# Phase 6.1 — individual proofreader replica → aggregator. Each replica
# (sanity / consistency / plausibility / cross-source / historical, per
# §6.2) emits exactly one ProofreaderVerdict per (request_id,
# prediction_id). The aggregator collects them inside the quorum window
# (`cfg.proofreader_quorum_window_ms`) and approves when ≥`cfg.proofreader_quorum`
# distinct replicas vote `accept` or `warn`. `reject` votes do not count
# toward quorum. The proofreader_aggregator agent is the SOLE consumer
# of this topic.
PROOFREADER_VERDICT = Topic("predict.proofreader_verdict.v1")

# Phase 5 — model lifecycle (TrainerReactor → ops dashboards/registry)
MODEL_TRAINED = Topic("models.events.v1")

# Phase 6.3 — maintenance event stream (drift agent → trainer / ops).
# Carries kinds like `retrain_request` (drift tripped on a predictor's
# Brier or input KS-test). The trainer subscribes here to schedule a
# retrain; ops dashboards subscribe for the alert. Producer was the
# drift agent in Phase 6; Phase 7.3 expands the producer set to
# include `ops_console` (Phase 8 maint surface) so operators can clear
# denylists, reset upstream fingerprints, etc. via the same envelope.
# Future maintenance agents reuse the same topic with a different
# `kind` (open enum — see `MaintEventKind` in payloads.py).
MAINT_EVENT = Topic("maint.event.v1")

# Phase 8 §8.0 — per-consumer ack of `maint.event.v1` envelopes.
# Producer set: any registered consumer of `maint.event.v1` (boundary
# test enforces). Consumer set: `ops_console` only — agents do not
# read each others' acks. Per ROADMAP §8 §0 ack semantics: every
# consumer that processes a `maint.event.v1{request_id}` publishes
# EXACTLY ONE `maint.ack.v1` carrying its own `accepted_by`. The
# §8.1 ops console waits for the expected ack set computed via
# `swarm.agents.maint.expected_ack_set(kind)`.
MAINT_ACK = Topic("maint.ack.v1")

# Phase 8.4 — source-watcher SDK migration report stream. The watcher
# remains time-driven, but it now publishes its deterministic diff /
# classification result on the bus so downstream agents can observe the
# same plan the legacy scheduler produced.
SOURCE_WATCH_REPORT_V1 = Topic("source.watch.report.v1")

# ── Phase 7 — Defense agents ─────────────────────────────────────
# ROADMAP §7 ships three sec.* agents: an input-sanitization escalator
# (§7.1), an upstream-anomaly detector (§7.2), and a rate-limit /
# burst detector (§7.3). The five topics below are the wire surface;
# the §7.5 catalog gives one row per topic and the §7.6 boundary
# tests pin the producer / consumer sets.

# `qa.request` — control-plane (unversioned by design, ROADMAP §3.7).
# Carries the *raw* user QA payload that the Go gateway could not
# decide deterministically; the `sec.input.v1` agent escalates step 5
# (small classifier) before publishing the sanitized v1 envelope.
# Mutually exclusive with the gateway's direct `qa.request.v1` path:
# the gateway publishes `qa.request.v1` only when its deterministic
# rules return `pass`; on `sanitize` / `escalate` it publishes here
# and `sec.input.v1` owns the v1 emission.
QA_REQUEST = Topic("qa.request")

# `qa.request.v1` — data-plane (versioned). The wire contract the
# Phase 10 NLP layer subscribes to. Two producers (the Go gateway
# and `sec.input.v1`) by construction one-or-the-other per
# `request_id`; consumer-side dedup belongs to the NLP layer.
QA_REQUEST_V1 = Topic("qa.request.v1")

# `sec.alert.v1` — data-plane. Open producer set within `sec.*`; the
# §7.4 envelope carries `kind` (open enum) + `severity`. Telemetry,
# supervisor, ops dashboards consume.
SEC_ALERT = Topic("sec.alert.v1")

# `sec.quarantine.v1` — data-plane. `sec.input.v1` (QA path) and
# `sec.scrape.v1` (scrape path) produce; `storage.v1` is the SOLE
# consumer (persists to `quarantine_samples`). Predictors / NLP /
# proofreader must not subscribe — boundary test enforces.
SEC_QUARANTINE = Topic("sec.quarantine.v1")

# `sec.denylist.v1` — data-plane. `sec.rate.v1` is the SOLE producer.
# API gateway cache + telemetry subscribe so dashboards stay in sync
# without polling Redis.
SEC_DENYLIST = Topic("sec.denylist.v1")

# `sec.config.v1` — control-plane (versioned because the schema is
# stable across the cross-pod sync). ROADMAP §7.1 binding: mtime
# polling does NOT fire on `kubectl rollout` of a ConfigMap-mounted
# file in every CRI runtime, so each `sec.input.v1` (and Go gateway)
# replica subscribes here for an out-of-band wake-up. Producer set:
# any sec.* agent that detects a local mtime delta + the Phase 8
# `ops_console` operator surface. The FILE remains the source of
# truth — the bus event only hints "go re-stat the path now". Both
# the producer and consumer compute the same sha256; a consumer
# whose current ruleset already matches the announced sha256 skips
# the disk re-read (idempotent).
SEC_CONFIG = Topic("sec.config.v1")

# Phase 9 §9.0 — API gateway audit topics.
# The Go process ``api.gateway.v1`` is the SOLE producer for both;
# no Python swarm agent may publish here (boundary test enforces).
#
# `api.request.v1`  — fan-in audit per accepted request (post-auth,
#                     post-sec gate, pre-RPC). Consumers: telemetry.v1,
#                     audit.v1 (Phase 8 §8.13.2 hash-chain mirror) —
#                     open enum so future Phase 19 SLO consumers can
#                     subscribe.
# `api.response.v1` — fan-out audit per sent response (status,
#                     latency_ms, bytes, cache_hit, degraded,
#                     request_id). Same producer/consumer set.
API_REQUEST_V1 = Topic("api.request.v1")
API_RESPONSE_V1 = Topic("api.response.v1")

# Phase 9 §9.5 — cancellation audit topic.
# Emitted by ``api.gateway.v1`` when a prediction request is cancelled
# before a response is written (client disconnect, deadline exceeded, or
# operator kill). Producer set bounded to ``api.gateway.v1``; the
# wire-authority constant is in ``swarm.sdk.wire_contracts``.
# Schema: ``ai/swarm/sdk/schemas/predict.cancel.v1.json``.
PREDICT_CANCEL_V1 = Topic("predict.cancel.v1")

# ── Phase 10 — Turkish NLP layer (§10.0 wire authority) ───────────────
# These six topics are the NLP plane's complete wire surface. The
# boundary test in ``test_boundary_discipline.py`` enforces that no
# NLP agent publishes outside this set and no NLP agent subscribes to
# the forbidden raw/candidate topics (``qa.request``, ``predict.final``).
#
# ``qa.intent.v1``      — sec-sanitized request → structured intent +
#                         entity envelope.  Produced by ``nlp.intent.v1``;
#                         consumed by ``nlp.dispatcher.v1`` (§10.6).
# ``qa.answer.v1``      — Turkish-language answer; produced by
#                         ``nlp.answer.v1`` (or ``nlp.proofreader.v1``
#                         post-block).  Consumer: API gateway response
#                         stream + ``cache.v1`` + ``telemetry.v1``.
# ``nlp.event.v1``      — kind-discriminated control-plane observability
#                         (§8.16.2 doctrine).  Producer set bounded to
#                         three NLP agents; consumer = ``telemetry.v1``
#                         + Phase 8 operator console.
# ``nlp.alert.v1``      — operator-visibility alert channel; mirrors the
#                         §7.4 ``sec.alert.v1`` pattern but scoped to NLP
#                         only so the ``sec.alert.v1`` producer-set stays
#                         bounded to sec.*/maint.*.
# ``predict.request.v1`` — versioned form of ``predict.request``; emitted
#                         by ``nlp.dispatcher.v1`` (§10.6, deferred) to
#                         route fully-resolved match+market intents to the
#                         Phase 5 predictor swarm.  Added here so the
#                         boundary test can reference it in the NLP
#                         outbound allow-set before the dispatcher lands.
# ``data.request.v1``  — emitted by ``nlp.dispatcher.v1`` (§10.6) to
#                         query Phase 4 storage for fixtures/standings.
QA_INTENT_V1 = Topic("qa.intent.v1")
QA_ANSWER_V1 = Topic("qa.answer.v1")
QA_CONTEXT_V1 = Topic("qa.context.v1")
NLP_EVENT_V1 = Topic("nlp.event.v1")
NLP_ALERT_V1 = Topic("nlp.alert.v1")
PREDICT_REQUEST_V1 = Topic("predict.request.v1")
DATA_REQUEST_V1 = Topic("data.request.v1")


__all__ = [
    "API_REQUEST_V1",
    "API_RESPONSE_V1",
    "DATA_REQUEST_V1",
    "NLP_ALERT_V1",
    "NLP_EVENT_V1",
    "PREDICT_CANCEL_V1",
    "PREDICT_REQUEST_V1",
    "QA_ANSWER_V1",
    "QA_CONTEXT_V1",
    "QA_INTENT_V1",
    "FRESHNESS_EVENTS",
    "MAINT_ACK",
    "MAINT_EVENT",
    "MATCH_NORMALIZED",
    "MATCH_OUTCOME",
    "MATCH_STORED",
    "MODEL_TRAINED",
    "PREDICT_APPROVED",
    "PREDICT_FINAL",
    "PREDICT_REQUEST",
    "PREDICT_VOTE",
    "PROOFREADER_VERDICT",
    "PROOF_FLAG",
    "QA_REQUEST",
    "QA_REQUEST_V1",
    "SCRAPE_CLASSIFIED",
    "SCRAPE_RAW",
    "SCRAPE_REQUEST",
    "SEC_ALERT",
    "SEC_CONFIG",
    "SEC_DENYLIST",
    "SEC_QUARANTINE",
    "SOURCE_WATCH_REPORT_V1",
    "TELEMETRY",
]
