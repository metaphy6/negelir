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


__all__ = [
    "FRESHNESS_EVENTS",
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
    "SEC_DENYLIST",
    "SEC_QUARANTINE",
    "TELEMETRY",
]
