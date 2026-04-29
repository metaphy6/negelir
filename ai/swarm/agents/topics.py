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
PREDICT_FINAL = Topic("predict.final")         # consensus → cache/proofreader

# Phase 5 — model lifecycle (TrainerReactor → ops dashboards/registry)
MODEL_TRAINED = Topic("models.events.v1")


__all__ = [
    "FRESHNESS_EVENTS",
    "MATCH_NORMALIZED",
    "MATCH_OUTCOME",
    "MATCH_STORED",
    "MODEL_TRAINED",
    "PREDICT_FINAL",
    "PREDICT_REQUEST",
    "PREDICT_VOTE",
    "PROOF_FLAG",
    "SCRAPE_CLASSIFIED",
    "SCRAPE_RAW",
    "SCRAPE_REQUEST",
    "TELEMETRY",
]
