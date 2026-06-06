"""Phase 10 §10.0 — NLP plane agent stubs (boundary-discipline skeletons).

Three agents land here per ROADMAP §10.0 wire-authority:

* ``nlp.intent.v1``    — subscribes ``qa.request.v1`` (sanitized
                         data-plane, NEVER the raw ``qa.request``
                         control-plane); normalizes, classifies intent,
                         extracts entities; publishes ``qa.intent.v1``
                         (consumed by the future nlp.dispatcher.v1,
                         §10.6) + ``nlp.event.v1`` / ``nlp.alert.v1``
                         for observability.

* ``nlp.answer.v1``    — subscribes ``qa.intent.v1`` (structured intent
                         envelope) and ``predict.approved.v1`` (Phase 6
                         gated; NEVER ``predict.final`` — that is the
                         unvetted candidate); assembles the Turkish-
                         language answer from templates (§10.7);
                         publishes ``qa.answer.v1`` +
                         ``nlp.event.v1`` / ``nlp.alert.v1``.

* ``nlp.proofreader.v1`` — subscribes ``qa.answer.v1`` (pre-clean
                           answer); performs PII detection + redaction
                           (§10.9); republishes to ``qa.answer.v1``
                           (clean path) + ``nlp.event.v1`` /
                           ``nlp.alert.v1``.
* ``nlp.dispatcher.v1`` — subscribes ``qa.intent.v1`` and ``qa.feedback.v1``;
                           resolves intents into ``predict.request.v1`` /
                           ``data.request.v1`` or directly emits ``qa.answer.v1``
                           for meta-only queries; emits ``qa.context.v1`` for
                           conversation state and `nlp.event.v1` / ``nlp.alert.v1``
                           for routing observability.
* ``nlp.prober.v1`` — synthetic probe agent that publishes addendum
                      audit on a fixed cadence; its outbound topic is
                      ``nlp.prober.v1``.

These skeletons carry the correct ``name``, ``subscribes``, and
``publishes`` class attributes so the Phase 10 boundary tests in
``test_boundary_discipline.py`` can import them and assert the wire
contract via registry walk.  Full handler logic lands per-bullet in
§10.1–§10.20; until then every ``handle()`` is a no-op that returns
an empty iterable.

Boundary invariants (all asserted by Rule 11 in
``test_boundary_discipline.py``):

* NLP NEVER subscribes to raw ``qa.request`` (control-plane).  Only
  ``qa.request.v1`` (sanitized data-plane).  Mirrors §7.5 doctrine.
* NLP NEVER subscribes to ``predict.final`` (Phase 5 candidate).
  Only ``predict.approved.v1`` (Phase 6 gated).
* NLP NEVER publishes to ``sec.*``, ``maint.*``, ``auth.*``,
  ``payment.*``, ``patcher.*``.  Outbound set is exactly
  ``{qa.intent.v1, qa.answer.v1, qa.context.v1, qa.context_extension.v1,
    nlp.event.v1, nlp.alert.v1, nlp.gossip.v1, nlp.shadow.v1,
    nlp.prober.v1, predict.request.v1, data.request.v1}``.
* NLP NEVER writes to Postgres directly.
"""
from __future__ import annotations

import datetime as _dt
import functools
import hashlib as _hashlib
import hmac as _hmac
import json
import locale
import logging
import math
import re
import threading as _threading
import time as _time
import unicodedata
from collections import Counter, deque
from typing import Any, Callable, Iterable
import os
from pathlib import Path
import stat
from uuid import uuid4

from common.config import cfg
from common.fixture_state import FixtureState
from common.security.patterns import PII_PATTERNS
from common.security.tr_pii import parse_redacted_tr_pii, redact_tr_pii
from common.telemetry import NLP_CLASSIFIER_EXTRACTOR_SKEW

from ...sdk import AlertDebouncer
from ...sdk.types import Message
from nlp.compliance import disclosures_snapshot_sha, load_disclosures
from nlp.lexicon_loader import is_safe_mode_active
from nlp.normalize import assert_minimum_signal, detect_all_caps
from nlp.proofreader import _prepend_confirmation_seeking_intro
from ..topics import (
    DATA_REQUEST_V1,
    MAINT_EVENT,
    NLP_ALERT_V1,
    NLP_EVENT_V1,
    NLP_GOSSIP_V1,
    NLP_PROBER_V1,
    NLP_SHADOW_V1,
    PREDICT_APPROVED,
    PREDICT_CANCEL_V1,
    PREDICT_REQUEST_V1,
    QA_ANSWER_V1,
    QA_CONTEXT_EXTENSION_V1,
    QA_CONTEXT_V1,
    QA_FEEDBACK_V1,
    QA_INTENT_V1,
    QA_REQUEST_V1,
)
from ._bus_circuit_breaker import NlpBusCircuitBreaker
from .abuse import NlpAbuseAgent
from .shadow_writer import NlpShadowWriter
from nlp.compat import _lexicon_snapshot_sha, validate_compatibility_matrix
from nlp.conversation import ConversationStore
from ._log_filter import PIIScrubFilter, add_log_filter
from nlp.aspectual_stack import detect_aspectual_stack
from nlp.phase10_30 import (
    classify_conversational_meta,
    detect_anaphora_pronouns,
    detect_coordinating_particles,
    detect_conditional_modifier,
    is_legal_anaphora_composition,
    load_pro_drop_intent_classes,
    resolve_anaphora_pronoun,
)
from nlp.quotative import detect_quotative_frame
from nlp.render import _resolve_locale_tag, build_environment, render

# ── internal helpers ──────────────────────────────────────────────────────

# Entity kinds that can anchor a predict.* intent to a specific fixture.
_FIXTURE_ENTITY_KINDS = frozenset({"team", "competition"})

# Number of gossip rounds to remember per pod for persistent divergence detection.
_NLP_GOSSIP_WINDOW_ROUNDS = 12
_PRO_DROP_SUBJECT_KINDS_BY_INTENT = {
    "predict.match_outcome": frozenset({"team", "player"}),
    "predict.over_under": frozenset({"team", "player"}),
    "predict.btts": frozenset({"team", "player"}),
    "predict.handicap": frozenset({"team", "player"}),
    "predict.score_grid": frozenset({"team", "player"}),
    "data.lineup_probable": frozenset({"team"}),
    "data.lineup_official": frozenset({"team"}),
    "data.score_current": frozenset({"fixture"}),
}

_INTENT_REQUIRED_ENTITY_MAP_PATH = Path(__file__).resolve().parents[3] / "nlp" / "intent_required_entities.tr.yaml"

_VENUE_TABLE_PATH = Path(__file__).resolve().parents[3] / "nlp" / "lang_tr" / "venues.tr.yaml"

@functools.lru_cache(maxsize=1)
def _load_venue_home_team_map() -> dict[str, str]:
    try:
        import yaml

        raw = yaml.safe_load(_VENUE_TABLE_PATH.read_text(encoding="utf-8")) or {}
    except (OSError, TypeError, yaml.YAMLError):
        return {}
    entries = raw.get("entries")
    if not isinstance(entries, list):
        return {}
    result: dict[str, str] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        venue_id = str(entry.get("canonical_slug", "")).strip()
        home_team = str(entry.get("home_team", "")).strip()
        if venue_id and home_team:
            result[venue_id] = home_team
    return result


@functools.lru_cache(maxsize=1)
def _load_pro_drop_intent_classes() -> dict[str, str]:
    return load_pro_drop_intent_classes()


def _get_pro_drop_subject_kinds(intent: str) -> frozenset[str] | None:
    return _PRO_DROP_SUBJECT_KINDS_BY_INTENT.get(intent)


def _favorite_team_from_request_metadata(payload: dict[str, object]) -> str | None:
    request_metadata = payload.get("request_metadata")
    if not isinstance(request_metadata, dict):
        return None
    user_preferences = request_metadata.get("user_preferences")
    if not isinstance(user_preferences, dict):
        return None
    favorite_team = user_preferences.get("favorite_team")
    if not isinstance(favorite_team, str) or not favorite_team.strip():
        return None
    return favorite_team.strip()


def _make_pro_drop_resolved_event(
    request_id: str,
    source: str,
    resolved_entity_id: str | None,
) -> Message:
    payload = {
        "kind": "pro_drop_resolved",
        "producer": "nlp.dispatcher.v1",
        "request_id": request_id or None,
        "source": source,
        "resolved_entity_id": resolved_entity_id,
        "emitted_at": _utc_iso(),
    }
    return Message.new(topic=NLP_EVENT_V1, payload=payload, producer="nlp.dispatcher.v1")


def _make_pro_drop_disambiguation(
    request_id: str,
    conversation_id: str | None,
) -> Message:
    qa_correlation_id = _new_id()
    payload = _make_qa_answer_payload(
        request_id=request_id,
        qa_correlation_id=qa_correlation_id,
        intent="predict.match_outcome",
        kind="disambiguation",
        answer_text="Hangi takımı/oyuncuyu kastettiğinizi belirtir misiniz?",
        tier_id_required=None,
        conversation_id=conversation_id,
        emitted_at_utc=_utc_iso(),
        schema_version=2,
    )
    return Message.new(topic=QA_ANSWER_V1, payload=payload, producer="nlp.dispatcher.v1")

def _pro_drop_anaphora_candidate(
    required_kinds: frozenset[str],
    previous_anaphora_mentions: list[dict[str, object]],
    current_turn_index: int,
) -> dict[str, object] | None:
    candidate: dict[str, object] | None = None
    best_score = 0.0
    lookback_turns = int(cfg.nlp_pro_drop_lookback_turns)
    min_confidence = float(cfg.nlp_pro_drop_min_implicit_subject_confidence)
    for mention in previous_anaphora_mentions:
        kind = mention.get("kind")
        canonical_id = mention.get("canonical_id")
        confidence = mention.get("confidence")
        mentioned_turn = mention.get("mentioned_turn")
        if not isinstance(kind, str) or kind not in required_kinds:
            continue
        if not isinstance(canonical_id, str) or not canonical_id:
            continue
        if not isinstance(confidence, (int, float)):
            continue
        if not isinstance(mentioned_turn, int):
            continue
        age_turns = current_turn_index - mentioned_turn
        if age_turns <= 0 or age_turns >= lookback_turns:
            continue
        decay = max(0.0, 1.0 - (age_turns / float(lookback_turns)))
        weighted_confidence = max(0.0, float(confidence) * decay)
        if weighted_confidence < min_confidence:
            continue
        if weighted_confidence > best_score:
            candidate = {
                "kind": kind,
                "canonical_id": canonical_id,
                "confidence": weighted_confidence,
                "name": mention.get("name") or canonical_id,
            }
            best_score = weighted_confidence
    return candidate


def _maybe_make_pro_drop_resolution(
    request_id: str,
    qa_corr_in: str,
    intent: str,
    entities: list[dict[str, object]],
    payload: dict[str, object],
    previous_anaphora_mentions: list[dict[str, object]],
    conversation_id: str | None,
    turn_index: int,
) -> tuple[Message | None, dict[str, object] | None, Message | None]:
    strategy = _load_pro_drop_intent_classes().get(intent)
    if strategy is None:
        return None, None, None
    required_kinds = _get_pro_drop_subject_kinds(intent)
    if not required_kinds:
        return None, None, None
    if any(
        isinstance(entity.get("kind"), str)
        and entity.get("kind") in required_kinds
        and isinstance(entity.get("canonical_id"), str)
        and entity.get("canonical_id")
        for entity in entities
    ):
        return None, None, None

    candidate = _pro_drop_anaphora_candidate(
        required_kinds=required_kinds,
        previous_anaphora_mentions=previous_anaphora_mentions,
        current_turn_index=turn_index,
    )
    if candidate is not None:
        event = _make_pro_drop_resolved_event(
            request_id=request_id,
            source="anaphora",
            resolved_entity_id=str(candidate["canonical_id"]),
        )
        return event, candidate, None

    if strategy == "cross_turn_anaphora_then_default_team":
        favorite_team = _favorite_team_from_request_metadata(payload)
        if favorite_team is not None:
            confidence = min(
                float(cfg.nlp_pro_drop_default_team_confidence_cap),
                0.55,
            )
            event = _make_pro_drop_resolved_event(
                request_id=request_id,
                source="default_team",
                resolved_entity_id=favorite_team,
            )
            return event, {
                "kind": "team",
                "canonical_id": favorite_team,
                "confidence": confidence,
                "source": "pro_drop",
            }, None

    return None, None, None

@functools.lru_cache(maxsize=1)
def _load_team_name_to_canonical_id_map() -> dict[str, str]:
    from nlp.lexicon_loader import LexiconStore

    store = LexiconStore.from_cfg(cfg, reload_s=9999, max_rss_mb=0)
    store.maybe_reload()
    entries = store.get("teams.tr.yaml")
    if entries is None:
        entries = store.get("teams.tr-TR.yaml")
    if entries is None:
        return {}
    _, rows = entries
    mapping: dict[str, str] = {}
    for entry in rows:
        if not isinstance(entry, dict):
            continue
        canonical_id = str(entry.get("canonical_id", "")).strip()
        if not canonical_id:
            continue
        mapping[canonical_id.lower()] = canonical_id
        for field in ("names", "aliases"):
            raw_values = entry.get(field)
            if not isinstance(raw_values, list):
                continue
            for alias in raw_values:
                if isinstance(alias, str) and alias.strip():
                    mapping[alias.strip().lower()] = canonical_id
    return mapping


def _load_intent_required_entity_map() -> dict[str, list[dict[str, int]]]:
    try:
        import yaml

        raw = yaml.safe_load(_INTENT_REQUIRED_ENTITY_MAP_PATH.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}
    intents_raw = raw.get("intents")
    if not isinstance(intents_raw, dict):
        return {}
    result: dict[str, list[dict[str, int]]] = {}
    for intent, entries in intents_raw.items():
        if not isinstance(intent, str):
            continue
        if not isinstance(entries, list):
            continue
        parsed: list[dict[str, int]] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            kind = str(entry.get("kind", "")).strip()
            if not kind:
                continue
            count = 1
            if isinstance(entry.get("count"), (int, float)):
                count = int(entry.get("count"))
            elif isinstance(entry.get("count"), str) and entry.get("count").isdigit():
                count = int(entry.get("count"))
            parsed.append({"kind": kind, "count": max(1, count)})
        if parsed:
            result[intent] = parsed
    return result


def _resolve_team_canonical_id_from_venue_slug(venue_slug: str) -> str | None:
    venue_home_team = _load_venue_home_team_map().get(venue_slug)
    names = _load_team_name_to_canonical_id_map()
    if venue_home_team:
        canonical_id = names.get(venue_home_team.strip().lower())
        if canonical_id:
            return canonical_id
    slug = venue_slug.strip().lower()
    if slug:
        for cid in names.values():
            if cid.lower().startswith(slug):
                return cid
    return None

# Summary intents that fan-out to multiple predict.request.v1 messages.
_SUMMARY_INTENTS = frozenset({"summary.next_week", "summary.matchday"})
_SUMMARY_TOP_N_BY = "öncelik (lig sıralaması, derbi, saat)"
_QA_ANSWER_SCHEMA_VERSION_REQUEST_KEY = "qa_answer_schema_version"

@functools.lru_cache(maxsize=1)
def _load_degraded_reason_translations() -> dict[str, str]:
    try:
        import yaml

        path = Path(__file__).resolve().parents[3] / "nlp" / "lang_tr" / "degraded_reasons.tr.yaml"
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        if not isinstance(data, dict):
            return {}
        return {str(k): str(v) for k, v in data.items()}
    except Exception:
        return {}


@functools.lru_cache(maxsize=1)
def _load_fixture_state_routing() -> dict[str, dict[str, str]]:
    try:
        import yaml

        path = Path(__file__).resolve().parents[3] / "nlp" / "dispatch" / "fixture_state_routing.yaml"
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        routing = data.get("routing")
        if not isinstance(routing, dict):
            return {}
        result: dict[str, dict[str, str]] = {}
        for state, config in routing.items():
            if not isinstance(config, dict):
                continue
            result[state] = {
                str(key): str(value)
                for key, value in config.items()
                if isinstance(key, str) and isinstance(value, str)
            }
        return result
    except Exception:
        return {}


def _fixture_state_refusal_meta(state: str) -> tuple[str, str, bool, str | None]:
    if state in {FixtureState.POSTPONED.value, FixtureState.SUSPENDED.value}:
        return (
            "meta.fixture_postponed",
            "Maç ertelendi veya askıya alındı; güncellenmiş bilgileri kontrol ediyorum.",
            False,
            None,
        )
    if state == FixtureState.ABANDONED.value:
        return (
            "meta.fixture_abandoned",
            "Maç terk edildi; mevcut duruma göre tahmin sunmuyorum.",
            False,
            None,
        )
    if state in {FixtureState.CANCELLED.value, FixtureState.AWARDED.value}:
        return (
            "meta.fixture_cancelled",
            "Maç iptal edildi veya ödüllendirildi; tahmin sunmuyorum.",
            False,
            None,
        )
    if state == FixtureState.UNKNOWN.value:
        return (
            "meta.fixture_state_unknown",
            "Maç durumu bilinmiyor; canlı bilgi bekleniyor.",
            True,
            "fixture_state_unknown",
        )
    return (
        "meta.live_match_unsupported",
        "Maç şu an oynanıyor; canlı tahmin sunmuyorum, mevcut skoru paylaşırım.",
        False,
        None,
    )


def _fixture_state_class(state: str) -> str | None:
    if state in {
        FixtureState.SCHEDULED.value,
        FixtureState.PREMATCH_LOCKED.value,
    }:
        return "pre_match"
    if state in {
        FixtureState.IN_PLAY_FIRST_HALF.value,
        FixtureState.HALFTIME.value,
        FixtureState.IN_PLAY_SECOND_HALF.value,
        FixtureState.IN_PLAY_EXTRA_TIME.value,
        FixtureState.PENALTY_SHOOTOUT.value,
    }:
        return "live"
    if state in {
        FixtureState.FINISHED.value,
        FixtureState.ABANDONED.value,
        FixtureState.AWARDED.value,
    }:
        return "post_match"
    if state in {
        FixtureState.POSTPONED.value,
        FixtureState.SUSPENDED.value,
    }:
        return "postponed"
    if state == FixtureState.CANCELLED.value:
        return "cancelled"
    return None


def _parse_iso_datetime(value: object) -> _dt.datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return _dt.datetime.fromisoformat(value)
    except ValueError:
        return None


def _entity_state_stale(entity: dict[str, object]) -> bool:
    state_class = entity.get("state_class")
    if not isinstance(state_class, str):
        return False
    threshold_key = {
        "pre_match": "nlp_entity_pre_match_max_stale_s",
        "live": "nlp_entity_live_max_stale_s",
        "post_match": "nlp_entity_post_match_max_stale_s",
    }.get(state_class)
    if threshold_key is None:
        return False
    last_resolved_at = _parse_iso_datetime(entity.get("last_resolved_state_at"))
    if last_resolved_at is None:
        return True
    from common.config import cfg as _cfg

    threshold_s = int(getattr(_cfg, threshold_key, 0))
    if threshold_s <= 0:
        return False
    now_dt = _dt.datetime.now(_dt.timezone.utc)
    return (now_dt - last_resolved_at).total_seconds() > float(threshold_s)


@functools.lru_cache(maxsize=1)
def _load_correction_markers() -> dict[str, list[str]]:
    try:
        import yaml

        path = Path(__file__).resolve().parents[3] / "nlp" / "lang_tr" / "correction" / "correction_markers.tr.yaml"
        if not path.exists():
            return {}
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        if not isinstance(data, dict):
            return {}
        result: dict[str, list[str]] = {}
        for kind, markers in data.items():
            if not isinstance(markers, list):
                continue
            normalized_markers = [str(marker).strip().lower() for marker in markers if isinstance(marker, str) and str(marker).strip()]
            if normalized_markers:
                result[kind] = normalized_markers
        return result
    except Exception:
        return {}


def _conversation_entity_summary(entity: dict[str, object]) -> str:
    kind = str(entity.get("kind", "unknown")).strip() or "unknown"
    canonical_id = entity.get("canonical_id")
    if isinstance(canonical_id, str) and canonical_id:
        return f"{kind}:{canonical_id}"
    return kind


def _append_conversation_history_entry(
    history_metadata: dict[str, object],
    intent: str,
    entities: list[dict[str, object]],
    turn_index: int,
) -> dict[str, object]:
    safe_entities = [
        _conversation_entity_summary(entity)
        for entity in entities
        if isinstance(entity, dict)
    ]
    entry: dict[str, object] = {
        "turn_index": turn_index,
        "intent": intent,
        "entities": [entity for entity in safe_entities if entity],
    }

    conversation_history = history_metadata.get("conversation_history")
    if not isinstance(conversation_history, list):
        conversation_history = []
    else:
        conversation_history = [item for item in conversation_history if isinstance(item, dict)]

    conversation_history.append(entry)
    history_metadata["conversation_history"] = conversation_history[-8:]
    return history_metadata


def _normalize_correction_text(text: str) -> str:
    return unicodedata.normalize("NFC", str(text or "")).strip().lower()


def _entity_sha8(entity: dict[str, object]) -> str:
    canonical_id = str(entity.get("canonical_id") or "")
    kind = str(entity.get("kind") or "")
    token = f"{kind}|{canonical_id}"
    return _hashlib.sha256(token.encode("utf-8")).hexdigest()[:8]


def _canonical_answer_body(payload: dict[str, object]) -> str:
    body = ""
    parts = payload.get("parts")
    if isinstance(parts, list) and parts:
        first = parts[0]
        if isinstance(first, dict) and isinstance(first.get("body"), str):
            body = first["body"]
    if not body:
        body = str(payload.get("answer_text") or "")
    body = unicodedata.normalize("NFC", body)
    body = re.sub(r"\s+", " ", body).strip()
    return body


