"""Phase 7 §7.2 — `sec.scrape.v1` upstream-data anomaly detector.

Subscribes ``scrape.raw`` filtered to **HTTP 200 + non-empty body**.
Failures (404 / 5xx / empty body) stay on the Phase 4.1 path (proof
flag / DLQ); the boundary test enforces no double-handling.

Detection surfaces (per §7.2):

* **Body-size delta** — sudden body-size delta vs. the rolling
  source baseline. Trips at ``cfg.sec_scrape_size_delta_pct``
  (default 200 %) — i.e. ``current > baseline_mean × (1 + pct/100)``.
* **Inflate-ratio outlier** — gzip / brotli expansion exceeding
  ``cfg.sec_scrape_inflate_ratio_max`` (default 50×). Defense
  against zip-bomb-style upstream payloads. v1 reads the wire-byte
  count from the envelope; the inflated count would come from the
  Phase 4 inflate buffer (forward hook — currently records the
  ratio when both sides are known on the payload).
* **Content-type mismatch** — header vs. magic-byte sniff (v1 uses
  a small known-prefix table; HTML / JSON / binary).
* **Encoded redirect** — ``<meta http-equiv="refresh">`` or JS
  ``location`` write inside the first 4 KiB.
* **Suspicious JS** — regex over a configurable allowlist of
  known-good script srcs from the seed corpus (v1 ships an empty
  allowlist; the loader is in place for the patcher to populate).
* **DOM structural drift (post-parse-shape)** — SimHash distance
  between the current sample's tag-path triples and the rolling
  baseline fingerprint exceeds ``cfg.sec_scrape_simhash_max_distance``
  (default 12 bits / 64). Routes to ``proof.flag{kind=parse_failed}``
  per the §7.2 verdict-routing contract — the patcher channel.

Verdict routing (binding — §7.2):

* Bytes-on-the-wire anomalies → ``sec.alert.v1``
  (operator-only; humans triage).
* Post-parse-shape anomalies → ``proof.flag{kind=parse_failed}``
  (patcher-eligible; Phase 17 ``datasource/patcher`` picks up
  selector-missing-after-DOM-shift cases).

Cold-start warm-up (§7.2 binding): the first
``cfg.sec_scrape_warmup_samples`` (default 50) successful samples
per source collect baseline statistics without emitting alerts.
Without warm-up, every newly onboarded source would generate
spurious dom_size_delta / inflate_ratio_outlier alerts on its first
request (the rolling baseline is empty → any value is an "outlier").

Baseline storage — **streaming statistic, not capped LRU** (§7.2
binding). Welford's online algorithm for (mean, variance) of body
size; bounded count-min-style bag for content-type. Memory bound
``O(constant per source)`` regardless of sample count. v1 keeps
the streaming state in process memory; Phase 8 lifts it to
``source_fingerprints`` (migration 008) on a flush interval.

Operator baseline reset (§7.2): subscribes
``maint.event.v1{kind=baseline_reset}`` and zeroes the in-memory
sketches for the targeted source, re-entering warmup.
"""
from __future__ import annotations

import hashlib
import logging
import math
import re
import threading
from base64 import b64decode
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Iterable
from uuid import uuid4

from common.config import cfg as _cfg

from ..payloads import (
    MaintEvent,
    ProofFlagKind,
    ScrapeRaw,
    SecAlert,
)
from ..topics import (
    MAINT_EVENT,
    PROOF_FLAG,
    SCRAPE_RAW,
    SEC_ALERT,
)
from ...sdk.types import Message, Topic
from ._alert import SecAlertDebouncer

_log = logging.getLogger("swarm.agents.sec.scrape")


# ── Welford streaming mean/variance ────────────────────────────────


@dataclass
class _Welford:
    """Online mean / variance per Welford (1962). O(1) per update,
    numerically stable. ``n`` counts samples; ``mean`` is the
    running mean; ``m2`` is the running sum of squared deltas.

    Variance = ``m2 / n`` (population); ``m2 / (n - 1)`` for sample
    variance. We use **population** because the baseline is the
    population we care about and sample-variance bias correction
    is meaningless once n > ~30.
    """

    n: int = 0
    mean: float = 0.0
    m2: float = 0.0

    def update(self, x: float) -> None:
        self.n += 1
        delta = x - self.mean
        self.mean += delta / self.n
        delta2 = x - self.mean
        self.m2 += delta * delta2

    @property
    def variance(self) -> float:
        return self.m2 / self.n if self.n else 0.0

    @property
    def stddev(self) -> float:
        return math.sqrt(self.variance)


