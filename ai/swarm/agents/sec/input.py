"""Phase 7 §7.1 — `sec.input.v1` escalation-tier classifier wrapper.

The Go gateway runs steps 1–4 of the SECURITY.md sec.input pipeline
(length cap, charset / control-strip, NFC + Turkish-aware lowercase,
deterministic injection rules) **in-process**. Verdict ``quarantine``
→ the gateway writes to ``sec.quarantine.v1`` and returns 400.
Verdict ``pass`` → the gateway publishes ``qa.request.v1`` directly.
Verdict ``sanitize`` (rules inconclusive) → the gateway publishes
the **raw** payload on ``qa.request`` for this agent to escalate.

This module owns the **agent side** of that contract. It subscribes
``qa.request``, runs the classifier (step 5 — small distilbert-class
model), and:

* on classifier verdict ``pass`` → publishes ``qa.request.v1``
  with ``sec_verdict=sanitized`` (the deterministic transforms the
  gateway already applied are recorded in ``sec_steps_run``);
* on classifier verdict ``quarantine`` → publishes
  ``sec.quarantine.v1`` and ``sec.alert.v1{kind=prompt_injection}``;
* on classifier degraded / load-shed / disabled → falls **open** to
  ``pass`` with a debounced ``sec.alert.v1{kind=classifier_*}``
  warning. **Fail-open is doctrine** (ROADMAP §7.7) — Phase 10 NLP
  answers from templates with no LLM in the answer hot path, so a
  bypassed sanitizer can never escalate into model-output abuse.

v1 scope (per ROADMAP §7.8 "Sec.input classifier promotion"):
``cfg.sec_input_classifier_path`` defaults to **empty**. With no
classifier on disk, the agent skips step 5 and the verdict short-
circuits to ``pass`` with one ``sec.alert.v1{kind=classifier_degraded,
severity=info}`` per (subject, ttl) bucket. The first labelled-
corpus drop (Phase 13 lexicon) unlocks the actual model load; the
agent's wire surface stays identical.

Idempotency: a ``request_id`` re-delivered through ``qa.request``
emits at most one ``qa.request.v1`` and at most one quarantine row
per ``cfg.qa_request_v1_dedup_window_s`` window. The dedup map is
bounded by ``cfg.sec_input_classifier_max_pending`` with insertion-
order LRU eviction.
"""
from __future__ import annotations

import hashlib
import logging
import re
import threading
import time
import unicodedata
from base64 import b64encode
from collections import OrderedDict, deque
from datetime import datetime, timezone
from typing import Callable, Deque, Iterable
from uuid import uuid4

from ai.common.config import cfg as _cfg
from ai.common.security import (
    PatternFileError,
    RuleSet,
    load_ruleset,
    resolve_path as _resolve_pattern_path,
)
from ai.common.security.tr_pii import redact_tr_pii
from ai.common.text.turkish import lowercase_tr

from ..payloads import (
    QaRequest,
    QaRequestV1,
    QuarantineSample,
    SecAlert,
    SecConfigEvent,
)
from ..topics import (
    MAINT_EVENT,
    QA_REQUEST,
    QA_REQUEST_V1,
    SEC_ALERT,
    SEC_CONFIG,
    SEC_QUARANTINE,
)
from ...sdk.types import Message, Topic
from ._alert import SecAlertDebouncer
from ._allowlist import (
    AllowlistCache,
    InMemoryAllowlistReader,
    PatternAllowlistReader,
    allowlist_hmac_key_age_days,
    compute_pattern_key_legacy_sha,
    compute_pattern_key,
)
from ..maint.scaler import _LabelCounter

_log = logging.getLogger("swarm.agents.sec.input")


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _new_id() -> str:
    return uuid4().hex


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ── Defense-in-depth sanitizer ────────────────────────────────────
#
# Per ROADMAP §7.1, the Go gateway's middleware applies steps 1–4
# (length cap, charset / control-char strip, NFC + Turkish-aware
# lowercase, deterministic injection rules) BEFORE publishing
# `qa.request`. This agent runs step 5 (classifier) and forwards.
#
# But §7.7 fail-open doctrine + Phase 9 cross-phase contract bind
# the agent to **defense-in-depth**: a misbehaving internal client,
# a dev-profile bypass, or a future regression that lets bytes reach
# `qa.request` without the gateway's transforms must NOT be able to
# inject zero-width chars, RTL overrides, or other charset-spoofing
# payloads into `qa.request.v1` (which the NLP layer trusts as
# `sec_verdict=sanitized`).
#
# So the agent re-applies the deterministic byte-level transforms
# itself before publishing v1. Idempotent — gateway-already-sanitized
# bytes survive untouched. The wire field `sec_steps_run` reports
# what THIS agent actually ran, not what the gateway claimed.