def _canonical_citations(payload: dict[str, object]) -> str:
    citations = payload.get("citations")
    if not isinstance(citations, list):
        return ""
    try:
        return json.dumps(citations, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    except Exception:
        return ""


def _compatibility_quartet_sha(payload: dict[str, object]) -> str:
    quartet = "|".join([
        str(payload.get("schema_version") or ""),
        str(payload.get("answer_format") or ""),
        str(payload.get("proofreader_status") or ""),
        str(payload.get("nlp_pipeline_version") or ""),
    ])
    return _hashlib.sha256(quartet.encode("utf-8")).hexdigest()[:16]


def _compute_qa_answer_envelope_signature(payload: dict[str, object], key: bytes) -> str:
    qa_correlation_id = str(payload.get("qa_correlation_id") or "")
    produced_at = str(payload.get("emitted_at_utc") or "")
    body_canonical = _canonical_answer_body(payload)
    citation_canonical = _canonical_citations(payload)
    degraded = "1" if payload.get("degraded") else "0"
    degraded_reason = str(payload.get("degraded_reason") or "")
    tier_id_required = str(payload.get("tier_id_required") or "")
    pipeline_version = str(payload.get("nlp_pipeline_version") or "")
    compatibility_quartet = _compatibility_quartet_sha(payload)
    blob = "|".join([
        qa_correlation_id,
        produced_at,
        body_canonical,
        citation_canonical,
        degraded,
        degraded_reason,
        tier_id_required,
        pipeline_version,
        compatibility_quartet,
    ]).encode("utf-8")
    return _hmac.new(key, blob, _hashlib.sha256).hexdigest()


def _load_qa_answer_hmac_keys() -> dict[str, bytes]:
    from common.config import cfg as _cfg

    loaded: dict[str, bytes] = {}
    key_path = str(getattr(_cfg, "qa_answer_hmac_key_path", "") or "").strip()
    grace_s = int(getattr(_cfg, "qa_answer_hmac_grace_s", 86_400) or 0)
    if key_path:
        path = Path(key_path).expanduser()
        try:
            key = path.read_bytes().strip()
            if key:
                loaded[_hashlib.sha256(key).hexdigest()[:16]] = key
            if grace_s > 0:
                prev_path = Path(f"{path}.prev")
                if prev_path.exists():
                    prev_key = prev_path.read_bytes().strip()
                    if prev_key:
                        loaded[_hashlib.sha256(prev_key).hexdigest()[:16]] = prev_key
        except OSError:
            pass

    if str(getattr(_cfg, "profile", "mock")).lower() == "mock":
        mock_key = b"negelir:mock:qa:answer:hmac:v1"
        loaded[_hashlib.sha256(mock_key).hexdigest()[:16]] = mock_key
    return loaded


def _envelope_signature_key_id(key: bytes) -> str:
    return _hashlib.sha256(key).hexdigest()[:16]


def _make_unverified_qa_answer_alert(
    request_id: str,
    qa_correlation_id: str | None,
    conversation_id: str | None,
    reason: str,
) -> Message:
    return Message.new(
        topic=NLP_ALERT_V1,
        payload={
            "schema_version": 1,
            "alert_id": uuid4().hex,
            "kind": "qa_answer_envelope_signature_missing",
            "severity": "warn",
            "source": "nlp.proofreader.v1",
            "reason": reason,
            "request_id": request_id or None,
            "qa_correlation_id": qa_correlation_id,
            "conversation_id": conversation_id,
            "emitted_at": _utc_iso(),
        },
        producer="nlp.proofreader.v1",
    )


def _make_conversation_correction_applied_event(
    request_id: str,
    conversation_id: str,
    correction_kind: str,
    prior_entity_sha8: str,
    new_entity_sha8: str,
) -> Message:
    return Message.new(
        topic=NLP_EVENT_V1,
        payload={
            "kind": "conversation_correction_applied",
            "producer": "nlp.dispatcher.v1",
            "request_id": request_id or None,
            "conversation_id": conversation_id,
            "correction_kind": correction_kind,
            "prior_entity_sha8": prior_entity_sha8,
            "new_entity_sha8": new_entity_sha8,
            "emitted_at": _utc_iso(),
        },
        producer="nlp.dispatcher.v1",
    )


def _make_conversation_restarted_by_user_event(
    request_id: str,
    conversation_id: str,
) -> Message:
    return Message.new(
        topic=NLP_EVENT_V1,
        payload={
            "kind": "conversation_restarted_by_user",
            "producer": "nlp.dispatcher.v1",
            "request_id": request_id or None,
            "conversation_id": conversation_id,
            "emitted_at": _utc_iso(),
        },
        producer="nlp.dispatcher.v1",
    )


def _detect_conversation_correction(
    normalized_text: str,
    current_entities: list[dict[str, object]],
    previous_entities: list[dict[str, object]],
) -> str:
    markers = _load_correction_markers()
    if not previous_entities or not normalized_text:
        return ""

    if current_entities and any(marker in normalized_text for marker in markers.get("replacement", [])):
        return "replacement"

    for marker in markers.get("restart", []):
        if normalized_text.startswith(marker):
            return "restart"

    for marker in markers.get("negation_of_prior", []):
        if normalized_text.startswith(marker):
            return "negation_of_prior"

    if any(phrase in normalized_text for phrase in markers.get("replacement", [])) and current_entities:
        return "replacement"

    return ""


def _normalize_subject_key(payload: dict[str, object]) -> str:
    candidate = payload.get("subject_key_sha8") or payload.get("subject_key_sha8_prefix_2")
    if isinstance(candidate, str) and candidate.strip():
        return candidate.strip()
    return "unknown"


def _record_empty_input_rate(subject: str, is_empty: bool) -> None:
    try:
        from common.telemetry import get_sink
    except ImportError:
        return
    sink = get_sink()
    try:
        sink.record_nlp_empty_input_rate(subject, is_empty)
    except Exception:
        pass


def _make_empty_input_anomaly_event(
    request_id: str,
    qa_correlation_id: str | None,
    subject: str,
    rate: float,
    total_requests: int,
    empty_requests: int,
    window_s: int,
) -> Message:
    payload: dict[str, object] = {
        "schema_version": 1,
        "alert_id": uuid4().hex,
        "kind": "nlp_empty_input_anomaly_per_subject",
        "severity": "warn",
        "source": "nlp.intent.v1",
        "subject": subject,
        "request_id": request_id or None,
        "qa_correlation_id": qa_correlation_id,
        "details": {
            "rate": round(rate, 3),
            "total_requests": total_requests,
            "empty_requests": empty_requests,
            "window_s": window_s,
        },
        "emitted_at": _utc_iso(),
    }
    return Message.new(
        topic=NLP_ALERT_V1,
        payload=payload,
        producer="nlp.intent.v1",
    )


def _make_nlp_shout_rate_anomaly_event(
    request_id: str,
    qa_correlation_id: str | None,
    subject: str,
    rate: float,
    total_requests: int,
    shout_requests: int,
    window_s: int,
) -> Message:
    payload: dict[str, object] = {
        "schema_version": 1,
        "alert_id": uuid4().hex,
        "kind": "nlp_shout_rate_anomaly_per_subject",
        "severity": "warn",
        "source": "nlp.intent.v1",
        "subject": subject,
        "request_id": request_id or None,
        "qa_correlation_id": qa_correlation_id,
        "details": {
            "rate": round(rate, 3),
            "total_requests": total_requests,
            "shout_requests": shout_requests,
            "window_s": window_s,
        },
        "emitted_at": _utc_iso(),
    }
    return Message.new(
        topic=NLP_ALERT_V1,
        payload=payload,
        producer="nlp.intent.v1",
    )


def _record_empty_input_rate(subject: str, rate: float) -> None:
    try:
        from common.telemetry import get_sink
    except ImportError:
        return
    sink = get_sink()
    try:
        sink.record_nlp_empty_input_rate(subject, rate)
    except Exception:
        pass


def _record_shout_rate(subject: str, is_shout: bool) -> tuple[bool, dict[str, object]]:
    if not is_shout:
        return False, {}
    try:
        from common.telemetry import get_sink
    except ImportError:
        return False, {}
    sink = get_sink()
    try:
        return sink.record_nlp_input_shout(subject, is_shout)
    except Exception:
        return False, {}


def _make_qa_answer_payload(
    request_id: str,
    qa_correlation_id: str,
    intent: str,
    kind: str,
    answer_text: str,
    *,
    answer_format: str = "plain",
    degraded: bool = False,
    degraded_reason: str | None = None,
    tier_id_required: str | None = None,
    citations: list[dict[str, object]] | None = None,
    humanizer_used: bool = False,
    proofreader_status: str = "pass",
    parts: list[dict[str, object]] | None = None,
    schema_version: int = 3,
    truncated_count: int | None = None,
    top_n_by: str | None = None,
    conversation_id: str | None = None,
    emitted_at_utc: str | None = None,
    nlp_pipeline_version: str | None = None,
    query_time_bucket: str | None = None,
    feature_set_hash: str | None = None,
    disclosures: list[dict[str, object]] | None = None,
    request_metadata: dict[str, object] | None = None,
) -> dict[str, object]:
    if emitted_at_utc is None:
        emitted_at_utc = _utc_iso()
    if nlp_pipeline_version is None:
        nlp_pipeline_version = str(cfg.nlp_pipeline_version)

    payload: dict[str, object] = {
        "request_id": request_id,
        "qa_correlation_id": qa_correlation_id,
        "schema_version": schema_version,
        "locale": "tr-TR",
        "intent": intent,
        "kind": kind,
        "answer_text": answer_text,
        "answer_format": answer_format,
        "degraded": degraded,
        "degraded_reason": degraded_reason,
        "humanizer_used": humanizer_used,
        "proofreader_status": proofreader_status,
        "tier_id_required": tier_id_required,
        "citations": citations if citations is not None else [],
        "emitted_at": emitted_at_utc,
        "emitted_at_utc": emitted_at_utc,
        "nlp_pipeline_version": nlp_pipeline_version,
    }
    if conversation_id:
        payload["conversation_id"] = conversation_id
    if schema_version >= 2:
        if not parts:
            parts = [
                _make_default_qa_answer_part(
                    intent=intent,
                    body=answer_text,
                    citations=citations,
                    qa_correlation_id=qa_correlation_id,
                    emitted_at_utc=emitted_at_utc,
                )
            ]
        payload["parts"] = parts
    if truncated_count is not None:
        payload["truncated_count"] = truncated_count
    if top_n_by is not None:
        payload["top_n_by"] = top_n_by
    elif parts is not None:
        payload["parts"] = parts
    if disclosures is not None:
        payload["disclosures"] = disclosures
    if request_metadata is not None:
        payload["request_metadata"] = request_metadata
    if query_time_bucket is not None:
        payload["query_time_bucket"] = query_time_bucket
    if feature_set_hash is not None:
        payload["feature_set_hash"] = feature_set_hash

    if schema_version >= 3:
        canonical_body = _canonical_answer_body(payload)
        payload["body_canonical_sha"] = _hashlib.sha256(canonical_body.encode("utf-8")).hexdigest()
        keys = _load_qa_answer_hmac_keys()
        if keys:
            key_id, key = next(iter(keys.items()))
            payload["envelope_signature_key_id"] = key_id
            payload["envelope_signature"] = _compute_qa_answer_envelope_signature(payload, key)
        elif cfg.nlp_answer_envelope_hmac_required == "enforce":
            raise RuntimeError(
                "QA answer envelope HMAC is required but no HMAC key could be loaded"
            )

    return _maybe_downgrade_qa_answer_payload(payload, request_metadata)


def _translate_degraded_reason_tr(reason: str) -> str:
    translations = _load_degraded_reason_translations()
    if reason not in translations:
        raise KeyError(f"Missing degraded_reason translation for {reason!r}")
    return translations[reason]


def _parse_rfc3339_utc(value: str) -> _dt.datetime | None:
    try:
        parsed = _dt.datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=_dt.timezone.utc)
        return parsed
    except Exception:
        return None


def _hour_truncated_bucket(value: str) -> str:
    parsed = _parse_rfc3339_utc(value)
    if parsed is None:
        parsed = _dt.datetime.now(_dt.timezone.utc)
    truncated = parsed.replace(minute=0, second=0, microsecond=0)
    return truncated.isoformat().replace("+00:00", "Z")


def _summary_feature_set_hash(predictions: list[dict[str, object]]) -> str:
    rows: list[str] = []
    for pred in sorted(predictions, key=lambda p: str(p.get("match_id", ""))):
        rows.append("|".join([
            str(pred.get("match_id", "")),
            str(pred.get("summary_expected_count", "")),
            str(pred.get("summary_original_count", "")),
            str(pred.get("summary_top_n_by", "")),
        ]))
    blob = "\n".join(rows)
    return _hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _summary_salience_score(
    entity: dict[str, object],
    now: _dt.datetime | None = None,
) -> float:
    if now is None:
        now = _dt.datetime.now(_dt.timezone.utc)

    league_tier = int(entity.get("league_tier") or 0)
    derby_bonus = 20.0 if entity.get("is_derby") else 0.0
    prior_mentions = float(entity.get("prior_user_team_mentions") or 0)

    kickoff_value = entity.get("kickoff_utc") or entity.get("kickoff_time")
    kickoff_dt: _dt.datetime | None = None
    if isinstance(kickoff_value, str):
        kickoff_dt = _parse_rfc3339_utc(kickoff_value)
    elif isinstance(kickoff_value, _dt.datetime):
        kickoff_dt = kickoff_value
    if kickoff_dt is not None and kickoff_dt.tzinfo is None:
        kickoff_dt = kickoff_dt.replace(tzinfo=_dt.timezone.utc)

    proximity_score = 0.0
    if kickoff_dt is not None:
        delta_hours = abs((kickoff_dt - now).total_seconds()) / 3600.0
        proximity_score = max(0.0, 1.0 - min(delta_hours, 24.0) / 24.0)

    return league_tier * 100.0 + derby_bonus + proximity_score * 10.0 + prior_mentions


def _load_disclosure_texts(locale: str) -> tuple[list[dict[str, object]], str]:
    disclosures, used_locale = load_disclosures(locale)
    return disclosures, used_locale


def _build_disclosures_metadata(disclosures: list[dict[str, object]]) -> list[dict[str, object]]:
    return [
        {
            "disclosure_id": d["disclosure_id"],
            "version": d["version"],
            "disclosure_sha8": d["disclosure_sha8"],
        }
        for d in disclosures
    ]


def _make_default_qa_answer_part(
    intent: str,
    body: str,
    citations: list[dict[str, object]] | None,
    qa_correlation_id: str,
    emitted_at_utc: str,
) -> dict[str, object]:
    citation: dict[str, object] = {
        "kind": "source",
        "produced_at_utc": emitted_at_utc,
    }
    if isinstance(citations, list):
        for item in citations:
            if isinstance(item, dict) and item.get("kind") and item.get("produced_at_utc"):
                citation = dict(item)
                break

    return {
        "intent": intent,
        "body": body,
        "citation": citation,
        "polarity": "affirm",
        "subquery_correlation_id": qa_correlation_id,
    }


def _collapse_parts_for_v1(payload: dict[str, object]) -> None:
    parts = payload.get("parts")
    if isinstance(parts, list) and parts:
        first = parts[0]
        if isinstance(first, dict) and isinstance(first.get("body"), str):
            payload["answer_text"] = first["body"]
    payload.pop("parts", None)
    payload.pop("envelope_signature", None)
    payload.pop("envelope_signature_key_id", None)
    payload.pop("body_canonical_sha", None)


def _strip_fields(payload: dict[str, object], field_paths: list[str]) -> None:
    for path in field_paths:
        if path == "parts":
            payload.pop("parts", None)
            continue
        if path in ("envelope_signature", "envelope_signature_key_id"):
            payload.pop(path, None)
            continue
        if path == "body_canonical_sha":
            payload.pop("body_canonical_sha", None)
            continue
        parts = path.split(".")
        current = payload
        for part in parts[:-1]:
            if not isinstance(current, dict):
                current = None
                break
            current = current.get(part)
        if isinstance(current, dict):
            current.pop(parts[-1], None)


def _requested_qa_answer_schema_version(request_metadata: dict[str, object] | None) -> int | None:
    if not isinstance(request_metadata, dict):
        return None

    raw = request_metadata.get(_QA_ANSWER_SCHEMA_VERSION_REQUEST_KEY)
    if raw is None:
        return None
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str):
        try:
            return int(raw)
        except ValueError:
            return None
    return None


def _maybe_downgrade_qa_answer_payload(
    payload: dict[str, object],
    request_metadata: dict[str, object] | None,
) -> dict[str, object]:
    target_version = _requested_qa_answer_schema_version(request_metadata)
    if target_version is None:
        return payload

    current_version = int(payload.get("schema_version") or 1)
    if target_version >= current_version:
        return payload

    original = dict(payload)
    downgraded = downgrade_qa_answer_v1(payload, target_version)
    event = _make_qa_answer_downgrade_event(
        original_payload=original,
        request_metadata=request_metadata,
        from_version=current_version,
        to_version=target_version,
    )
    if event is not None:
        downgraded["_qa_answer_downgrade_event"] = event
    return downgraded


def _load_downgrade_matrix() -> dict[str, dict[str, list[str]]]:
    path = Path(__file__).resolve().parents[3] / "swarm" / "sdk" / "schemas" / "qa.answer.v1.downgrade_matrix.json"
    try:
        import json
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def downgrade_qa_answer_v1(payload: dict[str, object], target_version: int) -> dict[str, object]:
    current_version = int(payload.get("schema_version") or 1)
    if target_version >= current_version:
        return dict(payload)
    matrix = _load_downgrade_matrix()
    from_version = str(current_version)
    to_version = str(target_version)
    if from_version not in matrix or to_version not in matrix[from_version]:
        raise ValueError(f"unsupported downgrade path {from_version} -> {to_version}")
    output = dict(payload)
    strip_fields = matrix[from_version][to_version] or []
    _strip_fields(output, strip_fields)
    if current_version >= 2 and target_version == 1:
        _collapse_parts_for_v1(output)
    output["schema_version"] = target_version
    return output