# ── SimHash 64-bit over tag-path triples ───────────────────────────


_TAG_RE = re.compile(rb"<\s*([a-zA-Z][a-zA-Z0-9]*)\b([^>]*)>")
_CLASS_RE = re.compile(rb'class\s*=\s*"([^"]*)"', re.IGNORECASE)
_ID_RE = re.compile(rb'id\s*=\s*"([^"]*)"', re.IGNORECASE)


def _tag_triples(html: bytes, max_nodes: int) -> Iterable[bytes]:
    """Yield up to ``max_nodes`` ``(tag, class, id)`` triples from
    the first-pass parse of ``html``. Insertion order is preserved
    (deterministic sampling per §7.2 — ``cfg.sec_scrape_dom_fingerprint_max_nodes``
    bounds parser memory).

    We do **not** use a real HTML parser: a raw regex is robust
    against malformed markup that would crash an html.parser pass,
    and the SimHash is intentionally noisy on whitespace / attribute
    order (the patcher already absorbs that churn). For a malicious
    10⁵-deep nested HTML, the regex walks the bytes once; memory
    stays bounded by the iterator + the cap.
    """
    count = 0
    for m in _TAG_RE.finditer(html):
        if count >= max_nodes:
            break
        tag = m.group(1).lower()
        attrs = m.group(2)
        cls_m = _CLASS_RE.search(attrs)
        id_m = _ID_RE.search(attrs)
        cls = cls_m.group(1) if cls_m else b""
        ident = id_m.group(1) if id_m else b""
        yield tag + b"\x00" + cls + b"\x00" + ident
        count += 1


def _simhash64(triples: Iterable[bytes]) -> int:
    """64-bit SimHash. Each triple contributes ±1 to each of the 64
    bit positions of its 64-bit hash; positive sums → 1, non-positive
    → 0. Empty iterator returns 0 (a deliberate sentinel — the
    Hamming distance from any real fingerprint will be the popcount
    of the other side, which is bounded by 64 and clearly not a
    "match")."""
    counts = [0] * 64
    saw_any = False
    for t in triples:
        saw_any = True
        # SHA-style 64-bit fold: deterministic, salt-free so the
        # SimHash distance computation is reproducible across
        # process restarts. SHA-1 truncated to 64 bits is
        # cryptographically irrelevant here (we only need uniform
        # bit distribution); the choice is locked for the lifetime
        # of the on-disk fingerprint format. Hoisted out of the
        # earlier per-iter import (perf nit; ~5x faster on large
        # DOMs in micro-bench).
        h = hashlib.sha1(t).digest()
        v = int.from_bytes(h[:8], "big")
        for i in range(64):
            if v & (1 << i):
                counts[i] += 1
            else:
                counts[i] -= 1
    if not saw_any:
        return 0
    out = 0
    for i in range(64):
        if counts[i] > 0:
            out |= 1 << i
    return out


def _hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


# ── Per-source baseline ────────────────────────────────────────────


@dataclass
class _SourceBaseline:
    """Per-source streaming-statistic state. Memory ~constant.

    ``simhash`` is the most-recent SimHash fingerprint; we compare
    each incoming sample against it. (A true baseline would weight
    multiple historical fingerprints; v1's "last good fingerprint"
    is the doctrine's minimum — Phase 8 streaming-fingerprint
    work could lift this to a centroid SimHash without changing
    the wire contract.)
    """

    body_size: _Welford = field(default_factory=_Welford)
    inflate_ratio: _Welford = field(default_factory=_Welford)
    content_types: dict[str, int] = field(default_factory=dict)
    simhash: int | None = None
    samples_seen: int = 0

    def warmed(self, threshold: int) -> bool:
        return self.samples_seen >= threshold


# ── Helpers ────────────────────────────────────────────────────────


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _new_id() -> str:
    return uuid4().hex