# Control chars (C0, except \t \n \r) + DEL + C1 + zero-width
# (U+200B..U+200F, U+202A..U+202E LRE/RLE/PDF/LRO/RLO,
#  U+2066..U+2069 LRI/RLI/FSI/PDI, U+FEFF BOM, U+00AD soft hyphen).
# Pattern is anchored to Unicode points so it is correct after NFC
# (where a precomposed char like ï is NOT split). Compiled once.
_STRIP_CONTROL_RE = re.compile(
    "["
    "\u0000-\u0008\u000B\u000C\u000E-\u001F"  # C0 minus \t \n \r
    "\u007F"                                    # DEL
    "\u0080-\u009F"                             # C1
    "\u00AD"                                    # SOFT HYPHEN
    "\u200B-\u200F"                             # ZWSP, ZWNJ, ZWJ, LRM, RLM
    "\u202A-\u202E"                             # LRE, RLE, PDF, LRO, RLO
    "\u2066-\u2069"                             # LRI, RLI, FSI, PDI
    "\uFEFF"                                    # BOM / ZWNBSP
    "]"
)

_FORMAT_CATEGORY_ALLOWLIST: frozenset[int] = frozenset()
_HANGUL_FILLER_CODEPOINTS = frozenset({0x115F, 0x1160, 0x3164})


def _is_disallowed_unicode_char(ch: str) -> bool:
    cp = ord(ch)
    category = unicodedata.category(ch)
    if category == "Cf" and cp not in _FORMAT_CATEGORY_ALLOWLIST:
        return True
    if 0xFE00 <= cp <= 0xFE0F:
        return True
    if cp in _HANGUL_FILLER_CODEPOINTS:
        return True
    if category in {"Cn", "Co", "Cs"}:
        return True
    return False


def sanitize_text(raw: str) -> tuple[str, list[str], bool]:
    """Apply defense-in-depth transforms.

    Returns ``(clean, steps_run, mutated)``:

    * ``clean`` — sanitized text safe to forward on `qa.request.v1`.
    * ``steps_run`` — deterministic list of transforms that executed
      (the agent always runs the same set; this lists them so the
      NLP layer's forensic trace is explicit on the wire).
    * ``mutated`` — ``True`` iff the bytes were actually changed.
      The agent uses this to fire a debounced
      ``sec.alert.v1{kind=charset_anomaly}`` info alert — a signal
      that something reached `qa.request` without being sanitized
      upstream, i.e. the gateway's middleware was bypassed or
      buggy. Loud-on-mutation is the §7.7 doctrine.

    Idempotent: ``sanitize_text(sanitize_text(s)[0])[2] is False``
    for any ``s``.
    """
    # 1. NFC normalize. Defends against canonical-equivalence smuggling.
    nfc = unicodedata.normalize("NFC", raw)
    # 2. Strip control chars + zero-widths + RTL overrides + BOM.
    stripped = _STRIP_CONTROL_RE.sub("", nfc)
    stripped = "".join(ch for ch in stripped if not _is_disallowed_unicode_char(ch))
    lowercased = lowercase_tr(stripped)
    return lowercased, ["nfc", "strip_control", "lowercase_tr"], lowercased != raw


