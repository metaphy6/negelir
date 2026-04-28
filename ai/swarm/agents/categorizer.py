"""Phase 4.2 — Categorizer agent.

Routes a `scrape.raw` payload into one of:

    fixture_list | match_detail | lineup | odds | irrelevant

Doctrine (ROADMAP §4.2 + AGENTS.md §2 rule 4): smallest model that
works. The default classifier is a deterministic rule chain over
URL + content-type + a tiny set of byte-level signatures (looking for
'lineup', 'kadro', 'oran', etc.). A scikit-learn LinearSVC slot is
exposed via ``set_model()`` for Phase 4.2.b once the seed corpus is
labelled — wiring is intentionally minimal here so the upgrade is
additive.

Below `cfg.categorizer_min_conf` (default 0.55) → emit a `proof.flag`
instead of `scrape.classified`. The proofreader will surface it.

LLM use is **forbidden** in this agent (ROADMAP §2.8 doctrine carries
forward). Future Phase 8 narration is a separate agent.
"""
from __future__ import annotations

import base64
import logging
from typing import Iterable, Protocol

from common.config import cfg

from ..sdk.types import Message
from .payloads import ScrapeClassified, ScrapeRaw
from .topics import PROOF_FLAG, SCRAPE_CLASSIFIED, SCRAPE_RAW

_log = logging.getLogger(__name__)


# ── Classifier interface ─────────────────────────────────────────


class Classifier(Protocol):
    """Pure function: (raw, body_text) -> (label, confidence).

    Implementations MUST be deterministic and side-effect-free.
    """

    classifier_id: str

    def classify(
        self, raw: ScrapeRaw, body_text: str
    ) -> tuple[str, float]: ...


# ── Built-in: rules baseline ─────────────────────────────────────


class RulesClassifier:
    """Deterministic rule chain. The Phase 4 floor."""

    classifier_id = "rules.v1"

    # Order matters: more specific signals first.
    _RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("lineup", ("lineup", "kadro", "ilk-11", "ilk11", "kadrolar")),
        ("odds", ("odds", "oran", "iddaa", "bulten", "bülten")),
        ("match_detail", (
            "match-detail", "macdetay", "maç-detay",
            "match/", "/maclar/", "/match/",
        )),
        ("fixture_list", (
            "fixtures", "fikstur", "fikstür", "schedule",
            "puan-durumu", "standings",
        )),
    )

    def classify(self, raw: ScrapeRaw, body_text: str) -> tuple[str, float]:
        target = (raw.target or "").lower()
        body_low = (body_text or "").lower()

        for label, needles in self._RULES:
            target_hits = sum(1 for n in needles if n in target)
            body_hits = sum(1 for n in needles if n in body_low)
            if target_hits >= 1:
                # URL-shaped signal is strong by itself.
                conf = 0.85 if body_hits else 0.7
                return label, conf
            if body_hits >= 2:
                # Two distinct keywords in the body — moderate confidence.
                return label, 0.6

        # JSON files from openfootball default to fixture lists.
        if (raw.content_type or "").startswith("application/json"):
            if any(k in body_low for k in ('"matches"', '"fixtures"', '"rounds"')):
                return "fixture_list", 0.75

        return "irrelevant", 0.4


# ── Agent ────────────────────────────────────────────────────────


class CategorizerAgent:
    name = "categorizer.v1"
    subscribes: tuple[str, ...] = (SCRAPE_RAW,)
    publishes: tuple[str, ...] = (SCRAPE_CLASSIFIED, PROOF_FLAG)

    def __init__(self, classifier: Classifier | None = None) -> None:
        self._classifier: Classifier = classifier or RulesClassifier()

    def set_model(self, classifier: Classifier) -> None:
        """Hot-swap the classifier (e.g., to a trained LinearSVC)."""
        self._classifier = classifier

    def handle(self, msg: Message) -> Iterable[Message]:
        try:
            raw = ScrapeRaw.from_dict(msg.payload)
        except (KeyError, TypeError, ValueError) as exc:
            _log.warning("%s: malformed scrape.raw: %s", self.name, exc)
            return ()

        body_text, decode_err = self._decode_body(raw)
        if decode_err is not None:
            # Mirror the processor's behaviour (Phase 4.3): a base64
            # decode failure is an upstream encoding bug and must be
            # surfaced distinctly so operators can tell it apart from
            # a low-confidence classification.
            return (
                Message.new(
                    PROOF_FLAG,
                    {
                        "kind": "decode_failed",
                        "source": raw.source,
                        "target": raw.target,
                        "detail": decode_err,
                        "agent": self.name,
                    },
                    producer=self.name,
                    trace_id=msg.envelope.trace_id,
                ),
            )
        label, conf = self._classifier.classify(raw, body_text)
        threshold = float(cfg.categorizer_min_conf)

        if conf < threshold or label == "irrelevant":
            return (
                Message.new(
                    PROOF_FLAG,
                    {
                        "kind": "low_confidence_classification",
                        "source": raw.source,
                        "target": raw.target,
                        "label": label,
                        "confidence": conf,
                        "classifier_id": self._classifier.classifier_id,
                        "threshold": threshold,
                    },
                    producer=self.name,
                    trace_id=msg.envelope.trace_id,
                ),
            )

        classified = ScrapeClassified(
            raw=raw,
            label=label,
            confidence=conf,
            classifier_id=self._classifier.classifier_id,
        )
        return (
            Message.new(
                SCRAPE_CLASSIFIED,
                classified.as_dict(),
                producer=self.name,
                trace_id=msg.envelope.trace_id,
            ),
        )

    @staticmethod
    def _decode_body(raw: ScrapeRaw) -> tuple[str, str | None]:
        """Returns ``(body, error)``. ``error`` is ``None`` on success.

        Empty inline payload is *not* an error — it simply means the
        producer used ``bytes_ref`` (Phase 4.1's content-addressed
        path). Aligned with ``ProcessorAgentBase._decode``.
        """
        if not raw.bytes_b64:
            return "", None
        try:
            data = base64.b64decode(raw.bytes_b64, validate=True)
        except (ValueError, base64.binascii.Error) as exc:
            return "", f"base64 decode failed: {exc}"
        # Best-effort decode; the categorizer only needs string-shaped
        # signal. Bytes that cannot be decoded as utf-8 fall back to
        # latin-1 (lossless) so substring tests still work.
        try:
            return data.decode("utf-8"), None
        except UnicodeDecodeError:
            return data.decode("latin-1", errors="replace"), None


__all__ = ["CategorizerAgent", "Classifier", "RulesClassifier"]