_MAGIC_PREFIXES: tuple[tuple[bytes, str], ...] = (
    (b"<!DOCTYPE", "text/html"),
    (b"<html", "text/html"),
    (b"<HTML", "text/html"),
    (b"{", "application/json"),
    (b"[", "application/json"),
    (b"<?xml", "application/xml"),
    (b"\x89PNG", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
)


def _sniff_content_type(prefix: bytes) -> str | None:
    """Return a guessed MIME from a magic-byte sniff, or None when
    we have no opinion (the agent then declines to flag). v1 ships
    a small allowlist; expansion lands as a Phase 8 patcher hook."""
    head = prefix.lstrip()[:32]
    for needle, mime in _MAGIC_PREFIXES:
        if head.startswith(needle):
            return mime
    return None


_REDIRECT_RE = re.compile(
    rb'<meta[^>]+http-equiv\s*=\s*"refresh"|window\s*\.\s*location|location\s*\.\s*href',
    re.IGNORECASE,
)

# Phase 7 §7.2 — `suspicious_js` detector. Fixture / odds pages are
# mostly HTML + small inline scripts; an attacker dropping `eval`,
# `Function(...)`, dynamic `<script src>` injection from a string,
# `atob(... ) → eval`, or `document.write(...)` of remote content
# is a strong supply-chain-style attack signal. Patterns deliberately
# overlap with the prompt-injection set in `injection_patterns.yaml`
# but live here in code (no YAML hot-reload for the scrape side —
# the scrape body is HTML, not user-controlled, so the pattern set
# does not need operator agility).
_SUSPICIOUS_JS_RE = re.compile(
    rb'\beval\s*\('                              # eval(
    rb'|\bFunction\s*\(\s*[\'"]'                  # Function("..."
    rb'|\batob\s*\([^)]+\)\s*\)?\s*[;\.]?\s*eval' # atob(...) → eval
    rb'|\bdocument\s*\.\s*write\s*\('             # document.write(
    rb'|\bnew\s+Function\s*\('                    # new Function(
    rb'|\.\s*innerHTML\s*=\s*[\'"]?\s*<\s*script' # x.innerHTML = "<script"
    rb'|\bsetTimeout\s*\(\s*[\'"]'                # setTimeout("...")
    rb'|\bsetInterval\s*\(\s*[\'"]',              # setInterval("...")
    re.IGNORECASE,
)

# Match a `<script ... >...</script>` block; group(0) is the full block.
# Non-greedy on body so multi-script pages each get inspected.
_SCRIPT_BLOCK_RE = re.compile(
    rb'<\s*script\b[^>]*>.*?<\s*/\s*script\s*>',
    re.IGNORECASE | re.DOTALL,
)


# ── Agent ──────────────────────────────────────────────────────────


class SecScrapeAgent:
    """Subscribes ``scrape.raw`` + ``maint.event.v1``; emits
    ``sec.alert.v1``, ``sec.quarantine.v1``, and ``proof.flag``
    (post-parse-shape only — patcher channel).
    """

    name = "sec.scrape.v1"
    subscribes: tuple[Topic, ...] = (SCRAPE_RAW, MAINT_EVENT)
    publishes: tuple[Topic, ...] = (SEC_ALERT, PROOF_FLAG)

    def __init__(
        self,
        *,
        debouncer: SecAlertDebouncer | None = None,
        clock_iso: Callable[[], str] | None = None,
        new_id: Callable[[], str] | None = None,
    ) -> None:
        # NOTE: explicit ``is None`` check rather than ``debouncer or ...``
        # because ``SecAlertDebouncer.__len__`` returns the bucket count
        # — a freshly-injected debouncer is len()==0 and therefore
        # falsy, which would silently drop the test/operator override.
        self._debouncer = debouncer if debouncer is not None else SecAlertDebouncer(
            ttl_s=int(_cfg.sec_alert_debounce_ttl_s),
            critical_bypass=not bool(_cfg.sec_alert_critical_debounce_enabled),
            max_buckets=int(_cfg.sec_rate_max_subjects),
        )
        self._clock_iso = clock_iso or _utc_iso
        self._new_id = new_id or _new_id
        self._lock = threading.Lock()
        # Per-source baselines. Source registry (Phase 2.8) bounds
        # the active source count; we do not LRU-cap here.
        self._baselines: dict[str, _SourceBaseline] = {}
        # Pending classification queue per §7.2 bounded-state. v1
        # processes inline — pending is reserved for future async
        # scoring. We still track it for the metric.
        self._pending: "OrderedDict[str, None]" = OrderedDict()
        self._max_pending = max(1, int(_cfg.sec_scrape_max_pending))
        # Idempotency: dedup on bytes_sha256 — a redelivered raw is
        # the same payload by content. Insertion-order LRU.
        self._dedup: "OrderedDict[str, None]" = OrderedDict()
        self._dedup_max = max(1, int(_cfg.sec_scrape_max_pending))

    # ── Bus contract ──────────────────────────────────────────────
    def handle(self, msg: Message) -> Iterable[Message]:
        topic = msg.envelope.topic
        if topic == SCRAPE_RAW:
            return list(self._handle_scrape(msg))
        if topic == MAINT_EVENT:
            return list(self._handle_maint(msg))
        _log.warning("%s: unsubscribed topic %r delivered", self.name, topic)
        return ()

    # ── scrape.raw ────────────────────────────────────────────────
    def _handle_scrape(self, msg: Message) -> Iterable[Message]:
        try:
            raw = ScrapeRaw.from_dict(msg.payload)
        except (KeyError, TypeError, ValueError) as exc:
            _log.warning("%s: malformed scrape.raw: %s", self.name, exc)
            return
        # Phase 4.1 contract: only HTTP 200 + non-empty body. Failures
        # stay on the proof.flag / DLQ path.
        if raw.http_status != 200:
            return
        # Idempotency. Key on (source, sha256): two different sources
        # may legitimately deliver byte-identical content (mocksrv
        # replays the same seed across vhosts; openfootball mirrors
        # tff fixtures). Per-source dedup ensures each source's
        # baseline still updates even when the bytes happen to
        # collide cross-source.
        if raw.bytes_sha256:
            dedup_key = f"{raw.source}|{raw.bytes_sha256}"
            with self._lock:
                if dedup_key in self._dedup:
                    return
                self._dedup[dedup_key] = None
                while len(self._dedup) > self._dedup_max:
                    self._dedup.popitem(last=False)

        # Decode body once; payload has either inline b64 or a ref.
        body: bytes
        if raw.bytes_b64:
            try:
                body = b64decode(raw.bytes_b64)
            except Exception:
                _log.warning(
                    "%s: malformed bytes_b64 for source=%s; skipping",
                    self.name, raw.source,
                )
                return
        else:
            # bytes_ref means we cannot inspect the body in v1 — the
            # storage backend that resolves the ref is Phase 8. Without
            # the bytes, the only check we can do is content-type sniff
            # vs. the header — which needs the bytes too. Skip and
            # surface a debug log.
            _log.debug(
                "%s: skipping ref-only payload source=%s ref=%s",
                self.name, raw.source, raw.bytes_ref,
            )
            return
        if not body:
            return  # empty body — Phase 4.1 path

        baseline = self._baselines.setdefault(raw.source, _SourceBaseline())
        warming = not baseline.warmed(int(_cfg.sec_scrape_warmup_samples))

        # Always update streaming statistics (warmup or not).
        prev_simhash = baseline.simhash
        new_simhash = _simhash64(_tag_triples(body, int(_cfg.sec_scrape_dom_fingerprint_max_nodes)))
        prev_mean = baseline.body_size.mean
        prev_n = baseline.body_size.n
        baseline.body_size.update(float(len(body)))
        baseline.samples_seen += 1
        sniffed = _sniff_content_type(body)
        if sniffed is not None:
            baseline.content_types[sniffed] = baseline.content_types.get(sniffed, 0) + 1
        baseline.simhash = new_simhash

        if warming:
            # Emit a single "warmup" info alert on the very first
            # sample for a brand-new source. Debounced.
            if baseline.samples_seen == 1:
                yield from self._maybe_alert(
                    kind="baseline_warmup",
                    severity="info",
                    subject=raw.source,
                    reason=f"source={raw.source} entering warmup",
                )
            return

        # Warmed — run the detection branches.
        # 1. Body-size delta vs running mean.
        if prev_n > 0 and prev_mean > 0:
            pct = (len(body) - prev_mean) / prev_mean * 100.0
            if pct > float(_cfg.sec_scrape_size_delta_pct):
                yield from self._maybe_alert(
                    kind="dom_size_delta",
                    severity="warn",
                    subject=raw.source,
                    reason=(
                        f"body size {len(body)}B vs baseline_mean "
                        f"{prev_mean:.0f}B (+{pct:.1f}%)"
                    ),
                )

        # 2. Encoded redirect inside the first 4 KiB.
        if _REDIRECT_RE.search(body[:4096]):
            yield from self._maybe_alert(
                kind="encoded_redirect",
                severity="error",
                subject=raw.source,
                reason="meta-refresh or JS location write in first 4KiB",
            )

        # 3. Content-type mismatch — declared vs sniffed.
        if raw.content_type and sniffed is not None:
            declared = raw.content_type.split(";", 1)[0].strip().lower()
            if sniffed not in declared and declared not in sniffed:
                yield from self._maybe_alert(
                    kind="content_type_mismatch",
                    severity="warn",
                    subject=raw.source,
                    reason=f"declared={declared!r} sniffed={sniffed!r}",
                )

        # 4. Inflate-ratio outlier — gzip / brotli expansion exceeding
        # `cfg.sec_scrape_inflate_ratio_max` is a zip-bomb / decompression
        # DoS signal. Both byte counts must be present and positive
        # (older producers send zeros = "unknown"; the check skips).
        if raw.wire_bytes > 0 and raw.decoded_bytes > 0:
            ratio = raw.decoded_bytes / raw.wire_bytes
            limit = float(_cfg.sec_scrape_inflate_ratio_max)
            if ratio > limit:
                # Update the running ratio statistic for forensic
                # context (no alert from the streaming-statistic
                # baseline alone — the cfg cap is the operator
                # contract).
                baseline.inflate_ratio.update(ratio)
                yield from self._maybe_alert(
                    kind="inflate_ratio_outlier",
                    severity="error",
                    subject=raw.source,
                    reason=(
                        f"decoded/wire={ratio:.1f}x "
                        f"({raw.decoded_bytes}B / {raw.wire_bytes}B) "
                        f"exceeds threshold {limit:.1f}x"
                    ),
                )
            else:
                # Healthy sample — fold into the baseline.
                baseline.inflate_ratio.update(ratio)

        # 5. Suspicious JS — scan inline `<script>` blocks for known
        # malicious-payload markers (eval / Function / atob→eval /
        # document.write / innerHTML script injection). One alert per
        # debounce window per source; the matching rule snippet lands
        # in the alert reason for forensic review.
        for block_m in _SCRIPT_BLOCK_RE.finditer(body[:65536]):
            block = block_m.group(0)
            sus = _SUSPICIOUS_JS_RE.search(block)
            if sus is None:
                continue
            snippet = sus.group(0).decode("ascii", errors="replace")[:64]
            yield from self._maybe_alert(
                kind="suspicious_js",
                severity="warn",
                subject=raw.source,
                reason=f"inline script matched suspicious-JS rule: {snippet!r}",
            )
            # One alert per body — debouncer collapses repeats but
            # we also break to keep CPU bounded on adversarial
            # script-stuffed bodies (10⁴+ blocks).
            break

        # 6. SimHash structural drift → proof.flag for the patcher.
        if prev_simhash is not None:
            distance = _hamming(prev_simhash, new_simhash)
            if distance > int(_cfg.sec_scrape_simhash_max_distance):
                # Per §7.2 verdict routing: post-parse-shape anomalies
                # use proof.flag{parse_failed} so the Phase 17 patcher
                # picks them up — NOT sec.alert.v1.
                from ..payloads import truncate_proof_detail
                yield Message.new(
                    PROOF_FLAG,
                    {
                        "kind": ProofFlagKind.PARSER_EXCEPTION,
                        "detail": truncate_proof_detail(
                            f"DOM SimHash drift source={raw.source} "
                            f"distance={distance}/64 (threshold "
                            f"{int(_cfg.sec_scrape_simhash_max_distance)})"
                        ),
                        "source": raw.source,
                        "target": raw.target,
                        "agent": self.name,
                    },
                    producer=self.name,
                )

    # ── maint.event.v1 (operator overrides) ───────────────────────
    def _handle_maint(self, msg: Message) -> Iterable[Message]:
        try:
            event = MaintEvent.from_dict(msg.payload)
        except (KeyError, TypeError, ValueError) as exc:
            _log.warning("%s: malformed maint.event.v1: %s", self.name, exc)
            return
        # Filter to the kinds we own.
        if event.kind != "baseline_reset":
            return
        target = event.target
        with self._lock:
            existed = target in self._baselines
            self._baselines.pop(target, None)
        if existed:
            yield from self._maybe_alert(
                kind="baseline_reset",
                severity="info",
                subject=target,
                reason="operator reset; re-entering warmup",
            )

    # ── Alert helper ──────────────────────────────────────────────
    def _maybe_alert(
        self,
        *,
        kind: str,
        severity: str,
        subject: str,
        reason: str,
    ) -> Iterable[Message]:
        decision = self._debouncer.decide(
            kind=kind, subject=subject, severity=severity, reason=reason
        )
        if not decision.emit:
            return
        alert = SecAlert(
            alert_id=self._new_id(),
            kind=kind,
            severity=severity,
            source=self.name,
            reason=decision.reason,
            produced_at=self._clock_iso(),
            subject=subject,
        )
        yield Message.new(SEC_ALERT, alert.as_dict(), producer=self.name)

    # ── Inspection helpers ────────────────────────────────────────
    def baseline_size(self, source: str) -> int:
        with self._lock:
            b = self._baselines.get(source)
            return b.samples_seen if b else 0

    def baseline_simhash(self, source: str) -> int | None:
        with self._lock:
            b = self._baselines.get(source)
            return b.simhash if b else None


__all__ = ["SecScrapeAgent"]