class SecInputAgent:
    """Subscribes ``qa.request``; emits ``qa.request.v1``,
    ``sec.quarantine.v1``, and ``sec.alert.v1`` per §7.1.

    Constructor knobs:

    * ``classifier`` — optional callable ``(text: str) -> tuple[str, str]``
      returning ``(verdict, reason)`` where ``verdict ∈ {pass,
      quarantine}``. When ``None``, the agent runs in v1 fallback
      mode (§7.8): every request short-circuits to ``pass`` with
      one ``classifier_degraded`` alert per subject debounce
      window. The wire contract is identical with or without the
      classifier — Phase 13 lexicon drop will inject a real
      callable without any other code change.
    * ``debouncer`` — optional ``SecAlertDebouncer``; one is built
      from ``cfg`` if not supplied.
    * ``clock_iso`` / ``new_id`` — injected for tests.
    """

    name = "sec.input.v1"
    subscribes: tuple[Topic, ...] = (QA_REQUEST, SEC_CONFIG)
    publishes: tuple[Topic, ...] = (
        QA_REQUEST_V1,
        SEC_QUARANTINE,
        SEC_ALERT,
        SEC_CONFIG,
        MAINT_EVENT,
    )

    def __init__(
        self,
        *,
        classifier: Callable[[str], tuple[str, str]] | None = None,
        debouncer: SecAlertDebouncer | None = None,
        clock_iso: Callable[[], str] | None = None,
        clock_mono: Callable[[], float] | None = None,
        new_id: Callable[[], str] | None = None,
        pattern_path: str | None = None,
        ruleset: RuleSet | None = None,
        allowlist_reader: PatternAllowlistReader | None = None,
    ) -> None:
        self._classifier = classifier
        # ── Deterministic injection-pattern engine (§7.1, binding) ─
        # Loaded eagerly so a startup with a malformed YAML fails
        # loud, not silently. The agent then polls the file's mtime
        # at most once every `cfg.sec_input_pattern_reload_s` seconds
        # and atomically swaps in a new ruleset on change. Reload
        # failures keep the previous ruleset in place and emit a
        # `pattern_reload` SecAlert with severity=error.
        #
        # Tests inject a pre-built `ruleset` to bypass disk I/O.
        self._pattern_path = pattern_path
        # Polling is enabled only when the agent owns its ruleset
        # (loaded from disk). When a caller injects a ruleset, the
        # caller controls reloads via maybe_reload_patterns().
        self._pattern_polling_enabled = ruleset is None
        if ruleset is not None:
            self._ruleset: RuleSet | None = ruleset
        else:
            try:
                self._ruleset = load_ruleset(pattern_path)
            except PatternFileError as exc:
                # Fail-open per §7.7 doctrine — agent stays alive,
                # patterns are just absent until operator fixes the
                # file. Polling will retry; a startup-time alert is
                # logged but not emitted on the bus (no bus yet).
                _log.error(
                    "%s: pattern load failed at startup (%s); "
                    "deterministic rules disabled until reload succeeds",
                    self.__class__.__name__, exc,
                )
                self._ruleset = None
        self._last_pattern_check_mono = 0.0
        # Pending alerts produced by reload bookkeeping; drained at
        # the top of the next handle() call so the bus surface is
        # the same regardless of whether reload happened mid-request
        # or out-of-band via maybe_reload_patterns().
        self._pending_pattern_alerts: Deque[Message] = deque()
        # NOTE: explicit ``is None`` check rather than ``debouncer or ...``
        # because ``SecAlertDebouncer.__len__`` returns the bucket count
        # — a freshly-injected debouncer is len()==0 and therefore
        # falsy, which would silently drop the test/operator override.
        self._debouncer = debouncer if debouncer is not None else SecAlertDebouncer(
            ttl_s=int(_cfg.sec_alert_debounce_ttl_s),
            critical_bypass=not bool(_cfg.sec_alert_critical_debounce_enabled),
            max_buckets=int(_cfg.sec_alert_debouncer_max_buckets),
        )
        self._clock_iso = clock_iso or _utc_iso
        self._clock_mono = clock_mono or time.monotonic
        self._new_id = new_id or _new_id
        # Idempotency: dedup by request_id with insertion-order LRU.
        self._dedup: "OrderedDict[str, None]" = OrderedDict()
        self._dedup_max = max(1, int(_cfg.sec_input_classifier_max_pending))
        # Producer-side overflow guard (§7.5 binding). When storage.v1
        # falls behind under a coordinated quarantine burst, this
        # bounded deque tracks the *recent* emission timestamps; old
        # entries (older than the storage-lag alert window) age out.
        # When the deque saturates, a `quarantine_overflow` SecAlert
        # fires (debounced, severity=error). We DO NOT drop the new
        # write — the freshest forensic evidence is the most valuable
        # (§7.5 doctrine: drop-oldest interpreted as drop-from-tracking,
        # not drop-from-publication; on InMemoryBus there's no real
        # storage backpressure to relieve, but the alert tells operators
        # the consumer-side guard `quarantine_storage_slow` is imminent).
        self._quarantine_inflight: Deque[float] = deque()
        self._quarantine_max = max(1, int(_cfg.sec_quarantine_producer_queue_max))
        self._quarantine_window_s = max(
            0.001, float(_cfg.sec_quarantine_storage_lag_alert_ms) / 1000.0
        )
        self._lock = threading.Lock()
        # Phase 8 §8.7 — pattern_allowlist read-side cache. The
        # default reader is an empty in-memory shim so dev/test boots
        # see no suppressions; production wires a Postgres-backed
        # reader (Phase 8.7b) that runs the version+rows SELECTs under
        # REPEATABLE READ snapshot isolation.
        self._allowlist_cache = AllowlistCache(
            allowlist_reader if allowlist_reader is not None
            else InMemoryAllowlistReader(),
            reload_s=int(_cfg.sec_input_allowlist_reload_s),
            clock_mono=self._clock_mono,
        )
        # Phase 8 §8.7 — observability surface (binding).
        # Counter ``sec_input_allowlist_hits_total{rule_id}``: one
        # increment per pattern-rule hit that was suppressed by an
        # active allowlist entry. Visible via :meth:`metrics_snapshot`
        # — the suppression is never silently lost.
        self._m_allowlist_hits = _LabelCounter(
            "sec_input_allowlist_hits_total", ("rule_id",)
        )
        # Phase 8 §8.16.10 — legacy SHA compatibility path emits one
        # maint.event.v1 signal per legacy row key to avoid event spam.
        self._legacy_allowlist_hit_rows: set[str] = set()
        # Phase 8 §8.16.10 — overdue allowlist key rotation alert is
        # debounced daily per process.
        self._allowlist_rotation_overdue_last_mono = float("-inf")
        self._allowlist_rotation_overdue_interval_s = 86400.0

    # ── Bus contract ──────────────────────────────────────────────
    def handle(self, msg: Message) -> Iterable[Message]:
        topic = msg.envelope.topic
        if topic == SEC_CONFIG:
            return list(self._handle_config(msg))
        if topic != QA_REQUEST:
            _log.warning("%s: unsubscribed topic %r delivered", self.name, topic)
            return ()
        try:
            req = QaRequest.from_dict(msg.payload)
        except (KeyError, TypeError, ValueError) as exc:
            _log.warning("%s: malformed qa.request: %s", self.name, exc)
            return ()
        # Drain pattern-reload alerts produced by the periodic poller
        # so they ride on the same handle() invocation as the request
        # that triggered the check (keeps test ordering deterministic).
        out: list[Message] = []
        self._maybe_poll_patterns(out)
        out.extend(self._handle_request(req))
        return out

    # ── sec.config.v1 (cross-pod fan-out) ─────────────────────────
    def _handle_config(self, msg: Message) -> Iterable[Message]:
        """React to a cross-pod hot-reload announcement.

        Per ROADMAP §7.1: mtime polling does not fire on
        ``kubectl rollout`` of a ConfigMap-mounted file in every
        CRI runtime. The bus event is the secondary wake-up — the
        FILE on disk is still the source of truth, the announced
        sha256 is just a cheap hint.

        Idempotency: if the announced sha matches our currently-
        loaded ruleset, this is a no-op (we silently skip).
        Otherwise we fall through to the same ``_reload_now()`` the
        mtime poller uses; on parse failure we keep the old
        ruleset and emit a debounced
        ``sec.alert.v1{kind=pattern_reload, severity=error}``.
        """
        try:
            event = SecConfigEvent.from_dict(msg.payload)
        except (KeyError, TypeError, ValueError) as exc:
            _log.warning("%s: malformed sec.config.v1: %s", self.name, exc)
            return
        if event.config_name != "injection_patterns":
            # The endpoint_costs file is owned by the Go gateway;
            # the Python agent has no view into it. Silent skip is
            # correct — and a test pins the contract.
            return
        # Quick sha pre-check under the lock so we don't redundantly
        # hit the disk on a re-broadcast of the same announcement.
        with self._lock:
            current = self._ruleset
            if current is not None and current.sha256 == event.sha256:
                return
        # Disk re-read; same fail-safe path as the mtime poller.
        yield from self._reload_now()

    # ── Core ──────────────────────────────────────────────────────
    def _handle_request(self, req: QaRequest) -> Iterable[Message]:
        # Idempotency gate — at-least-once redelivery must not double-
        # publish qa.request.v1 or double-quarantine. Dedup keys on
        # request_id (the §7.5 mutually-exclusive-producers contract is
        # per-request_id; replays land here regardless of the originating
        # producer).
        with self._lock:
            if req.request_id in self._dedup:
                _log.debug(
                    "%s: dedup hit for request_id=%s", self.name, req.request_id
                )
                return
            self._dedup[req.request_id] = None
            # Bounded LRU: evict oldest if we exceed cap.
            while len(self._dedup) > self._dedup_max:
                self._dedup.popitem(last=False)

        # Defense-in-depth Turkish-specific PII redaction happens before
        # the classifier and before the length cap. This ensures the NLP
        # plane never receives raw TR-sensitive identifiers in transit.
        if _cfg.nlp_tr_pii_redact_enabled:
            redacted_text, pii_spans = redact_tr_pii(req.raw_text)
        else:
            redacted_text, pii_spans = req.raw_text, []

        # Defense-in-depth length cap. The Go gateway enforces this on
        # the request boundary (rejects 413 before bytes reach the bus
        # — §7.1 byte-semantics binding); the agent re-checks because
        # any other producer reaching `qa.request` (a misbehaving
        # internal client, a bypass of the gateway in dev profiles)
        # must NOT be able to feed an oversized payload to the
        # classifier. Length is **bytes after UTF-8 encoding**, not
        # codepoints — same semantics as the gateway. Oversize
        # → quarantine (NOT pass), so a malicious bypass never
        # silently widens the attack surface.
        max_len = max(1, int(_cfg.sec_input_max_len))
        encoded_len = len(redacted_text.encode("utf-8", errors="replace"))
        if encoded_len > max_len:
            yield from self._emit_quarantine(
                req,
                classifier_reason=f"payload_oversize:{encoded_len}>{max_len}",
                kind="payload_oversize",
                severity="warn",
            )
            return

        # Defense-in-depth sanitization happens BEFORE the classifier
        # so an attacker cannot blind it with zero-widths / RTL
        # overrides / non-NFC sequences. The classifier sees the same
        # bytes the NLP layer will see (sec_verdict=sanitized
        # contract: the v1 envelope and the classifier input are
        # consistent — no slip-through between detection and forward).
        clean_text, sanitize_steps, sanitized_mutated = sanitize_text(redacted_text)
        mutated = sanitized_mutated or bool(pii_spans)
        sanitize_steps = ["tr_pii_redaction"] + sanitize_steps
        yield from self._emit_allowlist_key_rotation_overdue(req)

        # Deterministic injection-rule sweep BEFORE the (possibly
        # absent / load-shed) classifier. Quarantines the request
        # immediately on a hit; no bytes reach the classifier or the
        # NLP layer. The matching rule's id + reason land in the
        # quarantine envelope's `reasons` list for forensic review.
        if self._ruleset is not None:
            hit = self._ruleset.match(clean_text)
            if hit is not None:
                # Phase 8 §8.7 — pattern_allowlist suppression. Operator-
                # confirmed false positives shadow the rule for this
                # exact (source, rule_id, hit_substring) triple. The
                # raw substring is hashed (NFC + HMAC-SHA256[:16]) so the
                # cache never holds the unredacted text. Suppression
                # is counted, not silently dropped.
                m = hit.pattern.search(clean_text)
                hit_substring = m.group(0) if m is not None else clean_text
                allow_key = compute_pattern_key(
                    "qa", hit.rule_id, hit_substring,
                )
                allow_key_legacy = compute_pattern_key_legacy_sha(
                    "qa", hit.rule_id, hit_substring,
                )
                matched_key = self._allowlist_cache.first_match(
                    (allow_key, allow_key_legacy)
                )
                if matched_key is not None:
                    self._m_allowlist_hits.inc((hit.rule_id,))
                    if (
                        matched_key == allow_key_legacy
                        and self._mark_legacy_allowlist_row_seen(allow_key_legacy)
                    ):
                        yield Message.new(
                            MAINT_EVENT,
                            {
                                "kind": "pattern_allowlist_legacy_hit",
                                "kind_schema_version": 1,
                                "target": f"qa:{hit.rule_id}",
                                "source": "qa",
                                "rule_id": hit.rule_id,
                                "row_id": allow_key_legacy,
                                "produced_at": self._clock_iso(),
                            },
                            producer=self.name,
                        )
                    _log.debug(
                        "%s: pattern hit suppressed by allowlist "
                        "(rule_id=%s)", self.name, hit.rule_id,
                    )
                    # Fall through — request continues to the
                    # classifier as if the rule had not matched.
                else:
                    yield from self._emit_quarantine(
                        req,
                        classifier_reason=f"rule:{hit.rule_id}",
                        kind=hit.kind,
                        severity=hit.severity if hit.severity != "info" else "warn",
                        extra_reasons=(hit.reason,),
                    )
                    return

        verdict, reason = self._classify(clean_text)

        if verdict == "quarantine":
            # Quarantine carries the ORIGINAL raw bytes (not the
            # sanitized version) so forensic analysis sees what
            # actually arrived on the wire.
            yield from self._emit_quarantine(
                req,
                classifier_reason=reason,
                kind="prompt_injection",
                severity="warn",
            )
            return
        # `pass` — publish the v1 envelope. The gateway already ran
        # steps 1–4; the agent's job here is to record that the
        # classifier verdict (step 5) was `pass`. ``sec_verdict`` is
        # ``sanitized`` because the gateway's deterministic transforms
        # plus our defense-in-depth re-sanitization (above) jointly
        # produced the bytes the NLP layer reads.
        yield from self._emit_pass(
            req,
            clean_text=clean_text,
            sanitize_steps=sanitize_steps,
            mutated=mutated,
            classifier_reason=reason,
        )

    def _mark_legacy_allowlist_row_seen(self, row_id: str) -> bool:
        """Return True only on the first legacy-row hit in this process."""
        with self._lock:
            if row_id in self._legacy_allowlist_hit_rows:
                return False
            self._legacy_allowlist_hit_rows.add(row_id)
            return True

    def _emit_allowlist_key_rotation_overdue(self, req: QaRequest) -> Iterable[Message]:
        """Emit daily warn alert when allowlist HMAC key age exceeds policy."""
        age_days = allowlist_hmac_key_age_days()
        if age_days is None:
            return
        max_age_days = int(getattr(_cfg, "sec_input_allowlist_hmac_key_max_age_days", 365))
        if age_days <= max_age_days:
            return
        now = self._clock_mono()
        with self._lock:
            if (
                now - self._allowlist_rotation_overdue_last_mono
                < self._allowlist_rotation_overdue_interval_s
            ):
                return
            self._allowlist_rotation_overdue_last_mono = now
        alert = SecAlert(
            alert_id=self._new_id(),
            kind="allowlist_hmac_key_rotation_overdue",
            severity="warn",
            source=self.name,
            reason=(
                "allowlist HMAC key age exceeded max age "
                f"({age_days:.1f}d > {max_age_days}d)"
            ),
            produced_at=self._clock_iso(),
            subject="allowlist_hmac_key",
            request_id=req.request_id,
            client_id=req.client_id,
            ip=req.ip,
        )
        yield Message.new(SEC_ALERT, alert.as_dict(), producer=self.name)

    def _classify(self, text: str) -> tuple[str, str]:
        """Run the escalation-tier classifier and return
        ``(verdict, reason)``.

        Fail-open contract: any classifier error / OOM / disabled
        path resolves to ``pass`` with a reason string the alert
        debouncer surfaces. Never raise; never return ``quarantine``
        from the failure path (would be fail-closed).
        """
        if self._classifier is None:
            # v1 fallback per §7.8 — no classifier on disk.
            return "pass", "classifier_disabled"
        try:
            verdict, reason = self._classifier(text)
        except Exception as exc:  # pragma: no cover — defensive belt
            _log.warning(
                "%s: classifier raised %s; falling back to pass",
                self.name, exc,
            )
            return "pass", f"classifier_error: {type(exc).__name__}"
        if verdict not in {"pass", "quarantine"}:
            _log.warning(
                "%s: classifier returned unknown verdict %r; falling back to pass",
                self.name, verdict,
            )
            return "pass", "classifier_unknown_verdict"
        return verdict, reason

    def _emit_pass(
        self,
        req: QaRequest,
        *,
        clean_text: str,
        sanitize_steps: list[str],
        mutated: bool,
        classifier_reason: str,
    ) -> Iterable[Message]:
        # Defense-in-depth re-sanitization happened in the caller;
        # we receive the cleaned text + the steps that ran. If
        # `mutated` is True the upstream gateway either skipped a
        # step or was bypassed; we surface that as a debounced
        # `charset_anomaly` info alert.
        steps = list(sanitize_steps)
        if classifier_reason not in {"classifier_disabled"}:
            steps.append("classifier")
        v1 = QaRequestV1(
            request_id=req.request_id,
            sanitized_text=clean_text,
            locale=req.locale,
            sec_verdict="sanitized",
            sec_steps_run=steps,
            client_id=req.client_id,
            emitted_at=self._clock_iso(),
        )
        yield Message.new(QA_REQUEST_V1, v1.as_dict(), producer=self.name)

        # Loud-on-mutation: bytes-changed signals an upstream sanitizer
        # bypass; emit one debounced `charset_anomaly` info alert per
        # subject so operators see the bypass rate without alarm
        # fatigue. Severity stays `info` — the agent already neutralised
        # the bytes; this is forensic, not actionable in the moment.
        if mutated:
            decision = self._debouncer.decide(
                kind="charset_anomaly",
                subject=req.client_id or req.ip,
                severity="info",
                reason="defense-in-depth sanitizer mutated bytes (upstream bypass?)",
            )
            if decision.emit:
                alert = SecAlert(
                    alert_id=self._new_id(),
                    kind="charset_anomaly",
                    severity="info",
                    source=self.name,
                    reason=decision.reason,
                    produced_at=self._clock_iso(),
                    subject=req.client_id or req.ip,
                    request_id=req.request_id,
                    client_id=req.client_id,
                    ip=req.ip,
                )
                yield Message.new(SEC_ALERT, alert.as_dict(), producer=self.name)

        # If the classifier was a no-op (v1 fallback) or errored, surface
        # that as a debounced alert so operators see the degraded window.
        # Per §7.7 fail-open doctrine: alarm-loud, never silent.
        if classifier_reason not in {"classifier_disabled", "classifier_error", "classifier_unknown_verdict"}:
            return
        severity = "info" if classifier_reason == "classifier_disabled" else "warn"
        decision = self._debouncer.decide(
            kind="classifier_degraded",
            subject=req.client_id or req.ip,
            severity=severity,
            reason=classifier_reason,
        )
        if decision.emit:
            alert = SecAlert(
                alert_id=self._new_id(),
                kind="classifier_degraded",
                severity=severity,
                source=self.name,
                reason=decision.reason,
                produced_at=self._clock_iso(),
                subject=req.client_id or req.ip,
                request_id=req.request_id,
                client_id=req.client_id,
                ip=req.ip,
            )
            yield Message.new(SEC_ALERT, alert.as_dict(), producer=self.name)

    # ── §8.7 observability surface ────────────────────────────────
    def metrics_snapshot(self) -> dict[str, dict[tuple[str, ...], int]]:
        """Return a snapshot of agent counters keyed by metric name.

        The shape mirrors :class:`maint.scaler._LabelCounter` series:
        ``{metric_name: {label_tuple: count}}``. v1 only exposes the
        §8.7 ``sec_input_allowlist_hits_total{rule_id}`` counter; the
        Prometheus/OTel exporter (Phase 14) wires this surface into
        the scrape endpoint.
        """
        return {
            self._m_allowlist_hits.name: dict(self._m_allowlist_hits.series()),
        }

    def _emit_quarantine(
        self,
        req: QaRequest,
        *,
        classifier_reason: str,
        kind: str,
        severity: str,
        extra_reasons: tuple[str, ...] = (),
    ) -> Iterable[Message]:
        # Cap raw bytes per §7.1 BEFORE base64 encoding.
        raw = req.raw_text.encode("utf-8", errors="replace")
        cap = max(1, int(_cfg.sec_quarantine_payload_max_bytes))
        if len(raw) > cap:
            raw = raw[:cap]
        reasons: list[str] = [kind]
        if classifier_reason:
            reasons.append(classifier_reason)
        reasons.extend(extra_reasons)
        sample = QuarantineSample(
            quarantine_id=self._new_id(),
            source="qa",
            raw_bytes_b64=b64encode(raw).decode("ascii"),
            verdict="quarantine",
            reasons=reasons,
            detected_at=self._clock_iso(),
            pii_redacted=False,
            client_id=req.client_id,
            ip=req.ip,
            bytes_sha256=_sha256_hex(raw),
        )
        yield Message.new(SEC_QUARANTINE, sample.as_dict(), producer=self.name)

        # Producer-side overflow check (§7.5 binding). Done AFTER
        # publishing so the freshest sample is preserved on the wire;
        # the alert is purely a saturation signal for operators.
        overflow = self._note_quarantine_emission_locked()
        if overflow is not None:
            yield overflow

        decision = self._debouncer.decide(
            kind=kind,
            subject=req.client_id or req.ip,
            severity=severity,
            reason=f"{kind}: {classifier_reason}",
        )
        if decision.emit:
            alert = SecAlert(
                alert_id=self._new_id(),
                kind=kind,
                severity=severity,
                source=self.name,
                reason=decision.reason,
                produced_at=self._clock_iso(),
                subject=req.client_id or req.ip,
                request_id=req.request_id,
                client_id=req.client_id,
                ip=req.ip,
                evidence_ref=sample.bytes_sha256,
            )
            yield Message.new(SEC_ALERT, alert.as_dict(), producer=self.name)

    # ── Inspection helpers ────────────────────────────────────────
    def dedup_size(self) -> int:
        with self._lock:
            return len(self._dedup)

    def quarantine_inflight(self) -> int:
        """Number of recent (within storage-lag window) quarantine
        emissions tracked by the producer-side overflow guard."""
        with self._lock:
            return len(self._quarantine_inflight)

    # ── Pattern hot-reload (§7.1 binding) ─────────────────────────
    def maybe_reload_patterns(self, *, force: bool = False) -> list[Message]:
        """Public reload hook used by tests and (future) operators.

        Re-reads the YAML file (if mtime changed, or unconditionally
        when ``force=True``), atomically swaps the ruleset on
        success, and returns any SecAlert messages the swap should
        emit on the bus. Never raises — a parse failure produces a
        single `pattern_reload`/severity=`error` alert and leaves
        the previous ruleset in place.
        """
        return list(self._reload_now())

    def _maybe_poll_patterns(self, out: list[Message]) -> None:
        """Throttled mtime-watch hook called at the top of handle().

        Cost is one stat() per poll interval. The interval is the
        operator-tunable ``cfg.sec_input_pattern_reload_s`` knob;
        bounded by `_bounded` validation in config.py.
        """
        # Drain any previously-buffered alerts (e.g. produced by an
        # explicit force-reload between handle() calls).
        if self._pending_pattern_alerts:
            out.extend(self._pending_pattern_alerts)
            self._pending_pattern_alerts.clear()

        if not self._pattern_polling_enabled:
            return

        interval = max(1, int(_cfg.sec_input_pattern_reload_s))
        now = self._clock_mono()
        if now - self._last_pattern_check_mono < interval:
            return
        self._last_pattern_check_mono = now
        # Local mtime check against the agent's own ruleset (NOT the
        # module-level singleton — tests may inject a hand-built
        # ruleset that has nothing to do with the YAML on disk).
        #
        # When `rs is None` the previous load failed (startup or a
        # later reload that hit `PatternFileError`); fall through to
        # `_reload_now()` so the agent can recover once the operator
        # fixes the file. `_reload_now()` is itself fail-safe — a
        # repeated failure produces a single debounced
        # `pattern_reload`/severity=`error` alert, not a storm.
        rs = self._ruleset
        if rs is not None:
            try:
                p = _resolve_pattern_path(self._pattern_path)
                if p.stat().st_mtime_ns <= rs.mtime_ns:
                    return
            except OSError:
                return
        out.extend(self._reload_now())

    def _reload_now(self) -> Iterable[Message]:
        """Attempt a reload; yield any SecAlert messages it produced."""
        try:
            new_rs = load_ruleset(self._pattern_path)
        except PatternFileError as exc:
            decision = self._debouncer.decide(
                kind="pattern_reload",
                subject=None,
                severity="error",
                reason=f"pattern_reload_failed: {exc}",
            )
            if decision.emit:
                alert = SecAlert(
                    alert_id=self._new_id(),
                    kind="pattern_reload",
                    severity="error",
                    source=self.name,
                    reason=decision.reason,
                    produced_at=self._clock_iso(),
                )
                yield Message.new(SEC_ALERT, alert.as_dict(), producer=self.name)
            return

        with self._lock:
            prev = self._ruleset
            if prev is not None and prev.sha256 == new_rs.sha256:
                # No-op reload (file touched but bytes unchanged).
                return
            self._ruleset = new_rs

        decision = self._debouncer.decide(
            kind="pattern_reload",
            subject=None,
            severity="info",
            reason=(
                f"pattern_reload_ok: {len(new_rs.rules)} rules, "
                f"sha256={new_rs.sha256[:12]}, version={new_rs.version}"
            ),
        )
        if decision.emit:
            alert = SecAlert(
                alert_id=self._new_id(),
                kind="pattern_reload",
                severity="info",
                source=self.name,
                reason=decision.reason,
                produced_at=self._clock_iso(),
            )
            yield Message.new(SEC_ALERT, alert.as_dict(), producer=self.name)

    def current_ruleset_sha(self) -> str | None:
        """Return the sha256 of the currently-loaded ruleset, or None."""
        rs = self._ruleset
        return rs.sha256 if rs is not None else None

    # ── Internals ─────────────────────────────────────────────────
    def _note_quarantine_emission_locked(self) -> Message | None:
        """Append the current monotonic timestamp to the inflight
        deque, age out entries older than the storage-lag window,
        and return a debounced ``quarantine_overflow`` SecAlert
        message when the deque has saturated. Returns ``None``
        otherwise. Holds ``self._lock`` only for the bookkeeping
        slice; the alert envelope is built post-release.
        """
        now = self._clock_mono()
        cutoff = now - self._quarantine_window_s
        with self._lock:
            # Age out timestamps older than the lag window.
            while self._quarantine_inflight and self._quarantine_inflight[0] < cutoff:
                self._quarantine_inflight.popleft()
            self._quarantine_inflight.append(now)
            saturated = len(self._quarantine_inflight) >= self._quarantine_max
            if not saturated:
                return None
        # Saturated: emit overflow alert (debounced). Subject is empty
        # — overflow is a global producer signal, not per-subject.
        decision = self._debouncer.decide(
            kind="quarantine_overflow",
            subject=None,
            severity="error",
            reason=(
                f"producer queue saturated: "
                f"{self._quarantine_max}+ quarantines within "
                f"{self._quarantine_window_s:.1f}s "
                f"(storage.v1 may be falling behind)"
            ),
        )
        if not decision.emit:
            return None
        alert = SecAlert(
            alert_id=self._new_id(),
            kind="quarantine_overflow",
            severity="error",
            source=self.name,
            reason=decision.reason,
            produced_at=self._clock_iso(),
        )
        return Message.new(SEC_ALERT, alert.as_dict(), producer=self.name)


__all__ = ["SecInputAgent"]
