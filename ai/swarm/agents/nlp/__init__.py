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
  ``{qa.intent.v1, qa.answer.v1, nlp.event.v1, nlp.alert.v1,
    predict.request.v1, data.request.v1}``.
* NLP NEVER writes to Postgres directly.
"""
from __future__ import annotations

import datetime as _dt
import functools
import hashlib as _hashlib
import hmac as _hmac
import locale
import logging
import math
import re
import threading as _threading
import time as _time
from collections import deque
from typing import Any, Callable, Iterable
import os
from pathlib import Path
import stat
from uuid import uuid4

from common.config import cfg
from common.fixture_state import FixtureState
from common.security.patterns import PII_PATTERNS
from common.security.tr_pii import parse_redacted_tr_pii

from ...sdk import AlertDebouncer
from ...sdk.types import Message
from nlp.compliance import disclosures_snapshot_sha, load_disclosures
from nlp.lexicon_loader import is_safe_mode_active
from nlp.normalize import assert_minimum_signal
from ..topics import (
    DATA_REQUEST_V1,
    NLP_ALERT_V1,
    NLP_EVENT_V1,
    NLP_SHADOW_V1,
    PREDICT_APPROVED,
    PREDICT_CANCEL_V1,
    PREDICT_REQUEST_V1,
    QA_ANSWER_V1,
    QA_CONTEXT_V1,
    QA_FEEDBACK_V1,
    QA_INTENT_V1,
    QA_REQUEST_V1,
)
from ._bus_circuit_breaker import NlpBusCircuitBreaker
from .abuse import NlpAbuseAgent
from .shadow_writer import NlpShadowWriter
from nlp.compat import validate_compatibility_matrix
from nlp.conversation import ConversationStore
from ._log_filter import PIIScrubFilter, add_log_filter
from nlp.aspectual_stack import detect_aspectual_stack
from nlp.phase10_30 import (
    detect_anaphora_pronouns,
    detect_conditional_modifier,
    is_legal_anaphora_composition,
    resolve_anaphora_pronoun,
)
from nlp.quotative import detect_quotative_frame
from nlp.render import _resolve_locale_tag, build_environment, render

# ── internal helpers ──────────────────────────────────────────────────────

# Entity kinds that can anchor a predict.* intent to a specific fixture.
_FIXTURE_ENTITY_KINDS = frozenset({"team", "competition"})

# Summary intents that fan-out to multiple predict.request.v1 messages.
_SUMMARY_INTENTS = frozenset({"summary.next_week", "summary.matchday"})

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
    schema_version: int = 2,
    conversation_id: str | None = None,
    emitted_at_utc: str | None = None,
    nlp_pipeline_version: str | None = None,
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
    if parts is not None:
        payload["parts"] = parts
    if disclosures is not None:
        payload["disclosures"] = disclosures
    if request_metadata is not None:
        payload["request_metadata"] = request_metadata
    return payload


def _translate_degraded_reason_tr(reason: str) -> str:
    translations = _load_degraded_reason_translations()
    if reason not in translations:
        raise KeyError(f"Missing degraded_reason translation for {reason!r}")
    return translations[reason]


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


def _collapse_parts_for_v1(payload: dict[str, object]) -> None:
    parts = payload.get("parts")
    if isinstance(parts, list) and parts:
        first = parts[0]
        if isinstance(first, dict) and isinstance(first.get("body"), str):
            payload["answer_text"] = first["body"]
    payload.pop("parts", None)
    payload.pop("envelope_signature", None)


def _strip_fields(payload: dict[str, object], field_paths: list[str]) -> None:
    for path in field_paths:
        if path == "parts":
            payload.pop("parts", None)
            continue
        if path == "envelope_signature":
            payload.pop("envelope_signature", None)
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
    redacted = value
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

    os.makedirs(bundle_path, exist_ok=True)
    os.chmod(bundle_path, 0o700)
    _write_bundle_json(bundle_path, "manifest.json", {
        "bundle_sha": bundle_sha,
        "lexicon_snapshot_sha": lexicon_snapshot_sha,
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

    return _sha256_hex(
        "|".join(
            [
                lexicon_snapshot_sha,
                intent_model_sha,
                crf_model_sha,
                calibration_version,
                template_git_sha,
                pipeline_version,
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
) -> str:
    """§10.12 L1 answer cache key including model/calibration versions per §10.13.

    Key = sha256(intent | entity_hash | fixture_window_bucket | model_versions_hash |
                 intent_model_version | lexicon_snapshot_sha | calibration_version |
                 pipeline_version).

    Returns a 16-hex-char sha256 prefix.
    """
    components = (
        f"{intent}|{entity_hash}|{fixture_window_bucket}|{model_versions_hash}|"
        f"{intent_model_version}|{lexicon_snapshot_sha}|{calibration_version}|"
        f"{pipeline_version}"
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
        self._stage_caps_s = stage_caps_s or {
            1: 10.0,
            2: 3.0,
            3: 2.0,
            4: 10.0,
            5: 2.0,
            6: 3.0,
        }
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
        """Traffic readiness: false until boot stage 6 is reached."""
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
        """Compatibility helper: mark probe as fully booted (stage 6)."""
        with self._lock:
            if not self._timed_out:
                self._stage = len(self._STAGE_NAMES) - 1


class NlpIntentAgent:
    """Phase 10 §10.0–§10.5 skeleton: normalize + classify + extract.

    Subscribes to ``qa.request.v1`` (the sec-sanitized data-plane
    envelope, NEVER the raw ``qa.request`` control-plane).  Publishes
    ``qa.intent.v1`` carrying the structured intent + entity set, plus
    ``nlp.event.v1`` / ``nlp.alert.v1`` for operational observability.
    """

    name = "nlp.intent.v1"
    subscribes = [QA_REQUEST_V1, QA_CONTEXT_V1]
    publishes = [QA_INTENT_V1, NLP_EVENT_V1, NLP_ALERT_V1, NLP_SHADOW_V1]

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
        # §10.13 producer-side deduper (lazy-init from cfg).
        self._deduper = deduper
        self._deduper_lock = _threading.Lock()

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

        if msg.topic == QA_REQUEST_V1:
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

            sanitized_text = str(msg.payload.get("sanitized_text", ""))
            floor_kind, greeting_echo = assert_minimum_signal(sanitized_text, cfg=cfg)
            if floor_kind != "ok":
                return self._with_tr_pii_alerts(
                    self._make_floor_response(
                        request_id=request_id,
                        conversation_id=conversation_id or None,
                        floor_kind=floor_kind,
                        greeting_echo=greeting_echo,
                    ),
                    msg.payload,
                )

            results: list[Message] = []
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

        return []

    def _make_floor_response(
        self,
        request_id: str,
        conversation_id: str | None,
        floor_kind: str,
        greeting_echo: str | None,
    ) -> list[Message]:
        if greeting_echo:
            greeting = greeting_echo[0].upper() + greeting_echo[1:]
            answer_text = f"{greeting}! Bana bir maç ya da takım sorabilirsin."
        else:
            answer_text = "Merhaba! Bana bir maç ya da takım sorabilirsin."

        event_payload = {
            "kind": floor_kind,
            "producer": self.name,
            "request_id": request_id or None,
            "emitted_at": _utc_iso(),
        }
        if floor_kind == "meta.unsupported_too_short":
            event_payload["severity"] = "warn"
        else:
            event_payload["severity"] = "info"

        answer_payload = _make_qa_answer_payload(
            request_id=request_id,
            qa_correlation_id=_new_id(),
            intent="meta.help",
            kind="meta.help",
            answer_text=answer_text,
            conversation_id=conversation_id,
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
    ) -> None:
        self._log = logging.getLogger("swarm.agents.nlp.dispatcher")
        add_log_filter(self._log, filters=(PIIScrubFilter(),))
        self._clock_iso = clock_iso or _utc_iso
        _enforce_nlp_spool_audit_dir_modes()
        self._new_id = new_id or _new_id
        self._monotonic = monotonic or _time.monotonic
        self._conversation_store = ConversationStore()
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
        return merged_entities, override_occurred

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
        entities: list = list(payload.get("entities", []))
        request_id: str = str(payload.get("request_id", ""))
        raw_conversation_id = payload.get("conversation_id")
        conversation_id = str(raw_conversation_id).strip() if isinstance(raw_conversation_id, str) else ""
        context_msg: Message | None = None

        override_event: Message | None = None
        repeated_query_event: Message | None = None
        repeated_query_summary_offer: Message | None = None
        context_msg: Message | None = None
        previous_entities: list[dict[str, object]] = []
        previous_anaphora_mentions: list[dict[str, object]] = []
        turn_index = 0
        qa_corr_in: str = str(payload.get("qa_correlation_id") or "")

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
            signature = self._make_repeated_query_signature(
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

            pruned_history.append({
                "signature": signature,
                "ts": now_s,
            })
            history_metadata["repeated_query_history"] = pruned_history
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
            context_payload = {
                "schema_version": 1,
                "conversation_id": conversation_id,
                "turn_index": turn_index,
                "entities": entities,
                "intent": intent,
                "anaphora_mentions": mention_stack,
                "expires_at_utc": self._clock_iso(),
            }
            self._conversation_store.save(context_payload)
            if eviction_event is not None:
                nonlocal eviction_event_message
                eviction_event_message = eviction_event
            return Message.new(
                topic=QA_CONTEXT_V1,
                payload=context_payload,
                producer=self.name,
            )

        eviction_event_message: Message | None = None

        def _with_context(results: Iterable[Message]) -> list[Message]:
            nonlocal context_msg
            out = list(results)
            if override_event is not None:
                out.append(override_event)
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
            return out

        qa_corr_in: str = str(payload.get("qa_correlation_id") or "")

        # ── §10.6 idempotency — dedup before any routing ───────────────────
        dedup_key = f"{qa_corr_in}:{intent}:{_entity_hash(entities)}"
        if self._get_deduper().seen(dedup_key):  # type: ignore[union-attr]
            return _with_context([])

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
            capped = fixture_entities[:max_f]
            summary_corr = self._new_id()
            out: list[Message] = []
            routed_payloads: list[dict[str, object]] = []
            for entity in capped:
                match_id = str(entity["canonical_id"])
                _, _, _, lookup_req = FixtureStateLookup.get(
                    match_id=match_id,
                    request_id=request_id,
                    qa_correlation_id=qa_corr_in,
                    timeout_ms=int(cfg.nlp_fixture_state_lookup_timeout_ms),
                )
                out.append(lookup_req)
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
            if aspectual.modality_class == "progressive_inferential":
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
            _, _, _, lookup_req = FixtureStateLookup.get(
                match_id=match_id,
                request_id=request_id,
                qa_correlation_id=qa_corr_in,
                timeout_ms=int(cfg.nlp_fixture_state_lookup_timeout_ms),
            )
            # predict.* with resolvable fixture: emit fixture-state lookup and
            # then route to predict.request.v1 as the state reply is handled by
            # the downstream Phase 10 circuit.
            return _with_context([
                lookup_req,
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
                ),
            ])

        # data.*, meta.*, and resolvable predict.* routing: future bullets.
        return _with_context([])

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
        )
        return [
            Message.new(
                topic=QA_ANSWER_V1,
                payload=payload,
                producer=self.name,
            )
        ]

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
        if not conditional_modifier:
            return intent, None

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
        return Message.new(
            topic=QA_ANSWER_V1,
            payload=payload,
            producer=self.name,
        )

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
    subscribes = [QA_INTENT_V1, PREDICT_APPROVED, PREDICT_CANCEL_V1]
    publishes = [QA_ANSWER_V1, NLP_EVENT_V1, NLP_ALERT_V1]

    def __init__(
        self,
        clock_iso: Callable[[], str] | None = None,
        new_id: Callable[[], str] | None = None,
        monotonic: Callable[[], float] | None = None,
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
            return self._on_predict_approved(msg)
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
        if summary_corr:
            out = list(self._on_summary_prediction_arrived(payload, str(summary_corr)))
            if citation_check is not None:
                out.append(alert)
            return out
        # Single-predict path: stub for future §10.7 bullets.
        if citation_check is not None:
            return [alert]
        return []

    def _citation_key_id(self, key: bytes) -> str:
        return _hashlib.sha256(key).hexdigest()[:16]

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
    ) -> list[Message]:
        disclosure_messages: list[Message] = []
        intent = str(payload.get("intent") or "")
        if not intent.startswith("predict."):
            return disclosure_messages

        locale = str(payload.get("locale") or "tr-TR")
        disclosures, used_locale = _load_disclosure_texts(locale)
        if used_locale != locale:
            disclosure_messages.append(
                self._make_disclosure_locale_fallback_event(
                    request_id=str(payload.get("request_id") or ""),
                    requested_locale=locale,
                    resolved_locale=used_locale,
                )
            )

        body = str(payload.get("answer_text") or "")
        appended: list[str] = []
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
            footer = None
            auto_notice = next(
                (d for d in disclosures if d["disclosure_id"] == "automated_decision_notice"),
                None,
            )
            first_conversation = bool(conversation_id and conversation_id not in self._conversation_disclosures_emitted)
            if disclaimer:
                appended.append(disclaimer["text"])
            if age_gate:
                appended.append(age_gate["text"])
            appended.append(body)
            used_disclosures: list[dict[str, object]] = []
            if disclaimer:
                appended.append(disclaimer["text"])
                used_disclosures.append(disclaimer)
            if age_gate:
                appended.append(age_gate["text"])
                used_disclosures.append(age_gate)
            if first_conversation and conversation_id:
                footer = next(
                    (d for d in disclosures if d["disclosure_id"] == "kvkk_user_rights_footer_first_per_conversation"),
                    None,
                )
                if footer:
                    appended.append(footer["text"])
                    used_disclosures.append(footer)
            if first_conversation and auto_notice:
                appended.append(auto_notice["text"])
                used_disclosures.append(auto_notice)
            if first_conversation and conversation_id:
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

    def _validate_calibration_horizon(
        self,
        payload: dict[str, Any],
    ) -> tuple[bool, Message | None]:
        horizon = str(payload.get("calibration_state_horizon") or "prematch")
        schema_version = int(payload.get("schema_version") or 1)
        if schema_version <= 1 and cfg.nlp_calibration_horizon_strict and horizon != "prematch":
            alert = Message.new(
                topic=NLP_ALERT_V1,
                payload={
                    "schema_version": 1,
                    "alert_id": self._new_id(),
                    "kind": "calibration_horizon_mismatch",
                    "severity": "error",
                    "source": self.name,
                    "request_id": str(payload.get("qa_request_id") or payload.get("request_id") or "") or None,
                    "details": {
                        "horizon": horizon,
                        "schema_version": schema_version,
                    },
                    "emitted_at": self._clock_iso(),
                },
                producer=self.name,
            )
            return False, alert
        return True, None

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
            emitted_at_utc=self._clock_iso(),
        )
        self._apply_safe_mode_degradation(payload)
        return Message.new(
            topic=QA_ANSWER_V1,
            payload=payload,
            producer=self.name,
        )


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
        return self._deduper

    def handle(self, msg: Message) -> Iterable[Message]:
        """Process qa.answer.v1 (stub for §10.9).

        §10.13 idempotency: dedup on request_id at ingress.
        """
        request_id = str(msg.payload.get("request_id", ""))
        if self._get_deduper().seen(request_id):  # type: ignore[union-attr]
            return []

        out: list[Message] = []
        if str(msg.payload.get("kind", "")) == "proofreader_blocked":
            conversation_id = str(msg.payload.get("conversation_id", ""))
            if conversation_id:
                self._conversation_store.clear(conversation_id)
            out = [msg]
            out.append(self._build_conversation_context_cleared_alert(
                request_id=request_id,
                qa_correlation_id=str(msg.payload.get("qa_correlation_id", "")) or None,
                conversation_id=conversation_id or None,
            ))
        return out

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


__all__ = [
    "NlpAnswerAgent",
    "NlpBusCircuitBreaker",
    "NlpDispatcherAgent",
    "NlpIntentAgent",
    "NlpProofreaderAgent",
]