def _make_qa_answer_downgrade_event(
    original_payload: dict[str, object],
    request_metadata: dict[str, object] | None,
    from_version: int,
    to_version: int,
) -> dict[str, object] | None:
    if to_version >= from_version:
        return None

    event_payload: dict[str, object] = {
        "kind": "qa_answer_downgraded",
        "producer": "nlp.answer.v1",
        "request_id": original_payload.get("request_id"),
        "qa_correlation_id": original_payload.get("qa_correlation_id"),
        "from": from_version,
        "to": to_version,
        "emitted_at": _utc_iso(),
    }

    if isinstance(request_metadata, dict):
        client_id = request_metadata.get("client_id")
        if isinstance(client_id, str) and client_id != "":
            event_payload["client_id_h"] = _hashlib.sha256(
                client_id.encode("utf-8")
            ).hexdigest()

    sha_envelope = _hashlib.sha256(
        json.dumps(original_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    event_payload["sha_envelope"] = sha_envelope
    return event_payload


def _unwrap_qa_answer_downgrade_events(messages: Iterable[Message]) -> list[Message]:
    output: list[Message] = []
    for msg in messages:
        if msg.topic == QA_ANSWER_V1 and isinstance(msg.payload, dict):
            payload = dict(msg.payload)
            event_payload = payload.pop("_qa_answer_downgrade_event", None)
            output.append(Message.new(topic=QA_ANSWER_V1, payload=payload, producer=msg.envelope.producer))
            if isinstance(event_payload, dict):
                output.append(
                    Message.new(topic=NLP_EVENT_V1, payload=event_payload, producer=msg.envelope.producer)
                )
        else:
            output.append(msg)
    return output


class FixtureStateLookup:
    """Phase 10 §10.27.1 fixture-state lookup contract for the dispatcher."""

    @staticmethod
    def get(
        match_id: str,
        request_id: str,
        qa_correlation_id: str,
        timeout_ms: int,
    ) -> tuple[str, str, str, Message]:
        """Build a fixture-state lookup request and return a default degraded state.

        In the current Phase 10 skeleton, the actual data-plane reply is not
        yet wired through. The contract is preserved by emitting the
        data.request.v1{kind=fixture_state} request and treating a missing
        response as UNKNOWN rather than defaulting to scheduled.
        """
        request_msg = Message.new(
            topic=DATA_REQUEST_V1,
            payload={
                "schema_version": 1,
                "kind": "fixture_state",
                "match_id": match_id,
                "request_id": request_id,
                "qa_correlation_id": qa_correlation_id,
                "timeout_ms": timeout_ms,
                "emitted_at": _utc_iso(),
            },
            producer="nlp.dispatcher.v1",
        )
        return FixtureState.UNKNOWN.value, _utc_iso(), "fallback", request_msg

# Maximum number of dedup keys held in each NLP agent's LRU (structural cap;
# not a config knob because it is a data-structure bound, not a tunable
# threshold — the window_s config is the user-facing knob).
_NLP_DEDUP_MAX_KEYS: int = 100_000
_MOCK_PREDICT_CITATION_HMAC_KEY: bytes = b"negelir:mock:predict:citation:hmac:v1"


AUDIT_REDACTION_WHITELIST = frozenset(
    {
        "qa_correlation_id",
        "request_id",
        "intent",
        "intent_confidence",
        "entity_count",
        "proofreader_status",
        "humanizer_used",
        "degraded",
        "degraded_reason",
        "tier_id_required",
        "model_versions",
        "calibration_version",
        "nlp_pipeline_version",
        "lexicon_versions",
        "produced_at_utc",
    }
)


def _redact_text_with_pii_patterns(value: str) -> str:
    redacted, _ = redact_tr_pii(value)
    for pii_kind, pii_pattern in PII_PATTERNS:
        redacted = pii_pattern.sub(
            f"[REDACTED_{pii_kind.upper()}]",
            redacted,
        )
    return redacted


def _redact_value_with_pii_patterns(value: object) -> object:
    if isinstance(value, str):
        return _redact_text_with_pii_patterns(value)
    if isinstance(value, list):
        return [_redact_value_with_pii_patterns(item) for item in value]
    if isinstance(value, dict):
        return {
            key: _redact_value_with_pii_patterns(item)
            for key, item in value.items()
        }
    return value


def _sha256_hex(value: str) -> str:
    return _hashlib.sha256(value.encode("utf-8")).hexdigest()

_ASR_HESITATION_PHRASES = (
    "falan filan",
    "ne bileyim",
)
_ASR_HESITATION_TOKENS = frozenset(
    {
        "ııı",
        "eee",
        "ee",
        "ıı",
        "mmm",
        "hmmm",
        "şey",
        "yani",
        "aslında",
        "yaa",
        "işte",
        "falan",
        "bileyim",
    }
)
_ASR_TEXT_TOKEN_RE = re.compile(r"\b[^\W\d_]+\b", flags=re.UNICODE)


def _canonical_lexicon_snapshot_sha(lexicon_versions: object) -> str:
    if not isinstance(lexicon_versions, dict):
        return ""
    pairs = sorted(
        f"{str(key)}:{str(value)}"
        for key, value in lexicon_versions.items()
        if isinstance(key, str)
    )
    return _sha256_hex("|".join(pairs))


def _canonical_conversation_entity_graph_payload(envelope: dict[str, object]) -> dict[str, object]:
    conversation_id = str(envelope.get("conversation_id") or "").strip()
    if not conversation_id:
        return {}

    try:
        context = ConversationStore().load(conversation_id)
    except Exception:
        return {}
    if not isinstance(context, dict):
        return {}

    entities: list[dict[str, object]] = []
    for entity in context.get("entities", []):
        if not isinstance(entity, dict):
            continue
        kind = entity.get("kind")
        canonical_id = entity.get("canonical_id")
        if not isinstance(kind, str) or not isinstance(canonical_id, str):
            continue
        entry: dict[str, object] = {
            "kind": kind,
            "canonical_id": canonical_id,
        }
        account_id_h = entity.get("account_id_h")
        if isinstance(account_id_h, str) and account_id_h:
            entry["account_id_h"] = account_id_h
        entities.append(entry)

    if not entities:
        return {}

    anaphora_mentions: list[dict[str, object]] = []
    for mention in context.get("anaphora_mentions", []):
        if not isinstance(mention, dict):
            continue
        kind = mention.get("kind")
        canonical_id = mention.get("canonical_id")
        if not isinstance(kind, str) or not isinstance(canonical_id, str):
            continue
        anaphora_mentions.append({
            "kind": kind,
            "canonical_id": canonical_id,
        })

    graph: dict[str, object] = {
        "schema_version": 1,
        "conversation_id": conversation_id,
        "turn_index": int(context.get("turn_index") or 0),
        "entities": sorted(
            entities,
            key=lambda entity: (str(entity.get("kind") or ""), str(entity.get("canonical_id") or "")),
        ),
    }
    if anaphora_mentions:
        graph["anaphora_mentions"] = sorted(
            anaphora_mentions,
            key=lambda mention: (str(mention.get("kind") or ""), str(mention.get("canonical_id") or "")),
        )
    return graph


def _canonical_conversation_entity_graph_sha(envelope: dict[str, object]) -> str:
    graph_payload = _canonical_conversation_entity_graph_payload(envelope)
    if not graph_payload:
        return ""
    return _sha256_hex(
        json.dumps(graph_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    )


def _write_conversation_entity_graph(bundle_path: str, envelope: dict[str, object]) -> str:
    graph_payload = _canonical_conversation_entity_graph_payload(envelope)
    if not graph_payload:
        return ""
    _write_bundle_json(bundle_path, "conversation_entity_graph.json", graph_payload)
    return _sha256_hex(
        json.dumps(graph_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    )


def _erase_account_id_h_from_conversation_entity_graph(bundle_path: str, account_id_h: str) -> None:
    path = os.path.join(bundle_path, "conversation_entity_graph.json")
    if not os.path.exists(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as fh:
            graph = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return

    def _remove_account_id_h(value: object) -> bool:
        changed = False
        if isinstance(value, dict):
            if value.get("account_id_h") == account_id_h:
                value.pop("account_id_h", None)
                changed = True
            for item in value.values():
                if _remove_account_id_h(item):
                    changed = True
        elif isinstance(value, list):
            for item in value:
                if _remove_account_id_h(item):
                    changed = True
        return changed

    if _remove_account_id_h(graph):
        _write_bundle_json(bundle_path, "conversation_entity_graph.json", graph)


def _nlp_audit_bundle_dir(bundle_sha: str) -> str:
    return os.path.join("data", "nlp", "audit_bundles", bundle_sha)


def _write_bundle_file(bundle_path: str, rel_path: str, contents: str) -> None:
    path = os.path.join(bundle_path, rel_path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(contents)
    os.chmod(path, 0o600)


def _write_bundle_json(bundle_path: str, rel_path: str, data: object) -> None:
    path = os.path.join(bundle_path, rel_path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        import json

        json.dump(data, fh, ensure_ascii=False, indent=2)
    os.chmod(path, 0o600)


def _canonical_templates_dir() -> Path:
    return Path(__file__).resolve().parents[3] / "nlp" / "templates"


def _write_bundle_templates(bundle_path: str) -> None:
    template_dir = _canonical_templates_dir()
    if not template_dir.exists():
        return
    for path in sorted(template_dir.rglob("*.j2")):
        if not path.is_file():
            continue
        rel = path.relative_to(template_dir)
        sha = _hashlib.sha256(path.read_bytes()).hexdigest()
        rel_path = os.path.join("templates", f"{rel.as_posix()}.sha256")
        _write_bundle_file(bundle_path, rel_path, sha)


def _maybe_create_nlp_audit_bundle(envelope: dict[str, object]) -> None:
    from common.config import cfg

    bundle_sha = _nlp_audit_bundle_sha(envelope)
    bundle_path = _nlp_audit_bundle_dir(bundle_sha)
    manifest_path = os.path.join(bundle_path, "manifest.json")
    if os.path.exists(manifest_path):
        return

    lexicon_versions = envelope.get("lexicon_versions", {})
    lexicon_snapshot_sha = _canonical_lexicon_snapshot_sha(lexicon_versions)
    intent_model_sha = str(getattr(cfg, "nlp_intent_model_sha256", "") or "")
    crf_model_sha = str(getattr(cfg, "nlp_entity_crf_model_sha256", "") or "")
    calibration_version = str(envelope.get("calibration_version", "") or "")
    template_git_sha = str(getattr(cfg, "nlp_template_git_sha", "") or "")
    pipeline_version = str(envelope.get("nlp_pipeline_version", "") or "")
    conversation_entity_graph_sha = _write_conversation_entity_graph(bundle_path, envelope)

    os.makedirs(bundle_path, exist_ok=True)
    os.chmod(bundle_path, 0o700)
    _write_bundle_json(bundle_path, "manifest.json", {
        "bundle_sha": bundle_sha,
        "lexicon_snapshot_sha": lexicon_snapshot_sha,
        "conversation_entity_graph_sha": conversation_entity_graph_sha,
        "intent_model_sha256": intent_model_sha,
        "crf_model_sha256": crf_model_sha,
        "calibration_version": calibration_version,
        "template_git_sha": template_git_sha,
        "pipeline_version": pipeline_version,
        "first_observed_at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "retention_class": "legal_hold",
    })

    if isinstance(lexicon_versions, dict):
        for key, value in sorted(lexicon_versions.items()):
            if not isinstance(key, str) or not isinstance(value, str):
                continue
            name = f"{key}.tr.yaml.sha256"
            _write_bundle_file(bundle_path, os.path.join("lexicons", name), value)

    _write_bundle_file(bundle_path, "intent.tr.bin.sha256", intent_model_sha)
    _write_bundle_file(bundle_path, "crf.tr.model.sha256", crf_model_sha)
    _write_bundle_templates(bundle_path)


def _nlp_audit_bundle_sha(envelope: dict[str, object]) -> str:
    from common.config import cfg

    lexicon_snapshot_sha = _canonical_lexicon_snapshot_sha(
        envelope.get("lexicon_versions", {})
    )
    intent_model_sha = str(getattr(cfg, "nlp_intent_model_sha256", "") or "")
    crf_model_sha = str(getattr(cfg, "nlp_entity_crf_model_sha256", "") or "")
    calibration_version = str(envelope.get("calibration_version", "") or "")
    template_git_sha = str(getattr(cfg, "nlp_template_git_sha", "") or "")
    pipeline_version = str(envelope.get("nlp_pipeline_version", "") or "")
    conversation_entity_graph_sha = _canonical_conversation_entity_graph_sha(envelope)

    return _sha256_hex(
        "|".join(
            [
                lexicon_snapshot_sha,
                intent_model_sha,
                crf_model_sha,
                calibration_version,
                template_git_sha,
                pipeline_version,
                conversation_entity_graph_sha,
            ]
        )
    )


def _entity_hash(entities: list) -> str:
    """Stable 16-hex-char hash of the sorted canonical_id set in *entities*.

    Used as the third component of the §10.6 dispatcher idempotency key
    ``(qa_correlation_id, intent, entity_hash)``.
    """
    sorted_ids = sorted(
        str(e.get("canonical_id") or "") for e in entities
    )
    return _hashlib.sha256("|".join(sorted_ids).encode()).hexdigest()[:16]


def _normalize_intent_modifier(modifier: object | None) -> str:
    if modifier is None:
        return "none"
    if isinstance(modifier, (list, tuple)):
        return ",".join(str(item) for item in modifier)
    normalized = str(modifier)
    return normalized if normalized.strip() else "none"


def _make_repeated_query_signature(
    intent: str,
    entities: list[dict[str, object]],
    intent_modifier: object | None,
) -> str:
    return "|".join(
        [
            intent,
            _entity_hash(entities),
            _normalize_intent_modifier(intent_modifier),
        ]
    )


def audit_key(
    qa_correlation_id: str, intent_model_version: str, calibration_version: str
) -> str:
    """§10.13 audit key: stable hash of (qa_correlation_id, intent_model_version,
    calibration_version).

    Two requests with the same qa_correlation_id but different model/calibration
    versions MUST produce distinct qa.answer.v1 envelopes; this key is used for
    audit logging and ensuring distinct envelopes.

    Returns a 16-hex-char sha256 prefix.
    """
    components = f"{qa_correlation_id}|{intent_model_version}|{calibration_version}"
    return _hashlib.sha256(components.encode()).hexdigest()[:16]


def cache_key_for_intent(
    intent: str,
    entity_hash: str,
    fixture_window_bucket: str,
    model_versions_hash: str,
    intent_model_version: str,
    lexicon_snapshot_sha: str,
    calibration_version: str,
    pipeline_version: str,
    disclosures_snapshot_sha: str = "",
) -> str:
    """§10.12 L0/L1 cache key including model/calibration and disclosure snapshot state.

    Key = sha256(intent | entity_hash | fixture_window_bucket | model_versions_hash |
                 intent_model_version | lexicon_snapshot_sha | calibration_version |
                 pipeline_version | disclosures_snapshot_sha).

    Returns a 16-hex-char sha256 prefix.
    """
    components = (
        f"{intent}|{entity_hash}|{fixture_window_bucket}|{model_versions_hash}|"
        f"{intent_model_version}|{lexicon_snapshot_sha}|{calibration_version}|"
        f"{pipeline_version}|{disclosures_snapshot_sha}"
    )
    return _hashlib.sha256(components.encode()).hexdigest()[:16]


def _utc_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


def _new_id() -> str:
    return uuid4().hex


def _enforce_nlp_spool_audit_dir_modes() -> None:
    """Refuse startup when NLP spool/audit files are looser than 0600.

    Directory contract: ``0700`` for ``cfg.nlp_agent_spool_dir`` and
    ``data/nlp/audit`` (including subdirectories).
    File contract: ``0600`` for every existing file under those trees.
    """
    if os.name != "posix":
        return

    from common.config import cfg

    targets = [
        Path(str(cfg.nlp_agent_spool_dir)),
        Path("data") / "nlp" / "audit",
    ]
    violations: list[str] = []

    for root in targets:
        root.mkdir(parents=True, exist_ok=True)
        os.chmod(root, 0o700)

        for path in sorted(root.rglob("*")):
            if path.is_symlink():
                continue
            if path.is_dir():
                os.chmod(path, 0o700)
                continue
            if path.is_file():
                mode = stat.S_IMODE(path.stat().st_mode)
                if mode != 0o600:
                    violations.append(f"{path}: expected 0600, got {mode:04o}")

    if violations:
        raise RuntimeError(
            "NLP startup refused: insecure spool/audit file modes; "
            + "; ".join(violations)
        )


def _enforce_nlp_runtime_locale() -> None:
    from common.config import cfg

    locale_required = str(cfg.nlp_runtime_locale or "").strip()
    if not locale_required:
        raise RuntimeError(
            "NLP startup refused: nlp_runtime_locale is not configured; "
            "must be tr_TR.UTF-8 or und-TR"
        )

    try:
        actual = locale.setlocale(locale.LC_CTYPE, locale_required)
    except locale.Error as exc:
        raise RuntimeError(
            "NLP startup refused: nlp_runtime_locale mismatch; "
            "failed to set LC_CTYPE to the required locale. "
            "Expected tr_TR.UTF-8 or und-TR."
        ) from exc

    normalized_actual = actual.replace("-", "_").lower()
    if not normalized_actual.startswith(("tr_tr", "und_tr")):
        raise RuntimeError(
            "NLP startup refused: nlp_runtime_locale_mismatch; "
            f"LC_CTYPE resolved to {actual!r} instead of tr_TR.UTF-8 or und-TR"
        )


class _SummaryAgg:
    """In-flight aggregation state for a summary.* fan-out (§10.6)."""

    __slots__ = ("expected", "qa_request_id", "qa_correlation_id", "deadline", "predictions")

    def __init__(
        self,
        expected: int,
        qa_request_id: str,
        qa_correlation_id: str,
        deadline: float,
    ) -> None:
        self.expected = expected
        self.qa_request_id = qa_request_id
        # §10.6 qa_correlation_id invariant — read from predict.approved.v1
        # (additive Phase 5 field); defaults to summary_correlation_id so the
        # single-value case (`summary_corr`) is backward-compatible.
        self.qa_correlation_id = qa_correlation_id
        self.deadline = deadline  # monotonic timestamp
        self.predictions: list = []


class NlpBootProbeState:
    """Tracks probe state so liveness and readiness are not conflated.

    Phase 10 §10.21.9 starts with the failure mode where a pod is alive but
    still booting NLP assets. This state object makes that distinction
    explicit: liveness can be true while readiness is still false.
    """

    _STAGE_NAMES = (
        "starting",
        "lexicons_loaded",
        "intent_model_loaded",
        "crf_loaded",
        "symspell_built",
        "jinja_warmed",
        "gpu_lease_acquired_or_skipped",
        "consensus_smoke_observed",
    )

    __slots__ = (
        "_lock",
        "_stage",
        "_clock_iso",
        "_monotonic",
        "_boot_started_s",
        "_boot_budget_s",
        "_boot_liveness_grace_s",
        "_stage_caps_s",
        "_timed_out",
    )

    def __init__(
        self,
        clock_iso: Callable[[], str] | None = None,
        monotonic: Callable[[], float] | None = None,
        boot_budget_s: float | None = None,
        boot_liveness_grace_s: float | None = None,
        stage_caps_s: dict[int, float] | None = None,
    ) -> None:
        self._lock = _threading.Lock()
        self._stage = 0
        self._clock_iso = clock_iso or (
            lambda: _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
        )
        self._monotonic = monotonic or _time.monotonic
        self._boot_started_s = self._monotonic()
        if boot_budget_s is None or boot_liveness_grace_s is None:
            from common.config import cfg
            if boot_budget_s is None:
                boot_budget_s = float(cfg.nlp_boot_budget_s)
            if boot_liveness_grace_s is None:
                boot_liveness_grace_s = float(cfg.nlp_boot_liveness_grace_s)
        self._boot_budget_s = float(boot_budget_s)
        self._boot_liveness_grace_s = float(boot_liveness_grace_s)
        if stage_caps_s is None:
            from common.config import cfg

            self._stage_caps_s = {
                1: 10.0,
                2: 3.0,
                3: 2.0,
                4: 10.0,
                5: 2.0,
                6: 3.0,
                7: float(cfg.nlp_boot_consensus_smoke_timeout_s),
            }
        else:
            self._stage_caps_s = stage_caps_s
        self._timed_out = False

    def liveness(self) -> bool:
        """Process liveness with boot-timeout grace for K8s restart handoff."""
        with self._lock:
            ready = self._stage >= len(self._STAGE_NAMES) - 1 and not self._timed_out
            timed_out = self._timed_out
        if ready or not timed_out:
            return True
        elapsed_s = self._monotonic() - self._boot_started_s
        return elapsed_s < self._boot_liveness_grace_s

    def readiness(self) -> bool:
        """Traffic readiness: false until boot stage 7 is reached."""
        with self._lock:
            return (not self._timed_out) and self._stage >= len(self._STAGE_NAMES) - 1

    def startup_readiness(self) -> bool:
        """Startup probe readiness: true once lexicons are loaded (stage >= 1)."""
        with self._lock:
            return self._stage >= 1

    def _build_boot_timeout_alert(self, *, producer: str, reason: str, last_stage: int) -> Message:
        return Message.new(
            topic=NLP_ALERT_V1,
            payload={
                "schema_version": 1,
                "alert_id": _new_id(),
                "kind": "nlp_cold_start_timeout",
                "severity": "critical",
                "source": producer,
                "reason": reason,
                "request_id": None,
                "qa_correlation_id": None,
                "details": {
                    "last_stage": last_stage,
                    "last_stage_name": self._STAGE_NAMES[last_stage],
                    "boot_budget_s": self._boot_budget_s,
                },
                "emitted_at": self._clock_iso(),
            },
            producer=producer,
        )

    def stage(self) -> int:
        """Return the current monotonic boot stage index."""
        with self._lock:
            return self._stage

    def mark_stage(self, stage: int, elapsed_ms: int, producer: str = "nlp.intent.v1") -> Message:
        """Advance stage monotonically and emit ``nlp.event.v1{kind=cold_start_stage}``."""
        if stage < 0 or stage >= len(self._STAGE_NAMES):
            raise ValueError(f"invalid boot stage: {stage}")
        if elapsed_ms < 0:
            raise ValueError("elapsed_ms must be >= 0")

        timeout_reason: str | None = None
        last_stage = 0

        with self._lock:
            if stage < self._stage:
                raise ValueError(
                    f"boot stage regression: current={self._stage} attempted={stage}"
                )
            last_stage = self._stage
            if self._timed_out:
                timeout_reason = "boot_budget_already_breached"
            else:
                stage_cap_s = self._stage_caps_s.get(stage)
                if stage_cap_s is not None and (elapsed_ms / 1000.0) > stage_cap_s:
                    self._timed_out = True
                    timeout_reason = "stage_cap_breached"
                elif (self._monotonic() - self._boot_started_s) > self._boot_budget_s:
                    self._timed_out = True
                    timeout_reason = "total_boot_budget_breached"
                else:
                    self._stage = stage

        if timeout_reason is not None:
            return self._build_boot_timeout_alert(
                producer=producer,
                reason=timeout_reason,
                last_stage=last_stage,
            )

        return Message.new(
            topic=NLP_EVENT_V1,
            payload={
                "kind": "cold_start_stage",
                "producer": producer,
                "request_id": None,
                "stage": stage,
                "stage_name": self._STAGE_NAMES[stage],
                "elapsed_ms": elapsed_ms,
                "emitted_at": self._clock_iso(),
            },
            producer=producer,
        )

    def mark_ready(self) -> None:
        """Compatibility helper: mark probe as fully booted (final stage)."""
        with self._lock:
            if not self._timed_out:
                self._stage = len(self._STAGE_NAMES) - 1

    def mark_consensus_smoke_observed(self, elapsed_ms: int, producer: str = "nlp.intent.v1") -> Message:
        """Specialized transition for the boot consensus smoke stage."""
        return self.mark_stage(len(self._STAGE_NAMES) - 1, elapsed_ms=elapsed_ms, producer=producer)


class NlpIntentAgent:
    """Phase 10 §10.0–§10.5 skeleton: normalize + classify + extract.

    Subscribes to ``qa.request.v1`` (the sec-sanitized data-plane
    envelope, NEVER the raw ``qa.request`` control-plane).  Publishes
    ``qa.intent.v1`` carrying the structured intent + entity set, plus
    ``nlp.event.v1`` / ``nlp.alert.v1`` for operational observability.
    """

    name = "nlp.intent.v1"
    subscribes = [QA_REQUEST_V1, QA_CONTEXT_V1, QA_CONTEXT_EXTENSION_V1]
    publishes = [QA_INTENT_V1, NLP_EVENT_V1, NLP_ALERT_V1, NLP_GOSSIP_V1, NLP_SHADOW_V1]

    def __init__(
        self,
        monotonic: Callable[[], float] | None = None,
        deduper: object | None = None,
    ) -> None:
        self._log = logging.getLogger("swarm.agents.nlp.intent")
        add_log_filter(self._log, filters=(PIIScrubFilter(),))
        self._monotonic = monotonic or _time.monotonic
        _enforce_nlp_spool_audit_dir_modes()
        self._conversation_store = ConversationStore()
        self._tr_pii_alert_debouncer = AlertDebouncer(
            ttl_s=600,
            max_buckets=10_000,
            clock=self._monotonic,
        )
        self._asr_input_event_debouncer = AlertDebouncer(
            ttl_s=60,
            max_buckets=1_000,
            critical_bypass=False,
            clock=self._monotonic,
        )
        self._shout_rate_anomaly_debouncer = AlertDebouncer(
            ttl_s=600,
            max_buckets=10_000,
            clock=self._monotonic,
        )
        # §10.13 producer-side deduper (lazy-init from cfg).
        self._deduper = deduper
        self._deduper_lock = _threading.Lock()
        self._last_gossip_at = float("-inf")

    def _get_deduper(self) -> object:
        """Return the intent deduper, lazily creating it from cfg."""
        if self._deduper is None:
            with self._deduper_lock:
                if self._deduper is None:
                    from common.config import cfg
                    from swarm.sdk import RequestIdDeduper
                    self._deduper = RequestIdDeduper(
                        window_s=float(cfg.nlp_request_dedup_window_s),
                        max_keys=_NLP_DEDUP_MAX_KEYS,
                        clock=self._monotonic,
                    )
        return self._deduper

    def _make_gossip(self) -> Message:
        from common.config import cfg

        lexicon_set_sha = str(_lexicon_snapshot_sha() or "")
        intent_sha = str(getattr(cfg, "nlp_intent_model_sha256", "") or "")
        crf_sha = str(getattr(cfg, "nlp_entity_crf_model_sha256", "") or "")
        calibration_version = str(getattr(cfg, "nlp_intent_model_version", "") or "")
        template_git_sha = str(getattr(cfg, "nlp_template_git_sha", "") or "")
        pipeline_version = str(getattr(cfg, "nlp_pipeline_version", "") or "")

        return Message.new(
            topic=NLP_GOSSIP_V1,
            payload={
                "kind": "nlp_lexicon_state_gossip",
                "producer": self.name,
                "pod_instance_id": str(cfg.nlp_pod_id),
                "lexicon_set_sha": lexicon_set_sha,
                "intent_sha": intent_sha,
                "crf_sha": crf_sha,
                "calibration_version": calibration_version,
                "template_git_sha": template_git_sha,
                "pipeline_version": pipeline_version,
                "emitted_at_utc": _utc_iso(),
            },
            producer=self.name,
        )

    def on_heartbeat(self) -> list[Message]:
        from common.config import cfg

        now = self._monotonic()
        interval = float(cfg.nlp_lexicon_gossip_interval_s)
        if now - self._last_gossip_at < interval:
            return []
        self._last_gossip_at = now
        return [self._make_gossip()]

    def _make_tr_pii_alert(self, request_id: str, kind: str, subject: str) -> Message:
        return Message.new(
            topic=NLP_ALERT_V1,
            payload={
                "kind": kind,
                "producer": self.name,
                "request_id": request_id or None,
                "subject": subject,
                "severity": "warn",
                "emitted_at": _utc_iso(),
            },
            producer=self.name,
        )

    def _make_asr_input_auto_detected_event(self, request_id: str) -> Message:
        return Message.new(
            topic=NLP_EVENT_V1,
            payload={
                "kind": "asr_input_auto_detected",
                "producer": self.name,
                "request_id": request_id or None,
                "input_source": "voice",
                "emitted_at": _utc_iso(),
            },
            producer=self.name,
        )

    def _is_asr_input_text(self, text: str) -> bool:
        normalized = text.lower()
        if "?" in normalized or "," in normalized or len(normalized) < 40:
            return False
        hesitation_count = 0
        for phrase in _ASR_HESITATION_PHRASES:
            count = normalized.count(phrase)
            hesitation_count += count
            if count:
                normalized = normalized.replace(phrase, " ")
        tokens = _ASR_TEXT_TOKEN_RE.findall(normalized)
        hesitation_count += sum(1 for token in tokens if token in _ASR_HESITATION_TOKENS)
        return hesitation_count >= 2

    def _with_tr_pii_alerts(self, results: list[Message], payload: dict[str, object]) -> list[Message]:
        alerts: list[Message] = []
        request_id = str(payload.get("request_id", ""))
        sanitized_text = str(payload.get("sanitized_text", ""))
        for kind, subject in parse_redacted_tr_pii(sanitized_text):
            alert_kind = f"nlp_pii_in_input_{kind.lower()}"
            decision = self._tr_pii_alert_debouncer.decide(
                kind=alert_kind,
                subject=subject,
                severity="warn",
                reason=f"tr_pii_detected:{kind}",
            )
            if not decision.emit:
                continue
            alerts.append(self._make_tr_pii_alert(request_id, alert_kind, subject))
        return results + alerts

    def _merge_context_extension(
        self,
        conversation_id: str,
        payload: dict[str, object],
    ) -> None:
        entities = [entity for entity in payload.get("entities", []) if isinstance(entity, dict)]
        if not entities:
            return

        context = self._conversation_store.load(conversation_id) or {}
        mention_stack = (
            list(context.get("anaphora_mentions", []))
            if isinstance(context.get("anaphora_mentions"), list)
            else []
        )
        turn_index = (
            int(context.get("turn_index"))
            if isinstance(context.get("turn_index"), int)
            else 0
        )
        now = _utc_iso()
        for entity in entities:
            kind = str(entity.get("kind") or "").strip()
            canonical_id = str(entity.get("canonical_id") or "").strip()
            if not kind or not canonical_id:
                continue
            mention_stack.append({
                "kind": kind,
                "canonical_id": canonical_id,
                "confidence": float(entity.get("confidence") or 1.0),
                "source": str(entity.get("source") or "system"),
                "name": str(entity.get("name") or ""),
                "mentioned_by": "system",
                "mentioned_at": now,
                "mentioned_turn": turn_index,
            })

        stored = dict(context)
        stored["schema_version"] = int(context.get("schema_version", 1) or 1)
        stored["conversation_id"] = conversation_id
        stored["turn_index"] = int(context.get("turn_index")) if isinstance(context.get("turn_index"), int) else 0
        stored["entities"] = list(context.get("entities", [])) if isinstance(context.get("entities"), list) else []
        stored["intent"] = str(context.get("intent") or "")
        stored["anaphora_mentions"] = mention_stack
        self._conversation_store.save(stored)

    def handle(self, msg: Message) -> Iterable[Message]:
        """Process qa.request.v1 / qa.context.v1 for intent classification.

        §10.13 idempotency: dedup on request_id at ingress for qa.request.v1.
        """
        if msg.topic == QA_CONTEXT_V1:
            raw_conversation_id = msg.payload.get("conversation_id")
            conversation_id = str(raw_conversation_id).strip() if isinstance(raw_conversation_id, str) else ""
            if conversation_id:
                self._conversation_store.save(msg.payload)
            return []

        if msg.topic == QA_CONTEXT_EXTENSION_V1:
            raw_conversation_id = msg.payload.get("conversation_id")
            conversation_id = str(raw_conversation_id).strip() if isinstance(raw_conversation_id, str) else ""
            if conversation_id:
                self._merge_context_extension(conversation_id, msg.payload)
            return []

        if msg.topic == QA_REQUEST_V1:
            request_metadata_raw = msg.payload.get("request_metadata")
            self._current_request_metadata = request_metadata_raw if isinstance(request_metadata_raw, dict) else None
            try:
                raw_conversation_id = msg.payload.get("conversation_id")
                conversation_id = str(raw_conversation_id).strip() if isinstance(raw_conversation_id, str) else ""
                if conversation_id:
                    self._conversation_store.load(conversation_id)
                request_id = str(msg.payload.get("request_id", ""))
                if self._get_deduper().seen(request_id):  # type: ignore[union-attr]
                    return []

                locale = msg.payload.get("locale")
                requested_locale = str(locale).strip() if isinstance(locale, str) else ""
                resolved_locale = _resolve_locale_tag(requested_locale)
                if resolved_locale != requested_locale:
                    return self._with_tr_pii_alerts(
                        [
                            self._make_locale_fallback_event(
                                request_id=request_id,
                                requested=requested_locale,
                                resolved=resolved_locale,
                            )
                        ],
                        msg.payload,
                    )

                input_source = msg.payload.get("input_source")
                input_source = str(input_source).strip().lower() if isinstance(input_source, str) else ""
                if input_source not in {"keyboard", "voice", "paste", "unknown"}:
                    input_source = ""
                keyboard_hint = msg.payload.get("keyboard_hint")
                keyboard_hint = str(keyboard_hint).strip().lower() if isinstance(keyboard_hint, str) else ""
                if keyboard_hint not in {"q", "f", "swipe", "unknown"}:
                    keyboard_hint = ""

                sanitized_text = str(msg.payload.get("sanitized_text", ""))
                floor_kind, greeting_echo = assert_minimum_signal(sanitized_text, cfg=cfg)
                subject = _normalize_subject_key(msg.payload)
                shout = detect_all_caps(sanitized_text, cfg=cfg)
                if shout:
                    request_metadata = dict(self._current_request_metadata or {})
                    request_metadata["shout"] = True
                    self._current_request_metadata = request_metadata
                _record_empty_input_rate(subject, floor_kind in ("empty_input_floor_response", "meta.unsupported_too_short"))
                results: list[Message] = []
                if shout:
                    should_alert, shout_details = _record_shout_rate(subject, True)
                    if should_alert:
                        decision = self._shout_rate_anomaly_debouncer.decide(
                            kind="nlp_shout_rate_anomaly_per_subject",
                            subject=subject,
                            severity="warn",
                            reason="nlp_shout_rate_anomaly_per_subject",
                        )
                        if decision.emit:
                            details = {
                                "window_s": shout_details.get("window_s", int(getattr(cfg, "nlp_shout_rate_alert_window_s", 300)))
                            }
                            if "rate" in shout_details:
                                details["rate"] = shout_details["rate"]
                            if "total_requests" in shout_details:
                                details["total_requests"] = shout_details["total_requests"]
                            if "shout_requests" in shout_details:
                                details["shout_requests"] = shout_details["shout_requests"]
                            results.append(
                                _make_nlp_shout_rate_anomaly_event(
                                    request_id=request_id,
                                    qa_correlation_id=None,
                                    subject=subject,
                                    rate=float(details.get("rate", 0.0)),
                                    total_requests=int(details.get("total_requests", 0)),
                                    shout_requests=int(details.get("shout_requests", 0)),
                                    window_s=int(details.get("window_s", int(getattr(cfg, "nlp_shout_rate_alert_window_s", 300)))),
                                )
                            )
                if floor_kind != "ok":
                    return self._with_tr_pii_alerts(
                        self._make_floor_response(
                            request_id=request_id,
                            conversation_id=conversation_id or None,
                            floor_kind=floor_kind,
                            greeting_echo=greeting_echo,
                            normalized_text=sanitized_text,
                            request_metadata=self._current_request_metadata,
                        ) + results,
                        msg.payload,
                    )

                if not input_source and self._is_asr_input_text(sanitized_text):
                    decision = self._asr_input_event_debouncer.decide(
                        kind="asr_input_auto_detected",
                        subject="",
                        severity="warn",
                        reason="asr_input_auto_detected",
                    )
                    if decision.emit:
                        results.append(self._make_asr_input_auto_detected_event(request_id))

                return self._with_tr_pii_alerts(results, msg.payload)
            finally:
                self._current_request_metadata = None

        return []

    def _load_last_answer_text(self, conversation_id: str | None) -> str | None:
        if not conversation_id:
            return None
        history_metadata = self._conversation_store.load_metadata(conversation_id) or {}
        last_answer_text = history_metadata.get("last_qa_answer_text")
        if isinstance(last_answer_text, str) and last_answer_text:
            return last_answer_text
        return None

    def _render_conversational_meta_answer_text(
        self,
        intent: str,
        conversation_id: str | None,
        normalized_text: str,
    ) -> str:
        env = build_environment(user_text_for_guard=normalized_text)
        if intent == "meta.system_capabilities":
            return render(
                "meta.system_capabilities.tr.j2",
                {"system_capabilities": self._load_system_capabilities_text()},
                env=env,
            )

        if intent == "meta.user_data_disclosure":
            return render(
                "meta.user_data_disclosure.tr.j2",
                {},
                env=env,
            )

        if intent == "meta.conversation_history":
            history_metadata = self._conversation_store.load_metadata(conversation_id or "") or {}
            history = history_metadata.get("conversation_history")
            if not isinstance(history, list):
                history = []
            safe_history = [
                entry for entry in history
                if isinstance(entry, dict)
            ]
            return render(
                "meta.conversation_history.tr.j2",
                {"history": safe_history},
                env=env,
            )

        if intent == "meta.last_answer_explain":
            last_answer_text = self._load_last_answer_text(conversation_id)
            return render(
                "meta.last_answer_explain.explained.tr.j2",
                {"last_answer_text": last_answer_text or ""},
                env=env,
            )

        if intent == "meta.url_only_input":
            return render(
                "meta.url_only_input.tr.j2",
                {},
                env=env,
            )

        if intent == "meta.fragment_detected":
            return render(
                "meta.fragment_detected.tr.j2",
                {"user_text": normalized_text},
                env=env,
            )

        if intent == "meta.rhetorical_dismissive":
            return render(
                "meta.rhetorical_dismissive.tr.j2",
                {},
                env=env,
            )

        if intent in ("meta.opinion_unsupported", "meta.opinion_request"):
            return render(
                "meta.opinion_unsupported.tr.j2",
                {},
                env=env,
            )

        if intent == "meta.system_self":
            return render(
                "meta.system_self.tr.j2",
                {"system_capabilities": self._load_system_capabilities_text()},
                env=env,
            )

        return render("meta.unsupported", {}, env=env)

    def _make_floor_response(
        self,
        request_id: str,
        conversation_id: str | None,
        floor_kind: str,
        greeting_echo: str | None,
        normalized_text: str | None = None,
        request_metadata: dict[str, object] | None = None,
    ) -> list[Message]:
        if floor_kind == "meta.unsupported_fragment":
            answer_text = render(
                "meta.fragment_detected.tr.j2",
                {"user_text": normalized_text or ""},
                env=build_environment(user_text_for_guard=normalized_text or ""),
            )
            answer_intent = "meta.fragment_detected"
            answer_kind = "meta.fragment_detected"
        elif floor_kind == "meta.rhetorical_dismissive":
            answer_text = self._render_conversational_meta_answer_text(
                "meta.rhetorical_dismissive",
                conversation_id,
                normalized_text or "",
            )
            answer_intent = "meta.rhetorical_dismissive"
            answer_kind = "meta.rhetorical_dismissive"
        elif floor_kind in ("meta.opinion_unsupported", "meta.opinion_request"):
            answer_text = self._render_conversational_meta_answer_text(
                floor_kind,
                conversation_id,
                normalized_text or "",
            )
            answer_intent = floor_kind
            answer_kind = floor_kind
        elif floor_kind == "meta.url_only_input":
            answer_text = self._render_conversational_meta_answer_text(
                "meta.url_only_input",
                conversation_id,
                normalized_text or "",
            )
            answer_intent = "meta.url_only_input"
            answer_kind = "meta.url_only_input"
        elif floor_kind == "meta.structured_input_refused":
            answer_text = (
                "Gönderdiğin veri yapısı desteklenmiyor; lütfen bir maç ya da "
                "takım sorusu sor."
            )
            answer_intent = "meta.structured_input_refused"
            answer_kind = "meta.structured_input_refused"
        elif floor_kind in ("meta.system_self", "meta.system_capabilities"):
            answer_text = self._render_conversational_meta_answer_text(
                floor_kind,
                conversation_id,
                normalized_text or "",
            )
            answer_intent = floor_kind
            answer_kind = floor_kind
        elif floor_kind in (
            "meta.user_data_disclosure",
            "meta.conversation_history",
            "meta.last_answer_explain",
        ):
            answer_text = self._render_conversational_meta_answer_text(
                floor_kind,
                conversation_id,
                normalized_text or "",
            )
            answer_intent = floor_kind
            answer_kind = floor_kind
        elif greeting_echo:
            greeting = greeting_echo[0].upper() + greeting_echo[1:]
            answer_text = f"{greeting}! Bana bir maç ya da takım sorabilirsin."
            answer_intent = "meta.help"
            answer_kind = "meta.help"
        else:
            answer_text = "Merhaba! Bana bir maç ya da takım sorabilirsin."
            answer_intent = "meta.help"
            answer_kind = "meta.help"

        event_payload = {
            "kind": floor_kind,
            "producer": self.name,
            "request_id": request_id or None,
            "emitted_at": _utc_iso(),
        }
        if floor_kind in ("meta.unsupported_too_short", "meta.unsupported_fragment"):
            event_payload["severity"] = "warn"
        else:
            event_payload["severity"] = "info"

        answer_payload = _make_qa_answer_payload(
            request_id=request_id,
            qa_correlation_id=_new_id(),
            intent=answer_intent,
            kind=answer_kind,
            answer_text=answer_text,
            conversation_id=conversation_id,
            request_metadata=request_metadata,
            emitted_at_utc=_utc_iso(),
        )

        return [
            Message.new(topic=NLP_EVENT_V1, payload=event_payload, producer=self.name),
            Message.new(topic=QA_ANSWER_V1, payload=answer_payload, producer=self.name),
        ]

    def _make_locale_fallback_event(
        self,
        request_id: str,
        requested: str,
        resolved: str,
    ) -> Message:
        return Message.new(
            topic=NLP_EVENT_V1,
            payload={
                "kind": "locale_fallback_used",
                "producer": self.name,
                "request_id": request_id or None,
                "requested": requested,
                "resolved": resolved,
                "emitted_at": _utc_iso(),
            },
            producer=self.name,
        )


class NlpDispatcherAgent:
    """Phase 10 §10.6 skeleton: slot resolver + bus dispatch.

    Subscribes to ``qa.intent.v1`` (structured intent + entities).
    Translates ``(intent, entities)`` to exactly one of:

    * ``predict.request.v1`` — for any ``predict.*`` intent that fully
      resolves to a single fixture + market.
    * ``data.request.v1``    — for ``data.*`` intents (Phase 4 storage
      agent answers).
    * ``qa.answer.v1``       — directly for ``meta.*`` intents (no
      compute needed) or ``kind=disambiguation`` when slot resolution
      surfaces multiple plausible fixtures.

    Also emits ``nlp.event.v1{kind=slot_resolution_failed}`` when
    disambiguation is required, and ``nlp.alert.v1`` on error.

    §10.6 deterministic backoff (this bullet):
    When intent is ``predict.*`` but no fixture-anchoring entity
    (``team`` or ``competition`` kind) is present, the dispatcher MUST
    NOT default to "today's headline match".  It emits
    ``qa.answer.v1{kind=disambiguation}`` so the user can specify which
    match they mean.  The ``fixture_window_h`` in the metadata comes
    from ``cfg.nlp_default_fixture_window_h`` (§10.19 config key).
    """

    name = "nlp.dispatcher.v1"
    subscribes = [QA_INTENT_V1, QA_FEEDBACK_V1]
    publishes = [
        PREDICT_REQUEST_V1,
        DATA_REQUEST_V1,
        QA_CONTEXT_V1,
        QA_ANSWER_V1,
        NLP_EVENT_V1,
        NLP_ALERT_V1,
    ]

    def __init__(
        self,
        clock_iso: Callable[[], str] | None = None,
        new_id: Callable[[], str] | None = None,
        monotonic: Callable[[], float] | None = None,
        deduper: object | None = None,
        cache_invalidator: Callable[[dict[str, object], str | None], None] | None = None,
    ) -> None:
        self._log = logging.getLogger("swarm.agents.nlp.dispatcher")
        add_log_filter(self._log, filters=(PIIScrubFilter(),))
        self._clock_iso = clock_iso or _utc_iso
        _enforce_nlp_spool_audit_dir_modes()
        self._new_id = new_id or _new_id
        self._monotonic = monotonic or _time.monotonic
        self._conversation_store = ConversationStore()
        self._cache_invalidator = cache_invalidator
        self._conversation_entity_override_debouncer = AlertDebouncer(
            ttl_s=60,
            max_buckets=1_000,
            clock=self._monotonic,
        )
        self._anaphora_eviction_event_debouncer = AlertDebouncer(
            ttl_s=int(cfg.nlp_anaphora_eviction_event_ratelimit_s),
            max_buckets=1_000,
            critical_bypass=False,
            clock=self._monotonic,
        )
        self._skew_samples_by_intent: dict[str, deque[tuple[float, float]]] = {}
        self._skew_samples_lock = _threading.Lock()
        self._skew_alert_debouncer = AlertDebouncer(
            ttl_s=int(cfg.nlp_skew_alert_debounce_s),
            max_buckets=1_000,
            critical_bypass=False,
            clock=self._monotonic,
        )
        self._conversation_explicit_override_kinds = self._load_explicit_override_kinds()
        # §10.6 idempotency: lazy-init deduper (cfg not available at class load).
        self._deduper = deduper  # None → created on first handle() call
        self._deduper_lock = _threading.Lock()
        self._feedback_queue = deque(maxlen=int(cfg.nlp_active_learning_queue_max))

    def _get_deduper(self) -> object:
        """Return the dispatcher deduper, lazily creating it from cfg."""
        if self._deduper is None:
            with self._deduper_lock:
                if self._deduper is None:
                    from common.config import cfg
                    from swarm.sdk import RequestIdDeduper
                    self._deduper = RequestIdDeduper(
                        window_s=float(cfg.nlp_dispatch_dedup_window_s),
                        max_keys=_NLP_DEDUP_MAX_KEYS,
                        clock=self._monotonic,
                    )
        return self._deduper

    def _make_feedback_provenance_mismatch_event(
        self,
        request_id: str,
        offered_intents: list[str],
        accepted_intent: str | None,
    ) -> Message:
        return Message.new(
            topic=NLP_EVENT_V1,
            payload={
                "kind": "feedback_provenance_mismatch",
                "producer": self.name,
                "request_id": request_id or None,
                "offered_intents": offered_intents,
                "accepted_intent": accepted_intent,
                "emitted_at": self._clock_iso(),
            },
            producer=self.name,
        )

    def _make_active_learning_queue_overflow_event(
        self,
        request_id: str,
        queue_size: int,
        max_size: int,
    ) -> Message:
        return Message.new(
            topic=NLP_EVENT_V1,
            payload={
                "kind": "active_learning_queue_overflow",
                "producer": self.name,
                "request_id": request_id or None,
                "queue_size": queue_size,
                "max_size": max_size,
                "emitted_at": self._clock_iso(),
            },
            producer=self.name,
        )

    def _sanitize_feedback_payload(self, payload: dict[str, object]) -> dict[str, object]:
        offered = payload.get("did_you_mean_offered_intents")
        offered_intents = [
            str(item)
            for item in offered
            if isinstance(item, str)
        ] if isinstance(offered, list) else []
        accepted_intent_raw = payload.get("accepted_intent")
        accepted_intent = (
            str(accepted_intent_raw)
            if isinstance(accepted_intent_raw, str)
            else None
        )
        return {
            "request_id": str(payload.get("request_id", "")),
            "original_qa_correlation_id": str(payload.get("original_qa_correlation_id", "")),
            "did_you_mean_offered_intents": offered_intents,
            "accepted_intent": accepted_intent,
        }

    def _is_valid_feedback_payload(self, payload: dict[str, object]) -> bool:
        if not isinstance(payload.get("request_id"), str) or not payload["request_id"].strip():
            return False
        if not isinstance(payload.get("original_qa_correlation_id"), str) or not payload["original_qa_correlation_id"].strip():
            return False
        offered = payload.get("did_you_mean_offered_intents")
        if not isinstance(offered, list) or not offered:
            return False
        if not all(isinstance(item, str) and item.strip() for item in offered):
            return False
        accepted_intent = payload.get("accepted_intent")
        if accepted_intent is not None and not (isinstance(accepted_intent, str) and accepted_intent.strip()):
            return False
        return True

    def _enqueue_feedback(self, payload: dict[str, object], request_id: str) -> Message | None:
        if len(self._feedback_queue) >= self._feedback_queue.maxlen:
            overflow_event = self._make_active_learning_queue_overflow_event(
                request_id=request_id,
                queue_size=len(self._feedback_queue),
                max_size=self._feedback_queue.maxlen,
            )
            self._feedback_queue.append(payload)
            return overflow_event
        self._feedback_queue.append(payload)
        return None

    def _load_explicit_override_kinds(self) -> frozenset[str]:
        try:
            import yaml

            path = Path(__file__).resolve().parents[4] / "nlp" / "conversation" / "precedence.tr.yaml"
            if not path.exists():
                return frozenset()
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            return frozenset(
                kind
                for kind in data.get("explicit_override_kinds", [])
                if isinstance(kind, str)
            )
        except Exception:
            return frozenset()

    def _sanitize_context_entities(
        self,
        entities: list[dict[str, object]],
    ) -> list[dict[str, object]]:
        allowed_keys = {
            "span_start",
            "span_end",
            "kind",
            "canonical_id",
            "confidence",
            "lexicon_version",
            "source",
            "name",
        }
        sanitized: list[dict[str, object]] = []
        for entity in entities:
            if not isinstance(entity, dict):
                continue
            sanitized.append({k: v for k, v in entity.items() if k in allowed_keys})
        return sanitized

    def _merge_conversation_entities(
        self,
        previous_entities: list[dict[str, object]],
        current_entities: list[dict[str, object]],
    ) -> tuple[list[dict[str, object]], bool]:
        current_kinds = {
            str(entity.get("kind"))
            for entity in current_entities
            if isinstance(entity.get("kind"), str) and entity.get("canonical_id") is not None
        }
        if self._conversation_explicit_override_kinds:
            current_kinds &= self._conversation_explicit_override_kinds

        override_occurred = False
        previous_by_kind: dict[str, list[dict[str, object]]] = {}
        for entity in previous_entities:
            kind = entity.get("kind")
            if isinstance(kind, str):
                previous_by_kind.setdefault(kind, []).append(entity)

        for entity in current_entities:
            kind = entity.get("kind")
            if not isinstance(kind, str):
                continue
            canonical_id = entity.get("canonical_id")
            if canonical_id is None:
                continue
            for prior in previous_by_kind.get(kind, []):
                if prior.get("canonical_id") != canonical_id:
                    override_occurred = True
                    break
            if override_occurred:
                break

        merged_entities = [
            entity
            for entity in previous_entities
            if not (
                isinstance(entity.get("kind"), str)
                and entity.get("kind") in current_kinds
            )
        ]
        merged_entities.extend(current_entities)

        for entity in merged_entities:
            kind = entity.get("kind")
            canonical_id = entity.get("canonical_id")
            if not (isinstance(kind, str) and isinstance(canonical_id, str)):
                continue
            prior = previous_by_kind.get(kind, [])
            matching_prior = next(
                (item for item in prior if item.get("canonical_id") == canonical_id),
                None,
            )
            if matching_prior is None:
                continue
            for meta_key in ("fixture_state", "state_class", "last_resolved_state_at"):
                if meta_key not in entity and matching_prior.get(meta_key) is not None:
                    entity[meta_key] = matching_prior[meta_key]

        return merged_entities, override_occurred

    def _make_entity_state_change_disclosure(
        self,
        request_id: str,
        qa_correlation_id: str,
        conversation_id: str | None,
        entity: dict[str, object],
        new_state_class: str,
    ) -> Message:
        entity_name = str(entity.get("name") or entity.get("canonical_id") or entity.get("kind") or "ilgili")
        if not entity_name:
            entity_name = "ilgili"

        state_label_map = {
            "pre_match": "planlanan",
            "live": "canlı",
            "post_match": "sonuçlanmış",
            "postponed": "ertelendi veya askıya alındı",
            "cancelled": "iptal edildi",
        }
        state_label = state_label_map.get(new_state_class, "güncellenmiş")
        answer_text = f"Bahsettiğiniz {entity_name} maçının durumu değişmiş: şimdi {state_label}."
        return self._make_meta_answer(
            request_id=request_id,
            qa_correlation_id=qa_correlation_id,
            intent="meta.entity_state_changed",
            answer_text=answer_text,
            conversation_id=conversation_id,
        )

    def _update_entity_fixture_state(self, entity: dict[str, object], state: str) -> None:
        entity["fixture_state"] = state
        entity["state_class"] = _fixture_state_class(state)
        entity["last_resolved_state_at"] = self._clock_iso()

    def _clear_repeated_query_cache(self, conversation_id: str) -> None:
        history_metadata = self._conversation_store.load_metadata(conversation_id) or {}
        if "repeated_query_cached_answer" not in history_metadata:
            return
        history_metadata.pop("repeated_query_cached_answer", None)
        self._conversation_store.save_metadata(conversation_id, history_metadata)

    def _invalidate_entity_state_change_cache(
        self,
        entity: dict[str, object],
        conversation_id: str | None = None,
    ) -> None:
        if conversation_id:
            self._clear_repeated_query_cache(conversation_id)
        if self._cache_invalidator is not None:
            try:
                self._cache_invalidator(entity, conversation_id)
            except Exception as exc:
                self._log.warning(
                    "cache invalidation hook failed for entity %r: %s",
                    entity.get("canonical_id"),
                    exc,
                )

    def _should_refresh_entity_state(self, entity: dict[str, object]) -> bool:
        if not isinstance(entity.get("canonical_id"), str):
            return False
        if not isinstance(entity.get("kind"), str):
            return False
        if entity.get("kind") not in _FIXTURE_ENTITY_KINDS:
            return False
        if entity.get("fixture_state") is None:
            return False
        if entity.get("state_class") is None:
            return True
        if entity.get("last_resolved_state_at") is None:
            return True
        return _entity_state_stale(entity)

    def _refresh_referenced_entity_states(
        self,
        entities: list[dict[str, object]],
        request_id: str,
        qa_correlation_id: str,
        conversation_id: str | None,
        prelude_messages: list[Message],
        state_change_disclosure_messages: list[Message],
    ) -> None:
        for entity in entities:
            if not self._should_refresh_entity_state(entity):
                continue
            canonical_id = str(entity["canonical_id"])
            from common.config import cfg

            state, _, source, lookup_req = FixtureStateLookup.get(
                match_id=canonical_id,
                request_id=request_id,
                qa_correlation_id=qa_correlation_id,
                timeout_ms=int(cfg.nlp_fixture_state_lookup_timeout_ms),
            )
            if lookup_req is not None:
                prelude_messages.append(lookup_req)
            prior_state_class = str(entity.get("state_class") or "")
            self._update_entity_fixture_state(entity, state)
            new_state_class = entity.get("state_class")
            if isinstance(new_state_class, str) and new_state_class != prior_state_class:
                state_change_disclosure_messages.append(
                    self._make_entity_state_change_disclosure(
                        request_id=request_id,
                        qa_correlation_id=qa_correlation_id,
                        conversation_id=conversation_id,
                        entity=entity,
                        new_state_class=new_state_class,
                    )
                )
                self._invalidate_entity_state_change_cache(entity, conversation_id)

    def _use_cached_fixture_state(self, entity: dict[str, object]) -> bool:
        if entity.get("fixture_state") is None:
            return False
        if entity.get("state_class") is None or entity.get("last_resolved_state_at") is None:
            return False
        return not _entity_state_stale(entity)

    def _resolve_fixture_state_for_entity(
        self,
        entity: dict[str, object],
        request_id: str,
        qa_correlation_id: str,
        prelude_messages: list[Message],
    ) -> tuple[str, str, Message | None]:
        if self._use_cached_fixture_state(entity):
            return str(entity["fixture_state"]), "cache", None

        canonical_id = str(entity.get("canonical_id"))
        from common.config import cfg

        state, _, source, lookup_req = FixtureStateLookup.get(
            match_id=canonical_id,
            request_id=request_id,
            qa_correlation_id=qa_correlation_id,
            timeout_ms=int(cfg.nlp_fixture_state_lookup_timeout_ms),
        )
        self._update_entity_fixture_state(entity, state)
        if lookup_req is not None:
            prelude_messages.append(lookup_req)
        return state, source, lookup_req

    def _append_anaphora_mentions(
        self,
        previous_mentions: list[dict[str, object]],
        entities: list[dict[str, object]],
        turn_index: int,
        conversation_id: str | None = None,
        request_id: str = "",
    ) -> tuple[list[dict[str, object]], Message | None]:
        from common.config import cfg as _cfg

        now = self._clock_iso()
        pruned_mentions, evicted = self._prune_anaphora_mentions(
            list(previous_mentions),
            turn_index,
            now,
            _cfg,
        )
        for entity in entities:
            canonical_id = entity.get("canonical_id")
            kind = entity.get("kind")
            if not isinstance(canonical_id, str) or not isinstance(kind, str):
                continue
            mention: dict[str, object] = {
                "canonical_id": canonical_id,
                "kind": kind,
                "confidence": float(entity.get("confidence", 0.5)) if isinstance(entity.get("confidence"), (float, int)) else 0.5,
                "name": entity.get("name") or canonical_id,
                "mentioned_turn": turn_index,
                "mentioned_at": now,
                "mentioned_by": "user",
            }
            pruned_mentions.append(mention)
        event: Message | None = None
        if evicted and conversation_id:
            decision = self._anaphora_eviction_event_debouncer.decide(
                kind="anaphora_antecedent_evicted",
                subject=conversation_id,
                severity="info",
                reason="anaphora_antecedent_evicted",
            )
            if decision.emit:
                event = self._make_anaphora_antecedent_evicted_event(
                    request_id=request_id,
                    conversation_id=conversation_id,
                    evicted_count=len(evicted),
                    canonical_ids=[str(mention.get("canonical_id")) for mention in evicted if isinstance(mention.get("canonical_id"), str)],
                )
        return pruned_mentions, event

    def _prune_anaphora_mentions(
        self,
        mention_stack: list[dict[str, object]],
        current_turn_index: int,
        current_time_iso: str,
        cfg: object,
    ) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
        pruned: list[dict[str, object]] = []
        try:
            now_dt = _dt.datetime.fromisoformat(current_time_iso)
        except ValueError:
            now_dt = None

        lookback_turns = int(cfg.nlp_anaphora_lookback_turns)
        lookback_seconds = int(cfg.nlp_anaphora_lookback_seconds)
        evicted: list[dict[str, object]] = []

        for mention in mention_stack:
            mention_turn = mention.get("mentioned_turn")
            if isinstance(mention_turn, int) and lookback_turns >= 0:
                age_turns = current_turn_index - mention_turn
                if age_turns >= lookback_turns:
                    evicted.append(mention)
                    continue
            if now_dt is not None and isinstance(mention.get("mentioned_at"), str):
                try:
                    mention_at = _dt.datetime.fromisoformat(mention["mentioned_at"])
                    age_seconds = (now_dt - mention_at).total_seconds()
                except ValueError:
                    age_seconds = 0.0
                if age_seconds >= lookback_seconds:
                    evicted.append(mention)
                    continue
            pruned.append(mention)
        return pruned, evicted

    def _make_anaphora_disambiguation(
        self,
        request_id: str,
        intent: str,
        qa_correlation_id: str,
        conversation_id: str | None = None,
        mention_stack: list[dict[str, object]] | None = None,
    ) -> list[Message]:
        qa_correlation = self._new_id()
        tier_id_required = self._tier_id_required_for_intent(intent, cfg)
        names = []
        if mention_stack:
            names = [str(mention.get("name")) for mention in mention_stack if mention.get("name")]
            kinds = {str(mention.get("kind")) for mention in mention_stack if mention.get("kind")}
        else:
            kinds = set()
        if not names:
            recent_text = "önceki konuşmadaki varlıkları"
        else:
            recent_text = ", ".join(names[:3])

        if "venue" in kinds and kinds.intersection({"team", "player", "person", "coach", "referee"}):
            ask_text = "Hangi takımı / oyuncuyu ya da mekanı kastettiğinizi netleştirir misiniz? "
        elif "venue" in kinds:
            ask_text = "Hangi mekanı kastettiğinizi netleştirir misiniz? "
        else:
            ask_text = "Hangi takımı / oyuncuyu kastettiğinizi netleştirir misiniz? "

        answer_text = ask_text + f"Son konuşmada şu adlar geçti: {recent_text}."
        payload = {
            "request_id": request_id,
            "qa_correlation_id": qa_correlation,
            "answer_text": answer_text,
            "intent": intent,
            "kind": "disambiguation",
            "degraded": False,
            "degraded_reason": None,
            "tier_id_required": tier_id_required,
            "citations": [],
            "emitted_at": self._clock_iso(),
        }
        if conversation_id:
            payload["conversation_id"] = conversation_id
        return [Message.new(topic=QA_ANSWER_V1, payload=payload, producer=self.name)]

    def _make_verbal_noun_ambiguity_disambiguation(
        self,
        request_id: str,
        qa_correlation_id: str,
        conversation_id: str | None,
        entity_name: str,
    ) -> list[Message]:
        answer_text = (
            f"{entity_name}'ın oynaması mı, yoksa {entity_name} oynamak mı?"
        )
        payload = _make_qa_answer_payload(
            request_id=request_id,
            qa_correlation_id=qa_correlation_id,
            intent="data.fixture_lookup",
            kind="disambiguation",
            answer_text=answer_text,
            conversation_id=conversation_id,
            degraded=False,
            degraded_reason=None,
            emitted_at_utc=self._clock_iso(),
        )
        return [Message.new(topic=QA_ANSWER_V1, payload=payload, producer=self.name)]

    def _make_conversation_entity_overridden_event(
        self,
        request_id: str,
        conversation_id: str,
        overridden_kinds: list[str],
    ) -> Message | None:
        if not overridden_kinds:
            return None

        decision = self._conversation_entity_override_debouncer.decide(
            kind="conversation_entity_overridden",
            subject=conversation_id,
            severity="info",
            reason="conversation_entity_overridden",
        )
        if not decision.emit:
            return None
        return Message.new(
            topic=NLP_EVENT_V1,
            payload={
                "kind": "conversation_entity_overridden",
                "producer": self.name,
                "request_id": request_id or None,
                "conversation_id": conversation_id,
                "overridden_kinds": overridden_kinds,
                "emitted_at": self._clock_iso(),
            },
            producer=self.name,
        )

    def _normalize_intent_modifier(self, modifier: object | None) -> str:
        if modifier is None:
            return "none"
        if isinstance(modifier, (list, tuple)):
            return ",".join(str(item) for item in modifier)
        return str(modifier) if str(modifier).strip() else "none"

    def _make_repeated_query_signature(
        self,
        intent: str,
        entities: list[dict[str, object]],
        intent_modifier: object | None,
    ) -> str:
        return "|".join(
            [
                intent,
                _entity_hash(entities),
                self._normalize_intent_modifier(intent_modifier),
            ]
        )

    def _make_repeated_query_threshold_event(
        self,
        request_id: str,
        conversation_id: str,
        repeat_count: int,
        window_s: int,
    ) -> Message:
        return Message.new(
            topic=NLP_EVENT_V1,
            payload={
                "kind": "repeated_query_threshold_crossed",
                "producer": self.name,
                "request_id": request_id or None,
                "conversation_id": conversation_id,
                "repeat_count": repeat_count,
                "window_s": window_s,
                "emitted_at": self._clock_iso(),
            },
            producer=self.name,
        )

    def _make_repeated_query_summary_offer(
        self,
        request_id: str,
        qa_correlation_id: str,
        conversation_id: str | None = None,
    ) -> Message:
        tier_id_required = self._tier_id_required_for_intent("data.conversation_summary", cfg)
        payload = {
            "request_id": request_id,
            "qa_correlation_id": qa_correlation_id,
            "intent": "data.conversation_summary",
            "answer_text": "Bu konuyu birkaç kez sordunuz. Belki şunu denemek istersiniz: özet modu (yaz: 'özet').",
            "kind": "summary_offer",
            "degraded": False,
            "degraded_reason": None,
            "tier_id_required": tier_id_required,
            "citations": [],
            "emitted_at": self._clock_iso(),
        }
        if conversation_id:
            payload["conversation_id"] = conversation_id
        return Message.new(topic=QA_ANSWER_V1, payload=payload, producer=self.name)

    def _make_anaphora_antecedent_evicted_event(
        self,
        request_id: str,
        conversation_id: str,
        evicted_count: int,
        canonical_ids: list[str],
    ) -> Message:
        return Message.new(
            topic=NLP_EVENT_V1,
            payload={
                "kind": "anaphora_antecedent_evicted",
                "producer": self.name,
                "request_id": request_id or None,
                "conversation_id": conversation_id,
                "evicted_count": evicted_count,
                "evicted_canonical_ids": canonical_ids,
                "emitted_at": self._clock_iso(),
            },
            producer=self.name,
        )

    def _make_summary_too_large_answer(
        self,
        request_id: str,
        qa_correlation_id: str,
        intent: str,
        total_fixtures: int,
        league_ids: list[str] | None,
        conversation_id: str | None = None,
    ) -> Message:
        league_lines = []
        if league_ids:
            unique_ids = sorted({lid for lid in league_ids if lid})
            if unique_ids:
                league_lines = [f"- {league_id}: /lig/{league_id}" for league_id in unique_ids]
        answer_text = (
            f"Bu hafta toplam {total_fixtures} maç var; "
            "en öne çıkan özet yerine liste yanıtı sunuyorum. "
        )
        if league_lines:
            answer_text += "Lig listesi:\n" + "\n".join(league_lines)
        else:
            answer_text += "Lig listeleri için kaynaklara bakabilirsiniz."

        payload = _make_qa_answer_payload(
            request_id=request_id,
            qa_correlation_id=qa_correlation_id,
            intent=intent,
            kind="summary",
            answer_text=answer_text,
            degraded=True,
            degraded_reason="summary_hard_cap_exceeded",
            emitted_at_utc=self._clock_iso(),
        )
        if conversation_id:
            payload["conversation_id"] = conversation_id
        return Message.new(topic=QA_ANSWER_V1, payload=payload, producer=self.name)

    def handle(self, msg: Message) -> Iterable[Message]:
        """Route qa.intent.v1 to the appropriate downstream action.

        §10.6 backoff: predict.* intent without a resolvable fixture
        entity → emit qa.answer.v1{kind=disambiguation}.
        §10.6 multi-fixture: summary.* intent → fan-out N
        predict.request.v1 with shared summary_correlation_id.
        §10.6 idempotency: (qa_correlation_id, intent, entity_hash) dedup
        key suppresses replayed qa.intent.v1 messages within the window.
        All other routing paths remain stubs (future bullets).
        """
        from common.config import cfg  # local import avoids circular at module load

        payload = msg.payload
        if msg.topic == QA_FEEDBACK_V1:
            feedback_payload = self._sanitize_feedback_payload(payload)
            request_id = feedback_payload["request_id"]
            if not self._is_valid_feedback_payload(payload):
                return [
                    self._make_feedback_provenance_mismatch_event(
                        request_id=request_id,
                        offered_intents=feedback_payload["did_you_mean_offered_intents"],
                        accepted_intent=feedback_payload["accepted_intent"],
                    )
                ]
            offered_intents = feedback_payload["did_you_mean_offered_intents"]
            accepted_intent = feedback_payload["accepted_intent"]
            if accepted_intent is not None and accepted_intent not in offered_intents:
                return [
                    self._make_feedback_provenance_mismatch_event(
                        request_id=request_id,
                        offered_intents=offered_intents,
                        accepted_intent=accepted_intent,
                    )
                ]
            event = self._enqueue_feedback(feedback_payload, request_id=request_id)
            return [event] if event is not None else []

        intent: str = str(payload.get("intent", ""))
        entities: list[dict[str, object]] = [
            dict(entity)
            for entity in payload.get("entities", [])
            if isinstance(entity, dict)
        ]
        request_id: str = str(payload.get("request_id", ""))
        raw_conversation_id = payload.get("conversation_id")
        conversation_id = str(raw_conversation_id).strip() if isinstance(raw_conversation_id, str) else ""
        context_msg: Message | None = None

        override_event: Message | None = None
        correction_event: Message | None = None
        repeated_query_event: Message | None = None
        repeated_query_summary_offer: Message | None = None
        context_msg: Message | None = None
        prelude_messages: list[Message] = []
        state_change_disclosure_messages: list[Message] = []
        previous_entities: list[dict[str, object]] = []
        previous_anaphora_mentions: list[dict[str, object]] = []
        turn_index = 0
        qa_corr_in: str = str(payload.get("qa_correlation_id") or "")
        eviction_event_message: Message | None = None

        def _build_context_msg() -> Message | None:
            if not conversation_id:
                return None
            mention_stack, eviction_event = self._append_anaphora_mentions(
                previous_anaphora_mentions,
                entities,
                turn_index,
                conversation_id=conversation_id,
                request_id=request_id,
            )
            emitted_entities = self._sanitize_context_entities(entities)
            context_payload = {
                "schema_version": 1,
                "conversation_id": conversation_id,
                "turn_index": turn_index,
                "entities": emitted_entities,
                "intent": intent,
                "anaphora_mentions": mention_stack,
                "expires_at_utc": self._clock_iso(),
            }
            stored_context = dict(context_payload)
            stored_context["entities"] = entities
            self._conversation_store.save(stored_context)
            if eviction_event is not None:
                nonlocal eviction_event_message
                eviction_event_message = eviction_event
            return Message.new(
                topic=QA_CONTEXT_V1,
                payload=context_payload,
                producer=self.name,
            )

        def _with_context(results: Iterable[Message]) -> list[Message]:
            nonlocal context_msg
            out: list[Message] = []
            out.extend(prelude_messages)
            out.extend(state_change_disclosure_messages)
            out.extend(results)
            if override_event is not None:
                out.append(override_event)
            if correction_event is not None:
                out.append(correction_event)
            if repeated_query_event is not None:
                out.append(repeated_query_event)
            if repeated_query_summary_offer is not None:
                out.append(repeated_query_summary_offer)
            if context_msg is not None:
                out.append(context_msg)
            elif conversation_id:
                context_msg = _build_context_msg()
                if context_msg is not None:
                    out.append(context_msg)
            if eviction_event_message is not None:
                out.append(eviction_event_message)

            if conversation_id and signature:
                answer_messages = [m for m in out if m.topic == QA_ANSWER_V1]
                if answer_messages:
                    cached_payload = dict(answer_messages[-1].payload)
                    cached_payload.setdefault("cached_at", _utc_iso())
                    history_metadata["repeated_query_cached_answer"] = {
                        "signature": signature,
                        "cached_at": cached_payload["cached_at"],
                        "payload": cached_payload,
                    }
                    self._conversation_store.save_metadata(conversation_id, history_metadata)
            return _unwrap_qa_answer_downgrade_events(out)

        if conversation_id:
            context = self._conversation_store.load(conversation_id)
            turn_index = 0 if context is None else int(context.get("turn_index", -1)) + 1
            if turn_index >= int(cfg.nlp_conversation_max_turns):
                self._conversation_store.clear(conversation_id)
                context = None
                turn_index = 0

            previous_entities = list(context.get("entities", [])) if context else []
            previous_anaphora_mentions = list(context.get("anaphora_mentions", [])) if context else []

            merged_entities, override_occurred = self._merge_conversation_entities(
                previous_entities,
                entities,
            )
            if override_occurred:
                overridden_kinds = sorted({
                    str(entity.get("kind"))
                    for entity in entities
                    if isinstance(entity.get("kind"), str)
                })
                override_event = self._make_conversation_entity_overridden_event(
                    request_id=request_id,
                    conversation_id=conversation_id,
                    overridden_kinds=overridden_kinds,
                )
            entities = merged_entities
            self._refresh_referenced_entity_states(
                entities,
                request_id=request_id,
                qa_correlation_id=qa_corr_in,
                conversation_id=conversation_id or None,
                prelude_messages=prelude_messages,
                state_change_disclosure_messages=state_change_disclosure_messages,
            )

            history_metadata = self._conversation_store.load_metadata(conversation_id) or {}
            repeated_history = [
                item
                for item in history_metadata.get("repeated_query_history", [])
                if isinstance(item, dict)
            ]
            window_s = int(cfg.nlp_repeated_query_window_s)
            now_s = _dt.datetime.now(_dt.timezone.utc).timestamp()
            pruned_history: list[dict[str, object]] = []
            previous_same = 0
            signature = _make_repeated_query_signature(
                intent,
                entities,
                payload.get("intent_modifier"),
            )
            for item in repeated_history:
                ts = item.get("ts")
                if isinstance(ts, (int, float)) and now_s - float(ts) <= window_s:
                    pruned_history.append(item)
                    if item.get("signature") == signature:
                        previous_same += 1

            signature_map = history_metadata.get("repeated_query_signature_by_qa_corr_id")
            if not isinstance(signature_map, dict):
                signature_map = {}
            signature_map[qa_corr_in] = signature
            history_metadata["repeated_query_signature_by_qa_corr_id"] = signature_map

            cached_answer_message: Message | None = None
            if previous_same > 0:
                cached_entry = history_metadata.get("repeated_query_cached_answer")
                if isinstance(cached_entry, dict):
                    entry_signature = cached_entry.get("signature")
                    cached_at_iso = cached_entry.get("cached_at")
                    cached_payload = cached_entry.get("payload")
                    if (
                        entry_signature == signature
                        and isinstance(cached_at_iso, str)
                        and isinstance(cached_payload, dict)
                    ):
                        try:
                            cached_at_ts = _dt.datetime.fromisoformat(cached_at_iso).timestamp()
                        except ValueError:
                            cached_at_ts = None
                        if cached_at_ts is not None and now_s - cached_at_ts <= int(cfg.nlp_repeated_query_cache_max_age_s):
                            payload_copy = dict(cached_payload)
                            payload_copy["cached_at"] = cached_at_iso
                            cached_answer_message = Message.new(
                                topic=QA_ANSWER_V1,
                                payload=payload_copy,
                                producer=self.name,
                            )

            pruned_history.append({
                "signature": signature,
                "ts": now_s,
            })
            history_metadata["repeated_query_history"] = pruned_history
            history_metadata = _append_conversation_history_entry(
                history_metadata,
                intent,
                entities,
                turn_index,
            )
            self._conversation_store.save_metadata(conversation_id, history_metadata)

            threshold = int(cfg.nlp_repeated_query_threshold)
            summary_threshold = int(cfg.nlp_repeated_query_summary_threshold)
            current_count = previous_same + 1
            if current_count > summary_threshold:
                repeated_query_summary_offer = self._make_repeated_query_summary_offer(
                    request_id=request_id,
                    qa_correlation_id=qa_corr_in,
                    conversation_id=conversation_id or None,
                )
            if previous_same == threshold:
                repeated_query_event = self._make_repeated_query_threshold_event(
                    request_id=request_id,
                    conversation_id=conversation_id,
                    repeat_count=current_count,
                    window_s=window_s,
                )

            if cached_answer_message is not None:
                repeated_query_summary_offer = None
                return _with_context([cached_answer_message])

        # ── §10.6 idempotency — dedup before any routing ───────────────────
        dedup_key = f"{qa_corr_in or request_id}:{intent}:{_entity_hash(entities)}"
        if self._get_deduper().seen(dedup_key):  # type: ignore[union-attr]
            return _with_context([])

        skew_alert = self._maybe_make_classifier_extractor_skew_alert(
            request_id=request_id,
            qa_correlation_id=qa_corr_in,
            intent=intent,
            entities=entities,
            intent_confidence_raw=payload.get("intent_confidence"),
        )
        if skew_alert is not None:
            prelude_messages.append(skew_alert)

        # ── §10.6 multi-fixture fan-out ────────────────────────────────────
        if intent in _SUMMARY_INTENTS:
            fixture_entities = [
                e for e in entities
                if e.get("kind") in _FIXTURE_ENTITY_KINDS and e.get("canonical_id")
            ]
            if not fixture_entities:
                # No fixture anchors → disambiguation
                return _with_context(
                    self._make_disambiguation(
                        request_id,
                        intent,
                        cfg,
                        conversation_id=conversation_id or None,
                    )
                )
            max_f = cfg.nlp_summary_max_fixtures
            hard_cap = cfg.nlp_summary_max_fixtures_hard
            now = _dt.datetime.now(_dt.timezone.utc)
            sorted_fixtures = sorted(
                fixture_entities,
                key=lambda candidate: (
                    -_summary_salience_score(candidate, now=now),
                    str(candidate.get("canonical_id") or ""),
                ),
            )
            if len(sorted_fixtures) > hard_cap:
                league_ids = [str(entity.get("league_id") or "") for entity in sorted_fixtures]
                return _with_context([
                    self._make_summary_too_large_answer(
                        request_id=request_id,
                        qa_correlation_id=qa_corr_in,
                        intent=intent,
                        total_fixtures=len(sorted_fixtures),
                        league_ids=league_ids,
                        conversation_id=conversation_id or None,
                    )
                ])
            capped = sorted_fixtures[:max_f]
            summary_corr = self._new_id()
            out: list[Message] = []
            routed_payloads: list[dict[str, object]] = []
            for entity in capped:
                match_id = str(entity["canonical_id"])
                if self._use_cached_fixture_state(entity):
                    state = str(entity["fixture_state"])
                    source = "cache"
                else:
                    canonical_id = str(entity["canonical_id"])
                    state, _, source, lookup_req = FixtureStateLookup.get(
                        match_id=canonical_id,
                        request_id=request_id,
                        qa_correlation_id=qa_corr_in,
                        timeout_ms=int(cfg.nlp_fixture_state_lookup_timeout_ms),
                    )
                    if lookup_req is not None:
                        prelude_messages.append(lookup_req)
                    self._update_entity_fixture_state(entity, state)
                routed_payloads.append({
                    "match_id": match_id,
                    "market": "1x2",
                    "request_id": self._new_id(),
                    "qa_correlation_id": summary_corr,
                    "qa_request_id": request_id,
                    "summary_correlation_id": summary_corr,
                    "league_id": entity.get("league_id"),
                    "profile_id": None,
                    "emitted_at": self._clock_iso(),
                    "summary_original_count": len(sorted_fixtures),
                    "summary_top_n_by": _SUMMARY_TOP_N_BY,
                })
            expected_count = len(routed_payloads)
            for payload in routed_payloads:
                payload["summary_expected_count"] = expected_count
                out.append(
                    Message.new(
                        topic=PREDICT_REQUEST_V1,
                        payload=payload,
                        producer=self.name,
                    )
                )
            return _with_context(out)

        normalized_text = str(payload.get("normalized_text", ""))
        query_style = str(payload.get("query_style", "natural"))

        if conversation_id:
            correction_event = None
            correction_kind = _detect_conversation_correction(
                normalized_text,
                entities,
                previous_entities,
            )
            if correction_kind:
                if correction_kind == "restart":
                    self._conversation_store.clear(conversation_id)
                    previous_entities = []
                    previous_anaphora_mentions = []
                    entities = []
                    correction_event = _make_conversation_restarted_by_user_event(
                        request_id=request_id,
                        conversation_id=conversation_id,
                    )
                elif previous_entities:
                    prior_entity = previous_entities[-1]
                    prior_sha8 = _entity_sha8(prior_entity)
                    if correction_kind == "negation_of_prior":
                        previous_entities = previous_entities[:-1]
                        new_entity_sha8 = _entity_sha8(entities[-1]) if entities else ""
                    else:
                        previous_entities = previous_entities[:-1]
                        new_entity_sha8 = _entity_sha8(entities[-1]) if entities else ""
                    correction_event = _make_conversation_correction_applied_event(
                        request_id=request_id,
                        conversation_id=conversation_id,
                        correction_kind=correction_kind,
                        prior_entity_sha8=prior_sha8,
                        new_entity_sha8=new_entity_sha8,
                    )

            pronouns = detect_anaphora_pronouns(normalized_text)
            if pronouns:
                if len(pronouns) > 1 and not is_legal_anaphora_composition(pronouns):
                    return _with_context(self._make_anaphora_disambiguation(
                        request_id,
                        intent,
                        qa_corr_in,
                        conversation_id=conversation_id or None,
                        mention_stack=previous_anaphora_mentions,
                    ))

                resolved_antecedents: list[dict[str, object]] = []
                for pronoun in pronouns:
                    candidate, score = resolve_anaphora_pronoun(
                        pronoun,
                        previous_anaphora_mentions,
                        current_turn_index=turn_index,
                        current_time_iso=self._clock_iso(),
                    )
                    if candidate is None:
                        return _with_context(self._make_anaphora_disambiguation(
                            request_id,
                            intent,
                            qa_corr_in,
                            conversation_id=conversation_id or None,
                            mention_stack=previous_anaphora_mentions,
                        ))
                    resolved_antecedents.append(candidate)

                seen: set[str] = set()
                for resolved_antecedent in resolved_antecedents:
                    canonical_id = str(resolved_antecedent.get("canonical_id"))
                    if canonical_id in seen:
                        continue
                    seen.add(canonical_id)
                    entities.append({
                        "kind": resolved_antecedent["kind"],
                        "canonical_id": resolved_antecedent["canonical_id"],
                        "confidence": float(resolved_antecedent.get("confidence", 0.5)),
                    })

        pro_drop_event, pro_drop_entity, pro_drop_disambiguation = _maybe_make_pro_drop_resolution(
            request_id=request_id,
            qa_corr_in=qa_corr_in,
            intent=intent,
            entities=entities,
            payload=payload,
            previous_anaphora_mentions=previous_anaphora_mentions,
            conversation_id=conversation_id or None,
            turn_index=turn_index,
        )
        if pro_drop_event is not None and conversation_id:
            prelude_messages.append(pro_drop_event)
        if pro_drop_entity is not None:
            entities.append(pro_drop_entity)
        if pro_drop_disambiguation is not None:
            return _with_context([pro_drop_disambiguation])

        if query_style in {"search", "quoted_exact_search"}:
            return _with_context([
                self._make_meta_answer(
                    request_id,
                    qa_corr_in,
                    "meta.search_syntax_unsupported",
                    "Bu sistem doğal dilde sorulara yanıt veriyor; arama operatörleri (+, -, OR, AND, tırnak) şu an desteklenmiyor. Lütfen sorunuzu cümle olarak yazınız.",
                    conversation_id=conversation_id or None,
                )
            ])

        intent_modifier = payload.get("intent_modifier")
        has_sarcastic_modifier = (
            intent_modifier == "sarcastic"
            or (isinstance(intent_modifier, (list, tuple)) and "sarcastic" in intent_modifier)
        )
        if has_sarcastic_modifier and intent != "meta.opinion_unsupported":
            if intent.startswith("predict.") or intent == "data.sentiment":
                return _with_context([
                    self._make_meta_answer(
                        request_id,
                        qa_corr_in,
                        "meta.opinion_unsupported",
                        "Yorum içerir görünen ifadeler için cevap üretmiyorum; somut bir veri sorusu yöneltirseniz yardımcı olabilirim.",
                        conversation_id=conversation_id or None,
                    )
                ])

        conversational_meta_intent = classify_conversational_meta(normalized_text)
        if conversational_meta_intent is not None:
            answer_text = self._render_conversational_meta_answer_text(
                conversational_meta_intent,
                conversation_id or None,
                normalized_text,
            )
            return _with_context([
                self._make_meta_answer(
                    request_id,
                    qa_corr_in,
                    conversational_meta_intent,
                    answer_text,
                    conversation_id=conversation_id or None,
                )
            ])

        if any(
            isinstance(entity.get("syntactic_role"), str) and entity.get("syntactic_role") == "ambiguous"
            for entity in entities
        ):
            entity_name = "ilgili"
            ambiguous_entity = next(
                (entity for entity in entities if entity.get("syntactic_role") == "ambiguous"),
                None,
            )
            if isinstance(ambiguous_entity, dict):
                entity_name = str(ambiguous_entity.get("name") or ambiguous_entity.get("canonical_id") or "ilgili")
            return _with_context(
                self._make_verbal_noun_ambiguity_disambiguation(
                    request_id=request_id,
                    qa_correlation_id=qa_corr_in,
                    conversation_id=conversation_id or None,
                    entity_name=entity_name,
                )
            )

        # ── §10.22.5 composite-abbreviation match separator ────────────────
        if intent == "data.fixture_lookup":
            match = self._match_separator_team_pair(
                normalized_text,
                entities,
                cfg,
            )
            if match is None:
                match = self._match_word_bridge_team_pair(
                    normalized_text,
                    entities,
                    cfg,
                )
            if match is None:
                match = self._match_co_token_team_pair(
                    normalized_text,
                    entities,
                    cfg,
                )
            if match is not None:
                left_id, right_id = match
                fixture_filter = self._match_fixture_date_filter(
                    normalized_text,
                    entities,
                    left_id,
                    right_id,
                    cfg,
                )
                return _with_context(self._make_data_fixture_lookup_request(
                    request_id,
                    qa_corr_in,
                    left_id,
                    right_id,
                    fixture_filter=fixture_filter,
                ))

        routed_intent, conditional_result = self._apply_conditional_routing(
            intent,
            normalized_text,
            request_id,
            qa_corr_in,
            conversation_id or None,
        )
        if conditional_result is not None:
            return _with_context(conditional_result)
        intent = routed_intent

        intent = self._narrow_role_prefix_manager_intent(intent, entities)

        if intent.startswith("data.") and intent != "data.fixture_lookup":
            return _with_context(self._make_data_request(request_id, qa_corr_in, intent))

        quotative = detect_quotative_frame(normalized_text)
        if quotative is not None and quotative.confidence >= cfg.nlp_quotative_min_confidence:
            out: list[Message] = []
            out.append(self._make_quotative_frame_detected_event(request_id, qa_corr_in, quotative))
            if quotative.frame_class in ("direct_quote_marker", "attributed_source", "evidential_hearsay_compound"):
                out.extend(
                    self._make_data_request(
                        request_id,
                        qa_corr_in,
                        "data.attributed_claim",
                        extra_params={"quotative_negation": quotative.negated} if quotative.negated else None,
                    )
                )
                return _with_context(out)
            if quotative.frame_class == "social_media_attribution":
                return _with_context(out)

        aspectual = detect_aspectual_stack(normalized_text, max_depth=int(cfg.nlp_aspectual_stack_max_depth))
        if aspectual is not None and intent.startswith("predict."):
            out: list[Message] = []
            out.append(
                self._make_aspectual_stack_resolved_event(
                    request_id,
                    qa_corr_in,
                    aspectual.modality_class,
                    aspectual.confidence,
                )
            )
            if aspectual.modality_class == "epistemic_potential" and re.search(
                r"\b(olabilirmiş|kazanabilirmiş|gelebilirmiş|girebilirmiş|oynayabilirmiş)\b",
                normalized_text,
            ):
                out.append(
                    self._make_meta_answer(
                        request_id,
                        qa_corr_in,
                        "meta.unsupported",
                        "Bu cümle duyumlu potansiyel modalite içeriyor; destek veremem.",
                        conversation_id=conversation_id or None,
                    )
                )
                return _with_context(out)
            if aspectual.modality_class == "epistemic_potential" and self._contains_past_temporal_reference(
                normalized_text
            ):
                out.append(
                    self._make_meta_answer(
                        request_id,
                        qa_corr_in,
                        "meta.unsupported",
                        "Bu cümlede geçmiş bir zaman ifadesi ile potansiyel modalite çakışıyor; lütfen açık bir geçmiş sorgusu sorun.",
                        conversation_id=conversation_id or None,
                    )
                )
                return _with_context(out)
            if aspectual.modality_class == "counterfactual_past":
                out.append(
                    self._make_meta_answer(
                        request_id,
                        qa_corr_in,
                        "meta.counterfactual_past_unsupported",
                        "Olmuş bir maçın farklı sonuçlanmış halini öngöremem; geçmiş sonuçlar için sorabilirsiniz.",
                        conversation_id=conversation_id or None,
                    )
                )
                return _with_context(out)
            if aspectual.modality_class == "inferential_past":
                if self._has_resolved_fixture_entities(entities):
                    out.extend(
                        self._make_data_request(
                            request_id,
                            qa_corr_in,
                            "data.h2h",
                        )
                    )
                    return _with_context(out)
                return _with_context(self._make_disambiguation(request_id, intent, cfg, conversation_id=conversation_id or None))
            if aspectual.modality_class == "evidential_hearsay":
                if self._has_resolved_fixture_entities(entities):
                    out.extend(
                        self._make_data_request(
                            request_id,
                            qa_corr_in,
                            "data.h2h",
                        )
                    )
                    return _with_context(out)
                return _with_context(self._make_disambiguation(request_id, intent, cfg, conversation_id=conversation_id or None))
            if aspectual.modality_class == "obligative":
                out.append(
                    self._make_meta_answer(
                        request_id,
                        qa_corr_in,
                        "meta.advice_unsupported",
                        "Bahis tavsiyesi veremem; tahmin olasılıklarını paylaşabilirim; bahis bilgisi için yetkili sitelere başvurun.",
                        conversation_id=conversation_id or None,
                    )
                )
                return _with_context(out)
            if aspectual.modality_class == "future_perfect_evidential":
                out.append(
                    self._make_meta_answer(
                        request_id,
                        qa_corr_in,
                        "meta.counterfactual_probe",
                        "Olması durumunda nasıl olurdu sorusuna cevap veremem.",
                        conversation_id=conversation_id or None,
                    )
                )
                return _with_context(out)
            if aspectual.modality_class == "perfect_modal_potential":
                out.append(
                    self._make_meta_answer(
                        request_id,
                        qa_corr_in,
                        "meta.modality_unsupported",
                        "Bu tür modalite sorgusuna destek veremem.",
                        conversation_id=conversation_id or None,
                    )
                )
                return _with_context(out)
            if aspectual.modality_class == "imminent_progressive":
                out.extend(
                    self._make_data_request(
                        request_id,
                        qa_corr_in,
                        "data.live_state",
                    )
                )
                return _with_context(out)
            if aspectual.modality_class == "progressive_epistemic":
                out.extend(
                    self._make_data_request(
                        request_id,
                        qa_corr_in,
                        "data.fixture_lookup",
                        extra_params={"state": "in_play"},
                    )
                )
                return _with_context(out)
            if aspectual.modality_class == "future_relative_clause_attributive":
                out.extend(
                    self._make_data_request(
                        request_id,
                        qa_corr_in,
                        "data.lineup_probable",
                    )
                )
                return _with_context(out)

        routed_intent, conditional_result = self._apply_conditional_routing(
            intent,
            normalized_text,
            request_id,
            qa_corr_in,
            conversation_id or None,
        )
        if conditional_result is not None:
            return _with_context(conditional_result)
        intent = routed_intent

        inferred_team_entity = self._infer_team_from_venue(entities)
        if inferred_team_entity is not None:
            entities = [*entities, inferred_team_entity]

        # ── §10.6 deterministic backoff ────────────────────────────────────
        if intent.startswith("predict."):
            # Check for fixture-anchoring entities (team or competition).
            fixture_entities = [
                e for e in entities
                if e.get("kind") in _FIXTURE_ENTITY_KINDS and e.get("canonical_id")
            ]
            if not fixture_entities:
                # §10.6 deterministic backoff — never guess a headline match.
                return _with_context(self._make_disambiguation(request_id, intent, cfg, conversation_id=conversation_id or None))
            match_id = str(fixture_entities[0]["canonical_id"])
            if self._use_cached_fixture_state(fixture_entities[0]):
                state = str(fixture_entities[0]["fixture_state"])
                source = "cache"
                lookup_req = None
            else:
                canonical_id = str(fixture_entities[0]["canonical_id"])
                state, _, source, lookup_req = FixtureStateLookup.get(
                    match_id=canonical_id,
                    request_id=request_id,
                    qa_correlation_id=qa_corr_in,
                    timeout_ms=int(cfg.nlp_fixture_state_lookup_timeout_ms),
                )
                self._update_entity_fixture_state(fixture_entities[0], state)
                if lookup_req is not None:
                    prelude_messages.append(lookup_req)
            route = None
            if source != "fallback":
                route = _load_fixture_state_routing().get(state)
            if route is None:
                route = {"predict": "normal", "data": "normal", "summary": "normal"}

            if route.get("predict") == "h2h":
                return _with_context(
                    self._make_data_request(
                        request_id,
                        qa_corr_in,
                        "data.h2h",
                        extra_params={"match_id": match_id},
                    )
                )

            if route.get("predict") == "refuse":
                data_route = route.get("data")
                if data_route == "fixture_lookup":
                    data_requests = self._make_data_request(
                        request_id,
                        qa_corr_in,
                        "data.fixture_lookup",
                        extra_params={"match_id": match_id},
                    )
                else:
                    extra_params: dict[str, object] = {"match_id": match_id}
                    if state == FixtureState.UNKNOWN.value:
                        extra_params["degraded"] = True
                    data_requests = self._make_data_request(
                        request_id,
                        qa_corr_in,
                        "data.live_state",
                        extra_params=extra_params,
                    )
                intent_name, answer_text, degraded, degraded_reason = _fixture_state_refusal_meta(state)
                return _with_context([
                    *data_requests,
                    self._make_meta_answer(
                        request_id,
                        qa_corr_in,
                        intent_name,
                        answer_text,
                        conversation_id=conversation_id or None,
                        degraded=degraded,
                        degraded_reason=degraded_reason,
                    ),
                ])

            if intent == "predict.match_outcome.comparative":
                fixture_entities = [
                    e for e in entities
                    if e.get("kind") in _FIXTURE_ENTITY_KINDS and e.get("canonical_id")
                ]
                if len(fixture_entities) < 2:
                    return _with_context(
                        self._make_disambiguation(
                            request_id,
                            intent,
                            cfg,
                            conversation_id=conversation_id or None,
                        )
                    )
                max_f = len(fixture_entities)
                summary_corr = self._new_id()
                out = []
                expected_count = len(fixture_entities)
                for entity in fixture_entities:
                    match_id = str(entity["canonical_id"])
                    if self._use_cached_fixture_state(entity):
                        state = str(entity["fixture_state"])
                        source = "cache"
                        lookup_req = None
                    else:
                        canonical_id = str(entity["canonical_id"])
                        state, _, source, lookup_req = FixtureStateLookup.get(
                            match_id=canonical_id,
                            request_id=request_id,
                            qa_correlation_id=qa_corr_in,
                            timeout_ms=int(cfg.nlp_fixture_state_lookup_timeout_ms),
                        )
                        self._update_entity_fixture_state(entity, state)
                        if lookup_req is not None:
                            prelude_messages.append(lookup_req)
                    payload = {
                        "match_id": match_id,
                        "market": "1x2",
                        "request_id": self._new_id(),
                        "qa_correlation_id": qa_corr_in,
                        "qa_request_id": request_id,
                        "summary_correlation_id": summary_corr,
                        "summary_expected_count": expected_count,
                        "summary_original_count": expected_count,
                        "summary_top_n_by": _SUMMARY_TOP_N_BY,
                        "emitted_at": self._clock_iso(),
                    }
                    out.append(
                        Message.new(
                            topic=PREDICT_REQUEST_V1,
                            payload=payload,
                            producer=self.name,
                        )
                    )
                return _with_context(out)

            out: list[Message] = []
            out.append(
                Message.new(
                    topic=PREDICT_REQUEST_V1,
                    payload={
                        "match_id": match_id,
                        "market": "1x2",
                        "request_id": self._new_id(),
                        "qa_correlation_id": qa_corr_in,
                        "qa_request_id": request_id,
                        "emitted_at": self._clock_iso(),
                    },
                    producer=self.name,
                )
            )
            return _with_context(out)

        # data.*, meta.*, and resolvable predict.* routing: future bullets.
        return _with_context([])

    def _infer_team_from_venue(self, entities: list[dict[str, object]]) -> dict[str, object] | None:
        if any(
            isinstance(entity.get("kind"), str)
            and entity["kind"] in _FIXTURE_ENTITY_KINDS
            for entity in entities
        ):
            return None
        if any(
            isinstance(entity.get("kind"), str)
            and entity["kind"] == "team"
            for entity in entities
        ):
            return None

        for entity in entities:
            if (
                isinstance(entity.get("kind"), str)
                and entity["kind"] == "venue"
                and isinstance(entity.get("canonical_id"), str)
                and entity["canonical_id"].strip()
            ):
                team_id = _resolve_team_canonical_id_from_venue_slug(entity["canonical_id"].strip())
                if team_id is None:
                    return None
                confidence = float(cfg.nlp_venue_inferred_team_confidence_cap)
                if confidence < 0.0:
                    confidence = 0.0
                return {
                    "span_start": int(entity.get("span_start") or 0),
                    "span_end": int(entity.get("span_end") or 0),
                    "kind": "team",
                    "canonical_id": team_id,
                    "confidence": confidence,
                    "lexicon_version": str(entity.get("lexicon_version") or ""),
                    "source": "venue_inference",
                }
        return None

    def _make_disambiguation(
        self,
        request_id: str,
        intent: str,
        cfg: object,
        conversation_id: str | None = None,
    ) -> list[Message]:
        """Emit qa.answer.v1{kind=disambiguation} (shared helper)."""
        qa_correlation_id = self._new_id()
        tier_id_required = self._tier_id_required_for_intent(intent, cfg)
        window_h = getattr(cfg, "nlp_default_fixture_window_h", 48)
        answer_text = (
            f"Hangi maç için tahmin istiyorsunuz? "
            f"Önümüzdeki {window_h} saat içindeki maçları listeleyebilirim."
        )
        payload = _make_qa_answer_payload(
            request_id=request_id,
            qa_correlation_id=qa_correlation_id,
            intent=intent,
            kind="disambiguation",
            answer_text=answer_text,
            tier_id_required=tier_id_required,
            conversation_id=conversation_id,
            emitted_at_utc=self._clock_iso(),
            schema_version=2,
        )
        return [
            Message.new(
                topic=QA_ANSWER_V1,
                payload=payload,
                producer=self.name,
            )
        ]

    def _get_intent_required_entity_spec(self, intent: str) -> list[dict[str, int]]:
        all_specs = _load_intent_required_entity_map()
        return all_specs.get(intent, [])

    def _compute_classifier_extractor_skew(
        self,
        intent: str,
        entities: list[dict[str, object]],
        intent_confidence_raw: object | None,
    ) -> float:
        try:
            intent_confidence = float(intent_confidence_raw) if intent_confidence_raw is not None else 0.0
        except (TypeError, ValueError):
            intent_confidence = 0.0
        required = self._get_intent_required_entity_spec(intent)
        if not required:
            return 0.0

        entity_counts = Counter(
            str(entity.get("kind"))
            for entity in entities
            if isinstance(entity.get("kind"), str)
        )

        total_required = 0
        resolved_required = 0
        for entry in required:
            kind = entry["kind"]
            count = entry["count"]
            total_required += count
            if "_or_" in kind:
                if any(
                    any(part in actual_kind for part in kind.split("_or_") if part)
                    for actual_kind in entity_counts
                ):
                    resolved_required += count
            else:
                resolved_required += min(entity_counts.get(kind, 0), count)

        if total_required == 0:
            return 0.0

        ratio = resolved_required / float(total_required)
        skew = intent_confidence - ratio
        return float(skew) if skew > 0.0 else 0.0

    def _maybe_make_classifier_extractor_skew_alert(
        self,
        request_id: str,
        qa_correlation_id: str,
        intent: str,
        entities: list[dict[str, object]],
        intent_confidence_raw: object | None,
    ) -> Message | None:
        skew = self._compute_classifier_extractor_skew(
            intent,
            entities,
            intent_confidence_raw,
        )
        if NLP_CLASSIFIER_EXTRACTOR_SKEW is not None:
            try:
                NLP_CLASSIFIER_EXTRACTOR_SKEW.labels(intent=intent).observe(skew)
            except Exception:
                pass

        now_ts = _dt.datetime.now(_dt.timezone.utc).timestamp()
        window_s = int(cfg.nlp_skew_window_s)
        min_requests = int(cfg.nlp_skew_alert_min_requests)
        with self._skew_samples_lock:
            samples = self._skew_samples_by_intent.setdefault(intent, deque())
            while samples and now_ts - samples[0][0] > window_s:
                samples.popleft()
            samples.append((now_ts, skew))
            if len(samples) < min_requests:
                return None
            skew_values = sorted(value for _, value in samples)

        p95_index = max(0, min(len(skew_values) - 1, math.ceil(0.95 * len(skew_values)) - 1))
        p95_skew = skew_values[p95_index]
        if p95_skew <= float(cfg.nlp_skew_alert_p95):
            return None

        decision = self._skew_alert_debouncer.decide(
            kind="nlp_classifier_extractor_skew_high",
            subject=intent,
            severity="warn",
            reason=(
                f"Classifier/extractor skew p95={p95_skew:.3f} over {len(skew_values)} "
                f"requests in {window_s}s for intent={intent}."
            ),
        )
        if not decision.emit:
            return None

        payload = {
            "schema_version": 1,
            "alert_id": self._new_id(),
            "kind": "nlp_classifier_extractor_skew_high",
            "severity": "warn",
            "source": self.name,
            "reason": decision.reason,
            "subject": intent,
            "request_id": request_id or None,
            "qa_correlation_id": qa_correlation_id or None,
            "details": {
                "skew": round(skew, 6),
                "p95_skew": round(p95_skew, 6),
                "window_s": window_s,
                "request_count": len(skew_values),
            },
            "emitted_at": self._clock_iso(),
        }
        return Message.new(topic=NLP_ALERT_V1, payload=payload, producer=self.name)

    def _narrow_role_prefix_manager_intent(
        self,
        intent: str,
        entities: list[dict[str, object]],
    ) -> str:
        if intent != "data.player_card_risk":
            return intent
        for entity in entities:
            if (
                isinstance(entity.get("kind"), str)
                and entity["kind"] == "role_prefix"
                and str(entity.get("canonical_id", "")) == "manager"
            ):
                return "data.team_management_state"
        return intent

    def _apply_conditional_routing(
        self,
        intent: str,
        normalized_text: str,
        request_id: str,
        qa_correlation_id: str,
        conversation_id: str | None = None,
    ) -> tuple[str, list[Message] | None]:
        """Apply the Phase 10.30 conditional tense routing matrix."""
        modifier, tense = detect_conditional_modifier(normalized_text.split())
        conditional_modifier = (
            modifier == "conditional"
            or (isinstance(modifier, tuple) and len(modifier) > 0 and modifier[0] == "conditional")
        )
        comparative_modifier = (
            modifier == "comparative"
            or (
                isinstance(modifier, (list, tuple))
                and "comparative" in modifier
                and "conditional" not in modifier
            )
            or (
                intent == "predict.match_outcome"
                and detect_coordinating_particles(normalized_text)
            )
        )

        if conditional_modifier:
            if tense == "past":
                return intent, [
                    self._make_meta_answer(
                        request_id,
                        qa_correlation_id,
                        "meta.counterfactual_past_unsupported",
                        "Bir geçmiş varsayımı sorusuna yanıt veremiyorum.",
                        conversation_id=conversation_id,
                    )
                ]

            if tense == "future" and intent == "predict.match_outcome":
                return "predict.match_outcome.conditional", None

            if tense == "present" and intent == "predict.match_outcome":
                return "data.lineup_probable", None

        if comparative_modifier and intent == "predict.match_outcome":
            return "predict.match_outcome.comparative", None

        return intent, None

    def _make_quotative_frame_detected_event(
        self,
        request_id: str,
        qa_correlation_id: str,
        detection: "QuotativeDetection",
    ) -> Message:
        """Emit an NLP event when a quotative frame is detected."""
        return Message.new(
            topic=NLP_EVENT_V1,
            payload={
                "kind": "quotative_frame_detected",
                "producer": self.name,
                "request_id": request_id,
                "qa_correlation_id": qa_correlation_id or self._new_id(),
                "frame_class": detection.frame_class,
                "confidence": detection.confidence,
                "negated": detection.negated,
                "emitted_at": self._clock_iso(),
            },
            producer=self.name,
        )

    def _make_aspectual_stack_resolved_event(
        self,
        request_id: str,
        qa_correlation_id: str,
        decision: str,
        confidence: float,
    ) -> Message:
        return Message.new(
            topic=NLP_EVENT_V1,
            payload={
                "kind": "aspectual_stack_resolved",
                "producer": self.name,
                "request_id": request_id,
                "qa_correlation_id": qa_correlation_id or self._new_id(),
                "aspectual_stack_decision": decision,
                "confidence": confidence,
                "emitted_at": self._clock_iso(),
            },
            producer=self.name,
        )

    def _make_meta_answer(
        self,
        request_id: str,
        qa_correlation_id: str,
        intent: str,
        answer_text: str,
        conversation_id: str | None = None,
        parts: list[dict[str, object]] | None = None,
        degraded: bool = False,
        degraded_reason: str | None = None,
        request_metadata: dict[str, object] | None = None,
    ) -> Message:
        if request_metadata is None:
            request_metadata = getattr(self, "_current_request_metadata", None)
            if not isinstance(request_metadata, dict):
                request_metadata = None
        qa_corr = qa_correlation_id or self._new_id()
        kind = intent.split(".", 1)[1]
        payload = _make_qa_answer_payload(
            request_id=request_id,
            qa_correlation_id=qa_corr,
            intent=intent,
            kind=kind,
            answer_text=answer_text,
            tier_id_required=None,
            conversation_id=conversation_id,
            parts=parts,
            degraded=degraded,
            degraded_reason=degraded_reason,
            request_metadata=request_metadata,
            emitted_at_utc=self._clock_iso(),
        )
        return Message.new(
            topic=QA_ANSWER_V1,
            payload=payload,
            producer=self.name,
        )

    def _load_system_capabilities_text(self) -> str:
        template_path = str(cfg.nlp_system_capability_template_path or "").strip()
        if template_path:
            path = Path(template_path)
            try:
                return path.read_text(encoding="utf-8").strip()
            except OSError:
                pass
        return "Bu sistem futbol maçları, kadroları, skorları ve tahminleri hakkında Türkçe doğal dil yanıtları sunar."

    def _load_last_answer_text(self, conversation_id: str | None) -> str | None:
        if not conversation_id:
            return None
        history_metadata = self._conversation_store.load_metadata(conversation_id) or {}
        last_answer_text = history_metadata.get("last_qa_answer_text")
        if isinstance(last_answer_text, str) and last_answer_text:
            return last_answer_text
        return None

    def _render_conversational_meta_answer_text(
        self,
        intent: str,
        conversation_id: str | None,
        normalized_text: str,
    ) -> str:
        env = build_environment(user_text_for_guard=normalized_text)
        if intent == "meta.system_capabilities":
            return render(
                "meta.system_capabilities.tr.j2",
                {"system_capabilities": self._load_system_capabilities_text()},
                env=env,
            )

        if intent == "meta.user_data_disclosure":
            return render(
                "meta.user_data_disclosure.tr.j2",
                {},
                env=env,
            )

        if intent == "meta.conversation_history":
            history_metadata = self._conversation_store.load_metadata(conversation_id or "") or {}
            history = history_metadata.get("conversation_history")
            if not isinstance(history, list):
                history = []
            safe_history = [
                entry for entry in history
                if isinstance(entry, dict)
            ]
            return render(
                "meta.conversation_history.tr.j2",
                {"history": safe_history},
                env=env,
            )

        if intent == "meta.last_answer_explain":
            last_answer_text = self._load_last_answer_text(conversation_id)
            return render(
                "meta.last_answer_explain.explained.tr.j2",
                {"last_answer_text": last_answer_text or ""},
                env=env,
            )

        if intent == "meta.fragment_detected":
            return render(
                "meta.fragment_detected.tr.j2",
                {"user_text": normalized_text},
                env=env,
            )

        if intent == "meta.rhetorical_dismissive":
            return render(
                "meta.rhetorical_dismissive.tr.j2",
                {},
                env=env,
            )

        if intent in ("meta.opinion_unsupported", "meta.opinion_request"):
            return render(
                "meta.opinion_unsupported.tr.j2",
                {},
                env=env,
            )

        if intent == "meta.system_self":
            return render(
                "meta.system_self.tr.j2",
                {"system_capabilities": self._load_system_capabilities_text()},
                env=env,
            )

        return render("meta.unsupported", {}, env=env)

    def _make_fixture_state_flipped_during_rpc_event(
        self,
        request_id: str,
        qa_correlation_id: str,
        match_id: str,
        prior_state: str,
        new_state: str,
        rpc_age_ms: int,
    ) -> Message:
        payload = {
            "kind": "fixture_state_flipped_during_rpc",
            "producer": self.name,
            "request_id": request_id or None,
            "qa_correlation_id": qa_correlation_id or None,
            "match_id": match_id,
            "prior_state": prior_state,
            "new_state": new_state,
            "rpc_age_ms": rpc_age_ms,
            "emitted_at": self._clock_iso(),
        }
        return Message.new(topic=NLP_EVENT_V1, payload=payload, producer=self.name)

    def _make_data_request(
        self,
        request_id: str,
        qa_correlation_id: str,
        intent: str,
        extra_params: dict[str, object] | None = None,
    ) -> list[Message]:
        qa_corr = qa_correlation_id or self._new_id()
        kind = intent.split(".", 1)[1]
        params: dict[str, object] = {"intent": intent}
        if extra_params:
            params.update(extra_params)
        return [
            Message.new(
                topic=DATA_REQUEST_V1,
                payload={
                    "request_id": self._new_id(),
                    "qa_request_id": request_id,
                    "qa_correlation_id": qa_corr,
                    "kind": kind,
                    "params": params,
                    "emitted_at": self._clock_iso(),
                },
                producer=self.name,
            )
        ]

    def _match_separator_team_pair(
        self,
        normalized_text: str,
        entities: list[dict],
        cfg: object,
    ) -> tuple[str, str] | None:
        """Detect two resolved team entities separated by a match separator token."""
        team_entities = sorted(
            (
                e
                for e in entities
                if e.get("kind") == "team" and e.get("canonical_id")
            ),
            key=lambda ent: int(ent.get("span_start", 0)),
        )
        separator_re = re.compile(cfg.nlp_match_separator_pattern, re.UNICODE)
        for left, right in zip(team_entities, team_entities[1:]):
            if not isinstance(left.get("span_end"), int) or not isinstance(
                right.get("span_start"), int
            ):
                continue
            separator = normalized_text[left["span_end"] : right["span_start"]].strip()
            if separator and separator_re.fullmatch(separator):
                return str(left["canonical_id"]), str(right["canonical_id"])
        return None

    def _has_resolved_fixture_entities(self, entities: list[dict[str, object]]) -> bool:
        return any(
            e.get("kind") in _FIXTURE_ENTITY_KINDS
            and isinstance(e.get("canonical_id"), str)
            and e["canonical_id"].strip()
            for e in entities
        )

    def _contains_past_temporal_reference(self, normalized_text: str) -> bool:
        return bool(
            re.search(
                r"\b(dün|dünden|geçen hafta|geçen ay|geçen yıl|önceki hafta|önceki sezon|önceki maç|önceki)\b",
                normalized_text,
                flags=re.IGNORECASE,
            )
        )

    def _match_word_bridge_team_pair(
        self,
        normalized_text: str,
        entities: list[dict],
        cfg: object,
    ) -> tuple[str, str] | None:
        """Detect team pairs joined by bridge words (§10.22.7 word-bridge parsing)."""
        team_entities = sorted(
            (
                e
                for e in entities
                if e.get("kind") == "team" and e.get("canonical_id")
            ),
            key=lambda ent: int(ent.get("span_start", 0)),
        )
        if len(team_entities) < 2:
            return None

        bridges = getattr(cfg, "nlp_match_word_bridges", [])
        if not bridges:
            return None

        for left, right in zip(team_entities, team_entities[1:]):
            separator = normalized_text[left["span_end"] : right["span_start"]].strip()
            if not separator:
                continue
            for bridge in bridges:
                if re.fullmatch(
                    rf"\W*{re.escape(bridge)}\W*",
                    separator,
                    flags=re.UNICODE | re.IGNORECASE,
                ):
                    return str(left["canonical_id"]), str(right["canonical_id"])
        return None

    def _token_spans(self, normalized_text: str) -> list[tuple[str, int, int]]:
        tokens: list[tuple[str, int, int]] = []
        cursor = 0
        for token in normalized_text.split():
            start = normalized_text.find(token, cursor)
            if start == -1:
                continue
            tokens.append((token, start, start + len(token)))
            cursor = start + len(token)
        return tokens

    def _entity_token_interval(
        self,
        entity: dict,
        token_spans: list[tuple[str, int, int]],
    ) -> tuple[int | None, int | None]:
        start_index = None
        end_index = None
        for index, (_token, start, end) in enumerate(token_spans):
            if start_index is None and start == entity["span_start"]:
                start_index = index
            if end_index is None and end == entity["span_end"]:
                end_index = index
            if start_index is not None and end_index is not None:
                break
        if start_index is None:
            for index, (_token, start, end) in enumerate(token_spans):
                if start <= entity["span_start"] < end:
                    start_index = index
                    break
        if end_index is None:
            for index, (_token, start, end) in enumerate(token_spans):
                if start < entity["span_end"] <= end:
                    end_index = index
                    break
        if start_index is None or end_index is None:
            return None, None
        return start_index, end_index + 1

    def _match_co_token_team_pair(
        self,
        normalized_text: str,
        entities: list[dict],
        cfg: object,
    ) -> tuple[str, str] | None:
        """Detect team pairs by co-occurring match tokens (§10.22.7 adjacency rule)."""
        team_entities = sorted(
            (
                e
                for e in entities
                if e.get("kind") == "team" and e.get("canonical_id")
            ),
            key=lambda ent: int(ent.get("span_start", 0)),
        )
        if len(team_entities) < 2:
            return None

        co_tokens = {tok.lower() for tok in getattr(cfg, "nlp_match_co_tokens", [])}
        if not co_tokens:
            return None

        token_spans = self._token_spans(normalized_text)
        for left, right in zip(team_entities, team_entities[1:]):
            if re.search(r"[.!?]", normalized_text[left["span_end"] : right["span_start"]]):
                continue

            left_start, left_end = self._entity_token_interval(left, token_spans)
            right_start, right_end = self._entity_token_interval(right, token_spans)
            if left_start is None or right_start is None or right_end is None:
                continue

            for index, (token, _start, _end) in enumerate(token_spans):
                if token.lower() not in co_tokens:
                    continue
                if left_end <= index < right_start:
                    return str(left["canonical_id"]), str(right["canonical_id"])
                if index < left_start:
                    distance = left_start - index - 1
                elif index >= right_end:
                    distance = index - right_end
                else:
                    continue
                if distance <= getattr(cfg, "nlp_match_adjacency_radius", 4):
                    return str(left["canonical_id"]), str(right["canonical_id"])
        return None

    def _match_fixture_date_filter(
        self,
        normalized_text: str,
        entities: list[dict],
        team_a_id: str,
        team_b_id: str,
        cfg: object,
    ) -> dict[str, str] | None:
        """Bind a nearby resolved date/time entity to a fixture lookup request."""
        team_pair = {team_a_id, team_b_id}
        team_entities = sorted(
            (
                e
                for e in entities
                if e.get("kind") == "team"
                and e.get("canonical_id") in team_pair
            ),
            key=lambda ent: int(ent.get("span_start", 0)),
        )
        if len(team_entities) != 2:
            return None

        date_entities = [
            e
            for e in entities
            if e.get("kind") in ("date", "time") and e.get("canonical_id")
        ]
        if not date_entities:
            return None

        token_spans = self._token_spans(normalized_text)
        left_start, left_end = self._entity_token_interval(team_entities[0], token_spans)
        right_start, right_end = self._entity_token_interval(team_entities[1], token_spans)
        if left_start is None or right_start is None or right_end is None:
            return None

        radius = getattr(cfg, "nlp_fixture_date_adjacency_radius", 8)
        fixture_filter: dict[str, str] = {}
        for entity in date_entities:
            date_start, date_end = self._entity_token_interval(entity, token_spans)
            if date_start is None or date_end is None:
                continue
            if date_end <= left_start:
                gap = left_start - date_end
            elif date_start >= right_end:
                gap = date_start - right_end
            else:
                gap = 0
            if gap <= radius:
                kind = entity["kind"]
                fixture_filter[kind] = str(entity["canonical_id"])
        return fixture_filter or None

    def _make_data_fixture_lookup_request(
        self,
        request_id: str,
        qa_correlation_id: str,
        team_a_id: str,
        team_b_id: str,
        fixture_filter: dict[str, str] | None = None,
    ) -> list[Message]:
        """Emit a data.request.v1 for a composite match lookup slot."""
        qa_correlation_id = qa_correlation_id or self._new_id()
        params: dict[str, object] = {
            "team_pair": sorted([team_a_id, team_b_id])
        }
        if fixture_filter is not None:
            params["fixture_filter"] = fixture_filter
        return [
            Message.new(
                topic=DATA_REQUEST_V1,
                payload={
                    "request_id": self._new_id(),
                    "qa_request_id": request_id,
                    "qa_correlation_id": qa_correlation_id,
                    "kind": "fixture_lookup",
                    "params": params,
                    "emitted_at": self._clock_iso(),
                },
                producer=self.name,
            )
        ]

    def _make_data_request(
        self,
        request_id: str,
        qa_correlation_id: str,
        intent: str,
        extra_params: dict[str, object] | None = None,
    ) -> list[Message]:
        """Emit a generic data.request.v1 for any data.* intent."""
        qa_corr = qa_correlation_id or self._new_id()
        kind = intent.split(".", 1)[1]
        params: dict[str, object] = {"intent": intent}
        if extra_params:
            params.update(extra_params)
        return [
            Message.new(
                topic=DATA_REQUEST_V1,
                payload={
                    "request_id": self._new_id(),
                    "qa_request_id": request_id,
                    "qa_correlation_id": qa_corr,
                    "kind": kind,
                    "params": params,
                    "emitted_at": self._clock_iso(),
                },
                producer=self.name,
            )
        ]

    def _tier_id_required_for_intent(self, intent: str, cfg: object) -> str | None:
        """Resolve tier label from cfg.nlp_intent_tier_map using intent only."""
        tier_map = getattr(cfg, "nlp_intent_tier_map", {})
        if not isinstance(tier_map, dict):
            return None
        tier_value = tier_map.get(intent)
        if tier_value is None:
            return None
        normalized = str(tier_value).strip()
        return normalized or None

    def _check_backpressure(self, queue_depth: int) -> bool:
        """§10.19 backpressure stub: returns True when pressure is active.

        When qa.intent.v1 queue depth > cfg.nlp_queue_pressure_threshold:
        (a) disable humanizer (template-only mode) for cfg.nlp_pressure_humanize_off_s;
        (b) widen nlp_intent_cache_ttl_s 2x;
        (c) emit nlp.alert.v1{kind=nlp_queue_pressure, severity=warn} (debounced 60s).

        Full implementation lands in subsequent §10.19 bullets. This stub
        returns True when queue_depth exceeds the threshold, False otherwise.
        """
        from common.config import cfg

        threshold = cfg.nlp_queue_pressure_threshold
        return queue_depth > threshold


class NlpAnswerAgent:
    """Phase 10 §10.6–§10.7 skeleton: dispatch + answer assembly.

    Subscribes to ``qa.intent.v1`` (structured intent) and
    ``predict.approved.v1`` (Phase 6 proofreader-gated; NEVER
    ``predict.final`` — the unvetted candidate).  Publishes the
    Turkish-language answer on ``qa.answer.v1``.

    §10.6 multi-fixture aggregation: when ``predict.approved.v1``
    carries ``summary_correlation_id``, the agent accumulates arrivals
    up to ``expected_count`` within ``cfg.nlp_summary_aggregation_timeout_ms``.
    On completion *or* timeout it emits a single ``qa.answer.v1``
    (degraded=True with "X / Y maç hazır" note if under-collected).
    """

    name = "nlp.answer.v1"
    subscribes = [QA_INTENT_V1, PREDICT_APPROVED, PREDICT_CANCEL_V1, MAINT_EVENT]
    publishes = [QA_ANSWER_V1, QA_CONTEXT_EXTENSION_V1, NLP_EVENT_V1, NLP_ALERT_V1]

    def __init__(
        self,
        clock_iso: Callable[[], str] | None = None,
        new_id: Callable[[], str] | None = None,
        monotonic: Callable[[], float] | None = None,
        utcnow: Callable[[], _dt.datetime] | None = None,
        deduper: object | None = None,
    ) -> None:
        self._log = logging.getLogger("swarm.agents.nlp.answer")
        add_log_filter(self._log, filters=(PIIScrubFilter(),))
        self._clock_iso = clock_iso or _utc_iso
        _enforce_nlp_spool_audit_dir_modes()
        validate_compatibility_matrix()
        self._new_id = new_id or _new_id
        self._monotonic = monotonic or _time.monotonic
        # §10.13 producer-side deduper (lazy-init from cfg).
        self._deduper = deduper
        self._deduper_lock = _threading.Lock()
        self._utcnow = utcnow or (lambda: _dt.datetime.now(_dt.timezone.utc))
        self._kill_patterns: dict[str, dict[str, object]] = {}
        self._kill_pattern_generation = 0
        # Aggregation state for in-flight summary fan-outs.
        # Keyed by summary_correlation_id.
        self._pending_summaries: dict[str, _SummaryAgg] = {}
        self._lock = _threading.Lock()
        # Cancellation state for streaming humanizer requests.
        self._cancelled_requests: set[str] = set()
        self._cancel_lock = _threading.Lock()
        # §10.19 sampled answer audit state.
        self._audit_today_count = 0
        self._audit_date = ""
        self._audit_lock = _threading.Lock()
        # §10.27.8 regulatory disclosures emitted once per conversation.
        self._conversation_disclosures_emitted: set[str] = set()
        # §10.27.5 preview operator token budgets.
        self._preview_token_usage: dict[str, int] = {}
        self._preview_token_lock = _threading.Lock()
        self._calibration_horizon_mismatch_debouncer = AlertDebouncer(
            ttl_s=300,
            max_buckets=10_000,
            critical_bypass=False,
            clock=self._monotonic,
        )

    def _get_deduper(self) -> object:
        """Return the answer deduper, lazily creating it from cfg."""
        if self._deduper is None:
            with self._deduper_lock:
                if self._deduper is None:
                    from common.config import cfg
                    from swarm.sdk import RequestIdDeduper
                    self._deduper = RequestIdDeduper(
                        window_s=float(cfg.nlp_request_dedup_window_s),
                        max_keys=_NLP_DEDUP_MAX_KEYS,
                        clock=self._monotonic,
                    )
        return self._deduper

    def _maybe_audit_answer(
        self,
        answer_text: str,
        envelope: dict,
        qa_correlation_id: str,
        repair_classes: list[str] | None = None,
    ) -> None:
        """§10.19 sampled answer audit — capture 1-in-N answers (PII-redacted).

        Samples 1-in-cfg.nlp_answer_sample_inverse answers and writes them to
        ``data/nlp/audit/<YYYY-MM-DD>/<qa_correlation_id>.json`` for offline
        quality review. PII-redacts the answer text (email/phone regex) before
        writing. Enforces daily cap via in-memory counter (resets on date change).

        If present, ``repair_classes`` records the per-rule-class repair list
        without storing original tokens.

        Silently skips on any I/O error (never blocks the user).
        """
        import json
        import os
        import random

        from common.config import cfg

        # Sample 1-in-N
        if random.randint(1, cfg.nlp_answer_sample_inverse) != 1:
            return

        with self._audit_lock:
            today = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")
            # Reset counter on date change.
            if self._audit_date != today:
                self._audit_date = today
                self._audit_today_count = 0

            # Check daily cap.
            if self._audit_today_count >= cfg.nlp_answer_sample_daily_cap:
                return

            self._audit_today_count += 1

        redacted_text = _redact_text_with_pii_patterns(answer_text)
        redacted_envelope = {
            key: (
                value
                if key in AUDIT_REDACTION_WHITELIST
                else _redact_value_with_pii_patterns(value)
            )
            for key, value in envelope.items()
        }

        # Prepare audit payload.
        audit_payload = {
            "qa_correlation_id": qa_correlation_id,
            "answer_text_redacted": redacted_text,
            "envelope": redacted_envelope,
            "repair_classes": sorted(set(repair_classes or [])),
            "nlp_audit_bundle_sha": _nlp_audit_bundle_sha(envelope),
            "captured_at": _dt.datetime.now(_dt.timezone.utc).isoformat(
                timespec="seconds"
            ),
        }

        # Write bundle metadata on first observation. Never block the user.
        try:
            _maybe_create_nlp_audit_bundle(envelope)
        except OSError:
            pass

        # Write sampled audit row to disk (fail silently).
        try:
            audit_dir = os.path.join("data", "nlp", "audit", today)
            os.makedirs(audit_dir, exist_ok=True)
            audit_path = os.path.join(audit_dir, f"{qa_correlation_id}.json")
            with open(audit_path, "w", encoding="utf-8") as fh:
                json.dump(audit_payload, fh, ensure_ascii=False, indent=2)
            os.chmod(audit_path, 0o600)
        except OSError:
            # Fail silently — never block the user on audit I/O error.
            pass

    def _make_data_request(
        self,
        request_id: str,
        qa_correlation_id: str,
        intent: str,
        extra_params: dict[str, object] | None = None,
    ) -> list[Message]:
        """Emit a generic data.request.v1 for any data.* intent."""
        qa_corr = qa_correlation_id or self._new_id()
        kind = intent.split(".", 1)[1]
        params: dict[str, object] = {"intent": intent}
        if extra_params:
            params.update(extra_params)
        return [
            Message.new(
                topic=DATA_REQUEST_V1,
                payload={
                    "request_id": self._new_id(),
                    "qa_request_id": request_id,
                    "qa_correlation_id": qa_corr,
                    "kind": kind,
                    "params": params,
                    "emitted_at": self._clock_iso(),
                },
                producer=self.name,
            )
        ]

    def _make_meta_answer(
        self,
        request_id: str,
        qa_correlation_id: str,
        intent: str,
        answer_text: str,
        conversation_id: str | None = None,
        parts: list[dict[str, object]] | None = None,
        degraded: bool = False,
        degraded_reason: str | None = None,
        context_entities: list[dict[str, object]] | None = None,
    ) -> Message:
        qa_corr = qa_correlation_id or self._new_id()
        kind = intent.split(".", 1)[1]
        payload = _make_qa_answer_payload(
            request_id=request_id,
            qa_correlation_id=qa_corr,
            intent=intent,
            kind=kind,
            answer_text=answer_text,
            tier_id_required=None,
            conversation_id=conversation_id,
            parts=parts,
            degraded=degraded,
            degraded_reason=degraded_reason,
            emitted_at_utc=self._clock_iso(),
        )
        if context_entities:
            payload["_context_extension_entities"] = [
                entity for entity in context_entities if isinstance(entity, dict)
            ]
        return Message.new(
            topic=QA_ANSWER_V1,
            payload=payload,
            producer=self.name,
        )

    def _extract_system_context_entities(
        self,
        payload: dict[str, object],
    ) -> list[dict[str, object]] | None:
        entities = payload.get("entities")
        if not isinstance(entities, list):
            return None
        cleaned: list[dict[str, object]] = []
        for entity in entities:
            if not isinstance(entity, dict):
                continue
            kind = str(entity.get("kind") or "").strip()
            canonical_id = str(entity.get("canonical_id") or "").strip()
            if not kind or not canonical_id:
                continue
            cleaned.append({
                "kind": kind,
                "canonical_id": canonical_id,
                "confidence": float(entity.get("confidence") or 1.0),
                "source": str(entity.get("source") or "system"),
                "name": str(entity.get("name") or ""),
            })
        return cleaned if cleaned else None

    def _make_context_extension(
        self,
        conversation_id: str,
        entities: list[dict[str, object]],
    ) -> Message | None:
        if not conversation_id or not entities:
            return None
        safe_entities: list[dict[str, object]] = []
        for entity in entities:
            if not isinstance(entity, dict):
                continue
            kind = str(entity.get("kind") or "").strip()
            canonical_id = str(entity.get("canonical_id") or "").strip()
            if not kind or not canonical_id:
                continue
            safe_entities.append({
                "kind": kind,
                "canonical_id": canonical_id,
                "confidence": float(entity.get("confidence") or 1.0),
                "source": str(entity.get("source") or "system"),
            })
        if not safe_entities:
            return None
        return Message.new(
            topic=QA_CONTEXT_EXTENSION_V1,
            payload={
                "schema_version": 1,
                "conversation_id": conversation_id,
                "entities": safe_entities,
                "emitted_at_utc": self._clock_iso(),
            },
            producer=self.name,
        )

    def _make_fixture_state_flipped_during_rpc_event(
        self,
        request_id: str,
        qa_correlation_id: str,
        match_id: str,
        prior_state: str,
        new_state: str,
        rpc_age_ms: int,
    ) -> Message:
        payload = {
            "kind": "fixture_state_flipped_during_rpc",
            "producer": self.name,
            "request_id": request_id or None,
            "qa_correlation_id": qa_correlation_id or None,
            "match_id": match_id,
            "prior_state": prior_state,
            "new_state": new_state,
            "rpc_age_ms": rpc_age_ms,
            "emitted_at": self._clock_iso(),
        }
        return Message.new(topic=NLP_EVENT_V1, payload=payload, producer=self.name)

    def handle(self, msg: Message) -> Iterable[Message]:
        """Route by topic: qa.intent.v1 or predict.approved.v1.

        §10.13 idempotency: qa.intent.v1 deduped on request_id at ingress;
        predict.approved.v1 with summary aggregation is implicitly deduped
        by summary_correlation_id key in _pending_summaries.
        """
        topic = msg.envelope.topic
        if topic == QA_INTENT_V1:
            request_id = str(msg.payload.get("request_id", ""))
            if self._get_deduper().seen(request_id):  # type: ignore[union-attr]
                return []
            # Stub: full implementation lands in future bullets.
            return []
        if topic == PREDICT_CANCEL_V1:
            request_id = str(msg.payload.get("request_id", ""))
            if request_id:
                self._cancel_request(request_id)
            return []
        if topic == PREDICT_APPROVED:
            results = _unwrap_qa_answer_downgrade_events(self._on_predict_approved(msg))
            return self._with_disclosures(results, msg.payload)
        if topic == MAINT_EVENT:
            return list(self._handle_maint_event(msg))
        return []

    def _on_predict_approved(self, msg: Message) -> Iterable[Message]:
        payload = msg.payload
        citation_check = self._validate_citation_signature(payload)
        if citation_check is not None:
            alert = self._build_citation_signature_alert(payload, citation_check)
            if citation_check["mode"] == "enforce":
                return [
                    self._build_predict_timeout_answer(payload),
                    alert,
                ]

        summary_corr = payload.get("summary_correlation_id")
        request_id = str(payload.get("request_id") or "")
        qa_corr = str(payload.get("qa_correlation_id") or "")
        if self._kill_pattern_matches(payload):
            return [self._make_kill_pattern_answer(request_id=request_id, qa_correlation_id=qa_corr)]
        if summary_corr:
            out = list(self._on_summary_prediction_arrived(payload, str(summary_corr)))
            if citation_check is not None:
                out.append(alert)
            return out

        match_id = str(payload.get("match_id") or "")
        current_state: str | None = None
        lookup_req: Message | None = None
        if match_id:
            current_state, _, _, lookup_req = FixtureStateLookup.get(
                match_id=match_id,
                request_id=request_id,
                qa_correlation_id=qa_corr,
                timeout_ms=int(cfg.nlp_fixture_state_lookup_timeout_ms),
            )
            if current_state in {
                FixtureState.IN_PLAY_FIRST_HALF.value,
                FixtureState.HALFTIME.value,
                FixtureState.IN_PLAY_SECOND_HALF.value,
                FixtureState.IN_PLAY_EXTRA_TIME.value,
                FixtureState.PENALTY_SHOOTOUT.value,
            }:
                intent_name, answer_text, degraded, degraded_reason = _fixture_state_refusal_meta(current_state)
                prior_state = str(payload.get("fixture_state") or "unknown")
                rpc_age_ms = 0
                approved_at = str(payload.get("approved_at") or "")
                approved_dt = _parse_rfc3339_utc(approved_at)
                if approved_dt is not None:
                    rpc_age_ms = int(max(0.0, (_dt.datetime.now(_dt.timezone.utc) - approved_dt).total_seconds() * 1000.0))

                out: list[Message] = [
                    lookup_req,
                    *self._make_data_request(
                        request_id=request_id,
                        qa_correlation_id=qa_corr,
                        intent="data.live_state",
                        extra_params={"match_id": match_id},
                    ),
                    self._make_meta_answer(
                        request_id=request_id,
                        qa_correlation_id=qa_corr,
                        intent=intent_name,
                        answer_text=answer_text,
                        degraded=degraded,
                        degraded_reason=degraded_reason,
                        context_entities=self._extract_system_context_entities(payload),
                    ),
                    self._make_fixture_state_flipped_during_rpc_event(
                        request_id=request_id,
                        qa_correlation_id=qa_corr,
                        match_id=match_id,
                        prior_state=prior_state,
                        new_state=current_state,
                        rpc_age_ms=rpc_age_ms,
                    ),
                ]
                if citation_check is not None:
                    out.append(alert)
                return out

        valid_horizon, horizon_alert = self._validate_calibration_horizon(payload, current_state)
        if not valid_horizon:
            out: list[Message] = []
            if lookup_req is not None:
                out.append(lookup_req)
            if horizon_alert is not None:
                out.append(horizon_alert)
            out.append(
                self._build_calibration_horizon_mismatch_answer(
                    request_id=request_id,
                    qa_correlation_id=qa_corr,
                )
            )
            return out

        if citation_check is not None:
            return [alert]
        return []

    def _citation_key_id(self, key: bytes) -> str:
        return _hashlib.sha256(key).hexdigest()[:16]

    def _now(self) -> _dt.datetime:
        return self._utcnow()

    def _handle_maint_event(self, msg: Message) -> Iterable[Message]:
        try:
            event = MaintEvent.from_dict(msg.payload)
        except (KeyError, TypeError, ValueError) as exc:
            self._log.warning("%s: malformed maint.event.v1: %s", self.name, exc)
            return []

        if event.kind == "nlp_kill_pattern_armed":
            return list(self._arm_kill_pattern(msg.payload))
        if event.kind == "nlp_kill_pattern_disarmed":
            return list(self._disarm_kill_pattern(msg.payload))
        return []

    def _arm_kill_pattern(self, payload: dict[str, object]) -> Iterable[Message]:
        pattern_pack_sha8 = str(payload.get("pattern_pack_sha8") or "")
        ttl_s = int(payload.get("ttl_s") or 0)
        max_ttl_s = int(getattr(cfg, "opsctl_nlp_kill_max_ttl_s", 3600))
        if ttl_s > max_ttl_s:
            ttl_s = max_ttl_s
        if not pattern_pack_sha8 or ttl_s <= 0:
            return []

        expires_at = self._now() + _dt.timedelta(seconds=ttl_s)
        if expires_at <= self._now():
            return []

        pattern = {
            "pattern_pack_sha8": pattern_pack_sha8,
            "expires_at": expires_at,
            "match_id": str(payload.get("match_id") or ""),
            "request_id": str(payload.get("request_id") or ""),
            "intent_class": str(payload.get("intent_class") or ""),
            "template_id": str(payload.get("template_id") or ""),
            "lexicon_hit": str(payload.get("lexicon_hit") or ""),
            "body_substring_sha8": str(payload.get("body_substring_sha8") or ""),
        }

        if not any((pattern["match_id"], pattern["request_id"], pattern["intent_class"], pattern["template_id"], pattern["lexicon_hit"], pattern["body_substring_sha8"])):
            return []

        with self._lock:
            self._kill_patterns[pattern_pack_sha8] = pattern
            self._kill_pattern_generation += 1

        return [
            Message.new(
                topic=NLP_ALERT_V1,
                payload={
                    "kind": "nlp_kill_pattern_armed",
                    "severity": "warn",
                    "producer": self.name,
                    "operator_id_h": str(payload.get("operator_id_h") or ""),
                    "pattern_pack_sha8": pattern_pack_sha8,
                    "ttl_s": ttl_s,
                    "emitted_at": self._clock_iso(),
                },
                producer=self.name,
            )
        ]

    def _disarm_kill_pattern(self, payload: dict[str, object]) -> Iterable[Message]:
        pattern_pack_sha8 = str(payload.get("pattern_pack_sha8") or "")
        if not pattern_pack_sha8:
            return []

        removed = False
        with self._lock:
            removed = self._kill_patterns.pop(pattern_pack_sha8, None) is not None
            if removed:
                self._kill_pattern_generation += 1

        if not removed:
            return []

        return [
            Message.new(
                topic=NLP_ALERT_V1,
                payload={
                    "kind": "nlp_kill_pattern_disarmed",
                    "severity": "info",
                    "producer": self.name,
                    "operator_id_h": str(payload.get("operator_id_h") or ""),
                    "pattern_pack_sha8": pattern_pack_sha8,
                    "emitted_at": self._clock_iso(),
                },
                producer=self.name,
            )
        ]

    def _kill_pattern_matches(self, payload: dict[str, object]) -> bool:
        with self._lock:
            now = self._now()
            expired = [key for key, pattern in self._kill_patterns.items() if pattern["expires_at"] <= now]
            for key in expired:
                self._kill_patterns.pop(key, None)

            for pattern in self._kill_patterns.values():
                if self._kill_pattern_filter_matches(payload, pattern):
                    return True
        return False

    def _kill_pattern_filter_matches(self, payload: dict[str, object], pattern: dict[str, object]) -> bool:
        match_id = pattern.get("match_id")
        if match_id:
            if str(payload.get("match_id") or "") != match_id:
                return False

        request_id = pattern.get("request_id")
        if request_id:
            if str(payload.get("request_id") or "") != request_id:
                return False

        intent_class = pattern.get("intent_class")
        if intent_class:
            final = payload.get("final") or {}
            if not isinstance(final, dict) or str(final.get("intent") or "") != intent_class:
                return False

        template_id = pattern.get("template_id")
        if template_id:
            final = payload.get("final") or {}
            if not isinstance(final, dict) or str(final.get("template_id") or "") != template_id:
                return False

        lexicon_hit = pattern.get("lexicon_hit")
        if lexicon_hit:
            final = payload.get("final") or {}
            if not isinstance(final, dict) or str(final.get("lexicon_hit") or "") != lexicon_hit:
                return False

        body_substring_sha8 = pattern.get("body_substring_sha8")
        if body_substring_sha8:
            # Note: current Phase 10 skeleton does not carry rendered answer text
            # through predict.approved.v1. This field is preserved for future
            # kill-pattern matching once answer content is available.
            return False

        return True

    def _make_kill_pattern_answer(
        self,
        request_id: str,
        qa_correlation_id: str,
    ) -> Message:
        return self._make_meta_answer(
            request_id=request_id,
            qa_correlation_id=qa_correlation_id,
            intent="predict.temporarily_unavailable",
            answer_text="Bu içerik geçici olarak kullanım dışıdır.",
            degraded=True,
            degraded_reason="kill_pattern_armed",
        )

    def _cancel_request(self, request_id: str) -> None:
        with self._cancel_lock:
            self._cancelled_requests.add(request_id)

    def is_request_cancelled(self, request_id: str) -> bool:
        if not request_id:
            return False
        with self._cancel_lock:
            return request_id in self._cancelled_requests

    def _load_predict_citation_hmac_keys(self) -> dict[str, bytes]:
        from common.config import cfg

        loaded: dict[str, bytes] = {}
        key_path = str(getattr(cfg, "predict_citation_hmac_key_path", "") or "").strip()
        grace_s = int(getattr(cfg, "predict_citation_hmac_key_grace_s", 86_400) or 0)
        if key_path:
            path = Path(key_path).expanduser()
            try:
                key = path.read_bytes().strip()
                if key:
                    loaded[self._citation_key_id(key)] = key
                    if grace_s > 0:
                        current_age_s = max(0.0, _time.time() - path.stat().st_mtime)
                        if current_age_s <= grace_s:
                            prev_path = Path(f"{path}.prev")
                            if prev_path.exists():
                                prev_key = prev_path.read_bytes().strip()
                                if prev_key:
                                    loaded[self._citation_key_id(prev_key)] = prev_key
            except OSError:
                pass

        if str(getattr(cfg, "profile", "mock")).lower() == "mock":
            loaded[self._citation_key_id(_MOCK_PREDICT_CITATION_HMAC_KEY)] = _MOCK_PREDICT_CITATION_HMAC_KEY
        return loaded

    def _compute_expected_citation_signature(self, payload: dict, key: bytes) -> str:
        final = payload.get("final") if isinstance(payload.get("final"), dict) else {}
        prediction_id = str(payload.get("prediction_id") or "")
        produced_at = str(final.get("produced_at") or payload.get("approved_at") or "")
        model_versions = final.get("contributing_models")
        if not isinstance(model_versions, list):
            model_versions = []
        canonical_models = "|".join(sorted(str(mid) for mid in model_versions))
        calibration_version = int(payload.get("calibration_version") or final.get("calibration_version") or 1)
        blob = f"{prediction_id}|{produced_at}|{canonical_models}|{calibration_version}"
        return _hmac.new(key, blob.encode("utf-8"), _hashlib.sha256).hexdigest()

    def _validate_citation_signature(self, payload: dict) -> dict | None:
        from common.config import cfg

        schema_version = int(payload.get("schema_version") or 1)
        if schema_version < 3 and "citation_signature" not in payload:
            # Backward-compatibility path: pre-v3 approved envelopes did not
            # carry citation signatures, so they are consumed as-is.
            return None

        mode = str(getattr(cfg, "nlp_predict_citation_hmac_required", "warn") or "warn").lower()
        if mode == "off":
            return None

        keys = self._load_predict_citation_hmac_keys()
        if not keys:
            return {"mode": mode, "reason": "citation_hmac_key_unavailable"}

        signature = payload.get("citation_signature")
        if signature is None:
            return {"mode": mode, "reason": "citation_signature_missing"}
        observed = str(signature).strip().lower()
        if not observed:
            return {"mode": mode, "reason": "citation_signature_missing"}

        key_id = payload.get("citation_key_id")
        if key_id is not None:
            selected = keys.get(str(key_id).strip().lower())
            if selected is None:
                return {"mode": mode, "reason": "citation_key_id_unknown"}
            expected = self._compute_expected_citation_signature(payload, selected)
            if not _hmac.compare_digest(observed, expected):
                return {"mode": mode, "reason": "citation_signature_invalid"}
            return None

        # Backward compatibility path: older producers may not stamp key id.
        if not any(
            _hmac.compare_digest(observed, self._compute_expected_citation_signature(payload, key))
            for key in keys.values()
        ):
            return {"mode": mode, "reason": "citation_signature_invalid"}

        return None

    def _build_citation_signature_alert(self, payload: dict, check: dict) -> Message:
        severity = "critical" if check["mode"] == "enforce" else "warn"
        reason = str(check.get("reason") or "citation_signature_invalid")
        return Message.new(
            topic=NLP_ALERT_V1,
            payload={
                "schema_version": 1,
                "alert_id": self._new_id(),
                "kind": "nlp_citation_signature_verify_failed",
                "severity": severity,
                "source": self.name,
                "reason": reason,
                "request_id": str(payload.get("qa_request_id") or "") or None,
                "qa_correlation_id": (
                    str(payload.get("qa_correlation_id") or payload.get("summary_correlation_id") or "") or None
                ),
                "details": {
                    "mode": check["mode"],
                    "prediction_id": str(payload.get("prediction_id") or ""),
                },
                "emitted_at": self._clock_iso(),
            },
            producer=self.name,
        )

    def _calibration_horizon_state_class(self, state: str) -> str | None:
        if state in {
            FixtureState.SCHEDULED.value,
            FixtureState.PREMATCH_LOCKED.value,
        }:
            return "prematch"
        if state in {
            FixtureState.IN_PLAY_FIRST_HALF.value,
            FixtureState.HALFTIME.value,
            FixtureState.IN_PLAY_SECOND_HALF.value,
            FixtureState.IN_PLAY_EXTRA_TIME.value,
            FixtureState.PENALTY_SHOOTOUT.value,
        }:
            return "live"
        if state in {
            FixtureState.SCHEDULED.value,
            FixtureState.PREMATCH_LOCKED.value,
            FixtureState.IN_PLAY_FIRST_HALF.value,
            FixtureState.HALFTIME.value,
            FixtureState.IN_PLAY_SECOND_HALF.value,
            FixtureState.IN_PLAY_EXTRA_TIME.value,
            FixtureState.PENALTY_SHOOTOUT.value,
        }:
            return "both"
        return None

    def _calibration_horizon_matches_state(self, horizon: str, state: str) -> bool:
        if horizon == "both":
            return state in {
                FixtureState.SCHEDULED.value,
                FixtureState.PREMATCH_LOCKED.value,
                FixtureState.IN_PLAY_FIRST_HALF.value,
                FixtureState.HALFTIME.value,
                FixtureState.IN_PLAY_SECOND_HALF.value,
                FixtureState.IN_PLAY_EXTRA_TIME.value,
                FixtureState.PENALTY_SHOOTOUT.value,
            }
        if horizon == "prematch":
            return state in {
                FixtureState.SCHEDULED.value,
                FixtureState.PREMATCH_LOCKED.value,
            }
        if horizon == "live":
            return state in {
                FixtureState.IN_PLAY_FIRST_HALF.value,
                FixtureState.HALFTIME.value,
                FixtureState.IN_PLAY_SECOND_HALF.value,
                FixtureState.IN_PLAY_EXTRA_TIME.value,
                FixtureState.PENALTY_SHOOTOUT.value,
            }
        return False

    def _calibration_horizon_mismatch_subject(self, payload: dict[str, Any], state_class: str | None) -> str:
        profile_id = str(
            payload.get("profile_id")
            or (payload.get("final") or {}).get("profile_id")
            or "unknown"
        )
        return f"{profile_id}:{state_class or 'unknown'}"

    def _maybe_debounce_calibration_horizon_alert(self, alert: Message, payload: dict[str, Any], state_class: str | None) -> Message | None:
        decision = self._calibration_horizon_mismatch_debouncer.decide(
            kind=alert.payload.get("kind") or "calibration_horizon_mismatch",
            subject=self._calibration_horizon_mismatch_subject(payload, state_class),
            severity=str(alert.payload.get("severity") or "error"),
            reason=str(alert.payload.get("reason") or "calibration_horizon_mismatch"),
        )
        if not decision.emit:
            return None
        return alert

    def _build_calibration_horizon_mismatch_alert(self, payload: dict[str, Any], horizon: str, state: str | None) -> Message:
        state_class = self._calibration_horizon_state_class(state or "unknown")
        return Message.new(
            topic=NLP_ALERT_V1,
            payload={
                "schema_version": 1,
                "alert_id": self._new_id(),
                "kind": "calibration_horizon_mismatch",
                "severity": "error",
                "source": self.name,
                "request_id": str(payload.get("qa_request_id") or payload.get("request_id") or "") or None,
                "qa_correlation_id": (
                    str(payload.get("qa_correlation_id") or payload.get("summary_correlation_id") or "") or None
                ),
                "details": {
                    "horizon": horizon,
                    "state": state,
                    "state_class": state_class,
                },
                "emitted_at": self._clock_iso(),
            },
            producer=self.name,
        )

    def _build_calibration_horizon_mismatch_answer(
        self,
        request_id: str,
        qa_correlation_id: str,
        conversation_id: str | None = None,
    ) -> Message:
        return self._make_meta_answer(
            request_id=request_id,
            qa_correlation_id=qa_correlation_id,
            intent="meta.calibration_horizon_mismatch",
            answer_text="Tahmin kalibrasyonu maçın mevcut durumu ile uyumlu değil.",
            conversation_id=conversation_id,
            degraded=True,
            degraded_reason="calibration_horizon_mismatch",
        )

    def _validate_calibration_horizon(
        self,
        payload: dict[str, Any],
        current_state: str | None = None,
    ) -> tuple[bool, Message | None]:
        horizon = str(payload.get("calibration_state_horizon") or "prematch")
        schema_version = int(payload.get("schema_version") or 1)
        if schema_version <= 1 and cfg.nlp_calibration_horizon_strict and horizon != "prematch":
            alert = self._build_calibration_horizon_mismatch_alert(payload, horizon, current_state)
            alert = self._maybe_debounce_calibration_horizon_alert(alert, payload, self._calibration_horizon_state_class(current_state or "unknown"))
            return False, alert
        if current_state is not None:
            state_class = self._calibration_horizon_state_class(current_state)
            if state_class is not None and not self._calibration_horizon_matches_state(horizon, current_state):
                alert = self._build_calibration_horizon_mismatch_alert(payload, horizon, current_state)
                alert = self._maybe_debounce_calibration_horizon_alert(alert, payload, state_class)
                return False, alert
        return True, None

    def _build_predict_timeout_answer(self, payload: dict) -> Message:
        request_id = str(payload.get("qa_request_id") or payload.get("request_id") or "")
        qa_correlation_id = str(
            payload.get("qa_correlation_id")
            or payload.get("summary_correlation_id")
            or self._new_id()
        )
        output_payload = _make_qa_answer_payload(
            request_id=request_id,
            qa_correlation_id=qa_correlation_id,
            intent="predict.timeout",
            kind="predict.timeout",
            answer_text="Tahmin zaman aşımına uğradı.",
            degraded=True,
            degraded_reason="citation_signature_verification_failed",
            tier_id_required=None,
            emitted_at_utc=self._clock_iso(),
        )
        conversation_id = str(payload.get("conversation_id") or "")
        if conversation_id:
            output_payload["conversation_id"] = conversation_id
        self._apply_safe_mode_degradation(output_payload)
        return Message.new(
            topic=QA_ANSWER_V1,
            payload=output_payload,
            producer=self.name,
        )

    def _apply_safe_mode_degradation(self, payload: dict[str, Any]) -> None:
        """Apply safe-mode answer degradation to outgoing QA answer payloads."""
        if is_safe_mode_active():
            payload["degraded"] = True
            payload["degraded_reason"] = "lexicon_safe_mode_active"

    def _make_disclosure_emitted_event(
        self,
        request_id: str,
        conversation_id: str | None,
        disclosure_id: str,
        disclosure_version: int,
    ) -> Message:
        return Message.new(
            topic=NLP_EVENT_V1,
            payload={
                "kind": "disclosure_emitted",
                "producer": self.name,
                "request_id": request_id or None,
                "conversation_id": conversation_id,
                "disclosure_id": disclosure_id,
                "disclosure_version": disclosure_version,
                "emitted_at": self._clock_iso(),
            },
            producer=self.name,
        )

    def _make_disclosure_locale_fallback_event(
        self,
        request_id: str,
        requested_locale: str,
        resolved_locale: str,
    ) -> Message:
        return Message.new(
            topic=NLP_EVENT_V1,
            payload={
                "kind": "disclosure_locale_fallback",
                "producer": self.name,
                "request_id": request_id or None,
                "requested_locale": requested_locale,
                "resolved_locale": resolved_locale,
                "emitted_at": self._clock_iso(),
            },
            producer=self.name,
        )

    def _with_disclosures(
        self,
        messages: list[Message],
        request_payload: dict[str, object],
    ) -> list[Message]:
        output: list[Message] = []
        request_metadata = request_payload.get("request_metadata")
        conversation_id = str(request_payload.get("conversation_id") or "")
        requested_locale = str(request_payload.get("locale") or "tr-TR")
        for msg in messages:
            if msg.envelope.topic == QA_ANSWER_V1 and isinstance(msg.payload, dict):
                answer_payload = dict(msg.payload)
                context_entities = answer_payload.pop("_context_extension_entities", None)
                events = self._append_disclosures(
                    answer_payload,
                    request_metadata,
                    conversation_id or None,
                    requested_locale,
                )
                output.append(Message.new(topic=QA_ANSWER_V1, payload=answer_payload, producer=msg.envelope.producer))
                output.extend(events)
                if context_entities and conversation_id:
                    extension = self._make_context_extension(conversation_id, context_entities)
                    if extension is not None:
                        output.append(extension)
            else:
                output.append(msg)
        return output

    def _preview_budget_available(self, operator_id_h: str, estimate_tokens: int) -> bool:
        with self._preview_token_lock:
            used = self._preview_token_usage.get(operator_id_h, 0)
            return used + estimate_tokens <= int(cfg.nlp_preview_token_budget_per_operator_per_h)

    def _consume_preview_tokens(self, operator_id_h: str, estimate_tokens: int) -> None:
        with self._preview_token_lock:
            self._preview_token_usage[operator_id_h] = (
                self._preview_token_usage.get(operator_id_h, 0) + estimate_tokens
            )

    def _append_disclosures(
        self,
        payload: dict[str, Any],
        request_metadata: dict[str, Any] | None,
        conversation_id: str | None,
        requested_locale: str,
    ) -> list[Message]:
        disclosure_messages: list[Message] = []
        intent = str(payload.get("intent") or "")
        if not (intent.startswith("predict.") or intent == "summary"):
            return disclosure_messages

        answer_locale = str(payload.get("locale") or requested_locale or "tr-TR")
        disclosures, used_locale = _load_disclosure_texts(answer_locale)
        if used_locale != requested_locale:
            disclosure_messages.append(
                self._make_disclosure_locale_fallback_event(
                    request_id=str(payload.get("request_id") or ""),
                    requested_locale=requested_locale,
                    resolved_locale=used_locale,
                )
            )

        body = str(payload.get("answer_text") or "")
        preview_age_attestation = None
        if isinstance(request_metadata, dict):
            preview_age_attestation = request_metadata.get("user_age_attestation")

        if disclosures:
            disclaimer = next(
                (d for d in disclosures if d["disclosure_id"] == "gambling_law_disclaimer_band"),
                None,
            )
            age_gate = None
            if cfg.nlp_age_gating_enabled and not preview_age_attestation:
                age_gate = next(
                    (d for d in disclosures if d["disclosure_id"] == "eighteen_plus_gate"),
                    None,
                )
            auto_notice = next(
                (d for d in disclosures if d["disclosure_id"] == "automated_decision_notice"),
                None,
            )
            first_conversation = bool(conversation_id and conversation_id not in self._conversation_disclosures_emitted)
            appended: list[str] = []
            used_disclosures: list[dict[str, object]] = []

            if disclaimer:
                appended.append(disclaimer["text"])
                used_disclosures.append(disclaimer)
            if age_gate:
                appended.append(age_gate["text"])
                used_disclosures.append(age_gate)

            appended.append(body)

            if first_conversation and conversation_id:
                footer = next(
                    (d for d in disclosures if d["disclosure_id"] == "kvkk_user_rights_footer_first_per_conversation"),
                    None,
                )
                if footer:
                    appended.append(footer["text"])
                    used_disclosures.append(footer)
                if auto_notice:
                    appended.append(auto_notice["text"])
                    used_disclosures.append(auto_notice)
                self._conversation_disclosures_emitted.add(conversation_id)

            payload["answer_text"] = " ".join(appended)
            payload["disclosures"] = _build_disclosures_metadata(used_disclosures)
            for disclosure in used_disclosures:
                disclosure_messages.append(
                    self._make_disclosure_emitted_event(
                        request_id=str(payload.get("request_id") or ""),
                        conversation_id=conversation_id,
                        disclosure_id=disclosure["disclosure_id"],
                        disclosure_version=disclosure["version"],
                    )
                )
        return disclosure_messages

    def _build_predict_timeout_answer(self, payload: dict) -> Message:
        request_id = str(payload.get("qa_request_id") or payload.get("request_id") or "")
        qa_correlation_id = str(
            payload.get("qa_correlation_id")
            or payload.get("summary_correlation_id")
            or self._new_id()
        )
        output_payload = _make_qa_answer_payload(
            request_id=request_id,
            qa_correlation_id=qa_correlation_id,
            intent="predict.timeout",
            kind="predict.timeout",
            answer_text="Tahmin zaman aşımına uğradı.",
            degraded=True,
            degraded_reason="citation_signature_verification_failed",
            tier_id_required=None,
            emitted_at_utc=self._clock_iso(),
        )
        conversation_id = str(payload.get("conversation_id") or "")
        if conversation_id:
            output_payload["conversation_id"] = conversation_id
        self._apply_safe_mode_degradation(output_payload)
        return Message.new(
            topic=QA_ANSWER_V1,
            payload=output_payload,
            producer=self.name,
        )

    def _on_summary_prediction_arrived(
        self, payload: dict, summary_corr: str
    ) -> Iterable[Message]:
        from common.config import cfg

        with self._lock:
            agg = self._pending_summaries.get(summary_corr)
            if agg is None:
                expected = int(payload.get("summary_expected_count", 1))
                qa_request_id = str(payload.get("qa_request_id", ""))
                # §10.6 qa_correlation_id invariant: read the additive Phase 5
                # field from predict.approved.v1; fall back to summary_corr so
                # old approved envelopes that pre-date the additive field still
                # work (backward-compatible).
                qa_correlation_id = str(
                    payload.get("qa_correlation_id") or summary_corr
                )
                timeout_s = cfg.nlp_summary_aggregation_timeout_ms / 1000.0
                agg = _SummaryAgg(
                    expected=expected,
                    qa_request_id=qa_request_id,
                    qa_correlation_id=qa_correlation_id,
                    deadline=self._monotonic() + timeout_s,
                )
                self._pending_summaries[summary_corr] = agg
            agg.predictions.append(payload)
            received = len(agg.predictions)
            expired = self._monotonic() > agg.deadline
            complete = received >= agg.expected

            if complete or expired:
                del self._pending_summaries[summary_corr]
                return [self._build_summary_answer(agg, summary_corr, received)]
        return []

    def _build_summary_answer(
        self, agg: _SummaryAgg, summary_corr: str, received: int
    ) -> Message:
        from common.config import cfg

        # §10.16 hard rule: preserve degraded flag from predict.approved.v1.
        # Check if ANY prediction in the aggregation has degraded=True in its
        # final payload (predict.approved.v1 embeds predict.final under "final").
        # Combine timeout-degraded with prediction-degraded via OR.
        timeout_degraded = received < agg.expected
        prediction_degraded = False
        degraded_reasons: list[str] = []
        
        # §10.16 calibration version stamping: group predictions by
        # calibration_version; emit one citation entry per unique version.
        calibration_groups: dict[int, int] = {}
        model_versions_by_calibration: dict[int, set[str]] = {}
        prediction_links: list[str] = []
        
        for pred in agg.predictions:
            final = pred.get("final", {})
            if final.get("degraded"):
                prediction_degraded = True
                reason = final.get("degraded_reason", "")
                if reason:  # Only add non-empty reasons
                    degraded_reasons.append(reason)
            
            # Track calibration_version from predict.approved.v1 (top-level).
            cal_ver = int(pred.get("calibration_version", 1))
            calibration_groups[cal_ver] = calibration_groups.get(cal_ver, 0) + 1
            model_versions = final.get("contributing_models")
            if isinstance(model_versions, list):
                model_versions_by_calibration.setdefault(cal_ver, set()).update(
                    str(m) for m in model_versions if m is not None
                )
            prediction_id = str(pred.get("prediction_id") or "").strip()
            if prediction_id:
                prediction_links.append(f"/tahmin/{prediction_id}")
        
        degraded = timeout_degraded or prediction_degraded

        original_count: int | None = None
        top_n_by: str | None = None
        for pred in agg.predictions:
            if original_count is None:
                original_count = int(pred.get("summary_original_count") or 0)
            if top_n_by is None:
                top_n_by = str(pred.get("summary_top_n_by") or "")

        truncated_count = 0
        if original_count and original_count > agg.expected:
            truncated_count = original_count - agg.expected

        quorum_met = True
        if agg.expected > 0:
            quota = math.ceil(cfg.nlp_summary_min_fixture_quorum * agg.expected)
            quota = max(1, quota)
            quorum_met = received >= quota

        if timeout_degraded:
            degraded_reasons.insert(
                0, f"{received}/{agg.expected} predictions received before timeout"
            )

        if received == 0:
            return Message.new(
                topic=QA_ANSWER_V1,
                payload=_make_qa_answer_payload(
                    request_id=agg.qa_request_id,
                    qa_correlation_id=agg.qa_correlation_id,
                    intent="predict.timeout",
                    kind="predict.timeout",
                    answer_text="Tahmin zaman aşımına uğradı.",
                    degraded=True,
                    degraded_reason="summary_quorum_zero_received",
                    citations=[],
                    emitted_at_utc=self._clock_iso(),
                ),
                producer=self.name,
            )

        missing_count = max(0, agg.expected - received)
        missing_fixtures: list[dict[str, str]] = []
        if missing_count > 0:
            reason_tr = _translate_degraded_reason_tr("predict_timeout")
            missing_fixtures = [
                {
                    "label": f"Maç #{received + idx + 1}",
                    "degraded_reason_tr": reason_tr,
                }
                for idx in range(missing_count)
            ]

        if not quorum_met:
            degraded = True
            degraded_reasons.append("summary quorum not met")
            answer_text = render(
                "summary_per_fixture_only.tr.j2",
                {
                    "returned_count": received,
                    "total_count": agg.expected,
                    "missing_fixtures": missing_fixtures,
                },
                env=build_environment(),
                tenant_id=None,
            )
        elif missing_fixtures:
            answer_text = render(
                "summary_partial.tr.j2",
                {
                    "returned_count": received,
                    "total_count": agg.expected,
                    "missing_fixtures": missing_fixtures,
                },
                env=build_environment(),
                tenant_id=None,
            )
        elif degraded:
            answer_text = (
                f"{received} / {agg.expected} maç hazır. "
                "Bazı tahminler henüz tamamlanmadı."
            )
        else:
            answer_text = f"{received} maç tahmini hazır."

        multiple_versions = len(calibration_groups) > 1
        mismatch_policy = cfg.nlp_summary_calibration_mismatch_policy
        if multiple_versions and mismatch_policy == "refuse":
            degraded = True
            degraded_reasons.append("summary calibration mismatch")
            links = ", ".join(sorted(set(prediction_links)))
            answer_text = (
                "Bu hafta için tahminler farklı kalibrasyon sürümleriyle üretildiği için "
                "birleşik özet sunulamıyor."
            )
            if links:
                answer_text += f" Maç bağlantıları: {links}"
        elif multiple_versions and mismatch_policy == "note":
            answer_text += (
                " Not: Bu özet farklı kalibrasyon sürümleri içeren tahminleri birlikte sunar."
            )

        if truncated_count > 0 and original_count is not None:
            answer_text = (
                f"Bu hafta {original_count} maç var; en öne çıkan {agg.expected} tanesini özetledim. "
                "Diğerleri için lig listelerine bakabilirsiniz. "
                + answer_text
            )

        # Compute degraded_reason: join non-empty reasons or None if list is empty
        combined_reason = "; ".join(degraded_reasons) if degraded_reasons else None
        
        # Build citations: one entry per unique calibration_version.
        # If multiple versions exist, add explicit Turkish note to each.
        citations = []
        for cal_ver in sorted(calibration_groups.keys()):
            count = calibration_groups[cal_ver]
            model_versions = sorted(model_versions_by_calibration.get(cal_ver, []))
            entry: dict = {
                "calibration_version": cal_ver,
                "prediction_count": count,
                "model_versions": model_versions,
            }
            if multiple_versions:
                entry["note"] = f"{count} tahmin için kalibrasyon güncellendi"
            citations.append(entry)
        
        payload = _make_qa_answer_payload(
            request_id=agg.qa_request_id,
            qa_correlation_id=agg.qa_correlation_id,
            intent="summary",
            kind="summary",
            answer_text=answer_text,
            degraded=degraded,
            degraded_reason=combined_reason,
            citations=citations,
            truncated_count=truncated_count if truncated_count > 0 else None,
            top_n_by=top_n_by if truncated_count > 0 else None,
            emitted_at_utc=self._clock_iso(),
            query_time_bucket=_hour_truncated_bucket(self._clock_iso()),
            feature_set_hash=_summary_feature_set_hash(agg.predictions),
        )
        self._apply_safe_mode_degradation(payload)
        return Message.new(
            topic=QA_ANSWER_V1,
            payload=payload,
            producer=self.name,
        )


class NlpGossipAggregatorAgent:
    """Phase 10 §10.32.12 gossip aggregator for lexicon-state divergence.

    Subscribes to ``nlp.gossip.v1`` messages from NLP pods and publishes
    divergence visibility alerts on ``nlp.alert.v1``.
    """

    name = "nlp.gossip_aggregator.v1"
    subscribes = [NLP_GOSSIP_V1]
    publishes = [NLP_ALERT_V1]

    def __init__(
        self,
        monotonic: Callable[[], float] | None = None,
    ) -> None:
        self._log = logging.getLogger("swarm.agents.nlp.gossip_aggregator")
        add_log_filter(self._log, filters=(PIIScrubFilter(),))
        self._monotonic = monotonic or _time.monotonic
        self._observations: dict[str, deque[tuple[str, str, str, str, str, str]]] = {}
        self._lock = _threading.Lock()

    def _cluster_modal_tuple(self) -> tuple[str, str, str, str, str, str] | None:
        counts: Counter[tuple[str, str, str, str, str, str]] = Counter()
        for recent in self._observations.values():
            if recent:
                counts.update(recent)

        if not counts:
            return None

        most_common = counts.most_common(2)
        if len(most_common) == 1 or most_common[0][1] > most_common[1][1]:
            return most_common[0][0]
        return None

    def _make_divergence_alert(
        self,
        kind: str,
        pod_instance_id: str,
        observed: tuple[str, str, str, str, str, str] | None = None,
        expected: tuple[str, str, str, str, str, str] | None = None,
        severity: str = "error",
        auto_quarantine: bool = False,
    ) -> Message:
        details: dict[str, object] = {
            "pod_instance_id": pod_instance_id,
        }
        if expected is not None:
            details["expected_lexicon_state"] = {
                "lexicon_set_sha": expected[0],
                "intent_sha": expected[1],
                "crf_sha": expected[2],
                "calibration_version": expected[3],
                "template_git_sha": expected[4],
                "pipeline_version": expected[5],
            }
        if observed is not None:
            details["observed_lexicon_state"] = {
                "lexicon_set_sha": observed[0],
                "intent_sha": observed[1],
                "crf_sha": observed[2],
                "calibration_version": observed[3],
                "template_git_sha": observed[4],
                "pipeline_version": observed[5],
            }
        if auto_quarantine:
            details["auto_quarantine"] = True

        payload: dict[str, object] = {
            "schema_version": 1,
            "alert_id": uuid4().hex,
            "kind": kind,
            "severity": severity,
            "source": self.name,
            "producer": self.name,
            "details": details,
            "emitted_at": _utc_iso(),
        }
        return Message.new(topic=NLP_ALERT_V1, payload=payload, producer=self.name)

    def _has_persistent_divergence(
        self,
        pod_instance_id: str,
        observed: tuple[str, str, str, str, str, str],
        modal: tuple[str, str, str, str, str, str],
    ) -> bool:
        from common.config import cfg

        recent = self._observations.get(pod_instance_id)
        if not recent:
            return False
        if len(recent) < int(cfg.nlp_lexicon_divergence_min_rounds):
            return False
        return all(entry != modal for entry in recent)

    def handle(self, msg: Message) -> list[Message]:
        from common.config import cfg

        payload = msg.payload
        if not isinstance(payload, dict):
            return []

        kind = str(payload.get("kind") or "")
        if kind != "nlp_lexicon_state_gossip":
            return []

        pod_instance_id = str(payload.get("pod_instance_id") or "").strip()
        if not pod_instance_id:
            return []

        observed = (
            str(payload.get("lexicon_set_sha") or ""),
            str(payload.get("intent_sha") or ""),
            str(payload.get("crf_sha") or ""),
            str(payload.get("calibration_version") or ""),
            str(payload.get("template_git_sha") or ""),
            str(payload.get("pipeline_version") or ""),
        )

        with self._lock:
            recent = self._observations.setdefault(
                pod_instance_id,
                deque(maxlen=_NLP_GOSSIP_WINDOW_ROUNDS),
            )
            recent.append(observed)
            cluster_modal = self._cluster_modal_tuple()
            total_pods = len(self._observations)

        events: list[Message] = []
        if total_pods > int(cfg.nlp_gossip_max_pods):
            events.append(
                self._make_divergence_alert(
                    kind="lexicon_gossip_storm",
                    pod_instance_id=pod_instance_id,
                    severity="warn",
                )
            )

        if cluster_modal is None:
            if total_pods >= 2:
                events.append(
                    self._make_divergence_alert(
                        kind="lexicon_state_divergence_no_modal",
                        pod_instance_id=pod_instance_id,
                        severity="warn",
                    )
                )
            return events

        if self._has_persistent_divergence(pod_instance_id, observed, cluster_modal):
            events.append(
                self._make_divergence_alert(
                    kind="lexicon_state_divergence",
                    pod_instance_id=pod_instance_id,
                    observed=observed,
                    expected=cluster_modal,
                    severity="critical",
                    auto_quarantine=bool(cfg.nlp_lexicon_divergence_auto_quarantine),
                )
            )
        return events


class NlpProofreaderAgent:
    """Phase 10 §10.9 skeleton: PII detection + post-block clean path.

    Subscribes to ``qa.answer.v1`` (assembled answer from
    ``nlp.answer.v1``); runs PII detection and, when redaction is
    needed, republishes to ``qa.answer.v1`` (clean path) and emits
    ``nlp.event.v1{kind=pii_in_answer_redacted}`` /
    ``nlp.alert.v1`` for operator visibility.
    """

    name = "nlp.proofreader.v1"
    subscribes = [QA_ANSWER_V1]
    publishes = [QA_ANSWER_V1, NLP_EVENT_V1, NLP_ALERT_V1]

    def __init__(
        self,
        monotonic: Callable[[], float] | None = None,
        deduper: object | None = None,
    ) -> None:
        self._log = logging.getLogger("swarm.agents.nlp.proofreader")
        add_log_filter(self._log, filters=(PIIScrubFilter(),))
        self._monotonic = monotonic or _time.monotonic
        _enforce_nlp_spool_audit_dir_modes()
        self._conversation_store = ConversationStore()
        # §10.13 producer-side deduper (lazy-init from cfg).
        self._deduper = deduper
        self._deduper_lock = _threading.Lock()

    def _get_deduper(self) -> object:
        """Return the proofreader deduper, lazily creating it from cfg."""
        if self._deduper is None:
            with self._deduper_lock:
                if self._deduper is None:
                    from common.config import cfg
                    from swarm.sdk import RequestIdDeduper
                    self._deduper = RequestIdDeduper(
                        window_s=float(cfg.nlp_request_dedup_window_s),
                        max_keys=_NLP_DEDUP_MAX_KEYS,
                        clock=self._monotonic,
                    )

    def handle(self, msg: Message) -> Iterable[Message]:
        """Process qa.answer.v1 (stub for §10.9).

        §10.13 idempotency: dedup on request_id at ingress.
        """
        request_id = str(msg.payload.get("request_id", ""))
        if self._get_deduper().seen(request_id):  # type: ignore[union-attr]
            return []

        out: list[Message] = []
        conversation_id = str(msg.payload.get("conversation_id", ""))
        qa_corr_in = str(msg.payload.get("qa_correlation_id", ""))
        if str(msg.payload.get("kind", "")) == "proofreader_blocked":
            if conversation_id:
                self._conversation_store.clear(conversation_id)
            out = [msg]
            out.append(self._build_conversation_context_cleared_alert(
                request_id=request_id,
                qa_correlation_id=qa_corr_in or None,
                conversation_id=conversation_id or None,
            ))
            return _unwrap_qa_answer_downgrade_events(out)

        if conversation_id:
            history_metadata = self._conversation_store.load_metadata(conversation_id) or {}
            history_metadata["last_qa_answer_text"] = str(msg.payload.get("answer_text") or "")
            history_metadata["last_qa_answer_intent"] = str(msg.payload.get("intent") or "")
            self._conversation_store.save_metadata(conversation_id, history_metadata)

        request_metadata = msg.payload.get("request_metadata")
        pragmatic_class = (
            str(request_metadata.get("pragmatic_class"))
            if isinstance(request_metadata, dict)
            and isinstance(request_metadata.get("pragmatic_class"), str)
            else ""
        )
        if pragmatic_class == "confirmation_seeking":
            payload = dict(msg.payload)
            payload["answer_text"] = _prepend_confirmation_seeking_intro(
                str(msg.payload.get("answer_text") or ""),
                msg.payload.get("parts"),
            )
            return _unwrap_qa_answer_downgrade_events([
                Message.new(topic=QA_ANSWER_V1, payload=payload, producer=self.name)
            ])

        return _unwrap_qa_answer_downgrade_events([msg])

    def _build_conversation_context_cleared_alert(
        self,
        request_id: str,
        qa_correlation_id: str | None,
        conversation_id: str | None,
    ) -> Message:
        payload = {
            "schema_version": 1,
            "alert_id": uuid4().hex,
            "kind": "conversation_context_cleared_after_block",
            "severity": "info",
            "source": self.name,
            "reason": "Proofreader blocked this turn; cleared conversation context.",
            "emitted_at": _utc_iso(),
        }
        if request_id:
            payload["request_id"] = request_id
        if qa_correlation_id:
            payload["qa_correlation_id"] = qa_correlation_id
        if conversation_id:
            payload["subject"] = conversation_id
        return Message.new(
            topic=NLP_ALERT_V1,
            payload=payload,
            producer=self.name,
        )


class NlpProberAgent:
    """Phase 10 §10.32 skeleton: independent synthetic probe emitter.

    Publishes ``nlp.prober.v1`` when the prober runtime is enabled. The
    class exists in the canonical NLP registry so the §10.0 outbound
    wire contract can be asserted by a registry walk.
    """

    name = "nlp.prober.v1"
    subscribes: list[object] = []
    publishes = [NLP_PROBER_V1]

    def handle(self, msg: Message) -> Iterable[Message]:
        return ()


__all__ = [
    "NlpAnswerAgent",
    "NlpBusCircuitBreaker",
    "NlpDispatcherAgent",
    "NlpGossipAggregatorAgent",
    "NlpIntentAgent",
    "NlpProofreaderAgent",
    "NlpProberAgent",
]
